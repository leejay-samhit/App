"""Notification helper.
Extracted from server.py during Phase 2B refactor.

`create_notification` writes a notification document for a user. Routes and
business-logic helpers across the app call this whenever they need to alert
a user (welcome, payout, withdrawal status, ticket replies, etc.).
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from .db import db
from .utils import now_utc

logger = logging.getLogger(__name__)


async def create_notification(
    user_id: str,
    kind: str,
    title: str,
    body: str,
    *,
    extra: Optional[dict] = None,
    push: bool = True,
) -> str:
    """Insert a notification doc and return its id.

    extra: optional dict merged into the notification (e.g. {"ticket_id": ...}).
    push: also deliver it to the phone's notification bar (default). Orders,
    chat and account alerts must reach the tray even when the app is closed —
    an in-app bell row alone is invisible to the user (owner report, Sep 2026).
    Push is best-effort and never raises.
    """
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "kind": kind,
        "title": title,
        "body": body,
        "read": False,
        "created_at": now_utc().isoformat(),
    }
    if extra:
        for k, v in extra.items():
            if k not in doc:
                doc[k] = v
    await db.notifications.insert_one(doc)
    if push:
        try:
            from routes.push import send_push
            data = {"title": title, "message": body[:240]}
            action_url = (extra or {}).get("action_url")
            if action_url:
                data["action_url"] = action_url
            # Map the notification kind onto a preference category so a user
            # who muted "Order updates" doesn't get them through this path
            # either. Unknown kinds stay un-categorised (always delivered).
            category = {
                "order": "orders", "vendor": "orders",
                "chat": "chats",
                "announcement": "offers", "promo": "offers",
                "security": "login_alerts",
            }.get(kind)
            await send_push(
                recipients=[user_id], data=data,
                idempotency_key=f"notif-{doc['id']}", category=category,
            )
        except Exception as e:  # pragma: no cover — push is best-effort
            logger.info(f"notification push skipped: {e}")
    return doc["id"]
