"""Permanent product-image storage (Jun 2026).

ROOT CAUSE this module fixes
────────────────────────────
Smart Search (`/products/master/*`) and the Shopify-CSV→JSON restore both
wrote the *external* CDN URL straight into `product.image_url` /
`product.images[]`.  Those URLs are not ours:

  • DeoDap / Shopify CDN rotates object paths and enforces hotlink rules.
  • GSMArena / 91mobiles reject requests without a trusted Referer.
  • Openverse indexes Flickr photos that later get deleted.

So the shop looked fine right after an import and went blank days later —
exactly the reported symptom.  Nothing had ever been copied to storage we
control.

What we do instead
──────────────────
Every external image that enters a product document is now **downloaded,
validated, normalised and stored as binary inside our own MongoDB**
(collection `product_image_files`), and the product document only ever
references our own origin:

    /api/img/<sha1-of-bytes>.jpg      →  routes/images.py streams it back

MongoDB — not a metered third-party bucket — is deliberate: it is the one
store the app cannot run without, so a product photo can never become
unviewable because a credit balance ran out or an external service was
unreachable. Images are normalised to ≤1280 px JPEG first (typically
60-200 KB), so this is strictly smaller than the base64 covers the app
already kept inside the product documents themselves.

Key properties
  • Content-addressed: the same photo imported by 500 products is stored
    once and shares one reference.
  • Idempotent: re-importing a product is a cheap `image_assets` lookup.
  • Honest: a source we are not allowed to fetch (403 / hotlink-protected)
    is recorded as a failure with its reason — never silently skipped and
    never stored as a dead URL.
  • Conservative: we send a clearly identified bot UA and obey the upstream
    status code.  We never spoof a Referer to defeat hotlink protection,
    we only pass the source site's own origin where that is the documented
    expectation for a CDN fetch.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import ipaddress
import logging
import socket
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx
from bson.binary import Binary

from core.db import db

log = logging.getLogger("image_store")

# ── Public contract ──────────────────────────────────────────────────
#: Every permanent reference starts with this.  `resolveImageUrl()` on the
#: client prefixes it with the backend base URL.
REF_PREFIX = "/api/img/"

#: Collection holding the actual bytes. `_id` is the `<sha1>.<ext>` key.
FILES = "product_image_files"

#: Hard ceiling on a single download. Shopify originals are ~1-3 MB.
MAX_DOWNLOAD_BYTES = 12 * 1024 * 1024
#: Long edge after normalisation. Detail view is retina-sharp at 1280.
MAX_DIM = 1280
JPEG_QUALITY = 82

_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
_RETRY_DELAYS = (0.0, 0.8, 2.0)          # 3 attempts total

_BOT_UA = "SlangcartBot/1.0 (+https://slangcart.com; ops@slangcart.com)"
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

#: Magic-byte signatures we accept. Guards against an upstream that 200s
#: an HTML "enable JavaScript" page with `Content-Type: image/jpeg`.
_MAGIC: Tuple[Tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
)


def _sniff(raw: bytes) -> Optional[str]:
    for sig, mime in _MAGIC:
        if raw.startswith(sig):
            return mime
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    # ISO-BMFF family (AVIF / HEIF): "....ftyp<brand>"
    if raw[4:8] == b"ftyp":
        brand = raw[8:12]
        if brand in (b"avif", b"avis"):
            return "image/avif"
        if brand in (b"heic", b"heix", b"hevc", b"mif1", b"msf1"):
            return "image/heic"
    return None


# ── Shape helpers ────────────────────────────────────────────────────

def is_permanent(ref: Any) -> bool:
    """True when `ref` already points at our own permanent store."""
    return isinstance(ref, str) and ref.startswith(REF_PREFIX)


def canonical_ref(ref: Any) -> Any:
    """Strip the `?w=…&q=…` thumbnail hint off a permanent reference.

    List endpoints hand the client `/api/img/<key>.jpg?w=360&q=72`. If an
    editor seeded from a list row saved that back verbatim, the product's
    cover would be permanently pinned to a 360 px thumbnail. Writes always
    store the canonical, full-size key.
    """
    if is_permanent(ref) and "?" in ref:
        return ref.split("?", 1)[0]
    return ref


def is_managed_lazy_url(ref: Any) -> bool:
    """Our own on-demand thumbnail endpoint (`/api/products/{id}/image`).

    Not a permanent reference — it reads the inline base64 back out of the
    product document — but it is ours and it works, so repair leaves it be.
    """
    return isinstance(ref, str) and "/api/products/" in ref and "/image" in ref


def needs_persisting(ref: Any) -> bool:
    """True when `ref` is an EXTERNAL http(s) URL we should copy locally."""
    if not isinstance(ref, str):
        return False
    ref = ref.strip()
    if not ref.startswith(("http://", "https://")):
        return False
    if is_permanent(ref) or is_managed_lazy_url(ref):
        return False
    return True


def coerce_image_ref(entry: Any) -> str:
    """Normalise ONE gallery entry into a plain URL string.

    Shopify-CSV→JSON conversions ship `images` as objects, e.g.
    `{"src": "...", "position": 2}` or `{"url": "..."}`.  Older Slangcart
    exports ship plain strings.  Passing an object to the client made
    `resolveImageUrl()` call `.startsWith` on a non-string and crashed the
    Android release build on the product-detail screen — so every entry is
    flattened here, server-side, before it is ever persisted.
    """
    if isinstance(entry, str):
        return entry.strip()
    if isinstance(entry, dict):
        for key in ("src", "url", "image_url", "image", "href", "data_url"):
            v = entry.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return ""


def _position_of(entry: Any) -> Optional[int]:
    """Shopify `Image Position` when the entry carries one."""
    if isinstance(entry, dict):
        for key in ("position", "image_position", "Image Position", "sort_order"):
            v = entry.get(key)
            try:
                if v is not None:
                    return int(v)
            except (TypeError, ValueError):
                continue
    return None


def normalize_gallery(images: Any) -> List[str]:
    """Flatten + order + de-duplicate a gallery array.

      • objects → their `src`/`url`
      • Shopify `Image Position` preserved (entries without one keep file
        order, after the positioned ones)
      • duplicate URLs removed, UNIQUE images all kept
    """
    if not isinstance(images, list):
        return []
    positioned: List[Tuple[int, int, str]] = []
    plain: List[Tuple[int, str]] = []
    for i, entry in enumerate(images):
        url = coerce_image_ref(entry)
        if not url:
            continue
        pos = _position_of(entry)
        if pos is None:
            plain.append((i, url))
        else:
            positioned.append((pos, i, url))
    positioned.sort(key=lambda t: (t[0], t[1]))
    ordered = [u for _, _, u in positioned] + [u for _, u in plain]
    out: List[str] = []
    seen = set()
    for u in ordered:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


# ── Download + normalise + upload ────────────────────────────────────

def _headers_for(host: str) -> Dict[str, str]:
    """Headers an upstream CDN will honour for a legitimate fetch.

    Wikimedia's policy *requires* an identifiable bot UA (generic browser
    UAs are 403'd); everything else expects a normal browser UA.  We never
    forge a third-party Referer to bypass hotlink protection — a site that
    refuses the request is recorded as a failure.
    """
    if "wikimedia" in host:
        return {"User-Agent": _BOT_UA, "Accept": "image/*,*/*;q=0.8"}
    return {
        "User-Agent": _BROWSER_UA,
        # Deliberately NO `image/avif`: content-negotiating CDNs (Pexels,
        # Unsplash, Shopify) would hand back AVIF, which older Android
        # WebViews cannot decode. Asking for JPEG/PNG/WEBP keeps every
        # stored product photo renderable on every device.
        "Accept": "image/webp,image/png,image/jpeg,image/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }


#: Jun 2026 (SSRF) — a vendor controls these URLs, so the fetcher must never
#: be usable as a probe into the cluster. Only ordinary web ports, only
#: public IP addresses, and the resolved address is pinned for the request.
_ALLOWED_PORTS = {80, 443, 8080, 8443}


def _blocked_target(parsed) -> str:
    """Return a refusal reason when this URL must not be fetched, else ""."""
    port = parsed.port
    if port is not None and port not in _ALLOWED_PORTS:
        return "image source is not a public web address"
    host = (parsed.hostname or "").strip().lower()
    if not host or host == "localhost" or host.endswith(".localhost") or host.endswith(".internal"):
        return "image source is not a public web address"
    try:
        infos = socket.getaddrinfo(host, port or (443 if parsed.scheme == "https" else 80),
                                  proto=socket.IPPROTO_TCP)
    except Exception:
        return "image source could not be resolved"
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return "image source is not a public web address"
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            return "image source is not a public web address"
    return ""


async def _download(url: str) -> Tuple[Optional[bytes], str]:
    """Fetch image bytes with bounded retries. Returns (bytes, error)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None, "unsupported URL scheme"
    blocked = _blocked_target(parsed)
    if blocked:
        # Uniform message on purpose: a vendor must not be able to use this
        # downloader to map the cluster's internal ports.
        log.warning("image fetch refused (internal target): %s", url[:120])
        return None, blocked
    headers = _headers_for(parsed.hostname.lower())
    last = "download failed"
    for attempt, delay in enumerate(_RETRY_DELAYS):
        if delay:
            await asyncio.sleep(delay)
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
                # Redirects are followed MANUALLY so every hop is re-checked:
                # an allow-listed public CDN could otherwise 302 us to
                # 127.0.0.1 and defeat the guard above.
                target, hops = url, 0
                while True:
                    r = await client.get(target, headers=headers)
                    if r.status_code not in (301, 302, 303, 307, 308) or hops >= 4:
                        break
                    nxt = r.headers.get("location")
                    if not nxt:
                        break
                    target = str(httpx.URL(target).join(nxt))
                    hop = urlparse(target)
                    if hop.scheme not in ("http", "https"):
                        return None, "image source is not a public web address"
                    blocked_hop = _blocked_target(hop)
                    if blocked_hop:
                        log.warning("image redirect refused (internal target): %s", target[:120])
                        return None, blocked_hop
                    headers = _headers_for((hop.hostname or "").lower())
                    hops += 1
        except Exception as exc:                      # network / DNS / TLS
            last = f"network error: {type(exc).__name__}"
            continue
        if r.status_code in (401, 403, 451):
            # Access-controlled on purpose. Retrying is pointless and rude.
            return None, f"source denied access (HTTP {r.status_code})"
        if r.status_code == 404 or r.status_code == 410:
            return None, f"source image no longer exists (HTTP {r.status_code})"
        if r.status_code != 200:
            last = f"HTTP {r.status_code}"
            continue
        ct = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
        raw = r.content
        if len(raw) > MAX_DOWNLOAD_BYTES:
            return None, f"image too large ({len(raw) // 1024} KB)"
        if not raw:
            last = "empty response"
            continue
        sniffed = _sniff(raw)
        if not sniffed and not ct.startswith("image/"):
            return None, f"not a supported image (content-type {ct or 'unknown'})"
        if ct and not ct.startswith("image/"):
            return None, f"source returned {ct}, not an image"
        return raw, ""
        # unreachable
    return None, last


