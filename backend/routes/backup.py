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
import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pymongo import ReplaceOne

from core.danger import get_danger_pin_hash, verify_danger_pin
from core.db import db
from core.security import get_current_user, require_admin_role
from core.utils import now_utc

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
    docs = await db.products.find({"vendor_id": vendor["id"]}, {"_id": 0}) \
        .sort("created_at", 1).skip(offset).limit(limit).to_list(limit)
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
    """
    products: List[Dict[str, Any]] = payload.get("products") or []
    mode = (payload.get("mode") or "merge").lower()
    first_chunk = bool(payload.get("first_chunk"))
    if mode not in ("merge", "replace"):
        raise HTTPException(status_code=400, detail="mode must be 'merge' or 'replace'")
    if not isinstance(products, list):
        raise HTTPException(status_code=400, detail="products must be a list")

    wiped = 0
    if mode == "replace" and first_chunk:
        mine = await db.products.find({"vendor_id": vendor["id"]}, {"_id": 0, "id": 1}).to_list(5000)
        ids = [m["id"] for m in mine if m.get("id")]
        if ids:
            await db.products.delete_many({"id": {"$in": ids}})
            await db.cart_items.delete_many({"product_id": {"$in": ids}})
            wiped = len(ids)

    from core.image_compress import compress_product_payload
    from core.variants import apply_variants_to_payload

    created = 0
    skipped: List[str] = []
    docs: List[Dict[str, Any]] = []
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
        body = apply_variants_to_payload(body, price)
        docs.append({
            "id": str(uuid.uuid4()),
            **body,
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
            "created_at": now_utc().isoformat(),
            # Owner's choice: restored items are drafts until reviewed, and
            # publishing remains an admin action.
            "is_published": False,
            "restored_from_backup": True,
        })

    if docs:
        await db.products.insert_many(docs)
        created = len(docs)
        try:
            from routes.products_public import bust_products_public_caches
            bust_products_public_caches()
        except Exception:
            pass

    return {"ok": True, "created": created, "wiped": wiped, "skipped": skipped, "mode": mode}


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


def _json_safe(value: Any) -> Any:
    """Make a Mongo document JSON-serialisable without losing information."""
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items() if k != "_id"}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, ObjectId):
        return str(value)
    return value


async def _exportable_collections(include_reference: bool) -> List[str]:
    names = await db.list_collection_names()
    out = [
        n for n in sorted(names)
        if n not in NEVER_EXPORT and (include_reference or n not in REFERENCE_COLLECTIONS)
    ]
    return out


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
        collections.append({"name": n, "count": await db[n].count_documents({})})
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
    total = await db[collection].count_documents({})
    docs = await db[collection].find({}).skip(offset).limit(limit).to_list(limit)
    return {
        "collection": collection,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": (offset + len(docs)) < total,
        "docs": [_json_safe(d) for d in docs],
    }


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

    wiped = 0
    if mode == "wipe" and first_chunk:
        res = await db[collection].delete_many({})
        wiped = res.deleted_count

    cleaned = [{k: v for k, v in d.items() if k != "_id"} for d in docs if isinstance(d, dict)]
    inserted = 0
    upserted = 0
    if cleaned:
        if mode == "wipe":
            await db[collection].insert_many(cleaned)
            inserted = len(cleaned)
        else:
            ops = []
            plain = []
            for d in cleaned:
                if d.get("id"):
                    ops.append(ReplaceOne({"id": d["id"]}, d, upsert=True))
                else:
                    plain.append(d)
            if ops:
                r = await db[collection].bulk_write(ops, ordered=False)
                upserted = (r.upserted_count or 0) + (r.modified_count or 0)
            if plain:
                await db[collection].insert_many(plain)
                inserted = len(plain)

    if collection == "products":
        try:
            from routes.products_public import bust_products_public_caches
            bust_products_public_caches()
        except Exception:
            pass

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
    }
