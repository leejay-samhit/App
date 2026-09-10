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
import json
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
from routes.push import send_push

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


# ── Sprint 1 — WhatsApp-style chat upgrade (June 2026) ─────────────────────

class MessageInExt(BaseModel):
    """Extended message body with reply + client-side dedupe key."""
    text: Optional[str] = Field(default="", max_length=4000)
    image_data_url: Optional[str] = Field(default="", max_length=4_000_000)
    reply_to_id: Optional[str] = None
    client_dedupe_key: Optional[str] = Field(default=None, max_length=64)


class ReactionIn(BaseModel):
    emoji: str = Field(..., min_length=1, max_length=8)


class ReportIn(BaseModel):
    target_user_id: str = Field(..., min_length=1)
    reason: Optional[str] = Field(default="", max_length=400)
    message_id: Optional[str] = None


# Minimal offensive-word filter — server-side gate so blocked words can
# never enter chat_messages. Kept short on purpose; expand via admin
# settings later if needed. Match is case-insensitive and word-boundary.
OFFENSIVE_WORDS = {
    "fuck", "shit", "bitch", "bastard", "asshole", "dick", "pussy",
    "nigger", "faggot", "slut", "whore", "rape", "cunt",
    # Hindi/Telugu transliterations frequently flagged in MLM spam reports
    "madarchod", "behenchod", "chutiya", "lavda", "lund", "gandu",
}

import re  # noqa: E402  (kept module-local since the regex is only built once)
_OFFENSIVE_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in OFFENSIVE_WORDS) + r")\b",
    re.IGNORECASE,
)


def _contains_offensive(text: str) -> bool:
    if not text:
        return False
    return bool(_OFFENSIVE_RE.search(text))


# ============== Helpers ==============

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: Any) -> datetime:
    """Coerce a value (ISO string or datetime) into a tz-aware UTC datetime.

    Mongo returns naive UTC datetimes for fields written via Motor; mixing
    those with `_now()` (aware UTC) raises TypeError on subtraction. Normalise
    here so every elapsed-time check works regardless of source.
    """
    if isinstance(dt, str):
        try:
            d = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except Exception:
            return _now()
    elif isinstance(dt, datetime):
        d = dt
    else:
        return _now()
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


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
        return {"id": "", "name": "Unknown", "referral_code": "", "avatar": "", "sponsor_code": "", "is_vendor": False, "is_service_provider": False, "profile_image": None}
    return {
        "id": u.get("id", ""),
        "name": u.get("name") or u.get("email") or "User",
        "referral_code": u.get("referral_code", ""),
        "avatar": u.get("avatar_url") or u.get("avatar", "") or "",
        "sponsor_code": u.get("sponsor_code", ""),
        # Role flags exposed so the chat list can categorize threads
        # (Downline / Vendors / Services / All / Unread). Cheap booleans.
        "is_vendor":            bool(u.get("is_vendor")),
        "is_service_provider":  bool(u.get("is_service_provider")),
        # June 2026 — include the raw profile_image so the chat header /
        # profile-card modal can render the photo. Privacy mask is applied
        # by the calling endpoint via `_apply_user_brief_privacy()` below.
        "profile_image":        u.get("profile_image") or None,
        "profile_visibility":   u.get("profile_visibility") or "everyone",
    }


