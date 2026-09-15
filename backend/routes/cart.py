"""Cart + user-facing orders endpoints.

Carved out of server.py during the Phase 2B modular refactor (2026-05-27).

Houses these GET/POST endpoints:
  • POST /cart/add
  • GET  /cart
  • POST /cart/remove
  • POST /cart/clear
  • GET  /orders/me

POST /orders/checkout is intentionally NOT moved here — it depends on the
commission engine which still lives in server.py.
"""
import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from core.db import db
from core.security import get_current_user
from core.utils import now_utc
from core.variants import effective_line_price, find_variant
from models import CartItem, CartAdjust, CartRemove

router = APIRouter()


# ── Variant helpers (Jun 2026) ──────────────────────────────────────────
# A cart ROW is now keyed by (user, product, variant). Two sizes of the same
# shirt are two independent rows with their own qty, price and stock check.
# `variant_id: None` is stored as "" so the Mongo key is stable.
def _row_key(user_id: str, product_id: str, variant_id) -> dict:
    return {
        "user_id": user_id,
        "product_id": product_id,
        "variant_id": str(variant_id or ""),
    }


async def _resolve_variant(product: dict, variant_id, qty_wanted: int):
    """Validate the chosen option against the product. Returns the variant
    dict (or None for a plain product) and raises a friendly 400 when the
    customer skipped the size picker or picked a sold-out size."""
    variants = [v for v in (product.get("variants") or []) if v.get("active", True)]
    if not variants:
        return None
    v = find_variant(product, variant_id)
    if not v or not v.get("active", True):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "variant_required",
                "message": f"Please choose a size / option for '{product.get('name')}'.",
                "options": [
                    {"id": x.get("id"), "label": x.get("label"), "stock": x.get("stock", 0)}
                    for x in variants
                ],
            },
        )
    if int(v.get("stock") or 0) < qty_wanted:
        raise HTTPException(
            status_code=400,
            detail=f"'{product.get('name')}' — {v.get('label')} has only {int(v.get('stock') or 0)} left.",
        )
    return v


@router.post("/cart/add")
async def cart_add(payload: CartItem, user: Dict[str, Any] = Depends(get_current_user)):
    """Add a product to the user's cart (or bump qty if already there).
    Uses $inc so concurrent adds are safe at the Mongo level — no races."""
    product = await db.products.find_one({"id": payload.product_id}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    key = _row_key(user["id"], payload.product_id, payload.variant_id)
    existing = await db.cart_items.find_one(key)
    want = int(existing.get("qty", 0)) + payload.qty if existing else payload.qty
    variant = await _resolve_variant(product, payload.variant_id, want)
    if existing:
        await db.cart_items.update_one(key, {"$inc": {"qty": payload.qty}})
    else:
        await db.cart_items.insert_one({
            "id": str(uuid.uuid4()),
            **key,
            "variant_label": (variant or {}).get("label", ""),
            "qty": payload.qty,
            "created_at": now_utc().isoformat(),
        })
    return {"ok": True, "variant_label": (variant or {}).get("label", "")}


@router.post("/cart/adjust")
async def cart_adjust(payload: CartAdjust, user: Dict[str, Any] = Depends(get_current_user)):
    """Jun 2026 — Inline qty stepper.  Accepts any non-zero delta (± int)
    so the shop product cards can decrement without re-designing the
    /cart/add validator.  If the resulting qty ≤ 0 the row is deleted so
    the client sees a clean stepper→Add transition."""
    if payload.delta == 0:
        raise HTTPException(status_code=400, detail="delta must be non-zero")
    key = _row_key(user["id"], payload.product_id, payload.variant_id)
    existing = await db.cart_items.find_one(key)
    if not existing:
        if payload.delta < 0:
            raise HTTPException(status_code=400, detail="Cart row does not exist")
        # Positive delta → treat as an add for a brand-new row.
        product = await db.products.find_one({"id": payload.product_id}, {"_id": 0})
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        variant = await _resolve_variant(product, payload.variant_id, payload.delta)
        await db.cart_items.insert_one({
            "id": str(uuid.uuid4()),
            **key,
            "variant_label": (variant or {}).get("label", ""),
            "qty": payload.delta,
            "created_at": now_utc().isoformat(),
        })
        return {"ok": True, "qty": payload.delta}
    new_qty = int(existing.get("qty", 0)) + payload.delta
    if new_qty <= 0:
        await db.cart_items.delete_one(key)
        return {"ok": True, "qty": 0, "removed": True}
    if payload.delta > 0:
        product = await db.products.find_one({"id": payload.product_id}, {"_id": 0})
        if product:
            await _resolve_variant(product, payload.variant_id, new_qty)
            # Plain products (no variants) carry stock on the product doc.
            if not (product.get("variants") or []):
                avail = int(product.get("stock") or 0)
                if new_qty > avail:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Only {avail} left in stock for '{product.get('name')}'.",
                    )
    await db.cart_items.update_one(key, {"$set": {"qty": new_qty}})
    return {"ok": True, "qty": new_qty}


