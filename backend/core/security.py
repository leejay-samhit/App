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
import os
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
# evicted when the cap is exceeded. Override at deploy time via the
# MAX_SESSIONS_PER_USER env var if a power user complains.
try:
    MAX_SESSIONS_PER_USER = max(1, int(os.environ.get("MAX_SESSIONS_PER_USER", "10")))
except (TypeError, ValueError):
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
    count and without other devices noticing.

    The swap is also remembered for ROTATION_GRACE_SECONDS. A phone that
    loses the refresh RESPONSE (killed app, tunnel drop, two parallel
    refreshes) still holds the old token; without this memory its next call
    looked like a revoked session and the user was silently signed out.
    """
    await db.users.update_one(
        {"id": user_id},
        {
            "$pull": {"active_session_ids": old_sid},
        },
    )
    await db.users.update_one(
        {"id": user_id},
        {
            "$push": {
                "session_rotations": {
                    "$each": [{
                        "old": old_sid,
                        "new": new_sid,
                        "at": datetime.now(timezone.utc).isoformat(),
                    }],
                    "$slice": -30,
                }
            }
        },
    )
    await register_session(user_id, new_sid)


# How long a just-rotated refresh token may still be replayed (seconds).
ROTATION_GRACE_SECONDS = int(os.environ.get("ROTATION_GRACE_SECONDS", "300"))


def rotation_target(user: Dict[str, Any], sid: str) -> Optional[str]:
    """Return the session id that replaced `sid`, if it was rotated recently.

    Follows the chain (a device can rotate several times) and only accepts a
    hand-off that happened within the grace window, so a truly old token
    still gets rejected.
    """
    rotations = user.get("session_rotations") or []
    if not rotations:
        return None
    by_old = {r.get("old"): r for r in rotations if r.get("old")}
    active = set(user.get("active_session_ids") or [])
    cur = sid
    for _ in range(6):
        row = by_old.get(cur)
        if not row:
            return None
        try:
            at = datetime.fromisoformat(str(row.get("at")).replace("Z", "+00:00"))
            if at.tzinfo is None:
                at = at.replace(tzinfo=timezone.utc)
        except Exception:
            return None
        if (datetime.now(timezone.utc) - at).total_seconds() > ROTATION_GRACE_SECONDS:
            return None
        cur = row.get("new")
        if cur in active:
            return cur
    return None


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


async def get_current_user_optional(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[Dict[str, Any]]:
    """Same as `get_current_user` but returns None instead of raising.

    For endpoints that work for guests AND get better when they know who is
    asking — e.g. the personalised product rails. A bad or expired token is
    treated as "no user" rather than a hard 401, so a stale token on a public
    screen can never blank the page.
    """
    if not creds or not creds.credentials:
        return None
    try:
        return await get_current_user(request, creds)
    except HTTPException:
        return None


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
        # Nov-2026 — a blocked account (admin block, or the owner's own
        # deletion request) must stop working on devices that are ALREADY
        # signed in, not just at the next login.
        if user.get("is_blocked"):
            raise HTTPException(
                status_code=403,
                detail=user.get("block_reason") or "This account is blocked.",
            )

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

        # Expose the token's session id to routes that manage devices
        # (routes/login_history.py). Stripped by serialize_user.
        user["_sid"] = token_sid or ""
        return user
    except HTTPException:
        raise
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="token_expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


ADMIN_AREAS: Dict[str, Any] = {
    # Sep 2026 — scoped manager roles. A promoted user gets access to ONE
    # area of the admin panel and nothing else (owner's requirement: "don't
    # show all the admin available features"). `super_admin` keeps everything.
    #
    # Each entry lists the URL fragments that belong to that area; the guard
    # below matches the request path against them, so every current AND future
    # admin endpoint in that area is covered without touching each route.
    # An entry may be prefixed with a method ("GET /admin/products") to grant
    # read-only access to a neighbouring area a screen needs to function.
    "products_manager": [
        "/admin/products", "/admin/product", "/admin/bulk-products", "/admin/categories",
        "/admin/shop-categories", "/admin/brands", "/admin/ai-tools", "/admin/master-products",
        # The product list's "Filter by vendor" picker reads the vendor
        # roster — read-only, so no vendor can be approved or edited here.
        "GET /admin/vendors",
    ],
    "layout_manager": [
        "/admin/shop-layout", "/admin/promo-banners", "/admin/branding", "/admin/shop-categories",
        # The layout builder picks products into blocks — read-only, so a
        # layout manager still cannot create, edit or publish a product.
        "GET /admin/products",
    ],
    "order_manager": [
        "/admin/orders", "/admin/order", "/admin/export", "/admin/invoices", "/admin/sales",
    ],
    "vendor_service_manager": [
        "/admin/users/pending", "/admin/registrations", "/admin/approved-registrations",
        "/admin/rejected-registrations", "/admin/vendors", "/admin/vendor",
        "/admin/services", "/admin/service", "/admin/kyc", "/admin/approvals",
    ],
}

# Endpoints every admin needs just to open the panel / see themselves.
ADMIN_COMMON_PATHS = (
    "/admin/settings", "/admin/me", "/admin/stats", "/admin/dashboard",
    "/admin/notifications", "/admin/branding",
)


async def require_admin(request: Request, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    sub = user.get("admin_role") or "super_admin"
    allowed = ADMIN_AREAS.get(sub)
    if allowed is not None:
        path = request.url.path
        method = request.method.upper()

        def _matches(rule: str) -> bool:
            if " " in rule:
                want_method, frag = rule.split(" ", 1)
                return method == want_method.upper() and frag in path
            return rule in path

        if not (any(_matches(p) for p in allowed) or any(p in path for p in ADMIN_COMMON_PATHS)):
            raise HTTPException(
                status_code=403,
                detail=f"Your admin role ({sub.replace('_', ' ')}) doesn't cover this section.",
            )
    return user


def require_admin_role(*allowed: str):
    """Restrict an endpoint to specific admin sub-roles.

    Sep 2026 — the scoped manager roles (products / layout / order /
    vendor+service) are NOT super admins, so anything marked
    `require_admin_role("super_admin")` stays out of their reach; their own
    area is granted by the path check in `require_admin` above.
    """
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
