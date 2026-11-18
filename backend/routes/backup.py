"""Backup & Restore — Phase 4.

4A: VENDOR CATALOGUE portability (vendor-scoped, see /vendor/me/catalogue/*).
4B: FULL-APP file backup (admin-scoped, see /admin/backup/*) — one .json with
    users, products, orders, invoices, chat, services, wallet + transactions,
    layouts and settings, restorable into a fork or back into live.

Why: a vendor who opens a second shop (or migrates to a new login) had no way
to carry their catalogue across, and re-typing 100 SKUs with photos is a
non-starter. Admins also asked for a way to clone a catalogue between
environments (fork → live).

Design notes
------------
* CHUNKED. Product documents carry base64 cover images and galleries, so a
  200-SKU catalogue is tens of megabytes. Sending that in one response is
  exactly what makes Cloudflare give up ("could not parse response"), so both
  export and import are paged: the client walks `offset`/`limit` and stitches
  the file locally.
* The export is a plain, human-readable JSON envelope (see EXPORT_FORMAT) so
  it can be inspected, diffed and even hand-edited before a restore.
* Restores are ALWAYS re-stamped: a new product id, the importing vendor's
  id/email, and that vendor's own store location + delivery zone. A backup can
  therefore never smuggle another shop's delivery area into a new account.
* Restored products land UNPUBLISHED (owner's choice) so the vendor reviews
  price / stock before anything hits the public shop. Publishing stays
  admin-only, exactly like a manually created product.
"""
import asyncio
import base64
import json
import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Any, AsyncIterator, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pymongo import ReplaceOne

from core.danger import get_danger_pin_hash, verify_danger_pin
from core.db import db
from core.security import get_current_user, require_admin_role
from core.utils import now_utc

log = logging.getLogger("backup")

router = APIRouter()

EXPORT_FORMAT = "slangcart.vendor-catalogue"
EXPORT_VERSION = 1

# Fields that describe WHO/WHERE a product belongs to. They are dropped on
# export and re-stamped from the importing vendor on restore.
OWNERSHIP_FIELDS = {
    "_id", "id", "vendor_id", "vendor_email",
    "store_pincode", "store_location", "store_city", "store_state", "store_district",
    "delivery_radius_km", "delivery_radius_mode", "delivery_available", "delivery_pincodes",
    "created_at", "updated_at", "is_published",
    # Bookkeeping from a previous restore — meaningless in a new file.
    "restore_session", "restored_at", "restored_from_backup",
    # Engagement / analytics counters belong to the original listing.
    "interested_count", "views", "orders_count", "rating", "rating_count",
}


