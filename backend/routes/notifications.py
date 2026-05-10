"""Notification routes — user-side notification list / mark-all-read.
Extracted from server.py during Phase 2B refactor.

Endpoints (mounted at /api by server.py):
  GET  /notifications/me           — list current user's notifications
  POST /notifications/me/read-all  — mark all unread as read
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends

from core.db import db
from core.security import get_current_user

router = APIRouter(tags=["notifications"])


@router.get("/notifications/me")
async def my_notifications(
    user: Dict[str, Any] = Depends(get_current_user),
    unread_only: bool = False,
):
    q: Dict[str, Any] = {"user_id": user["id"]}
    if unread_only:
        q["read"] = False
    items = await db.notifications.find(q, {"_id": 0}).sort("created_at", -1).limit(100).to_list(100)
    return items


@router.post("/notifications/me/read-all")
async def read_all_notifications(user: Dict[str, Any] = Depends(get_current_user)):
    await db.notifications.update_many(
        {"user_id": user["id"], "read": False},
        {"$set": {"read": True}},
    )
    return {"ok": True}
