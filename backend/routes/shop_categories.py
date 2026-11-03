"""Shop Categories — admin-managed shop category catalog.

Extracted from hardcoded CATEGORIES in /app/frontend/src/shop-home.tsx so
admins can rename, re-icon, re-image, or delete the customer-facing
category strip without redeploying.

Endpoints (mounted at /api by server.py):
  GET    /shop-categories             — public, returns ACTIVE root categories
  GET    /shop-categories/tree        — public, returns nested tree
  GET    /shop-categories/{id}/subcategories — public, direct children
  GET    /shop-categories/{id}/descendants   — public, ALL descendant ids
  GET    /admin/shop-categories       — admin, returns ALL incl. inactive
  POST   /admin/shop-categories       — admin, create (optional parent_id → subcategory)
  PUT    /admin/shop-categories/{id}  — admin, partial update (parent_id supported)
  DELETE /admin/shop-categories/{id}  — admin, hard delete + orphaned children re-parented
  POST   /admin/shop-categories/seed  — admin, idempotent seed of defaults

Data model (collection: `shop_categories`):
  {
    id: str (uuid),
    name: str,                    # display label
    slug: str,                    # url-safe key
    parent_id: str | None,        # ← Nov 2026: unlimited nesting
    depth: int,                   # ← denormalised — 0 = root, 1 = child, …
    icon_pack: str,
    icon_name: str,
    image_url: str | None,
    color: str,
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
from core.security import require_admin
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
        # ── Nov 2026: hierarchy fields ──
        "parent_id": doc.get("parent_id") or None,
        "depth": int(doc.get("depth") or 0),
        "icon_pack": doc.get("icon_pack") or "feather",
        "icon_name": doc.get("icon_name") or "shopping-bag",
        "image_url": doc.get("image_url") or None,
        "color": doc.get("color") or "#E5F2EC",
        "sort_order": int(doc.get("sort_order") or 0),
        "active": bool(doc.get("active", True)),
        "created_at": (doc.get("created_at") or datetime.utcnow()).isoformat() if isinstance(doc.get("created_at"), datetime) else doc.get("created_at"),
        "updated_at": (doc.get("updated_at") or datetime.utcnow()).isoformat() if isinstance(doc.get("updated_at"), datetime) else doc.get("updated_at"),
    }


async def _compute_depth(parent_id: Optional[str]) -> int:
    if not parent_id:
        return 0
    parent = await db.shop_categories.find_one({"id": parent_id}, {"depth": 1})
    if not parent:
        return 0
    return int(parent.get("depth") or 0) + 1


async def _collect_descendants(cat_id: str) -> List[str]:
    """Return the ids of every descendant of `cat_id` (excluding itself).
    Walks the tree breadth-first — safe for unlimited nesting."""
    out: List[str] = []
    frontier = [cat_id]
    seen = {cat_id}
    while frontier:
        cursor = db.shop_categories.find({"parent_id": {"$in": frontier}}, {"id": 1})
        next_layer: List[str] = []
        async for c in cursor:
            cid = c.get("id")
            if cid and cid not in seen:
                seen.add(cid); out.append(cid); next_layer.append(cid)
        frontier = next_layer
    return out


async def _collect_names_in_subtree(cat_id: str) -> List[str]:
    """Return the display names of `cat_id` and all its descendants — used
    to cascade product filtering (a product tagged with a leaf category
    still shows up when the customer taps its ancestor)."""
    ids = [cat_id] + await _collect_descendants(cat_id)
    if not ids:
        return []
    names: List[str] = []
    async for c in db.shop_categories.find({"id": {"$in": ids}}, {"name": 1, "slug": 1}):
        n = (c.get("name") or "").strip()
        if n and n not in names: names.append(n)
    return names


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


async def _ensure_indexes() -> None:
    """Create indexes required for the hierarchy + fast product lookups.

    Cheap to call on every seed — MongoDB de-dupes."""
    try:
        await db.shop_categories.create_index("parent_id")
        await db.shop_categories.create_index("slug", unique=False)
        await db.shop_categories.create_index([("active", 1), ("sort_order", 1)])
        # Product-side helpers used by cascading filter
        await db.products.create_index("category")
        await db.products.create_index("subcategory")
        await db.products.create_index("is_published")
    except Exception:
        pass


async def _ensure_seeded() -> None:
    """Insert default categories ONCE on first ever boot.

    Also backfills the `parent_id` / `depth` fields introduced in Nov 2026
    on legacy documents so `_serialize` never returns `None` for depth.
    """
    try:
        await _ensure_indexes()
        marker = await db.app_state.find_one({"_id": "shop_categories_seeded"})
        if not marker:
            count = await db.shop_categories.count_documents({})
            if count > 0:
                await db.app_state.update_one(
                    {"_id": "shop_categories_seeded"},
                    {"$set": {"at": datetime.utcnow(), "reason": "preexisting_data"}},
                    upsert=True,
                )
            else:
                now = datetime.utcnow()
                docs = []
                for i, c in enumerate(DEFAULT_CATEGORIES):
                    docs.append({
                        "id": str(uuid.uuid4()),
                        "name": c["name"],
                        "slug": _slugify(c["name"]),
                        "parent_id": None,
                        "depth": 0,
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
                await db.app_state.update_one(
                    {"_id": "shop_categories_seeded"},
                    {"$set": {"at": now, "reason": "first_boot_seed", "count": len(docs)}},
                    upsert=True,
                )
        # ── One-shot backfill of hierarchy fields on legacy docs ──
        await db.shop_categories.update_many(
            {"parent_id": {"$exists": False}},
            {"$set": {"parent_id": None, "depth": 0}},
        )
    except Exception:
        # Best-effort: never let seeding break startup or requests.
        pass


# ── Schemas ──────────────────────────────────────────────────────────
class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    parent_id: Optional[str] = None
    icon_pack: Optional[str] = Field(default="feather")
    icon_name: Optional[str] = Field(default="shopping-bag")
    image_url: Optional[str] = None
    color: Optional[str] = Field(default="#E5F2EC")
    sort_order: Optional[int] = 999
    active: Optional[bool] = True


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=64)
    parent_id: Optional[str] = None  # empty string / null = move to root
    icon_pack: Optional[str] = None
    icon_name: Optional[str] = None
    image_url: Optional[str] = None
    color: Optional[str] = None
    sort_order: Optional[int] = None
    active: Optional[bool] = None


# ── Public ───────────────────────────────────────────────────────────
RECHARGE_ROOT_NAMES = {"recharge", "recharges", "mobile recharge", "dth tv recharge"}


async def _recharge_category_ids() -> set:
    """Ids of the Recharge root and everything under it.

    Nov-2026 — Recharge is sold through its own flow (plans, operators,
    circles), not as a shop product, so it must not appear in the Shop Layout
    pickers or in the customer-facing category lists. The categories stay in
    the database: the recharge services, plans, transactions and payment
    flows are untouched.
    """
    roots = await db.shop_categories.find(
        {"$or": [
            {"name": {"$in": [n.title() for n in RECHARGE_ROOT_NAMES]}},
            {"recharge_group": {"$nin": [None, ""]}},
            {"recharge_kind": {"$nin": [None, ""]}},
        ]},
        {"_id": 0, "id": 1, "name": 1, "parent_id": 1},
    ).to_list(200)
    ids = {r["id"] for r in roots if (r.get("name") or "").strip().lower() in RECHARGE_ROOT_NAMES
           or r.get("parent_id") is None}
    ids |= {r["id"] for r in roots}
    if not ids:
        return set()
    # Walk down: every descendant of a recharge root is a recharge category.
    frontier = set(ids)
    for _ in range(6):  # depth guard
        kids = await db.shop_categories.find(
            {"parent_id": {"$in": list(frontier)}}, {"_id": 0, "id": 1},
        ).to_list(500)
        new = {k["id"] for k in kids} - ids
        if not new:
            break
        ids |= new
        frontier = new
    return ids


@router.get("/shop-categories")
async def list_public_categories(root_only: bool = True):
    """PUBLIC — returns ACTIVE categories.

    Default: only ROOT (top-level) categories so the customer Shop tab
    stays clean.  Pass `?root_only=false` to include children (flat
    list, still ordered by `sort_order → name`).

    Recharge categories are excluded — see `_recharge_category_ids`.
    """
    await _ensure_seeded()
    q: Dict[str, Any] = {"active": True}
    if root_only:
        # Match both explicit None and legacy docs missing the field.
        q["$or"] = [{"parent_id": None}, {"parent_id": {"$exists": False}}]
    cursor = db.shop_categories.find(q).sort([("sort_order", 1), ("name", 1)])
    docs = await cursor.to_list(length=500)
    skip = await _recharge_category_ids()
    return {"items": [_serialize(d) for d in docs if d.get("id") not in skip]}


@router.get("/shop-categories/tree")
async def list_category_tree():
    """PUBLIC — full nested category tree.  Response shape:
    [{ ...category, children: [{ ...category, children: [...] }] }]

    Recharge categories are excluded — see `_recharge_category_ids`."""
    await _ensure_seeded()
    docs = await db.shop_categories.find({"active": True}).sort([("sort_order", 1), ("name", 1)]).to_list(2000)
    skip = await _recharge_category_ids()
    by_id: Dict[str, Dict[str, Any]] = {}
    for d in docs:
        if d.get("id") in skip:
            continue
        node = _serialize(d)
        node["children"] = []
        by_id[node["id"]] = node
    roots: List[Dict[str, Any]] = []
    for node in by_id.values():
        pid = node.get("parent_id")
        if pid and pid in by_id:
            by_id[pid]["children"].append(node)
        else:
            roots.append(node)
    return {"items": roots}


@router.get("/shop-categories/{cat_id}/subcategories")
async def list_subcategories(cat_id: str):
    """PUBLIC — direct children of a given category (one level)."""
    docs = await db.shop_categories.find(
        {"parent_id": cat_id, "active": True},
    ).sort([("sort_order", 1), ("name", 1)]).to_list(500)
    return {"items": [_serialize(d) for d in docs]}


@router.get("/shop-categories/{cat_id}/descendants")
async def list_descendants(cat_id: str):
    """PUBLIC — ids + names of ALL descendants (any depth).  Used by the
    customer app to cascade filter products under a parent category."""
    ids = await _collect_descendants(cat_id)
    names = await _collect_names_in_subtree(cat_id)
    return {"ids": ids, "names": names}


# ── Admin ────────────────────────────────────────────────────────────
@router.get("/admin/shop-categories")
async def admin_list_categories(
    exclude_recharge: bool = False,
    _: Dict[str, Any] = Depends(require_admin),
):
    """Admin category list.

    `exclude_recharge=true` is used by the Shop Layout screen: recharge is
    sold through its own flow, so it must not be offerable as a layout
    scope. Category MANAGEMENT still sees everything (default false), so
    recharge categories remain editable where they belong.
    """
    await _ensure_seeded()
    cursor = db.shop_categories.find({}).sort([("sort_order", 1), ("name", 1)])
    docs = await cursor.to_list(length=1000)
    skip = await _recharge_category_ids() if exclude_recharge else set()
    return {"items": [_serialize(d) for d in docs if d.get("id") not in skip]}


@router.post("/admin/shop-categories")
async def admin_create_category(
    payload: CategoryCreate,
    admin: Dict[str, Any] = Depends(require_admin),
):
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "Name required")
    # Optional parent — used for nested subcategories.
    parent_id: Optional[str] = None
    depth = 0
    if payload.parent_id:
        parent = await db.shop_categories.find_one({"id": payload.parent_id})
        if not parent:
            raise HTTPException(400, "Parent category not found")
        parent_id = parent["id"]
        depth = int(parent.get("depth") or 0) + 1
    slug = _slugify(name)
    # Reject duplicate slug WITHIN the same parent — different parents can
    # share a slug ("Electronics/Chargers" vs "Automotive/Chargers").
    if await db.shop_categories.find_one({"slug": slug, "parent_id": parent_id}):
        raise HTTPException(409, f"Category '{name}' already exists at this level")
    now = datetime.utcnow()
    doc = {
        "id": str(uuid.uuid4()),
        "name": name,
        "slug": slug,
        "parent_id": parent_id,
        "depth": depth,
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
    await audit_log(admin, "shop_categories.create", {"id": doc["id"], "name": name, "parent_id": parent_id})
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
        parent_id = doc.get("parent_id")
        if new_slug != doc.get("slug"):
            clash = await db.shop_categories.find_one({"slug": new_slug, "parent_id": parent_id, "id": {"$ne": cat_id}})
            if clash:
                raise HTTPException(409, f"Category '{new_name}' already exists at this level")
            update["slug"] = new_slug
    # ── Re-parenting (with cycle protection & depth cascade) ──
    if payload.parent_id is not None:
        new_parent = (payload.parent_id or "").strip() or None
        if new_parent == cat_id:
            raise HTTPException(400, "A category cannot be its own parent")
        if new_parent:
            # Prevent moving under one of its own descendants.
            forbidden = set(await _collect_descendants(cat_id))
            if new_parent in forbidden:
                raise HTTPException(400, "Cannot re-parent under a descendant (would create a cycle)")
            parent_doc = await db.shop_categories.find_one({"id": new_parent})
            if not parent_doc:
                raise HTTPException(400, "Parent category not found")
            update["parent_id"] = new_parent
            update["depth"] = int(parent_doc.get("depth") or 0) + 1
        else:
            update["parent_id"] = None
            update["depth"] = 0
    if payload.icon_pack is not None:
        update["icon_pack"] = payload.icon_pack.lower()
    if payload.icon_name is not None:
        update["icon_name"] = payload.icon_name
    if payload.image_url is not None:
        update["image_url"] = payload.image_url or None
    if payload.color is not None:
        update["color"] = payload.color
    if payload.sort_order is not None:
        update["sort_order"] = int(payload.sort_order)
    if payload.active is not None:
        update["active"] = bool(payload.active)
    await db.shop_categories.update_one({"id": cat_id}, {"$set": update})
    # If we changed depth, cascade the change to every descendant.
    if "depth" in update:
        await _recompute_subtree_depth(cat_id)
    fresh = await db.shop_categories.find_one({"id": cat_id})
    await audit_log(admin, "shop_categories.update", {"id": cat_id, "changes": {k: v for k, v in update.items() if k != "updated_at"}})
    return _serialize(fresh) if fresh else {"id": cat_id}


async def _recompute_subtree_depth(root_id: str) -> None:
    """Walk `root_id`'s subtree BFS and rewrite the `depth` field so it
    reflects the current parent chain.  Called after re-parenting."""
    root = await db.shop_categories.find_one({"id": root_id}, {"depth": 1})
    if not root:
        return
    base_depth = int(root.get("depth") or 0)
    # (id, expected_depth) frontier
    frontier: List[tuple] = [(root_id, base_depth)]
    while frontier:
        next_frontier: List[tuple] = []
        parent_ids = [p[0] for p in frontier]
        depth_map = {p[0]: p[1] for p in frontier}
        async for c in db.shop_categories.find({"parent_id": {"$in": parent_ids}}, {"id": 1, "parent_id": 1}):
            new_d = depth_map[c["parent_id"]] + 1
            await db.shop_categories.update_one({"id": c["id"]}, {"$set": {"depth": new_d}})
            next_frontier.append((c["id"], new_d))
        frontier = next_frontier


@router.delete("/admin/shop-categories/{cat_id}")
async def admin_delete_category(
    cat_id: str,
    admin: Dict[str, Any] = Depends(require_admin),
):
    doc = await db.shop_categories.find_one({"id": cat_id})
    if not doc:
        raise HTTPException(404, "Category not found")
    # Re-parent direct children to the deleted node's parent so they
    # aren't orphaned (and don't disappear from the tree).
    new_parent = doc.get("parent_id") or None
    await db.shop_categories.update_many(
        {"parent_id": cat_id},
        {"$set": {"parent_id": new_parent, "updated_at": datetime.utcnow()}},
    )
    # After moving them up, their `depth` needs to be recomputed.
    if new_parent:
        await _recompute_subtree_depth(new_parent)
    else:
        # Children promoted to root — depth = 0 and cascade further.
        async for child in db.shop_categories.find({"parent_id": None}, {"id": 1}):
            await db.shop_categories.update_one({"id": child["id"]}, {"$set": {"depth": 0}})
    await db.shop_categories.delete_one({"id": cat_id})
    await audit_log(admin, "shop_categories.delete", {"id": cat_id, "name": doc.get("name")})
    return {"ok": True, "id": cat_id, "children_re_parented_to": new_parent}


@router.post("/admin/shop-categories/seed")
async def admin_seed_defaults(admin: Dict[str, Any] = Depends(require_admin)):
    """Idempotent — only inserts if collection is empty."""
    await _ensure_seeded()
    count = await db.shop_categories.count_documents({})
    return {"ok": True, "total": count}


@router.post("/admin/products/backfill-store-pincode")
async def admin_backfill_store_pincode(admin: Dict[str, Any] = Depends(require_admin)):
    """Nov 2026 — Backfill `store_pincode` / delivery fields on all
    existing products from their vendor's `users` doc.  Idempotent —
    safe to run any time after a bulk vendor migration."""
    updated = 0
    async for prod in db.products.find({}, {"id": 1, "vendor_id": 1, "store_pincode": 1}):
        vid = prod.get("vendor_id")
        if not vid:
            continue
        # Skip products that already have a pincode — respect vendor's later edits.
        if prod.get("store_pincode"):
            continue
        vend = await db.users.find_one({"id": vid}, {
            "_id": 0, "pincode": 1, "location": 1, "city": 1, "state": 1, "district": 1,
            "delivery_radius_km": 1, "delivery_radius_mode": 1, "delivery_available": 1,
            "delivery_pincodes": 1,
        })
        if not vend or not vend.get("pincode"):
            continue
        await db.products.update_one({"id": prod["id"]}, {"$set": {
            "store_pincode": vend.get("pincode"),
            "store_location": vend.get("location"),
            "store_city": vend.get("city"),
            "store_state": vend.get("state"),
            "store_district": vend.get("district"),
            "delivery_radius_km": vend.get("delivery_radius_km"),
            "delivery_radius_mode": vend.get("delivery_radius_mode") or "pincode",
            "delivery_available": vend.get("delivery_available", True),
            "delivery_pincodes": vend.get("delivery_pincodes") or [],
        }})
        updated += 1
    return {"ok": True, "updated": updated}
