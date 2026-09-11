"""
Push Notifications — Emergent managed push relay (SuprSend backend).

Endpoints:
  - POST /api/register-push    → relays device token to provider
  - POST /api/push/test        → super-admin only, send a test push to self

Helper:
  - send_push(recipients, data, idempotency_key=None) → fire from event handlers.

CRITICAL (per the integration playbook):
  - Backend ONLY calls integrations.emergentagent.com — never the frontend.
  - EMERGENT_PUSH_KEY is provided by the deployer at build/deploy time.
    During local dev we use the literal string "placeholder" which causes
    upstream 401s; THIS IS EXPECTED and the helper swallows the failure
    so it never blocks the primary operation (e.g. posting a chat msg).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.security import get_current_user, require_admin_role

logger = logging.getLogger(__name__)

PUSH_BASE_URL = os.environ.get("EMERGENT_PUSH_BASE_URL", "https://integrations.emergentagent.com")
PUSH_KEY = os.environ.get("EMERGENT_PUSH_KEY", "placeholder")

# Module-level shared async client. Kept alive across the FastAPI lifespan
# so connection pooling pays off.
_client = httpx.AsyncClient(
    base_url=PUSH_BASE_URL,
    headers={"X-Push-Key": PUSH_KEY},
    timeout=10.0,
)

router = APIRouter()


# ── Notification preferences ──────────────────────────────────────────
# Jun 2026 — users pick which pushes they want in Profile → Notification
# settings. Everything is ON by default (an empty/absent prefs dict means
# "send me everything"), so existing users keep getting their order updates.
PUSH_CATEGORIES = ("orders", "chats", "offers", "login_alerts", "vendor_new_order")
DEFAULT_PREFS: Dict[str, bool] = {k: True for k in PUSH_CATEGORIES}


def normalise_prefs(raw: Any) -> Dict[str, bool]:
    prefs = dict(DEFAULT_PREFS)
    if isinstance(raw, dict):
        for k in PUSH_CATEGORIES:
            if k in raw:
                prefs[k] = bool(raw[k])
    return prefs


async def filter_by_prefs(user_ids: List[str], category: str) -> List[str]:
    """Drop recipients who switched this notification category off."""
    from core.db import db  # local import — keeps this module import-light

    if category not in PUSH_CATEGORIES:
        return user_ids
    ids = list(dict.fromkeys([u for u in user_ids if u]))
    if not ids:
        return []
    opted_out = set()
    async for u in db.users.find(
        {"id": {"$in": ids}, f"notification_prefs.{category}": False},
        {"_id": 0, "id": 1},
    ):
        opted_out.add(u["id"])
    return [u for u in ids if u not in opted_out]


class NotificationPrefsBody(BaseModel):
    orders: Optional[bool] = None
    chats: Optional[bool] = None
    offers: Optional[bool] = None
    login_alerts: Optional[bool] = None
    vendor_new_order: Optional[bool] = None


@router.get("/me/notification-prefs")
async def get_notification_prefs(user: Dict[str, Any] = Depends(get_current_user)):
    return {
        "prefs": normalise_prefs(user.get("notification_prefs")),
        "is_vendor": bool(user.get("is_vendor_approved") or user.get("vendor_status") == "approved"),
    }


@router.put("/me/notification-prefs")
async def update_notification_prefs(
    body: NotificationPrefsBody,
    user: Dict[str, Any] = Depends(get_current_user),
):
    from core.db import db

    current = normalise_prefs(user.get("notification_prefs"))
    for k, v in body.model_dump(exclude_none=True).items():
        current[k] = bool(v)
    await db.users.update_one({"id": user["id"]}, {"$set": {"notification_prefs": current}})
    return {"ok": True, "prefs": current}


class RegisterPushBody(BaseModel):
    user_id: str = Field(..., min_length=1)
    platform: str = Field(..., min_length=2, max_length=16)  # "android" | "ios" | "web"
    device_token: str = Field(..., min_length=1)


@router.post("/register-push", status_code=201)
async def register_push(
    body: RegisterPushBody,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Frontend posts the native FCM/APNs token here right after login.

    We re-check the body's user_id against the caller's JWT to prevent
    a malicious client from registering tokens under another user.
    """
    if body.user_id != user.get("id"):
        raise HTTPException(status_code=403, detail="user_id mismatch with JWT")

    try:
        resp = await _client.post(
            "/api/v1/push/users/register",
            json=body.model_dump(),
        )
    except httpx.HTTPError as e:
        logger.warning(f"register-push relay failed: {e}")
        # Don't 5xx the caller — push registration is best-effort.
        return {"status": "deferred", "reason": "upstream_unreachable"}

    if resp.status_code == 401:
        # During local dev the key is the literal "placeholder". Don't 500
        # the client; just report the deferred status so the FE still
        # remembers to retry later.
        logger.info("register-push: EMERGENT_PUSH_KEY missing/invalid (expected in dev)")
        return {"status": "deferred", "reason": "key_missing"}
    if resp.status_code >= 500:
        logger.warning(f"register-push: upstream {resp.status_code} {resp.text[:200]}")
        return {"status": "deferred", "reason": "upstream_5xx"}
    if 400 <= resp.status_code < 500:
        # Surface 4xx as a soft warning — don't break the client.
        logger.warning(f"register-push: upstream {resp.status_code} {resp.text[:200]}")
        return {"status": "deferred", "reason": f"upstream_{resp.status_code}"}
    return {"status": "registered"}


