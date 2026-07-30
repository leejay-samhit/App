"""Public product catalog routes.
Extracted from server.py during Phase 2B refactor.

Endpoints (mounted at /api by server.py):
  GET  /products                  — public, returns published products
                                    with computed `is_in_stock` flag and
                                    `interested_count`
  POST /products/{id}/interested  — auth user registers interest in an
                                    out-of-stock product (idempotent)
  GET  /products/{id}/interested  — admin/vendor sees the count + list of
                                    users interested
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core.db import db
from core.notifications import create_notification
from core.security import get_current_user
from core.utils import now_utc

router = APIRouter(tags=["products-public"])


def _shape_product(p: Dict[str, Any]) -> Dict[str, Any]:
    """Add computed fields (`is_in_stock`, `interested_count`) to a product doc.
    Keeps the original fields untouched so existing UI code keeps working."""
    stock = int(p.get("stock") or 0)
    interested = p.get("interested_users") or []
    p["is_in_stock"] = stock > 0
    p["interested_count"] = len(interested) if isinstance(interested, list) else 0
    # Don't leak raw user-id list to the public endpoint — only the count.
    p.pop("interested_users", None)
    return p


async def _collect_cascade_names(root_ident: str) -> List[str]:
    """Given a category name OR id, return the set of category names to
    match against products (root + every descendant).  Supports both
    lookups because vendors historically wrote free-form names into
    `product.category` while the new tree stores UUIDs."""
    # Locate the root by id, then fall back to name / slug
    root = await db.shop_categories.find_one({"id": root_ident})
    if not root:
        root = await db.shop_categories.find_one({"name": root_ident})
    if not root:
        root = await db.shop_categories.find_one({"slug": root_ident.lower()})
    if not root:
        return [root_ident]  # fall back to literal text match

    # BFS to collect all descendants
    names: List[str] = [(root.get("name") or "").strip()]
    frontier = [root["id"]]
    seen = set(frontier)
    while frontier:
        next_layer: List[str] = []
        async for c in db.shop_categories.find({"parent_id": {"$in": frontier}}, {"id": 1, "name": 1}):
            cid = c.get("id")
            if cid and cid not in seen:
                seen.add(cid); next_layer.append(cid)
                n = (c.get("name") or "").strip()
                if n and n not in names: names.append(n)
        frontier = next_layer
    return [n for n in names if n]


def _build_category_filter(names: List[str]) -> Dict[str, Any]:
    """Match any product whose `category` / `subcategory` / `sub_category`
    matches one of the given names (case-insensitive).

    Jul 2026 — Added `sub_category` (with underscore) because vendors
    have been writing the sub-category into that field historically
    while the tree data model uses `subcategory` — one match blob
    covers both variants."""
    if not names:
        return {}
    # Escape and build a case-insensitive OR
    import re as _re
    regexes = [{"$regex": f"^{_re.escape(n)}$", "$options": "i"} for n in names]
    return {"$or": [
        {"category": {"$in": names}},
        {"subcategory": {"$in": names}},
        {"sub_category": {"$in": names}},
        # Legacy free-form vendors may have written the name in different
        # casing — a case-insensitive regex catches those too.
        *[{"category": r} for r in regexes],
        *[{"subcategory": r} for r in regexes],
        *[{"sub_category": r} for r in regexes],
    ]}


@router.get("/products")
async def list_products(
    category: Optional[str] = Query(None, description="Filter by category name/id — cascades to all descendants when it matches a category tree node"),
    subcategory: Optional[str] = Query(None, description="Filter by subcategory name — ignored when `category` is a leaf"),
    pincode: Optional[str] = Query(None, description="Nov 2026 — filter products to vendors whose store_pincode / delivery_pincodes matches"),
    lat: Optional[float] = Query(None, description="Jul 2026 — customer latitude (used together with lng to km-radius match vendors)"),
    lng: Optional[float] = Query(None, description="Jul 2026 — customer longitude"),
    strict_location: bool = Query(False, description="Jul 2026 — when true, require a location match. If no pincode + no lat/lng is provided, return an empty list instead of the global catalog."),
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort: str = Query("newest", description="newest | popular | price_asc | price_desc"),
):
    """PUBLIC — paginated + category-cascading product list.

    Jul 2026 — location-first behaviour:
      • When `lat` + `lng` are provided, the endpoint additionally OR-includes
        vendors within their `delivery_radius_km` of the customer, calculated
        with the haversine formula in-Python from vendor `lat`/`lng` docs.
      • When `strict_location=true` and NEITHER pincode NOR (lat,lng) is
        provided → returns `{items: [], total: 0}` immediately (used by the
        Shop screen to force GPS capture before showing products).

    Nov 2026 upgrade (retained):
      • Supports `?category=` (id / name / slug) with automatic descendant
        cascade.
      • `?subcategory=` narrows further to that leaf.
      • `?pincode=` filters to vendors whose store_pincode / delivery_pincodes
        matches.
      • `?limit` + `?offset` paginate with a `total` count.
      • `?sort=` supports newest / popular / price_asc / price_desc.
    """
    # ── strict location gate ────────────────────────────────────────────
    have_pincode = bool(pincode)
    have_coords = (lat is not None and lng is not None)
    if strict_location and not have_pincode and not have_coords:
        return {"items": [], "total": 0, "limit": limit, "offset": offset, "has_more": False}

    q: Dict[str, Any] = {"$or": [{"is_published": True}, {"is_published": {"$exists": False}}]}

    if category:
        names = await _collect_cascade_names(category)
        cat_filter = _build_category_filter(names)
        if cat_filter:
            q = {"$and": [q, cat_filter]}

    if subcategory:
        sub_names = await _collect_cascade_names(subcategory)
        sub_filter = _build_category_filter(sub_names)
        if sub_filter:
            q = {"$and": [q, sub_filter]} if "$and" not in q else {"$and": q["$and"] + [sub_filter]}

    # Nov 2026 → Jul 2026 — Location filter (by vendor, not by product).
    # Vendor delivery config lives on the USER doc (store_pincode,
    # delivery_pincodes, delivery_radius_km/mode, lat/lng), so we resolve
    # the set of eligible vendor ids in a single query, then filter
    # products by vendor_id IN that set.
    location_or: List[Dict[str, Any]] = []
    if have_pincode or have_coords:
        vendor_ids = await _eligible_vendor_ids(
            pincode=pincode,
            lat=float(lat) if lat is not None else None,
            lng=float(lng) if lng is not None else None,
        )
        if vendor_ids:
            location_or.append({"vendor_id": {"$in": list(vendor_ids)}})
        # Backward compat — the ORIGINAL denormalized filter (if any
        # products happen to carry these fields directly on the product).
        if have_pincode:
            location_or.extend([
                {"$and": [
                    {"store_pincode": pincode},
                    {"$or": [
                        {"delivery_radius_mode": "pincode"},
                        {"delivery_radius_mode": "both"},
                        {"delivery_radius_mode": {"$exists": False}},
                    ]},
                ]},
                {"delivery_pincodes": pincode},
            ])

    if location_or:
        pin_filter = {"$or": location_or}
        q = {"$and": [q, pin_filter]} if "$and" not in q else {"$and": q["$and"] + [pin_filter]}
    elif strict_location:
        # We had location signals but no vendors matched — return empty.
        return {"items": [], "total": 0, "limit": limit, "offset": offset, "has_more": False}

    # Sort mapping
    sort_spec: List[tuple] = [("created_at", -1)]
    s = (sort or "newest").lower()
    if s == "price_asc":
        sort_spec = [("price", 1), ("created_at", -1)]
    elif s == "price_desc":
        sort_spec = [("price", -1), ("created_at", -1)]
    elif s == "popular":
        # popular by sales_count then interested_count
        sort_spec = [("sales_count", -1), ("created_at", -1)]

    # Total count (parallel to the paginated fetch) — kept cheap by
    # relying on the newly-added compound indexes.
    total = await db.products.count_documents(q)

    cursor = db.products.find(q, {"_id": 0}).sort(sort_spec).skip(offset).limit(limit)
    items = await cursor.to_list(limit)
    shaped = [_shape_product(p) for p in items]

    if category or subcategory or pincode or have_coords or offset > 0 or limit != 60 or sort != "newest":
        return {
            "items": shaped,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": (offset + len(shaped)) < total,
        }
    return shaped


# ─────────────────────────────────────────────────────────────────────
# Location-based vendor eligibility helper.
# ─────────────────────────────────────────────────────────────────────
async def _eligible_vendor_ids(
    pincode: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
) -> set:
    """Return the set of approved-vendor user ids that can DELIVER to the
    customer identified by `pincode` and/or `(lat, lng)`.

    A vendor is eligible when ANY of:
      1) Pincode mode: customer pincode == vendor.store_pincode AND the
         vendor's delivery_radius_mode allows pincode delivery
         (`pincode` / `both`, or the legacy vendors where mode is unset).
      2) Explicit pincode allow-list: customer pincode is in the vendor's
         `delivery_pincodes` array (regardless of mode).
      3) Radius mode: the customer's lat/lng is within
         `vendor.delivery_radius_km` km of the vendor's own lat/lng
         (mode `radius` / `both`).

    Vendors that predate the `delivery_radius_mode` field are treated
    conservatively — they only match via (1) and (2).
    """
    import math
    ids: set = set()

    # ─ Pincode-based matches (Mongo query — fast) ──────────────────
    if pincode:
        pincode_filter = {
            "is_vendor_approved": True,
            "$or": [
                {"delivery_pincodes": pincode},
                {"$and": [
                    {"store_pincode": pincode},
                    {"$or": [
                        {"delivery_radius_mode": "pincode"},
                        {"delivery_radius_mode": "both"},
                        {"delivery_radius_mode": {"$exists": False}},
                    ]},
                ]},
            ],
        }
        async for v in db.users.find(pincode_filter, {"_id": 0, "id": 1}):
            ids.add(v["id"])

    # ─ Radius-based matches (in-Python haversine) ──────────────────
    if lat is not None and lng is not None:
        R = 6371.0088  # Earth radius, km
        plat = math.radians(lat); plng = math.radians(lng)
        radius_filter = {
            "is_vendor_approved": True,
            "lat": {"$type": "number"}, "lng": {"$type": "number"},
            "delivery_radius_km": {"$gt": 0},
            "$or": [
                {"delivery_radius_mode": "radius"},
                {"delivery_radius_mode": "both"},
            ],
        }
        async for v in db.users.find(
            radius_filter,
            {"_id": 0, "id": 1, "lat": 1, "lng": 1, "delivery_radius_km": 1},
        ):
            try:
                vlat = math.radians(float(v["lat"])); vlng = math.radians(float(v["lng"]))
                dlat = vlat - plat; dlng = vlng - plng
                a = math.sin(dlat/2)**2 + math.cos(plat)*math.cos(vlat)*math.sin(dlng/2)**2
                d = 2 * R * math.asin(math.sqrt(a))
                if d <= float(v.get("delivery_radius_km") or 0):
                    ids.add(v["id"])
            except Exception:
                continue
    return ids


# ─────────────────────────────────────────────────────────────────────
# Haversine-based vendor lookup used by /products?lat=&lng=.
# Deprecated: use `_eligible_vendor_ids` instead. Kept for import compat.
# ─────────────────────────────────────────────────────────────────────
async def _vendors_within_radius(lat: float, lng: float) -> set:
    return await _eligible_vendor_ids(lat=lat, lng=lng)


# IMPORTANT: this route MUST be declared BEFORE `/products/{product_id}` or
# FastAPI's first-match routing will treat "by-source" as a product_id and
# 404 the whole dynamic shop-layout pipeline. Same pattern as the previously
# fixed /admin/pincodes/in-region route-ordering bug.
@router.get("/products/by-source")
async def list_products_by_source(
    source: str = "trending",
    limit: int = 10,
    category: str | None = None,
    pincode: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    strict_location: bool = False,
):
    """Return products for a Shop Layout section based on a logical source:

      source=trending  → top N by `interested_count` then orders volume
      source=new       → newest by `created_at`
      source=best      → most-sold (uses `sales_count` if tracked, else `interested_count`)
      source=category  → filtered by `category` field

    Optional `category` filter narrows ALL sources to a department/category.
    Jul 2026 — Location filter (`pincode` / `lat` / `lng` /
    `strict_location=true`) matches the customer's delivery zone so that
    shop-layout blocks never leak products from vendors who don't
    deliver.  Always returns a flat ARRAY of shaped products (same shape
    as /products).
    """
    limit = max(1, min(50, int(limit or 10)))
    src = (source or "trending").strip().lower()
    if src not in ("trending", "new", "best", "category", "manual"):
        src = "trending"

    have_pincode = bool(pincode)
    have_coords = (lat is not None and lng is not None)
    if strict_location and not have_pincode and not have_coords:
        return []

    q: Dict[str, Any] = {"$or": [{"is_published": True}, {"is_published": {"$exists": False}}]}
    if category:
        q["category"] = category

    # Jul 2026 — apply vendor-in-zone filter identical to /products
    if have_pincode or have_coords:
        vendor_ids = await _eligible_vendor_ids(
            pincode=pincode,
            lat=float(lat) if lat is not None else None,
            lng=float(lng) if lng is not None else None,
        )
        location_or: List[Dict[str, Any]] = []
        if vendor_ids:
            location_or.append({"vendor_id": {"$in": list(vendor_ids)}})
        if have_pincode:
            location_or.extend([
                {"$and": [
                    {"store_pincode": pincode},
                    {"$or": [
                        {"delivery_radius_mode": "pincode"},
                        {"delivery_radius_mode": "both"},
                        {"delivery_radius_mode": {"$exists": False}},
                    ]},
                ]},
                {"delivery_pincodes": pincode},
            ])
        if location_or:
            q = {"$and": [q, {"$or": location_or}]}
        elif strict_location:
            return []

    if src == "new":
        cursor = db.products.find(q, {"_id": 0}).sort("created_at", -1).limit(limit)
    elif src == "category":
        cursor = db.products.find(q, {"_id": 0}).sort("created_at", -1).limit(limit)
    else:
        # trending / best → pull a larger window, then sort in-process by a
        # composite "popularity" score so MongoDB doesn't need a custom index.
        cursor = db.products.find(q, {"_id": 0}).sort("created_at", -1).limit(max(limit * 4, 40))

    items = await cursor.to_list(limit * 4 if src in ("trending", "best") else limit)
    if src in ("trending", "best"):
        def score(p: Dict[str, Any]) -> int:
            interested = p.get("interested_users") or []
            interested_n = len(interested) if isinstance(interested, list) else 0
            sales = int(p.get("sales_count") or 0)
            # `best` weights actual sales heavier; `trending` weights interest
            if src == "best":
                return sales * 10 + interested_n
            return interested_n * 5 + sales
        items.sort(key=score, reverse=True)
        items = items[:limit]
    return [_shape_product(p) for p in items]


@router.get("/products/{product_id}")
async def get_product(product_id: str):
    """Public single-product detail endpoint.

    Returns the FULL product document (all extended fields included) plus the
    computed `is_in_stock` and `interested_count`.  Used by the customer
    Product Detail page so we don't have to fetch the entire catalog just to
    render one product.

    Legacy products (created before the extended schema landed) are still
    returned cleanly with safe defaults for any missing rich field, so the UI
    never explodes on `undefined` accesses.
    """
    p = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    # Hide unpublished products from the public endpoint (admins use a
    # different route).
    if p.get("is_published") is False:
        raise HTTPException(status_code=404, detail="Product not available")
    # ── Back-fill safe defaults for legacy products ──
    p.setdefault("brand", "")
    p.setdefault("sub_features", [])
    p.setdefault("images", [])
    p.setdefault("price_summary", {"text": "", "bold": False, "font_size": None, "align": "left"})
    p.setdefault("protection_summary", {"text": "", "bold": False, "font_size": None, "align": "left"})
    p.setdefault("warranty_summary", {"text": "", "bold": False, "font_size": None, "align": "left"})
    p.setdefault("delivery_summary", {"text": "", "bold": False, "font_size": None, "align": "left"})
    p.setdefault("attrs_brand", "")
    p.setdefault("attrs_os", "")
    p.setdefault("attrs_ram", "")
    p.setdefault("attrs_cpu_model", "")
    p.setdefault("attrs_cpu_speed", "")
    p.setdefault("attrs_storage", "")
    p.setdefault("extra_attrs", {})
    p.setdefault("spec_tabs", [])
    p.setdefault("whats_in_box", [])
    return _shape_product(p)


@router.post("/products/{product_id}/interested")
async def register_interest(
    product_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Customer marks they're interested in an out-of-stock product. Idempotent
    — same user clicking twice doesn't double-count. Notifies the vendor (if
    any) so they can plan a restock."""
    product = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Idempotent add via $addToSet
    res = await db.products.update_one(
        {"id": product_id},
        {"$addToSet": {"interested_users": user["id"]}},
    )
    fresh = await db.products.find_one({"id": product_id}, {"_id": 0})
    interested = fresh.get("interested_users") or []
    count = len(interested) if isinstance(interested, list) else 0

    # Newly added (modified_count==1 means the array changed) → notify vendor
    if res.modified_count > 0 and product.get("vendor_id"):
        try:
            await create_notification(
                product["vendor_id"],
                "stock_interest",
                "Customer wants to buy your product",
                f"{user.get('name')} is interested in '{product.get('name')}' "
                f"(now {count} customer{'s' if count != 1 else ''} interested). "
                "Restock soon to capture the sale.",
                extra={"product_id": product_id},
            )
        except Exception:
            pass

    return {
        "ok": True,
        "interested_count": count,
        "already_registered": res.modified_count == 0,
    }


@router.get("/products/{product_id}/interested")
async def list_interested_users(
    product_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Vendor (owner) or admin can see the count + list of users interested.
    Customers get a 403."""
    product = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    is_admin = user.get("role") == "admin"
    is_owner = product.get("vendor_id") == user["id"]
    if not is_admin and not is_owner:
        raise HTTPException(status_code=403, detail="Not allowed")

    ids = product.get("interested_users") or []
    users_info: list = []
    if ids:
        cursor = db.users.find(
            {"id": {"$in": ids}},
            {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1},
        )
        users_info = await cursor.to_list(2000)

    return {
        "product_id": product_id,
        "product_name": product.get("name"),
        "interested_count": len(ids),
        "users": users_info,
        "as_of": now_utc().isoformat(),
    }

