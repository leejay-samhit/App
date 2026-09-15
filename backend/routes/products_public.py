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

import time
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from core.db import db
from core.notifications import create_notification
from core.security import get_current_user
from core.utils import now_utc

router = APIRouter(tags=["products-public"])

# ─────────────────────────────────────────────────────────────────────
# Dec 2026 — In-memory caches for the two hottest helpers.  Every
# /products, /products/by-source, /shop-categories/tree and category
# screen mount runs `_collect_cascade_names` + `_eligible_vendor_ids`
# — hitting Mongo O(N) each time, where N = approved-vendor count.
#
# These caches turn the O(N) scans into O(1) lookups for repeated
# customer sessions (which is the common case: the same customer
# opens several categories in a row from the same GPS/pincode).
#
# TTLs are short (60s) so vendor pincode / radius edits still flow
# through quickly; admin approval flow also busts the vendor cache
# via `bust_eligible_vendor_cache()` below.
# ─────────────────────────────────────────────────────────────────────
_CASCADE_TTL = 300.0          # 5 min — category tree changes are rare
_ELIGIBLE_TTL = 60.0           # 1 min — vendor config changes take up to 60s to propagate
_cascade_cache: Dict[str, Tuple[float, List[str]]] = {}
_eligible_cache: Dict[str, Tuple[float, set]] = {}


def bust_products_public_caches() -> None:
    """Called by admin routes after vendor approval / category edits."""
    _cascade_cache.clear()
    _eligible_cache.clear()


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


# Dec 2026 — Slim projection for LIST endpoints.  Vendors often paste
# 200-500 KB base64 images per product, so a naive list of 40 products
# would ship 20+ MB over the wire → "network error" on mobile.  For
# list views we ONLY return the primary `image_url` (typically a small
# CDN URL or thumbnail) and drop:
#   • `images[]`              — full-size gallery, only needed on detail
#   • `description`           — long-form, only needed on detail
#   • `specifications`        — structured detail block
#   • `interested_users[]`    — raw user list (privacy)
#   • `reviews[]`, `questions[]` — heavy relational blobs
#   • base64 `image_url` values are TRUNCATED to nothing so clients can
#     lazy-load the full image via /products/{id}.
_LIST_PROJECTION: Dict[str, int] = {
    "_id": 0,
    "images": 0,
    "description": 0,
    "specifications": 0,
    "interested_users": 0,
    "reviews": 0,
    "questions": 0,
}


def _slim_list_item(p: Dict[str, Any]) -> Dict[str, Any]:
    """Post-process a list-item document for the wire.

    When `image_url` is a giant base64 `data:` URI we rewrite it to a
    **thumbnail** endpoint URL (`?w=360&q=72`) that the client fetches
    lazily as each card scrolls into view.  A 200 KB source image is
    reduced to ~30 KB on the wire, keeping the shop grid crisp on
    retina screens without the payload cost of full-res.
    Regular URLs pass through untouched.
    """
    img = p.get("image_url") or ""
    if isinstance(img, str) and img.startswith("data:"):
        # 360 px is 2× a typical grid tile (180 dp on a phone).  q=72 is
        # the sweet spot between perceptual quality and payload size.
        p["image_url"] = f"/api/products/{p.get('id')}/image?w=360&q=72"
        p["has_inline_image"] = True
    # Jun 2026 — list cards need to know a product HAS sizes so the "+"
    # opens the size picker instead of blind-adding, and so the price can
    # read "from ₹499". The heavy `variants` array itself is dropped.
    variants = p.pop("variants", None) or []
    active = [v for v in variants if isinstance(v, dict) and v.get("active", True)]
    p["has_variants"] = len(active) > 0
    p["variant_count"] = len(active)
    return _shape_product(p)