@router.post("/orders/{order_id}/reorder")
async def reorder(order_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    """Jun 2026 — one-tap Reorder from My Orders.

    Re-adds every line of a past order to the cart. Items that can't come
    back (delisted, out of stock, or the seller no longer delivers to the
    customer's saved delivery pincode) are SKIPPED and reported, so the
    buyer gets whatever is still available instead of a hard failure.
    """
    order = await db.orders.find_one({"id": order_id, "user_id": user["id"]}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    lines = order.get("items") or []
    if not lines:
        raise HTTPException(status_code=400, detail="This order has no items to reorder.")

    pids = list({ln.get("product_id") for ln in lines if ln.get("product_id")})
    products = {
        p["id"]: p
        async for p in db.products.find(
            {"id": {"$in": pids}},
            {"_id": 0, "images": 0, "description": 0, "specifications": 0, "reviews": 0, "questions": 0},
        )
    }

    # Same delivery-eligibility rule the shop uses, based on the pincode the
    # order was shipped to (best available signal for "where I buy").
    from routes.products_public import _eligible_vendor_ids
    ship_pin = str((order.get("shipping_address") or {}).get("pincode") or "").strip()
    addr = order.get("shipping_address") or {}
    eligible = await _eligible_vendor_ids(
        pincode=ship_pin or None,
        lat=addr.get("latitude") if isinstance(addr.get("latitude"), (int, float)) else None,
        lng=addr.get("longitude") if isinstance(addr.get("longitude"), (int, float)) else None,
    )

    added: list = []
    skipped: list = []
    for ln in lines:
        name = ln.get("name") or "Item"
        qty = max(1, int(ln.get("qty") or 1))
        product = products.get(ln.get("product_id"))
        if not product or product.get("is_published") is False:
            skipped.append({"name": name, "reason": "no longer available"})
            continue
        vid = product.get("vendor_id")
        if vid and vid not in eligible:
            skipped.append({"name": name, "reason": "seller doesn't deliver to your area anymore"})
            continue

        variant = find_variant(product, ln.get("variant_id"))
        active_variants = [v for v in (product.get("variants") or []) if v.get("active", True)]
        if active_variants and not variant:
            skipped.append({"name": name, "reason": "this size / option was discontinued"})
            continue
        avail = int((variant or product).get("stock") or 0)
        if avail <= 0:
            skipped.append({"name": name, "reason": "out of stock"})
            continue
        take = min(qty, avail)

        key = _row_key(user["id"], product["id"], (variant or {}).get("id"))
        existing = await db.cart_items.find_one(key)
        if existing:
            # Don't stack past the shelf — cap the row at available stock.
            new_qty = min(int(existing.get("qty") or 0) + take, avail)
            await db.cart_items.update_one(key, {"$set": {"qty": new_qty}})
        else:
            await db.cart_items.insert_one({
                "id": str(uuid.uuid4()),
                **key,
                "variant_label": (variant or {}).get("label", ""),
                "qty": take,
                "created_at": now_utc().isoformat(),
            })
        added.append({"name": name, "qty": take, "variant_label": (variant or {}).get("label", "")})
        if take < qty:
            skipped.append({"name": name, "reason": f"only {avail} left — added {take}"})

    if not added:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "reorder_unavailable",
                "message": "None of these items can be reordered right now.",
                "skipped": skipped,
            },
        )
    count = await db.cart_items.count_documents({"user_id": user["id"]})
    return {"ok": True, "added": added, "skipped": skipped, "cart_count": count}


