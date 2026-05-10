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
