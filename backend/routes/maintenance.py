"""Admin-only one-shot maintenance / data-healing endpoints.

Everything here is gated behind `require_admin_role('super_admin')` because
these routes mutate user rows in bulk and must never be exposed to lesser
roles. Idempotent by design — safe to re-run.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends

from core.db import db
from core.security import require_admin_role

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/admin/maintenance/backfill-approval-status")
async def backfill_approval_status(
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    """Copy legacy `users.status` -> `users.approval_status` where missing.

    Older registration flows wrote the bare `status` field; newer code
    (and every admin query that segments the audience for broadcasts /
    payouts) reads `approval_status`. Running this once normalises both
    fields so future queries can rely on `approval_status` alone.
    """
    # 1. Rows that have a legacy `status` but no `approval_status` yet.
    cur = db.users.find(
        {
            "approval_status": {"$exists": False},
            "status": {"$in": ["pending", "approved", "active", "rejected"]},
        },
        {"_id": 0, "id": 1, "status": 1},
    )
    updated = 0
    async for u in cur:
        await db.users.update_one(
            {"id": u["id"]},
            {"$set": {"approval_status": u.get("status")}},
        )
        updated += 1

    # 2. Rows with neither field — default to 'approved' for legacy admin /
    # seed accounts so they don't get accidentally locked out of broadcasts.
    res = await db.users.update_many(
        {
            "approval_status": {"$exists": False},
            "status": {"$exists": False},
            "role": "admin",
        },
        {"$set": {"approval_status": "approved"}},
    )

    logger.info(
        "backfill_approval_status: copied=%d admin_defaulted=%d (by %s)",
        updated, res.modified_count, admin.get("email"),
    )
    return {
        "ok": True,
        "copied_from_status": updated,
        "admin_defaulted": res.modified_count,
    }
