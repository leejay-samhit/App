"""Notification helper.
Extracted from server.py during Phase 2B refactor.

`create_notification` writes a notification document for a user. Routes and
business-logic helpers across the app call this whenever they need to alert
a user (welcome, payout, withdrawal status, ticket replies, etc.).
"""
from __future__ import annotations

import uuid
from typing import Optional

from .db import db
from .utils import now_utc


async def create_notification(
    user_id: str,
    kind: str,
    title: str,
    body: str,
    *,
    extra: Optional[dict] = None,
) -> str:
    """Insert a notification doc and return its id.

    extra: optional dict merged into the notification (e.g. {"ticket_id": ...}).
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
    return doc["id"]
