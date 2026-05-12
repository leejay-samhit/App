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


# IMPORTANT: this route MUST be declared BEFORE `/products/{product_id}` or
# FastAPI's first-match routing will treat "by-source" as a product_id and
# 404 the whole dynamic shop-layout pipeline. Same pattern as the previously
# fixed /admin/pincodes/in-region route-ordering bug.
@router.get("/products/by-source")
async def list_products_by_source(
    source: str = "trending",
    limit: int = 10,
    category: str | None = None,
):
    """Return products for a Shop Layout section based on a logical source:

      source=trending  → top N by `interested_count` then orders volume
      source=new       → newest by `created_at`
      source=best      → most-sold (uses `sales_count` if tracked, else `interested_count`)
      source=category  → filtered by `category` field

    Optional `category` filter narrows ALL sources to a department/category.
    Always returns a flat ARRAY of shaped products (same shape as /products),
    so the mobile renderer can drop them straight into a product grid.
    """
    limit = max(1, min(50, int(limit or 10)))
    src = (source or "trending").strip().lower()
    if src not in ("trending", "new", "best", "category", "manual"):
        src = "trending"

    q: Dict[str, Any] = {"$or": [{"is_published": True}, {"is_published": {"$exists": False}}]}
    if category:
        q["category"] = category

    if src == "new":
        cursor = db.products.find(q, {"_id": 0}).sort("created_at", -1).limit(limit)
    elif src == "category":
        cursor = db.products.find(q, {"_id": 0}).sort("created_at", -1).limit(limit)
    else:
        # trending / best → pull a larger window, then sort in-process by a
        # composite "popularity" score so MongoDB doesn't need a custom index.
        cursor = db.products.find(q, {"_id": 0}).sort("created_at", -1).limit(max(limit * 4, 40))

    items = await cursor.to_list(limit * 4 if src in ("trending", "best") else limit)
    if src in ("trending", "best"):
        def score(p: Dict[str, Any]) -> int:
            interested = p.get("interested_users") or []
            interested_n = len(interested) if isinstance(interested, list) else 0
            sales = int(p.get("sales_count") or 0)
            # `best` weights actual sales heavier; `trending` weights interest
            if src == "best":
                return sales * 10 + interested_n
            return interested_n * 5 + sales
        items.sort(key=score, reverse=True)
        items = items[:limit]
    return [_shape_product(p) for p in items]


@router.get("/products/{product_id}")
async def get_product(product_id: str):
    """Public single-product detail endpoint.

    Returns the FULL product document (all extended fields included) plus the
    computed `is_in_stock` and `interested_count`.  Used by the customer
    Product Detail page so we don't have to fetch the entire catalog just to
    render one product.

    Legacy products (created before the extended schema landed) are still
    returned cleanly with safe defaults for any missing rich field, so the UI
    never explodes on `undefined` accesses.
    """
    p = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    # Hide unpublished products from the public endpoint (admins use a
    # different route).
    if p.get("is_published") is False:
        raise HTTPException(status_code=404, detail="Product not available")
    # ── Back-fill safe defaults for legacy products ──
    p.setdefault("brand", "")
    p.setdefault("sub_features", [])
    p.setdefault("images", [])
    p.setdefault("price_summary", {"text": "", "bold": False, "font_size": None, "align": "left"})
    p.setdefault("protection_summary", {"text": "", "bold": False, "font_size": None, "align": "left"})
    p.setdefault("warranty_summary", {"text": "", "bold": False, "font_size": None, "align": "left"})
    p.setdefault("delivery_summary", {"text": "", "bold": False, "font_size": None, "align": "left"})
    p.setdefault("attrs_brand", "")
    p.setdefault("attrs_os", "")
    p.setdefault("attrs_ram", "")
    p.setdefault("attrs_cpu_model", "")
    p.setdefault("attrs_cpu_speed", "")
    p.setdefault("attrs_storage", "")
    p.setdefault("extra_attrs", {})
    p.setdefault("spec_tabs", [])
    p.setdefault("whats_in_box", [])
    return _shape_product(p)


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

