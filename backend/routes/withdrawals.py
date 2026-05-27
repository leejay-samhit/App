"""User-facing withdrawal endpoints.

Carved out of server.py during the Phase 2B modular refactor (2026-05-27).

Currently houses only the READ endpoint /withdrawals/me — the WRITE
endpoint POST /withdrawals stays in server.py for now because it depends
on require_clean_device + the rate-limiter decorator + several helper
constants. Will be extracted once the commission engine itself is
externalised.
"""
from typing import Any, Dict

from fastapi import APIRouter, Depends

from core.db import db
from core.security import get_current_user

router = APIRouter()


@router.get("/withdrawals/me")
async def my_withdrawals(
    user: Dict[str, Any] = Depends(get_current_user),
    limit: int = 0,
    offset: int = 0,
):
    """User withdrawal history. Pagination is opt-in: when limit is omitted
    (or 0) we return the legacy unbounded list (capped at 1000) so existing
    clients keep working. New FE infinite-scroll passes limit=20."""
    cursor = db.withdrawals.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1)
    if limit and limit > 0:
        cursor = cursor.skip(max(0, offset)).limit(min(limit, 200))
        return await cursor.to_list(min(limit, 200))
    return await cursor.to_list(1000)
