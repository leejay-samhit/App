"""Login-history endpoints — "where is my account signed in?" (Sep 2026).

Rows are written by core/login_history.record_login on every sign-in. The user
can see them and sign any other device out; a super admin can review any
account's history from the Users screen.
"""
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query

from core.db import db
from core.security import get_current_user, require_admin_role, revoke_session

router = APIRouter(tags=["login-history"])


async def _rows(user_id: str, limit: int) -> List[Dict[str, Any]]:
    return await db.login_history.find(
        {"user_id": user_id}, {"_id": 0}
    ).sort("created_at", -1).limit(limit).to_list(limit)


def _decorate(rows: List[Dict[str, Any]], active_sids: List[str], current_sid: str):
    out = []
    for r in rows:
        sid = r.get("session_id")
        out.append({
            **r,
            "is_current": bool(sid and sid == current_sid),
            "is_active": bool(sid and sid in active_sids),
        })
    return out


@router.get("/users/me/login-history")
async def my_login_history(
    limit: int = Query(30, ge=1, le=50),
    user: Dict[str, Any] = Depends(get_current_user),
):
    fresh = await db.users.find_one(
        {"id": user["id"]}, {"_id": 0, "active_session_ids": 1, "active_session_id": 1},
    ) or {}
    active = list(fresh.get("active_session_ids") or [])
    if fresh.get("active_session_id"):
        active.append(fresh["active_session_id"])
    rows = _decorate(await _rows(user["id"], limit), active, str(user.get("_sid") or ""))
    return {
        "items": rows,
        "active_devices": sum(1 for r in rows if r["is_active"]),
    }


@router.post("/users/me/login-history/{entry_id}/revoke")
async def revoke_device(entry_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    """Sign one listed device out (its session id is pulled from the account)."""
    row = await db.login_history.find_one({"id": entry_id, "user_id": user["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(status_code=404, detail="Login entry not found")
    sid = row.get("session_id")
    if not sid:
        raise HTTPException(status_code=400, detail="This entry has no session to sign out")
    if sid == str(user.get("_sid") or ""):
        raise HTTPException(status_code=400, detail="That’s this device — use Log out instead")
    await revoke_session(user["id"], sid)
    return {"ok": True, "revoked": sid}


@router.post("/users/me/login-history/revoke-others")
async def revoke_other_devices(user: Dict[str, Any] = Depends(get_current_user)):
    """Keep this device signed in, sign every other one out."""
    current = str(user.get("_sid") or "")
    fresh = await db.users.find_one({"id": user["id"]}, {"_id": 0, "active_session_ids": 1}) or {}
    others = [s for s in (fresh.get("active_session_ids") or []) if s and s != current]
    for sid in others:
        await revoke_session(user["id"], sid)
    return {"ok": True, "signed_out": len(others)}


@router.get("/admin/users/{user_id}/login-history")
async def admin_login_history(
    user_id: str,
    limit: int = Query(30, ge=1, le=50),
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    target = await db.users.find_one({"id": user_id}, {"_id": 0, "active_session_ids": 1, "email": 1})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    rows = _decorate(await _rows(user_id, limit), list(target.get("active_session_ids") or []), "")
    return {"email": target.get("email"), "items": rows}
