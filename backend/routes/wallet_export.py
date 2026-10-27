"""Admin → Wallet / Treasury → Group-wise Excel export.

One authoritative source: `db.transactions`. Every figure in the workbook is
summed from the same ledger the admin dashboard reads, so the totals reconcile
exactly for identical filters. No row is ever emitted twice — each transaction
belongs to exactly ONE group (first match in `GROUPS` order wins).

Columns are the owner's spec, including separate Date / Time / Date-Time
columns and the permanent short IDs from `core/seq_ids.py`.
"""
import io
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from core.db import db
from core.security import require_admin
from core.seq_ids import get_many
from core.utils import now_utc

logger = logging.getLogger(__name__)
router = APIRouter()

IST = timezone(timedelta(hours=5, minutes=30))

# ── GROUP DEFINITIONS ───────────────────────────────────────────────────
# key → (label, txn types). Evaluated top-down, so a transaction lands in
# the FIRST group that claims its type. That is what guarantees "no
# duplicate transactions" across the group sheets.
GROUPS: List[Tuple[str, str, List[str]]] = [
    ("cashback",            "Cashback",                 ["cashback_credit"]),
    ("pending_cashback",    "Pending Cashback",         ["cashback_pending"]),
    ("cashback_reversal",   "Cashback Reversals",       ["cashback_reversal", "cashback_funding_refund"]),
    ("vendor_cashback_fund","Vendor Cashback Funding",  ["cashback_funding"]),
    ("vendor_outstanding",  "Vendor Outstanding",       ["cashback_platform_funded", "vendor_outstanding", "cashback_vendor_recovery", "cashback_recovery", "advance_recovery"]),
    ("delivery_charges",    "Delivery Charges",         ["delivery_charge_collected", "delivery_charge_reversal", "delivery_charge_paid", "dp_delivery_commission"]),
    ("customer_add_money",  "Customer Add Money",       ["wallet_topup", "add_money", "razorpay_topup"]),
    ("razorpay",            "Razorpay Payments",        ["registration_fee", "razorpay_payment", "direct_signup_credit"]),
    ("cod",                 "COD",                      ["cod_collected", "cod_order", "dp_cash_collected", "dp_cash_remitted", "dp_cash_paid_from_wallet", "vendor_cod_self_collected"]),
    ("orders",              "Order Payments",           ["order", "purchase", "order_payment", "order_payment_upi"]),
    ("refunds",             "Refunds",                  ["refund", "return_refund_debit", "return_refund_credit", "refund_company_funded", "withdrawal_refund", "payment_reconciliation_refund"]),
    ("reversals",           "Reversals",                ["shop_commission_reversal", "service_commission_reversal", "platform_fee_reversal", "reversal", "vendor_sale_reversal", "refund_clawback", "mlm_cutover_reversal", "mlm_cutover_reclaim"]),
    ("vendor_settlement",   "Vendor Settlement",        ["vendor_sale", "vendor_payout", "withdrawal", "withdrawal_hold", "withdrawal_transaction_fee",
                                                 "withdrawal_transaction_fee_refund",
                                                 "vendor_adjustment_credit", "vendor_adjustment_debit"]),
    ("gst",                 "GST",                       ["gst_collected"]),
    ("treasury",            "Slangcart Treasury",       ["system_deposit", "admin_credit", "admin_debit", "fee_residual", "l1_funding", "shop_commission", "service_commission", "shopping_margin", "service_margin", "platform_fee_collected", "expense"]),
    # Jun-2026 — mobile / DTH recharge money has its own sheet so the owner
    # can tie every top-up to the number that was recharged.
    ("recharge",            "Recharge",                 ["recharge", "recharge_payment_upi"]),
    ("legacy_referral",     "Legacy Referral (closed)", ["referral_payout", "cascade_overflow"]),
]

GROUP_LABELS: Dict[str, str] = {k: label for k, label, _ in GROUPS}
GROUP_TYPES: Dict[str, List[str]] = {k: types for k, _, types in GROUPS}
_TYPE_TO_GROUP: Dict[str, str] = {}
for _k, _l, _types in GROUPS:
    for _t in _types:
        _TYPE_TO_GROUP.setdefault(_t, _k)

# Wallet-owner grouping (who the money sits with), used by the
# Customer/Vendor/Admin Wallet sheets.
WALLET_GROUPS = ("customer_wallet", "vendor_wallet", "admin_wallet")

