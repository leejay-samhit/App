"""Device login history + new-device alerts (Sep 2026, owner request).

Every successful sign-in is written to `login_history` with the device
fingerprint the app already sends (`X-Device-FP`, see frontend/src/device.ts),
a human device label (`X-Device-Name`) and the IP. The session id is stored
alongside so the user can sign a specific device out from the app.

When a fingerprint the account has never used before appears, the user gets an
in-app notification and (best-effort) a push — the "alert" half of the feature.
The very first login on an account is NOT alerted (that's the device they are
holding).
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from fastapi import Request

from .db import db
from .notifications import create_notification
from .utils import now_utc

logger = logging.getLogger(__name__)

MAX_HISTORY_PER_USER = 50


def client_ip(request: Request) -> Optional[str]:
    fwd = request.headers.get("x-forwarded-for") or ""
    if fwd:
        return fwd.split(",")[0].strip() or None
    return request.client.host if request.client else None


def _device_label(request: Request) -> str:
    """Best available human name for the device."""
    name = (request.headers.get("x-device-name") or "").strip()
    if name:
        return name[:80]
    ua = (request.headers.get("user-agent") or "").strip()
    if not ua:
        return "Unknown device"
    low = ua.lower()
    for needle, label in (
        ("iphone", "iPhone"), ("ipad", "iPad"), ("android", "Android device"),
        ("windows", "Windows computer"), ("macintosh", "Mac"), ("linux", "Linux computer"),
    ):
        if needle in low:
            return label
    return ua[:80]


def _platform(request: Request) -> str:
    fp = (request.headers.get("x-device-fp") or "").lower()
    for p in ("ios", "android", "web"):
        if fp.startswith(p):
            return p
    ua = (request.headers.get("user-agent") or "").lower()
    if "iphone" in ua or "ipad" in ua:
        return "ios"
    if "android" in ua:
        return "android"
    return "web"


async def record_login(
    user: Dict[str, Any],
    request: Request,
    sid: str,
    method: str = "password",
) -> Dict[str, Any]:
    """Write one history row; alert the user when the device is new.

    Never raises — a logging failure must not break sign-in.
    """
    try:
        user_id = user["id"]
        fp = (request.headers.get("x-device-fp") or "").strip() or None
        label = _device_label(request)
        ip = client_ip(request)
        # "New device" = a fingerprint (or, with none, a device label) this
        # account has not signed in from before.
        prev_query: Dict[str, Any] = {"user_id": user_id}
        prev_query.update({"device_fp": fp} if fp else {"device_label": label})
        seen_before = await db.login_history.find_one(prev_query, {"_id": 0, "id": 1})
        had_any = await db.login_history.find_one({"user_id": user_id}, {"_id": 0, "id": 1})
        doc = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "email": user.get("email"),
            "session_id": sid,
            "device_fp": fp,
            "device_label": label,
            "platform": _platform(request),
            "user_agent": (request.headers.get("user-agent") or "")[:300],
            "ip": ip,
            "method": method,
            "is_new_device": bool(had_any and not seen_before),
            "created_at": now_utc().isoformat(),
        }
        await db.login_history.insert_one(doc)
        # One live session per device: drop the sids this same device used
        # before, so repeated logins on one phone can't push OTHER devices
        # out of the 10-slot session pool (that looked like a random logout).
        if fp:
            stale = await db.login_history.find(
                {"user_id": user_id, "device_fp": fp, "session_id": {"$nin": [sid, None]}},
                {"_id": 0, "session_id": 1},
            ).to_list(60)
            old_sids = [s["session_id"] for s in stale if s.get("session_id") and s["session_id"] != sid]
            if old_sids:
                await db.users.update_one(
                    {"id": user_id}, {"$pullAll": {"active_session_ids": old_sids}},
                )
        # Keep the collection lean per user.
        extra = await db.login_history.find(
            {"user_id": user_id}, {"_id": 1}
        ).sort("created_at", -1).skip(MAX_HISTORY_PER_USER).to_list(200)
        if extra:
            await db.login_history.delete_many({"_id": {"$in": [e["_id"] for e in extra]}})

        if doc["is_new_device"]:
            body = f"{label} signed in{f' from {ip}' if ip else ''}. If this wasn’t you, change your password and sign that device out."
            await create_notification(
                user_id, "security", "New device signed in", body,
                extra={"action_url": "/login-history", "login_id": doc["id"]},
            )
            try:
                from routes.push import send_push
                await send_push(
                    recipients=[user_id],
                    data={"title": "New device signed in", "message": body, "url": "/login-history"},
                    idempotency_key=f"newdev-{doc['id']}",
                )
            except Exception as e:  # pragma: no cover - push is best-effort
                logger.info(f"new-device push skipped: {e}")
        doc.pop("_id", None)
        return doc
    except Exception as e:
        logger.warning(f"record_login failed (non-blocking): {e}")
        return {}
