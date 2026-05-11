"""
Shop Layout Analytics — track impressions & clicks on dynamic blocks so the
admin can see which blocks customers actually engage with.

Collection: `shop_layout_analytics`
  {block_id, scope, event: "impression"|"click", user_id, ts}

Endpoints:
  POST /api/shop-layout/analytics       — public, batched events from mobile
  GET  /api/admin/shop-layout/analytics — admin, aggregated per-block counts
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.db import db
from core.security import require_admin, get_current_user

router = APIRouter()


class AnalyticsEvent(BaseModel):
    block_id: str = Field(..., min_length=1, max_length=64)
    event: str  # "impression" | "click"
    scope: Optional[str] = "home"


class AnalyticsBatch(BaseModel):
    events: List[AnalyticsEvent] = Field(default_factory=list, max_length=200)


@router.post("/shop-layout/analytics")
async def log_analytics(body: AnalyticsBatch, user: Dict[str, Any] = Depends(get_current_user)):
    """Public — batched analytics events from the mobile app."""
    if not body.events:
        return {"ok": True, "logged": 0}
    docs = []
    now = datetime.now(timezone.utc)
    for ev in body.events:
        if ev.event not in ("impression", "click"):
            continue
        docs.append({
            "block_id": ev.block_id,
            "scope": (ev.scope or "home"),
            "event": ev.event,
            "user_id": user.get("id"),
            "ts": now,
        })
    if docs:
        await db.shop_layout_analytics.insert_many(docs)
    return {"ok": True, "logged": len(docs)}


@router.get("/admin/shop-layout/analytics")
async def aggregate_analytics(days: int = 7, _: Dict[str, Any] = Depends(require_admin)):
    """Admin — return per-block impression & click counts over the last N days."""
    days = max(1, min(90, int(days or 7)))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    pipeline = [
        {"$match": {"ts": {"$gte": since}}},
        {"$group": {"_id": {"block_id": "$block_id", "event": "$event"}, "count": {"$sum": 1}}},
    ]
    rows = await db.shop_layout_analytics.aggregate(pipeline).to_list(10000)
    out: Dict[str, Dict[str, int]] = {}
    for r in rows:
        bid = r["_id"]["block_id"]
        ev = r["_id"]["event"]
        out.setdefault(bid, {"impressions": 0, "clicks": 0})
        if ev in ("impression", "click"):
            out[bid][ev + "s"] = int(r["count"])
    # Add CTR
    for bid, stats in out.items():
        imp = stats.get("impressions", 0)
        clk = stats.get("clicks", 0)
        stats["ctr"] = round((clk / imp) * 100, 1) if imp else 0.0
    return {"days": days, "blocks": out}
