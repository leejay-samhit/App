"""Admin password tools (Sep 2026, owner request).

Admin → Users → edit can now show a customer's password and reset it.

Passwords remain bcrypt-hashed for login; a Fernet-encrypted copy is written
alongside on every password write (core/password_recovery). Only a
`super_admin` may read it, every read is audit-logged, and accounts created
before this feature have no recoverable copy — those get a 409 and the app
offers "Reset & reveal" instead.
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Response

from core.db import db
from core.password_recovery import (
    FIELD, decrypt_password, generate_password, password_fields,
)
from core.security import require_admin_role
from core.utils import now_utc

logger = logging.getLogger(__name__)
router = APIRouter(tags=["admin-passwords"])


async def _audit(admin: Dict[str, Any], action: str, target: Dict[str, Any], extra: Optional[dict] = None):
    import uuid
    await db.audit_logs.insert_one({
        "id": str(uuid.uuid4()),
        "actor_id": admin.get("id"),
        "actor_email": admin.get("email"),
        "action": action,
        "entity": "user",
        "entity_id": target.get("id"),
        # Never store the password itself — only who looked and when.
        "details": {"target_email": target.get("email"), **(extra or {})},
        "timestamp": now_utc().isoformat(),
    })


@router.get("/admin/users/{user_id}/password")
async def reveal_password(
    user_id: str,
    response: Response,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    response.headers["Cache-Control"] = "no-store"
    target = await db.users.find_one({"id": user_id}, {"_id": 0, "id": 1, "email": 1, "name": 1, FIELD: 1})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    token = target.get(FIELD)
    if not token:
        raise HTTPException(
            status_code=409,
            detail="This password was set before password viewing existed — use “Reset & reveal” to give them a new one.",
        )
    try:
        plain = decrypt_password(token)
    except ValueError:
        raise HTTPException(status_code=409, detail="Password is not recoverable — use “Reset & reveal”.")
    await _audit(admin, "user.password_revealed", target)
    return {"user_id": user_id, "email": target.get("email"), "password": plain}


@router.post("/admin/users/{user_id}/password/reset-reveal")
async def reset_and_reveal(
    user_id: str,
    response: Response,
    payload: Dict[str, Any] = Body(default={}),
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    """Set a new password (given or generated) and show it once."""
    response.headers["Cache-Control"] = "no-store"
    target = await db.users.find_one({"id": user_id}, {"_id": 0, "id": 1, "email": 1, "name": 1})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    new_password = str(payload.get("password") or "").strip() or generate_password()
    if len(new_password) < 6 or len(new_password.encode("utf-8")) > 72:
        raise HTTPException(status_code=400, detail="Password must be 6–72 characters")
    await db.users.update_one({"id": user_id}, {"$set": {
        **password_fields(new_password),
        "password_changed_at": now_utc().isoformat(),
        "password_set_by_admin": admin.get("email"),
    }})
    await _audit(admin, "user.password_reset", target, {"generated": not payload.get("password")})
    try:
        from server import _create_notification
        await _create_notification(
            user_id, "account", "Password changed",
            "An admin set a new password for your account. Please use it to log in.",
        )
    except Exception:
        pass
    return {"user_id": user_id, "email": target.get("email"), "password": new_password}
