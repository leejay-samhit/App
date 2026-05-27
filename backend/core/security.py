"""Auth helpers: password hashing, JWT (access + refresh), FastAPI dependencies.

Token model (Phase 1 Session B, 2026-05-27):
  • Access token:  15 minutes — payload {sub, email, role, sid, type=access}
  • Refresh token: 7 days     — payload {sub, sid, type=refresh}

`sid` (session id) binds both tokens to a single device session. On every new
successful login we mint a brand-new sid and store it on the user doc as
`active_session_id`. Subsequent authenticated requests verify that the
incoming token's sid matches the stored one — if not, the response is 401
with `detail="session_revoked"` and the frontend logs the user out.

Backward compatibility: tokens minted BEFORE this change have no `sid`
claim. We accept them as-is (legacy single-mode) so already-logged-in users
aren't kicked out. They will be rotated to the new model on their next login.
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

        # ── Single-session enforcement (backward-compatible) ────────────
        # New tokens carry `sid`; user docs carry `active_session_id`.
        # Behaviour matrix:
        #   token has sid + user has active_session_id + match  → OK
        #   token has sid + user has active_session_id + diff   → kick (other-device login)
        #   token has sid + user.active_session_id is MISSING   → kick (explicit logout cleared it)
        #   token has NO sid (legacy) + user has NO sid yet     → OK (grandfathered until next login)
        #   token has NO sid (legacy) + user already has sid    → kick (user has since logged in fresh)
        token_sid = payload.get("sid")
        user_sid = user.get("active_session_id")
        if token_sid:
            if user_sid is None or user_sid != token_sid:
                raise HTTPException(status_code=401, detail="session_revoked")
        else:
            # Legacy token (no sid). Only allow it while the user hasn't yet
            # logged in under the new model. As soon as `active_session_id`
            # is set on the user doc, all legacy tokens must die.
            if user_sid:
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
