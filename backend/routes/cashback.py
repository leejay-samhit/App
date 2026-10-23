"""Cashback routes — public config, customer summary, vendor outstanding and
the admin pending-cashback queue.

All money maths lives in `core/cashback.py`; these endpoints only read it or
trigger it. Nothing here ever trusts a client-supplied amount.
"""
import csv
import io
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from core.cashback import (
    MAX_CASHBACK_PCT,
    clamp_pct,
    customer_cashback_summary,
    fund_pending_cashback,
    recover_outstanding_from_wallet,
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
    from core import vendor_advances
    # Oct-2026 — the screen shows EVERY rupee a seller owes us: fronted
    # cashback AND advances (a return refund the company paid because his
    # wallet was short, fees). One list, one recovery button.
    q: Dict[str, Any] = {"status": "open",
                         "kind": {"$in": ["cashback", *vendor_advances.RECOVERABLE_KINDS]}}
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
            "cashback_outstanding": 0.0,
            "advance_outstanding": 0.0,
            "orders": 0,
        })
        slot["outstanding"] = round(slot["outstanding"] + owed, 2)
        if r.get("kind") == "cashback":
            slot["cashback_outstanding"] = round(slot.get("cashback_outstanding", 0.0) + owed, 2)
        else:
            slot["advance_outstanding"] = round(slot.get("advance_outstanding", 0.0) + owed, 2)
        slot["orders"] += 1
    # Jun-2026 — recovery now comes out of the seller's shop-earnings wallet,
    # so the admin must see what is actually collectable right now.
    if by_vendor:
        async for v in db.users.find(
            {"id": {"$in": list(by_vendor.keys())}},
            {"_id": 0, "id": 1, "vendor_earnings": 1, "vendor_business_name": 1,
             "shop_name": 1, "name": 1},
        ):
            slot = by_vendor.get(v["id"])
            if not slot:
                continue
            avail = round(float(v.get("vendor_earnings") or 0), 2)
            slot["vendor_name"] = (
                slot.get("vendor_name") or v.get("vendor_business_name")
                or v.get("shop_name") or v.get("name")
            )
            slot["wallet_balance"] = avail
            slot["recoverable_now"] = round(min(avail, slot["outstanding"]), 2)
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
    """Recover fronted cashback from the seller's SHOP EARNINGS WALLET.

    Jun-2026 — the old screen offered "cash entry" and "bank deposit", which
    were two hand-typed entries for money that had not necessarily moved and
    could be recorded twice. There is now exactly ONE process: pull it out of
    the balance the seller already has with us. One wallet debit, one
    treasury credit, one audit row — nothing to reconcile by hand.
    """
    from server import credit_admin_bucket

    try:
        amount = round(float(payload.get("amount") or 0), 2)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid amount")
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero")

    note = str(payload.get("note") or "Shop earnings wallet recovery").strip()
    try:
        result = await recover_outstanding_from_wallet(
            vendor_id, amount,
            credit_admin_bucket=credit_admin_bucket,
            note=note,
            recorded_by=admin.get("email") or admin.get("id"),
        )
        # Oct-2026 — cashback first, then whatever the company advanced for
        # this shop (a return refund it funded, fees). Same wallet, same
        # single tap, two clearly-labelled ledger rows.
        applied_cb = round(float(result.get("applied") or 0), 2)
        left = round(amount - applied_cb, 2)
        adv: Dict[str, Any] = {"applied": 0.0}
        if left > 0.009:
            from core import vendor_advances
            adv = await vendor_advances.recover_from_wallet(
                vendor_id, left,
                credit_admin_bucket=credit_admin_bucket,
                note=note,
                recorded_by=admin.get("email") or admin.get("id"),
            )
        applied_adv = round(float(adv.get("applied") or 0), 2)
        result = {
            **result,
            "cashback_applied": applied_cb,
            "advance_applied": applied_adv,
            "applied": round(applied_cb + applied_adv, 2),
            "rows": int(result.get("rows") or 0) + int(adv.get("rows") or 0),
            "outstanding_before": round(
                float(result.get("outstanding_before") or 0)
                + float(adv.get("outstanding_before") or 0), 2),
            "outstanding_after": round(
                float(result.get("outstanding_after") or 0)
                + float(adv.get("outstanding_after") or 0), 2),
            "unapplied": round(max(0.0, amount - applied_cb - applied_adv), 2),
            "cashback_outstanding_after": result.get("outstanding_after"),
            "advance_outstanding_after": adv.get("outstanding_after"),
            "wallet_after": adv.get("wallet_after", result.get("wallet_after")),
        }
        if applied_cb <= 0.009 and applied_adv > 0.009:
            result.pop("reason", None)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if result.get("applied", 0) <= 0.009 and result.get("reason") in ("wallet_empty", "nothing_to_recover"):
        raise HTTPException(
            status_code=400,
            detail=(
                "There is nothing to recover from this seller right now."
                if result.get("reason") == "nothing_to_recover" else
                "This seller's shop earnings wallet has no balance to recover from yet. "
                "It is recovered automatically from his next sale."
            ),
        )
    await _audit_log(admin, "cashback.recover_outstanding", "user", vendor_id, {
        "amount": amount, "note": note, "method": "wallet", **result,
    })
    return {"ok": True, "at": now_utc().isoformat(), **result}