@router.get("/cart")
async def cart_get(user: Dict[str, Any] = Depends(get_current_user)):
    """Return enriched cart: each row carries the product detail + line_total.
    Cart icon badge on the Shop tab reads from `count`.

    Jun 2026 (scale fix):
      • Uses ONE batched find({id: {$in: [...]}}) instead of N find_one()
        loops (per-item RTT was killing cart open time).
      • Only projects list-safe fields — base64 images are excluded so a
        5-item cart can't ship 5 MB over the wire.  image_url is rewritten
        to the lazy thumbnail endpoint if it was a data: URI.
    """
    items = await db.cart_items.find({"user_id": user["id"]}, {"_id": 0}).to_list(1000)
    if not items:
        return {"items": [], "total": 0.0, "count": 0}

    pids = list({it.get("product_id") for it in items if it.get("product_id")})
    # Slim projection — drop the heavy fields that a cart row never needs.
    proj = {
        "_id": 0,
        "images": 0,
        "description": 0,
        "specifications": 0,
        "interested_users": 0,
        "reviews": 0,
        "questions": 0,
    }
    prod_map: Dict[str, Dict[str, Any]] = {}
    async for p in db.products.find({"id": {"$in": pids}}, proj):
        # Rewrite base64 image URLs to the thumbnail endpoint so the cart
        # doesn't drag a full 500 KB data URI over per line.
        img = p.get("image_url") or ""
        if isinstance(img, str) and img.startswith("data:"):
            p["image_url"] = f"/api/products/{p.get('id')}/image?w=240&q=70"
        prod_map[p["id"]] = p

    # Jun 2026 — the cart groups lines by SELLER (checkout splits into one
    # order per vendor), so ship the vendor display name with every row.
    vendor_ids = list({p.get("vendor_id") for p in prod_map.values() if p.get("vendor_id")})
    vendor_names: Dict[str, str] = {}
    if vendor_ids:
        async for v in db.users.find(
            {"id": {"$in": vendor_ids}},
            {"_id": 0, "id": 1, "vendor_business_name": 1, "shop_name": 1, "name": 1},
        ):
            vendor_names[v["id"]] = (
                v.get("vendor_business_name") or v.get("shop_name") or v.get("name") or "Seller"
            )
    for p in prod_map.values():
        if p.get("vendor_id"):
            p["vendor_name"] = vendor_names.get(p["vendor_id"]) or "Seller"

    enriched = []
    total = 0.0
    for it in items:
        product = prod_map.get(it.get("product_id"))
        if product:
            # Jun 2026 — price comes from the chosen size / RAM-ROM option
            # when the product has variants.
            variant = find_variant(product, it.get("variant_id"))
            unit = effective_line_price(product, variant)
            line_total = round(unit * float(it.get("qty", 0)), 2)
            total += line_total
            enriched.append({
                **it,
                "product": product,
                "unit_price": unit,
                "variant_label": (variant or {}).get("label", it.get("variant_label") or ""),
                "variant_stock": int((variant or {}).get("stock") or 0) if variant else None,
                "line_total": line_total,
            })
    return {"items": enriched, "total": total, "count": sum(int(i.get("qty", 0)) for i in items)}


@router.post("/cart/remove")
async def cart_remove(payload: CartRemove, user: Dict[str, Any] = Depends(get_current_user)):
    """Drop a cart row entirely (regardless of qty).

    Jun 2026 — when no `variant_id` is supplied we remove EVERY option of
    that product, which is what the cart screen's swipe-to-delete means.
    """
    if payload.variant_id:
        await db.cart_items.delete_one(_row_key(user["id"], payload.product_id, payload.variant_id))
    else:
        await db.cart_items.delete_many({"user_id": user["id"], "product_id": payload.product_id})
    return {"ok": True}


@router.post("/cart/clear")
async def cart_clear(user: Dict[str, Any] = Depends(get_current_user)):
    """Wipe the cart — called after a successful checkout AND from the
    user-facing 'Clear cart' button."""
    await db.cart_items.delete_many({"user_id": user["id"]})
    return {"ok": True}


