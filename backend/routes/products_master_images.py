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


# ── Server-side proxy + base64 fetch ─────────────────────────────────
# Sept 2026 — Rationale.
#   The RN app running on `localhost:3000` (Metro dev) or `slangcart.com`
#   (production) hits Wikimedia's CDN with a `Referer` header that
#   Wikimedia's hotlink policy sometimes rejects, and Wikimedia does not
#   send `Access-Control-Allow-Origin: *` so JS `fetch()` → `blob()`
#   fails with a CORS error even when `<img>` succeeds.  Both symptoms
#   were visible in the vendor screenshot: blank thumbnail cells + a
#   "Couldn't download the selected images" toast when tapping Use.
#
#   Fix: do EVERY image fetch server-side.
#     * `GET  /products/images/proxy?url=…`  → streams the bytes with a
#       browser UA + explicit `Referer` header so the mobile app can
#       render Wikimedia thumbnails as regular images.
#     * `POST /products/images/fetch-to-data` → accepts a list of URLs,
#       returns a matching list of base64 `data:image/…` strings ready
#       to drop straight into the product doc's `image_url`/`images`.
from urllib.parse import urlparse

from fastapi.responses import Response
from pydantic import BaseModel

_PROXY_ALLOWED_HOSTS = {
    # Openverse serves via api.openverse.org (redirect) + these upstreams:
    "api.openverse.org", "upload.wikimedia.org", "commons.wikimedia.org",
    "live.staticflickr.com", "farm1.staticflickr.com", "farm2.staticflickr.com",
    "farm3.staticflickr.com", "farm4.staticflickr.com", "farm5.staticflickr.com",
    "farm6.staticflickr.com", "farm7.staticflickr.com", "farm8.staticflickr.com",
    "farm9.staticflickr.com", "cdn.stocksnap.io", "images.nappy.co",
    "stocksnap.io", "images.pexels.com", "images.unsplash.com",
    "burst.shopifycdn.com", "www.pxfuel.com", "get.pxhere.com",
    "cdn.pixabay.com", "cdn0.pixabay.com", "cdn1.pixabay.com",
    "cdn2.pixabay.com", "cdn3.pixabay.com",
}


def _proxy_headers_for(host: str) -> Dict[str, str]:
    """Return headers with a UA + Referer the upstream trusts.

    Wikimedia's `upload.wikimedia.org` CDN enforces their bot-agent policy:
    generic `Mozilla/5.0` UAs are HTTP 403, but identifiable UAs (with a
    contact URL) get 200.  Every other allow-listed CDN behaves like a
    regular browser CDN and expects a browser UA.
    """
    is_wikimedia = "wikimedia" in host
    ua = (
        "SlangcartBot/1.0 (https://slangcart.com; ops@slangcart.com)"
        if is_wikimedia
        else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    referer = "https://commons.wikimedia.org/" if is_wikimedia else f"https://{host}/"
    return {
        "User-Agent": ua,
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": referer,
    }


@router.get("/products/images/proxy")
async def proxy_image(
    url: str = Query(..., min_length=8, max_length=2000),
    # Intentionally PUBLIC — RN `<Image>` cannot pass Bearer tokens.
    # Security is bound by the `_PROXY_ALLOWED_HOSTS` allow-list which
    # only permits well-known Creative-Commons image CDNs, so there is
    # no SSRF or private-network exfiltration surface here.
):
    """Stream an image from an allow-listed public CDN through our origin.

    Frontend uses this for thumbnail rendering (avoids Wikimedia hotlink
    quirks + CORS on RN Web).  Only allow-listed hosts are proxied — no
    open SSRF vector.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not host or host not in _PROXY_ALLOWED_HOSTS:
        raise HTTPException(status_code=400, detail=f"Host '{host}' not allow-listed for image proxying")
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Only http/https URLs are supported")
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            r = await client.get(url, headers=_proxy_headers_for(host))
    except Exception as e:
        log.info("Image proxy fetch failed for %s: %s", url, e)
        raise HTTPException(status_code=502, detail="Upstream image fetch failed")
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=f"Upstream returned {r.status_code}")
    content_type = r.headers.get("content-type", "image/jpeg")
    if not content_type.startswith("image/"):
        # Some sites 200 an HTML "please turn on JS" page — reject to
        # avoid poisoning the frontend cache with non-image bytes.
        raise HTTPException(status_code=502, detail="Upstream returned non-image content")
    return Response(
        content=r.content,
        media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=86400, immutable",
            # Explicit CORS so RN Web fetch() consumers also work if they
            # bypass our proxy later.
            "Access-Control-Allow-Origin": "*",
        },
    )


class BatchFetchIn(BaseModel):
    urls: List[str]


@router.post("/products/images/fetch-to-data")
async def batch_fetch_to_data_urls(
    body: BatchFetchIn,
    user: Dict[str, Any] = Depends(get_current_user),  # noqa: F841
):
    """Convert a list of remote image URLs into base64 `data:image/…`
    strings ready to persist as `image_url` / `images[]` on a product.

    Runs the fetches in parallel with a small concurrency cap so a
    5-image pick completes in one round-trip.  Silently skips URLs whose
    host isn't on `_PROXY_ALLOWED_HOSTS`, whose upstream errored, or
    whose byte size exceeds 2 MB (keeps Mongo docs sane).
    """
    urls = list(body.urls or [])
    if not urls:
        raise HTTPException(status_code=400, detail="urls is required")
    if len(urls) > 20:
        raise HTTPException(status_code=400, detail="Max 20 URLs per request")

    MAX_BYTES = 2 * 1024 * 1024  # 2 MB per image

    async def _one(url: str) -> Optional[str]:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if not host or host not in _PROXY_ALLOWED_HOSTS:
            return None
        if parsed.scheme not in ("http", "https"):
            return None
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
                r = await client.get(url, headers=_proxy_headers_for(host))
        except Exception as e:
            log.info("batch fetch failed for %s: %s", url, e)
            return None
        if r.status_code != 200:
            return None
        ct = r.headers.get("content-type", "image/jpeg")
        if not ct.startswith("image/"):
            return None
        if len(r.content) > MAX_BYTES:
            return None
        import base64
        b64 = base64.b64encode(r.content).decode("ascii")
        return f"data:{ct};base64,{b64}"

    # Concurrency cap of 5 — plenty for a picker, keeps memory bounded.
    sem = asyncio.Semaphore(5)

    async def _with_sem(u: str) -> Optional[str]:
        async with sem:
            return await _one(u)

    results = await asyncio.gather(*(_with_sem(u) for u in urls))

    out: List[Dict[str, Any]] = []
    for u, d in zip(urls, results):
        out.append({"url": u, "data_url": d, "ok": d is not None})
    ok_count = sum(1 for r in out if r["ok"])
    if ok_count == 0:
        raise HTTPException(status_code=502, detail="Every upstream image fetch failed")
    return {"count": len(out), "ok_count": ok_count, "items": out}
