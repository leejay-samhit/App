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

import hashlib
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.security import get_current_user, require_admin_role

logger = logging.getLogger(__name__)

PUSH_BASE_URL = os.environ.get("EMERGENT_PUSH_BASE_URL", "https://integrations.emergentagent.com")
PUSH_KEY = os.environ.get("EMERGENT_PUSH_KEY", "placeholder")
KEY_CONFIGURED = bool(PUSH_KEY) and PUSH_KEY != "placeholder"

# ── Android notification channels (Sep 2026 root-cause fix) ────────────
# Android FREEZES a channel's importance/sound the moment it is created. The
# original "default" / "chat" channels were created on devices by earlier
# builds, so raising `importance` in app code afterwards has NO effect — the
# OS keeps whatever the channel was born with (and whatever the user later
# toggled). That is exactly how a push can be accepted by FCM, handed to the
# app, written to the in-app bell, and still never appear in the tray.
#
# The only supported migration is a NEW channel id. Every send is therefore
# routed to a v2 channel, created at MAX importance in app/_layout.tsx, and
# the legacy ids are transparently remapped so no call-site has to change.
CHANNEL_ORDERS = "orders_v2"
CHANNEL_CHAT = "chat_v2"
CHANNEL_BY_CATEGORY = {
    "chats": CHANNEL_CHAT,
    "orders": CHANNEL_ORDERS,
    "offers": CHANNEL_ORDERS,
    "login_alerts": CHANNEL_ORDERS,
    "vendor_new_order": CHANNEL_ORDERS,
}
LEGACY_CHANNEL_MAP = {"chat": CHANNEL_CHAT, "default": CHANNEL_ORDERS}

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
    # Sep 2026 — diagnostics only. Stripped before the relay call; they exist
    # so "no tray notification" can be told apart from "this phone never had
    # a usable token" (Expo Go, emulator, permission denied, …).
    app_ownership: Optional[str] = Field(default=None, max_length=32)
    is_device: Optional[bool] = None
    os_version: Optional[str] = Field(default=None, max_length=32)
    device_name: Optional[str] = Field(default=None, max_length=64)
    app_version: Optional[str] = Field(default=None, max_length=32)
    permission_status: Optional[str] = Field(default=None, max_length=24)


def token_fingerprint(token: str) -> str:
    """A stable, non-reversible id for a device token.

    The playbook forbids storing device tokens (SuprSend owns them), but
    without ANY identifier it is impossible to prove the backend is targeting
    the phone that is actually in the owner's hand. A sha256 prefix plus the
    last 6 characters is enough to compare across registrations and is
    useless to an attacker.
    """
    if not token:
        return ""
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
    return f"{digest}…{token[-6:]} ({len(token)} chars)"


async def _record_device(body: RegisterPushBody, status: str, upstream: Dict[str, Any]) -> None:
    """Device registration evidence — one row per (user, device token).

    Keeps the whole history so multiple devices per user, token rotation and
    logout/login are all visible, and stamps `users.push_registration` for
    the quick check the rest of the app already reads.
    """
    from core.db import db
    from core.utils import now_utc

    ts = now_utc().isoformat()
    fp = token_fingerprint(body.device_token)
    await db.push_devices.update_one(
        {"user_id": body.user_id, "token_fingerprint": fp},
        {
            "$set": {
                "platform": body.platform,
                "status": status,
                "upstream_status": upstream.get("status"),
                "upstream_body": str(upstream.get("body") or "")[:300],
                "key_configured": KEY_CONFIGURED,
                "app_ownership": body.app_ownership,
                "is_device": body.is_device,
                "os_version": body.os_version,
                "device_name": body.device_name,
                "app_version": body.app_version,
                "permission_status": body.permission_status,
                "last_seen_at": ts,
            },
            "$setOnInsert": {"id": str(uuid.uuid4()), "first_seen_at": ts},
            "$inc": {"registrations": 1},
        },
        upsert=True,
    )
    await db.users.update_one(
        {"id": body.user_id},
        {"$set": {"push_registration": {
            "status": status,
            "platform": body.platform,
            "token_fingerprint": fp,
            "app_ownership": body.app_ownership,
            "is_device": body.is_device,
            "permission_status": body.permission_status,
            "upstream_status": upstream.get("status"),
            "at": ts,
        }}},
    )


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

    # Only the three fields the relay contract defines go upstream.
    relay_body = {
        "user_id": body.user_id,
        "platform": body.platform,
        "device_token": body.device_token,
    }
    try:
        resp = await _client.post("/api/v1/push/users/register", json=relay_body)
    except httpx.HTTPError as e:
        logger.warning(f"register-push relay failed: {e}")
        # Don't 5xx the caller — push registration is best-effort.
        await _record_device(body, "deferred_upstream_unreachable", {"status": None, "body": str(e)})
        return {"status": "deferred", "reason": "upstream_unreachable"}

    upstream = {"status": resp.status_code, "body": resp.text[:300]}
    if resp.status_code == 401:
        # During local dev the key is the literal "placeholder". Don't 500
        # the client; just report the deferred status so the FE still
        # remembers to retry later.
        logger.info("register-push: EMERGENT_PUSH_KEY missing/invalid (expected in dev)")
        await _record_device(body, "deferred_key_missing", upstream)
        return {"status": "deferred", "reason": "key_missing"}
    if resp.status_code >= 500:
        logger.warning(f"register-push: upstream {resp.status_code} {resp.text[:200]}")
        await _record_device(body, "deferred_upstream_5xx", upstream)
        return {"status": "deferred", "reason": "upstream_5xx"}
    if 400 <= resp.status_code < 500:
        # Surface 4xx as a soft warning — don't break the client.
        logger.warning(f"register-push: upstream {resp.status_code} {resp.text[:200]}")
        await _record_device(body, f"deferred_upstream_{resp.status_code}", upstream)
        return {"status": "deferred", "reason": f"upstream_{resp.status_code}"}
    await _record_device(body, "registered", upstream)
    return {"status": "registered", "token_fingerprint": token_fingerprint(body.device_token)}