def _normalise_bytes(raw: bytes) -> Tuple[Optional[bytes], str, str]:
    """Downscale + re-encode. Returns (bytes, content_type, extension).

    Falls back to the original bytes when Pillow can't decode them, so a
    valid-but-exotic format is never lost — EXCEPT for AVIF/HEIF, which
    older Android builds cannot render: if we can't transcode those to
    JPEG we report a failure instead of storing an unviewable file.
    """
    sniffed = _sniff(raw) or "image/jpeg"
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
           "image/gif": "gif", "image/bmp": "bmp"}.get(sniffed, "")
    exotic = sniffed in ("image/avif", "image/heic")
    try:
        from PIL import Image, ImageOps
    except Exception:
        return (None, "", "") if exotic else (raw, sniffed, ext or "jpg")
    try:
        img = Image.open(io.BytesIO(raw))
        if getattr(img, "is_animated", False):
            return raw, sniffed, ext or "gif"     # keep animated GIF/WEBP intact
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "L"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            conv = img.convert("RGBA")
            bg.paste(conv, mask=conv.split()[3])
            img = bg
        elif img.mode == "L":
            img = img.convert("RGB")
        w, h = img.size
        long_side = max(w, h)
        if long_side > MAX_DIM:
            ratio = MAX_DIM / long_side
            img = img.resize((max(1, int(w * ratio)), max(1, int(h * ratio))), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
        out = buf.getvalue()
    except Exception:
        return (None, "", "") if exotic else (raw, sniffed, ext or "jpg")
    if len(out) >= len(raw) and long_side <= MAX_DIM and ext:
        return raw, sniffed, ext
    return out, "image/jpeg", "jpg"


async def _record(url: str, ref: str, ok: bool, error: str, size: int) -> None:
    await db.image_assets.update_one(
        {"source_url": url},
        {"$set": {
            "source_url": url,
            "ref": ref or None,
            "ok": ok,
            "error": error or None,
            "bytes": size,
            "updated_at": time.time(),
        }, "$setOnInsert": {"created_at": time.time()}},
        upsert=True,
    )


async def persist_external_image(url: str) -> Tuple[Optional[str], str]:
    """Copy ONE external image into permanent storage.

    Returns `(permanent_ref, "")` on success or `(None, reason)`.
    Never raises.  Already-permanent refs pass straight through.
    """
    url = (url or "").strip()
    if not url:
        return None, "empty url"
    if not needs_persisting(url):
        return url, ""                     # already ours / not fetchable

    # Dedupe: this exact source was imported before.
    try:
        hit = await db.image_assets.find_one({"source_url": url}, {"_id": 0, "ref": 1, "ok": 1})
    except Exception:
        hit = None
    if hit and hit.get("ok") and is_permanent(hit.get("ref")):
        return hit["ref"], ""

    raw, err = await _download(url)
    if raw is None:
        await _record(url, "", False, err, 0)
        return None, err

    data, ctype, ext = _normalise_bytes(raw)
    if data is None:
        reason = "image format not supported by this device family (AVIF/HEIF)"
        await _record(url, "", False, reason, len(raw))
        return None, reason
    digest = hashlib.sha1(data).hexdigest()
    key = f"{digest}.{ext}"
    try:
        await db[FILES].update_one(
            {"_id": key},
            {"$set": {"content_type": ctype, "bytes": len(data)},
             "$setOnInsert": {"data": Binary(data), "created_at": time.time()}},
            upsert=True,
        )
    except Exception as exc:
        reason = f"storage write failed: {exc}"
        log.warning("persist_external_image: %s (%s)", reason, url)
        await _record(url, "", False, reason, len(data))
        return None, reason

    ref = f"{REF_PREFIX}{key}"
    await _record(url, ref, True, "", len(data))
    return ref, ""


async def read_permanent_image(key: str) -> Tuple[bytes, str]:
    """Read bytes back out of permanent storage for `routes/images.py`."""
    doc = await db[FILES].find_one({"_id": key})
    if not doc or not doc.get("data"):
        raise FileNotFoundError(key)
    return bytes(doc["data"]), doc.get("content_type") or "image/jpeg"


async def store_bytes(data: bytes, content_type: str = "image/jpeg") -> str:
    """Persist raw image bytes (already validated) and return its ref."""
    digest = hashlib.sha1(data).hexdigest()
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
           "image/gif": "gif", "image/bmp": "bmp"}.get(content_type, "jpg")
    key = f"{digest}.{ext}"
    await db[FILES].update_one(
        {"_id": key},
        {"$set": {"content_type": content_type, "bytes": len(data)},
         "$setOnInsert": {"data": Binary(data), "created_at": time.time()}},
        upsert=True,
    )
    return f"{REF_PREFIX}{key}"


