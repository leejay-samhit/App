"""
Shop Layout — admin-managed content blocks rendered on the customer Shop tab
between the promo carousel and the products grid.

Block types:
  background      — Full-bleed background image for the Shop screen
  section_header  — A bold sub-category / section title (e.g. "ELECTRONICS")
  text            — A paragraph of free text
  content_box     — A card with title, optional subtitle, optional image,
                    and optional product link (CTA "View")

Endpoints:
  GET    /api/shop-layout                — public, returns active blocks (sorted)
  GET    /api/admin/shop-layout          — admin, returns all blocks
  POST   /api/admin/shop-layout          — admin, create
  PATCH  /api/admin/shop-layout/{id}     — admin, partial update
  DELETE /api/admin/shop-layout/{id}     — admin, delete
"""
from __future__ import annotations
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.db import db
from core.security import require_admin, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()

ALLOWED_TYPES = {"background", "section_header", "text", "content_box"}


class ShopLayoutBlockIn(BaseModel):
    block_type: str = Field(..., min_length=1, max_length=32)
    title: Optional[str] = ""
    subtitle: Optional[str] = ""
    body: Optional[str] = ""
    image_data_url: Optional[str] = Field(None, max_length=4_000_000)
    product_id: Optional[str] = None
    cta_label: Optional[str] = ""
    sort_order: int = 0
    active: bool = True
    size: Optional[str] = "medium"  # small | medium | large (for content_box/background resize)


class ShopLayoutBlockPatch(BaseModel):
    block_type: Optional[str] = None
    title: Optional[str] = None
    subtitle: Optional[str] = None
    body: Optional[str] = None
    image_data_url: Optional[str] = None
    product_id: Optional[str] = None
    cta_label: Optional[str] = None
    sort_order: Optional[int] = None
    active: Optional[bool] = None
    size: Optional[str] = None


def _serialize(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc:
        return {}
    doc.pop("_id", None)
    return doc


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_type(t: Optional[str]) -> str:
    if not t:
        raise HTTPException(status_code=400, detail="block_type is required")
    if t not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail=f"block_type must be one of {sorted(ALLOWED_TYPES)}")
    return t


# ---------- Public ----------

@router.get("/shop-layout")
async def list_active_shop_layout(_: Dict[str, Any] = Depends(get_current_user)):
    cursor = db.shop_layout_blocks.find({"active": True}).sort([("sort_order", 1), ("created_at", 1)])
    items = [_serialize(d) for d in await cursor.to_list(100)]
    return {"items": items}


# ---------- Admin ----------

@router.get("/admin/shop-layout")
async def list_all_shop_layout(_: Dict[str, Any] = Depends(require_admin)):
    cursor = db.shop_layout_blocks.find({}).sort([("sort_order", 1), ("created_at", 1)])
    items = [_serialize(d) for d in await cursor.to_list(500)]
    return {"items": items}


@router.post("/admin/shop-layout")
async def create_shop_layout_block(body: ShopLayoutBlockIn, _: Dict[str, Any] = Depends(require_admin)):
    _validate_type(body.block_type)
    doc = {
        "id": str(uuid.uuid4()),
        "block_type": body.block_type,
        "title": (body.title or "").strip(),
        "subtitle": (body.subtitle or "").strip(),
        "body": (body.body or "").strip(),
        "image_data_url": body.image_data_url or "",
        "product_id": (body.product_id or "").strip() or None,
        "cta_label": (body.cta_label or "").strip(),
        "sort_order": int(body.sort_order or 0),
        "active": bool(body.active),
        "size": (body.size if body.size in ("small", "medium", "large") else "medium"),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.shop_layout_blocks.insert_one(doc.copy())
    return _serialize(doc)


@router.patch("/admin/shop-layout/{block_id}")
async def update_shop_layout_block(block_id: str, body: ShopLayoutBlockPatch, _: Dict[str, Any] = Depends(require_admin)):
    existing = await db.shop_layout_blocks.find_one({"id": block_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Block not found")
    updates: Dict[str, Any] = {}
    payload = body.dict(exclude_unset=True)
    if "block_type" in payload and payload["block_type"] is not None:
        updates["block_type"] = _validate_type(payload["block_type"])
    for f in ("title", "subtitle", "body", "cta_label"):
        if f in payload and payload[f] is not None:
            updates[f] = str(payload[f]).strip()
    if "image_data_url" in payload and payload["image_data_url"] is not None:
        updates["image_data_url"] = payload["image_data_url"]
    if "product_id" in payload:
        v = payload["product_id"]
        updates["product_id"] = (str(v).strip() if v else None) or None
    if "sort_order" in payload and payload["sort_order"] is not None:
        updates["sort_order"] = int(payload["sort_order"])
    if "active" in payload and payload["active"] is not None:
        updates["active"] = bool(payload["active"])
    if "size" in payload and payload["size"] is not None:
        s = str(payload["size"]).lower()
        if s in ("small", "medium", "large"):
            updates["size"] = s
    if updates:
        updates["updated_at"] = _now()
        await db.shop_layout_blocks.update_one({"id": block_id}, {"$set": updates})
    refreshed = await db.shop_layout_blocks.find_one({"id": block_id})
    return _serialize(refreshed)


@router.delete("/admin/shop-layout/{block_id}")
async def delete_shop_layout_block(block_id: str, _: Dict[str, Any] = Depends(require_admin)):
    res = await db.shop_layout_blocks.delete_one({"id": block_id})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Block not found")
    return {"ok": True}