COLUMNS = [
    "Transaction ID", "Date", "Time", "Date / Time", "Transaction Group",
    "Transaction Type", "Customer/Vendor", "Shop", "Order ID", "Payment ID",
    "Source Wallet", "Destination Wallet", "Debit", "Credit", "Amount",
    "Previous Balance", "New Balance", "Cashback %", "Cashback Amount",
    "Delivery Charge", "GST", "Settlement Status", "Payment Method",
    "Reference ID", "Remarks",
]


def group_of(txn_type: str) -> str:
    return _TYPE_TO_GROUP.get(txn_type or "", "treasury")


def _ist(iso: str) -> Optional[datetime]:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST)


def _date_cell(iso: str) -> str:
    dt = _ist(iso)
    return dt.strftime("%d/%m/%Y") if dt else ""


def _time_cell(iso: str) -> str:
    dt = _ist(iso)
    if not dt:
        return ""
    # "10:51PM" — owner's format, no date.
    return dt.strftime("%I:%M%p").lstrip("0")


def _datetime_cell(iso: str) -> str:
    d, t = _date_cell(iso), _time_cell(iso)
    return f"{d} {t}".strip()


async def _build_query(
    date_from: Optional[str], date_to: Optional[str],
    group: Optional[str], txn_type: Optional[str],
    customer: Optional[str], vendor: Optional[str],
    order_id: Optional[str], payment_id: Optional[str],
    status: Optional[str],
) -> Dict[str, Any]:
    q: Dict[str, Any] = {}
    if date_from or date_to:
        rng: Dict[str, str] = {}
        if date_from:
            rng["$gte"] = date_from
        if date_to:
            # inclusive end-of-day
            rng["$lte"] = f"{date_to}T23:59:59.999999"
        q["created_at"] = rng
    if txn_type:
        q["type"] = txn_type
    elif group and group in GROUP_TYPES:
        q["type"] = {"$in": GROUP_TYPES[group]}
    if status:
        q["status"] = status
    if order_id:
        q["order_id"] = order_id
    if payment_id:
        q["$or"] = [
            {"razorpay_payment_id": payment_id},
            {"payment_id": payment_id},
            {"reference_number": payment_id},
        ]
    # Customer / vendor filters accept an id, an email or a name fragment.
    people_ids: List[str] = []
    for needle, extra in ((customer, {}), (vendor, {"is_vendor": True})):
        if not needle:
            continue
        matched = await db.users.find(
            {"$and": [
                extra or {},
                {"$or": [
                    {"id": needle},
                    {"email": needle.lower()},
                    {"name": {"$regex": needle, "$options": "i"}},
                    {"store_name": {"$regex": needle, "$options": "i"}},
                ]},
            ]},
            {"_id": 0, "id": 1},
        ).to_list(500)
        people_ids.extend([m["id"] for m in matched])
    if (customer or vendor) and not people_ids:
        q["user_id"] = "__no_match__"
    elif people_ids:
        q["user_id"] = {"$in": list(dict.fromkeys(people_ids))}
    return q


async def _load_rows(query: Dict[str, Any], cap: int) -> List[Dict[str, Any]]:
    return await db.transactions.find(query, {"_id": 0}).sort("created_at", 1).limit(cap).to_list(cap)