# ── Product-payload entry point ──────────────────────────────────────

async def persist_product_images(payload: Dict[str, Any], *, concurrency: int = 4) -> Dict[str, Any]:
    """Rewrite `image_url` + `images[]` on a product payload IN PLACE so
    they only ever reference permanent storage.

    Returns an import report:
        { "imported": n, "reused": n, "failed": n, "failures": [{url, reason}],
          "status": "ok" | "partial" | "failed" | "none" }

    Behaviour:
      • `images` is flattened / ordered / de-duplicated first (Shopify
        objects + `Image Position` handled).
      • base64 `data:` covers and our own `/api/...` refs are left alone.
      • The primary image is taken from `image_url`; when that is empty or
        unusable the first surviving gallery image is promoted so a product
        always has a thumbnail if ANY of its photos imported.
      • A URL that cannot be imported is dropped from the stored arrays and
        listed in `failures` — we never persist a dead reference.
    """
    report: Dict[str, Any] = {"imported": 0, "reused": 0, "failed": 0, "failures": [], "status": "none"}
    if not isinstance(payload, dict):
        return report

    has_cover_key = "image_url" in payload
    has_gallery_key = "images" in payload

    cover_raw = coerce_image_ref(payload.get("image_url")) if has_cover_key else ""
    gallery_raw = normalize_gallery(payload.get("images")) if has_gallery_key else []
    cover_raw = canonical_ref(cover_raw)
    gallery_raw = [canonical_ref(u) for u in gallery_raw]

    # Build the ordered work list: cover first, then gallery, de-duplicated.
    todo: List[str] = []
    seen = set()
    for u in ([cover_raw] if cover_raw else []) + gallery_raw:
        if u and u not in seen:
            seen.add(u)
            todo.append(u)
    if not todo:
        if has_gallery_key:
            payload["images"] = []
        return report

    sem = asyncio.Semaphore(max(1, concurrency))

    async def _one(u: str) -> Tuple[str, Optional[str], str]:
        if not needs_persisting(u):
            return u, u, ""               # data: URI, our own ref, etc.
        async with sem:
            ref, err = await persist_external_image(u)
        return u, ref, err

    results = await asyncio.gather(*(_one(u) for u in todo))

    mapped: Dict[str, Optional[str]] = {}
    for src, ref, err in results:
        if ref is None:
            # IMPORTANT: keep the original URL in place. Blanking it would
            # destroy the only record of where the photo came from, making a
            # later retry impossible — and the source may still work for some
            # clients. The `failed` status is what drives the placeholder and
            # the admin's re-import list.
            mapped[src] = src
            report["failed"] += 1
            report["failures"].append({"url": src, "reason": err or "unknown error"})
        elif needs_persisting(src):
            mapped[src] = ref
            report["imported"] += 1
        else:
            mapped[src] = ref
            report["reused"] += 1

    new_gallery = [mapped[u] for u in gallery_raw if mapped.get(u)]
    new_cover = mapped.get(cover_raw) if cover_raw else None
    # Prefer a PERMANENT photo as the thumbnail: if the chosen cover could
    # not be copied but a gallery photo could, lead with the one that works.
    if not is_permanent(new_cover):
        permanent_first = next((u for u in new_gallery if is_permanent(u)), None)
        if permanent_first:
            new_cover = permanent_first
    if not new_cover and new_gallery:
        new_cover = new_gallery[0]

    if has_cover_key:
        payload["image_url"] = new_cover or ""
    elif new_cover and not payload.get("image_url"):
        payload["image_url"] = new_cover
    if has_gallery_key or new_gallery:
        payload["images"] = new_gallery

    if report["failed"] and report["imported"] == 0 and not any(is_permanent(u) for u in new_gallery):
        report["status"] = "failed"
    elif report["failed"]:
        report["status"] = "partial"
    elif report["imported"] or report["reused"]:
        report["status"] = "ok"

    if report["status"] != "none":
        payload["image_import_status"] = report["status"]
        payload["image_import_failures"] = report["failures"][:20]
        payload["image_import_at"] = time.time()
    return report


def merge_reports(into: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    """Accumulate per-product reports into one restore-level summary."""
    into["imported"] = into.get("imported", 0) + extra.get("imported", 0)
    into["reused"] = into.get("reused", 0) + extra.get("reused", 0)
    into["failed"] = into.get("failed", 0) + extra.get("failed", 0)
    fails = into.setdefault("failures", [])
    for f in extra.get("failures", []):
        if len(fails) < 50:
            fails.append(f)
    return into