@router.get("/orders/me")
async def my_orders(user: Dict[str, Any] = Depends(get_current_user)):
    """User's order history. Returns up to 500 rows newest-first — the FE
    paginates client-side because order volumes are very small per user.

    Jun 2026 — checkouts are now SPLIT into one order per vendor, so each
    row already carries `vendor_id` / `vendor_name` / `order_number`.
    Legacy pre-split orders are back-filled on read so the UI can render
    a single consistent card design.
    """
    items = await db.orders.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(500)

    # Back-fill vendor identity for legacy (pre-split) orders.
    need_vendor = [o for o in items if not o.get("vendor_name")]
    vendor_ids = set()
    for o in need_vendor:
        vid = o.get("vendor_id") or next(
            (it.get("vendor_id") for it in (o.get("items") or []) if it.get("vendor_id")), None,
        )
        if vid:
            vendor_ids.add(vid)
    names: Dict[str, str] = {}
    if vendor_ids:
        rows = await db.users.find(
            {"id": {"$in": list(vendor_ids)}},
            {"_id": 0, "id": 1, "vendor_business_name": 1, "shop_name": 1, "name": 1},
        ).to_list(len(vendor_ids))
        names = {
            r["id"]: (r.get("vendor_business_name") or r.get("shop_name") or r.get("name") or "Vendor")
            for r in rows
        }

    for o in items:
        if not o.get("order_number"):
            o["order_number"] = f"SC-{str(o.get('id') or '')[:6].upper()}"
        vids = {it.get("vendor_id") for it in (o.get("items") or []) if it.get("vendor_id")}
        if not o.get("vendor_id") and len(vids) == 1:
            o["vendor_id"] = next(iter(vids))
        if not o.get("vendor_name") and o.get("vendor_id"):
            o["vendor_name"] = names.get(o["vendor_id"])
        # Legacy docs predate the wallet/COD split fields.
        if o.get("wallet_paid") is None:
            paid_via = (o.get("paid_via") or "wallet").lower()
            o["wallet_paid"] = 0.0 if paid_via == "cod" else float(o.get("total") or 0)
        if o.get("online_paid") is None:
            o["online_paid"] = 0.0
        if o.get("cod_due") is None:
            o["cod_due"] = round(
                float(o.get("total") or 0)
                - float(o.get("wallet_paid") or 0)
                - float(o.get("online_paid") or 0),
                2,
            )
        o["vendor_count"] = len(vids) or 1

    # ── Phase 2 — return eligibility (7 days from successful delivery) ──
    # Computed on the SERVER so app and web can never disagree about which
    # orders still show "Return" (and which are simply "Completed").
    from core import returns as _rt
    from core.utils import get_settings as _get_settings
    from datetime import datetime, timezone
    _s = await _get_settings()
    try:
        window = max(0, int(_s.get("return_window_days") or _rt.DEFAULT_WINDOW_DAYS))
    except (TypeError, ValueError):
        window = _rt.DEFAULT_WINDOW_DAYS
    ret_rows = await db.returns.find(
        {"user_id": user["id"]},
        {"_id": 0, "order_id": 1, "status": 1, "items": 1, "return_number": 1, "id": 1},
    ).to_list(1000)
    by_order: Dict[str, List[Dict[str, Any]]] = {}
    for r in ret_rows:
        by_order.setdefault(r.get("order_id"), []).append(r)
    now = datetime.now(timezone.utc)
    for o in items:
        status = (o.get("status") or "").lower()
        rows = by_order.get(o.get("id")) or []
        returned: Dict[str, int] = {}
        for r in rows:
            if r.get("status") in ("rejected", "cancelled"):
                continue
            for it in r.get("items") or []:
                k = f"{it.get('product_id')}|{it.get('variant_id') or ''}"
                returned[k] = returned.get(k, 0) + int(float(it.get("qty") or 0))
        units_left = 0
        for it in o.get("items") or []:
            k = f"{it.get('product_id')}|{it.get('variant_id') or ''}"
            units_left += max(0, int(float(it.get("qty") or 1)) - returned.get(k, 0))
        deadline = _rt._deadline(o.get("delivered_at"), window) if status == "delivered" else None
        within = False
        days_left = 0
        if deadline:
            try:
                dl = datetime.fromisoformat(deadline)
                if dl.tzinfo is None:
                    dl = dl.replace(tzinfo=timezone.utc)
                within = now <= dl
                if within:
                    gap = dl - now
                    days_left = gap.days + (1 if gap.seconds > 0 else 0)
            except ValueError:
                within = False
        o["return_window_days"] = window
        o["return_deadline"] = deadline
        o["return_days_left"] = days_left
        o["return_eligible"] = bool(status == "delivered" and within and units_left > 0)
        o["return_window_expired"] = bool(status == "delivered" and deadline and not within)
        o["returnable_units"] = units_left
        o["has_returns"] = bool(rows)
        o["returns"] = [
            {"id": r.get("id"), "return_number": r.get("return_number"), "status": r.get("status")}
            for r in rows
        ]
        o["can_cancel"] = bool(status == "placed" and not o.get("delivery_info_updated_at"))
        o["display_status"] = (
            "completed"
            if (status == "delivered" and (not within or units_left <= 0)) else status
        )
    return items


