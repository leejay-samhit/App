"""Admin service category CRUD + service analytics dashboard.

Extracted from server.py (2026-05-28). Houses all admin-side endpoints
for managing the `service_categories` collection plus the analytics view
that powers the Service Management dashboard.

Endpoints:
  GET    /admin/service-categories            — list with provider counts
  POST   /admin/service-categories            — create (super_admin / manager)
  PATCH  /admin/service-categories/{cat_id}   — update (super_admin / manager)
  DELETE /admin/service-categories/{cat_id}   — delete or soft-deactivate (super_admin)
  GET    /admin/service-analytics             — dashboard summary
"""
from __future__ import annotations

import re
import uuid
from datetime import timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException

from core.db import db
from core.security import require_admin, require_admin_role
from core.utils import now_utc, audit_log as _audit_log
from models import ServiceCategoryCreate, ServiceCategoryUpdate


router = APIRouter()


# ============================================================
# Service Categories — Admin CRUD
# ============================================================
@router.get("/admin/service-categories")
async def admin_list_service_categories(_: Dict[str, Any] = Depends(require_admin)):
    cats = await db.service_categories.find({}, {"_id": 0}).sort(
        [("sort_order", 1), ("name", 1)]
    ).to_list(200)
    for c in cats:
        c["provider_count"] = await db.users.count_documents({
            "is_service_provider": True,
            "$or": [{"category_id": c["id"]}, {"service_category": c["name"]}],
        })
    return {"categories": cats}


