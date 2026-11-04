"""Product image repair + health (Jun 2026).

Existing catalogues already contain thousands of products whose
`image_url` / `images[]` point at an external CDN that has since started
refusing us (DeoDap/Shopify hotlink rules, deleted Flickr originals,
GSMArena Referer checks).  Those are the blank cards in the shop.

This module repairs them WITHOUT deleting or re-importing a single
product: for every product that still references an external URL we try
to download a copy into permanent storage (see `core/image_store.py`) and
rewrite the reference.  Images we are not allowed or able to fetch are
recorded with a reason so the admin can re-import them from the source
file — never silently blanked.

Three ways to run it, all driven by the same `repair_product_images()`:
  1. Admin button          → POST /api/admin/products/repair-images
  2. Automatic background  → a worker started on boot that walks the whole
                             catalogue in small batches and then idles
  3. On first open         → `maybe_repair_one()` is fired (and forgotten)
                             by the product-detail endpoint

Endpoints (mounted at /api by server.py):
  GET  /admin/products/image-health        — counts by state
  POST /admin/products/repair-images       — repair a batch, returns report
  GET  /admin/products/image-repair-status — background worker progress
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, Body, Depends

from core.db import db
from core.image_store import (
    coerce_image_ref,
    merge_reports,
    needs_persisting,
    normalize_gallery,
    persist_product_images,
)
from core.security import require_admin

log = logging.getLogger("product_images_repair")
router = APIRouter(tags=["product-images"])

#: Mongo filter matching every product that still references an external
#: image. `^https?://` is deliberately broad — our own permanent refs start
#: with `/api/img/` and inline covers with `data:`, so neither matches.
EXTERNAL_RE = {"$regex": r"^https?://", "$options": "i"}
EXTERNAL_FILTER: Dict[str, Any] = {
    "$or": [{"image_url": EXTERNAL_RE}, {"images": {"$elemMatch": EXTERNAL_RE}}],
}

#: Products whose gallery is a list of OBJECTS instead of strings (the
#: Shopify-converted shape that crashed the Android product screen).
OBJECT_GALLERY_FILTER: Dict[str, Any] = {"images": {"$elemMatch": {"$type": "object"}}}

#: Products an earlier repair attempt blanked: no reference left, but the
#: original URL is still recorded under `image_import_failures`. These are
#: recoverable and are picked up by "Retry failed photos".
RECOVERABLE_FILTER: Dict[str, Any] = {
    "$and": [
        {"image_import_failures.0": {"$exists": True}},
        {"$or": [{"image_url": {"$in": [None, ""]}}, {"image_url": {"$exists": False}}]},
    ],
}

NEEDS_REPAIR_FILTER: Dict[str, Any] = {
    "$or": [EXTERNAL_FILTER, OBJECT_GALLERY_FILTER, RECOVERABLE_FILTER],
}

#: What is left to do. A product we have ALREADY attempted and could only
#: partly (or not at all) fix still matches `NEEDS_REPAIR_FILTER`, because the
#: dead URL is deliberately kept for a retry. Without excluding those two
#: statuses the background worker re-downloaded the same dead photos every
#: few seconds forever and starved every other product.
PENDING_FILTER: Dict[str, Any] = {
    "$and": [
        NEEDS_REPAIR_FILTER,
        {"image_import_status": {"$nin": ["failed", "partial"]}},
    ],
}

#: Products we already tried and could not fully fetch — skipped by the
#: background worker so it doesn't hammer a dead CDN forever, but still
#: repairable from the admin button with `retry_failed=true`.
_FAILED_FILTER: Dict[str, Any] = {"image_import_status": {"$in": ["failed", "partial"]}}

# ── Shared worker state (read by the status endpoint) ────────────────
_state: Dict[str, Any] = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "scanned": 0,
    "repaired": 0,
    "partial": 0,
    "failed": 0,
    "images_imported": 0,
    "images_failed": 0,
    "last_error": None,
    "trigger": None,
}
_lock = asyncio.Lock()
#: Guards against the lazy per-product repair stampeding on a popular SKU.
_inflight: Set[str] = set()


def _snapshot() -> Dict[str, Any]:
    return dict(_state)


async def repair_one(product: Dict[str, Any]) -> Dict[str, Any]:
    """Repair ONE product document. Returns its import report.

    Only the image fields are ever written — price, stock, description,
    variants, GST, categories and every other field are untouched.
    """
    pid = product.get("id")
    if not pid:
        return {"status": "none", "imported": 0, "reused": 0, "failed": 0, "failures": []}

    payload: Dict[str, Any] = {
        "image_url": coerce_image_ref(product.get("image_url")),
        "images": normalize_gallery(product.get("images")),
    }
    # Recovery path: an earlier repair attempt (before Jun 2026) blanked the
    # reference when a download failed, so the only surviving record of the
    # photo is the URL inside `image_import_failures`. Feed those back in so
    # a retry can actually succeed instead of staring at an empty field.
    if not payload["image_url"] and not payload["images"]:
        recovered = [
            f.get("url") for f in (product.get("image_import_failures") or [])
            if isinstance(f, dict) and isinstance(f.get("url"), str) and f.get("url")
        ]
        if recovered:
            payload["image_url"] = recovered[0]
            payload["images"] = recovered[1:]

    report = await persist_product_images(payload)

    update: Dict[str, Any] = {
        "image_url": payload.get("image_url") or "",
        "images": payload.get("images") or [],
        "image_import_status": payload.get("image_import_status", report.get("status")),
        "image_import_failures": payload.get("image_import_failures", report.get("failures", []))[:20],
        "image_import_at": time.time(),
    }
    await db.products.update_one({"id": pid}, {"$set": update})
    return report


async def maybe_repair_one(product_id: str) -> None:
    """Fire-and-forget repair triggered the first time a shopper opens a
    product whose images are still external.  Deliberately silent."""
    if not product_id or product_id in _inflight:
        return
    _inflight.add(product_id)
    try:
        doc = await db.products.find_one(
            {"id": product_id, **NEEDS_REPAIR_FILTER},
            {"_id": 0, "id": 1, "image_url": 1, "images": 1, "image_import_failures": 1},
        )
        if doc:
            await repair_one(doc)
    except Exception as exc:
        log.info("lazy image repair for %s failed: %s", product_id, exc)
    finally:
        _inflight.discard(product_id)


async def repair_batch(
    limit: int = 25,
    *,
    retry_failed: bool = False,
    product_ids: Optional[List[str]] = None,
    trigger: str = "manual",
) -> Dict[str, Any]:
    """Repair up to `limit` products that still reference external images."""
    query: Dict[str, Any] = dict(NEEDS_REPAIR_FILTER)
    if product_ids:
        query = {"id": {"$in": product_ids}}
    elif not retry_failed:
        query = PENDING_FILTER

    docs = await db.products.find(
        query, {"_id": 0, "id": 1, "name": 1, "image_url": 1, "images": 1,
                "image_import_failures": 1},
    ).limit(max(1, min(200, int(limit)))).to_list(200)

    summary: Dict[str, Any] = {
        "scanned": 0, "repaired": 0, "partial": 0, "failed": 0,
        "imported": 0, "reused": 0, "images_failed": 0, "failures": [],
    }
    for doc in docs:
        # Yield between products — repair_one runs PIL image compression,
        # which is CPU work on the event loop. Without this a single long
        # batch starves the /health probe and the deployer reports the backend
        # as down.
        await asyncio.sleep(0)
        try:
            rep = await repair_one(doc)
        except Exception as exc:
            log.warning("repair_one(%s) crashed: %s", doc.get("id"), exc)
            summary["failed"] += 1
            summary["scanned"] += 1
            continue
        summary["scanned"] += 1
        # Name the product on each failure so the admin can find it.
        for f in rep.get("failures", []):
            f.setdefault("product", doc.get("name") or doc.get("id"))
        # `failed` counts PRODUCTS, `images_failed` counts PHOTOS — mixing
        # the two made the report read "18 scanned, 26 failed".
        images_before = summary["failed"]
        merge_reports(summary, rep)
        summary["images_failed"] += summary["failed"] - images_before
        summary["failed"] = images_before
        status = rep.get("status")
        if status == "ok":
            summary["repaired"] += 1
        elif status == "partial":
            summary["partial"] += 1
        elif status == "failed":
            summary["failed"] += 1

    _state["scanned"] += summary["scanned"]
    _state["repaired"] += summary["repaired"]
    _state["partial"] += summary["partial"]
    _state["failed"] += summary["failed"]
    _state["images_imported"] += summary["imported"]
    _state["images_failed"] += summary["images_failed"]
    _state["trigger"] = trigger
    if summary["scanned"]:
        try:
            from routes.products_public import bust_products_public_caches
            bust_products_public_caches()
        except Exception:
            pass
    summary["remaining"] = await db.products.count_documents(
        PENDING_FILTER
    )
    return summary


# ── Background worker ────────────────────────────────────────────────

async def _worker(batch: int, pause: float) -> None:
    """Walk the whole catalogue in small batches, then stop.

    Batches are small and paced so a 1,500-product import doesn't saturate
    the pod or the upstream CDN.
    """
    _state.update({"running": True, "started_at": time.time(), "finished_at": None,
                   "last_error": None, "trigger": "auto"})
    try:
        while True:
            summary = await repair_batch(batch, trigger="auto")
            if summary["scanned"] == 0:
                break
            await asyncio.sleep(pause)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _state["last_error"] = str(exc)
        log.warning("image repair worker stopped: %s", exc)
    finally:
        _state["running"] = False
        _state["finished_at"] = time.time()


async def start_background_repair(batch: int = 10, pause: float = 3.0, delay: float = 120.0) -> None:
    """Kick the worker off shortly after boot (once per process).

    The delay is generous on purpose: the deployment health probe marks the
    pod as READY within seconds, and a repair sweep starting while the probe
    is still exercising /health can starve the single uvicorn worker and fail
    the whole deploy. Two minutes of warm-up keeps the boot cheap; repair is
    not time-critical.
    """
    await asyncio.sleep(delay)          # let the app finish warming up + the probe pass
    if (os.environ.get("DISABLE_AUTO_IMAGE_REPAIR") or "").strip().lower() in ("1", "true", "yes"):
        log.info("auto image repair disabled by DISABLE_AUTO_IMAGE_REPAIR")
        return
    async with _lock:
        if _state["running"]:
            return
        pending = await db.products.count_documents(
            PENDING_FILTER
        )
        if pending == 0:
            return
        log.info("auto image repair: %s product(s) need permanent images", pending)
        asyncio.create_task(_worker(batch, pause))


# ── Endpoints ────────────────────────────────────────────────────────

@router.get("/admin/products/image-health")
async def image_health(_: Dict[str, Any] = Depends(require_admin)):
    """How many products have working vs. broken image references."""
    total = await db.products.count_documents({})
    external = await db.products.count_documents(EXTERNAL_FILTER)
    object_shaped = await db.products.count_documents(OBJECT_GALLERY_FILTER)
    permanent = await db.products.count_documents({"image_url": {"$regex": r"^/api/img/"}})
    inline = await db.products.count_documents({"image_url": {"$regex": r"^data:"}})
    failed = await db.products.count_documents(_FAILED_FILTER)
    missing = await db.products.count_documents(
        {"$and": [
            {"$or": [{"image_url": {"$in": [None, ""]}}, {"image_url": {"$exists": False}}]},
            {"$or": [{"images": {"$in": [None, []]}}, {"images": {"$exists": False}}]},
        ]}
    )
    pending = await db.products.count_documents(
        PENDING_FILTER
    )
    return {
        "total_products": total,
        "permanent": permanent,
        "inline_base64": inline,
        "external_pending": external,
        "object_shaped_gallery": object_shaped,
        "needs_repair": pending,
        "failed": failed,
        "no_image_at_all": missing,
        "worker": _snapshot(),
    }


@router.post("/admin/products/repair-images")
async def repair_images(
    body: Dict[str, Any] = Body(default={}),
    _: Dict[str, Any] = Depends(require_admin),
):
    """Repair a batch of products.

    Body (all optional):
      limit        : how many products this call should process (1-200, default 25)
      retry_failed : also retry products previously marked `failed` or
                     `partial` (those are skipped by the automatic sweep so
                     a dead CDN isn't hammered forever)
      product_ids  : repair exactly these products
      run_all      : start/continue the background worker instead of a
                     single batch, so the whole catalogue is swept
    """
    if bool(body.get("run_all")):
        async with _lock:
            if not _state["running"]:
                asyncio.create_task(_worker(int(body.get("batch") or 10), float(body.get("pause") or 2.0)))
        return {"ok": True, "mode": "background", "worker": _snapshot()}

    summary = await repair_batch(
        int(body.get("limit") or 25),
        retry_failed=bool(body.get("retry_failed")),
        product_ids=body.get("product_ids") or None,
        trigger="manual",
    )
    return {"ok": True, "mode": "batch", **summary}


@router.get("/admin/products/image-repair-status")
async def repair_status(_: Dict[str, Any] = Depends(require_admin)):
    pending = await db.products.count_documents(
        PENDING_FILTER
    )
    return {"worker": _snapshot(), "remaining": pending}