@router.post("/orders/{order_id}/chat-vendor")
async def chat_vendor_for_order(order_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    """Jun 2026 — One-tap "Ask this seller" from My Orders.

    A completed purchase is itself proof of relationship, so we skip the
    chat-request handshake and open (or reuse) a direct thread between the
    buyer and the order's vendor. Returns `{ thread_id }`.
    """
    o = await db.orders.find_one({"id": order_id, "user_id": user["id"]}, {"_id": 0})
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    vendor_id = o.get("vendor_id") or next(
        (it.get("vendor_id") for it in (o.get("items") or []) if it.get("vendor_id")), None,
    )
    if not vendor_id:
        raise HTTPException(status_code=400, detail="This order has no seller to chat with.")
    if vendor_id == user["id"]:
        raise HTTPException(status_code=400, detail="You can't chat with yourself.")
    vendor = await db.users.find_one({"id": vendor_id}, {"_id": 0, "id": 1})
    if not vendor:
        raise HTTPException(status_code=404, detail="Seller account not found.")

    from routes.chat import _find_or_create_thread
    thread = await _find_or_create_thread(user["id"], vendor_id)
    return {"thread_id": thread.get("id"), "vendor_id": vendor_id}


@router.post("/orders/{order_id}/cancel")
async def cancel_my_order(order_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    """User-initiated order cancellation.

    Jul 2026 policy: a customer may cancel ONLY when
      • the order is still at status="placed", AND
      • the vendor hasn't taken any downstream action yet
        (i.e. `delivery_info_updated_at` is not set — the vendor
        hasn't set ETA / delivery-person nor moved to shipped).
    Once the vendor engages with the order, cancellation is disabled
    to protect the vendor's fulfilment workflow.
    """
    o = await db.orders.find_one({"id": order_id, "user_id": user["id"]}, {"_id": 0})
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    if o.get("status") != "placed":
        raise HTTPException(status_code=400, detail="This order can no longer be cancelled by you. Contact support.")
    if o.get("delivery_info_updated_at"):
        raise HTTPException(status_code=400, detail="Your vendor has already started processing this order. Please contact support to cancel.")

    # Flip status + refund wallet if paid via wallet.
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).isoformat()
    await db.orders.update_one({"id": order_id}, {"$set": {"status": "cancelled", "cancelled_at": ts, "cancelled_by": "user"}})
    # Refund the wallet-funded portion (full total for wallet orders,
    # `wallet_paid` slice for Wallet+COD combos, nothing for pure COD).
    paid_via = (o.get("paid_via") or "").lower()
    if paid_via == "wallet":
        refund_amt = float(o.get("total") or 0)
    elif paid_via in ("wallet_cod", "online", "wallet_online"):
        # Wallet slice + any Razorpay-captured amount (online refunds land in
        # the wallet). Pure-cash portions were never collected.
        refund_amt = float(o.get("wallet_paid") or 0) + float(o.get("online_paid") or 0)
    else:
        refund_amt = 0.0
    if refund_amt > 0:
        await db.users.update_one({"id": user["id"]}, {"$inc": {"wallet_balance": refund_amt}})
        try:
            import uuid as _u
            await db.transactions.insert_one({
                "id": str(_u.uuid4()), "user_id": user["id"], "type": "refund",
                "amount": refund_amt, "status": "success",
                "description": f"Refund for cancelled order {o.get('order_number') or ('#' + order_id[:8].upper())}",
                "order_id": order_id, "created_at": ts,
            })
        except Exception:
            pass
    return {"ok": True, "status": "cancelled", "refunded": round(refund_amt, 2)}
