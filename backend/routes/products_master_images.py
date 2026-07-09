"""Free image search — powers the "🖼️ Free image picker" in Smart Search
(Sept 2026).

Owner asked for a Google-Images-style picker that:
  1. Returns non-e-commerce images (no Amazon, Flipkart, Meesho, etc.)
  2. Uses zero paid API keys
  3. Works for Indian regional terms like "Bellam" (jaggery), "Uddi pappu"
     (urad dal), "Kandi pappu" (toor dal), "Senaga pappu" (chana dal)

We use two Creative-Commons-friendly image sources, in order:

  1. **Openverse** (api.openverse.org) — Wordpress Foundation's aggregator
     of Wikimedia Commons + Flickr CC + Nappy + StockSnap + ~30 more.
     100% royalty-free and marketplace-safe by definition (only CC content).
     No API key required.
  2. **Wikimedia Commons** (commons.wikimedia.org/w/api.php) — direct
     fallback when Openverse comes up empty (e.g. very niche cultural
     terms).  Also 100% royalty-free.

Both sources are queried in ENGLISH when possible — we auto-translate a
short lexicon of common Indian regional grocery / spice / cloth terms
(Telugu / Hindi / Tamil).  If the query already has ≥3 Openverse hits
we skip translation to preserve exactness.

DuckDuckGo image search was ORIGINALLY chosen for this feature (per the
owner's spec) but the pod's egress firewall blocks duckduckgo.com — see
Sept-2026 investigation in git log.  Openverse/Wikimedia both work and
actually deliver a better UX because they hard-guarantee CC licence.

Endpoint (mounted at /api by server.py):
  GET /products/images/search?q=<query>&limit=<N>

Response:
  { "query": "sugar",
    "resolved_query": "sugar",       # what we actually searched (post-translation)
    "count": 20,
    "items": [
      { "image": "https://.../foo.jpg",
        "thumbnail": "https://.../foo_thumb.jpg",
        "title": "White refined sugar",
        "source": "wikimedia",
        "provider": "wikimedia",
        "width": 1024, "height": 768,
        "license": "CC BY-SA 4.0" },
      ...
    ] }
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from core.db import db
from core.security import get_current_user
from core.utils import now_utc

log = logging.getLogger("products_master_images")
router = APIRouter(tags=["products-master-images"])

# ── Config ────────────────────────────────────────────────────────────
_OPENVERSE_URL = "https://api.openverse.org/v1/images/"
_WIKIMEDIA_URL = "https://commons.wikimedia.org/w/api.php"
_TIMEOUT = 10.0
_CACHE_TTL_HOURS = 24

# Owner-provided UA — Wikimedia hard-requires an identifiable agent.
_HEADERS = {
    "User-Agent": "SlangcartBot/1.0 (https://slangcart.com; ops@slangcart.com)",
    "Accept": "application/json",
}

# Hide obvious e-commerce sources — owner asked "plain image, no
# ecommerce sites".  Openverse only indexes CC sources so this mostly
# hits Wikimedia's occasional catalogue-page images.
_ECOMMERCE_BLOCKLIST = {
    "amazon", "flipkart", "alibaba", "shopee", "meesho", "ajio",
    "myntra", "snapdeal", "deodap", "aliexpress", "tatacliq", "nykaa",
    "firstcry", "reliancedigital", "croma", "shopify", "etsy", "ebay",
    "walmart", "target", "bestbuy",
}

# ── Indian regional grocery/spice translations ────────────────────────
# Mostly Telugu / Hindi / Tamil food staples that don't index in
# Openverse or Wikimedia under the vernacular name.  Extend as needed —
# this dict is the "why doesn't Bellam return anything" fix.
_TRANSLATIONS = {
    # Sugar / sweeteners
    "bellam": "jaggery",
    "gud": "jaggery",
    "vellam": "jaggery",
    "khand": "sugar cube",
    # Dals / pulses
    "uddi pappu": "urad dal",
    "minap pappu": "urad dal",
    "minapa pappu": "urad dal",
    "kandi pappu": "toor dal",
    "kandhi pappu": "toor dal",
    "arhar dal": "toor dal",
    "senaga pappu": "chana dal",
    "sanaga pappu": "chana dal",
    "pesara pappu": "moong dal",
    "moong pappu": "moong dal",
    "masoor pappu": "masoor dal",
    "chintapandu": "tamarind",
    # Grains
    "biyyam": "rice",
    "godhumalu": "wheat grain",
    # Spices
    "karivepaku": "curry leaves",
    "kothimeera": "coriander leaves",
    "pudina": "mint leaves",
    "aavalu": "mustard seeds",
    "jilakara": "cumin seeds",
    "dhaniyalu": "coriander seeds",
    "menthulu": "fenugreek seeds",
    # Vegetables
    "vankaya": "brinjal",
    "aloogadda": "potato",
    "ullipaya": "onion",
    "vellulli": "garlic",
    "allam": "ginger",
    "tomatalu": "tomato",
    "bhindi": "okra",
    "bendakaya": "okra",
    # Fruits
    "aavakaya": "mango pickle",
    "mamidikaya": "raw mango",
    "arati pandu": "banana",
    "boppayi": "papaya",
}


def _norm(q: str) -> str:
    return re.sub(r"\s+", " ", (q or "").strip().lower())


def _translate(q: str) -> Optional[str]:
    """Look up a vernacular Indian term; return the English equivalent or None."""
    key = _norm(q)
    if not key:
        return None
    # Exact match
    if key in _TRANSLATIONS:
        return _TRANSLATIONS[key]
    # Substring match — e.g. "senaga pappu 1kg" matches "senaga pappu"
    for k, v in _TRANSLATIONS.items():
        if k in key:
            return v
    return None


def _is_ecommerce(source: str) -> bool:
    s = (source or "").lower()
    for blk in _ECOMMERCE_BLOCKLIST:
        if blk in s:
            return True
    return False


# ── Openverse ─────────────────────────────────────────────────────────
async def _fetch_openverse(client: httpx.AsyncClient, q: str, want: int) -> List[Dict[str, Any]]:
    """Pull CC images from Openverse. Returns shaped list; never raises."""
    try:
        r = await client.get(
            _OPENVERSE_URL,
            params={"q": q, "page_size": min(max(want, 20), 40)},
            headers=_HEADERS,
        )
    except Exception as e:
        log.info("Openverse fetch failed: %s", e)
        return []
    if r.status_code != 200:
        log.info("Openverse non-200: %s", r.status_code)
        return []
    try:
        data = r.json()
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for row in data.get("results") or []:
        img = row.get("url") or ""
        thumb = row.get("thumbnail") or img
        if not img.startswith("http"):
            continue
        source_host = (row.get("source") or "").lower()
        if _is_ecommerce(source_host):
            continue
        out.append({
            "image": img,
            "thumbnail": thumb,
            "title": (row.get("title") or "").strip()[:120],
            "source": row.get("source") or "openverse",
            "provider": "openverse",
            "width": row.get("width") or None,
            "height": row.get("height") or None,
            "license": (row.get("license") or "").upper() + (" " + str(row.get("license_version")) if row.get("license_version") else ""),
        })
    return out


# ── Wikimedia Commons fallback ─────────────────────────────────────────
async def _fetch_wikimedia(client: httpx.AsyncClient, q: str, want: int) -> List[Dict[str, Any]]:
    """Pull images from Wikimedia Commons directly. Never raises."""
    try:
        r = await client.get(
            _WIKIMEDIA_URL,
            params={
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrnamespace": "6",  # File namespace
                "gsrsearch": q,
                "gsrlimit": min(max(want, 15), 30),
                "prop": "imageinfo",
                "iiprop": "url|size|extmetadata",
                "iiurlwidth": 400,
            },
            headers=_HEADERS,
        )
    except Exception as e:
        log.info("Wikimedia fetch failed: %s", e)
        return []
    if r.status_code != 200:
        log.info("Wikimedia non-200: %s", r.status_code)
        return []
    try:
        data = r.json()
    except Exception:
        return []
    pages = (data.get("query") or {}).get("pages") or {}
    out: List[Dict[str, Any]] = []
    # Sort by page index to match Wikimedia's own ordering
    for _, p in sorted(pages.items(), key=lambda kv: kv[1].get("index", 0)):
        ii_list = p.get("imageinfo") or []
        if not ii_list:
            continue
        ii = ii_list[0]
        url = ii.get("url") or ""
        thumb = ii.get("thumburl") or url
        if not url.startswith("http"):
            continue
        # Skip SVG (renders poorly as product cover) and audio/video.
        low = url.lower()
        if low.endswith((".svg", ".ogg", ".webm", ".ogv", ".mid", ".pdf")):
            continue
        w = ii.get("width") or 0
        h = ii.get("height") or 0
        title = (p.get("title") or "File:").replace("File:", "").rsplit(".", 1)[0][:120]
        meta = ii.get("extmetadata") or {}
        licence = (meta.get("LicenseShortName") or {}).get("value") or ""
        out.append({
            "image": url,
            "thumbnail": thumb,
            "title": title.replace("_", " "),
            "source": "commons.wikimedia.org",
            "provider": "wikimedia",
            "width": int(w) if w else None,
            "height": int(h) if h else None,
            "license": licence,
        })
    return out


# ── Route ─────────────────────────────────────────────────────────────
@router.get("/products/images/search")
async def search_free_images(
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(20, ge=1, le=40),
    user: Dict[str, Any] = Depends(get_current_user),  # noqa: F841
):
    """Free, non-e-commerce, Creative-Commons image search.

    Under the hood: Openverse (primary) + Wikimedia Commons (fallback for
    regional terms).  Auto-translates common Telugu grocery/spice words
    (bellam → jaggery, uddi pappu → urad dal, etc.) when the raw query
    returns fewer than 3 hits.

    Response payload includes the `resolved_query` we actually searched
    so the frontend can show a "Showing results for 'jaggery'" hint if
    we translated.
    """
    query = (q or "").strip()
    if len(query) < 1:
        raise HTTPException(status_code=400, detail="Query is required")

    cache_key = f"free_imgs::{_norm(query)}"
    try:
        cached = await db.products_master_cache.find_one({"key": cache_key}, {"_id": 0})
        if cached:
            from datetime import datetime
            at = cached.get("at")
            if isinstance(at, str):
                at = datetime.fromisoformat(at.replace("Z", "+00:00"))
            if at and (now_utc() - at).total_seconds() < _CACHE_TTL_HOURS * 3600:
                items = cached.get("items") or []
                if items:
                    return {
                        "query": query,
                        "resolved_query": cached.get("resolved_query") or query,
                        "count": min(len(items), limit),
                        "items": items[:limit],
                    }
    except Exception:
        pass

    resolved_query = query
    translation = _translate(query)
    # Sept 2026 fix — For KNOWN vernacular keys we always translate.
    # Previously we only translated when the raw query returned <3 hits,
    # but Openverse sometimes returns partially-matching cruft (e.g.
    # "Bellam Pulusu" for "Bellam") that fills the quota without actually
    # showing jaggery. Better UX: translate up-front for terms we've
    # explicitly mapped, and fall back to the raw query only if the
    # translation itself comes up empty.
    known_vernacular = bool(translation)

    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        if known_vernacular and translation and translation.lower() != query.lower():
            # Search with translation first
            resolved_query = translation
            primary = await _fetch_openverse(client, translation, limit)
            # If translation gave nothing, fall back to the raw query
            if not primary:
                resolved_query = query
                primary = await _fetch_openverse(client, query, limit)
        else:
            # 1. Openverse with the raw query
            primary = await _fetch_openverse(client, query, limit)
            # 2. If thin, retry with English translation (should be rare
            #    now — most vernacular hits are handled above)
            if len(primary) < 3 and translation and translation.lower() != query.lower():
                resolved_query = translation
                primary = await _fetch_openverse(client, translation, limit)

        # 3. If still thin, fall back to Wikimedia Commons on the resolved query
        wm: List[Dict[str, Any]] = []
        if len(primary) < 5:
            wm = await _fetch_wikimedia(client, resolved_query, limit)

    # Merge — de-dupe by image URL, prefer Openverse ordering.
    merged: List[Dict[str, Any]] = []
    seen: set = set()
    for row in primary + wm:
        img = row.get("image") or ""
        if not img or img in seen:
            continue
        seen.add(img)
        merged.append(row)
        if len(merged) >= max(limit, 30):
            break

    if not merged:
        raise HTTPException(
            status_code=404,
            detail=f"No safe (non-ecommerce) images found for '{query}'. "
                   f"Try a simpler English term, e.g. 'jaggery' instead of 'bellam'.",
        )

    try:
        await db.products_master_cache.update_one(
            {"key": cache_key},
            {"$set": {
                "key": cache_key,
                "at": now_utc().isoformat(),
                "resolved_query": resolved_query,
                "items": merged,
            }},
            upsert=True,
        )
    except Exception:
        pass

    return {
        "query": query,
        "resolved_query": resolved_query,
        "count": len(merged[:limit]),
        "items": merged[:limit],
    }
