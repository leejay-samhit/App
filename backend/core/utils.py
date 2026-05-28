"""Small generic helpers used across the backend."""
import secrets
import string
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from .db import db
from .config import DEFAULT_SETTINGS


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def serialize_user(u: Dict[str, Any]) -> Dict[str, Any]:
    if not u:
        return u
    u = dict(u)
    u.pop("_id", None)
    u.pop("password_hash", None)
    return u


def gen_referral_code(prefix: str = "") -> str:
    alphabet = string.ascii_uppercase + string.digits
    return prefix + ''.join(secrets.choice(alphabet) for _ in range(6))


async def get_settings() -> Dict[str, Any]:
    doc = await db.settings.find_one({"id": "global"}, {"_id": 0})
    if not doc:
        return {**DEFAULT_SETTINGS, "id": "global"}
    # Backfill any missing level keys with defaults so older docs still work
    merged = {**DEFAULT_SETTINGS, **doc}
    # ── Safety guard (June 2026) ──
    # If admin ever saves the registration fee as 0 (or somehow ends up empty
    # in storage) the UI will display "Scan to Pay ₹0", which breaks the
    # entire onboarding funnel. Coerce to the platform default so the
    # payment flow always shows a sensible amount. Hard floor of 118 so
    # accidental low values can't ship.
    HARD_FLOOR = 118.0
    try:
        fee = float(merged.get("registration_fee") or 0)
        if fee < HARD_FLOOR:
            merged["registration_fee"] = max(HARD_FLOOR, float(DEFAULT_SETTINGS.get("registration_fee") or HARD_FLOOR))
    except (TypeError, ValueError):
        merged["registration_fee"] = max(HARD_FLOOR, float(DEFAULT_SETTINGS.get("registration_fee") or HARD_FLOOR))
    return merged


async def audit_log(admin: Dict[str, Any], action: str, target_type: str = "", target_id: str = "", details: Optional[Dict[str, Any]] = None):
    await db.audit_logs.insert_one({
        "id": str(uuid.uuid4()),
        "admin_id": admin["id"],
        "admin_email": admin.get("email"),
        "admin_role": admin.get("admin_role") or "super_admin",
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "details": details or {},
        "created_at": now_utc().isoformat(),
    })


# Backwards-compat alias for existing call-sites that use the underscore name.
_audit_log = audit_log


async def security_event(
    action: str,
    user_id: Optional[str] = None,
    email: Optional[str] = None,
    ip: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    severity: str = "info",
) -> None:
    """Log a security-relevant event to the `security_events` collection.

    Unlike `audit_log` (which is admin-keyed), this is for *system-observed*
    events: failed logins, IP anomalies, device-fingerprint mismatches,
    rate-limit breaches, etc. No admin context required — caller passes
    whatever identity it has (user_id, email, or just IP).

    Stays a separate collection so the admin Audit Log UI isn't flooded
    with auth-failure noise, but admins can still query it via a dedicated
    endpoint when investigating an incident.
    """
    try:
        await db.security_events.insert_one({
            "id": str(uuid.uuid4()),
            "action": action,
            "user_id": user_id,
            "email": (email or "").lower() or None,
            "ip": ip,
            "details": details or {},
            "severity": severity,
            "created_at": now_utc().isoformat(),
        })
    except Exception:
        # Never let auditing crash the request path.
        pass
