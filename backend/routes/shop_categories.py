"""Shop Categories — admin-managed shop category catalog.

Extracted from hardcoded CATEGORIES in /app/frontend/src/shop-home.tsx so
admins can rename, re-icon, re-image, or delete the customer-facing
category strip without redeploying.

Endpoints (mounted at /api by server.py):
  GET    /shop-categories             — public, returns ACTIVE categories sorted
  GET    /admin/shop-categories       — admin, returns ALL incl. inactive
  POST   /admin/shop-categories       — admin, create
  PUT    /admin/shop-categories/{id}  — admin, partial update
  DELETE /admin/shop-categories/{id}  — admin, soft delete (active=False)
  POST   /admin/shop-categories/seed  — admin, idempotent seed of defaults

Data model (collection: `shop_categories`):
  {
    id: str (uuid),
    name: str,                    # display label, e.g. "Sarees"
    slug: str,                    # url-safe key, e.g. "sarees"
    icon_pack: str,               # "mci" | "feather" | "mat"
    icon_name: str,               # e.g. "hanger" / "user" / "grid-view"
    image_url: str | None,        # data URL (base64) — when set takes precedence
    color: str,                   # bg color hex e.g. "#FCE7F3"
    sort_order: int,
    active: bool,
    created_at: datetime,
    updated_at: datetime,
  }
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.db import db
from core.security import require_admin, get_current_user
from core.utils import audit_log

router = APIRouter(tags=["shop-categories"])


# ── Helpers ──────────────────────────────────────────────────────────
def _slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "category"


def _serialize(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Strip Mongo _id, normalise types for JSON."""
    return {
        "id": doc.get("id"),
        "name": doc.get("name") or "",
        "slug": doc.get("slug") or "",
        "icon_pack": doc.get("icon_pack") or "feather",
        "icon_name": doc.get("icon_name") or "shopping-bag",
        "image_url": doc.get("image_url") or None,
        "color": doc.get("color") or "#E5F2EC",
        "sort_order": int(doc.get("sort_order") or 0),
        "active": bool(doc.get("active", True)),
        "created_at": (doc.get("created_at") or datetime.utcnow()).isoformat() if isinstance(doc.get("created_at"), datetime) else doc.get("created_at"),
        "updated_at": (doc.get("updated_at") or datetime.utcnow()).isoformat() if isinstance(doc.get("updated_at"), datetime) else doc.get("updated_at"),
    }


# ── Default seed list (mirrors shop-home.tsx ALL_CATEGORIES) ─────────
DEFAULT_CATEGORIES: List[Dict[str, Any]] = [
    {"name": "Sarees",      "icon_pack": "mci",     "icon_name": "hanger",                "color": "#FCE7F3"},
    {"name": "Men",         "icon_pack": "mci",     "icon_name": "human-male",            "color": "#DBEAFE"},
    {"name": "Women",       "icon_pack": "mci",     "icon_name": "human-female",          "color": "#FDE68A"},
    {"name": "Kids",        "icon_pack": "mci",     "icon_name": "baby-face",             "color": "#FEE2E2"},
    {"name": "Clothes",     "icon_pack": "mci",     "icon_name": "tshirt-crew",           "color": "#FCE7F3"},
    {"name": "Shoes",       "icon_pack": "mci",     "icon_name": "shoe-sneaker",          "color": "#E0E7FF"},
    {"name": "Accessories", "icon_pack": "mci",     "icon_name": "sunglasses",            "color": "#FFE4E6"},
    {"name": "Electronics", "icon_pack": "mci",     "icon_name": "television",            "color": "#E0E7FF"},
    {"name": "Mobiles",     "icon_pack": "mci",     "icon_name": "cellphone",             "color": "#DBEAFE"},
    {"name": "Laptop",      "icon_pack": "mci",     "icon_name": "laptop",                "color": "#E5E7EB"},
    {"name": "Home",        "icon_pack": "mci",     "icon_name": "sofa",                  "color": "#FFEDD5"},
    {"name": "Beauty",      "icon_pack": "mci",     "icon_name": "lipstick",              "color": "#FCE7F3"},
    {"name": "Grocery",     "icon_pack": "mci",     "icon_name": "cart",                  "color": "#DCFCE7"},
    {"name": "Toys",        "icon_pack": "mci",     "icon_name": "robot-happy",           "color": "#FAE8FF"},
    {"name": "Books",       "icon_pack": "mci",     "icon_name": "book-open-page-variant","color": "#FEF3C7"},
    {"name": "Sports",      "icon_pack": "mci",     "icon_name": "soccer",                "color": "#D1FAE5"},
    {"name": "Health",      "icon_pack": "mci",     "icon_name": "heart-pulse",           "color": "#FFE4E6"},
    {"name": "Pet Care",    "icon_pack": "mci",     "icon_name": "dog",                   "color": "#FDE68A"},
]


async def _ensure_seeded() -> None:
    """Insert default categories if the collection is empty."""
    try:
        count = await db.shop_categories.count_documents({})
        if count > 0:
            return
        now = datetime.utcnow()
        docs = []
        for i, c in enumerate(DEFAULT_CATEGORIES):
            docs.append({
                "id": str(uuid.uuid4()),
                "name": c["name"],
                "slug": _slugify(c["name"]),
                "icon_pack": c["icon_pack"],
                "icon_name": c["icon_name"],
                "image_url": None,
                "color": c["color"],
                "sort_order": i,
                "active": True,
                "created_at": now,
                "updated_at": now,
            })
        if docs:
            await db.shop_categories.insert_many(docs)
    except Exception:
        # Best-effort: never let seeding break startup or requests.
        pass


