"""Suspicious-word flagging for Slang-Connect chats (Sep 2026).

Owner requirement: "Flag chats containing abusive or scam words so you can
review them first."

Two signals land in the `chat_flags` collection:

  • kind="message"          — a message that WAS delivered but matched a
                              scam / abuse pattern (scam wording is never
                              blocked: blocking it would just teach the
                              scammer to rephrase, and we want the evidence).
  • kind="blocked_attempt"  — abusive text the send filter REJECTED. The
                              message never reached the other user, but the
                              attempt itself is the thing an admin wants to
                              see, together with what was typed.

Flag doc shape:
    { id, thread_id, message_id|None, sender_id, kind, categories: [...],
      words: [...], text, status: "open"|"reviewed", created_at,
      reviewed_by, reviewed_at }

One doc per message (upserted), so a re-scan never duplicates rows.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.db import db

logger = logging.getLogger(__name__)


# ── Abuse ────────────────────────────────────────────────────────────────
# Also used by routes/chat.py as the send-time block list.
ABUSE_WORDS = {
    "fuck", "shit", "bitch", "bastard", "asshole", "dick", "pussy",
    "nigger", "faggot", "slut", "whore", "rape", "cunt",
    # Hindi / Telugu transliterations frequently flagged in MLM spam reports
    "madarchod", "behenchod", "chutiya", "lavda", "lund", "gandu",
}

_ABUSE_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in sorted(ABUSE_WORDS)) + r")\b",
    re.IGNORECASE,
)

# ── Scam / fraud wording ────────────────────────────────────────────────
# Phrases, not single words, wherever a single word would be too noisy
# ("bank" alone is fine; "bank details" is not). Every entry is matched
# case-insensitively with word boundaries.
SCAM_PHRASES = [
    # Credential / OTP harvesting
    "otp", "o t p", "one time password", "atm pin", "upi pin", "card pin",
    "cvv", "expiry date", "net banking password", "account password",
    "share your password", "send me your otp", "tell me the otp",
    "aadhaar number", "aadhar number", "pan number", "bank details",
    "account number and ifsc", "screen share", "anydesk", "teamviewer",
    "quick support", "remote access",
    # Money-transfer bait
    "send money", "transfer money", "pay advance", "advance payment",
    "processing fee", "registration fee refund", "scan this qr",
    "scan the qr", "google pay me", "phonepe me", "paytm me",
    "gift card", "amazon gift card", "steam card",
    # Income / investment bait
    "double your money", "double the money", "guaranteed income",
    "guaranteed profit", "guaranteed returns", "risk free income",
    "investment plan", "trading tips", "crypto investment", "usdt",
    "binary trading", "forex tips", "lottery", "you have won",
    "lucky winner", "prize money", "work from home job", "part time job offer",
    # Off-platform pull
    "whatsapp number", "telegram id", "join telegram", "contact me outside",
    "deal outside app", "cash on hand only",
]

_SCAM_RE = re.compile(
    r"(?<!\w)(" + "|".join(re.escape(p) for p in sorted(SCAM_PHRASES)) + r")(?!\w)",
    re.IGNORECASE,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def contains_abuse(text: str) -> bool:
    return bool(text) and bool(_ABUSE_RE.search(text))


def scan(text: str) -> Dict[str, List[str]]:
    """Return {"categories": [...], "words": [...]} for one piece of text."""
    if not text:
        return {"categories": [], "words": []}
    abuse = sorted({m.group(0).lower() for m in _ABUSE_RE.finditer(text)})
    scam = sorted({m.group(0).lower() for m in _SCAM_RE.finditer(text)})
    categories: List[str] = []
    if abuse:
        categories.append("abuse")
    if scam:
        categories.append("scam")
    return {"categories": categories, "words": abuse + scam}


async def flag_message(msg: Dict[str, Any], text: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Scan a delivered message and upsert its flag row. No-op when clean."""
    body = text if text is not None else (msg.get("text") or msg.get("audit_text") or "")
    hit = scan(body)
    if not hit["categories"]:
        return None
    doc = {
        "thread_id": msg.get("thread_id"),
        "message_id": msg.get("id"),
        "sender_id": msg.get("sender_id"),
        "kind": "message",
        "categories": hit["categories"],
        "words": hit["words"],
        "text": body[:500],
        "created_at": msg.get("created_at") or _now(),
    }
    try:
        await db.chat_flags.update_one(
            {"message_id": msg.get("id"), "kind": "message"},
            {"$set": doc, "$setOnInsert": {"id": str(uuid.uuid4()), "status": "open"}},
            upsert=True,
        )
    except Exception as e:  # never break a chat send over a flag write
        logger.warning(f"chat flag write failed (non-blocking): {e}")
        return None
    return doc


async def flag_blocked_attempt(thread_id: str, sender_id: str, text: str) -> None:
    """Record abusive text the send filter refused to deliver."""
    hit = scan(text)
    try:
        await db.chat_flags.insert_one({
            "id": str(uuid.uuid4()),
            "thread_id": thread_id,
            "message_id": None,
            "sender_id": sender_id,
            "kind": "blocked_attempt",
            "categories": hit["categories"] or ["abuse"],
            "words": hit["words"],
            "text": (text or "")[:500],
            "status": "open",
            "created_at": _now(),
        })
    except Exception as e:
        logger.warning(f"blocked-attempt flag write failed (non-blocking): {e}")
