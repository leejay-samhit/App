"""Product Master Autocomplete (UPDATE 2, June 2026).

Provides a fast typeahead search endpoint for the vendor Add-Product form so
sellers can reuse an existing catalog entry (image, brand, price, specs)
instead of hand-typing everything.

Endpoint (mounted at `/api` by server.py):
  GET  /products/master/search?q=<query>&limit=<N>

The endpoint currently pulls from the LOCAL `products` collection only —
searching both admin-uploaded and vendor-uploaded rows.  It de-duplicates
overlapping catalog entries by (normalised name + brand) so vendors don't
see 30 near-identical "iPhone 15 128GB" rows.

Design decisions (from the June 2026 spec):
  • No external scrape yet — 91mobiles.com is behind Cloudflare and rejects
    server-side requests from datacentres. When we add a scraper-proxy
    integration later (e.g. ScraperAPI, Bright Data) it will slot in here.
  • Rich payload — we return the SAME shape the vendor form expects
    (name, brand, image_url, price, category, sub_features, attrs_*, specs,
    whats_in_box) so tapping a suggestion auto-fills every field in one go.
  • Auth-gated — the endpoint is available to any signed-in user (matches
    the vendor RichProductEditor which is only shown to approved vendors),
    keeping the search behind login to prevent unauthenticated scraping of
    our own catalog.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query

from core.db import db
from core.security import get_current_user

router = APIRouter(tags=["products-master"])


def _norm(s: Any) -> str:
    """Lowercase, collapse whitespace, strip punctuation for de-dupe keys."""
    if not s:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", str(s).lower())).strip()


def _shape_master_row(p: Dict[str, Any], source: str = "local") -> Dict[str, Any]:
    """Return the payload the vendor form consumes to prefill fields."""
    return {
        "source": source,  # "local" | "master" | "external" (future)
        "id": p.get("id"),
        "name": p.get("name") or "",
        "brand": p.get("brand") or p.get("attrs_brand") or "",
        "image_url": p.get("image_url") or (p.get("images") or [None])[0] or "",
        "images": p.get("images") or [],
        "price": p.get("price") or 0,
        "category": p.get("category") or "",
        "sub_category": p.get("sub_category") or "",
        "description": p.get("description") or "",
        "sub_features": p.get("sub_features") or [],
        # Structured attrs (mobile/electronics)
        "attrs_brand": p.get("attrs_brand") or "",
        "attrs_os": p.get("attrs_os") or "",
        "attrs_ram": p.get("attrs_ram") or "",
        "attrs_cpu_model": p.get("attrs_cpu_model") or "",
        "attrs_cpu_speed": p.get("attrs_cpu_speed") or "",
        "attrs_storage": p.get("attrs_storage") or "",
        "extra_attrs": p.get("extra_attrs") or {},
        # Styled summaries (kept optional so simple products stay simple)
        "price_summary": p.get("price_summary"),
        "protection_summary": p.get("protection_summary"),
        "warranty_summary": p.get("warranty_summary"),
        "delivery_summary": p.get("delivery_summary"),
        # Rich spec tabs + what's-in-the-box (may be empty)
        "spec_tabs": p.get("spec_tabs") or [],
        "whats_in_box": p.get("whats_in_box") or [],
    }


@router.get("/products/master/search")
async def master_search(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(10, ge=1, le=25),
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Typeahead search over the local product catalog.

    Returns a de-duplicated, ranked list of catalog matches formatted so the
    vendor form can prefill every field in one tap.

    Ranking (highest first):
      1. Exact name prefix match (case-insensitive)
      2. Any word in query matches product name
      3. Brand match
      4. Category/description match

    We SKIP the current user's own products so vendors don't see their own
    drafts as "suggested masters" (UPDATE 1 scoping).
    """
    query = (q or "").strip()
    if len(query) < 1:
        raise HTTPException(status_code=400, detail="Query is required")
    if len(query) > 100:
        query = query[:100]

    # Regex-escape user input for a safe partial-match search.
    safe = re.escape(query)
    tokens = [re.escape(t) for t in query.split() if t]
    or_clauses: List[Dict[str, Any]] = [
        {"name": {"$regex": safe, "$options": "i"}},
        {"brand": {"$regex": safe, "$options": "i"}},
        {"attrs_brand": {"$regex": safe, "$options": "i"}},
        {"category": {"$regex": safe, "$options": "i"}},
        {"description": {"$regex": safe, "$options": "i"}},
    ]
    # Also match ANY individual word from the query — helps with
    # "samsung s24 ultra" pulling in "Galaxy S24 Ultra".
    for t in tokens:
        or_clauses.append({"name": {"$regex": t, "$options": "i"}})
        or_clauses.append({"brand": {"$regex": t, "$options": "i"}})

    mongo_q: Dict[str, Any] = {"$or": or_clauses}

    # Pull a wider window than needed so ranking + de-dupe can trim it.
    raw = await db.products.find(mongo_q, {"_id": 0}).limit(limit * 6).to_list(limit * 6)

    own_id = user.get("id")

    def score(p: Dict[str, Any]) -> int:
        """Higher score = better match. Used for ranking after de-dupe."""
        name_l = (p.get("name") or "").lower()
        brand_l = (p.get("brand") or p.get("attrs_brand") or "").lower()
        q_l = query.lower()
        s = 0
        if name_l.startswith(q_l):
            s += 100
        if q_l in name_l:
            s += 50
        if q_l in brand_l:
            s += 20
        # Boost complete/rich rows (with brand + image + at least one spec)
        if p.get("image_url"):
            s += 5
        if p.get("brand") or p.get("attrs_brand"):
            s += 3
        if p.get("spec_tabs") or p.get("extra_attrs"):
            s += 2
        # Newer entries first (rough tie-breaker)
        s += int((p.get("created_at") or "")[:4] or 0)
        return s

    # De-dupe by (normalised name, brand) so we don't return 12 near-identical
    # "Redmi Note 13" rows from different vendors.
    seen: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for p in raw:
        # Skip current user's own products (their own catalog isn't a "master")
        if own_id and p.get("vendor_id") == own_id:
            continue
        key = (_norm(p.get("name")), _norm(p.get("brand") or p.get("attrs_brand")))
        if not key[0]:
            continue
        prev = seen.get(key)
        if prev is None or score(p) > score(prev):
            seen[key] = p

    ranked = sorted(seen.values(), key=score, reverse=True)[:limit]
    items = [_shape_master_row(p, source="local") for p in ranked]

    return {
        "query": query,
        "count": len(items),
        "items": items,
        # `external_available` signals to the client whether we tried an
        # external fallback (currently always false until scraper-proxy is
        # configured). Kept in the response so the frontend can render the
        # correct "No matches — you'll enter this manually" copy vs. an
        # "external lookup unavailable" hint later.
        "external_available": False,
    }