# ── Schemas ──────────────────────────────────────────────────────────
class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    icon_pack: Optional[str] = Field(default="feather")
    icon_name: Optional[str] = Field(default="shopping-bag")
    image_url: Optional[str] = None
    color: Optional[str] = Field(default="#E5F2EC")
    sort_order: Optional[int] = 999
    active: Optional[bool] = True


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=64)
    icon_pack: Optional[str] = None
    icon_name: Optional[str] = None
    image_url: Optional[str] = None
    color: Optional[str] = None
    sort_order: Optional[int] = None
    active: Optional[bool] = None


# ── Public ───────────────────────────────────────────────────────────
@router.get("/shop-categories")
async def list_public_categories():
    """PUBLIC — returns ACTIVE categories ordered by sort_order then name."""
    await _ensure_seeded()
    cursor = db.shop_categories.find({"active": True}).sort([("sort_order", 1), ("name", 1)])
    docs = await cursor.to_list(length=500)
    return {"items": [_serialize(d) for d in docs]}


# ── Admin ────────────────────────────────────────────────────────────
@router.get("/admin/shop-categories")
async def admin_list_categories(_: Dict[str, Any] = Depends(require_admin)):
    await _ensure_seeded()
    cursor = db.shop_categories.find({}).sort([("sort_order", 1), ("name", 1)])
    docs = await cursor.to_list(length=1000)
    return {"items": [_serialize(d) for d in docs]}


@router.post("/admin/shop-categories")
async def admin_create_category(
    payload: CategoryCreate,
    admin: Dict[str, Any] = Depends(require_admin),
):
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "Name required")
    slug = _slugify(name)
    # Reject duplicates by slug
    if await db.shop_categories.find_one({"slug": slug}):
        raise HTTPException(409, f"Category '{name}' already exists")
    now = datetime.utcnow()
    doc = {
        "id": str(uuid.uuid4()),
        "name": name,
        "slug": slug,
        "icon_pack": (payload.icon_pack or "feather").lower(),
        "icon_name": payload.icon_name or "shopping-bag",
        "image_url": payload.image_url or None,
        "color": payload.color or "#E5F2EC",
        "sort_order": payload.sort_order if payload.sort_order is not None else 999,
        "active": bool(payload.active),
        "created_at": now,
        "updated_at": now,
    }
    await db.shop_categories.insert_one(doc)
    await audit_log(admin, "shop_categories.create", {"id": doc["id"], "name": name})
    return _serialize(doc)


@router.put("/admin/shop-categories/{cat_id}")
async def admin_update_category(
    cat_id: str,
    payload: CategoryUpdate,
    admin: Dict[str, Any] = Depends(require_admin),
):
    doc = await db.shop_categories.find_one({"id": cat_id})
    if not doc:
        raise HTTPException(404, "Category not found")
    update: Dict[str, Any] = {"updated_at": datetime.utcnow()}
    if payload.name is not None:
        new_name = payload.name.strip()
        if not new_name:
            raise HTTPException(400, "Name cannot be empty")
        update["name"] = new_name
        new_slug = _slugify(new_name)
        # If slug changes, ensure no other doc owns it
        if new_slug != doc.get("slug"):
            clash = await db.shop_categories.find_one({"slug": new_slug, "id": {"$ne": cat_id}})
            if clash:
                raise HTTPException(409, f"Category '{new_name}' already exists")
            update["slug"] = new_slug
    if payload.icon_pack is not None:
        update["icon_pack"] = payload.icon_pack.lower()
    if payload.icon_name is not None:
        update["icon_name"] = payload.icon_name
    if payload.image_url is not None:
        # Treat empty string as clear
        update["image_url"] = payload.image_url or None
    if payload.color is not None:
        update["color"] = payload.color
    if payload.sort_order is not None:
        update["sort_order"] = int(payload.sort_order)
    if payload.active is not None:
        update["active"] = bool(payload.active)
    await db.shop_categories.update_one({"id": cat_id}, {"$set": update})
    fresh = await db.shop_categories.find_one({"id": cat_id})
    await audit_log(admin, "shop_categories.update", {"id": cat_id, "changes": {k: v for k, v in update.items() if k != "updated_at"}})
    return _serialize(fresh) if fresh else {"id": cat_id}


@router.delete("/admin/shop-categories/{cat_id}")
async def admin_delete_category(
    cat_id: str,
    admin: Dict[str, Any] = Depends(require_admin),
):
    doc = await db.shop_categories.find_one({"id": cat_id})
    if not doc:
        raise HTTPException(404, "Category not found")
    await db.shop_categories.delete_one({"id": cat_id})
    await audit_log(admin, "shop_categories.delete", {"id": cat_id, "name": doc.get("name")})
    return {"ok": True, "id": cat_id}


@router.post("/admin/shop-categories/seed")
async def admin_seed_defaults(admin: Dict[str, Any] = Depends(require_admin)):
    """Idempotent — only inserts if collection is empty."""
    await _ensure_seeded()
    count = await db.shop_categories.count_documents({})
    return {"ok": True, "total": count}
