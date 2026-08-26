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
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from core.db import db
from core.security import get_current_user
from core.utils import now_utc
from models import CartItem, CartAdjust, CartRemove

router = APIRouter()


@router.post("/cart/add")
async def cart_add(payload: CartItem, user: Dict[str, Any] = Depends(get_current_user)):
    """Add a product to the user's cart (or bump qty if already there).
    Uses $inc so concurrent adds are safe at the Mongo level — no races."""
    product = await db.products.find_one({"id": payload.product_id}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    existing = await db.cart_items.find_one(
        {"user_id": user["id"], "product_id": payload.product_id},
    )
    if existing:
        await db.cart_items.update_one(
            {"user_id": user["id"], "product_id": payload.product_id},
            {"$inc": {"qty": payload.qty}},
        )
    else:
        await db.cart_items.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": user["id"],
            "product_id": payload.product_id,
            "qty": payload.qty,
            "created_at": now_utc().isoformat(),
        })
    return {"ok": True}


@router.post("/cart/adjust")
async def cart_adjust(payload: CartAdjust, user: Dict[str, Any] = Depends(get_current_user)):
    """Jun 2026 — Inline qty stepper.  Accepts any non-zero delta (± int)
    so the shop product cards can decrement without re-designing the
    /cart/add validator.  If the resulting qty ≤ 0 the row is deleted so
    the client sees a clean stepper→Add transition."""
    if payload.delta == 0:
        raise HTTPException(status_code=400, detail="delta must be non-zero")
    existing = await db.cart_items.find_one(
        {"user_id": user["id"], "product_id": payload.product_id},
    )
    if not existing:
        if payload.delta < 0:
            raise HTTPException(status_code=400, detail="Cart row does not exist")
        # Positive delta → treat as an add for a brand-new row.
        product = await db.products.find_one({"id": payload.product_id}, {"_id": 0, "id": 1})
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        await db.cart_items.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": user["id"],
            "product_id": payload.product_id,
            "qty": payload.delta,
            "created_at": now_utc().isoformat(),
        })
        return {"ok": True, "qty": payload.delta}
    new_qty = int(existing.get("qty", 0)) + payload.delta
    if new_qty <= 0:
        await db.cart_items.delete_one({"user_id": user["id"], "product_id": payload.product_id})
        return {"ok": True, "qty": 0, "removed": True}
    await db.cart_items.update_one(
        {"user_id": user["id"], "product_id": payload.product_id},
        {"$set": {"qty": new_qty}},
    )
    return {"ok": True, "qty": new_qty}


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

    enriched = []
    total = 0.0
    for it in items:
        product = prod_map.get(it.get("product_id"))
        if product:
            line_total = float(product.get("price", 0)) * float(it.get("qty", 0))
            total += line_total
            enriched.append({**it, "product": product, "line_total": line_total})
    return {"items": enriched, "total": total, "count": sum(int(i.get("qty", 0)) for i in items)}


@router.post("/cart/remove")
async def cart_remove(payload: CartRemove, user: Dict[str, Any] = Depends(get_current_user)):
    """Drop a product from the cart entirely (regardless of qty)."""
    await db.cart_items.delete_one({"user_id": user["id"], "product_id": payload.product_id})
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
        if o.get("cod_due") is None:
            o["cod_due"] = round(float(o.get("total") or 0) - float(o.get("wallet_paid") or 0), 2)
        o["vendor_count"] = len(vids) or 1
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
    elif paid_via == "wallet_cod":
        refund_amt = float(o.get("wallet_paid") or 0)
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