async def _log_send(entry: Dict[str, Any]) -> None:
    """Persist one push attempt. Without this the pipeline is a black box:
    a database notification row proves NOTHING about tray delivery."""
    try:
        from core.db import db
        await db.push_log.insert_one(entry)
    except Exception as e:  # pragma: no cover — logging must never break a send
        logger.info(f"push_log write skipped: {e}")


class ClientPushStatus(BaseModel):
    """What the PHONE experienced. Reported even (especially) when it failed."""
    stage: str = Field(..., max_length=40)      # permission_denied | no_token | token_error | not_a_device | ok
    detail: Optional[str] = Field(default=None, max_length=300)
    permission_status: Optional[str] = Field(default=None, max_length=24)
    can_ask_again: Optional[bool] = None
    platform: Optional[str] = Field(default=None, max_length=16)
    app_ownership: Optional[str] = Field(default=None, max_length=32)
    is_device: Optional[bool] = None
    os_version: Optional[str] = Field(default=None, max_length=32)
    device_name: Optional[str] = Field(default=None, max_length=64)
    app_version: Optional[str] = Field(default=None, max_length=32)


@router.post("/push/client-status")
async def push_client_status(
    body: ClientPushStatus,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """The phone tells us why it could NOT register.

    Without this, a device that never obtains an FCM token (notification
    permission refused, a Dual-App / cloned instance with no Play Services
    binding, an emulator, a Firebase init failure) is indistinguishable from
    a server that never sent — both just look like "no device registered".
    Recorded against the account so Admin → Push diagnostics can name the
    real blocker instead of guessing.
    """
    from core.db import db
    from core.utils import now_utc

    ts = now_utc().isoformat()
    key = f"client:{body.platform or 'unknown'}:{body.device_name or 'device'}"
    await db.push_devices.update_one(
        {"user_id": user["id"], "token_fingerprint": key},
        {
            "$set": {
                "platform": body.platform,
                "status": f"client_{body.stage}",
                "client_stage": body.stage,
                "client_detail": body.detail,
                "permission_status": body.permission_status,
                "can_ask_again": body.can_ask_again,
                "app_ownership": body.app_ownership,
                "is_device": body.is_device,
                "os_version": body.os_version,
                "device_name": body.device_name,
                "app_version": body.app_version,
                "upstream_status": None,
                "last_seen_at": ts,
            },
            "$setOnInsert": {"id": str(uuid.uuid4()), "first_seen_at": ts},
            "$inc": {"reports": 1},
        },
        upsert=True,
    )
    # Only overwrite the account-level summary while there is no WORKING
    # registration — a good token must never be masked by a clone's failure.
    current = (user.get("push_registration") or {}).get("status")
    if current != "registered":
        await db.users.update_one(
            {"id": user["id"]},
            {"$set": {"push_registration": {
                "status": f"client_{body.stage}",
                "platform": body.platform,
                "client_detail": body.detail,
                "permission_status": body.permission_status,
                "app_ownership": body.app_ownership,
                "is_device": body.is_device,
                "at": ts,
            }}},
        )
    return {"ok": True, "recorded": body.stage}


async def send_push(
    recipients: List[str],
    data: Dict[str, Any],
    idempotency_key: Optional[str] = None,
    category: Optional[str] = None,
) -> str:
    """Fire a push notification to one or many user_ids.

    `data` must include `title` and `message`. Optional keys: `subtext`,
    `image_url` (HTTPS), `action_url` (used as deep-link on tap),
    `channel_id` (Android channel — filled in automatically from `category`
    when the caller omits it, and legacy ids are remapped to the v2 channels).

    `category` opts the send into the user's notification preferences
    (Profile → Notification settings): "orders" | "chats" | "offers" |
    "login_alerts" | "vendor_new_order". Recipients who switched that
    category off are dropped before the relay call. Omit it for
    must-deliver messages (e.g. the admin's own test push).

    NEVER raises. Failures are logged-and-swallowed so callers (chat post,
    broadcast, etc.) never break on a push relay hiccup — but EVERY attempt
    is now recorded in `push_log` with the exact relay status and body, so
    CREATED / SENT TO RELAY / ACCEPTED / REJECTED are separate, provable
    states instead of an assumption.
    """
    from core.utils import now_utc

    requested = list(dict.fromkeys([r for r in (recipients or []) if r]))
    entry: Dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "created_at": now_utc().isoformat(),
        "stage": "created",
        "title": str(data.get("title") or "")[:120],
        "message": str(data.get("message") or "")[:200],
        "category": category,
        "idempotency_key": idempotency_key,
        "requested_recipients": len(requested),
        "recipients": requested[:20],
        "key_configured": KEY_CONFIGURED,
    }

    if not requested:
        entry.update({"stage": "skipped", "result": "no_recipients"})
        await _log_send(entry)
        return "no_recipients"
    if "title" not in data or "message" not in data:
        logger.warning("send_push: missing title/message in payload")
        entry.update({"stage": "skipped", "result": "bad_payload"})
        await _log_send(entry)
        return "bad_payload"
    if category:
        requested = await filter_by_prefs(requested, category)
        if not requested:
            entry.update({"stage": "skipped", "result": "opted_out"})
            await _log_send(entry)
            return "opted_out"
    # Chunk over 100 — playbook hard limit.
    if len(requested) > 100:
        for i in range(0, len(requested), 100):
            await send_push(requested[i:i + 100], data, idempotency_key=idempotency_key)
        entry.update({"stage": "chunked", "result": "chunked"})
        await _log_send(entry)
        return "chunked"

    # Android channel routing. An explicit legacy id is remapped, an absent
    # one is derived from the category — so every payload names a v2 channel
    # that was born at MAX importance.
    payload_data = dict(data)
    channel = payload_data.get("channel_id")
    channel = LEGACY_CHANNEL_MAP.get(channel, channel) if channel else None
    if not channel:
        channel = CHANNEL_BY_CATEGORY.get(category or "", CHANNEL_ORDERS)
    payload_data["channel_id"] = channel
    entry["channel_id"] = channel
    entry["sent_recipients"] = len(requested)

    payload: Dict[str, Any] = {"recipients": requested, "data": payload_data}
    if idempotency_key:
        payload["$idempotency_key"] = idempotency_key

    entry["stage"] = "sent_to_relay"
    try:
        resp = await _client.post("/api/v1/push/trigger", json=payload)
    except httpx.HTTPError as e:
        logger.warning(f"send_push: relay error {e}")
        entry.update({"stage": "rejected", "result": "relay_unreachable", "error": str(e)[:300]})
        await _log_send(entry)
        return "relay_unreachable"

    entry["http_status"] = resp.status_code
    entry["upstream_body"] = resp.text[:400]
    if resp.status_code == 401:
        # Expected in dev — placeholder key.
        logger.info("send_push: EMERGENT_PUSH_KEY missing/invalid (dev placeholder)")
        entry.update({"stage": "rejected", "result": "key_missing"})
        await _log_send(entry)
        return "key_missing"
    if resp.status_code >= 400:
        logger.warning(f"send_push: upstream {resp.status_code} {resp.text[:300]}")
        entry.update({"stage": "rejected", "result": f"upstream_{resp.status_code}"})
        await _log_send(entry)
        return f"upstream_{resp.status_code}"
    entry.update({"stage": "accepted", "result": "sent"})
    await _log_send(entry)
    return "sent"


