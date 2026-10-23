"""Vendor Net Worth · Sales Ledgers · Excel — Phase 2 (Jun-2026).

Every number here is derived from the LEDGER (`transactions`) or the source
documents (`orders`, `returns`, `offline_sales`). Nothing is computed on the
frontend, so the app, the vendor web panel and the downloaded workbook can
never disagree.
"""
import io
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from core import gst as gst_engine
from core import shop_money
from core.db import db
from core.security import get_current_user
from core.utils import now_utc

router = APIRouter()

LIVE_STATUSES = ("placed", "confirmed", "shipped", "out_for_delivery")
DEAD_STATUSES = ("cancelled", "refunded", "returned")


async def require_vendor(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if not (user.get("is_vendor") and user.get("is_vendor_approved")):
        raise HTTPException(status_code=403, detail="Vendor access required")
    return user


async def require_vendor_or_admin(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if user.get("role") == "admin" or user.get("is_admin") or (user.get("is_vendor") and user.get("is_vendor_approved")):
        return user
    raise HTTPException(status_code=403, detail="Vendor or admin access required")


def _f(v: Any) -> float:
    try:
        x = float(v or 0)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if x != x else x


def _r(v: Any) -> float:
    return round(_f(v), 2)


TYPE_GROUPS = {
    "opening_balance": "opening",
    "vendor_sale": "sales",
    "vendor_sale_reversal": "sale_reversals",
    "delivery_charge_paid": "delivery_charges",
    "delivery_charge_reversal": "delivery_charge_reversals",
    "return_refund_debit": "refunds",
    "withdrawal_hold": "withdrawals",
    "withdrawal_refund": "withdrawal_reversals",
    "cashback_funding": "cashback_funded",
    "cashback_funding_refund": "cashback_funding_returned",
    "vendor_adjustment_credit": "adjustments_credit",
    "vendor_adjustment_debit": "adjustments_debit",
    # What the platform clawed back out of this wallet.
    "cashback_recovery": "recoveries",
    "advance_recovery": "recoveries",
    "withdrawal_transaction_fee": "transaction_fees",
    "withdrawal_transaction_fee_refund": "transaction_fee_refunds",
}


# ── 1. Net worth ───────────────────────────────────────────────────────

@router.get("/vendor/me/net-worth")
async def vendor_net_worth(vendor: Dict[str, Any] = Depends(require_vendor)):
    """Opening + credits − debits = available. Straight off the ledger."""
    view = await shop_money.vendor_wallet_view(vendor["id"])

    rows = await db.transactions.find(
        {"user_id": vendor["id"], "wallet_impact": "vendor_earnings_only"},
        {"_id": 0, "type": 1, "credit": 1, "debit": 1, "amount": 1},
    ).to_list(50000)
    buckets: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        key = TYPE_GROUPS.get(r.get("type") or "", "other")
        slot = buckets.setdefault(key, {"key": key, "credit": 0.0, "debit": 0.0, "count": 0})
        c, d = _f(r.get("credit")), _f(r.get("debit"))
        if not c and not d:
            amt = abs(_f(r.get("amount")))
            if key in ("sales", "delivery_charge_reversals", "withdrawal_reversals",
                       "cashback_funding_returned", "adjustments_credit", "opening",
                       "transaction_fee_refunds"):
                c = amt
            else:
                d = amt
        slot["credit"] = _r(slot["credit"] + c)
        slot["debit"] = _r(slot["debit"] + d)
        slot["count"] += 1

    def _net(key: str) -> float:
        b = buckets.get(key) or {}
        return _r(_f(b.get("credit")) - _f(b.get("debit")))

    # COD cash the vendor will still physically collect (never a wallet row).
    cod_rows = await db.orders.find(
        {"vendor_id": vendor["id"], "cod_due": {"$gt": 0}, "status": {"$in": list(LIVE_STATUSES)}},
        {"_id": 0, "cod_due": 1},
    ).to_list(20000)
    cod_pending = _r(sum(_f(o.get("cod_due")) for o in cod_rows))

    offline = await db.offline_sales.aggregate([
        {"$match": {"vendor_id": vendor["id"], "status": "completed"}},
        {"$group": {
            "_id": None,
            "turnover": {"$sum": "$totals.grand_total"},
            "gst": {"$sum": "$totals.gst_total"},
            "profit": {"$sum": "$totals.profit"},
            "bills": {"$sum": 1},
        }},
    ]).to_list(1)
    off = offline[0] if offline else {}

    open_returns = await db.returns.count_documents(
        {"vendor_id": vendor["id"], "status": {"$in": ["requested", "approved", "returned"]}},
    )
    pending_refunds = await db.returns.aggregate([
        {"$match": {"vendor_id": vendor["id"], "status": "refund_pending"}},
        {"$group": {"_id": None, "s": {"$sum": "$refund_needed"}, "n": {"$sum": 1}}},
    ]).to_list(1)
    outstanding = await db.vendor_outstanding.aggregate([
        {"$match": {"vendor_id": vendor["id"], "status": "open"}},
        {"$group": {"_id": None, "s": {"$sum": "$amount"}, "r": {"$sum": "$recovered"}}},
    ]).to_list(1)

    return {
        "vendor_id": vendor["id"],
        "shop_name": vendor.get("vendor_business_name") or vendor.get("shop_name") or vendor.get("name"),
        "available_balance": view["available_balance"],
        "ledger_credits": view["ledger_credits"],
        "ledger_debits": view["ledger_debits"],
        "ledger_balance": view["ledger_balance"],
        "in_sync": view["in_sync"],
        "unledgered_difference": view["unledgered_difference"],
        "pending_withdrawals": view["pending_withdrawals"],
        "pending_balance": cod_pending,
        "withdrawable": _r(max(0.0, view["available_balance"])),
        "breakdown": {
            "opening": _net("opening"),
            "sales": _net("sales"),
            "sale_reversals": _r((buckets.get("sale_reversals") or {}).get("debit")),
            "delivery_charges": _r((buckets.get("delivery_charges") or {}).get("debit")),
            "refunds": _r((buckets.get("refunds") or {}).get("debit")),
            "withdrawals": _r((buckets.get("withdrawals") or {}).get("debit")),
            "cashback_funded": _r((buckets.get("cashback_funded") or {}).get("debit")),
            # Oct-2026 — the money that comes BACK also has to be on the
            # statement, otherwise the lines cannot add up to the balance
            # (a rejected settlement alone was ₹1.8 lakh off).
            "withdrawal_reversals": _r((buckets.get("withdrawal_reversals") or {}).get("credit")),
            "delivery_charge_reversals": _r((buckets.get("delivery_charge_reversals") or {}).get("credit")),
            "cashback_funding_returned": _r((buckets.get("cashback_funding_returned") or {}).get("credit")),
            "recoveries": _r((buckets.get("recoveries") or {}).get("debit")),
            "transaction_fees": _r((buckets.get("transaction_fees") or {}).get("debit")),
            "transaction_fee_refunds": _r((buckets.get("transaction_fee_refunds") or {}).get("credit")),
            "adjustments": _r(
                _f((buckets.get("adjustments_credit") or {}).get("credit"))
                - _f((buckets.get("adjustments_debit") or {}).get("debit"))
            ),
            "other": _net("other"),
        },
        "buckets": list(buckets.values()),
        "offline": {
            "turnover": _r(off.get("turnover")),
            "gst": _r(off.get("gst")),
            "profit": _r(off.get("profit")),
            "bills": int(off.get("bills") or 0),
        },
        "returns": {
            "open": open_returns,
            "refund_pending_amount": _r((pending_refunds or [{}])[0].get("s") if pending_refunds else 0),
            "refund_pending_count": int((pending_refunds or [{}])[0].get("n") or 0) if pending_refunds else 0,
        },
        "outstanding_to_platform": _r(
            _f((outstanding or [{}])[0].get("s")) - _f((outstanding or [{}])[0].get("r"))
            if outstanding else 0
        ),
        "reconciliation": {
            "formula": (
                "opening + sales + withdrawal reversals + delivery reversals + returned "
                "cashback funding + adjustments + other − sale reversals − delivery charges "
                "− refunds − withdrawals − cashback funded = available balance"
            ),
            "computed": view["ledger_balance"],
            "stored": view["available_balance"],
            "difference": view["unledgered_difference"],
            "balanced": view["in_sync"],
        },
        "generated_at": now_utc().isoformat(),
    }


# ── 2. Online shop sales ledger ────────────────────────────────────────

def _order_rows(orders: List[Dict[str, Any]], section: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for o in orders:
        paid_via = (o.get("paid_via") or "").lower()
        base = {
            "order_id": o.get("id"),
            "order_number": o.get("order_number"),
            "customer": o.get("customer_name") or (o.get("shipping_address") or {}).get("name") or "Customer",
            "status": o.get("status"),
            "payment_method": paid_via,
            "item_amount": _r(o.get("goods_total") if o.get("goods_total") is not None
                              else _f(o.get("total")) - _f(o.get("delivery_charge"))),
            "delivery_charge": _r(o.get("delivery_charge")),
            "total": _r(o.get("total")),
            "wallet_amount": _r(o.get("wallet_paid")),
            "online_amount": _r(o.get("online_paid")),
            "cod_amount": _r(o.get("cod_due")),
            "razorpay_payment_id": o.get("razorpay_payment_id") or "",
            "settlement_status": (
                "settled" if o.get("delivery_settled")
                else (o.get("delivery_settlement_status") or ("paid" if o.get("status") == "delivered" else "pending"))
            ),
            "treasury_deduction": _r(o.get("delivery_charge")) if o.get("delivery_settled") else 0.0,
            "created_at": o.get("created_at"),
            "delivered_at": o.get("delivered_at"),
            "items": [
                {
                    "product_id": it.get("product_id"),
                    "name": it.get("name"),
                    "qty": int(_f(it.get("qty")) or 1),
                    "unit_price": _r(_f(it.get("line_total")) / max(1, int(_f(it.get("qty")) or 1))),
                    "line_total": _r(it.get("line_total")),
                }
                for it in (o.get("items") or [])
            ],
        }
        out.append(base)
    return out


@router.get("/vendor/me/sales-ledger")
async def vendor_sales_ledger(
    section: str = Query("all", description="all|cod|wallet|online|returns"),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    order_id: Optional[str] = None,
    limit: int = 300,
    vendor: Dict[str, Any] = Depends(require_vendor),
):
    """Detailed online-shop ledger, split exactly as the owner specified:
    Cash on Delivery · Wallet Payment · Online Payment · Return Items."""
    limit = max(1, min(int(limit or 300), 1000))
    filt: Dict[str, Any] = {"vendor_id": vendor["id"]}
    if order_id:
        filt["$or"] = [{"id": order_id}, {"order_number": order_id}]
    if date_from or date_to:
        rng: Dict[str, Any] = {}
        if date_from:
            rng["$gte"] = date_from
        if date_to:
            rng["$lte"] = f"{date_to}T23:59:59.999999"
        filt["created_at"] = rng

    orders = await db.orders.find(filt, {"_id": 0}).sort("created_at", -1).limit(3000).to_list(3000)
    txn_by_order: Dict[str, Dict[str, Any]] = {}
    for t in await db.transactions.find(
        {"user_id": vendor["id"], "type": "vendor_sale"},
        {"_id": 0, "order_id": 1, "reference_number": 1, "id": 1, "amount": 1},
    ).to_list(20000):
        txn_by_order[t.get("order_id")] = t

    def _bucket(o: Dict[str, Any]) -> str:
        pv = (o.get("paid_via") or "").lower()
        if pv in ("cod", "wallet_cod"):
            return "cod"
        if pv in ("online", "wallet_online"):
            return "online"
        return "wallet"

    grouped: Dict[str, List[Dict[str, Any]]] = {"cod": [], "wallet": [], "online": []}
    for row, src in zip(_order_rows(orders, section), orders):
        t = txn_by_order.get(src.get("id")) or {}
        row["transaction_id"] = t.get("reference_number") or t.get("id") or ""
        row["vendor_credit"] = _r(t.get("amount"))
        row["remaining_vendor_amount"] = _r(_f(t.get("amount")) - (
            _f(src.get("delivery_charge")) if src.get("delivery_settled") else 0.0
        ))
        grouped[_bucket(src)].append(row)

    ret_filt: Dict[str, Any] = {"vendor_id": vendor["id"]}
    if order_id:
        ret_filt["$or"] = [{"order_id": order_id}, {"order_number": order_id}, {"return_number": order_id}]
    returns = await db.returns.find(ret_filt, {"_id": 0}).sort("created_at", -1).limit(1000).to_list(1000)
    return_rows: List[Dict[str, Any]] = []
    for r in returns:
        for it in r.get("items") or []:
            return_rows.append({
                "original_order_id": r.get("order_id"),
                "original_order_number": r.get("order_number"),
                "return_id": r.get("id"),
                "return_number": r.get("return_number"),
                "product": it.get("name"),
                "product_id": it.get("product_id"),
                "qty": int(_f(it.get("qty"))),
                "original_amount": _r(it.get("original_line_total")),
                "refund_amount": _r(it.get("refund_amount")),
                "original_payment_method": r.get("original_payment_method"),
                "vendor_debit": _r(it.get("refund_amount")),
                "customer_credit": _r(it.get("refund_amount")),
                "inventory_restored": bool(r.get("inventory_restored")),
                "transaction_id": r.get("refund_txn_id") or "",
                "status": r.get("status"),
                "created_at": r.get("created_at"),
            })

    def _sum(rows: List[Dict[str, Any]], key: str) -> float:
        return _r(sum(_f(x.get(key)) for x in rows))

    payload = {
        "cod": {
            "rows": grouped["cod"][:limit],
            "count": len(grouped["cod"]),
            "item_amount": _sum(grouped["cod"], "item_amount"),
            "delivery_charge": _sum(grouped["cod"], "delivery_charge"),
            "cash_to_collect": _sum(grouped["cod"], "cod_amount"),
        },
        "wallet": {
            "rows": grouped["wallet"][:limit],
            "count": len(grouped["wallet"]),
            "wallet_amount": _sum(grouped["wallet"], "wallet_amount"),
            "vendor_credit": _sum(grouped["wallet"], "vendor_credit"),
            "delivery_charge": _sum(grouped["wallet"], "delivery_charge"),
            "treasury_deduction": _sum(grouped["wallet"], "treasury_deduction"),
        },
        "online": {
            "rows": grouped["online"][:limit],
            "count": len(grouped["online"]),
            "item_amount": _sum(grouped["online"], "item_amount"),
            "delivery_charge": _sum(grouped["online"], "delivery_charge"),
            "vendor_credit": _sum(grouped["online"], "vendor_credit"),
        },
        "returns": {
            "rows": return_rows[:limit],
            "count": len(return_rows),
            "original_amount": _sum(return_rows, "original_amount"),
            "refund_amount": _sum(return_rows, "refund_amount"),
        },
        "generated_at": now_utc().isoformat(),
    }
    if section and section != "all":
        return {section: payload.get(section, {}), "generated_at": payload["generated_at"]}
    return payload


# ── 3. Offline shop sales ledger ───────────────────────────────────────

@router.get("/vendor/me/offline-ledger")
async def vendor_offline_ledger(
    mode: str = Query("all", description="all|cash|upi|card"),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 300,
    vendor: Dict[str, Any] = Depends(require_vendor),
):
    """Cash · UPI · Card counter sales with GST and net-worth impact."""
    limit = max(1, min(int(limit or 300), 1000))
    filt: Dict[str, Any] = {"vendor_id": vendor["id"], "status": "completed"}
    if date_from or date_to:
        rng: Dict[str, Any] = {}
        if date_from:
            rng["$gte"] = date_from
        if date_to:
            rng["$lte"] = f"{date_to}T23:59:59.999999"
        filt["created_at"] = rng
    sales = await db.offline_sales.find(filt, {"_id": 0}).sort("created_at", -1).limit(2000).to_list(2000)

    buckets: Dict[str, List[Dict[str, Any]]] = {"cash": [], "upi": [], "card": [], "other": []}
    for s in sales:
        payments = s.get("payments") or []
        totals = s.get("totals") or {}
        names = ", ".join(str(i.get("name") or "") for i in (s.get("items") or []))[:200]
        qty = sum(_f(i.get("qty")) for i in (s.get("items") or []))
        for p in payments or [{"mode": "cash", "amount": totals.get("grand_total")}]:
            m = (p.get("mode") or "cash").lower()
            key = m if m in buckets else "other"
            buckets[key].append({
                "sale_id": s.get("invoice_no") or s.get("id"),
                "raw_id": s.get("id"),
                "product": names,
                "qty": _r(qty),
                "amount": _r(p.get("amount")),
                "bill_total": _r(totals.get("grand_total")),
                "gst": _r(totals.get("gst_total")),
                "profit": _r(totals.get("profit")),
                "payment_mode": m,
                "reference": p.get("ref") or p.get("reference") or p.get("utr") or "",
                "payment_status": p.get("status") or "received",
                "customer": (s.get("customer") or {}).get("name") or "Walk-in",
                "net_worth_impact": _r(p.get("amount")),
                "created_at": s.get("created_at"),
            })

    def _pack(key: str) -> Dict[str, Any]:
        rows = buckets[key]
        return {
            "rows": rows[:limit],
            "count": len(rows),
            "amount": _r(sum(_f(r.get("amount")) for r in rows)),
            "gst": _r(sum(_f(r.get("gst")) for r in rows)),
        }

    payload = {k: _pack(k) for k in ("cash", "upi", "card", "other")}
    payload["generated_at"] = now_utc().isoformat()
    if mode and mode != "all":
        return {mode: payload.get(mode, {}), "generated_at": payload["generated_at"]}
    return payload


# ── 4. Excel export (Phase 2 §13) ──────────────────────────────────────

COLUMNS = [
    "Transaction ID", "Date/Time", "Transaction Group", "Transaction Type",
    "Customer/Vendor", "Shop", "Order ID", "Payment ID",
    "Source Wallet", "Destination Wallet", "Debit", "Credit", "Amount",
    "Previous Balance", "New Balance", "Cashback %", "Cashback Amount",
    "Delivery Charge", "GST", "Settlement Status", "Payment Method",
    "Reference ID", "Remarks",
]


@router.get("/vendor/me/net-worth/export")
async def export_net_worth(
    vendor: Dict[str, Any] = Depends(require_vendor),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    order_id: Optional[str] = None,
    payment_method: Optional[str] = None,
    txn_type: Optional[str] = None,
    settlement_status: Optional[str] = None,
    sale_type: Optional[str] = Query(None, description="online|offline|returns"),
):
    """One workbook: Net Worth ledger + Online sales + Offline sales +
    Returns + a Reconciliation sheet. Same numbers as the screens."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    filt: Dict[str, Any] = {"user_id": vendor["id"], "wallet_impact": "vendor_earnings_only"}
    if date_from or date_to:
        rng: Dict[str, Any] = {}
        if date_from:
            rng["$gte"] = date_from
        if date_to:
            rng["$lte"] = f"{date_to}T23:59:59.999999"
        filt["created_at"] = rng
    if order_id:
        filt["$or"] = [{"order_id": order_id}, {"order_number": order_id}]
    if payment_method:
        filt["payment_method"] = payment_method
    if txn_type:
        filt["type"] = txn_type
    if settlement_status:
        filt["settlement_status"] = settlement_status

    ledger = await db.transactions.find(filt, {"_id": 0}).sort("created_at", 1).limit(50000).to_list(50000)
    shop = vendor.get("vendor_business_name") or vendor.get("shop_name") or vendor.get("name") or ""

    wb = Workbook()
    wb.remove(wb.active)
    head_font = Font(bold=True, color="FFFFFF", size=10)
    head_fill = PatternFill("solid", fgColor="143D2E")
    sum_font = Font(bold=True, size=10)

    def _sheet(title: str, cols: List[str], rows: List[List[Any]], summary: List[tuple] = ()) -> None:
        ws = wb.create_sheet(title[:31])
        ws.append(cols)
        for i, _ in enumerate(cols, start=1):
            c = ws.cell(row=1, column=i)
            c.font = head_font
            c.fill = head_fill
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for r in rows:
            ws.append(r)
        if summary:
            start = ws.max_row + 2
            for i, (label, value) in enumerate(summary):
                ws.cell(row=start + i, column=1, value=label).font = sum_font
                ws.cell(row=start + i, column=2, value=value).font = sum_font
        for i in range(1, len(cols) + 1):
            ws.column_dimensions[get_column_letter(i)].width = 20
        ws.freeze_panes = "A2"

    if not sale_type or sale_type == "online":
        rows = [[
            r.get("reference_number") or r.get("id"),
            r.get("created_at"),
            r.get("txn_group") or "vendor",
            r.get("type"),
            r.get("shop_name") or shop,
            shop,
            r.get("order_number") or r.get("order_id") or "",
            r.get("payment_id") or "",
            r.get("source_wallet") or "",
            r.get("destination_wallet") or "",
            _r(r.get("debit")),
            _r(r.get("credit")),
            _r(r.get("amount")),
            r.get("previous_balance") if r.get("previous_balance") is not None else "",
            r.get("new_balance") if r.get("new_balance") is not None else "",
            _r(r.get("cashback_pct")),
            _r(r.get("cashback_amount")),
            _r(r.get("delivery_charge")),
            _r(r.get("gst")),
            r.get("settlement_status") or "",
            r.get("payment_method") or "",
            r.get("order_id") or r.get("payment_id") or r.get("id") or "",
            (r.get("remarks") or r.get("description") or "")[:400],
        ] for r in ledger]
        credits = _r(sum(_f(r.get("credit")) for r in ledger))
        debits = _r(sum(_f(r.get("debit")) for r in ledger))
        _sheet("Net Worth Ledger", COLUMNS, rows, [
            ("Total Credits", credits),
            ("Total Debits", debits),
            ("Net", _r(credits - debits)),
            ("Rows", len(rows)),
        ])

    online = await vendor_sales_ledger(
        section="all", date_from=date_from, date_to=date_to, order_id=order_id,
        limit=1000, vendor=vendor,
    )
    if not sale_type or sale_type == "online":
        cols = ["Order ID", "Customer", "Payment Method", "Item Amount", "Delivery Charge",
                "Wallet", "Online", "COD", "Vendor Credit", "Treasury Deduction",
                "Settlement Status", "Razorpay Payment ID", "Transaction ID", "Status", "Date/Time"]
        for key, label in (("cod", "Sales · COD"), ("wallet", "Sales · Wallet"), ("online", "Sales · Online")):
            block = online.get(key) or {}
            _sheet(label, cols, [[
                r.get("order_number"), r.get("customer"), r.get("payment_method"),
                r.get("item_amount"), r.get("delivery_charge"), r.get("wallet_amount"),
                r.get("online_amount"), r.get("cod_amount"), r.get("vendor_credit"),
                r.get("treasury_deduction"), r.get("settlement_status"),
                r.get("razorpay_payment_id"), r.get("transaction_id"),
                r.get("status"), r.get("created_at"),
            ] for r in (block.get("rows") or [])], [
                ("Item Amount", block.get("item_amount", 0)),
                ("Delivery Charge", block.get("delivery_charge", 0)),
                ("Rows", block.get("count", 0)),
            ])

    if not sale_type or sale_type == "returns":
        rblock = online.get("returns") or {}
        _sheet("Return Items", [
            "Original Order ID", "Return ID", "Product", "Qty", "Original Amount",
            "Refund Amount", "Original Payment Method", "Vendor Debit", "Customer Credit",
            "Inventory Restored", "Transaction ID", "Status", "Date/Time",
        ], [[
            r.get("original_order_number"), r.get("return_number"), r.get("product"),
            r.get("qty"), r.get("original_amount"), r.get("refund_amount"),
            r.get("original_payment_method"), r.get("vendor_debit"), r.get("customer_credit"),
            "Yes" if r.get("inventory_restored") else "No", r.get("transaction_id"),
            r.get("status"), r.get("created_at"),
        ] for r in (rblock.get("rows") or [])], [
            ("Original Amount", rblock.get("original_amount", 0)),
            ("Refund Amount", rblock.get("refund_amount", 0)),
            ("Rows", rblock.get("count", 0)),
        ])

    if not sale_type or sale_type == "offline":
        off = await vendor_offline_ledger(
            mode="all", date_from=date_from, date_to=date_to, limit=1000, vendor=vendor,
        )
        cols = ["Sale ID", "Reference", "Product", "Qty", "Amount", "GST", "Profit",
                "Payment Mode", "Payment Status", "Customer", "Net Worth Impact", "Date/Time"]
        for key, label in (("cash", "Offline · Cash"), ("upi", "Offline · UPI"), ("card", "Offline · Card")):
            block = off.get(key) or {}
            if not (block.get("rows") or []):
                continue
            _sheet(label, cols, [[
                r.get("sale_id"), r.get("reference"), r.get("product"), r.get("qty"),
                r.get("amount"), r.get("gst"), r.get("profit"), r.get("payment_mode"),
                r.get("payment_status"), r.get("customer"), r.get("net_worth_impact"),
                r.get("created_at"),
            ] for r in block["rows"]], [
                ("Amount", block.get("amount", 0)),
                ("GST", block.get("gst", 0)),
                ("Rows", block.get("count", 0)),
            ])

    nw = await vendor_net_worth(vendor=vendor)
    _sheet("Reconciliation", ["Item", "Amount"], [
        ["Opening (ledger)", nw["breakdown"]["opening"]],
        ["Sales", nw["breakdown"]["sales"]],
        ["Sale reversals", -nw["breakdown"]["sale_reversals"]],
        ["Delivery charges paid", -nw["breakdown"]["delivery_charges"]],
        ["Delivery charges returned", nw["breakdown"]["delivery_charge_reversals"]],
        ["Refunds paid", -nw["breakdown"]["refunds"]],
        ["Withdrawals", -nw["breakdown"]["withdrawals"]],
        ["Withdrawals returned (rejected)", nw["breakdown"]["withdrawal_reversals"]],
        ["Transaction fees", -nw["breakdown"]["transaction_fees"]],
        ["Transaction fees returned", nw["breakdown"]["transaction_fee_refunds"]],
        ["Cashback funded", -nw["breakdown"]["cashback_funded"]],
        ["Cashback funding returned", nw["breakdown"]["cashback_funding_returned"]],
        ["Recovered by Slangcart", -nw["breakdown"]["recoveries"]],
        ["Adjustments", nw["breakdown"]["adjustments"]],
        ["Other", nw["breakdown"]["other"]],
        ["= Ledger balance", nw["ledger_balance"]],
        ["Stored available balance", nw["available_balance"]],
        ["Difference", nw["unledgered_difference"]],
        ["Pending withdrawals", nw["pending_withdrawals"]],
        ["COD cash to collect", nw["pending_balance"]],
        ["Balanced", "YES" if nw["in_sync"] else "NO"],
    ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    stamp = now_utc().strftime("%Y%m%d-%H%M")
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="slangcart-networth-{stamp}.xlsx"'},
    )


# ── 5. Product pricing / profit (GST engine, vendor-private) ───────────

@router.get("/gst/compute")
async def compute_gst(
    base: float = Query(..., ge=0),
    pct: float = Query(0, ge=0, le=100),
    qty: float = Query(1, gt=0),
    inclusive: bool = True,
    _user: Dict[str, Any] = Depends(require_vendor_or_admin),
):
    """THE GST calculator, exposed so no screen ever does its own maths.

    Vendor/admin only — buyers never price anything, so they never need it.

    Defaults to INCLUSIVE: `base` is treated as the final price and the tax
    is pulled out of it, which is how the whole app prices things. Pass
    `inclusive=false` only for an explicit add-on-top quote.
    """
    if inclusive:
        return gst_engine.split_inclusive(base, pct, qty=qty)
    return gst_engine.split_gst(base, pct, qty=qty)


@router.get("/vendor/me/products/{product_id}/pricing")
async def product_pricing(product_id: str, vendor: Dict[str, Any] = Depends(require_vendor)):
    p = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    if p.get("vendor_id") != vendor["id"]:
        raise HTTPException(status_code=403, detail="Not your product")
    return {"product_id": product_id, "name": p.get("name"), **gst_engine.pricing_block(p)}


@router.get("/vendor/me/profit-report")
async def profit_report(vendor: Dict[str, Any] = Depends(require_vendor), limit: int = 500):
    """Profit per unit and potential stock profit across the catalogue —
    vendor-private, always from the one GST engine."""
    rows = await db.products.find(
        {"vendor_id": vendor["id"]},
        {"_id": 0, "id": 1, "name": 1, "price": 1, "stock": 1, "cashback_pct": 1,
         "cashback_flat": 1, "purchase_price": 1, "purchase_gst_pct": 1, "selling_gst_pct": 1},
    ).limit(max(1, min(int(limit or 500), 2000))).to_list(2000)
    items = []
    for p in rows:
        block = gst_engine.pricing_block(p)
        items.append({
            "product_id": p.get("id"),
            "name": p.get("name"),
            # Purchase and selling are the FINAL, GST-inclusive prices the
            # vendor typed; the base/GST split is what sits inside them.
            "purchase_total": block["purchase"]["final_amount"],
            "purchase_base": block["purchase"]["base_amount"],
            "purchase_gst": block["purchase"]["total_gst"],
            "selling_total": block["selling"]["final_amount"],
            "selling_base": block["selling"]["base_amount"],
            "selling_gst": block["selling"]["total_gst"],
            "cashback_mode": block["cashback"]["mode"],
            "cashback_pct": block["cashback"]["pct"],
            "cashback_amount": block["cashback"]["amount"],
            "gross_profit_per_unit": block["gross_profit_per_unit"],
            "profit_per_unit": block["profit_per_unit"],
            "margin_pct": block["margin_pct"],
            "stock": block["stock"],
            "potential_stock_profit": block["potential_stock_profit"],
            "has_purchase_price": block["has_purchase_price"],
        })
    priced = [i for i in items if i["has_purchase_price"]]
    return {
        "items": items,
        "total": len(items),
        "priced_count": len(priced),
        "missing_purchase_price": len(items) - len(priced),
        "total_potential_profit": _r(sum(i["potential_stock_profit"] for i in priced)),
        "tax_basis": "gst_inclusive",
    }
