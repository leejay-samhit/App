"""Cashback routes — public config, customer summary, vendor outstanding and
the admin pending-cashback queue.

All money maths lives in `core/cashback.py`; these endpoints only read it or
trigger it. Nothing here ever trusts a client-supplied amount.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from core.cashback import (
    MAX_CASHBACK_PCT,
    clamp_pct,
    customer_cashback_summary,
    fund_pending_cashback,
    recover_vendor_outstanding,
)
from core.db import db
from core.security import get_current_user, require_admin, require_admin_role
from core.utils import get_settings, now_utc, audit_log as _audit_log

router = APIRouter()


async def require_vendor(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Approved-seller gate. Mirrors server.require_vendor; declared locally
    so this module never imports server at module scope."""
    if not (user.get("is_vendor") and user.get("is_vendor_approved")):
        raise HTTPException(status_code=403, detail="Vendor access required")
    return user


@router.get("/cashback-config")
async def cashback_config() -> Dict[str, Any]:
    """Public config so the product page / cart can SHOW the applicable
    cashback before purchase. The authoritative amount is always recomputed
    server-side at checkout and again at settlement."""
    s = await get_settings()
    return {
        "max_cashback_pct": MAX_CASHBACK_PCT,
        "default_cashback_pct": clamp_pct(s.get("default_cashback_pct")),
        "cashback_enabled": bool(s.get("cashback_enabled", True)),
        "delivery_charge_enabled": bool(s.get("delivery_charge_enabled", True)),
        "delivery_charge_flat": float(s.get("delivery_charge_flat") or 0),
        "delivery_free_threshold": float(s.get("delivery_free_threshold") or 0),
        "delivery_cart_max": float(s.get("delivery_cart_max") or 0),
    }


