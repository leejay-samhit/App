"""Public product catalog routes.
Extracted from server.py during Phase 2B refactor.

Endpoints (mounted at /api by server.py):
  GET  /products                  — public, returns published products
                                    with computed `is_in_stock` flag and
                                    `interested_count`
  POST /products/{id}/interested  — auth user registers interest in an
                                    out-of-stock product (idempotent)
  GET  /products/{id}/interested  — admin/vendor sees the count + list of
                                    users interested
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from core.db import db
from core.notifications import create_notification
from core.security import get_current_user
from core.utils import now_utc

router = APIRouter(tags=["products-public"])


def _shape_product(p: Dict[str, Any]) -> Dict[str, Any]:
    """Add computed fields (`is_in_stock`, `interested_count`) to a product doc.
    Keeps the original fields untouched so existing UI code keeps working."""
    stock = int(p.get("stock") or 0)
    interested = p.get("interested_users") or []
    p["is_in_stock"] = stock > 0
    p["interested_count"] = len(interested) if isinstance(interested, list) else 0
    # Don't leak raw user-id list to the public endpoint — only the count.
    p.pop("interested_users", None)
    return p


@router.get("/products")
async def list_products():
    items = await db.products.find(
        {"$or": [{"is_published": True}, {"is_published": {"$exists": False}}]},
        {"_id": 0},
    ).sort("created_at", -1).to_list(2000)
    return [_shape_product(p) for p in items]


@router.post("/products/{product_id}/interested")
async def register_interest(
    product_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Customer marks they're interested in an out-of-stock product. Idempotent
    — same user clicking twice doesn't double-count. Notifies the vendor (if
    any) so they can plan a restock."""
    product = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Idempotent add via $addToSet
    res = await db.products.update_one(
        {"id": product_id},
        {"$addToSet": {"interested_users": user["id"]}},
    )
    fresh = await db.products.find_one({"id": product_id}, {"_id": 0})
    interested = fresh.get("interested_users") or []
    count = len(interested) if isinstance(interested, list) else 0

    # Newly added (modified_count==1 means the array changed) → notify vendor
    if res.modified_count > 0 and product.get("vendor_id"):
        try:
            await create_notification(
                product["vendor_id"],
                "stock_interest",
                "Customer wants to buy your product",
                f"{user.get('name')} is interested in '{product.get('name')}' "
                f"(now {count} customer{'s' if count != 1 else ''} interested). "
                "Restock soon to capture the sale.",
                extra={"product_id": product_id},
            )
        except Exception:
            pass

    return {
        "ok": True,
        "interested_count": count,
        "already_registered": res.modified_count == 0,
    }


@router.get("/products/{product_id}/interested")
async def list_interested_users(
    product_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Vendor (owner) or admin can see the count + list of users interested.
    Customers get a 403."""
    product = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    is_admin = user.get("role") == "admin"
    is_owner = product.get("vendor_id") == user["id"]
    if not is_admin and not is_owner:
        raise HTTPException(status_code=403, detail="Not allowed")

    ids = product.get("interested_users") or []
    users_info: list = []
    if ids:
        cursor = db.users.find(
            {"id": {"$in": ids}},
            {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1},
        )
        users_info = await cursor.to_list(2000)

    return {
        "product_id": product_id,
        "product_name": product.get("name"),
        "interested_count": len(ids),
        "users": users_info,
        "as_of": now_utc().isoformat(),
    }