@router.post("/admin/service-categories")
async def admin_create_service_category(
    payload: ServiceCategoryCreate,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "manager")),
):
    name = payload.name.strip()
    slug = (payload.slug or re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"))[:40]
    # Reject duplicates by name or slug
    dup = await db.service_categories.find_one({"$or": [{"name": name}, {"slug": slug}]})
    if dup:
        raise HTTPException(status_code=400, detail=f"Category '{dup.get('name')}' already exists")
    cid = str(uuid.uuid4())
    doc = {
        "id": cid,
        "name": name,
        "slug": slug,
        "icon": payload.icon or "briefcase",
        "color": payload.color or "#2563EB",
        "sort_order": int(payload.sort_order or 0),
        "active": True if payload.active is None else bool(payload.active),
        "image_b64": payload.image_b64 or None,
        "banner_b64": payload.banner_b64 or None,
        "description": (payload.description or "").strip()[:500] if payload.description else None,
        "created_at": now_utc().isoformat(),
    }
    await db.service_categories.insert_one(doc)
    await _audit_log(admin, "service_category.create", "service_category", cid, {"name": name})
    doc.pop("_id", None)
    return {"ok": True, "category": doc}


@router.patch("/admin/service-categories/{cat_id}")
async def admin_update_service_category(
    cat_id: str,
    payload: ServiceCategoryUpdate,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "manager")),
):
    existing = await db.service_categories.find_one({"id": cat_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Category not found")
    update = {k: v for k, v in payload.dict().items() if v is not None}
    if "name" in update:
        update["name"] = update["name"].strip()
    if "slug" in update:
        update["slug"] = re.sub(r"[^a-z0-9]+", "-", update["slug"].lower()).strip("-")[:40]
    if not update:
        raise HTTPException(status_code=400, detail="No fields provided")
    await db.service_categories.update_one({"id": cat_id}, {"$set": update})
    await _audit_log(admin, "service_category.update", "service_category", cat_id, update)
    fresh = await db.service_categories.find_one({"id": cat_id}, {"_id": 0})
    return {"ok": True, "category": fresh}


@router.delete("/admin/service-categories/{cat_id}")
async def admin_delete_service_category(
    cat_id: str,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    existing = await db.service_categories.find_one({"id": cat_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Category not found")
    # Check if any provider is currently linked
    in_use = await db.users.count_documents({"is_service_provider": True, "category_id": cat_id})
    if in_use > 0:
        # Soft-delete instead of hard-delete to avoid orphaning providers
        await db.service_categories.update_one({"id": cat_id}, {"$set": {"active": False}})
        await _audit_log(admin, "service_category.deactivate", "service_category", cat_id, {"in_use": in_use})
        return {"ok": True, "deactivated": True, "providers_using": in_use}
    await db.service_categories.delete_one({"id": cat_id})
    await _audit_log(admin, "service_category.delete", "service_category", cat_id, {"name": existing.get("name")})
    return {"ok": True, "deleted": True}


# ============================================================
# Service Analytics — Admin dashboard
# ============================================================
@router.get("/admin/service-analytics")
async def admin_service_analytics(
    pincode: Optional[str] = None,
    admin: Dict[str, Any] = Depends(require_admin),
):
    """Compact analytics for the Service Management screen.

    Optional `pincode` query parameter filters provider counts and revenue
    to a single area — used by the admin's "live data filter" UI to spot
    coverage gaps and demand pockets by location.

    Returns:
      - provider counts by availability (available / busy / offline / unset)
      - top categories by provider count and recent activity (last 30d)
      - phone-reveal invoice totals (last 30d + lifetime)
      - service application counts by status
    """
    pin_filter: Dict[str, Any] = {}
    if pincode:
        pin_filter["service_pincode"] = pincode.strip()

    # Provider availability bucket (scoped by pincode when provided)
    avail_pipeline = [
        {"$match": {"is_service_provider": True, **pin_filter}},
        {"$group": {"_id": "$availability_status", "count": {"$sum": 1}}},
    ]
    avail_rows = await db.users.aggregate(avail_pipeline).to_list(20)
    avail = {"available": 0, "busy": 0, "offline": 0, "unset": 0}
    for r in avail_rows:
        key = (r.get("_id") or "unset")
        if key not in avail:
            key = "unset"
        avail[key] = int(r.get("count") or 0)

    # Top categories by provider count
    # Fast path (June 2026): batch both groupings up-front instead of N+1
    # count_documents per category (the previous loop made 200+ MongoDB
    # round-trips for analytics — slow under admin load).
    cats = await db.service_categories.find({}, {"_id": 0}).to_list(200)
    counts_by_id: Dict[str, int] = {}
    counts_by_name: Dict[str, int] = {}
    async for r in db.users.aggregate([
        {"$match": {"is_service_provider": True, **pin_filter}},
        {"$group": {"_id": "$category_id", "count": {"$sum": 1}}},
    ]):
        if r.get("_id"):
            counts_by_id[str(r["_id"])] = int(r.get("count") or 0)
    async for r in db.users.aggregate([
        {"$match": {"is_service_provider": True, "category_id": {"$in": [None, ""]}, **pin_filter}},
        {"$group": {"_id": "$service_category", "count": {"$sum": 1}}},
    ]):
        if r.get("_id"):
            counts_by_name[str(r["_id"])] = int(r.get("count") or 0)
    cat_rows = []
    for c in cats:
        cid = c.get("id")
        cnt = int(counts_by_id.get(cid, 0)) + int(counts_by_name.get(c.get("name"), 0))
        cat_rows.append({
            "id": cid, "name": c.get("name"),
            "icon": c.get("icon"), "color": c.get("color"),
            "provider_count": cnt,
            "active": bool(c.get("active", True)),
        })
    cat_rows.sort(key=lambda x: -x["provider_count"])

    # Phone-reveal invoices
    cutoff = (now_utc() - timedelta(days=30)).isoformat()
    last30_cursor = db.phone_reveal_invoices.find({"created_at": {"$gte": cutoff}})
    last30 = await last30_cursor.to_list(2000)
    lifetime_cnt = await db.phone_reveal_invoices.count_documents({})
    reveal_stats = {
        "count_30d":    len(last30),
        "amount_30d":   round(sum(float(r.get("total") or 0) for r in last30), 2),
        "fee_30d":      round(sum(float(r.get("fee") or 0) for r in last30), 2),
        "gst_30d":      round(sum(float(r.get("gst_amount") or 0) for r in last30), 2),
        "count_lifetime": lifetime_cnt,
    }

    # Service applications by status
    app_pipeline = [
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
    ]
    app_rows = await db.service_applications.aggregate(app_pipeline).to_list(20)
    apps = {"pending": 0, "approved": 0, "rejected": 0}
    for r in app_rows:
        s = (r.get("_id") or "pending").lower()
        apps[s] = int(r.get("count") or 0)

    return {
        "availability":  avail,
        "categories":    cat_rows,
        "reveal_stats":  reveal_stats,
        "applications":  apps,
        "generated_at":  now_utc().isoformat(),
    }