async def send_push(
    recipients: List[str],
    data: Dict[str, Any],
    idempotency_key: Optional[str] = None,
    category: Optional[str] = None,
) -> None:
    """Fire a push notification to one or many user_ids.

    `data` must include `title` and `message`. Optional keys: `subtext`,
    `image_url` (HTTPS), `action_url` (used as deep-link on tap),
    `channel_id` (Android channel, e.g. "chat").

    `category` opts the send into the user's notification preferences
    (Profile → Notification settings): "orders" | "chats" | "offers" |
    "login_alerts" | "vendor_new_order". Recipients who switched that
    category off are dropped before the relay call. Omit it for
    must-deliver messages (e.g. the admin's own test push).

    NEVER raises. Failures are logged-and-swallowed so callers (chat post,
    broadcast, etc.) never break on a push relay hiccup.
    """
    if not recipients:
        return
    if "title" not in data or "message" not in data:
        logger.warning("send_push: missing title/message in payload")
        return
    if category:
        recipients = await filter_by_prefs(recipients, category)
        if not recipients:
            return
    # Chunk over 100 — playbook hard limit.
    if len(recipients) > 100:
        for i in range(0, len(recipients), 100):
            await send_push(recipients[i:i + 100], data, idempotency_key=idempotency_key)
        return

    payload: Dict[str, Any] = {"recipients": recipients, "data": data}
    if idempotency_key:
        payload["$idempotency_key"] = idempotency_key

    try:
        resp = await _client.post("/api/v1/push/trigger", json=payload)
    except httpx.HTTPError as e:
        logger.warning(f"send_push: relay error {e}")
        return

    if resp.status_code == 401:
        # Expected in dev — placeholder key.
        logger.info("send_push: EMERGENT_PUSH_KEY missing/invalid (dev placeholder)")
        return
    if resp.status_code >= 400:
        logger.warning(f"send_push: upstream {resp.status_code} {resp.text[:300]}")
        return


# ── Test helper for super admins ───────────────────────────────────────

class TestPushBody(BaseModel):
    title: str = Field(default="Slangcart Test")
    message: str = Field(default="If you see this, push notifications are wired up.")


@router.post("/push/test")
async def push_test(
    body: TestPushBody,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    """Super admin smoke test — sends a push to themselves so they can
    verify the relay end-to-end after deploying."""
    await send_push(
        recipients=[admin["id"]],
        data={"title": body.title, "message": body.message},
        idempotency_key=f"push-test-{admin['id']}",
    )
    return {"ok": True, "sent_to": admin["id"]}
