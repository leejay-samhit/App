"""
Promo Banners — admin-managed swipeable hero slides on the Shop screen.

Schema (MongoDB collection `promo_banners`):
  id              str   uuid
  image_data_url  str   base64 data URL (PNG/JPEG/GIF) — small (<2 MB)
  title           str   primary label (e.g. "Save 70%")
  subtitle        str   supporting text
  cta_label       str   button label (default "Shop now")
  product_id      str?  optional product to link to
  sort_order      int   ascending order (lower = earlier)
  active          bool  visible to customers
  created_at      iso
  updated_at      iso

Endpoints:
  GET    /api/promo-banners          — public, returns active banners (sorted)
  GET    /api/admin/promo-banners    — admin, returns all banners
  POST   /api/admin/promo-banners    — admin, create
  PATCH  /api/admin/promo-banners/{id} — admin, partial update
  DELETE /api/admin/promo-banners/{id} — admin, delete
"""
from __future__ import annotations
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.db import db
from core.security import require_admin, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------- Models ----------

class PromoBannerIn(BaseModel):
    image_data_url: str = Field(..., min_length=10, max_length=4_000_000)
    title: Optional[str] = ""
    subtitle: Optional[str] = ""
    cta_label: Optional[str] = "Shop now"
    product_id: Optional[str] = None
    sort_order: int = 0
    active: bool = True


class PromoBannerPatch(BaseModel):
    image_data_url: Optional[str] = Field(None, min_length=10, max_length=4_000_000)
    title: Optional[str] = None
    subtitle: Optional[str] = None
    cta_label: Optional[str] = None
    product_id: Optional[str] = None
    sort_order: Optional[int] = None
    active: Optional[bool] = None


def _serialize(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc:
        return {}
    doc.pop("_id", None)
    return doc


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- Public ----------

@router.get("/promo-banners")
async def list_active_promo_banners(_: Dict[str, Any] = Depends(get_current_user)):
    """Return active banners sorted by `sort_order` ascending. Used by the Shop screen."""
    cursor = db.promo_banners.find({"active": True}).sort([("sort_order", 1), ("created_at", 1)])
    items = [_serialize(d) for d in await cursor.to_list(50)]
    return {"items": items}


# ---------- Admin ----------

@router.get("/admin/promo-banners")
async def list_all_promo_banners(_: Dict[str, Any] = Depends(require_admin)):
    """Admin: list all banners (active and inactive)."""
    cursor = db.promo_banners.find({}).sort([("sort_order", 1), ("created_at", 1)])
    items = [_serialize(d) for d in await cursor.to_list(200)]
    return {"items": items}


@router.post("/admin/promo-banners")
async def create_promo_banner(body: PromoBannerIn, _: Dict[str, Any] = Depends(require_admin)):
    doc = {
        "id": str(uuid.uuid4()),
        "image_data_url": body.image_data_url,
        "title": (body.title or "").strip(),
        "subtitle": (body.subtitle or "").strip(),
        "cta_label": (body.cta_label or "Shop now").strip(),
        "product_id": (body.product_id or "").strip() or None,
        "sort_order": int(body.sort_order or 0),
        "active": bool(body.active),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.promo_banners.insert_one(doc.copy())
    return _serialize(doc)


@router.patch("/admin/promo-banners/{banner_id}")
async def update_promo_banner(banner_id: str, body: PromoBannerPatch, _: Dict[str, Any] = Depends(require_admin)):
    existing = await db.promo_banners.find_one({"id": banner_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Banner not found")
    updates: Dict[str, Any] = {}
    for field, value in body.dict(exclude_unset=True).items():
        if field in ("title", "subtitle", "cta_label") and value is not None:
            updates[field] = str(value).strip()
        elif field == "product_id":
            updates[field] = (str(value).strip() if value else None) or None
        elif field == "sort_order" and value is not None:
            updates[field] = int(value)
        else:
            updates[field] = value
    if updates:
        updates["updated_at"] = _now()
        await db.promo_banners.update_one({"id": banner_id}, {"$set": updates})
    refreshed = await db.promo_banners.find_one({"id": banner_id})
    return _serialize(refreshed)


@router.delete("/admin/promo-banners/{banner_id}")
async def delete_promo_banner(banner_id: str, _: Dict[str, Any] = Depends(require_admin)):
    res = await db.promo_banners.delete_one({"id": banner_id})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Banner not found")
    return {"ok": True}