# ── Test helper for super admins ───────────────────────────────────────

class TestPushBody(BaseModel):
    title: str = Field(default="Slangcart Test")
    message: str = Field(default="If you see this, push notifications are wired up.")
    # Sep 2026 — target another account (by email) so the owner can fire a
    # test at the exact phone that is failing, not only at their own.
    target_email: Optional[str] = Field(default=None, max_length=200)
    channel_id: Optional[str] = Field(default=None, max_length=40)


@router.post("/push/test")
async def push_test(
    body: TestPushBody,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    """Super admin smoke test — sends a push and returns the FULL evidence:
    the relay HTTP status, the relay's response body, whether the relay key
    is injected, and the target device's registration record. This is the
    proof that separates "server didn't send" from "Firebase rejected" from
    "this phone never registered"."""
    from core.db import db

    target = admin
    if body.target_email:
        found = await db.users.find_one(
            {"email": body.target_email.strip().lower()}, {"_id": 0},
        )
        if not found:
            raise HTTPException(status_code=404, detail="No user with that email")
        target = found

    relay = await send_push(
        recipients=[target["id"]],
        data={
            "title": body.title,
            "message": body.message,
            "channel_id": body.channel_id or CHANNEL_ORDERS,
            "action_url": "/notifications",
        },
        idempotency_key=f"push-test-{target['id']}-{uuid.uuid4().hex[:8]}",
    )
    log = await db.push_log.find({}, {"_id": 0}).sort("created_at", -1).limit(1).to_list(1)
    devices = await db.push_devices.find(
        {"user_id": target["id"]}, {"_id": 0},
    ).sort("last_seen_at", -1).to_list(20)
    reg = target.get("push_registration") or {}
    registered = [d for d in devices if d.get("status") == "registered"]
    blocked = [d for d in devices if str(d.get("status") or "").startswith("client_")]

    if not KEY_CONFIGURED:
        hint = (
            "This environment has no push relay key yet (EMERGENT_PUSH_KEY is still "
            "'placeholder'), so nothing was sent to Firebase. The key is injected "
            "automatically when you Publish/Deploy — test again on the deployed build."
        )
    elif blocked and not registered:
        b = blocked[0]
        hint = (
            f"This phone could not get a Firebase token: {b.get('client_stage')} — "
            f"{b.get('client_detail') or 'no detail'}. "
            "Cloned 'Dual App' instances and emulators cannot receive push at all; "
            "if it says permission_denied, turn notifications on in Android Settings → "
            "Apps → Slangcart → Notifications."
        )
    elif not registered:
        hint = (
            "The relay key is live but this account has no successfully registered "
            "device. Open the INSTALLED app (not Expo Go, not the web preview), allow "
            "notifications, then retry."
        )
    elif reg.get("app_ownership") == "expo":
        hint = (
            "This device registered from Expo Go, which cannot receive push at all. "
            "Install the generated APK/AAB build and retry."
        )
    elif relay != "sent":
        hint = (
            f"The relay REJECTED the send ({relay}). See relay_http_status and "
            f"relay_response below — that is Firebase's / SuprSend's own answer."
        )
    else:
        hint = (
            "Accepted by the relay. If it still does not appear in the tray, the phone "
            "either has the channel muted or the app was force-stopped — check "
            "Android Settings → Apps → Slangcart → Notifications → "
            "'Orders & delivery' / 'Chat messages'."
        )
    last = log[0] if log else {}
    return {
        "ok": relay == "sent",
        "sent_to": target["id"],
        "sent_to_email": target.get("email"),
        "relay": relay,
        "relay_http_status": last.get("http_status"),
        "relay_response": last.get("upstream_body"),
        "channel_id": last.get("channel_id"),
        "stage": last.get("stage"),
        "key_configured": KEY_CONFIGURED,
        "device_registration": reg or None,
        "devices": devices,
        "hint": hint,
    }


# ── Diagnostics (Sep 2026) ─────────────────────────────────────────────

@router.get("/admin/push/diagnostics")
async def push_diagnostics(
    limit: int = 50,
    _admin: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    """The whole pipeline in one response: relay key state, device
    registrations, and the last N send attempts with the exact upstream
    status and body. Nothing here is inferred — every field is what the
    relay actually answered."""
    from core.db import db
    from core.utils import now_utc

    limit = max(1, min(int(limit or 50), 300))
    stages = await db.push_log.aggregate([
        {"$group": {"_id": "$stage", "n": {"$sum": 1}}},
    ]).to_list(20)
    results = await db.push_log.aggregate([
        {"$group": {"_id": "$result", "n": {"$sum": 1}}},
    ]).to_list(40)
    recent = await db.push_log.find({}, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    devices = await db.push_devices.find({}, {"_id": 0}).sort("last_seen_at", -1).limit(100).to_list(100)
    dev_status = await db.push_devices.aggregate([
        {"$group": {"_id": "$status", "n": {"$sum": 1}}},
    ]).to_list(20)

    # Live reachability probe — proves whether the relay host answers at all
    # from this pod, without sending a notification to anybody.
    probe: Dict[str, Any] = {}
    try:
        r = await _client.post("/api/v1/push/trigger", json={"recipients": [], "data": {}})
        probe = {"reachable": True, "http_status": r.status_code, "body": r.text[:200]}
    except httpx.HTTPError as e:
        probe = {"reachable": False, "error": str(e)[:200]}

    accepted = sum(s["n"] for s in stages if s["_id"] == "accepted")
    rejected = sum(s["n"] for s in stages if s["_id"] == "rejected")
    registered = [d for d in devices if d.get("status") == "registered"]
    blockers = [
        {
            "user_id": d.get("user_id"),
            "platform": d.get("platform"),
            "device_name": d.get("device_name"),
            "stage": d.get("client_stage"),
            "detail": d.get("client_detail"),
            "permission_status": d.get("permission_status"),
            "app_ownership": d.get("app_ownership"),
            "last_seen_at": d.get("last_seen_at"),
        }
        for d in devices if str(d.get("status") or "").startswith("client_")
    ]
    return {
        "key_configured": KEY_CONFIGURED,
        "relay_base_url": PUSH_BASE_URL,
        "channels": {
            "orders": CHANNEL_ORDERS,
            "chat": CHANNEL_CHAT,
            "legacy_remap": LEGACY_CHANNEL_MAP,
            "note": (
                "Android freezes a channel's importance at creation. The v2 ids "
                "were introduced because the original 'default'/'chat' channels "
                "already existed on devices at a lower importance, which silences "
                "the tray while the in-app bell keeps working."
            ),
        },
        "totals": {
            "attempts": sum(s["n"] for s in stages),
            "accepted_by_relay": accepted,
            "rejected": rejected,
            "by_stage": {s["_id"]: s["n"] for s in stages},
            "by_result": {r["_id"]: r["n"] for r in results},
        },
        "devices": {
            "total": len(devices),
            "registered": len(registered),
            "by_status": {d["_id"]: d["n"] for d in dev_status},
            "rows": devices,
        },
        # Failures the PHONE reported — permission refused, a cloned/Dual-App
        # instance that cannot get an FCM token, an emulator, a broken
        # Firebase init. Without these, "no device registered" is ambiguous.
        "device_blockers": blockers,
        "relay_probe": probe,
        "recent_sends": recent,
        "generated_at": now_utc().isoformat(),
        "verdict": (
            "relay_key_missing" if not KEY_CONFIGURED
            else "device_cannot_register" if (not registered and blockers)
            else "no_device_registered" if not registered
            else "relay_rejecting" if rejected and not accepted
            else "pipeline_healthy" if accepted
            else "nothing_sent_yet"
        ),
    }


@router.get("/admin/push/diagnostics/user")
async def push_diagnostics_user(
    email: str,
    _admin: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    """One account's push truth: its devices and its last 50 attempts."""
    from core.db import db

    user = await db.users.find_one({"email": email.strip().lower()}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="No user with that email")
    devices = await db.push_devices.find(
        {"user_id": user["id"]}, {"_id": 0},
    ).sort("last_seen_at", -1).to_list(50)
    sends = await db.push_log.find(
        {"recipients": user["id"]}, {"_id": 0},
    ).sort("created_at", -1).limit(50).to_list(50)
    return {
        "user": {
            "id": user["id"], "email": user.get("email"), "name": user.get("name"),
            "notification_prefs": normalise_prefs(user.get("notification_prefs")),
            "push_registration": user.get("push_registration"),
        },
        "devices": devices,
        "recent_sends": sends,
        "in_app_notifications": await db.notifications.count_documents({"user_id": user["id"]}),
    }
