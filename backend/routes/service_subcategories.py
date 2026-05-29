"""Service Subcategories — CRUD + reorder.

Extracted from server.py (2026-05-28). Self-contained subcategory routes
plus the parent-category reorder helper (kept together because they share
the same admin/drag-drop UX).

Endpoints:
  GET    /service-subcategories                   — public
  GET    /admin/service-subcategories             — admin list
  POST   /admin/service-subcategories             — admin create
  PATCH  /admin/service-subcategories/{sub_id}    — admin update
  DELETE /admin/service-subcategories/{sub_id}    — admin delete
  POST   /admin/service-categories/reorder        — admin reorder parents
  POST   /admin/service-subcategories/reorder     — admin reorder subs
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException

from core.db import db
from core.security import require_admin
from core.utils import now_utc, audit_log as _audit_log
from models import (
    ServiceSubcategoryCreate,
    ServiceSubcategoryUpdate,
    CategoryReorderRequest,
)


router = APIRouter()


@router.get("/service-subcategories")
async def list_service_subcategories(parent_id: Optional[str] = None):
    """Public — used by the user app when picking a sub-category."""
    filt: Dict[str, Any] = {"active": True}
    if parent_id:
        filt["parent_id"] = parent_id
    rows = await db.service_subcategories.find(
        filt, {"_id": 0}
    ).sort([("sort_order", 1), ("name", 1)]).to_list(500)
    return {"items": rows, "total": len(rows)}


@router.get("/admin/service-subcategories")
async def admin_list_service_subcategories(
    parent_id: Optional[str] = None,
    admin: Dict[str, Any] = Depends(require_admin),
):
    filt: Dict[str, Any] = {}
    if parent_id:
        filt["parent_id"] = parent_id
    rows = await db.service_subcategories.find(
        filt, {"_id": 0}
    ).sort([("sort_order", 1), ("name", 1)]).to_list(500)
    return {"items": rows, "total": len(rows)}


@router.post("/admin/service-subcategories")
async def admin_create_subcategory(
    payload: ServiceSubcategoryCreate,
    admin: Dict[str, Any] = Depends(require_admin),
):
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    parent = await db.service_categories.find_one({"id": payload.parent_id})
    if not parent:
        raise HTTPException(status_code=404, detail="Parent category not found")
    slug = (payload.slug or re.sub(r"[^a-z0-9-]+", "-", name.lower())).strip("-")[:60]
    dup = await db.service_subcategories.find_one({"parent_id": payload.parent_id, "name": name})
    if dup:
        raise HTTPException(status_code=400, detail="A subcategory with this name already exists under that parent")
    cnt = await db.service_subcategories.count_documents({"parent_id": payload.parent_id})
    doc = {
        "id":          str(uuid.uuid4()),
        "parent_id":   payload.parent_id,
        "name":        name,
        "slug":        slug,
        "icon":        payload.icon,
        "image_b64":   payload.image_b64,
        "description": (payload.description or "").strip()[:500],
        "sort_order":  payload.sort_order if payload.sort_order is not None else cnt,
        "active":      bool(payload.active),
        "created_at":  now_utc().isoformat(),
    }
    await db.service_subcategories.insert_one(doc)
    doc.pop("_id", None)
    await _audit_log(admin, "service_subcategory.create", "subcategory", doc["id"], {"name": name})
    return {"ok": True, "subcategory": doc}


@router.patch("/admin/service-subcategories/{sub_id}")
async def admin_update_subcategory(
    sub_id: str,
    payload: ServiceSubcategoryUpdate,
    admin: Dict[str, Any] = Depends(require_admin),
):
    existing = await db.service_subcategories.find_one({"id": sub_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Not found")
    update: Dict[str, Any] = {}
    if payload.name is not None:        update["name"] = payload.name.strip()[:80]
    if payload.icon is not None:        update["icon"] = payload.icon
    if payload.image_b64 is not None:   update["image_b64"] = payload.image_b64 or None
    if payload.description is not None: update["description"] = payload.description.strip()[:500]
    if payload.sort_order is not None:  update["sort_order"] = int(payload.sort_order)
    if payload.active is not None:      update["active"] = bool(payload.active)
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    update["updated_at"] = now_utc().isoformat()
    await db.service_subcategories.update_one({"id": sub_id}, {"$set": update})
    fresh = await db.service_subcategories.find_one({"id": sub_id}, {"_id": 0})
    await _audit_log(admin, "service_subcategory.update", "subcategory", sub_id, update)
    return {"ok": True, "subcategory": fresh}


@router.delete("/admin/service-subcategories/{sub_id}")
async def admin_delete_subcategory(
    sub_id: str,
    admin: Dict[str, Any] = Depends(require_admin),
):
    existing = await db.service_subcategories.find_one({"id": sub_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Not found")
    await db.service_subcategories.delete_one({"id": sub_id})
    await _audit_log(admin, "service_subcategory.delete", "subcategory", sub_id, {"name": existing.get("name")})
    return {"ok": True}


@router.post("/admin/service-categories/reorder")
async def admin_reorder_categories(
    payload: CategoryReorderRequest,
    admin: Dict[str, Any] = Depends(require_admin),
):
    """Bulk update `sort_order` on a list of categories — used by admin drag-drop."""
    for it in payload.items[:200]:
        cid = str(it.get("id") or "").strip()
        try:
            so = int(it.get("sort_order") or 0)
        except (TypeError, ValueError):
            continue
        if not cid:
            continue
        await db.service_categories.update_one({"id": cid}, {"$set": {"sort_order": so}})
    await _audit_log(admin, "service_category.reorder", "category", "bulk", {"count": len(payload.items)})
    return {"ok": True, "updated": len(payload.items)}


@router.post("/admin/service-subcategories/reorder")
async def admin_reorder_subcategories(
    payload: CategoryReorderRequest,
    admin: Dict[str, Any] = Depends(require_admin),
):
    for it in payload.items[:500]:
        sid = str(it.get("id") or "").strip()
        try:
            so = int(it.get("sort_order") or 0)
        except (TypeError, ValueError):
            continue
        if not sid:
            continue
        await db.service_subcategories.update_one({"id": sid}, {"$set": {"sort_order": so}})
    return {"ok": True, "updated": len(payload.items)}
