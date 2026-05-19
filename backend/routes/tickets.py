"""Support Tickets — User + Admin endpoints.
Extracted from server.py during Phase 2B refactor.

Collections:
  tickets:           ticket headers (subject / status / counts)
  ticket_messages:   messages in a ticket thread

Endpoints mounted under /api by server.py:
  POST   /tickets                          — user creates a ticket
  GET    /tickets/me                       — user lists own tickets
  GET    /tickets/{id}                     — read ticket + thread (owner or admin)
  POST   /tickets/{id}/reply               — append message (owner or admin)
  POST   /tickets/{id}/close               — user closes own ticket
  GET    /admin/tickets                    — admin list/filter
  GET    /admin/tickets/stats              — admin count buckets
  PATCH  /admin/tickets/{id}               — admin update (status/priority/assign)
  GET    /admin/tickets/export             — admin CSV export
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from core.db import db
from core.notifications import create_notification
from core.security import get_current_user, require_admin_role
from core.utils import now_utc
from models import TicketCreateRequest, TicketReplyRequest, TicketUpdateRequest


router = APIRouter(tags=["tickets"])


TICKET_CATEGORIES = ("payment", "withdrawal", "account", "kyc", "product", "other")
TICKET_STATUSES = ("open", "in_progress", "resolved", "closed")
TICKET_PRIORITIES = ("low", "normal", "high", "urgent")
TICKET_ADMIN_ROLES = ("super_admin", "support", "finance")


def _sanitize_ticket(t: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in t.items() if k != "_id"}


def _short_preview(text: str, n: int = 80) -> str:
    t = (text or "").strip().replace("\n", " ")
    return t[:n] + ("…" if len(t) > n else "")


async def _notify_support_admins(title: str, body: str, ticket_id: str) -> None:
    """Notify all admins with support / super_admin / finance roles."""
    async for a in db.users.find(
        {"role": "admin", "admin_role": {"$in": list(TICKET_ADMIN_ROLES)}},
        {"id": 1, "_id": 0},
    ):
        try:
            await create_notification(a["id"], "ticket", title, body)
        except Exception:
            pass


# ──────────────────────────── USER endpoints ──────────────────────────── #

@router.post("/tickets")
async def create_ticket(
    payload: TicketCreateRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    subject = (payload.subject or "").strip()
    message = (payload.message or "").strip()
    category = (payload.category or "other").strip().lower()
    if not subject or len(subject) < 3:
        raise HTTPException(status_code=400, detail="Subject is required (min 3 chars)")
    if not message or len(message) < 3:
        raise HTTPException(status_code=400, detail="Message is required (min 3 chars)")
    if category not in TICKET_CATEGORIES:
        category = "other"

    tid = str(uuid.uuid4())
    ts = now_utc().isoformat()
    preview = _short_preview(message)
    doc = {
        "id": tid,
        "user_id": user["id"],
        "user_email": user.get("email"),
        "user_name": user.get("name"),
        "subject": subject,
        "category": category,
        "priority": "normal",
        "status": "open",
        "assigned_to": None,
        "assigned_to_email": None,
        "message_count": 1,
        "last_message_at": ts,
        "last_message_by": "user",
        "last_message_preview": preview,
        "has_unread_admin": True,
        "has_unread_user": False,
        "created_at": ts,
        "updated_at": ts,
    }
    await db.tickets.insert_one(doc)

    await db.ticket_messages.insert_one({
        "id": str(uuid.uuid4()),
        "ticket_id": tid,
        "sender_id": user["id"],
        "sender_type": "user",
        "sender_name": user.get("name"),
        "sender_email": user.get("email"),
        "message": message,
        "attachment_b64": payload.attachment_b64 or None,
        "created_at": ts,
    })

    await _notify_support_admins(
        "New support ticket",
        f"{user.get('name') or user.get('email')}: {subject}",
        tid,
    )

    return {"ok": True, "ticket": _sanitize_ticket(doc)}


@router.get("/tickets/me")
async def my_tickets(user: Dict[str, Any] = Depends(get_current_user)):
    items = await db.tickets.find(
        {"user_id": user["id"]}, {"_id": 0}
    ).sort("updated_at", -1).to_list(200)
    return {"items": items, "total": len(items)}


@router.get("/tickets/{ticket_id}")
async def get_ticket(ticket_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")
    is_admin = (
        user.get("role") == "admin"
        and (user.get("admin_role") or "super_admin") in TICKET_ADMIN_ROLES
    )
    if t.get("user_id") != user["id"] and not is_admin:
        raise HTTPException(status_code=403, detail="Not allowed")
    messages = await db.ticket_messages.find(
        {"ticket_id": ticket_id}, {"_id": 0}
    ).sort("created_at", 1).to_list(1000)
    # Clear unread flag for whichever side is reading
    if user.get("role") == "admin":
        if t.get("has_unread_admin"):
            await db.tickets.update_one(
                {"id": ticket_id}, {"$set": {"has_unread_admin": False}}
            )
            t["has_unread_admin"] = False
    else:
        if t.get("has_unread_user"):
            await db.tickets.update_one(
                {"id": ticket_id}, {"$set": {"has_unread_user": False}}
            )
            t["has_unread_user"] = False
    return {"ticket": t, "messages": messages}


@router.post("/tickets/{ticket_id}/reply")
async def reply_ticket(
    ticket_id: str,
    payload: TicketReplyRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    t = await db.tickets.find_one({"id": ticket_id})
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")
    is_admin = (
        user.get("role") == "admin"
        and (user.get("admin_role") or "super_admin") in TICKET_ADMIN_ROLES
    )
    if t.get("user_id") != user["id"] and not is_admin:
        raise HTTPException(status_code=403, detail="Not allowed")
    msg = (payload.message or "").strip()
    if not msg:
        raise HTTPException(status_code=400, detail="Message is required")
    if t.get("status") == "closed":
        raise HTTPException(status_code=400, detail="Ticket is closed — cannot reply")

    ts = now_utc().isoformat()
    sender_type = "admin" if is_admin else "user"
    preview = _short_preview(msg)

    await db.ticket_messages.insert_one({
        "id": str(uuid.uuid4()),
        "ticket_id": ticket_id,
        "sender_id": user["id"],
        "sender_type": sender_type,
        "sender_name": user.get("name"),
        "sender_email": user.get("email"),
        "message": msg,
        "attachment_b64": payload.attachment_b64 or None,
        "created_at": ts,
    })

    update: Dict[str, Any] = {
        "last_message_at": ts,
        "last_message_by": sender_type,
        "last_message_preview": preview,
        "updated_at": ts,
    }
    if sender_type == "admin":
        update["has_unread_user"] = True
        update["has_unread_admin"] = False
        if t.get("status") == "open":
            update["status"] = "in_progress"
        await create_notification(
            t["user_id"], "ticket",
            f"Support replied: {t.get('subject', 'Your ticket')}",
            preview,
        )
    else:
        update["has_unread_admin"] = True
        update["has_unread_user"] = False
        if t.get("status") == "resolved":
            update["status"] = "in_progress"
        await _notify_support_admins(
            "Ticket reply",
            f"{t.get('user_email') or 'User'}: {t.get('subject', 'Ticket update')}",
            ticket_id,
        )

    await db.tickets.update_one(
        {"id": ticket_id}, {"$set": update, "$inc": {"message_count": 1}}
    )
    t2 = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    return {"ok": True, "ticket": t2}


@router.post("/tickets/{ticket_id}/close")
async def close_ticket_by_user(
    ticket_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """User closes their own ticket."""
    t = await db.tickets.find_one({"id": ticket_id})
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if t.get("user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Not allowed")
    if t.get("status") not in ("resolved", "in_progress", "open"):
        raise HTTPException(status_code=400, detail="Ticket is already closed")
    ts = now_utc().isoformat()
    await db.tickets.update_one(
        {"id": ticket_id},
        {"$set": {
            "status": "closed",
            "closed_at": ts,
            "closed_by": "user",
            "updated_at": ts,
        }},
    )
    return {"ok": True}


# ──────────────────────────── ADMIN endpoints ──────────────────────────── #

@router.get("/admin/tickets")
async def admin_list_tickets(
    status: Optional[str] = None,
    category: Optional[str] = None,
    priority: Optional[str] = None,
    assigned_to: Optional[str] = None,
    q: Optional[str] = None,
    admin: Dict[str, Any] = Depends(require_admin_role(*TICKET_ADMIN_ROLES)),
):
    query: Dict[str, Any] = {}
    if status and status in TICKET_STATUSES:
        query["status"] = status
    if category and category in TICKET_CATEGORIES:
        query["category"] = category
    if priority and priority in TICKET_PRIORITIES:
        query["priority"] = priority
    if assigned_to:
        if assigned_to == "me":
            query["assigned_to"] = admin["id"]
        elif assigned_to == "unassigned":
            query["assigned_to"] = None
        else:
            query["assigned_to"] = assigned_to
    if q:
        regex = {"$regex": q.strip(), "$options": "i"}
        query["$or"] = [
            {"subject": regex},
            {"user_email": regex},
            {"user_name": regex},
            {"last_message_preview": regex},
        ]
    items = await db.tickets.find(query, {"_id": 0}).sort("updated_at", -1).to_list(500)
    open_count = await db.tickets.count_documents({"status": "open"})
    in_progress_count = await db.tickets.count_documents({"status": "in_progress"})
    unread_admin_count = await db.tickets.count_documents(
        {"has_unread_admin": True, "status": {"$ne": "closed"}}
    )
    return {
        "items": items,
        "total": len(items),
        "counts": {
            "open": open_count,
            "in_progress": in_progress_count,
            "unread_admin": unread_admin_count,
        },
    }


@router.get("/admin/tickets/stats")
async def admin_ticket_stats(
    admin: Dict[str, Any] = Depends(require_admin_role(*TICKET_ADMIN_ROLES)),
):
    total = await db.tickets.count_documents({})
    return {
        "total": total,
        "open": await db.tickets.count_documents({"status": "open"}),
        "in_progress": await db.tickets.count_documents({"status": "in_progress"}),
        "resolved": await db.tickets.count_documents({"status": "resolved"}),
        "closed": await db.tickets.count_documents({"status": "closed"}),
        "unread_admin": await db.tickets.count_documents(
            {"has_unread_admin": True, "status": {"$ne": "closed"}}
        ),
    }


@router.patch("/admin/tickets/{ticket_id}")
async def admin_update_ticket(
    ticket_id: str,
    payload: TicketUpdateRequest,
    admin: Dict[str, Any] = Depends(require_admin_role(*TICKET_ADMIN_ROLES)),
):
    t = await db.tickets.find_one({"id": ticket_id})
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")
    update: Dict[str, Any] = {}
    note_parts: List[str] = []
    if payload.status is not None:
        if payload.status not in TICKET_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status")
        update["status"] = payload.status
        note_parts.append(f"status → {payload.status}")
        if payload.status == "closed":
            update["closed_at"] = now_utc().isoformat()
            update["closed_by"] = "admin"
        elif payload.status == "resolved":
            update["resolved_at"] = now_utc().isoformat()
            update["resolved_by"] = admin["id"]
    if payload.priority is not None:
        if payload.priority not in TICKET_PRIORITIES:
            raise HTTPException(status_code=400, detail="Invalid priority")
        update["priority"] = payload.priority
        note_parts.append(f"priority → {payload.priority}")
    if payload.assigned_to is not None:
        if payload.assigned_to == "" or payload.assigned_to is None:
            update["assigned_to"] = None
            update["assigned_to_email"] = None
            note_parts.append("unassigned")
        else:
            target = await db.users.find_one(
                {"id": payload.assigned_to, "role": "admin"},
                {"id": 1, "email": 1, "_id": 0},
            )
            if not target:
                raise HTTPException(status_code=400, detail="Assignee is not a valid admin")
            update["assigned_to"] = target["id"]
            update["assigned_to_email"] = target.get("email")
            note_parts.append(f"assigned → {target.get('email')}")
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")

    update["updated_at"] = now_utc().isoformat()
    await db.tickets.update_one({"id": ticket_id}, {"$set": update})

    if note_parts and t.get("user_id"):
        try:
            await create_notification(
                t["user_id"], "ticket",
                f"Ticket updated: {t.get('subject', '')}",
                ", ".join(note_parts),
            )
        except Exception:
            pass

    t2 = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    return {"ok": True, "ticket": t2}


@router.get("/admin/tickets/export")
async def admin_export_tickets(
    admin: Dict[str, Any] = Depends(require_admin_role(*TICKET_ADMIN_ROLES)),
):
    """CSV export of tickets metadata."""
    rows = await db.tickets.find({}, {"_id": 0}).sort("updated_at", -1).to_list(5000)
    header = (
        "id,subject,category,priority,status,user_email,user_name,"
        "assigned_to_email,message_count,created_at,updated_at,"
        "last_message_at,last_message_by\n"
    )

    def esc(v: Any) -> str:
        if v is None:
            return ""
        s = str(v).replace('"', '""').replace("\n", " ").replace("\r", " ")
        return f'"{s}"' if ("," in s or '"' in s) else s

    lines: List[str] = [header]
    for r in rows:
        lines.append(",".join([
            esc(r.get("id")),
            esc(r.get("subject")),
            esc(r.get("category")),
            esc(r.get("priority")),
            esc(r.get("status")),
            esc(r.get("user_email")),
            esc(r.get("user_name")),
            esc(r.get("assigned_to_email")),
            esc(r.get("message_count")),
            esc(r.get("created_at")),
            esc(r.get("updated_at")),
            esc(r.get("last_message_at")),
            esc(r.get("last_message_by")),
        ]) + "\n")
    csv = "".join(lines)
    return Response(
        content=csv,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=tickets.csv"},
    )
