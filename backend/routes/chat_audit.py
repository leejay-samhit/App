"""Chat Records — SUPER-ADMIN-ONLY read-only chat audit + legal export.

Owner requirement (Sep 2026):
    "Whoever registered the app and used Slang-Connect chat, admin can read
     all the text and images. If the user deleted it, still show it. For
     security reasons — if the government asks about two specific users'
     communication we have to produce it to the court. Also download the
     whole chat summary as one .txt file with the user name, sent date/time,
     message, and the other user's reply date/time and message."

Design notes:
  • READ ONLY. There is no write/reply endpoint here on purpose — the
    admin's ability to message users lives in the normal chat routes.
  • Deleted messages: the chat delete handlers now copy the original
    content into `audit_text` / `audit_image_data_url` before wiping the
    live fields, so participants still see "deleted" while this screen can
    recover it. Messages deleted BEFORE that change have no archive and are
    reported as "[DELETED — content not recoverable]".
  • Images are NEVER inlined in the list response (a single base64 photo can
    be 4 MB and edge proxies truncate large bodies). The list returns
    `has_image` and the bytes are served one-at-a-time from
    GET /admin/chat-audit/messages/{id}/image.
  • Every read and every export writes an `audit_log` row — the audit trail
    matters as much as the data when this is produced in court.
"""
from __future__ import annotations

import base64
import binascii
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from core.db import db
from core.security import require_admin_role
from core.utils import audit_log

router = APIRouter()

super_admin_only = require_admin_role("super_admin")

IST = timezone(timedelta(hours=5, minutes=30))


# ============== helpers ==============

def _as_dt(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str):
        try:
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def _iso(v: Any) -> Optional[str]:
    d = _as_dt(v)
    return d.isoformat() if d else None


def _ist(v: Any) -> str:
    d = _as_dt(v)
    return d.astimezone(IST).strftime("%d-%m-%Y %I:%M:%S %p") + " IST" if d else "unknown time"


def _party(u: Optional[Dict[str, Any]], uid: str = "") -> Dict[str, Any]:
    """Full identity of a chat party — this screen is the legal record, so
    unlike the normal chat brief nothing is masked here."""
    if not u:
        return {"id": uid, "name": "Deleted user", "email": "", "phone": "",
                "referral_code": "", "role": "unknown"}
    role = u.get("role") or "user"
    if role == "admin":
        role = f"admin ({u.get('admin_role') or 'super_admin'})"
    elif u.get("is_vendor"):
        role = "vendor"
    elif u.get("is_service_provider"):
        role = "service provider"
    return {
        "id": u.get("id") or uid,
        "name": u.get("name") or u.get("email") or "User",
        "email": u.get("email") or "",
        "phone": u.get("phone") or "",
        "referral_code": u.get("referral_code") or "",
        "role": role,
    }


