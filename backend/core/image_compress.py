"""
Image compression helper for vendor / admin uploads.

Dec 2026 — Central choke-point for every base64 image entering the DB.
Vendors historically pasted 200-500 KB base64 blobs directly into the
`image_url` / `images[]` fields; without pre-compression, the DB grew
proportionally and every list query dragged multi-MB payloads across
the wire.

This module applies a **single-pass server-side compression** at upload
time:
  * Downscale so the LARGEST dimension is ≤ 1280 px (retina-quality
    detail view — grids use `?w=360` thumbnails via the public image
    endpoint on top of this).
  * Convert to JPEG at quality 82 (progressive) — perceptually
    indistinguishable from the source for typical product photos.
  * Auto-rotate per EXIF, composite alpha on white.
  * Fall through to the original bytes on any decode failure so we
    never lose the vendor's upload.

Callers pass a base64 `data:` URI (or a raw base64 string) and get
back a base64 `data:image/jpeg` URI that is typically 5-10× smaller.
"""

from __future__ import annotations

import base64
import io
from typing import Optional


_MAX_DIM = 1280         # px
_JPEG_QUALITY = 82


def compress_data_url(src: Optional[str]) -> Optional[str]:
    """Compress a data:URI image; return the compressed data:URI.

    Behaviour:
      * `None` / empty → returned unchanged.
      * Non-data URIs (http[s] links) → returned unchanged.
      * Malformed base64 / non-image bytes → returned unchanged.
    """
    if not src or not isinstance(src, str):
        return src
    if not src.startswith("data:"):
        return src
    try:
        head, b64 = src.split(",", 1)
        raw = base64.b64decode(b64)
    except Exception:
        return src

    # Only touch actual images.  Non-image data URIs are extremely rare
    # in this codebase but might exist for legacy attachments.
    try:
        from PIL import Image, ImageOps
    except Exception:
        # Pillow unavailable — pass through untouched.
        return src

    try:
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)
        # Composite alpha on white so JPEG doesn't render black behind
        # transparent pixels.
        if img.mode not in ("RGB", "L"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "RGBA":
                bg.paste(img, mask=img.split()[3])
            else:
                conv = img.convert("RGBA")
                bg.paste(conv, mask=conv.split()[3])
            img = bg
        elif img.mode == "L":
            img = img.convert("RGB")
        # Downscale only — never upscale (never fabricate detail).
        w, h = img.size
        long_side = max(w, h)
        if long_side > _MAX_DIM:
            ratio = _MAX_DIM / long_side
            img = img.resize((max(1, int(w * ratio)), max(1, int(h * ratio))), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_JPEG_QUALITY, optimize=True, progressive=True)
        out = buf.getvalue()
    except Exception:
        # Any decode error → pass source through.
        return src

    # Only substitute if the compressed version is actually smaller
    # (otherwise return the original — some tiny icons don't gain).
    if len(out) >= len(raw):
        return src
    return "data:image/jpeg;base64," + base64.b64encode(out).decode()


def compress_product_payload(payload_dict: dict) -> dict:
    """In-place compression for a product-create/update payload.

    Handles the two conventional shape variants:
      * `image_url`  : str | None
      * `images`     : list[str] | None
    """
    if not isinstance(payload_dict, dict):
        return payload_dict
    if "image_url" in payload_dict:
        payload_dict["image_url"] = compress_data_url(payload_dict.get("image_url"))
    imgs = payload_dict.get("images")
    if isinstance(imgs, list):
        payload_dict["images"] = [compress_data_url(x) for x in imgs]
    return payload_dict