async def _apply_user_brief_privacy(brief: Dict[str, Any], viewer_id: str) -> Dict[str, Any]:
    """Strip `profile_image` from a `_user_brief()` output when the viewer
    isn't allowed to see it, per `routes/privacy.can_view_profile_image`.
    """
    from routes.privacy import can_view_profile_image  # local import to avoid cycles
    if not brief or not brief.get("id"):
        return brief
    target = {
        "id": brief["id"],
        "is_service_provider": brief.get("is_service_provider"),
        "is_vendor": brief.get("is_vendor"),
        "profile_visibility": brief.get("profile_visibility") or "everyone",
        "profile_image": brief.get("profile_image"),
    }
    if not await can_view_profile_image(viewer_id, target):
        brief.pop("profile_image", None)
        brief["profile_image_hidden"] = True
    return brief


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
        # user_id → thread_id the user currently has OPEN on screen. Used to
        # decide whether a phone push would be redundant. A socket being
        # merely connected is NOT enough: on Android the app keeps a live
        # socket while backgrounded (location service), which used to
        # swallow every chat push (owner report, Sep 2026).
        self._viewing: Dict[str, str] = {}

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

    def is_online(self, user_id: str) -> bool:
        """Truthy if at least one live WS connection exists for this user."""
        return bool(self._conns.get(user_id))

    def set_viewing(self, user_id: str, thread_id: Optional[str]) -> None:
        if thread_id:
            self._viewing[user_id] = thread_id
        else:
            self._viewing.pop(user_id, None)

    def is_viewing(self, user_id: str, thread_id: str) -> bool:
        return self._viewing.get(user_id) == thread_id


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


@router.post("/chat/threads")
async def start_thread(body: Dict[str, Any], user: Dict[str, Any] = Depends(get_current_user)):
    """June 2026 — Service-Provider Start-Chat shortcut.

    The classic chat flow requires sending a `chat_request` and waiting for
    acceptance. For Service Providers we skip that handshake: once the
    customer has paid to reveal the provider's phone (any successful
    `phone_reveal_invoices` row between the two), the chat thread is
    created instantly so the customer can message the provider without
    leaving the screen. Returns the thread doc.
    """
    other_user_id = (body or {}).get("other_user_id") or ""
    if not other_user_id:
        raise HTTPException(status_code=400, detail="other_user_id is required")
    if other_user_id == user["id"]:
        raise HTTPException(status_code=400, detail="Can't chat with yourself.")
    other = await db.users.find_one({"id": other_user_id}, {"_id": 0})
    if not other:
        raise HTTPException(status_code=404, detail="User not found.")

    # Allow if (a) the customer has revealed THIS provider's phone, OR
    # (b) the OTHER user is an approved service provider and the caller
    # has at least one successful reveal of them in `phone_reveal_invoices`.
    # Sep 2026 BUGFIX — this guard looked for `customer_id` + a `status`
    # field, but a paid reveal writes `user_id` and no status at all (see
    # /services/{id}/reveal-phone). So every customer who HAD paid the
    # ₹1.18 fee still got "Reveal the provider's phone first" and Start
    # Chat did nothing. An invoice row only exists after the wallet debit
    # succeeded, so its presence IS the proof of payment.
    if other.get("is_service_provider") or other.get("service_status") == "approved":
        ok = await db.phone_reveal_invoices.find_one({
            "provider_id": other_user_id,
            "$or": [{"user_id": user["id"]}, {"customer_id": user["id"]}],
        })
        if not ok:
            # A zero-fee configuration means chat is free for everyone —
            # admins can set the unlock fee to ₹0 in Service Analytics.
            settings = await db.settings.find_one({"id": "global"}, {"_id": 0, "phone_reveal_fee": 1}) or {}
            fee = float(settings.get("phone_reveal_fee") if settings.get("phone_reveal_fee") is not None else 1.0)
            if fee > 0:
                raise HTTPException(
                    status_code=403,
                    detail="Unlock this provider first to start a chat.",
                )
    else:
        # For non-provider chats keep the existing safety net — must already
        # have an accepted thread or an approved request.
        parts = await _participants_canonical(user["id"], other_user_id)
        existing = await db.chat_threads.find_one({"participants": parts})
        if not existing:
            raise HTTPException(
                status_code=403,
                detail="Send a chat request to this user first.",
            )

    thread = await _find_or_create_thread(user["id"], other_user_id)
    return _serialize(dict(thread))


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

