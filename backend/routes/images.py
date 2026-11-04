"""Permanent product-image serving (Jun 2026).

Counterpart to `core/image_store.py`.  Emergent Managed Object Storage has
no public URLs, so every read is proxied through our own origin:

    GET /api/img/<sha1>.<ext>[?w=360&q=72]

References are content-addressed, so the bytes behind a key can never
change — we serve them `immutable` with a one-year cache and a strong
ETag.  That is what makes the Android release build cache them properly
instead of re-fetching (and re-failing) on every scroll.

PUBLIC on purpose: React Native's `<Image>` cannot attach a bearer token.
There is no enumeration risk — a key is a SHA-1 of the image bytes, and
product photos are public catalogue data anyway.
"""
from __future__ import annotations

import io
import logging
import re
import time
from typing import Dict, Optional, Tuple

from fastapi import APIRouter, HTTPException, Header, Query
from fastapi.responses import Response

from core.image_store import read_permanent_image

log = logging.getLogger("images")
router = APIRouter(tags=["images"])

_KEY_RE = re.compile(r"^[0-9a-f]{40}\.(jpg|jpeg|png|webp|gif|bmp)$")

#: Tiny in-process LRU so a shop grid of 30 cards doesn't make 30 round
#: trips to object storage on every mount.  Bounded by entry count AND
#: total bytes so a big catalogue can't exhaust the pod's memory.
_CACHE: Dict[str, Tuple[float, bytes, str]] = {}
_CACHE_MAX_ENTRIES = 240
_CACHE_MAX_BYTES = 48 * 1024 * 1024
_CACHE_TTL = 3600.0
_cache_bytes = 0


def _cache_get(key: str) -> Optional[Tuple[bytes, str]]:
    hit = _CACHE.get(key)
    if not hit:
        return None
    ts, data, ctype = hit
    if (time.time() - ts) > _CACHE_TTL:
        _cache_drop(key)
        return None
    return data, ctype


def _cache_drop(key: str) -> None:
    global _cache_bytes
    old = _CACHE.pop(key, None)
    if old:
        _cache_bytes -= len(old[1])


def _cache_put(key: str, data: bytes, ctype: str) -> None:
    global _cache_bytes
    if len(data) > _CACHE_MAX_BYTES // 4:
        return
    _cache_drop(key)
    _CACHE[key] = (time.time(), data, ctype)
    _cache_bytes += len(data)
    while _CACHE and (len(_CACHE) > _CACHE_MAX_ENTRIES or _cache_bytes > _CACHE_MAX_BYTES):
        oldest = min(_CACHE, key=lambda k: _CACHE[k][0])
        _cache_drop(oldest)


def _resize(raw: bytes, w: int, q: int) -> Tuple[bytes, str]:
    """Downscale for grid thumbnails. Falls back to the original bytes."""
    try:
        from PIL import Image, ImageOps
        img = Image.open(io.BytesIO(raw))
        if getattr(img, "is_animated", False):
            return raw, ""
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "L"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            conv = img.convert("RGBA")
            bg.paste(conv, mask=conv.split()[3])
            img = bg
        elif img.mode == "L":
            img = img.convert("RGB")
        target = min(int(w), img.width)
        if target < img.width:
            ratio = target / img.width
            img = img.resize((target, max(1, int(round(img.height * ratio)))), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=max(40, min(95, q)), optimize=True, progressive=True)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        return raw, ""


@router.get("/img/{key}")
async def serve_permanent_image(
    key: str,
    w: Optional[int] = Query(None, ge=16, le=2048, description="Optional max width"),
    q: int = Query(78, ge=40, le=95, description="JPEG quality when resizing"),
    if_none_match: Optional[str] = Header(None, alias="If-None-Match"),
):
    """Stream a permanently-stored product image."""
    key = (key or "").strip().lower()
    if not _KEY_RE.match(key):
        raise HTTPException(status_code=400, detail="Invalid image key")

    etag = f'"{key.split(".")[0][:24]}-{w or 0}-{q}"'
    if if_none_match and if_none_match.strip() == etag:
        return Response(status_code=304, headers={
            "ETag": etag,
            "Cache-Control": "public, max-age=31536000, immutable",
        })

    variant = f"{key}|{w or 0}|{q}"
    cached = _cache_get(variant)
    if cached:
        data, ctype = cached
    else:
        try:
            raw, ctype = await read_permanent_image(key)
        except Exception as exc:
            # Object storage returns 500 for a missing object, so we cannot
            # distinguish "gone" from "down". Either way the client should
            # fall back to its placeholder rather than render a broken box.
            log.info("permanent image %s unavailable: %s", key, exc)
            raise HTTPException(status_code=404, detail="Image not found")
        data = raw
        if w:
            resized, new_ct = _resize(raw, w, q)
            data = resized
            ctype = new_ct or ctype
        _cache_put(variant, data, ctype)

    return Response(
        content=data,
        media_type=ctype or "image/jpeg",
        headers={
            "ETag": etag,
            "Cache-Control": "public, max-age=31536000, immutable",
            "Access-Control-Allow-Origin": "*",
        },
    )
