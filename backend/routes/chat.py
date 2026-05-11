"""
Chat — referral-code-gated 1:1 messaging with WebSocket real-time delivery.

Flow:
  1. User searches another user by referral code        → /chat/search
  2. Send chat request                                   → /chat/request
  3. Recipient accepts                                   → /chat/request/{id}/accept
  4. A `chat_threads` doc is created, both can text      → /chat/{thread_id}/messages
  5. Edit own message within 15 min if not yet replied   → PATCH /chat/messages/{id}
  6. Soft-delete own message any time                    → DELETE /chat/messages/{id}

Real-time:
  /api/ws/chat?token=<jwt> — WebSocket; server pushes messages, edits, deletes
  to participants currently connected.

Collections:
  chat_requests : {id, from_user_id, to_user_id, status, message, created_at}
  chat_threads  : {id, participants: [a, b], created_at, last_message_at}
  chat_messages : {id, thread_id, sender_id, text, image_data_url, deleted,
                    edited, created_at, updated_at}
"""
from __future__ import annotations
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set

import jwt
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from pydantic import BaseModel, Field

from core.config import JWT_SECRET, JWT_ALGORITHM
from core.db import db
from core.security import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()

EDIT_WINDOW_MIN = 15


# ============== Models ==============

class ChatRequestIn(BaseModel):
    to_user_id: str = Field(..., min_length=1)
    message: Optional[str] = Field(default="", max_length=300)


class MessageIn(BaseModel):
    text: Optional[str] = Field(default="", max_length=4000)
    image_data_url: Optional[str] = Field(default="", max_length=4_000_000)