async def require_vendor_user(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Local copy of server.require_vendor — importing it would be circular."""
    if not (bool(user.get("is_vendor")) and user.get("vendor_status") == "approved"):
        raise HTTPException(status_code=403, detail="Vendor access only — your account is not an approved vendor")
    return user


def _strip_for_export(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in doc.items() if k not in OWNERSHIP_FIELDS}


# ───────────────────────────── EXPORT ─────────────────────────────

@router.get("/vendor/me/catalogue/export")
async def vendor_export_catalogue(
    offset: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=25),
    vendor: Dict[str, Any] = Depends(require_vendor_user),
):
    """One page of the vendor's catalogue, images included.

    `limit` is capped at 25 because each product can carry several base64
    photos — the client keeps calling with a bumped `offset` until
    `has_more` is false and writes ONE file at the end.
    """
    total = await db.products.count_documents({"vendor_id": vendor["id"]})
    # Jun 2026 — `_id` is the unique tie-breaker. Sorting on `created_at`
    # alone let pages overlap whenever products share a timestamp (a bulk
    # import writes hundreds in the same second), so an exported file had
    # duplicate rows AND silently missed products.
    docs = await db.products.find({"vendor_id": vendor["id"]}, {"_id": 0}) \
        .sort([("created_at", 1), ("id", 1)]).skip(offset).limit(limit).to_list(limit)
    return {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "exported_at": now_utc().isoformat(),
        "vendor": {
            "id": vendor["id"],
            "email": vendor.get("email"),
            "shop_name": vendor.get("shop_name") or vendor.get("name"),
        },
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": (offset + len(docs)) < total,
        "products": [_strip_for_export(d) for d in docs],
    }


# ───────────────────────────── IMPORT ─────────────────────────────

@router.post("/vendor/me/catalogue/import")
async def vendor_import_catalogue(
    payload: Dict[str, Any] = Body(...),
    vendor: Dict[str, Any] = Depends(require_vendor_user),
):
    """Restore a page of products into the CALLING vendor's account.

    Body:
      products   : list of product objects from an export file (required)
      mode       : "merge" (default) | "replace"
      first_chunk: true on the first call — only then does "replace" wipe the
                   vendor's existing products, so a multi-chunk restore
                   doesn't delete what the previous chunk just inserted.
      restore_session: an id the client keeps for the whole file. Every row
                   this restore creates or updates is stamped with it, and
                   stamped rows are never matched again — otherwise a file
                   listing the same product name in two different chunks had
                   its second chunk overwrite the row the first chunk had just
                   created, silently losing a product.
    """
    products: List[Dict[str, Any]] = payload.get("products") or []
    mode = (payload.get("mode") or "merge").lower()
    first_chunk = bool(payload.get("first_chunk"))
    session_id = str(payload.get("restore_session") or "").strip()[:64]
    if mode not in ("merge", "replace"):
        raise HTTPException(status_code=400, detail="mode must be 'merge' or 'replace'")
    if not isinstance(products, list):
        raise HTTPException(status_code=400, detail="products must be a list")

    wiped = 0
    if mode == "replace" and first_chunk:
        # Jun 2026 — delete by QUERY, not by a capped id list. The old code
        # read the first 5,000 ids and deleted those, so a larger catalogue
        # was only partly replaced.
        mine = [m["id"] async for m in db.products.find(
            {"vendor_id": vendor["id"]}, {"_id": 0, "id": 1},
        ) if m.get("id")]
        res = await db.products.delete_many({"vendor_id": vendor["id"]})
        wiped = res.deleted_count
        for i in range(0, len(mine), 500):
            await db.cart_items.delete_many({"product_id": {"$in": mine[i:i + 500]}})

    from core.image_compress import compress_product_payload
    from core.image_store import merge_reports, persist_product_images
    from core.variants import apply_variants_to_payload

    created = 0
    updated = 0
    skipped: List[str] = []
    #: name -> still-unclaimed existing product ids in this shop (see below).
    name_matches: Dict[str, List[str]] = {}
    stamped_at = now_utc().isoformat()
    docs: List[Dict[str, Any]] = []
    image_report: Dict[str, Any] = {"imported": 0, "reused": 0, "failed": 0, "failures": [], "deferred": 0}
    import time as _time
    from core.image_store import normalize_gallery
    deadline = _time.monotonic() + RESTORE_IMAGE_BUDGET_SECONDS
    for raw in products:
        if not isinstance(raw, dict):
            skipped.append("not an object")
            continue
        name = str(raw.get("name") or "").strip()
        price = float(raw.get("price") or 0)
        if not name:
            skipped.append("missing name")
            continue
        if price <= 0:
            skipped.append(f"{name}: price must be > 0")
            continue
        body = {k: v for k, v in raw.items() if k not in OWNERSHIP_FIELDS}
        body = compress_product_payload(body)
        # Jun 2026 — copy every external image into permanent storage so a
        # restored catalogue doesn't go blank when the source CDN rotates.
        # Shape-normalise always; download within this request's budget and
        # leave the rest to the background repair worker.
        if "images" in body:
            body["images"] = normalize_gallery(body.get("images"))
        if _time.monotonic() > deadline:
            body["image_import_status"] = "pending"
            image_report["deferred"] += 1
        else:
            try:
                rep = await persist_product_images(body)
                for f in rep.get("failures", []):
                    f.setdefault("product", name)
                merge_reports(image_report, rep)
            except Exception:
                body["image_import_status"] = "pending"
                image_report["deferred"] += 1
        body = apply_variants_to_payload(body, price)
        ownership = {
            "vendor_id": vendor["id"],
            "vendor_email": vendor.get("email"),
            "store_pincode": vendor.get("pincode") or None,
            "store_location": vendor.get("location") or None,
            "store_city": vendor.get("city") or None,
            "store_state": vendor.get("state") or None,
            "store_district": vendor.get("district") or None,
            "delivery_radius_km": vendor.get("delivery_radius_km"),
            "delivery_radius_mode": vendor.get("delivery_radius_mode") or "pincode",
            "delivery_available": vendor.get("delivery_available", True),
            "delivery_pincodes": vendor.get("delivery_pincodes") or [],
            "restored_from_backup": True,
        }
        # Jun 2026 — Idempotent merge. The export strips product ids (a
        # restore can land in a different shop), so the shop's own product
        # NAME is the natural key: restoring the same file twice must update
        # the product, not create a second copy of it. "replace" wiped the
        # catalogue on the first chunk, so there is nothing to match.
        # A shop may legitimately hold two products with the SAME name, and a
        # file may list that name twice. Each existing row is therefore
        # claimed at most once: the 1st "Red Saree" in the file updates the 1st
        # in the shop, the 2nd updates the 2nd, and a 3rd with no partner left
        # is created. Rows already touched by THIS restore session are skipped,
        # so a name split across two upload chunks no longer has the second
        # chunk overwrite what the first chunk just created.
        if mode == "merge":
            if name not in name_matches:
                q: Dict[str, Any] = {"vendor_id": vendor["id"], "name": name}
                if session_id:
                    q["restore_session"] = {"$ne": session_id}
                # An APK installed before `restore_session` existed sends no
                # id, so its chunks share no key and a name split across two
                # chunks can still merge onto one row. There is no reliable
                # server-side substitute (a time window would make a repeat
                # restore duplicate the whole catalogue, which is worse), so
                # the legacy path keeps its original behaviour and the real
                # fix is for the owner to install the new build.
                rows = await db.products.find(
                    q, {"_id": 0, "id": 1},
                ).sort("id", 1).to_list(500)
                name_matches[name] = [r["id"] for r in rows]
            pool = name_matches[name]
            if pool:
                target = pool.pop(0)
                # Never take a live product offline: a restore over a running
                # shop refreshes the data and leaves publishing as it was.
                stamp = {"restored_at": stamped_at}
                if session_id:
                    stamp["restore_session"] = session_id
                await db.products.update_one(
                    {"id": target}, {"$set": {**body, **ownership, **stamp}},
                )
                updated += 1
                continue
        docs.append({
            "id": str(uuid.uuid4()),
            **body,
            **ownership,
            "restored_at": stamped_at,
            **({"restore_session": session_id} if session_id else {}),
            "created_at": now_utc().isoformat(),
            # Owner's choice: restored items are drafts until reviewed, and
            # publishing remains an admin action.
            "is_published": False,
        })

    if docs or updated:
        if docs:
            await db.products.insert_many(docs)
            created = len(docs)
        try:
            from routes.products_public import bust_products_public_caches
            bust_products_public_caches()
        except Exception:
            pass
        if image_report.get("deferred"):
            try:
                import asyncio as _aio
                from routes.product_images_repair import start_background_repair
                _aio.create_task(start_background_repair(delay=5.0))
            except Exception:
                pass

    return {
        "ok": True, "created": created, "updated": updated,
        "wiped": wiped, "skipped": skipped, "mode": mode,
        "images_imported": image_report["imported"],
        "images_reused": image_report["reused"],
        "images_failed": image_report["failed"],
        "images_deferred": image_report.get("deferred", 0),
        "image_failures": image_report["failures"][:25],
    }


# ══════════════════════ 4B — FULL APP BACKUP (admin) ══════════════════════
#
# One file → every collection that makes the app what it is: users, products,
# orders, invoices/POS sales, chat, services, wallet + transactions, layouts
# and settings. Restorable into a fork and back into live.
#
# Same chunking rule as the vendor catalogue: the client asks for a manifest,
# then pages each collection, then writes ONE file. A restore replays the file
# collection-by-collection so no single request is ever huge.

APP_EXPORT_FORMAT = "slangcart.app-backup"

# Never exported: derived, self-referential or machine-local data. Putting
# db_snapshots in a file backup would nest every previous snapshot inside it.
NEVER_EXPORT = {
    "db_snapshots",
    "db_snapshot_chunks",
    "security_events",
    "shop_layout_analytics",
    "gsmarena_brand_cache",
    "products_master_cache",
    "ledger_alerts",
}

# Reference/lookup data that is re-seeded on boot. Skipped by default because
# it dwarfs the real business data (19k+ pincode rows), opt in with
# ?include_reference=true.
REFERENCE_COLLECTIONS = {"pincodes"}

#: Jun 2026 — Per-chunk wall-clock budget for downloading product photos
#: during a restore. Keeps every request comfortably inside the 60 s edge
#: timeout; the remainder is finished by the background repair worker.
RESTORE_IMAGE_BUDGET_SECONDS = 22.0


def _json_safe(value: Any) -> Any:
    """Make a Mongo document JSON-serialisable without losing information.

    Jun 2026 — `_id` used to be stripped here.  That quietly destroyed the
    permanent image store: in `product_image_files` the `_id` IS the key
    behind every `/api/img/<key>` link, so a restored backup came back with
    every photo blank.  `_id` is now kept, and raw image bytes are
    base64-encoded instead of being str()'d into `"b'\\xff\\xd8...'"`.
    """
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, ObjectId):
        # Flagged so a restore can put a real ObjectId back.
        return {"$oid": str(value)}
    if isinstance(value, (bytes, bytearray)):
        return {"$b64": base64.b64encode(bytes(value)).decode("ascii")}
    return value


def _json_revive(value: Any) -> Any:
    """Inverse of :func:`_json_safe` — run on every document being restored."""
    if isinstance(value, dict):
        if len(value) == 1:
            if "$b64" in value and isinstance(value["$b64"], str):
                try:
                    return base64.b64decode(value["$b64"])
                except Exception:
                    return b""
            if "$oid" in value and isinstance(value["$oid"], str):
                try:
                    return ObjectId(value["$oid"])
                except Exception:
                    return value["$oid"]
        return {k: _json_revive(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_revive(v) for v in value]
    return value


async def _exportable_collections(include_reference: bool) -> List[str]:
    names = await db.list_collection_names()
    out = [
        n for n in sorted(names)
        if n not in NEVER_EXPORT and (include_reference or n not in REFERENCE_COLLECTIONS)
    ]
    return out


#: How long a single count is allowed to take before we fall back (ms).
_COUNT_TIME_LIMIT_MS = 4000


async def safe_count(name: str) -> int:
    """Count a collection without ever failing the whole request.

    Nov 2026 — `count_documents({})` runs a real aggregation, and on Atlas it
    exceeded the operation time limit on `product_image_files` (which holds
    multi-megabyte image binaries): "Executor error during getMore :: operation
    exceeded time limit", MaxTimeMSExpired. That exception propagated out of
    the manifest endpoint as a 500, which is why BOTH the File Backup &
    Snapshots → Restore screen and the whole Reset Center showed
    "Request failed with status code 500" — they each load the manifest first.

    An exact count is nice but never worth a dead screen, so a slow collection
    falls back to the instant metadata estimate, and a broken one reports 0.
    """
    try:
        return await db[name].count_documents({}, maxTimeMS=_COUNT_TIME_LIMIT_MS)
    except Exception as exc:
        try:
            est = await db[name].estimated_document_count()
            log.warning("count fell back to an estimate for %s: %s", name, exc)
            return int(est)
        except Exception as exc2:
            log.warning("could not count %s at all: %s", name, exc2)
            return 0


@router.get("/admin/backup/manifest")
async def admin_backup_manifest(
    include_reference: bool = Query(False),
    _: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    """What's in the database right now — the client uses this to plan the
    download and to show the admin a preview before anything happens."""
    names = await _exportable_collections(include_reference)
    collections = []
    for n in names:
        collections.append({"name": n, "count": await safe_count(n)})
    return {
        "format": APP_EXPORT_FORMAT,
        "version": 1,
        "generated_at": now_utc().isoformat(),
        "include_reference": include_reference,
        "collections": collections,
        "total_documents": sum(c["count"] for c in collections),
        "skipped": sorted(NEVER_EXPORT | (set() if include_reference else REFERENCE_COLLECTIONS)),
    }


@router.get("/admin/backup/dump")
async def admin_backup_dump(
    collection: str = Query(...),
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    _: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    """One page of one collection. `limit` is deliberately client-tunable so
    the app can drop to 25 for image-heavy collections like `products`."""
    if collection in NEVER_EXPORT:
        raise HTTPException(status_code=400, detail=f"{collection} is not exportable")
    names = await db.list_collection_names()
    if collection not in names:
        raise HTTPException(status_code=404, detail="No such collection")
    total = await safe_count(collection)
    # A skip/limit walk needs a STABLE order or pages overlap and rows are
    # lost. `_id` is unique and always indexed.
    docs = await db[collection].find({}).sort("_id", 1).skip(offset).limit(limit).to_list(limit)
    return {
        "collection": collection,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": (offset + len(docs)) < total,
        "docs": [_json_safe(d) for d in docs],
    }


# ══════════════════ 4C — SCOPED (per-account) BACKUP ═════════════════════
#
# Owner ask: "before resetting one user, create one backup of ALL data for
# that particular user, and the user can restore it back."
#
# There is no single field that marks ownership across 50+ collections, so
# instead of hardcoding a map we LINK UP on every id/email field a document
# could plausibly carry. Mongo simply ignores the branches a collection
# doesn't have, so this stays correct as new collections appear.
SCOPE_ID_FIELDS = [
    "user_id", "vendor_id", "buyer_id", "customer_id", "seller_id", "owner_id",
    "provider_id", "referrer_id", "from_user_id", "to_user_id", "actor_id",
    "created_by", "assigned_to", "target_user_id", "sender_id", "recipient_id",
    # Oct-2026 — rider-owned rows (dp_vendor_map, dp_remittances) were left
    # behind by a per-account clear, so a reset rider stayed mapped to shops
    # and his remittance history survived.
    "dp_id", "delivery_partner_id", "linked_user_id", "joiner_id",
    "original_user_id", "deposited_by",
]
SCOPE_EMAIL_FIELDS = ["user_email", "vendor_email", "email", "customer_email", "actor_email"]


def scope_query(user_id: str, email: Optional[str], collection: str) -> Dict[str, Any]:
    ors: List[Dict[str, Any]] = [{f: user_id} for f in SCOPE_ID_FIELDS]
    ors.append({"participants": user_id})          # chat threads
    ors.append({"user_ids": user_id})
    if email:
        ors.extend({f: email} for f in SCOPE_EMAIL_FIELDS)
    if collection == "users":
        ors.append({"id": user_id})
    return {"$or": ors}


async def _scope_target(user_id: str) -> Dict[str, Any]:
    u = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    return u


async def safe_count_q(name: str, query: Dict[str, Any]) -> int:
    """`safe_count` for a filtered count — same MaxTimeMSExpired protection.

    A filtered count has no metadata shortcut, so a slow collection reports 0
    rather than killing the account manifest with a 500.
    """
    try:
        return await db[name].count_documents(query, maxTimeMS=_COUNT_TIME_LIMIT_MS)
    except Exception as exc:
        log.warning("scoped count failed for %s: %s", name, exc)
        return 0


@router.get("/admin/backup/account/{user_id}/manifest")
async def account_backup_manifest(
    user_id: str,
    _: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    """Everything the app holds about ONE account (customer or vendor)."""
    u = await _scope_target(user_id)
    email = (u.get("email") or "").lower() or None
    collections = []
    for name in await _exportable_collections(False):
        n = await safe_count_q(name, scope_query(user_id, email, name))
        if n:
            collections.append({"name": name, "count": n})
    return {
        "format": "slangcart.account-backup",
        "version": 1,
        "generated_at": now_utc().isoformat(),
        "account": {
            "id": u["id"], "email": u.get("email"), "name": u.get("name"),
            "is_vendor": bool(u.get("is_vendor")), "role": u.get("role"),
        },
        "collections": collections,
        "total_documents": sum(c["count"] for c in collections),
    }


@router.get("/admin/backup/account/{user_id}/dump")
async def account_backup_dump(
    user_id: str,
    collection: str = Query(...),
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    _: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    u = await _scope_target(user_id)
    if collection in NEVER_EXPORT:
        raise HTTPException(status_code=400, detail=f"{collection} is not exportable")
    email = (u.get("email") or "").lower() or None
    q = scope_query(user_id, email, collection)
    total = await safe_count_q(collection, q)
    docs = await db[collection].find(q).sort("_id", 1).skip(offset).limit(limit).to_list(limit)
    return {
        "collection": collection, "total": total, "offset": offset, "limit": limit,
        "has_more": (offset + len(docs)) < total,
        "docs": [_json_safe(d) for d in docs],
    }


# ══════════════════ 4D — ONE-SHOT STREAMED BACKUP FILE ═══════════════════
#
# Why this exists: the app used to fetch every page of every collection and
# stitch the file together in JS, then hand a ~120 MB string to
# FileSystem.writeAsStringAsync — which crashed Android with
# "java.lang.OutOfMemoryError: Failed to allocate a 126097912 byte
# allocation".  The server now streams the finished .json straight to disk,
# so neither side ever holds the whole backup in memory.
def _doc_json(doc: Dict[str, Any]) -> str:
    return json.dumps(_json_safe(doc), default=str, ensure_ascii=False)


#: How many docs a single cursor getMore fetches. Atlas shared clusters kill
#: a getMore that takes too long ("Executor error during getMore :: operation
#: exceeded time limit", MaxTimeMSExpired) — the production failure that made
#: full backups hang at "Packing on the server…" forever. A dead cursor used
#: to kill the whole streamed response; now each collection is fault-tolerant
#: and image-heavy collections fetch just a few big docs per round-trip.
_STREAM_BATCH = 25
_STREAM_BATCH_BIGDOCS = 3   # product_image_files etc. — multi-MB documents

#: Collections whose documents can be several MB apiece (raw bytes / base64).
_BIGDOC_COLLECTIONS = {"product_image_files", "image_assets", "backup_file_chunks"}


async def _backup_json_bytes(
    names: List[str],
    query_for,
    envelope: Dict[str, Any],
) -> AsyncIterator[bytes]:
    """Yield one complete backup JSON document, a few documents at a time.

    Nov 2026 hardening:
      * small cursor batches so Atlas can't kill a getMore on big collections;
      * a collection whose cursor dies mid-stream no longer kills the whole
        file — it contributes an empty array and is listed under `warnings`
        at the end of the document;
      * the client therefore ALWAYS receives a complete, valid JSON file.
    """
    warnings: List[str] = []
    head = {k: v for k, v in envelope.items()}
    opening = json.dumps(head, ensure_ascii=False)[:-1]  # drop the closing brace
    yield (opening + (", " if head else "") + '"collections": {').encode()
    for i, name in enumerate(names):
        yield (("," if i else "") + json.dumps(name) + ":[").encode()
        first = True
        buf: List[str] = []
        batch = _STREAM_BATCH_BIGDOCS if name in _BIGDOC_COLLECTIONS else _STREAM_BATCH
        try:
            cursor = db[name].find(query_for(name)).sort("_id", 1).batch_size(batch)
            async for doc in cursor:
                buf.append(("" if first else ",") + _doc_json(doc))
                first = False
                if len(buf) >= 50:
                    yield "".join(buf).encode()
                    buf = []
            if buf:
                yield "".join(buf).encode()
        except Exception as e:
            # A mid-stream cursor failure (Atlas maxTimeMS, transient network)
            # used to abort the ENTIRE download with a half-written file.
            log.error("backup stream: %s failed after some rows: %s", name, e)
            warnings.append(f"{name}: export stopped early — {e}")
        yield b"]"
    yield b"}"
    if warnings:
        yield b', "warnings": ' + json.dumps(warnings, ensure_ascii=False).encode()
    yield b"}"


def _attachment(name: str) -> Dict[str, str]:
    return {
        "Content-Disposition": f'attachment; filename="{name}"',
        "Cache-Control": "no-store",
        "X-Accel-Buffering": "no",
    }


@router.get("/admin/backup/file")
async def admin_backup_file(
    include_reference: bool = Query(False),
    _: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    """The whole app as ONE streamed .json download."""
    names = await _exportable_collections(include_reference)
    stamp = now_utc().strftime("%Y%m%d-%H%M")
    envelope = {
        "format": APP_EXPORT_FORMAT,
        "version": 1,
        "scope": "app",
        "exported_at": now_utc().isoformat(),
    }
    return StreamingResponse(
        _backup_json_bytes(names, lambda _n: {}, envelope),
        media_type="application/json",
        headers=_attachment(f"slangcart-full-backup-{stamp}.json"),
    )


@router.get("/admin/backup/account/{user_id}/file")
async def account_backup_file(
    user_id: str,
    _: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    """Everything about ONE account (customer or shop) as one streamed .json."""
    u = await _scope_target(user_id)
    email = (u.get("email") or "").lower() or None
    names = await _exportable_collections(False)
    stamp = now_utc().strftime("%Y%m%d-%H%M")
    label = (u.get("email") or user_id).replace("@", "-at-")
    label = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in label)
    envelope = {
        "format": APP_EXPORT_FORMAT,
        "version": 1,
        "scope": "account",
        "account": {"id": u["id"], "email": u.get("email"), "name": u.get("name")},
        "exported_at": now_utc().isoformat(),
    }
    return StreamingResponse(
        _backup_json_bytes(names, lambda n: scope_query(user_id, email, n), envelope),
        media_type="application/json",
        headers=_attachment(f"slangcart-account-backup-{label}-{stamp}.json"),
    )


# ══════════════════ 4E — SERVER-PACKED BACKUP FILES ═══════════════════
#
# Nov 2026 — the app used to hold a screen open while the server STREAMED a
# full backup; on Atlas the pack can take tens of minutes, a minimized app
# paused the JS side, and a dead cursor left the download hanging at
# "Packing on the server…" forever. Now the server packs the file in a
# BACKGROUND task (bytes kept in `backup_file_chunks`), the phone polls for
# progress and only downloads once the file is finished — fast, and immune
# to the app being closed in between.

_PREPARED_TTL_HOURS = 24
_FILE_CHUNK_BYTES = 4 * 1024 * 1024  # keep Mongo docs comfortably under 16 MB


async def _pack_backup_file(job_id: str, names: List[str], query_for, envelope: Dict[str, Any]) -> None:
    """Background task: run the same JSON stream into Mongo chunks."""
    buf = bytearray()
    seq = 0
    done = 0
    total_bytes = 0
    try:
        async def _flush(final: bool = False) -> None:
            nonlocal seq
            while len(buf) >= _FILE_CHUNK_BYTES or (final and buf):
                take = min(len(buf), _FILE_CHUNK_BYTES)
                await db.backup_file_chunks.insert_one(
                    {"job_id": job_id, "seq": seq, "data": bytes(buf[:take])},
                )
                del buf[:take]
                seq += 1
                if len(buf) < _FILE_CHUNK_BYTES and not final:
                    break

        # Track which collection the stream is on by watching the emitted
        # "name":[ markers — a cheap way to report progress.
        import re as _re
        marker = _re.compile(rb'"([^"\\]+)":\[$')
        async for part in _backup_json_bytes(names, query_for, envelope):
            m = marker.search(part.rstrip())
            if m:
                nm = m.group(1).decode("utf-8", "ignore")
                if nm in names:
                    done = names.index(nm) + 1
            buf.extend(part)
            total_bytes += len(part)
            await _flush()
            await db.backup_file_jobs.update_one(
                {"id": job_id},
                {"$set": {"bytes_written": total_bytes, "collections_done": done}},
            )
        await _flush(final=True)
        await db.backup_file_jobs.update_one(
            {"id": job_id},
            {"$set": {"status": "ready", "finished_at": now_utc().isoformat(),
                      "collections_done": len(names)}},
        )
    except Exception as e:
        log.exception("backup pack %s failed", job_id)
        await db.backup_file_jobs.update_one(
            {"id": job_id},
            {"$set": {"status": "failed", "error": str(e), "finished_at": now_utc().isoformat()}},
        )


@router.post("/admin/backup/file/prepare")
async def prepare_backup_file(
    payload: Dict[str, Any] = Body(default={}),
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    """Start packing a backup file on the server. Returns a job id the app
    polls; the finished file downloads in seconds. Works even if the app is
    closed while packing."""
    scope = (payload.get("scope") or "app").lower()
    user_id = payload.get("user_id")
    if scope == "account":
        if not user_id:
            raise HTTPException(status_code=400, detail="user_id required for an account backup")
        u = await _scope_target(user_id)
        email = (u.get("email") or "").lower() or None
        names = await _exportable_collections(False)
        query_for = lambda n: scope_query(user_id, email, n)
        envelope = {
            "format": APP_EXPORT_FORMAT, "version": 1, "scope": "account",
            "account": {"id": u["id"], "email": u.get("email"), "name": u.get("name")},
            "exported_at": now_utc().isoformat(),
        }
        filename = f"slangcart-account-backup-{(u.get('email') or user_id).replace('@', '-at-')}-{now_utc().strftime('%Y%m%d-%H%M')}.json"
    else:
        names = await _exportable_collections(bool(payload.get("include_reference")))
        query_for = lambda _n: {}
        envelope = {
            "format": APP_EXPORT_FORMAT, "version": 1, "scope": "app",
            "exported_at": now_utc().isoformat(),
        }
        filename = f"slangcart-full-backup-{now_utc().strftime('%Y%m%d-%H%M')}.json"

    # Retention: prepared files are a cache, not history — drop anything old.
    cutoff = (now_utc() - timedelta(hours=_PREPARED_TTL_HOURS)).isoformat()
    old = await db.backup_file_jobs.find({"created_at": {"$lt": cutoff}}, {"_id": 0, "id": 1}).to_list(100)
    if old:
        old_ids = [o["id"] for o in old]
        await db.backup_file_jobs.delete_many({"id": {"$in": old_ids}})
        await db.backup_file_chunks.delete_many({"job_id": {"$in": old_ids}})

    job_id = str(uuid.uuid4())
    await db.backup_file_jobs.insert_one({
        "id": job_id,
        "status": "packing",
        "scope": scope,
        "filename": filename,
        "collections_total": len(names),
        "collections_done": 0,
        "bytes_written": 0,
        "created_by": admin["id"],
        "created_at": now_utc().isoformat(),
    })
    asyncio.create_task(_pack_backup_file(job_id, names, query_for, envelope))
    return {"job_id": job_id, "status": "packing", "collections_total": len(names)}


@router.get("/admin/backup/file/jobs/{job_id}")
async def backup_file_job_status(
    job_id: str,
    _: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    job = await db.backup_file_jobs.find_one({"id": job_id, "expired": {"$ne": True}}, {"_id": 0})
    if not job:
        raise HTTPException(status_code=404, detail="No such backup job")
    return job


@router.get("/admin/backup/file/jobs/{job_id}/download")
async def download_prepared_backup(
    job_id: str,
    _: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    """Stream the finished file from its Mongo chunks — fast, because the
    packing already happened."""
    job = await db.backup_file_jobs.find_one({"id": job_id, "expired": {"$ne": True}})
    if not job:
        raise HTTPException(status_code=404, detail="No such backup job")
    if job.get("status") != "ready":
        raise HTTPException(status_code=409, detail=f"Still packing ({job.get('status')})")

    async def _chunks() -> AsyncIterator[bytes]:
        async for ch in db.backup_file_chunks.find({"job_id": job_id, "expired": {"$ne": True}}).sort("seq", 1):
            yield bytes(ch["data"])

    return StreamingResponse(
        _chunks(),
        media_type="application/json",
        headers=_attachment(job.get("filename") or f"slangcart-backup-{job_id}.json"),
    )


@router.post("/admin/backup/restore")
async def admin_backup_restore(
    payload: Dict[str, Any] = Body(...),
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    """Replay one page of one collection from a backup file.

    Body:
      collection : target collection name (required)
      docs       : list of documents (required)
      mode       : "merge" (upsert by id) | "wipe" (delete the collection's
                   rows on the first chunk, then insert)
      first_chunk: true on the first page for this collection
      danger_pin : the 6-digit Danger PIN — same gate as Danger Zone

    Money is restored exactly as it appears in the file (owner's choice); this
    is a data replay, so no commission, payout or notification logic runs.
    """
    collection = str(payload.get("collection") or "").strip()
    docs = payload.get("docs")
    mode = (payload.get("mode") or "merge").lower()
    first_chunk = bool(payload.get("first_chunk"))
    pin = str(payload.get("danger_pin") or "")

    if not collection or collection in NEVER_EXPORT:
        raise HTTPException(status_code=400, detail="Invalid collection")
    if not isinstance(docs, list):
        raise HTTPException(status_code=400, detail="docs must be a list")
    if mode not in ("merge", "wipe"):
        raise HTTPException(status_code=400, detail="mode must be 'merge' or 'wipe'")
    if not await get_danger_pin_hash():
        raise HTTPException(status_code=400, detail="Danger PIN not set. Set it in Admin → Admin access.")
    if not await verify_danger_pin(pin):
        raise HTTPException(status_code=401, detail="Invalid Danger PIN")

    # Read the live Danger PIN BEFORE anything is deleted — a `wipe` of
    # `settings` empties the very row it lives in.
    live_pin = await get_danger_pin_hash() if collection == "settings" else None

    # Same for the acting admin's sessions: restoring `users` would otherwise
    # roll back `active_session_ids` and log the admin out mid-restore.
    live_sessions: Optional[Dict[str, Any]] = None
    if collection == "users":
        live_sessions = await db.users.find_one(
            {"id": admin["id"]},
            {"_id": 0, "active_session_ids": 1, "active_session_id": 1},
        )

    wiped = 0
    if mode == "wipe" and first_chunk:
        res = await db[collection].delete_many({})
        wiped = res.deleted_count

    # Jun 2026 — revive what the export encoded: real ObjectIds and real image
    # bytes.  `_id` is KEPT (it is the key behind `/api/img/<key>`), so a
    # restore can upsert on it and bring the permanent image store back.
    cleaned = [_json_revive(d) for d in docs if isinstance(d, dict)]

    if collection == "users":
        # The file's session data must not clobber whoever is logged in now.
        for d in cleaned:
            d.pop("active_session_ids", None)
            d.pop("active_session_id", None)

    # The Danger PIN lives in `settings`, and the admin had to type it to get
    # here. Restoring a file from another deployment (or one taken before the
    # PIN was changed) used to overwrite the live hash, so the VERY NEXT
    # collection came back 401 "Invalid Danger PIN" — the client walks
    # collections alphabetically and stops on the first error, which meant
    # `users`, `transactions`, `wallet_topups`, `withdrawals` and everything
    # else after `settings` was never restored, and the admin was locked out
    # of their own PIN. The live PIN is therefore always kept.
    if collection == "settings":
        for d in cleaned:
            d.pop("danger_pin_hash", None)

    # ── Jun 2026 — Permanent images on restore ────────────────────────────
    # A Shopify-CSV→JSON file carries `image_url` plus a whole `images`
    # array of Shopify-CDN links (sometimes as objects with an `Image
    # Position`).  Those links are not ours and stop resolving, so every
    # one is downloaded into permanent storage here, in file order, with
    # duplicates removed.  Prices, stock, descriptions, variants, GST and
    # categories are never touched.
    #
    # A chunk of 25 products can carry 300+ photos, which would blow past
    # the 60 s edge timeout.  So each chunk gets a TIME BUDGET: whatever is
    # downloaded inline is reported immediately, and anything left over is
    # marked `pending` and handed to the background repair worker — it is
    # never reported as restored and never silently dropped.
    image_report: Dict[str, Any] = {"imported": 0, "reused": 0, "failed": 0, "failures": [], "deferred": 0}
    if collection == "products" and cleaned:
        import time as _time
        from core.image_store import merge_reports, normalize_gallery, persist_product_images
        deadline = _time.monotonic() + RESTORE_IMAGE_BUDGET_SECONDS
        for d in cleaned:
            # Shape-normalise ALWAYS (cheap, no network): flattens Shopify
            # image objects, honours `Image Position`, drops duplicates.
            if "images" in d:
                d["images"] = normalize_gallery(d.get("images"))
            if _time.monotonic() > deadline:
                d["image_import_status"] = "pending"
                image_report["deferred"] += 1
                continue
            try:
                rep = await persist_product_images(d)
            except Exception as exc:          # never abort a restore on images
                log.warning("restore image persist failed for %s: %s", d.get("id"), exc)
                d["image_import_status"] = "pending"
                image_report["deferred"] += 1
                continue
            for f in rep.get("failures", []):
                f.setdefault("product", d.get("name") or d.get("id"))
            merge_reports(image_report, rep)

    inserted = 0
    upserted = 0
    replayed = 0
    if cleaned:
        if mode == "wipe":
            # A client that retries a chunk (flaky mobile upload) used to hit a
            # duplicate `_id` and get a 500 now that `_id` is restored. Upsert
            # on `_id` so a retry is simply a no-op.
            keyed = [d for d in cleaned if d.get("_id") is not None]
            plain = [d for d in cleaned if d.get("_id") is None]
            if keyed:
                r = await db[collection].bulk_write(
                    [ReplaceOne({"_id": d["_id"]}, d, upsert=True) for d in keyed],
                    ordered=False,
                )
                inserted += (r.upserted_count or 0)
                # A retried chunk matches rows already restored — counting
                # those again over-reported the restore summary.
                replayed += (r.matched_count or 0)
            if plain:
                await db[collection].insert_many(plain)
                inserted += len(plain)
        else:
            ops = []
            plain = []
            for d in cleaned:
                if d.get("id"):
                    # Mongo refuses to change an existing document's `_id`
                    # (error 66), so a row already present under a different
                    # `_id` made the whole restore 500 — and since the client
                    # walks collections in order, everything after `settings`
                    # was never restored. Match on `id`, leave `_id` alone.
                    body = {k: v for k, v in d.items() if k != "_id"}
                    ops.append(ReplaceOne({"id": d["id"]}, body, upsert=True))
                elif d.get("_id") is not None:
                    # Jun 2026 — collections with no `id` field (short_ids,
                    # image_assets, payout_keys, product_image_files…) used to
                    # be blind-inserted, so a second merge duplicated them or
                    # tripped a unique index.  `_id` is unique by definition.
                    ops.append(ReplaceOne({"_id": d["_id"]}, d, upsert=True))
                else:
                    plain.append(d)
            if ops:
                r = await db[collection].bulk_write(ops, ordered=False)
                # `modified_count` is 0 when the document is byte-identical, which
                # made a re-restore look like it had done nothing. Count matches.
                upserted = (r.upserted_count or 0) + (r.matched_count or 0)
            if plain:
                await db[collection].insert_many(plain)
                inserted = len(plain)

    if collection == "products":
        try:
            from routes.products_public import bust_products_public_caches
            bust_products_public_caches()
        except Exception:
            pass
        # Anything we ran out of time for is picked up by the background
        # repair worker, so the catalogue converges on permanent images
        # without the admin having to do anything.
        if image_report.get("deferred"):
            try:
                import asyncio as _aio
                from routes.product_images_repair import start_background_repair
                _aio.create_task(start_background_repair(delay=5.0))
            except Exception:
                pass

    if collection == "settings" and live_pin:
        # Put the admin's own PIN back whatever the file contained, so the
        # next collection in the walk still authenticates.
        await db.settings.update_one(
            {"id": "global"}, {"$set": {"danger_pin_hash": live_pin}}, upsert=True,
        )

    if collection == "users" and live_sessions:
        # Re-attach the acting admin's live sessions — ReplaceOne/wipe would
        # otherwise leave them logged out of the very restore they're running.
        await db.users.update_one(
            {"id": admin["id"]},
            {"$set": {
                "active_session_ids": live_sessions.get("active_session_ids") or [],
                "active_session_id": live_sessions.get("active_session_id"),
            }},
        )

    await db.audit_logs.insert_one({
        "id": str(uuid.uuid4()),
        "actor_id": admin.get("id"),
        "actor_email": admin.get("email"),
        "action": "backup.restore_file",
        "entity": "collection",
        "entity_id": collection,
        "details": {"mode": mode, "docs": len(cleaned), "wiped": wiped},
        "timestamp": now_utc().isoformat(),
    })
    return {
        "ok": True, "collection": collection, "mode": mode,
        "wiped": wiped, "inserted": inserted, "upserted": upserted,
        # Rows a retried chunk found already restored — counted separately so
        # the summary doesn't claim them as freshly inserted.
        "replayed": replayed,
        # Separate image success / failure counts so the restore report can
        # show exactly which photos did not come across and why.
        "images_imported": image_report["imported"],
        "images_reused": image_report["reused"],
        "images_failed": image_report["failed"],
        "images_deferred": image_report.get("deferred", 0),
        "image_failures": image_report["failures"][:25],
    }
