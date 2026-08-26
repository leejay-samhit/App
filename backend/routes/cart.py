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
    paginates client-side because order volumes are very small per user."""
    items = await db.orders.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return items


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
    # Refund wallet if applicable
    if (o.get("paid_via") or "").lower() == "wallet" and (o.get("total") or 0) > 0:
        await db.users.update_one({"id": user["id"]}, {"$inc": {"wallet_balance": float(o["total"])}})
        try:
            import uuid as _u
            await db.transactions.insert_one({
                "id": str(_u.uuid4()), "user_id": user["id"], "type": "refund",
                "amount": float(o["total"]), "status": "success",
                "description": f"Refund for cancelled order #{order_id[:8].upper()}",
                "order_id": order_id, "created_at": ts,
            })
        except Exception:
            pass
    return {"ok": True, "status": "cancelled"}