@router.post("/chat/contact-support")
async def contact_support(body: Dict[str, Any] = {}, user: Dict[str, Any] = Depends(get_current_user)):
    """Open chat with the Support Team. Creates / opens approved threads with
    EVERY super_admin AND every admin with admin_role='support' so the user's
    message reaches them all at once (no message broadcasting yet — we just
    auto-create the thread skeletons so the user can pick whichever to chat
    with from the Support tab of their chat list).

    Returns the list of thread IDs created/found so the caller can navigate to
    one of them (typically the first super_admin).
    """
    msg = (body.get("message") if isinstance(body, dict) else "") or ""
    msg = str(msg).strip()[:1000]
    admin_filter = {"role": "admin", "admin_role": {"$in": ["super_admin", "support"]}}
    admins = await db.users.find(admin_filter, {"_id": 0, "id": 1, "name": 1}).to_list(50)
    if not admins:
        # Fallback: any admin
        admins = await db.users.find({"role": "admin"}, {"_id": 0, "id": 1, "name": 1}).to_list(50)
    threads = []
    for a in admins:
        if a["id"] == user["id"]:
            continue
        thread = await _find_or_create_thread(user["id"], a["id"])
        threads.append({"thread_id": thread["id"], "admin_id": a["id"], "admin_name": a.get("name") or "Support"})
        # Auto-send initial message to BOTH super_admin and support so they
        # see the same content immediately (per user request).
        if msg:
            doc = {
                "id":          str(uuid.uuid4()),
                "thread_id":   thread["id"],
                "sender_id":   user["id"],
                "type":        "text",
                "text":        msg,
                "created_at":  _now(),
                "read_by":     [user["id"]],
            }
            await db.chat_messages.insert_one(doc.copy())
            await db.chat_threads.update_one(
                {"id": thread["id"]},
                {"$set": {"last_message_at": _now()}},
            )
            await manager.send_to([a["id"]], {
                "type":   "message.new",
                "thread_id": thread["id"],
                "message": _serialize(dict(doc)),
                "from":   _user_brief(user),
            })
    return {"threads": threads, "count": len(threads)}


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
        brief = _user_brief(other)
        brief = await _apply_user_brief_privacy(brief, user["id"])
        out.append({
            "id": t["id"],
            "other": brief,
            "is_downline": is_downline,
            "is_announcement": bool(t.get("is_announcement")),
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


@router.get("/chat/search/messages")
async def search_messages(
    q: str = Query(..., min_length=2, max_length=80),
    thread_id: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Full-text search across the caller's threads.

    IMPORTANT: this static-prefix route MUST be declared before any
    `/chat/{thread_id}/...` dynamic route — otherwise FastAPI matches
    `search` as the `thread_id` path param and returns 404 (route
    shadowing).
    """
    safe = re.escape(q.strip())
    base: Dict[str, Any] = {
        "text": {"$regex": safe, "$options": "i"},
        "deleted_for_everyone": {"$ne": True},
    }
    if thread_id:
        await _assert_thread_member(thread_id, user["id"])
        base["thread_id"] = thread_id
    else:
        # All threads this user participates in.
        my_threads = await db.chat_threads.find({"participants": user["id"]}, {"_id": 0, "id": 1}).to_list(2000)
        base["thread_id"] = {"$in": [t["id"] for t in my_threads]}
    rows = await db.chat_messages.find(base, {"_id": 0}).sort("created_at", -1).limit(100).to_list(100)
    return {"messages": [_serialize(dict(r)) for r in rows]}


@router.get("/chat/{thread_id}/messages")
async def list_messages(thread_id: str, before: Optional[str] = None, limit: int = 50, user: Dict[str, Any] = Depends(get_current_user)):
    await _assert_thread_member(thread_id, user["id"])
    limit = max(1, min(200, int(limit or 50)))
    q: Dict[str, Any] = {"thread_id": thread_id, "hidden_for_users": {"$ne": user["id"]}}
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
async def post_message(thread_id: str, body: MessageInExt, user: Dict[str, Any] = Depends(get_current_user)):
    t = await _assert_thread_member(thread_id, user["id"])
    text = (body.text or "").strip()
    img = body.image_data_url or ""
    if not text and not img:
        raise HTTPException(status_code=400, detail="Message can't be empty.")

    # ── Announcement thread guard — only super admins may post into a
    # thread that was created as a one-way broadcast channel. Regular
    # users see the thread as read-only on the client; this enforces it
    # server-side as well.
    if t.get("is_announcement"):
        is_super = (user.get("role") == "admin" and
                    (user.get("admin_role") or "super_admin") == "super_admin")
        if not is_super:
            raise HTTPException(
                status_code=403,
                detail="This is a one-way announcements channel — you can't reply here.",
            )

    # ── Offensive-word filter — block on send so the message never lands
    # in chat_messages. Returns 422 (custom) so the client can show a
    # friendly tooltip instead of a generic error.
    if _contains_offensive(text):
        raise HTTPException(status_code=422, detail="Your message contains language that's not allowed.")

    # ── Block list check — both directions. If either party has blocked
    # the other we silently 403 (do not leak which side did the block).
    other_id = next((p for p in t["participants"] if p != user["id"]), None)
    if other_id:
        blocked = await db.chat_blocks.find_one({
            "$or": [
                {"blocker_id": user["id"], "blocked_id": other_id},
                {"blocker_id": other_id,    "blocked_id": user["id"]},
            ]
        })
        if blocked:
            raise HTTPException(status_code=403, detail="You can't message this user right now.")

    # ── Client-side dedupe — same key from the same sender in the last
    # 30 seconds returns the prior doc instead of creating a new one.
    if body.client_dedupe_key:
        recent = await db.chat_messages.find_one({
            "thread_id": thread_id, "sender_id": user["id"],
            "client_dedupe_key": body.client_dedupe_key,
            "created_at": {"$gte": _now() - timedelta(seconds=30)},
        })
        if recent:
            return _serialize(dict(recent))

    # ── Soft rate-limit — max 30 messages / 60s per sender per thread.
    sixty_ago = _now() - timedelta(seconds=60)
    recent_count = await db.chat_messages.count_documents({
        "thread_id": thread_id, "sender_id": user["id"],
        "created_at": {"$gte": sixty_ago},
    })
    if recent_count >= 30:
        raise HTTPException(status_code=429, detail="You're sending messages too fast — slow down.")

    # ── Optional reply quote — embed a snapshot so the bubble survives
    # even if the original message gets deleted later.
    reply_quote: Optional[Dict[str, Any]] = None
    if body.reply_to_id:
        orig = await db.chat_messages.find_one({"id": body.reply_to_id, "thread_id": thread_id})
        if orig and not orig.get("deleted"):
            reply_quote = {
                "id":      orig["id"],
                "sender_id": orig.get("sender_id"),
                "text":    (orig.get("text") or "")[:160],
                "has_image": bool(orig.get("image_data_url")),
            }

    doc = {
        "id": str(uuid.uuid4()),
        "thread_id": thread_id,
        "sender_id": user["id"],
        "text": text,
        "image_data_url": img,
        "deleted": False,
        "deleted_for_everyone": False,
        "edited": False,
        "read_by": [user["id"]],
        # Delivered tracking — populated when recipient's WS receives the
        # `message.new` event or when they next call /messages.
        "delivered_to": [user["id"]],
        "reply_to": reply_quote,
        "reactions": {},      # emoji → [user_ids]
        "starred_by": [],     # user_ids who starred this message
        "client_dedupe_key": body.client_dedupe_key,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.chat_messages.insert_one(doc.copy())
    await db.chat_threads.update_one({"id": thread_id}, {"$set": {"last_message_at": _now()}})

    # If the other party is currently connected via WS, mark delivered now.
    other = other_id or ""
    if other and manager.is_online(other):
        await db.chat_messages.update_one(
            {"id": doc["id"]},
            {"$addToSet": {"delivered_to": other}},
        )
        doc["delivered_to"] = list(set(doc["delivered_to"] + [other]))

    # WS broadcast to both participants
    await manager.send_to(list(t["participants"]), {
        "type": "message.new",
        "thread_id": thread_id,
        "message": _serialize(dict(doc)),
    })

    # ── Sep 2026 — in-app notification for EVERY message ────────────────
    # Only a phone push existed, and it was skipped whenever the recipient
    # had a socket open — so a user who wasn't looking at the chat screen
    # got no bell entry at all and thought chat was broken. The bell row is
    # always written; the push still only fires when they're offline.
    if other_id:
        try:
            from core.notifications import create_notification
            sender = user.get("name") or user.get("email") or "Someone"
            await create_notification(
                other_id, "chat", f"New message from {sender}",
                (text if text else "📷 Photo")[:180],
                extra={"thread_id": thread_id, "action_url": f"/chat/{thread_id}"},
                # The tray push is fired below with the "is the user reading
                # this thread right now?" check — don't double-send here.
                push=False,
            )
        except Exception as e:
            logger.warning(f"chat notification failed (non-blocking): {e}")

    # ── Push notification to the recipient (best-effort, never blocks).
    # Only skipped when they literally have THIS thread open on screen —
    # a merely-connected socket (backgrounded app) still gets the push.
    if other_id and not manager.is_viewing(other_id, thread_id):
        try:
            sender_name = user.get("name") or "Someone"
            preview = text if text else "📷 Photo"
            await send_push(
                recipients=[other_id],
                data={
                    "title":      f"💬 {sender_name}",
                    "message":    preview[:240],
                    "action_url": f"/chat/{thread_id}",
                },
                idempotency_key=f"chat-{doc['id']}",
            )
        except Exception as e:
            logger.warning(f"chat push failed (non-blocking): {e}")

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
    age = _now() - _as_utc(m["created_at"])
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
    # Sep 2026 — COMPLIANCE ARCHIVE. The live `text` / `image_data_url` are
    # still wiped so both chat participants see "deleted", but the original
    # content is copied into `audit_*` fields which ONLY the super-admin
    # Chat Records screen can read (routes/chat_audit.py). Required so the
    # platform can produce a conversation on a lawful request.
    await db.chat_messages.update_one({"id": msg_id}, {"$set": {
        "deleted": True,
        "text": "", "image_data_url": "",
        "audit_text": m.get("audit_text") or m.get("text") or "",
        "audit_image_data_url": m.get("audit_image_data_url") or m.get("image_data_url") or "",
        "deleted_at": _now(),
        "deleted_by": user["id"],
        "updated_at": _now(),
    }})
    t = await db.chat_threads.find_one({"id": m["thread_id"]})
    if t:
        await manager.send_to(list(t["participants"]), {"type": "message.deleted", "thread_id": m["thread_id"], "message_id": msg_id})
    return {"ok": True}


@router.delete("/chat/{thread_id}/messages")
async def clear_thread_messages(
    thread_id: str,
    scope: str = "me",
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Clear ALL messages in a thread.

    scope=me        → hide the messages (and any starred / media) from the
                       current viewer only; the other party still sees them.
                       Implemented by appending the user's id to a
                       `hidden_for_users` array on every message.
    scope=everyone → soft-delete every message for BOTH sides. Also wipes
                       images, text, reactions, and starred-by lists so
                       shared-media + starred summaries reset on both
                       sides. Cannot be undone.
    """
    t = await _assert_thread_member(thread_id, user["id"])
    scope = (scope or "me").lower().strip()
    if scope not in ("me", "everyone"):
        raise HTTPException(status_code=400, detail="scope must be 'me' or 'everyone'.")

    if scope == "me":
        # Append this user to hidden_for_users on every message in the
        # thread (idempotent — $addToSet). Also remove them from starred_by
        # so their starred summary resets.
        await db.chat_messages.update_many(
            {"thread_id": thread_id},
            {
                "$addToSet": {"hidden_for_users": user["id"]},
                "$pull": {"starred_by": user["id"]},
                "$set": {"updated_at": _now()},
            },
        )
        return {"ok": True, "scope": "me"}

    # scope == "everyone" — wipe for both sides. Content is archived into
    # `audit_*` first (compliance — see delete_message above).
    async for m in db.chat_messages.find(
        {"thread_id": thread_id, "audit_text": {"$exists": False}},
        {"_id": 0, "id": 1, "text": 1, "image_data_url": 1},
    ):
        await db.chat_messages.update_one({"id": m["id"]}, {"$set": {
            "audit_text": m.get("text") or "",
            "audit_image_data_url": m.get("image_data_url") or "",
        }})
    await db.chat_messages.update_many(
        {"thread_id": thread_id},
        {
            "$set": {
                "deleted": True,
                "deleted_for_everyone": True,
                "text": "",
                "image_data_url": "",
                "reactions": {},
                "starred_by": [],
                "deleted_at": _now(),
                "deleted_by": user["id"],
                "updated_at": _now(),
            },
        },
    )
    await manager.send_to(
        list(t["participants"]),
        {"type": "thread.cleared", "thread_id": thread_id, "by": user["id"]},
    )
    return {"ok": True, "scope": "everyone"}


@router.get("/chat/{thread_id}/details")
async def thread_details(thread_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    """June 2026 — header tap shows the 'other party' profile-card.

    Returns the masked user brief PLUS aggregate counts the chat
    UI surfaces (media shared, starred by me) so the modal can render
    all of it in one round-trip.
    """
    t = await _assert_thread_member(thread_id, user["id"])
    other_id = next((p for p in t["participants"] if p != user["id"]), None)
    other_doc = await db.users.find_one({"id": other_id}) if other_id else None
    brief = _user_brief(other_doc)
    brief = await _apply_user_brief_privacy(brief, user["id"])

    media_count = await db.chat_messages.count_documents({
        "thread_id": thread_id,
        "image_data_url": {"$exists": True, "$ne": ""},
        "deleted_for_everyone": {"$ne": True},
        "hidden_for_users": {"$ne": user["id"]},
    })
    starred_count = await db.chat_messages.count_documents({
        "thread_id": thread_id,
        "starred_by": user["id"],
        "deleted_for_everyone": {"$ne": True},
        "hidden_for_users": {"$ne": user["id"]},
    })
    return {
        "thread_id": thread_id,
        "other": brief,
        "is_announcement": bool(t.get("is_announcement")),
        "media_count": media_count,
        "starred_count": starred_count,
    }


@router.get("/chat/{thread_id}/media")
async def thread_media(thread_id: str, limit: int = 200, user: Dict[str, Any] = Depends(get_current_user)):
    """All image attachments in this thread (chronological)."""
    await _assert_thread_member(thread_id, user["id"])
    rows = await db.chat_messages.find(
        {
            "thread_id": thread_id,
            "image_data_url": {"$exists": True, "$ne": ""},
            "deleted_for_everyone": {"$ne": True},
            "hidden_for_users": {"$ne": user["id"]},
        },
        {"_id": 0},
    ).sort("created_at", -1).limit(max(1, min(int(limit or 200), 500))).to_list(500)
    return {"messages": [_serialize(dict(r)) for r in rows]}


# ============== Sprint 1 — Reactions / Star / Pin / Block / Report / Search ==============

@router.post("/chat/messages/{msg_id}/react")
async def toggle_reaction(msg_id: str, body: ReactionIn, user: Dict[str, Any] = Depends(get_current_user)):
    """Toggle this user's emoji reaction on a message. Sending the same
    emoji a second time removes it; a new emoji replaces the previous one
    (one reaction per user per message — WhatsApp/Insta style)."""
    m = await db.chat_messages.find_one({"id": msg_id})
    if not m or m.get("deleted_for_everyone"):
        raise HTTPException(status_code=404, detail="Message not found.")
    await _assert_thread_member(m["thread_id"], user["id"])
    reactions: Dict[str, List[str]] = dict(m.get("reactions") or {})
    # Remove this user from every emoji bucket first.
    for emo in list(reactions.keys()):
        if user["id"] in reactions[emo]:
            reactions[emo] = [u for u in reactions[emo] if u != user["id"]]
            if not reactions[emo]:
                reactions.pop(emo)
    # Toggle on if the user hadn't already had this exact emoji.
    if body.emoji not in (m.get("reactions") or {}) or user["id"] not in ((m.get("reactions") or {}).get(body.emoji) or []):
        reactions.setdefault(body.emoji, []).append(user["id"])
    await db.chat_messages.update_one({"id": msg_id}, {"$set": {"reactions": reactions, "updated_at": _now()}})
    t = await db.chat_threads.find_one({"id": m["thread_id"]})
    if t:
        await manager.send_to(list(t["participants"]), {"type": "message.reacted", "thread_id": m["thread_id"], "message_id": msg_id, "reactions": reactions})
    return {"ok": True, "reactions": reactions}


@router.post("/chat/messages/{msg_id}/star")
async def toggle_star(msg_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    """Toggle star (per-user, like Gmail/WhatsApp). Starred list endpoint below."""
    m = await db.chat_messages.find_one({"id": msg_id})
    if not m:
        raise HTTPException(status_code=404, detail="Message not found.")
    await _assert_thread_member(m["thread_id"], user["id"])
    starred = list(m.get("starred_by") or [])
    if user["id"] in starred:
        starred.remove(user["id"])
        starred_now = False
    else:
        starred.append(user["id"])
        starred_now = True
    await db.chat_messages.update_one({"id": msg_id}, {"$set": {"starred_by": starred}})
    return {"ok": True, "starred": starred_now}


@router.get("/chat/starred")
async def list_starred(limit: int = 100, user: Dict[str, Any] = Depends(get_current_user)):
    rows = await db.chat_messages.find(
        {"starred_by": user["id"], "deleted_for_everyone": {"$ne": True}, "hidden_for_users": {"$ne": user["id"]}},
        {"_id": 0},
    ).sort("created_at", -1).limit(max(1, min(int(limit or 100), 500))).to_list(500)
    return {"messages": [_serialize(dict(r)) for r in rows]}


@router.post("/chat/threads/{thread_id}/pin")
async def toggle_pin(thread_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    t = await _assert_thread_member(thread_id, user["id"])
    pinned = list(t.get("pinned_by") or [])
    if user["id"] in pinned:
        pinned.remove(user["id"])
        now_pinned = False
    else:
        pinned.append(user["id"])
        now_pinned = True
    await db.chat_threads.update_one({"id": thread_id}, {"$set": {"pinned_by": pinned}})
    return {"ok": True, "pinned": now_pinned}


# ── Mark delivered (called on WS receive or on first /messages fetch) ──
@router.post("/chat/{thread_id}/delivered")
async def mark_delivered(thread_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    await _assert_thread_member(thread_id, user["id"])
    res = await db.chat_messages.update_many(
        {"thread_id": thread_id, "sender_id": {"$ne": user["id"]}, "delivered_to": {"$ne": user["id"]}},
        {"$addToSet": {"delivered_to": user["id"]}},
    )
    t = await db.chat_threads.find_one({"id": thread_id})
    if t and res.modified_count:
        await manager.send_to(list(t["participants"]), {
            "type": "message.delivered", "thread_id": thread_id, "by_user_id": user["id"],
        })
    return {"ok": True, "count": res.modified_count}


# ── Typing indicator (WS-only fanout, no DB row) ──
@router.post("/chat/{thread_id}/typing")
async def typing_ping(thread_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    t = await _assert_thread_member(thread_id, user["id"])
    others = [p for p in t["participants"] if p != user["id"]]
    await manager.send_to(others, {
        "type": "typing", "thread_id": thread_id, "user_id": user["id"], "at": _now().isoformat(),
    })
    return {"ok": True}


# ── Online / last-seen for the OTHER party of a thread ──
@router.get("/chat/{thread_id}/presence")
async def thread_presence(thread_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    t = await _assert_thread_member(thread_id, user["id"])
    other_id = next((p for p in t["participants"] if p != user["id"]), None)
    if not other_id:
        return {"online": False, "last_seen": None}
    online = manager.is_online(other_id)
    last_seen = None
    if not online:
        u = await db.users.find_one({"id": other_id}, {"_id": 0, "last_seen_at": 1})
        last_seen = (u or {}).get("last_seen_at")
        if isinstance(last_seen, datetime):
            last_seen = last_seen.isoformat()
    return {"online": online, "last_seen": last_seen}


# ── Block / Unblock ──
@router.post("/chat/block/{target_user_id}")
async def block_user(target_user_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    if target_user_id == user["id"]:
        raise HTTPException(status_code=400, detail="Can't block yourself.")
    await db.chat_blocks.update_one(
        {"blocker_id": user["id"], "blocked_id": target_user_id},
        {"$set": {"blocker_id": user["id"], "blocked_id": target_user_id, "created_at": _now()}},
        upsert=True,
    )
    return {"ok": True}


@router.delete("/chat/block/{target_user_id}")
async def unblock_user(target_user_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    await db.chat_blocks.delete_one({"blocker_id": user["id"], "blocked_id": target_user_id})
    return {"ok": True}


@router.get("/chat/blocks")
async def list_blocks(user: Dict[str, Any] = Depends(get_current_user)):
    rows = await db.chat_blocks.find({"blocker_id": user["id"]}, {"_id": 0}).to_list(500)
    return {"blocks": [_serialize(dict(r)) for r in rows]}


# ── Report ──
@router.post("/chat/report")
async def report_user(body: ReportIn, user: Dict[str, Any] = Depends(get_current_user)):
    if body.target_user_id == user["id"]:
        raise HTTPException(status_code=400, detail="Can't report yourself.")
    doc = {
        "id": str(uuid.uuid4()),
        "reporter_id": user["id"],
        "target_user_id": body.target_user_id,
        "reason": (body.reason or "").strip(),
        "message_id": body.message_id,
        "status": "open",
        "created_at": _now(),
    }
    await db.chat_reports.insert_one(doc.copy())
    return _serialize(dict(doc))


# ── Search messages — the canonical implementation lives earlier in this
# file (above the `/chat/{thread_id}/...` dynamic routes). The duplicate
# declaration that previously sat here triggered FastAPI's "Duplicate
# Operation ID" warning at startup, so it has been removed.


# ── "Delete for everyone" — only the sender, within 1 hour ──
DELETE_FOR_EVERYONE_WINDOW = timedelta(hours=1)


@router.delete("/chat/messages/{msg_id}/for-everyone")
async def delete_for_everyone(msg_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    m = await db.chat_messages.find_one({"id": msg_id})
    if not m:
        raise HTTPException(status_code=404, detail="Message not found.")
    if m["sender_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="You can only delete your own messages.")
    created = _as_utc(m["created_at"])
    if _now() - created > DELETE_FOR_EVERYONE_WINDOW:
        raise HTTPException(status_code=400, detail="The 1-hour window for delete-for-everyone has passed.")
    await db.chat_messages.update_one(
        {"id": msg_id},
        {"$set": {
            "deleted": True, "deleted_for_everyone": True,
            "text": "", "image_data_url": "",
            "audit_text": m.get("audit_text") or m.get("text") or "",
            "audit_image_data_url": m.get("audit_image_data_url") or m.get("image_data_url") or "",
            "deleted_at": _now(),
            "deleted_by": user["id"],
            "updated_at": _now(),
        }},
    )
    t = await db.chat_threads.find_one({"id": m["thread_id"]})
    if t:
        await manager.send_to(list(t["participants"]), {
            "type": "message.deleted", "thread_id": m["thread_id"], "message_id": msg_id, "for_everyone": True,
        })
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
    # Track presence — bump last_seen_at on connect AND disconnect so the
    # "Last seen N min ago" string is always fresh.
    try:
        await db.users.update_one({"id": user_id}, {"$set": {"last_seen_at": _now()}})
    except Exception:
        pass
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
                    continue
                # {"type":"viewing","thread_id":"…"|null} — the app tells us
                # which thread is on screen so we don't push a message the
                # user is already reading.
                try:
                    data = json.loads(msg)
                except Exception:
                    data = None
                if isinstance(data, dict) and data.get("type") == "viewing":
                    manager.set_viewing(user_id, data.get("thread_id") or None)
            except WebSocketDisconnect:
                break
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(user_id, ws)
        manager.set_viewing(user_id, None)
        try:
            await db.users.update_one({"id": user_id}, {"$set": {"last_seen_at": _now()}})
        except Exception:
            pass
