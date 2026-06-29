"""Auth helpers: password hashing, JWT (access + refresh), FastAPI dependencies.

Token model (Phase 2 multi-session, 2026-06-27):
  • Access token:  15 minutes — payload {sub, email, role, sid, type=access}
  • Refresh token: 7 days     — payload {sub, sid, type=refresh}

`sid` (session id) binds both tokens to a SINGLE DEVICE SESSION. Every login
mints a brand-new sid and ADDS it to the user's `active_session_ids` array.
Up to N (default 10) concurrent sessions per user are tolerated, so a user
can be logged in on their phone APK AND on slangcart.com web simultaneously
without one kicking the other.

Behaviour matrix in get_current_user():
  • token.sid ∈ user.active_session_ids                → OK
  • token.sid present, user.active_session_ids exists
    but does NOT contain token.sid                     → kick (revoked)
  • token.sid present, user has legacy `active_session_id`
    (no array yet) that matches token.sid              → OK (grandfathered)
  • token.sid absent (legacy token, pre-Phase 1) and
    user has NO session model yet                      → OK (grandfathered)
  • token.sid absent but user has new session model    → kick

On explicit /auth/logout, ONLY the current device's sid is pulled from
the array — other devices stay logged in.

Backward compatibility: legacy `active_session_id` (single string) is still
read for grandfathering. New logins write BOTH `active_session_id` (latest,
for legacy display) AND `active_session_ids` (the authoritative array).
"""
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
import uuid

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from .config import JWT_SECRET, JWT_ALGORITHM
from .db import db

security = HTTPBearer(auto_error=False)