def _content(m: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve the real content of a message, recovering deleted text/image
    from the compliance archive when the live fields were wiped."""
    deleted = bool(m.get("deleted") or m.get("deleted_for_everyone"))
    text = m.get("text") or ""
    image = m.get("image_data_url") or ""
    recovered = False
    if deleted:
        arch_t = m.get("audit_text") or ""
        arch_i = m.get("audit_image_data_url") or ""
        if arch_t or arch_i:
            text, image, recovered = arch_t, arch_i, True
    return {
        "text": text,
        "has_image": bool(image),
        "deleted": deleted,
        "deleted_for_everyone": bool(m.get("deleted_for_everyone")),
        "recovered": recovered,
        "unrecoverable": deleted and not recovered,
    }


async def _users_by_ids(ids: List[str]) -> Dict[str, Dict[str, Any]]:
    ids = [i for i in set(ids) if i]
    if not ids:
        return {}
    rows = await db.users.find({"id": {"$in": ids}}, {"_id": 0}).to_list(len(ids) + 10)
    return {r["id"]: r for r in rows}


# ============== thread list ==============

@router.get("/admin/chat-audit/threads")
async def audit_threads(
    q: str = Query("", max_length=80, description="Search by name / email / phone / referral code"),
    limit: int = Query(60, ge=1, le=200),
    skip: int = Query(0, ge=0),
    admin: Dict[str, Any] = Depends(super_admin_only),
):
    """Every conversation on the platform (user↔user AND admin↔user)."""
    thread_filter: Dict[str, Any] = {}
    clean = (q or "").strip()
    if clean:
        safe = re.escape(clean)
        matched = await db.users.find(
            {"$or": [
                {"name":          {"$regex": safe, "$options": "i"}},
                {"email":         {"$regex": safe, "$options": "i"}},
                {"phone":         {"$regex": safe, "$options": "i"}},
                {"referral_code": {"$regex": safe, "$options": "i"}},
            ]},
            {"_id": 0, "id": 1},
        ).to_list(500)
        ids = [m["id"] for m in matched]
        if not ids:
            return {"threads": [], "total": 0}
        thread_filter["participants"] = {"$in": ids}

    total = await db.chat_threads.count_documents(thread_filter)
    threads = await db.chat_threads.find(thread_filter, {"_id": 0}).sort(
        "last_message_at", -1
    ).skip(skip).limit(limit).to_list(limit)

    people = await _users_by_ids([p for t in threads for p in (t.get("participants") or [])])

    out: List[Dict[str, Any]] = []
    for t in threads:
        parts = t.get("participants") or []
        total_msgs = await db.chat_messages.count_documents({"thread_id": t["id"]})
        deleted_msgs = await db.chat_messages.count_documents({
            "thread_id": t["id"], "deleted": True,
        })
        media = await db.chat_messages.count_documents({
            "thread_id": t["id"],
            "$or": [
                {"image_data_url": {"$nin": ["", None]}},
                {"audit_image_data_url": {"$nin": ["", None]}},
            ],
        })
        last = await db.chat_messages.find_one(
            {"thread_id": t["id"]}, {"_id": 0}, sort=[("created_at", -1)],
        )
        preview = ""
        if last:
            c = _content(last)
            preview = c["text"][:80] or ("📷 Photo" if c["has_image"] else "")
            if c["deleted"]:
                preview = f"(deleted) {preview}".strip()
        out.append({
            "id": t["id"],
            "participants": [_party(people.get(p), p) for p in parts],
            "is_announcement": bool(t.get("is_announcement")),
            "message_count": total_msgs,
            "deleted_count": deleted_msgs,
            "media_count": media,
            "last_message_at": _iso(t.get("last_message_at") or t.get("created_at")),
            "last_preview": preview,
        })
    return {"threads": out, "total": total}


# ============== single thread transcript ==============

@router.get("/admin/chat-audit/threads/{thread_id}/messages")
async def audit_thread_messages(
    thread_id: str,
    limit: int = Query(500, ge=1, le=2000),
    admin: Dict[str, Any] = Depends(super_admin_only),
):
    t = await db.chat_threads.find_one({"id": thread_id}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Conversation not found")
    people = await _users_by_ids(t.get("participants") or [])
    rows = await db.chat_messages.find({"thread_id": thread_id}, {
        "_id": 0, "audit_image_data_url": 0, "image_data_url": 0,
    }).sort("created_at", 1).limit(limit).to_list(limit)

    # The projection above dropped the image blobs, so re-read only the
    # "does an image exist" flags in one cheap pass.
    with_img = {
        r["id"] for r in await db.chat_messages.find(
            {"thread_id": thread_id, "$or": [
                {"image_data_url": {"$nin": ["", None]}},
                {"audit_image_data_url": {"$nin": ["", None]}},
            ]},
            {"_id": 0, "id": 1},
        ).to_list(limit)
    }

    msgs: List[Dict[str, Any]] = []
    for m in rows:
        c = _content(m)
        sender = people.get(m.get("sender_id"))
        msgs.append({
            "id": m.get("id"),
            "sender_id": m.get("sender_id"),
            "sender_name": (sender or {}).get("name") or "Deleted user",
            "text": c["text"],
            "has_image": m["id"] in with_img,
            "deleted": c["deleted"],
            "recovered": c["recovered"],
            "unrecoverable": c["unrecoverable"],
            "edited": bool(m.get("edited")),
            "reply_to_id": (m.get("reply_to") or {}).get("id"),
            "created_at": _iso(m.get("created_at")),
            "created_at_ist": _ist(m.get("created_at")),
            "deleted_at_ist": _ist(m.get("deleted_at")) if m.get("deleted_at") else None,
        })

    await audit_log(
        admin, "chat_audit.read_thread",
        target_type="chat_thread", target_id=thread_id,
        details={"messages": len(msgs), "participants": t.get("participants")},
    )
    return {
        "thread_id": thread_id,
        "participants": [_party(people.get(p), p) for p in (t.get("participants") or [])],
        "messages": msgs,
        "count": len(msgs),
    }


@router.get("/admin/chat-audit/messages/{msg_id}/image")
async def audit_message_image(
    msg_id: str,
    admin: Dict[str, Any] = Depends(super_admin_only),
):
    """Serve ONE chat photo (including one the sender deleted) as raw bytes."""
    m = await db.chat_messages.find_one({"id": msg_id}, {"_id": 0})
    if not m:
        raise HTTPException(status_code=404, detail="Message not found")
    data_url = m.get("image_data_url") or m.get("audit_image_data_url") or ""
    if not data_url:
        raise HTTPException(status_code=404, detail="No image on this message")
    if data_url.startswith("http"):
        return Response(status_code=307, headers={"Location": data_url})
    match = re.match(r"^data:(?P<mime>[\w/+.-]+);base64,(?P<b64>.+)$", data_url, re.DOTALL)
    if not match:
        raise HTTPException(status_code=415, detail="Unsupported image encoding")
    try:
        raw = base64.b64decode(match.group("b64"))
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=415, detail="Corrupt image data")
    return Response(content=raw, media_type=match.group("mime"),
                    headers={"Cache-Control": "private, max-age=300"})


@router.get("/admin/chat-audit/messages/{msg_id}/image-data")
async def audit_message_image_data(
    msg_id: str,
    admin: Dict[str, Any] = Depends(super_admin_only),
):
    """Same photo as the endpoint above, but returned as a data URL so the
    Expo `<Image>` can render it identically on web and native (an <img>
    tag can't send the Authorization header)."""
    m = await db.chat_messages.find_one({"id": msg_id}, {"_id": 0})
    if not m:
        raise HTTPException(status_code=404, detail="Message not found")
    data_url = m.get("image_data_url") or m.get("audit_image_data_url") or ""
    if not data_url:
        raise HTTPException(status_code=404, detail="No image on this message")
    return {"message_id": msg_id, "data_url": data_url,
            "was_deleted": bool(m.get("deleted"))}


# ============== .txt legal export ==============

_RULE = "-" * 72


def _header(admin: Dict[str, Any], title: str, extra: List[str]) -> List[str]:
    return [
        "SLANGCART — CHAT RECORD (CONFIDENTIAL)",
        title,
        f"Generated at   : {_ist(datetime.now(timezone.utc))}",
        f"Generated by   : {admin.get('email') or admin.get('id')} (super admin)",
        *extra,
        "",
        "Note: messages a participant deleted are included and marked",
        "[DELETED]. All times are India Standard Time (IST).",
        _RULE,
    ]


def _transcript_block(
    parts: List[Dict[str, Any]],
    msgs: List[Dict[str, Any]],
    thread_id: str,
) -> List[str]:
    labels = {p["id"]: chr(65 + i) for i, p in enumerate(parts)}
    names = {p["id"]: p["name"] for p in parts}
    lines: List[str] = [f"Conversation ID: {thread_id}", "Participants:"]
    for p in parts:
        lines.append(
            f"  {labels[p['id']]}) {p['name']} | {p['email'] or 'no email'} | "
            f"{p['phone'] or 'no phone'} | ref {p['referral_code'] or '-'} | "
            f"{p['role']} | user id {p['id']}"
        )
    deleted_n = sum(1 for m in msgs if m["deleted"])
    lines += [
        f"Total messages : {len(msgs)}  (deleted: {deleted_n})",
        _RULE,
        "",
    ]
    order = {m["id"]: i + 1 for i, m in enumerate(msgs)}
    for i, m in enumerate(msgs, start=1):
        sid = m["sender_id"]
        other = next((p["id"] for p in parts if p["id"] != sid), None)
        flags: List[str] = []
        if m["edited"]:
            flags.append("EDITED")
        if m["has_image"]:
            flags.append("PHOTO attached — visible in app")
        if m["reply_to_id"] and order.get(m["reply_to_id"]):
            flags.append(f"REPLY to #{order[m['reply_to_id']]}")
        if m["deleted"]:
            flags.append(
                f"DELETED at {m['deleted_at_ist'] or 'unknown time'}"
                + (" — content recovered" if m["recovered"] else " — content not recoverable")
            )
        flag_str = ("  [" + " | ".join(flags) + "]") if flags else ""
        lines.append(
            f"[{i}] {m['created_at_ist']}  {names.get(sid, m['sender_name'])} "
            f"({labels.get(sid, '?')}) -> {names.get(other, 'other party')} "
            f"({labels.get(other, '?')}){flag_str}"
        )
        body = (m["text"] or "").strip()
        if not body:
            body = "(no text — photo only)" if m["has_image"] else "(empty)"
        for ln in body.splitlines() or [""]:
            lines.append(f"      {ln}")
        lines.append("")
    lines += [_RULE, f"END OF CONVERSATION {thread_id} — {len(msgs)} messages", ""]
    return lines


async def _thread_payload(thread_id: str) -> Optional[Dict[str, Any]]:
    t = await db.chat_threads.find_one({"id": thread_id}, {"_id": 0})
    if not t:
        return None
    people = await _users_by_ids(t.get("participants") or [])
    rows = await db.chat_messages.find({"thread_id": thread_id}, {"_id": 0}).sort(
        "created_at", 1
    ).to_list(5000)
    msgs = []
    for m in rows:
        c = _content(m)
        msgs.append({
            "id": m.get("id"),
            "sender_id": m.get("sender_id"),
            "sender_name": (people.get(m.get("sender_id")) or {}).get("name") or "Deleted user",
            "text": c["text"],
            "has_image": c["has_image"],
            "deleted": c["deleted"],
            "recovered": c["recovered"],
            "edited": bool(m.get("edited")),
            "reply_to_id": (m.get("reply_to") or {}).get("id"),
            "created_at_ist": _ist(m.get("created_at")),
            "deleted_at_ist": _ist(m.get("deleted_at")) if m.get("deleted_at") else None,
        })
    return {
        "thread": t,
        "participants": [_party(people.get(p), p) for p in (t.get("participants") or [])],
        "messages": msgs,
    }


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", s or "").strip("-")[:32] or "user"


@router.get("/admin/chat-audit/threads/{thread_id}/export")
async def export_thread_txt(
    thread_id: str,
    admin: Dict[str, Any] = Depends(super_admin_only),
):
    """One conversation as a plain-text legal record.

    Returns `{filename, content}` so the app can hand it to the browser
    download / native share sheet with the same helper the CSV exports use.
    """
    payload = await _thread_payload(thread_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Conversation not found")
    parts = payload["participants"]
    lines = _header(
        admin,
        "Record type    : single conversation between two users",
        [f"Conversation   : {' <-> '.join(p['name'] for p in parts)}"],
    )
    lines += [""] + _transcript_block(parts, payload["messages"], thread_id)
    content = "\n".join(lines)
    names = "-and-".join(_safe(p["name"]) for p in parts)
    filename = f"slangcart-chat-{names}-{datetime.now(IST).strftime('%Y%m%d-%H%M')}.txt"

    await audit_log(
        admin, "chat_audit.export_thread",
        target_type="chat_thread", target_id=thread_id,
        details={"messages": len(payload["messages"]),
                 "participants": [p["id"] for p in parts]},
    )
    return {"filename": filename, "content": content,
            "message_count": len(payload["messages"])}


@router.get("/admin/chat-audit/users/{user_id}/export")
async def export_user_txt(
    user_id: str,
    admin: Dict[str, Any] = Depends(super_admin_only),
):
    """EVERY conversation one user has taken part in, in a single .txt."""
    u = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    threads = await db.chat_threads.find(
        {"participants": user_id}, {"_id": 0, "id": 1},
    ).sort("last_message_at", -1).to_list(1000)

    subject = _party(u)
    blocks: List[str] = []
    total_msgs = 0
    for t in threads:
        payload = await _thread_payload(t["id"])
        if not payload:
            continue
        total_msgs += len(payload["messages"])
        blocks += _transcript_block(payload["participants"], payload["messages"], t["id"])

    lines = _header(
        admin,
        "Record type    : all conversations of one user",
        [
            f"Subject user   : {subject['name']} | {subject['email'] or 'no email'} | "
            f"{subject['phone'] or 'no phone'} | ref {subject['referral_code'] or '-'} | "
            f"user id {subject['id']}",
            f"Conversations  : {len(threads)}   Messages: {total_msgs}",
        ],
    )
    content = "\n".join(lines + [""] + (blocks or ["(this user has no conversations)"]))
    filename = (
        f"slangcart-chat-all-{_safe(subject['name'])}-"
        f"{datetime.now(IST).strftime('%Y%m%d-%H%M')}.txt"
    )

    await audit_log(
        admin, "chat_audit.export_user",
        target_type="user", target_id=user_id,
        details={"threads": len(threads), "messages": total_msgs},
    )
    return {"filename": filename, "content": content,
            "message_count": total_msgs, "thread_count": len(threads)}
