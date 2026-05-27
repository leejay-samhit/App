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
from models import CartItem, CartRemove

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


@router.get("/cart")
async def cart_get(user: Dict[str, Any] = Depends(get_current_user)):
    """Return enriched cart: each row carries the product detail + line_total.
    Cart icon badge on the Shop tab reads from `count`."""
    items = await db.cart_items.find({"user_id": user["id"]}, {"_id": 0}).to_list(1000)
    enriched = []
    total = 0.0
    for it in items:
        product = await db.products.find_one({"id": it["product_id"]}, {"_id": 0})
        if product:
            line_total = product["price"] * it["qty"]
            total += line_total
            enriched.append({**it, "product": product, "line_total": line_total})
    return {"items": enriched, "total": total, "count": sum(i["qty"] for i in items)}


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
