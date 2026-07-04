"""Product Master Autocomplete (UPDATE 2, June 2026).

Provides a fast typeahead search endpoint for the vendor Add-Product form so
sellers can reuse an existing catalog entry (image, brand, price, specs)
instead of hand-typing everything.

Endpoint (mounted at `/api` by server.py):
  GET  /products/master/search?q=<query>&limit=<N>

Data sources (in order):
  1. LOCAL — the `products` collection (admin + vendor catalogs). Fast, free,
     100% offline-capable.
  2. EXTERNAL — 91mobiles.com public autosuggest JSON API when the local
     hit-count is low.  Cached in `products_master_cache` for 24h so we
     don't hammer their API and to keep repeat searches instant.

Cache layout (`products_master_cache` collection):
  { key: "iphone 15",         # normalised query
    at:  ISO8601 timestamp,
    items: [ ...shaped rows ] }

The 91mobiles JSON we consume today:
  GET https://api.91mobiles.com/api/v1/search/autosuggest?q=<query>&c=all&source=web
  → { query, eshits, suggestions: [{ pro_id, name, brand, model_name,
                                     price, thumbnail, url, category }, ...] }
Only rows with `category == "product"` are kept (skips the top-of-list
"search category" row).

Design decisions:
  • The 91mobiles search box uses this exact API — we're using it the same
    way a browser would, no authentication, no scraping HTML.
  • The rich product detail (spec_tabs, whats_in_box) is NOT available on
    91mobiles' JSON. We still surface name, brand, price, thumbnail —
    enough for the vendor to skip typing the boring parts.
  • Response includes `source: "91mobiles"` so the client can badge the row.
  • If the external API is slow / rate-limits, we silently fall back to the
    local-only result. Never fails the request.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Tuple

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from core.db import db
from core.security import get_current_user
from core.utils import now_utc

log = logging.getLogger("products_master")
router = APIRouter(tags=["products-master"])

# ── 91mobiles autosuggest config ──
_M91_URL = "https://api.91mobiles.com/api/v1/search/autosuggest"
_M91_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-IN,en;q=0.9",
    "Origin": "https://www.91mobiles.com",
    "Referer": "https://www.91mobiles.com/",
}
_M91_TIMEOUT_SECS = 6.0
_M91_CACHE_HOURS = 24
_M91_MIN_LOCAL_HITS = 3  # if local returns fewer than this, augment with 91mobiles


def _norm(s: Any) -> str:
    """Lowercase, collapse whitespace, strip punctuation for de-dupe keys."""
    if not s:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", str(s).lower())).strip()


def _strip_html(s: Any) -> str:
    if not s:
        return ""
    return re.sub(r"<[^>]+>", "", str(s)).strip()


def _shape_master_row(p: Dict[str, Any], source: str = "local") -> Dict[str, Any]:
    """Return the payload the vendor form consumes to prefill fields."""
    return {
        "source": source,  # "local" | "91mobiles"
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
        # Extra hint the vendor might want to see (opens 91mobiles page)
        "external_url": p.get("external_url"),
    }


# ── 91mobiles helpers ──────────────────────────────────────────────────

def _shape_91_row(row: Dict[str, Any]) -> Dict[str, Any] | None:
    """Convert a 91mobiles autosuggest item into our master-search shape.

    Returns None for non-product rows (the top-of-list "Search Category"
    entry the site injects).
    """
    if (row.get("category") or "") != "product":
        return None
    name = _strip_html(row.get("name") or row.get("model_name") or "")
    brand = row.get("brand") or ""
    if not name:
        return None
    price = row.get("price") or 0
    slug = row.get("url") or ""
    external_url = f"https://www.91mobiles.com/{slug}" if slug else None
    thumb = row.get("thumbnail") or ""

    # Try to sniff storage/RAM out of the model name (e.g. "iPhone 15 256GB")
    storage_m = re.search(r"(\d+\s*(?:GB|TB))\b", name, re.I)
    ram_m = re.search(r"(\d+\s*GB)\s*RAM\b", name, re.I)
    attrs_storage = storage_m.group(1).upper().replace(" ", "") if storage_m else ""
    attrs_ram = ram_m.group(1).upper().replace(" ", "") if ram_m else ""

    # Category — 91mobiles autosuggest is mobile-only, so we default to "Mobiles"
    category = "Mobiles"

    # We DON'T set stock/description — the vendor still fills those.
    shaped = {
        "source": "91mobiles",
        "id": f"91m-{row.get('pro_id')}",
        "name": name,
        "brand": brand,
        "image_url": thumb,
        "images": [thumb] if thumb else [],
        "price": int(price) if price else 0,
        "category": category,
        "description": "",
        "sub_features": [],
        "attrs_brand": brand,
        "attrs_os": "",
        "attrs_ram": attrs_ram,
        "attrs_cpu_model": "",
        "attrs_cpu_speed": "",
        "attrs_storage": attrs_storage,
        "extra_attrs": {},
        "price_summary": None,
        "protection_summary": None,
        "warranty_summary": None,
        "delivery_summary": None,
        "spec_tabs": [],
        "whats_in_box": [],
        "external_url": external_url,
    }
    return shaped


async def _cache_get(query_norm: str) -> List[Dict[str, Any]] | None:
    """Return cached 91mobiles rows if they're fresh (<24h), else None."""
    doc = await db.products_master_cache.find_one({"key": query_norm}, {"_id": 0})
    if not doc:
        return None
    try:
        from datetime import datetime, timezone, timedelta
        at = doc.get("at")
        if isinstance(at, str):
            at = datetime.fromisoformat(at.replace("Z", "+00:00"))
        if at and (now_utc() - at).total_seconds() < _M91_CACHE_HOURS * 3600:
            return doc.get("items") or []
    except Exception:
        pass
    return None