@router.get("/users/me/cashback")
async def my_cashback(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    summary = await customer_cashback_summary(user["id"])
    # Name the sellers so the customer sees "arriving soon from <shop>".
    vendor_ids = [r.get("vendor_id") for r in summary["pending_orders"] if r.get("vendor_id")]
    names: Dict[str, Dict[str, Any]] = {}
    if vendor_ids:
        async for v in db.users.find(
            {"id": {"$in": vendor_ids}},
            {"_id": 0, "id": 1, "store_name": 1, "shop_name": 1, "name": 1, "phone": 1, "email": 1},
        ):
            names[v["id"]] = v
    for row in summary["pending_orders"]:
        v = names.get(row.get("vendor_id") or "") or {}
        row["vendor_name"] = v.get("store_name") or v.get("shop_name") or v.get("name") or "the seller"
        row["vendor_phone"] = v.get("phone")
        row["vendor_email"] = v.get("email")
    return summary


@router.get("/vendor/me/cashback")
async def vendor_cashback(vendor: Dict[str, Any] = Depends(require_vendor)) -> Dict[str, Any]:
    """Seller view: what they funded, what they still owe Slangcart."""
    vid = vendor["id"]

    async def _sum(match: Dict[str, Any]) -> float:
        agg = await db.transactions.aggregate([
            {"$match": match},
            {"$group": {"_id": None, "t": {"$sum": "$amount"}}},
        ]).to_list(1)
        return round(float(agg[0]["t"]), 2) if agg else 0.0

    funded = abs(await _sum({"user_id": vid, "type": "cashback_funding", "status": "success"}))
    refunded = await _sum({"user_id": vid, "type": "cashback_funding_refund", "status": "success"})
    open_rows = await db.vendor_outstanding.find(
        {"vendor_id": vid, "status": "open", "kind": "cashback"}, {"_id": 0},
    ).sort("created_at", 1).to_list(200)
    outstanding = round(
        sum(float(r.get("amount") or 0) - float(r.get("recovered") or 0) for r in open_rows), 2,
    )
    pending = await db.cashback_ledger.count_documents({"vendor_id": vid, "status": "pending"})
    return {
        "funded_total": funded,
        "funding_refunded": refunded,
        "outstanding": outstanding,
        "outstanding_rows": open_rows,
        "pending_count": pending,
        "wallet_balance": round(float(vendor.get("wallet_balance") or 0), 2),
    }


@router.get("/admin/cashback/pending")
async def admin_pending_cashback(
    _: Dict[str, Any] = Depends(require_admin),
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """Queue of cashback that could not be funded when the order was
    delivered, so an admin can release it manually."""
    limit = max(1, min(limit, 200))
    rows = await db.cashback_ledger.find(
        {"status": "pending"},
    ).sort("created_at", 1).skip(max(0, offset)).limit(limit).to_list(limit)
    total = await db.cashback_ledger.count_documents({"status": "pending"})
    total_amount = 0.0
    agg = await db.cashback_ledger.aggregate([
        {"$match": {"status": "pending"}},
        {"$group": {"_id": None, "t": {"$sum": "$amount"}}},
    ]).to_list(1)
    if agg:
        total_amount = round(float(agg[0]["t"]), 2)

    user_ids = list({r.get("user_id") for r in rows if r.get("user_id")})
    vendor_ids = list({r.get("vendor_id") for r in rows if r.get("vendor_id")})
    people: Dict[str, Dict[str, Any]] = {}
    if user_ids or vendor_ids:
        async for u in db.users.find(
            {"id": {"$in": user_ids + vendor_ids}},
            {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1,
             "store_name": 1, "shop_name": 1, "wallet_balance": 1},
        ):
            people[u["id"]] = u
    out: List[Dict[str, Any]] = []
    for r in rows:
        r.pop("_id", None)
        cust = people.get(r.get("user_id") or "") or {}
        vend = people.get(r.get("vendor_id") or "") or {}
        out.append({
            **r,
            "order_id": r.get("order_id"),
            "customer_name": cust.get("name"),
            "customer_email": cust.get("email"),
            "customer_phone": cust.get("phone"),
            "vendor_name": vend.get("store_name") or vend.get("shop_name") or vend.get("name"),
            "vendor_phone": vend.get("phone"),
            "vendor_wallet_balance": round(float(vend.get("wallet_balance") or 0), 2),
        })
    return {"items": out, "total": total, "total_amount": total_amount}


@router.post("/admin/cashback/{order_id}/fund")
async def admin_fund_cashback(
    order_id: str,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "finance")),
) -> Dict[str, Any]:
    """Manually release one pending cashback. Prefers the seller's wallet if
    the money has since arrived; otherwise Slangcart fronts it and books a
    recoverable seller outstanding. The customer is never credited twice."""
    from server import credit_admin_bucket
    from core.notifications import create_notification

    result = await fund_pending_cashback(
        order_id,
        credit_admin_bucket=credit_admin_bucket,
        notify=create_notification,
        by=admin.get("email") or admin.get("id"),
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason") or "Could not fund this cashback")
    await _audit_log(admin, "cashback.manual_fund", "order", order_id, result)
    return result


@router.get("/admin/cashback/outstanding")
async def admin_cashback_outstanding(
    _: Dict[str, Any] = Depends(require_admin),
    vendor_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Money Slangcart fronted on behalf of sellers and has not recovered."""
    q: Dict[str, Any] = {"status": "open", "kind": "cashback"}
    if vendor_id:
        q["vendor_id"] = vendor_id
    rows = await db.vendor_outstanding.find(q, {"_id": 0}).sort("created_at", 1).to_list(500)
    by_vendor: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        owed = round(float(r.get("amount") or 0) - float(r.get("recovered") or 0), 2)
        slot = by_vendor.setdefault(r["vendor_id"], {
            "vendor_id": r["vendor_id"],
            "vendor_name": r.get("vendor_name"),
            "outstanding": 0.0,
            "orders": 0,
        })
        slot["outstanding"] = round(slot["outstanding"] + owed, 2)
        slot["orders"] += 1
    return {
        "vendors": sorted(by_vendor.values(), key=lambda x: -x["outstanding"]),
        "rows": rows,
        "total": round(sum(v["outstanding"] for v in by_vendor.values()), 2),
    }


@router.post("/admin/cashback/outstanding/{vendor_id}/recover")
async def admin_recover_outstanding(
    vendor_id: str,
    payload: Dict[str, Any],
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "finance")),
) -> Dict[str, Any]:
    """Record that a seller has paid Slangcart back. Settles their open
    cashback outstanding oldest-first. No customer wallet is touched."""
    from server import credit_admin_bucket

    try:
        amount = round(float(payload.get("amount") or 0), 2)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid amount")
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero")

    note = str(payload.get("note") or "Seller settled outstanding cashback").strip()
    result = await recover_vendor_outstanding(
        vendor_id, amount, credit_admin_bucket=credit_admin_bucket, note=note,
    )
    await _audit_log(admin, "cashback.recover_outstanding", "user", vendor_id, {
        "amount": amount, "note": note, **result,
    })
    return {"ok": True, "at": now_utc().isoformat(), **result}