@router.get("/admin/cashback/outstanding/export")
async def admin_cashback_outstanding_export(
    _: Dict[str, Any] = Depends(require_admin),
    status: str = "all",
):
    """Excel-friendly CSV of seller cashback outstanding, so the owner can
    track who is pending and who has cleared without reading the app.

    `status`: all | open | settled
    """
    q: Dict[str, Any] = {"kind": "cashback"}
    if status in ("open", "settled"):
        q["status"] = status
    rows = await db.vendor_outstanding.find(q, {"_id": 0}).sort("created_at", 1).to_list(20000)

    vendor_ids = sorted({r.get("vendor_id") for r in rows if r.get("vendor_id")})
    vendors = {
        v["id"]: v for v in await db.users.find(
            {"id": {"$in": vendor_ids}},
            {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1,
             "shop_name": 1, "cashback_outstanding": 1, "vendor_earnings": 1},
        ).to_list(len(vendor_ids) or 1)
    }
    # How much each seller has had clawed back automatically out of sales.
    auto_agg = await db.transactions.aggregate([
        {"$match": {"type": "cashback_recovery", "vendor_id": {"$in": vendor_ids}}},
        {"$group": {"_id": "$vendor_id", "sum": {"$sum": "$amount"}}},
    ]).to_list(len(vendor_ids) or 1)
    auto_by_vendor = {a["_id"]: round(float(a["sum"] or 0), 2) for a in auto_agg}
    manual_agg = await db.transactions.aggregate([
        {"$match": {"type": "cashback_vendor_recovery", "vendor_id": {"$in": vendor_ids}}},
        {"$group": {"_id": "$vendor_id", "sum": {"$sum": "$amount"}}},
    ]).to_list(len(vendor_ids) or 1)
    manual_by_vendor = {a["_id"]: round(float(a["sum"] or 0), 2) for a in manual_agg}

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "Seller", "Shop", "Email", "Phone", "Order #", "Order ID",
        "Cashback fronted (Rs)", "Recovered (Rs)", "Still owed (Rs)", "Row status",
        "Raised on", "Settled on",
        "Seller total outstanding (Rs)", "Auto-recovered from sales (Rs)",
        "Manually recovered (Rs)", "Seller shop wallet (Rs)",
    ])
    for r in rows:
        v = vendors.get(r.get("vendor_id")) or {}
        fronted = round(float(r.get("amount") or 0), 2)
        recovered = round(float(r.get("recovered") or 0), 2)
        w.writerow([
            v.get("name") or r.get("vendor_name") or "",
            v.get("shop_name") or "",
            v.get("email") or "",
            v.get("phone") or "",
            r.get("order_number") or "",
            r.get("order_id") or "",
            f"{fronted:.2f}",
            f"{recovered:.2f}",
            f"{max(0.0, round(fronted - recovered, 2)):.2f}",
            "CLEARED" if r.get("status") == "settled" else "PENDING",
            str(r.get("created_at") or "")[:19],
            str(r.get("settled_at") or "")[:19],
            f"{round(float(v.get('cashback_outstanding') or 0), 2):.2f}",
            f"{auto_by_vendor.get(r.get('vendor_id'), 0.0):.2f}",
            f"{manual_by_vendor.get(r.get('vendor_id'), 0.0):.2f}",
            f"{round(float(v.get('vendor_earnings') or 0), 2):.2f}",
        ])
    stamp = now_utc().strftime("%Y%m%d-%H%M")
    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={
            "Content-Disposition":
                f'attachment; filename="seller-cashback-outstanding-{status}-{stamp}.csv"',
        },
    )