async def _cache_set(query_norm: str, items: List[Dict[str, Any]]) -> None:
    """Upsert the 91mobiles rows for this query."""
    try:
        await db.products_master_cache.update_one(
            {"key": query_norm},
            {"$set": {
                "key": query_norm,
                "at": now_utc().isoformat(),
                "items": items,
            }},
            upsert=True,
        )
    except Exception as e:
        log.warning("products_master_cache write failed: %s", e)


async def _fetch_91mobiles(query: str) -> List[Dict[str, Any]]:
    """Hit 91mobiles autosuggest and return shaped product rows. Never raises."""
    params = {"q": query, "c": "all", "source": "web", "sticky": "false"}
    try:
        async with httpx.AsyncClient(timeout=_M91_TIMEOUT_SECS, follow_redirects=True) as client:
            r = await client.get(_M91_URL, params=params, headers=_M91_HEADERS)
        if r.status_code != 200:
            log.info("91mobiles autosuggest non-200: %s", r.status_code)
            return []
        data = r.json()
    except Exception as e:
        log.info("91mobiles fetch failed (%s): %s", type(e).__name__, e)
        return []
    suggestions = data.get("suggestions") or []
    out: List[Dict[str, Any]] = []
    for row in suggestions:
        s = _shape_91_row(row)
        if s:
            out.append(s)
    return out


@router.get("/products/master/search")
async def master_search(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(10, ge=1, le=25),
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Typeahead search across the LOCAL catalog + 91mobiles autosuggest.

    Order of operations:
      1. Query the local `products` collection (fast, always runs).
      2. If the local result set is thin (< 3 hits), fire 91mobiles in
         parallel. Cached 24h in `products_master_cache`.
      3. Merge, de-dupe by (norm(name)+norm(brand)) preferring local rows
         because they carry richer specs.

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
    for t in tokens:
        or_clauses.append({"name": {"$regex": t, "$options": "i"}})
        or_clauses.append({"brand": {"$regex": t, "$options": "i"}})

    mongo_q: Dict[str, Any] = {"$or": or_clauses}

    # Pull a wider window than needed so ranking + de-dupe can trim it.
    raw = await db.products.find(mongo_q, {"_id": 0}).limit(limit * 6).to_list(limit * 6)

    own_id = user.get("id")

    def local_score(p: Dict[str, Any]) -> int:
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
        if p.get("image_url"):
            s += 5
        if p.get("brand") or p.get("attrs_brand"):
            s += 3
        if p.get("spec_tabs") or p.get("extra_attrs"):
            s += 2
        s += int((p.get("created_at") or "")[:4] or 0)
        return s

    # De-dupe local rows by (normalised name, brand)
    seen: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for p in raw:
        if own_id and p.get("vendor_id") == own_id:
            continue
        key = (_norm(p.get("name")), _norm(p.get("brand") or p.get("attrs_brand")))
        if not key[0]:
            continue
        prev = seen.get(key)
        if prev is None or local_score(p) > local_score(prev):
            seen[key] = p

    local_shaped = [_shape_master_row(p, source="local") for p in sorted(seen.values(), key=local_score, reverse=True)]

    # ── External augment (91mobiles) ──
    external_available = True
    external_used = False
    external_shaped: List[Dict[str, Any]] = []
    if len(local_shaped) < _M91_MIN_LOCAL_HITS:
        query_norm = _norm(query)
        cached = await _cache_get(query_norm)
        if cached is not None:
            external_shaped = cached
        else:
            try:
                external_shaped = await asyncio.wait_for(_fetch_91mobiles(query), timeout=_M91_TIMEOUT_SECS + 1)
                if external_shaped:
                    await _cache_set(query_norm, external_shaped)
            except Exception:
                external_shaped = []
        external_used = bool(external_shaped)

    # Merge — local rows first (they carry richer specs vendors want)
    merged: List[Dict[str, Any]] = list(local_shaped)
    already: set = {(_norm(r["name"]), _norm(r.get("brand"))) for r in merged}
    for row in external_shaped:
        key = (_norm(row.get("name")), _norm(row.get("brand")))
        if key in already:
            continue
        merged.append(row)
        already.add(key)

    merged = merged[:limit]

    return {
        "query": query,
        "count": len(merged),
        "items": merged,
        # Whether the 91mobiles fallback was queried this call — helps the
        # client show "Searching web…" hints and (later) a badge on external rows.
        "external_available": external_available,
        "external_used": external_used,
        "local_hits": len(local_shaped),
    }

