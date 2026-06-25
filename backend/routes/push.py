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

PUSH_BASE_URL = "https://integrations.emergentagent.com"
PUSH_KEY = os.environ.get("EMERGENT_PUSH_KEY", "placeholder")

# Module-level shared async client. Kept alive across the FastAPI lifespan
# so connection pooling pays off.
_client = httpx.AsyncClient(
    base_url=PUSH_BASE_URL,
    headers={"X-Push-Key": PUSH_KEY},
    timeout=10.0,
)

router = APIRouter()


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
) -> None:
    """Fire a push notification to one or many user_ids.

    `data` must include `title` and `message`. Optional keys: `subtext`,
    `image_url` (HTTPS), `action_url` (used as deep-link on tap).

    NEVER raises. Failures are logged-and-swallowed so callers (chat post,
    broadcast, etc.) never break on a push relay hiccup.
    """
    if not recipients:
        return
    if "title" not in data or "message" not in data:
        logger.warning("send_push: missing title/message in payload")
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