async def _collect_cascade_names(root_ident: str) -> List[str]:
    """Given a category name OR id, return the set of category names to
    match against products (root + every descendant).  Supports both
    lookups because vendors historically wrote free-form names into
    `product.category` while the new tree stores UUIDs.

    Dec 2026 — Cached for 5 min so repeated category-screen mounts (the
    hot path from the customer's shop navigation) don't re-walk the
    tree via 3-6 Mongo queries every time.
    """
    key = (root_ident or "").strip().lower()
    now = time.time()
    hit = _cascade_cache.get(key)
    if hit and (now - hit[0]) < _CASCADE_TTL:
        return list(hit[1])

    # Locate the root by id, then fall back to name / slug
    root = await db.shop_categories.find_one({"id": root_ident})
    if not root:
        root = await db.shop_categories.find_one({"name": root_ident})
    if not root:
        root = await db.shop_categories.find_one({"slug": root_ident.lower()})
    if not root:
        result = [root_ident]  # fall back to literal text match
        _cascade_cache[key] = (now, result)
        return result

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
    result = [n for n in names if n]
    _cascade_cache[key] = (now, result)
    return result


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
    q: Optional[str] = Query(None, description="Free-text search — case-insensitive substring match across name / description / brand / category"),
    pincode: Optional[str] = Query(None, description="Nov 2026 — filter products to vendors whose store_pincode / delivery_pincodes matches"),
    lat: Optional[float] = Query(None, description="Jul 2026 — customer latitude (used together with lng to km-radius match vendors)"),
    lng: Optional[float] = Query(None, description="Jul 2026 — customer longitude"),
    strict_location: bool = Query(False, description="Jul 2026 — when true, require a location match. If no pincode + no lat/lng is provided, return an empty list instead of the global catalog."),
    limit: int = Query(60, ge=1, le=300),
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

    query: Dict[str, Any] = {"$or": [{"is_published": True}, {"is_published": {"$exists": False}}]}

    if category:
        names = await _collect_cascade_names(category)
        cat_filter = _build_category_filter(names)
        if cat_filter:
            query = {"$and": [query, cat_filter]}

    if subcategory:
        sub_names = await _collect_cascade_names(subcategory)
        sub_filter = _build_category_filter(sub_names)
        if sub_filter:
            query = {"$and": [query, sub_filter]} if "$and" not in query else {"$and": query["$and"] + [sub_filter]}

    # Dec 2026 — Free-text search across name / description / brand /
    # category / sub_category.  Case-insensitive, escapes regex metas.
    if q and q.strip():
        import re as _re
        needle = _re.escape(q.strip())
        text_or = {"$or": [
            {"name": {"$regex": needle, "$options": "i"}},
            {"description": {"$regex": needle, "$options": "i"}},
            {"brand": {"$regex": needle, "$options": "i"}},
            {"category": {"$regex": needle, "$options": "i"}},
            {"sub_category": {"$regex": needle, "$options": "i"}},
            {"subcategory": {"$regex": needle, "$options": "i"}},
            {"tags": {"$regex": needle, "$options": "i"}},
        ]}
        query = {"$and": [query, text_or]} if "$and" not in query else {"$and": query["$and"] + [text_or]}

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
        query = {"$and": [query, pin_filter]} if "$and" not in query else {"$and": query["$and"] + [pin_filter]}
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
    total = await db.products.count_documents(query)

    cursor = db.products.find(query, _LIST_PROJECTION).sort(sort_spec).skip(offset).limit(limit)
    items = await cursor.to_list(limit)
    shaped = [_slim_list_item(p) for p in items]

    if category or subcategory or (q and q.strip()) or pincode or have_coords or offset > 0 or limit != 60 or sort != "newest":
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

    Dec 2026 — Result is cached in-memory for 60s keyed by
    (pincode, lat, lng).  This turns the O(N) vendor scan + haversine
    loop into an O(1) lookup for repeated calls from the same
    customer session (category screen, layout blocks, checkout).

    Jun 2026 (Phase 5A) — the RULES now live in `core/delivery.py` so the
    vendor's Delivery Radius screen, this filter and checkout all answer
    "can this vendor deliver here?" identically. That module additionally
    falls back to the PINCODE CENTRE when the customer has no GPS fix, which
    is what used to make a pincode inside the vendor's radius look
    undeliverable.
    """
    # Round coords to 3 decimal places (~110m) for cache key stability
    # — a customer walking 100m shouldn't invalidate their session.
    lat_k = round(float(lat), 3) if lat is not None else None
    lng_k = round(float(lng), 3) if lng is not None else None
    cache_key = f"{pincode or ''}|{lat_k or ''}|{lng_k or ''}"
    now = time.time()
    hit = _eligible_cache.get(cache_key)
    if hit and (now - hit[0]) < _ELIGIBLE_TTL:
        return set(hit[1])

    from core.delivery import eligible_vendor_ids as _shared_eligible
    ids = await _shared_eligible(
        pincode=pincode,
        lat=float(lat) if lat is not None else None,
        lng=float(lng) if lng is not None else None,
    )
    _eligible_cache[cache_key] = (now, ids)
    return ids


# ─────────────────────────────────────────────────────────────────────
# Haversine-based vendor lookup used by /products?lat=&lng=.
# Deprecated: use `_eligible_vendor_ids` instead. Kept for import compat.
# ─────────────────────────────────────────────────────────────────────
async def _vendors_within_radius(lat: float, lng: float) -> set:
    return await _eligible_vendor_ids(lat=lat, lng=lng)


@router.get("/product-variant-charts")
async def product_variant_charts():
    """Size / option chart catalogue for the vendor + admin product forms.

    Jun 2026 — served from the SERVER (core/variants.py) so the mobile app,
    the admin panel and the web build can never drift out of sync on which
    sizes exist or what the measurement table says.
    """
    from core.variants import charts_payload
    return charts_payload()


@router.get("/products/search-suggest")
async def search_suggest(
    q: str = Query(..., min_length=1, description="Partial product name typed by the customer"),
    pincode: Optional[str] = Query(None),
    lat: Optional[float] = Query(None),
    lng: Optional[float] = Query(None),
    limit: int = Query(10, ge=1, le=25),
):
    """Jun 2026 — Smart-search typeahead.

    The shop search box previously showed ZERO suggestions: the customer had
    to submit a full query and hope for hits.  Worse, when several vendors
    list the SAME product the raw result set repeated the name once per
    vendor, so a 6-suggestion dropdown could be one product six times.

    This endpoint groups by the lower-cased product NAME, so each suggestion
    is a distinct product with:
      • `vendor_count`  — how many vendors near you carry it
      • `min_price` / `max_price` — the price band across those vendors
      • `image`         — thumbnail URL of one representative listing
    Tapping a suggestion should run the normal `/products?q=<name>` search,
    which still lists EVERY published vendor listing for that product.

    Location-aware: honours the same pincode / radius vendor eligibility
    rules as `/products` so we never suggest something nobody can deliver.
    """
    needle = (q or "").strip()
    if not needle:
        return {"items": [], "query": ""}

    import re as _re
    rx = {"$regex": _re.escape(needle), "$options": "i"}
    match: Dict[str, Any] = {"$and": [
        {"$or": [{"is_published": True}, {"is_published": {"$exists": False}}]},
        {"$or": [{"name": rx}, {"brand": rx}, {"category": rx}, {"sub_category": rx}, {"tags": rx}]},
    ]}

    have_pincode = bool(pincode)
    have_coords = (lat is not None and lng is not None)
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
            location_or.append({"store_pincode": pincode})
            location_or.append({"delivery_pincodes": pincode})
        if not location_or:
            return {"items": [], "query": needle}
        match["$and"].append({"$or": location_or})

    rows = await db.products.aggregate([
        {"$match": match},
        {"$group": {
            "_id": {"$toLower": {"$ifNull": ["$name", ""]}},
            "name": {"$first": "$name"},
            "brand": {"$first": "$brand"},
            "category": {"$first": "$category"},
            "cover_id": {"$first": "$id"},
            "min_price": {"$min": "$price"},
            "max_price": {"$max": "$price"},
            "listings": {"$sum": 1},
            "vendors": {"$addToSet": "$vendor_id"},
        }},
        {"$sort": {"listings": -1, "name": 1}},
        {"$limit": int(limit)},
    ]).to_list(int(limit))

    items = []
    for r in rows:
        vendors = [v for v in (r.get("vendors") or []) if v]
        items.append({
            "name": r.get("name") or "",
            "brand": r.get("brand") or "",
            "category": r.get("category") or "",
            "min_price": round(float(r.get("min_price") or 0), 2),
            "max_price": round(float(r.get("max_price") or 0), 2),
            "listings": int(r.get("listings") or 0),
            "vendor_count": len(vendors),
            "image": f"/api/products/{r.get('cover_id')}/image?w=120&q=70",
        })
    return {"items": items, "query": needle}


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
    limit = max(1, min(300, int(limit or 10)))
    src = (source or "trending").strip().lower()
    if src not in ("trending", "new", "best", "category", "manual"):
        src = "trending"

    have_pincode = bool(pincode)
    have_coords = (lat is not None and lng is not None)
    if strict_location and not have_pincode and not have_coords:
        return []

    q: Dict[str, Any] = {"$or": [{"is_published": True}, {"is_published": {"$exists": False}}]}
    if category:
        # Jun 2026 BUGFIX — the admin's category picker lists the whole
        # hierarchy, so a Shop-Layout block scoped to a SUB-category
        # ("Vegetables", "Mobiles") matched nothing here: we only compared
        # the top-level `category` field. Now we match either level, and
        # case-insensitively, because vendors type these labels by hand.
        import re as _re
        rx = {"$regex": f"^{_re.escape(category)}$", "$options": "i"}
        q = {"$and": [q, {"$or": [
            {"category": rx},
            {"sub_category": rx},
            {"subcategory": rx},
        ]}]}

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
        cursor = db.products.find(q, _LIST_PROJECTION).sort("created_at", -1).limit(limit)
    elif src == "category":
        cursor = db.products.find(q, _LIST_PROJECTION).sort("created_at", -1).limit(limit)
    else:
        # trending / best → pull a larger window, then sort in-process by a
        # composite "popularity" score so MongoDB doesn't need a custom index.
        cursor = db.products.find(q, _LIST_PROJECTION).sort("created_at", -1).limit(max(limit * 4, 40))

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
    return [_slim_list_item(p) for p in items]


@router.get("/products/{product_id}/image")
async def get_product_image(
    product_id: str,
    request: Request,
    idx: int = Query(0, ge=0, le=32),
    w: Optional[int] = Query(None, ge=32, le=1600),
    q: int = Query(72, ge=40, le=95),
):
    """Dec 2026 — Lazy-load endpoint for base64 product images with
    ON-THE-FLY THUMBNAILING + aggressive caching.

    Query params:
      * `w`  — target width in px.  When set (e.g. `w=360` for grid cards),
               we resize the source image, re-encode as JPEG at quality
               `q` (default 72) → typical 200 KB source → 25-40 KB thumb.
               For the customer shop grid this is a **~90% payload
               reduction on top of the base64 → binary conversion**.
      * `q`  — JPEG quality 40-95, default 72.  Bigger for detail page.
      * Omit `w` → returns the original (used by product detail).

    Caching:
      * ETag = sha1(image bytes)[:16] — client sends `If-None-Match`
        and the server returns 304 Not Modified when unchanged (0 KB
        response body).
      * `Cache-Control: public, max-age=604800, immutable` — client /
        CDN caches the exact w×q variant for a full week.
    """
    from fastapi.responses import Response, RedirectResponse
    from fastapi import Request  # noqa: F401
    import base64, hashlib, io

    # Client ETag → 304 shortcut, saves the entire decode/resize.
    client_etag = request.headers.get("if-none-match") or ""

    # Jun 2026 fix — this endpoint used to 404 whenever `is_published` was
    # False.  Vendor-created products are ALWAYS unpublished until an admin
    # approves them, so every vendor product thumbnail rendered as a broken
    # image inside the Admin Products grid (which is exactly where the admin
    # needs to SEE the photo before publishing).  Product ids are UUIDs and
    # an image carries no private data, so we now serve bytes regardless of
    # publish state.  Listing visibility is still gated by /products.
    p = await db.products.find_one(
        {"id": product_id},
        {"_id": 0, "image_url": 1, "images": 1},
    )
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    src = ""
    if idx == 0:
        src = str(p.get("image_url") or "")
    if not src:
        imgs = p.get("images") or []
        if 0 <= idx < len(imgs):
            src = str(imgs[idx] or "")
    if not src:
        # 1×1 transparent PNG placeholder so <Image> doesn't render broken
        px = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")
        return Response(px, media_type="image/png", headers={"Cache-Control": "public, max-age=60"})

    # External URL — 307 redirect (browser / RN Image caches it).
    if not src.startswith("data:"):
        return RedirectResponse(src, status_code=307)

    # data:image/<mime>;base64,<...>
    try:
        head, b64 = src.split(",", 1)
        raw = base64.b64decode(b64)
    except Exception:
        raise HTTPException(status_code=500, detail="Corrupt image data")

    # Compute the variant ETag PRE-decode so we can 304-short-circuit
    # the expensive PIL resize on subsequent visits.  Key = sha1 of
    # (raw source bytes + width + quality).
    src_hash = hashlib.sha1(raw).digest()
    variant_key = hashlib.sha1(src_hash + str(w or 0).encode() + str(q).encode()).hexdigest()[:16]
    if client_etag and client_etag.strip('"').startswith(variant_key):
        return Response(status_code=304, headers={
            "ETag": variant_key,
            "Cache-Control": "public, max-age=604800, immutable",
        })

    # Fast path: no resize requested → serve as-is.
    if not w:
        mime = head[5:].split(";", 1)[0] or "image/jpeg"
        return Response(
            raw,
            media_type=mime,
            headers={
                "ETag": variant_key,
                "Cache-Control": "public, max-age=604800, immutable",
            },
        )

    # Slow path: resize + re-encode.  Import Pillow lazily so the module
    # can be imported in test environments without the native dep.
    try:
        from PIL import Image, ImageOps
        img = Image.open(io.BytesIO(raw))
        # Autorotate per EXIF, then convert to RGB (JPEG can't do alpha).
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "L"):
            # Composite alpha over white so PNG/WEBP transparency looks OK.
            bg = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "RGBA":
                bg.paste(img, mask=img.split()[3])
            else:
                bg.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[3])
            img = bg
        # Preserve aspect ratio, only downscale (never upscale).
        target_w = min(int(w), img.width)
        if target_w < img.width:
            ratio = target_w / img.width
            new_h = max(1, int(round(img.height * ratio)))
            img = img.resize((target_w, new_h), Image.LANCZOS)
        buf = io.BytesIO()
        # progressive JPEG loads perceptibly faster on slow connections.
        img.save(buf, format="JPEG", quality=int(q), optimize=True, progressive=True)
        out = buf.getvalue()
    except Exception:
        # Pillow decode failure — fall back to the raw source so the
        # image at least loads (albeit at full size).
        mime = head[5:].split(";", 1)[0] or "image/jpeg"
        return Response(
            raw,
            media_type=mime,
            headers={"ETag": variant_key, "Cache-Control": "public, max-age=604800, immutable"},
        )

    return Response(
        out,
        media_type="image/jpeg",
        headers={
            "ETag": variant_key,
            "Cache-Control": "public, max-age=604800, immutable",
            # Vary lets any intermediate cache key on the resize/quality knobs.
            "Vary": "Accept",
        },
    )


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
    p = await db.products.find_one(
        {"id": product_id},
        # Phase 2 §16 — purchase price / purchase GST are VENDOR-PRIVATE and
        # must never reach a customer. Excluded at the query, not after.
        {"_id": 0, "purchase_price": 0, "purchase_gst_pct": 0},
    )
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
    # ── Jun 2026 — Variants (sizes / RAM-ROM) ─────────────────────────────
    # Ship each option with its final selling price already computed and the
    # matching measurement chart, so the product page can render the size
    # selector + "Size guide" sheet without a second round-trip.
    from core.variants import CHARTS, variant_price
    p.setdefault("variants", [])
    p.setdefault("variant_chart", "")
    p.setdefault("variant_price_mode", "extra")
    base = float(p.get("base_price") or p.get("price") or 0)
    mode = str(p.get("variant_price_mode") or "extra")
    live = []
    for v in (p.get("variants") or []):
        if not v.get("active", True):
            continue
        live.append({
            "id": v.get("id"),
            "label": v.get("label"),
            "price": round(float(v.get("price") or 0) or variant_price(v, base, mode), 2),
            "stock": int(v.get("stock") or 0),
            "in_stock": int(v.get("stock") or 0) > 0,
        })
    p["variants"] = live
    p["has_variants"] = len(live) > 0
    chart = CHARTS.get(str(p.get("variant_chart") or ""))
    p["variant_guide"] = {
        "label": chart["label"], "unit": chart["unit"],
        "columns": chart["columns"], "guide": chart["guide"],
    } if chart else None
    # Phase 2 §18 — customer-facing tax breakdown from the ONE GST engine.
    from core import gst as _gst
    p["gst_breakdown"] = _gst.public_pricing(p)["selling"]
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

