"""
Super Admin Broadcast — one-way announcements that fan out to every approved
user as a pinned "Slangcart Announcements" thread + a native push notification.

Endpoints:
  - POST   /api/admin/broadcasts       → create & deliver a broadcast (super_admin)
  - GET    /api/admin/broadcasts       → list past broadcasts (super_admin)
  - GET    /api/admin/broadcasts/{id}  → broadcast detail incl. delivery stats

User-side: the per-user announcement thread is auto-created when the first
broadcast lands; `routes.chat.list_threads` already surfaces it because the
super admin is one of the participants.

To prevent users from replying, the thread is flagged `is_announcement=true`
and `post_message` (see routes/chat.py) rejects sends from non-super-admins
on those threads.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.db import db
from core.security import require_admin_role
from routes.push import send_push

logger = logging.getLogger(__name__)
router = APIRouter()


# ============== Models ==============

class BroadcastIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    message: str = Field(..., min_length=1, max_length=2000)
    image_data_url: Optional[str] = Field(default=None, max_length=4_000_000)
    link_url: Optional[str] = Field(default=None, max_length=500)
    # "all" (default), "providers", "vendors", "users" — segments the audience.
    audience: str = Field(default="all", max_length=20)


# ============== Helpers ==============

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _serialize(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not doc:
        return None
    doc.pop("_id", None)
    for k, v in list(doc.items()):
        if isinstance(v, datetime):
            doc[k] = v.isoformat()
    return doc


async def _audience_user_ids(audience: str) -> List[str]:
    """Resolve the audience selector into a flat list of user IDs.

    Only approved/active non-admin users receive broadcasts. Service Providers
    and Vendors are included by default; the selector lets the admin narrow
    delivery when needed.
    """
    base: Dict[str, Any] = {
        "role": {"$ne": "admin"},
        # Field used by both legacy and new registrations. Some old rows
        # may still set the bare `status` field, so accept either.
        "$or": [
            {"approval_status": {"$in": ["approved", "active"]}},
            {"status":          {"$in": ["approved", "active"]}},
        ],
        "deleted": {"$ne": True},
    }
    if audience == "providers":
        base["is_service_provider"] = True
    elif audience == "vendors":
        base["is_vendor"] = True
    elif audience == "users":
        # Exclude vendors AND providers — broadcast to plain network users only.
        base["is_vendor"] = {"$ne": True}
        base["is_service_provider"] = {"$ne": True}
    # "all" → no extra filter
    docs = await db.users.find(base, {"_id": 0, "id": 1}).to_list(100000)
    return [d["id"] for d in docs if d.get("id")]


async def _get_or_create_announcement_thread(admin_id: str, user_id: str) -> Dict[str, Any]:
    """Per-user announcement thread between the super admin and the user.

    Marked with `is_announcement=true` so non-admins cannot reply (enforced
    in routes/chat.post_message). Reuses the existing `chat_threads` schema
    so the user's chat list picks it up automatically — no separate UI.
    """
    parts = sorted([admin_id, user_id])
    existing = await db.chat_threads.find_one({"participants": parts})
    if existing:
        # Promote any pre-existing thread to announcement mode so future
        # broadcasts can also use it. (Harmless if it's the super admin's
        # own support thread — they can still post.)
        if not existing.get("is_announcement"):
            await db.chat_threads.update_one(
                {"id": existing["id"]},
                {"$set": {"is_announcement": True, "announcement_by": admin_id}},
            )
            existing["is_announcement"] = True
            existing["announcement_by"] = admin_id
        return existing
    doc = {
        "id": str(uuid.uuid4()),
        "participants": parts,
        "is_announcement": True,
        "announcement_by": admin_id,
        "created_at": _now(),
        "last_message_at": _now(),
    }
    await db.chat_threads.insert_one(doc.copy())
    return doc


# ============== Endpoints ==============

@router.post("/admin/broadcasts", status_code=201)
async def create_broadcast(
    body: BroadcastIn,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    """Create + deliver a broadcast to every user in the chosen audience.

    Delivery steps per user:
      1. Find / create an announcement thread between admin and user.
      2. Insert a chat_messages doc tagged `is_broadcast=true`.
      3. Bump the thread's last_message_at so it surfaces at the top of
         the user's chat list.

    Push notifications are sent in chunks of 100 (Emergent relay hard cap).
    """
    user_ids = await _audience_user_ids(body.audience)
    if not user_ids:
        raise HTTPException(status_code=400, detail="No users in this audience.")

    broadcast_id = str(uuid.uuid4())
    now = _now()
    record = {
        "id":             broadcast_id,
        "title":          body.title.strip(),
        "message":        body.message.strip(),
        "image_data_url": body.image_data_url or "",
        "link_url":       (body.link_url or "").strip(),
        "audience":       body.audience,
        "sent_by":        admin["id"],
        "sent_by_name":   admin.get("name") or "Slangcart Team",
        "recipient_count": len(user_ids),
        "created_at":     now,
    }
    await db.admin_broadcasts.insert_one(record.copy())

    # Per-user fan-out — single bulk insert into chat_messages.
    msg_docs: List[Dict[str, Any]] = []
    thread_ids: List[str] = []
    for uid in user_ids:
        try:
            thread = await _get_or_create_announcement_thread(admin["id"], uid)
        except Exception as e:
            logger.warning(f"broadcast: thread create failed for {uid}: {e}")
            continue
        thread_ids.append(thread["id"])
        msg_docs.append({
            "id":              str(uuid.uuid4()),
            "thread_id":       thread["id"],
            "sender_id":       admin["id"],
            "text":            body.message.strip(),
            "image_data_url":  body.image_data_url or "",
            "link_url":        (body.link_url or "").strip(),
            "broadcast_id":    broadcast_id,
            "broadcast_title": body.title.strip(),
            "is_broadcast":    True,
            "deleted":         False,
            "deleted_for_everyone": False,
            "edited":          False,
            "read_by":         [admin["id"]],
            "delivered_to":    [admin["id"]],
            "reactions":       {},
            "starred_by":      [],
            "created_at":      now,
            "updated_at":      now,
        })

    if msg_docs:
        await db.chat_messages.insert_many(msg_docs)
    if thread_ids:
        await db.chat_threads.update_many(
            {"id": {"$in": thread_ids}},
            {"$set": {"last_message_at": now}},
        )

    # Push notification fan-out. send_push() already chunks at 100.
    push_data: Dict[str, Any] = {
        "title":   f"📣 {body.title.strip()}",
        "message": body.message.strip()[:240],
        "action_url": "/(tabs)/chat",
    }
    if body.image_data_url and body.image_data_url.startswith("https://"):
        push_data["image_url"] = body.image_data_url
    try:
        await send_push(
            recipients=user_ids,
            data=push_data,
            idempotency_key=f"broadcast-{broadcast_id}",
        )
    except Exception as e:
        logger.warning(f"broadcast push failed (non-blocking): {e}")

    return _serialize(record)


@router.get("/admin/broadcasts")
async def list_broadcasts(
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin")),
    limit: int = 100,
):
    limit = max(1, min(int(limit or 100), 500))
    rows = await db.admin_broadcasts.find({}, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    return {"broadcasts": [_serialize(dict(r)) for r in rows]}


@router.get("/admin/broadcasts/{broadcast_id}")
async def broadcast_detail(
    broadcast_id: str,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    row = await db.admin_broadcasts.find_one({"id": broadcast_id}, {"_id": 0})
    if not row:
        raise HTTPException(status_code=404, detail="Broadcast not found.")
    # Read receipts — count chat_messages tagged with this broadcast.
    delivered = await db.chat_messages.count_documents({"broadcast_id": broadcast_id})
    return {**_serialize(dict(row)), "delivered_count": delivered}