async def _decorate(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Attach short IDs and people/shop names in bulk."""
    txn_codes = await get_many("txn", [r.get("id") for r in rows])
    order_codes = await get_many("order", [r.get("order_id") for r in rows if r.get("order_id")])

    user_ids = {r.get("user_id") for r in rows if r.get("user_id")}
    vendor_ids = {r.get("vendor_id") for r in rows if r.get("vendor_id")}
    people: Dict[str, Dict[str, Any]] = {}
    ids = list(user_ids | vendor_ids)
    if ids:
        async for u in db.users.find(
            {"id": {"$in": ids}},
            {"_id": 0, "id": 1, "name": 1, "email": 1, "role": 1,
             "is_vendor": 1, "store_name": 1, "shop_name": 1},
        ):
            people[u["id"]] = u
    cust_codes = await get_many(
        "customer",
        [u["id"] for u in people.values() if not u.get("is_vendor") and u.get("role") != "admin"],
    )
    vend_codes = await get_many("vendor", [u["id"] for u in people.values() if u.get("is_vendor")])
    shop_codes = await get_many("shop", [u["id"] for u in people.values() if u.get("is_vendor")])

    out: List[Dict[str, Any]] = []
    for r in rows:
        owner = people.get(r.get("user_id") or "") or {}
        vend = people.get(r.get("vendor_id") or "") or owner if r.get("vendor_id") else owner
        is_vendor_row = bool(vend.get("is_vendor"))
        is_admin_row = (owner.get("role") == "admin")
        amount = float(r.get("amount") or 0)
        # Jun-2026 — ledger rows written by core.shop_money carry explicit
        # credit/debit columns and ALWAYS store `amount` as a positive
        # magnitude. Reading only the sign of `amount` therefore showed every
        # wallet DEBIT (delivery fee, cashback recovery, withdrawal hold,
        # return refund) as a credit in the Excel report. Credit/debit win
        # whenever they are present; legacy rows keep the signed behaviour.
        c_col = float(r.get("credit") or 0)
        d_col = float(r.get("debit") or 0)
        has_cols = bool(c_col or d_col)
        signed = round(c_col - d_col, 2) if has_cols else round(amount, 2)
        party_code = (
            vend_codes.get(vend.get("id") or "")
            if is_vendor_row else cust_codes.get(owner.get("id") or "")
        )
        party_name = owner.get("name") or owner.get("email") or ""
        if is_admin_row:
            party_code = "ADMIN"
        wallet_group = (
            "admin_wallet" if is_admin_row
            else "vendor_wallet" if is_vendor_row
            else "customer_wallet"
        )
        out.append({
            **r,
            "_short_id": txn_codes.get(r.get("id") or "", ""),
            "_order_short": order_codes.get(r.get("order_id") or "", ""),
            "_party": f"{party_code} · {party_name}".strip(" ·") if party_code else party_name,
            "_shop": (
                f"{shop_codes.get(vend.get('id') or '', '')} · "
                f"{vend.get('store_name') or vend.get('shop_name') or ''}".strip(" ·")
                if is_vendor_row else ""
            ),
            "_group": group_of(r.get("type") or ""),
            "_wallet_group": wallet_group,
            "_debit": round(d_col, 2) if has_cols else (round(abs(amount), 2) if amount < 0 else 0.0),
            "_credit": round(c_col, 2) if has_cols else (round(amount, 2) if amount > 0 else 0.0),
            "_amount": signed,
        })
    return out


def _row_cells(r: Dict[str, Any]) -> List[Any]:
    created = r.get("created_at") or ""
    amount = float(r.get("_amount") if r.get("_amount") is not None else (r.get("amount") or 0))
    return [
        r.get("_short_id") or "",
        _date_cell(created),
        _time_cell(created),
        _datetime_cell(created),
        GROUP_LABELS.get(r.get("_group") or "", r.get("_group") or ""),
        r.get("type") or "",
        r.get("_party") or "",
        r.get("_shop") or "",
        r.get("_order_short") or "",
        r.get("razorpay_payment_id") or r.get("payment_id") or "",
        r.get("source_wallet") or ("customer" if amount < 0 else ""),
        r.get("destination_wallet") or ("customer" if amount > 0 else ""),
        r.get("_debit") or 0,
        r.get("_credit") or 0,
        round(amount, 2),
        r.get("previous_balance") if r.get("previous_balance") is not None else "",
        r.get("new_balance") if r.get("new_balance") is not None else "",
        r.get("cashback_pct") if r.get("cashback_pct") is not None else "",
        r.get("cashback_amount") if r.get("cashback_amount") is not None else "",
        r.get("delivery_charge") if r.get("delivery_charge") is not None else "",
        r.get("gst_amount") if r.get("gst_amount") is not None else "",
        r.get("status") or "",
        r.get("paid_via") or r.get("payment_method") or "",
        r.get("reference_number") or r.get("id") or "",
        (r.get("description") or "")[:400],
    ]


@router.get("/admin/wallet/export/groupwise")
async def export_groupwise(
    _: Dict[str, Any] = Depends(require_admin),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    group: Optional[str] = None,
    txn_type: Optional[str] = None,
    customer: Optional[str] = None,
    vendor: Optional[str] = None,
    order_id: Optional[str] = None,
    payment_id: Optional[str] = None,
    status: Optional[str] = None,
    cap: int = 50_000,
):
    """Streamed .xlsx: one sheet per transaction group plus the three wallet
    sheets, each with a Group Summary block (opening / credits / debits /
    net / count / closing)."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    cap = max(1, min(cap, 200_000))
    query = await _build_query(
        date_from, date_to, group, txn_type, customer, vendor,
        order_id, payment_id, status,
    )
    rows = await _decorate(await _load_rows(query, cap))

    # Opening balance = everything BEFORE the window, same other filters.
    opening_by_group: Dict[str, float] = {}
    if date_from:
        pre_query = dict(query)
        pre_query["created_at"] = {"$lt": date_from}
        for pre in await _decorate(await _load_rows(pre_query, cap)):
            k = pre["_group"]
            opening_by_group[k] = round(opening_by_group.get(k, 0.0) + float(pre.get("_amount") or 0), 2)
            wk = pre["_wallet_group"]
            opening_by_group[wk] = round(opening_by_group.get(wk, 0.0) + float(pre.get("_amount") or 0), 2)

    wb = Workbook(write_only=False)
    wb.remove(wb.active)

    head_font = Font(bold=True, color="FFFFFF", size=10)
    head_fill = PatternFill("solid", fgColor="143D2E")
    sum_font = Font(bold=True, size=10)
    sum_fill = PatternFill("solid", fgColor="F3F1EC")

    def _sheet(title: str, sheet_rows: List[Dict[str, Any]], opening: float) -> None:
        ws = wb.create_sheet(title[:31])
        ws.append(COLUMNS)
        for i, _ in enumerate(COLUMNS, start=1):
            c = ws.cell(row=1, column=i)
            c.font = head_font
            c.fill = head_fill
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for r in sheet_rows:
            ws.append(_row_cells(r))

        credits = round(sum(float(r.get("_credit") or 0) for r in sheet_rows), 2)
        debits = round(sum(float(r.get("_debit") or 0) for r in sheet_rows), 2)
        net = round(credits - debits, 2)
        start = ws.max_row + 2
        summary = [
            ("GROUP SUMMARY", ""),
            ("Opening Balance", round(opening, 2)),
            ("Total Credits", credits),
            ("Total Debits", debits),
            ("Net Amount", net),
            ("Transaction Count", len(sheet_rows)),
            ("Closing Balance", round(opening + net, 2)),
        ]
        for i, (label, value) in enumerate(summary):
            ws.cell(row=start + i, column=1, value=label).font = sum_font
            ws.cell(row=start + i, column=1).fill = sum_fill
            cell = ws.cell(row=start + i, column=2, value=value)
            cell.font = sum_font
            cell.fill = sum_fill

        widths = [14, 12, 11, 20, 22, 22, 28, 24, 12, 20, 16, 18, 12, 12, 12, 16, 14, 11, 15, 15, 10, 16, 16, 22, 48]
        for i, w in enumerate(widths[:len(COLUMNS)], start=1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = "A2"

    # ── ALL sheet first (everything the filters matched, exactly once) ──
    _sheet("All Transactions", rows, sum(opening_by_group.get(k, 0.0) for k, _, _ in GROUPS))

    # ── Wallet-owner sheets ────────────────────────────────────────────
    for wk, label in (
        ("customer_wallet", "Customer Wallet"),
        ("vendor_wallet", "Vendor Wallet"),
        ("admin_wallet", "Admin Wallet"),
    ):
        subset = [r for r in rows if r["_wallet_group"] == wk]
        if subset:
            _sheet(label, subset, opening_by_group.get(wk, 0.0))

    # ── One sheet per transaction group ────────────────────────────────
    for key, label, _types in GROUPS:
        subset = [r for r in rows if r["_group"] == key]
        if subset:
            _sheet(label, subset, opening_by_group.get(key, 0.0))

    # ── Receivables sheet (Jun-2026) ───────────────────────────────────
    # What sellers still owe the treasury — the cashback we paid shoppers on
    # their behalf and any refund the company advanced. The total here is the
    # SAME figure as Receivables on System Wallet → Company net worth, so the
    # workbook and the screen can never disagree.
    rec_rows: List[Dict[str, Any]] = []
    # Oct 2026 — only the kinds the company actually PAID OUT are receivable.
    # An open `return_refund` row is a refund the SELLER still owes the
    # shopper (the company never advanced it), so counting it here inflated
    # the workbook's receivables above the API's figure. Those rows are
    # listed separately, below the total, further down this sheet.
    async for row in db.vendor_outstanding.find(
        {
            "status": "open",
            "kind": {"$in": ["return_refund_company_funded", "delivery_fee_company_funded", "delivery_fee"]},
        },
        {"_id": 0},
    ):
        owed = round(float(row.get("amount") or 0) - float(row.get("recovered") or 0), 2)
        if owed <= 0.009:
            continue
        rec_rows.append({
            "shop": row.get("vendor_name") or row.get("vendor_id"),
            "kind": row.get("kind"),
            "order": row.get("order_number") or row.get("order_id") or row.get("return_id") or "",
            "amount": round(float(row.get("amount") or 0), 2),
            "recovered": round(float(row.get("recovered") or 0), 2),
            "owed": owed,
            "since": row.get("created_at"),
            "note": row.get("description") or row.get("reason") or "",
        })
    # Refunds a SELLER still owes a shopper. The company never advanced this
    # money, so it is NOT a receivable and is excluded from the total above —
    # but it creates no wallet transaction either, so without this block it
    # would appear nowhere in the workbook at all.
    pending_refund_rows: List[Dict[str, Any]] = []
    async for row in db.vendor_outstanding.find(
        {"status": "open", "kind": {"$nin": [
            "return_refund_company_funded", "delivery_fee_company_funded", "delivery_fee",
        ]}},
        {"_id": 0},
    ):
        owed = round(float(row.get("amount") or 0) - float(row.get("recovered") or 0), 2)
        if owed <= 0.009:
            continue
        pending_refund_rows.append({
            "shop": row.get("vendor_name") or row.get("vendor_id"),
            "kind": row.get("kind"),
            "order": row.get("order_number") or row.get("order_id") or row.get("return_id") or "",
            "owed": owed,
            "since": row.get("created_at"),
            "note": row.get("description") or row.get("reason") or "",
        })

    cb_rows: List[Dict[str, Any]] = []
    async for v in db.users.find(
        {"cashback_outstanding": {"$gt": 0.009}},
        {"_id": 0, "id": 1, "vendor_business_name": 1, "name": 1,
         "cashback_outstanding": 1, "vendor_earnings": 1},
    ):
        cb_rows.append({
            "shop": v.get("vendor_business_name") or v.get("name") or v["id"],
            "owed": round(float(v.get("cashback_outstanding") or 0), 2),
            "wallet": round(float(v.get("vendor_earnings") or 0), 2),
        })

    ws = wb.create_sheet("Receivables")
    ws.append(["RECEIVABLES — what sellers owe the System Wallet treasury"])
    ws.cell(row=1, column=1).font = sum_font
    ws.append([])
    ws.append(["Cashback owed by sellers (paid to shoppers on their behalf)"])
    ws.cell(row=ws.max_row, column=1).font = head_font
    ws.append(["Shop", "Owed", "Their wallet balance", "Recoverable now"])
    for i in range(1, 5):
        c = ws.cell(row=ws.max_row, column=i)
        c.font = head_font
        c.fill = head_fill
    for r in cb_rows:
        ws.append([r["shop"], r["owed"], r["wallet"], round(min(r["owed"], r["wallet"]), 2)])
    ws.append(["TOTAL", round(sum(r["owed"] for r in cb_rows), 2), "", ""])
    ws.cell(row=ws.max_row, column=1).font = sum_font
    ws.cell(row=ws.max_row, column=2).font = sum_font

    ws.append([])
    ws.append(["Other advances (refunds / fees the company paid for a seller)"])
    ws.cell(row=ws.max_row, column=1).font = head_font
    ws.append(["Shop", "Kind", "Reference", "Amount", "Recovered", "Still owed", "Since", "Remarks"])
    for i in range(1, 9):
        c = ws.cell(row=ws.max_row, column=i)
        c.font = head_font
        c.fill = head_fill
    for r in rec_rows:
        if r["kind"] == "cashback":
            continue
        ws.append([r["shop"], r["kind"], r["order"], r["amount"], r["recovered"],
                   r["owed"], r["since"], r["note"]])
    ws.append(["TOTAL", "", "", "", "",
               round(sum(r["owed"] for r in rec_rows if r["kind"] != "cashback"), 2), "", ""])
    ws.cell(row=ws.max_row, column=1).font = sum_font
    ws.cell(row=ws.max_row, column=6).font = sum_font
    ws.append([])
    ws.append(["RECEIVABLES TOTAL (in Company net worth)",
               round(sum(r["owed"] for r in cb_rows)
                     + sum(r["owed"] for r in rec_rows if r["kind"] != "cashback"), 2)])
    ws.cell(row=ws.max_row, column=1).font = sum_font
    ws.cell(row=ws.max_row, column=2).font = sum_font

    # Informational only — deliberately BELOW the total and never added to it.
    # Parking a refund creates no wallet transaction, so without this block
    # the money a seller owes a shopper would appear nowhere in the workbook.
    if pending_refund_rows:
        ws.append([])
        ws.append(["NOT a receivable — refunds a seller still owes a shopper (the company never paid these)"])
        ws.cell(row=ws.max_row, column=1).font = head_font
        ws.append(["Shop", "Owed to shopper", "Kind", "Order / return", "Since", "Remarks"])
        for i in range(1, 7):
            c = ws.cell(row=ws.max_row, column=i)
            c.font = head_font
            c.fill = head_fill
        for r in pending_refund_rows:
            ws.append([r["shop"], r["owed"], r["kind"], r["order"], r["since"], r["note"]])
        ws.append(["TOTAL awaiting the seller's wallet (excluded from receivables)",
                   round(sum(r["owed"] for r in pending_refund_rows), 2)])
        ws.cell(row=ws.max_row, column=1).font = sum_font
        ws.cell(row=ws.max_row, column=2).font = sum_font
    for i, w in enumerate([34, 16, 24, 14, 14, 14, 24, 60], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    stamp = now_utc().strftime("%Y%m%d-%H%M")
    name = f"slangcart-wallet-{group or 'all'}-{stamp}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/admin/wallet/groupwise-summary")
async def groupwise_summary(
    _: Dict[str, Any] = Depends(require_admin),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    group: Optional[str] = None,
    txn_type: Optional[str] = None,
    customer: Optional[str] = None,
    vendor: Optional[str] = None,
    order_id: Optional[str] = None,
    payment_id: Optional[str] = None,
    status: Optional[str] = None,
    cap: int = 50_000,
):
    """The same numbers the workbook will contain — so the admin screen and
    the download can be verified to match before anyone opens Excel."""
    query = await _build_query(
        date_from, date_to, group, txn_type, customer, vendor,
        order_id, payment_id, status,
    )
    rows = await _decorate(await _load_rows(query, max(1, min(cap, 200_000))))
    buckets: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        slot = buckets.setdefault(r["_group"], {
            "key": r["_group"],
            "label": GROUP_LABELS.get(r["_group"], r["_group"]),
            "credits": 0.0, "debits": 0.0, "count": 0,
        })
        slot["credits"] = round(slot["credits"] + float(r.get("_credit") or 0), 2)
        slot["debits"] = round(slot["debits"] + float(r.get("_debit") or 0), 2)
        slot["count"] += 1
    for slot in buckets.values():
        slot["net"] = round(slot["credits"] - slot["debits"], 2)
    return {
        "groups": sorted(buckets.values(), key=lambda x: -abs(x["net"])),
        "available_groups": [{"key": k, "label": label} for k, label, _ in GROUPS],
        "total": {
            "credits": round(sum(b["credits"] for b in buckets.values()), 2),
            "debits": round(sum(b["debits"] for b in buckets.values()), 2),
            "net": round(sum(b["net"] for b in buckets.values()), 2),
            "count": len(rows),
        },
        "truncated": len(rows) >= min(cap, 200_000),
    }


@router.get("/admin/short-id/{code}")
async def lookup_short_id(code: str, _: Dict[str, Any] = Depends(require_admin)):
    """Paste `TXNA125` (or ORD6, CUS3 …) and get the original record back."""
    from core.seq_ids import resolve

    row = await resolve(code)
    if not row:
        raise HTTPException(status_code=404, detail=f"No record found for {code}")
    kind, ref = row["kind"], row["ref_id"]
    coll_map = {
        "txn": ("transactions", "id"),
        "order": ("orders", "id"),
        "customer": ("users", "id"),
        "vendor": ("users", "id"),
        "shop": ("users", "id"),
        "cashback": ("cashback_ledger", "_id"),
        "refund": ("refund_requests", "id"),
        "delivery": ("withdrawals", "id"),
    }
    coll_name, field = coll_map.get(kind, (None, None))
    record = None
    if coll_name:
        proj = {"_id": 0, "password_hash": 0, "password_recovery_ciphertext": 0}
        record = await getattr(db, coll_name).find_one({field: ref}, proj)
    return {"code": row["code"], "kind": kind, "ref_id": ref, "record": record}


@router.post("/admin/short-id/backfill")
async def backfill_short_ids(_: Dict[str, Any] = Depends(require_admin)):
    """Assign permanent codes to all pre-existing records, in creation order.
    Idempotent — already-mapped rows are skipped."""
    from core.seq_ids import backfill, ensure_indexes

    await ensure_indexes()
    return {"ok": True, "minted": await backfill()}