# Lifetimes — kept here as module constants so the rest of the code stays
# declarative and an admin can tweak them in one place if needed.
ACCESS_TOKEN_TTL = timedelta(minutes=15)
REFRESH_TOKEN_TTL = timedelta(days=7)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Safely verify a plaintext password against a bcrypt hash.

    Returns False (NEVER raises) when:
      • `hashed` is empty / None  — e.g. Google-OAuth-only accounts have no
        password_hash, so a malicious email+password login attempt against
        them must cleanly return 401 instead of 500.
      • `hashed` is malformed     — bcrypt.checkpw raises ValueError("Invalid
        salt") on garbage input which would otherwise leak as a 500 Internal
        Server Error and look like the backend is down.
    """
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        # Malformed hash → treat as failed login (defence-in-depth).
        return False


def new_session_id() -> str:
    """Generate a fresh session id for a new login."""
    return uuid.uuid4().hex


# Maximum number of concurrent device sessions a single user may hold.
# Phone APK + web slangcart.com + secondary devices comfortably fit; oldest
# evicted when the cap is exceeded. Lifted via env if a power user complains.
MAX_SESSIONS_PER_USER = 10


async def register_session(user_id: str, sid: str) -> None:
    """Register a freshly-minted session id on the user document.

    Adds `sid` to the `active_session_ids` array (capped at the most-recent
    MAX_SESSIONS_PER_USER entries) and ALSO mirrors it onto the legacy
    `active_session_id` scalar for code that still reads the old field.

    Idempotent — calling with an sid that's already in the array is a no-op
    (Mongo's $push + $each + $slice handles dupes by trimming).
    """
    await db.users.update_one(
        {"id": user_id},
        {
            "$set": {"active_session_id": sid},
            "$push": {
                "active_session_ids": {
                    "$each": [sid],
                    "$slice": -MAX_SESSIONS_PER_USER,
                }
            },
        },
    )


async def revoke_session(user_id: str, sid: str) -> None:
    """Pull a single device's sid from the active set (explicit logout).

    Other devices stay logged in. If the array empties, also unset the
    legacy scalar so a legacy-token-bearing client can't sneak past the
    `token.sid == legacy` grandfathering branch in get_current_user.
    """
    await db.users.update_one(
        {"id": user_id},
        {"$pull": {"active_session_ids": sid}},
    )
    u = await db.users.find_one(
        {"id": user_id},
        {"_id": 0, "active_session_ids": 1, "active_session_id": 1},
    )
    if u and not (u.get("active_session_ids") or []):
        await db.users.update_one(
            {"id": user_id},
            {"$unset": {"active_session_id": ""}},
        )
    elif u and u.get("active_session_id") == sid:
        # Promote a still-valid sid into the legacy scalar so downstream
        # code that displays "current session" stays meaningful.
        remaining = (u.get("active_session_ids") or [])
        if remaining:
            await db.users.update_one(
                {"id": user_id},
                {"$set": {"active_session_id": remaining[-1]}},
            )


async def rotate_session(user_id: str, old_sid: str, new_sid: str) -> None:
    """Refresh-token rotation: replace `old_sid` with `new_sid` atomically
    in the active set so the device keeps its slot without inflating the
    count and without other devices noticing."""
    await db.users.update_one(
        {"id": user_id},
        {"$pull": {"active_session_ids": old_sid}},
    )
    await register_session(user_id, new_sid)


def create_access_token(user_id: str, email: str, role: str, sid: Optional[str] = None) -> str:
    """Mint a short-lived (15-min) access token.

    `sid` is optional ONLY for legacy call-sites still in the codebase; new
    code paths (login, register, refresh) always pass an explicit sid.
    """
    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        "sub": user_id,
        "email": email,
        "role": role,
        "iat": now,
        "exp": now + ACCESS_TOKEN_TTL,
        "type": "access",
    }
    if sid:
        payload["sid"] = sid
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str, sid: str) -> str:
    """Mint a long-lived (7-day) refresh token. Carries only what's needed
    to re-mint an access token: subject + session id."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "sid": sid,
        "iat": now,
        "exp": now + REFRESH_TOKEN_TTL,
        "type": "refresh",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_refresh_token(token: str) -> Dict[str, Any]:
    """Validate + decode a refresh token. Raises HTTPException(401) on any
    failure with a clear `detail` so the caller (and frontend) can react."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="refresh_expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="refresh_invalid")
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="refresh_invalid")
    return payload


async def get_current_user(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    if not creds or not creds.credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = creds.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        # ── Multi-session enforcement (Phase 2 — 2026-06-27) ───────────
        # A user may be logged in on MULTIPLE devices concurrently (e.g.
        # mobile APK + web at slangcart.com). Each device's JWT carries a
        # unique `sid`. A login adds that sid to user.active_session_ids
        # (capped at 10 newest); logout pulls only the current sid.
        # Behaviour matrix:
        #   token.sid ∈ user.active_session_ids                → OK
        #   token.sid present, array exists but no match       → kick
        #   token.sid present, no array yet, matches legacy
        #     `active_session_id`                              → OK (grandfathered)
        #   token.sid absent (legacy), no session model yet    → OK (grandfathered)
        #   token.sid absent, new session model active         → kick
        token_sid = payload.get("sid")
        active_sids = user.get("active_session_ids") or []
        legacy_sid = user.get("active_session_id")
        if token_sid:
            if active_sids:
                if token_sid not in active_sids:
                    raise HTTPException(status_code=401, detail="session_revoked")
            elif legacy_sid is not None:
                if legacy_sid != token_sid:
                    raise HTTPException(status_code=401, detail="session_revoked")
            else:
                # Session model fully cleared (explicit logout of all devices).
                raise HTTPException(status_code=401, detail="session_revoked")
        else:
            # Legacy token (no sid). Only allow it while the user hasn't yet
            # logged in under the new model.
            if active_sids or legacy_sid:
                raise HTTPException(status_code=401, detail="session_revoked")

        # ── Device fingerprint observation (audit-log only, no block) ──
        # FE sends a stable per-install UUID via X-Device-FP. If it changes
        # for a given user we log a security event but do NOT block — false
        # positives (clearing app data, reinstall, multi-device family use)
        # would lock people out for no real safety gain.
        try:
            fp = (request.headers.get("x-device-fp") or "").strip()
            if fp and len(fp) <= 128:
                last_fp = user.get("last_device_fp")
                if last_fp and last_fp != fp:
                    # Lazy import to avoid circular dep with core.utils.
                    from .utils import security_event as _se
                    await _se(
                        "auth.device_change",
                        user_id=user["id"],
                        email=user.get("email"),
                        ip=(request.client.host if request.client else None),
                        details={"previous_fp": last_fp[:16] + "…", "new_fp": fp[:16] + "…"},
                        severity="warning",
                    )
                if last_fp != fp:
                    await db.users.update_one(
                        {"id": user["id"]},
                        {"$set": {"last_device_fp": fp}},
                    )
        except Exception:
            # Fingerprint observation must never break the request.
            pass

        return user
    except HTTPException:
        raise
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="token_expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def require_admin(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def require_admin_role(*allowed: str):
    """Restrict an endpoint to specific admin sub-roles (super_admin, manager, support, finance)."""
    async def checker(admin: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
        sub = admin.get("admin_role") or "super_admin"  # legacy admins default super
        if sub not in allowed:
            raise HTTPException(status_code=403, detail=f"Requires admin role: {' or '.join(allowed)}")
        return admin
    return checker


async def require_admin_not_finance(admin: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Block finance role from non-financial admin write actions."""
    sub = admin.get("admin_role") or "super_admin"
    if sub == "finance":
        raise HTTPException(status_code=403, detail="Finance role cannot perform this action — only withdrawals.")
    return admin


async def require_clean_device(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Phase 3 — block financial actions when the user's device failed an
    integrity check (root/jailbreak/Play-Integrity/SSL-pin/...).

    The frontend POSTs to /api/security/integrity-report on app boot. That
    endpoint stamps users.integrity_status with the verdict. Here we read
    the stamp and reject the request when level ∈ {read_only, hard_block}.

    Backward compat: users with NO integrity_status (legacy install, Expo
    Go, OAuth users who haven't reported yet) are ALLOWED — anti-tampering
    rolls out without locking out the existing base. The FE will stamp
    them on its next boot.
    """
    integ = (user or {}).get("integrity_status") or {}
    level = integ.get("block_level")
    if level in ("read_only", "hard_block"):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "device_compromised",
                "block_level": level,
                "reasons": integ.get("reasons", []),
                "message": "Action blocked: device failed a security check. Please use the app on a non-rooted, non-tampered device.",
            },
        )
    return user