class MessagePatch(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


# ============== Helpers ==============

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _serialize(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not doc:
        return None
    doc.pop("_id", None)
    # Convert any datetime to iso
    for k, v in list(doc.items()):
        if isinstance(v, datetime):
            doc[k] = v.isoformat()
    return doc


def _user_brief(u: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not u:
        return {"id": "", "name": "Unknown", "referral_code": "", "avatar": "", "sponsor_code": ""}
    return {
        "id": u.get("id", ""),
        "name": u.get("name") or u.get("email") or "User",
        "referral_code": u.get("referral_code", ""),
        "avatar": u.get("avatar_url") or u.get("avatar", "") or "",
        "sponsor_code": u.get("sponsor_code", ""),
    }


async def _is_downline(target_user_id: str, my_referral_code: str) -> bool:
    """A user is in my downline if their sponsor_code chain eventually
    points to me. For MVP we check direct + 1-hop indirect (cheap).
    Walk up at most 10 levels matching the MLM tree depth."""
    if not my_referral_code:
        return False
    cur = await db.users.find_one({"id": target_user_id}, {"sponsor_code": 1, "id": 1})
    if not cur:
        return False
    code = cur.get("sponsor_code") or ""
    for _ in range(10):
        if not code:
            return False
        if code == my_referral_code:
            return True
        parent = await db.users.find_one({"referral_code": code}, {"sponsor_code": 1})
        if not parent:
            return False
        code = parent.get("sponsor_code") or ""
    return False


async def _participants_canonical(a: str, b: str) -> List[str]:
    return sorted([a, b])


async def _find_or_create_thread(a: str, b: str) -> Dict[str, Any]:
    parts = await _participants_canonical(a, b)
    existing = await db.chat_threads.find_one({"participants": parts})
    if existing:
        return existing
    doc = {
        "id": str(uuid.uuid4()),
        "participants": parts,
        "created_at": _now(),
        "last_message_at": _now(),
    }
    await db.chat_threads.insert_one(doc.copy())
    return doc


# ============== Connection manager (WebSocket) ==============

class _ConnectionManager:
    """In-process registry of active WebSocket connections keyed by user_id."""

    def __init__(self) -> None:
        self._conns: Dict[str, Set[WebSocket]] = {}

    async def connect(self, user_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._conns.setdefault(user_id, set()).add(ws)

    def disconnect(self, user_id: str, ws: WebSocket) -> None:
        s = self._conns.get(user_id)
        if not s:
            return
        s.discard(ws)
        if not s:
            self._conns.pop(user_id, None)

    async def send_to(self, user_ids: List[str], payload: Dict[str, Any]) -> None:
        for uid in user_ids:
            for ws in list(self._conns.get(uid, [])):
                try:
                    await ws.send_json(payload)
                except Exception:
                    self.disconnect(uid, ws)


manager = _ConnectionManager()


# ============== Search / Requests ==============

@router.get("/chat/search")
async def search_by_refcode(code: str = Query(..., min_length=2, max_length=20), user: Dict[str, Any] = Depends(get_current_user)):
    """Find a user by referral code. Returns minimal public info plus a
    `relationship` summary (already_chatting / request_pending / can_request)."""
    clean = code.strip().upper()
    target = await db.users.find_one({"referral_code": clean}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="No user matches that referral code.")
    if target.get("id") == user.get("id"):
        raise HTTPException(status_code=400, detail="That's your own referral code.")
    if (target.get("status") or "approved") not in ("approved", "active"):
        raise HTTPException(status_code=403, detail="That user has not been approved yet.")

    # relationship
    parts = await _participants_canonical(user["id"], target["id"])
    existing_thread = await db.chat_threads.find_one({"participants": parts})
    pending = await db.chat_requests.find_one({
        "$or": [
            {"from_user_id": user["id"], "to_user_id": target["id"], "status": "pending"},
            {"from_user_id": target["id"], "to_user_id": user["id"], "status": "pending"},
        ]
    })
    is_downline = await _is_downline(target["id"], user.get("referral_code") or "")
    relationship = "already_chatting" if existing_thread else ("request_pending" if pending else "can_request")
    return {
        "user": _user_brief(target),
        "relationship": relationship,
        "thread_id": (existing_thread or {}).get("id"),
        "request_id": (pending or {}).get("id"),
        "is_downline": is_downline,
    }


@router.post("/chat/request")
async def send_chat_request(body: ChatRequestIn, user: Dict[str, Any] = Depends(get_current_user)):
    if body.to_user_id == user["id"]:
        raise HTTPException(status_code=400, detail="Can't send a request to yourself.")
    target = await db.users.find_one({"id": body.to_user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="User not found.")
    # Already chatting?
    parts = await _participants_canonical(user["id"], target["id"])
    if await db.chat_threads.find_one({"participants": parts}):
        raise HTTPException(status_code=400, detail="You're already chatting with this user.")
    # Pending?
    pending = await db.chat_requests.find_one({
        "$or": [
            {"from_user_id": user["id"], "to_user_id": target["id"], "status": "pending"},
            {"from_user_id": target["id"], "to_user_id": user["id"], "status": "pending"},
        ]
    })
    if pending:
        return _serialize(pending)
    doc = {
        "id": str(uuid.uuid4()),
        "from_user_id": user["id"],
        "to_user_id": target["id"],
        "status": "pending",
        "message": (body.message or "").strip(),
        "created_at": _now(),
    }
    await db.chat_requests.insert_one(doc.copy())
    # WS notify recipient
    await manager.send_to([target["id"]], {
        "type": "request.new",
        "request": _serialize(dict(doc)),
        "from": _user_brief(user),
    })
    return _serialize(dict(doc))


@router.get("/chat/requests")
async def list_my_requests(user: Dict[str, Any] = Depends(get_current_user)):
    """Pending requests — incoming (to me) and outgoing (from me)."""
    cur_in = db.chat_requests.find({"to_user_id": user["id"], "status": "pending"}).sort("created_at", -1)
    cur_out = db.chat_requests.find({"from_user_id": user["id"], "status": "pending"}).sort("created_at", -1)
    in_list = await cur_in.to_list(50)
    out_list = await cur_out.to_list(50)
    # Hydrate counter-party briefs
    user_ids = list({*(r["from_user_id"] for r in in_list), *(r["to_user_id"] for r in out_list)})
    users = {u["id"]: u for u in await db.users.find({"id": {"$in": user_ids}}, {"_id": 0}).to_list(200)}
    return {
        "incoming": [{**_serialize(dict(r)), "from": _user_brief(users.get(r["from_user_id"]))} for r in in_list],
        "outgoing": [{**_serialize(dict(r)), "to": _user_brief(users.get(r["to_user_id"]))} for r in out_list],
    }


@router.post("/chat/request/{req_id}/accept")
async def accept_request(req_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    r = await db.chat_requests.find_one({"id": req_id, "to_user_id": user["id"], "status": "pending"})
    if not r:
        raise HTTPException(status_code=404, detail="Request not found.")
    thread = await _find_or_create_thread(r["from_user_id"], r["to_user_id"])
    await db.chat_requests.update_one({"id": req_id}, {"$set": {"status": "accepted", "thread_id": thread["id"]}})
    # WS notify both
    await manager.send_to([r["from_user_id"], r["to_user_id"]], {
        "type": "request.accepted",
        "request_id": req_id,
        "thread_id": thread["id"],
    })
    return {"ok": True, "thread_id": thread["id"]}


@router.post("/chat/request/{req_id}/reject")
async def reject_request(req_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    r = await db.chat_requests.find_one({"id": req_id, "to_user_id": user["id"], "status": "pending"})
    if not r:
        raise HTTPException(status_code=404, detail="Request not found.")
    await db.chat_requests.update_one({"id": req_id}, {"$set": {"status": "rejected"}})
    await manager.send_to([r["from_user_id"]], {"type": "request.rejected", "request_id": req_id})
    return {"ok": True}


# ============== Threads / Messages ==============

@router.get("/chat/threads")
async def list_threads(user: Dict[str, Any] = Depends(get_current_user)):
    """Approved chats. Downline threads come first with a `is_downline=true` flag."""
    cursor = db.chat_threads.find({"participants": user["id"]}).sort("last_message_at", -1)
    threads = await cursor.to_list(500)
    other_ids = [next((p for p in t["participants"] if p != user["id"]), None) for t in threads]
    other_ids = [x for x in other_ids if x]
    users = {u["id"]: u for u in await db.users.find({"id": {"$in": other_ids}}, {"_id": 0}).to_list(500)}
    my_code = user.get("referral_code") or ""

    out: List[Dict[str, Any]] = []
    for t in threads:
        other_id = next((p for p in t["participants"] if p != user["id"]), None)
        other = users.get(other_id)
        # Last message preview
        last_msg = await db.chat_messages.find_one({"thread_id": t["id"]}, {"_id": 0}, sort=[("created_at", -1)])
        is_downline = False
        if other:
            is_downline = await _is_downline(other["id"], my_code)
        # Unread count = messages from other that the current user hasn't "read"
        unread = await db.chat_messages.count_documents({
            "thread_id": t["id"], "sender_id": other_id, "deleted": {"$ne": True},
            "read_by": {"$ne": user["id"]},
        })
        out.append({
            "id": t["id"],
            "other": _user_brief(other),
            "is_downline": is_downline,
            "last_message": _serialize(dict(last_msg)) if last_msg else None,
            "unread_count": unread,
            "last_message_at": (t.get("last_message_at") or t.get("created_at")).isoformat() if isinstance(t.get("last_message_at") or t.get("created_at"), datetime) else (t.get("last_message_at") or t.get("created_at")),
        })
    # Sort: downline first, then by last_message_at desc
    out.sort(key=lambda x: (0 if x["is_downline"] else 1, -(_parse_iso(x.get("last_message_at")))))
    return {"threads": out}


def _parse_iso(s: Any) -> float:
    try:
        if isinstance(s, str):
            return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
        if isinstance(s, datetime):
            return s.timestamp()
    except Exception:
        pass
    return 0.0


async def _assert_thread_member(thread_id: str, user_id: str) -> Dict[str, Any]:
    t = await db.chat_threads.find_one({"id": thread_id, "participants": user_id})
    if not t:
        raise HTTPException(status_code=404, detail="Chat not found")
    return t


@router.get("/chat/{thread_id}/messages")
async def list_messages(thread_id: str, before: Optional[str] = None, limit: int = 50, user: Dict[str, Any] = Depends(get_current_user)):
    await _assert_thread_member(thread_id, user["id"])
    limit = max(1, min(200, int(limit or 50)))
    q: Dict[str, Any] = {"thread_id": thread_id}
    if before:
        try:
            q["created_at"] = {"$lt": datetime.fromisoformat(before.replace("Z", "+00:00"))}
        except Exception:
            pass
    cursor = db.chat_messages.find(q, {"_id": 0}).sort("created_at", -1).limit(limit)
    msgs = await cursor.to_list(limit)
    msgs.reverse()
    # Mark all as read for current user
    await db.chat_messages.update_many(
        {"thread_id": thread_id, "sender_id": {"$ne": user["id"]}, "read_by": {"$ne": user["id"]}},
        {"$addToSet": {"read_by": user["id"]}},
    )
    return {"messages": [_serialize(dict(m)) for m in msgs]}


@router.post("/chat/{thread_id}/messages")
async def post_message(thread_id: str, body: MessageIn, user: Dict[str, Any] = Depends(get_current_user)):
    t = await _assert_thread_member(thread_id, user["id"])
    text = (body.text or "").strip()
    img = body.image_data_url or ""
    if not text and not img:
        raise HTTPException(status_code=400, detail="Message can't be empty.")
    doc = {
        "id": str(uuid.uuid4()),
        "thread_id": thread_id,
        "sender_id": user["id"],
        "text": text,
        "image_data_url": img,
        "deleted": False,
        "edited": False,
        "read_by": [user["id"]],
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.chat_messages.insert_one(doc.copy())
    await db.chat_threads.update_one({"id": thread_id}, {"$set": {"last_message_at": _now()}})
    # WS broadcast to both participants
    await manager.send_to(list(t["participants"]), {
        "type": "message.new",
        "thread_id": thread_id,
        "message": _serialize(dict(doc)),
    })
    return _serialize(dict(doc))


@router.patch("/chat/messages/{msg_id}")
async def edit_message(msg_id: str, body: MessagePatch, user: Dict[str, Any] = Depends(get_current_user)):
    m = await db.chat_messages.find_one({"id": msg_id})
    if not m:
        raise HTTPException(status_code=404, detail="Message not found.")
    if m["sender_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="You can only edit your own messages.")
    if m.get("deleted"):
        raise HTTPException(status_code=400, detail="This message was deleted.")
    age = _now() - (m["created_at"] if isinstance(m["created_at"], datetime) else datetime.fromisoformat(m["created_at"]))
    if age > timedelta(minutes=EDIT_WINDOW_MIN):
        raise HTTPException(status_code=400, detail=f"Edit window expired ({EDIT_WINDOW_MIN} min).")
    # Block edit if the other person has already replied AFTER this message
    next_reply = await db.chat_messages.find_one({
        "thread_id": m["thread_id"],
        "sender_id": {"$ne": user["id"]},
        "created_at": {"$gt": m["created_at"]},
        "deleted": {"$ne": True},
    })
    if next_reply:
        raise HTTPException(status_code=400, detail="Can't edit — the other person already replied.")
    new_text = body.text.strip()
    if not new_text:
        raise HTTPException(status_code=400, detail="Edit can't be empty.")
    await db.chat_messages.update_one({"id": msg_id}, {"$set": {"text": new_text, "edited": True, "updated_at": _now()}})
    updated = await db.chat_messages.find_one({"id": msg_id}, {"_id": 0})
    t = await db.chat_threads.find_one({"id": m["thread_id"]})
    if t:
        await manager.send_to(list(t["participants"]), {"type": "message.edited", "thread_id": m["thread_id"], "message": _serialize(dict(updated))})
    return _serialize(dict(updated))


@router.delete("/chat/messages/{msg_id}")
async def delete_message(msg_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    m = await db.chat_messages.find_one({"id": msg_id})
    if not m:
        raise HTTPException(status_code=404, detail="Message not found.")
    if m["sender_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="You can only delete your own messages.")
    await db.chat_messages.update_one({"id": msg_id}, {"$set": {"deleted": True, "text": "", "image_data_url": "", "updated_at": _now()}})
    t = await db.chat_threads.find_one({"id": m["thread_id"]})
    if t:
        await manager.send_to(list(t["participants"]), {"type": "message.deleted", "thread_id": m["thread_id"], "message_id": msg_id})
    return {"ok": True}


# ============== WebSocket ==============

@router.websocket("/ws/chat")
async def websocket_chat(ws: WebSocket, token: str = Query(...)):
    """Real-time delivery channel. Auth: pass JWT as ?token=. The server only
    needs to know which user_id the socket belongs to; all sending happens
    server-side from REST handlers."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        if not user_id or payload.get("type") != "access":
            await ws.close(code=4401)
            return
    except Exception:
        await ws.close(code=4401)
        return
    await manager.connect(user_id, ws)
    try:
        # Send a hello so the client can confirm connection
        await ws.send_json({"type": "hello", "user_id": user_id})
        while True:
            # We don't expect inbound client messages for now (REST handles
            # sending). Keep the socket alive — any inbound is treated as a
            # ping/heartbeat.
            try:
                msg = await ws.receive_text()
                if msg == "ping":
                    await ws.send_text("pong")
            except WebSocketDisconnect:
                break
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(user_id, ws)
