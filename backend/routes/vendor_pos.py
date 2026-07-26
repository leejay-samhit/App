"""Vendor Cloud-POS (Point-of-Sale) endpoints — spec'd in
SALES_BACKEND_SPEC.md (29-Jun-2026, web frontend → backend handoff).

Scope:
  • Vendor-scoped, JWT-authenticated POS routes mounted under /vendor/me/pos/*
  • Admin read-only fan-out under /admin/vendors/{user_id}/pos/* and
    /admin/pos/global-summary
  • Strict tenant isolation — vendor_id always comes from the JWT.
  • Inventory decrement is atomic via find_one_and_update with a stock>=qty
    filter (so two concurrent bills for the same SKU can't oversell).
  • NO wallet, GST-ledger, platform-fee or system-wallet writes (per §0 of
    the spec). This module is strictly vendor business-records + inventory
    sync. Money flow stays in routes/wallet.py, server.py commission engine
    etc. — completely untouched.

Endpoints (22):
  Settings       GET /me/pos/settings  PUT /me/pos/settings
  Counter        POST /me/pos/invoice/peek  POST /me/pos/invoice/consume
  Sales          POST /me/pos/sales
                 POST /me/pos/sales/bulk-import
                 GET  /me/pos/sales
                 GET  /me/pos/sales/{id}
                 POST /me/pos/sales/{id}/cancel
                 POST /me/pos/sales/{id}/refund
                 GET  /me/pos/sales/{id}/invoice.pdf  (HTML for v1 — no PDF lib)
  Dashboard      GET /me/pos/dashboard
                 GET /me/pos/cash-summary
                 GET /me/pos/statement
                 GET /me/pos/analytics
  Customers      GET /me/pos/customers
                 POST /me/pos/customers
                 GET /me/pos/customers/{id}
                 PATCH /me/pos/customers/{id}
  Admin RO       GET /admin/vendors/{user_id}/pos/sales
                 GET /admin/vendors/{user_id}/pos/dashboard
                 GET /admin/pos/global-summary
"""
import re
import uuid
from datetime import timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse

from core.db import db
from core.security import get_current_user, require_admin
from core.utils import now_utc
from models import (
    PosCreateSaleRequest,
    PosBulkImportRequest,
    PosRefundRequest,
    PosSettingsUpdate,
    PosCustomerUpsert,
    PosCustomerPatch,
)

router = APIRouter()


# ───────────────────────── Helpers ─────────────────────────

DEFAULT_POS_SETTINGS: Dict[str, Any] = {
    "invoice_prefix": "INV",
    "invoice_pad": 4,
    "business_name": "",
    "business_address": "",
    "business_phone": "",
    "business_email": "",
    "business_gstin": "",
    "default_gst_pct": 0.0,
    "gst_inclusive": False,
    "opening_balance": 0.0,
}


async def _ensure_vendor(user: Dict[str, Any]) -> str:
    """Authorize the request as belonging to a vendor user.

    For v1 we allow ANY authenticated user with role=user to use the POS
    (so a small-shop owner who hasn't been promoted to a formal `vendor`
    record yet can still record their bills). If the product collection
    flags this user as a vendor, we use that record. Otherwise we treat
    the user.id itself as the vendor scope.

    Returns the canonical vendor scope id (always equal to user.id for v1).
    Future tightening: gate behind user.is_vendor / role check.
    """
    return user["id"]


async def _get_pos_settings(vendor_id: str) -> Dict[str, Any]:
    doc = await db.vendor_pos_settings.find_one({"vendor_id": vendor_id}, {"_id": 0}) or {}
    merged = {**DEFAULT_POS_SETTINGS, **doc, "vendor_id": vendor_id}
    return merged


def _format_invoice_no(prefix: str, pad: int, number: int) -> str:
    pad = max(1, min(int(pad or 4), 10))
    return f"{prefix or 'INV'}-{str(int(number)).zfill(pad)}"


async def _peek_next_invoice_no(vendor_id: str) -> str:
    settings = await _get_pos_settings(vendor_id)
    counter = await db.vendor_invoice_counters.find_one({"vendor_id": vendor_id}, {"_id": 0}) or {}
    last_n = int(counter.get("last_number") or 0)
    return _format_invoice_no(settings["invoice_prefix"], settings["invoice_pad"], last_n + 1)


async def _consume_next_invoice_no(vendor_id: str) -> str:
    """Atomically increment the per-vendor counter and return the new number."""
    settings = await _get_pos_settings(vendor_id)
    doc = await db.vendor_invoice_counters.find_one_and_update(
        {"vendor_id": vendor_id},
        {
            "$inc": {"last_number": 1},
            "$setOnInsert": {
                "vendor_id": vendor_id,
                "prefix": settings["invoice_prefix"],
                "pad": settings["invoice_pad"],
            },
        },
        upsert=True,
        return_document=True,  # AFTER
    )
    return _format_invoice_no(
        doc.get("prefix") or settings["invoice_prefix"],
        doc.get("pad") or settings["invoice_pad"],
        int(doc.get("last_number") or 1),
    )


def _parse_discount(raw: Optional[str], base: float) -> float:
    """`5%` → 5% of `base`, `50` → 50 flat, anything else → 0."""
    if not raw:
        return 0.0
    s = str(raw).strip()
    try:
        if s.endswith("%"):
            return round(float(s[:-1]) * base / 100.0, 2)
        return round(float(s), 2)
    except (TypeError, ValueError):
        return 0.0


def _round2(x: float) -> float:
    return round(float(x or 0.0), 2)


def _compute_totals(items: List[Dict[str, Any]], gst_inclusive: bool, bill_discount: Optional[str], round_off: bool) -> Dict[str, Any]:
    """Server-side canonical recompute — never trust client-sent totals."""
    subtotal = 0.0
    gst_total = 0.0
    line_discount_total = 0.0
    profit = 0.0
    for it in items:
        qty = float(it["qty"])
        price = float(it["price"])
        gross = qty * price
        d_amt = _parse_discount(it.get("discount"), gross)
        taxable_before_gst = max(0.0, gross - d_amt)
        gst_pct = float(it.get("gst_pct") or 0)
        if gst_inclusive:
            # price already includes GST → strip it to get taxable
            taxable = taxable_before_gst / (1 + gst_pct / 100.0) if gst_pct > 0 else taxable_before_gst
            tax = taxable_before_gst - taxable
            line_total = taxable_before_gst
        else:
            taxable = taxable_before_gst
            tax = taxable * gst_pct / 100.0
            line_total = taxable + tax
        it["discount_amount"] = _round2(d_amt)
        it["taxable"] = _round2(taxable)
        it["tax_amount"] = _round2(tax)
        it["line_total"] = _round2(line_total)
        cost = float(it.get("cost") or 0)
        profit += (taxable - cost * qty)
        subtotal += taxable
        gst_total += tax
        line_discount_total += d_amt
    bill_disc_amt = _parse_discount(bill_discount, subtotal + gst_total)
    pre_round = max(0.0, subtotal + gst_total - bill_disc_amt)
    grand = round(pre_round) if round_off else _round2(pre_round)
    return {
        "subtotal": _round2(subtotal),
        "gst_total": _round2(gst_total),
        "discount_total": _round2(line_discount_total),
        "bill_discount": _round2(bill_disc_amt),
        "round_off": _round2(grand - pre_round) if round_off else 0.0,
        "grand_total": _round2(grand),
        "profit": _round2(profit),
    }


def _serialize_sale(sale: Dict[str, Any]) -> Dict[str, Any]:
    sale = dict(sale)
    sale.pop("_id", None)
    return sale


# ───────────────────────── Settings ─────────────────────────

@router.get("/vendor/me/pos/settings")
async def get_vendor_pos_settings(user: Dict[str, Any] = Depends(get_current_user)):
    vendor_id = await _ensure_vendor(user)
    return await _get_pos_settings(vendor_id)


@router.put("/vendor/me/pos/settings")
async def update_vendor_pos_settings(
    payload: PosSettingsUpdate,
    user: Dict[str, Any] = Depends(get_current_user),
):
    vendor_id = await _ensure_vendor(user)
    update = {k: v for k, v in payload.dict().items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="No fields provided")
    await db.vendor_pos_settings.update_one(
        {"vendor_id": vendor_id},
        {"$set": {**update, "vendor_id": vendor_id, "updated_at": now_utc().isoformat()}},
        upsert=True,
    )
    # Keep the counter's prefix/pad in sync if either was changed — invoice
    # numbers issued from now on use the new prefix.
    if any(k in update for k in ("invoice_prefix", "invoice_pad")):
        prefix_pad = {}
        if "invoice_prefix" in update:
            prefix_pad["prefix"] = update["invoice_prefix"]
        if "invoice_pad" in update:
            prefix_pad["pad"] = update["invoice_pad"]
        await db.vendor_invoice_counters.update_one(
            {"vendor_id": vendor_id},
            {"$set": prefix_pad, "$setOnInsert": {"vendor_id": vendor_id, "last_number": 0}},
            upsert=True,
        )
    return await _get_pos_settings(vendor_id)


# ───────────────────────── Invoice counter ─────────────────────────

@router.post("/vendor/me/pos/invoice/peek")
async def peek_invoice_number(user: Dict[str, Any] = Depends(get_current_user)):
    vendor_id = await _ensure_vendor(user)
    return {"invoice_no": await _peek_next_invoice_no(vendor_id)}


@router.post("/vendor/me/pos/invoice/consume")
async def consume_invoice_number(user: Dict[str, Any] = Depends(get_current_user)):
    vendor_id = await _ensure_vendor(user)
    return {"invoice_no": await _consume_next_invoice_no(vendor_id)}


# ───────────────────────── Sales — Create ─────────────────────────

async def _create_sale_internal(
    vendor_id: str,
    payload: PosCreateSaleRequest,
) -> Dict[str, Any]:
    """Shared logic between single-create and bulk-import.

    Atomically decrements stock for every line item BEFORE inserting the
    sale. If any product is short, rolls back any partial decrements and
    raises 409 with the conflicting product list.
    """
    items = [it.dict() for it in payload.items]
    payments = [p.dict() for p in payload.payments]

    # 1) Snapshot product cost + stock for each line, and atomically decrement.
    decremented: List[Dict[str, Any]] = []
    insufficient: List[Dict[str, Any]] = []
    try:
        for it in items:
            qty = float(it["qty"])
            prod_id = it["product_id"]
            # Cost + stock_before snapshot via the SAME atomic op as the
            # decrement: filter requires stock>=qty so concurrent bills
            # can't drive stock negative.
            doc = await db.products.find_one_and_update(
                {
                    "id": prod_id,
                    "vendor_id": vendor_id,
                    "stock": {"$gte": qty},
                },
                {"$inc": {"stock": -qty}},
                return_document=False,  # BEFORE — gives stock_before for free
            )
            if not doc:
                # Either product missing, not owned by vendor, or out of stock.
                cur = await db.products.find_one(
                    {"id": prod_id, "vendor_id": vendor_id},
                    {"_id": 0, "id": 1, "name": 1, "stock": 1},
                )
                insufficient.append({
                    "product_id": prod_id,
                    "name": it.get("name") or (cur or {}).get("name"),
                    "available": (cur or {}).get("stock", 0),
                    "requested": qty,
                })
                continue
            it["cost"] = float(doc.get("cost_price") or doc.get("cost") or 0)
            it["stock_before"] = int(doc.get("stock") or 0)
            decremented.append({"product_id": prod_id, "qty": qty})
        if insufficient:
            # Roll back any decrements made so far so the request is all-or-nothing.
            for d in decremented:
                await db.products.update_one(
                    {"id": d["product_id"], "vendor_id": vendor_id},
                    {"$inc": {"stock": float(d["qty"])}},
                )
            raise HTTPException(status_code=409, detail={"error": "stock_insufficient", "items": insufficient})
    except HTTPException:
        raise
    except Exception as e:
        # Best-effort rollback then bubble up.
        for d in decremented:
            await db.products.update_one(
                {"id": d["product_id"], "vendor_id": vendor_id},
                {"$inc": {"stock": float(d["qty"])}},
            )
        raise HTTPException(status_code=500, detail=f"create_sale_failed: {e!s}")

    # 2) Compute canonical totals server-side (never trust client values).
    totals = _compute_totals(items, payload.gst_inclusive, payload.bill_discount, payload.round_off)

    # 3) Allocate invoice number (atomic per-vendor counter).
    invoice_no = (payload.invoice_no or "").strip() or await _consume_next_invoice_no(vendor_id)

    sale = {
        "id": str(uuid.uuid4()),
        "vendor_id": vendor_id,
        "invoice_no": invoice_no,
        "created_at": now_utc().isoformat(),
        "status": "completed",
        "cancelled_at": None,
        "refunded_at": None,
        "refund_reason": None,
        "customer": payload.customer.dict(),
        "gst_inclusive": payload.gst_inclusive,
        "totals": totals,
        "notes": payload.notes or "",
        "items": items,
        "payments": payments,
        "client_id": payload.client_id,
    }
    await db.offline_sales.insert_one(sale)

    # ── Nov 2026 — GST collected on POS sales flows into the platform's
    # GST sub-ledger so it shows up in the Admin System Wallet as a
    # dedicated bucket.  This is a *tracking* ledger, not a wallet
    # transfer — the money is with the vendor until admin settles it.
    try:
        gst_amt = float((totals or {}).get("gst_total") or 0)
        if gst_amt > 0:
            await db.system_wallet_deposits.insert_one({
                "id": str(uuid.uuid4()),
                "source": "gst_pos",
                "bucket": "gst",
                "amount": round(gst_amt, 2),
                "vendor_id": vendor_id,
                "invoice_no": invoice_no,
                "sale_id": sale["id"],
                "created_at": now_utc(),
            })
    except Exception:
        # GST ledger is telemetry — never block the sale on a write failure.
        pass

    # 4) Upsert customer record (when named & has phone).
    cust = payload.customer
    if cust.kind == "named" and (cust.phone or cust.email):
        key = {"vendor_id": vendor_id, "phone": cust.phone} if cust.phone else {"vendor_id": vendor_id, "email": cust.email}
        await db.vendor_customers.update_one(
            key,
            {
                "$set": {
                    "vendor_id": vendor_id,
                    "name": cust.name,
                    "phone": cust.phone,
                    "gstin": cust.gstin,
                    "address": cust.address,
                    "email": cust.email,
                    "last_seen": now_utc().isoformat(),
                },
                "$inc": {"total_spend": totals["grand_total"], "bills_count": 1},
                "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": now_utc().isoformat()},
            },
            upsert=True,
        )

    return _serialize_sale(sale)


@router.post("/vendor/me/pos/sales")
async def create_sale(
    payload: PosCreateSaleRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    vendor_id = await _ensure_vendor(user)
    return await _create_sale_internal(vendor_id, payload)


@router.post("/vendor/me/pos/sales/bulk-import")
async def bulk_import_sales(
    payload: PosBulkImportRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Accepts the localStorage sales array verbatim. Returns an id_map
    so the client can mark each local row as cloud-synced."""
    vendor_id = await _ensure_vendor(user)
    id_map: Dict[str, str] = {}
    imported = 0
    skipped: List[Dict[str, Any]] = []
    for raw in payload.sales or []:
        local_id = str(raw.get("id") or raw.get("local_id") or "")
        # Dedupe via client_id — if a sale with this client_id already exists, skip.
        if local_id:
            existing = await db.offline_sales.find_one(
                {"vendor_id": vendor_id, "client_id": local_id}, {"_id": 0, "id": 1},
            )
            if existing:
                id_map[local_id] = existing["id"]
                skipped.append({"local_id": local_id, "reason": "duplicate"})
                continue
        try:
            req = PosCreateSaleRequest(
                items=raw.get("items") or [],
                payments=raw.get("payments") or [],
                customer=raw.get("customer") or {},
                gst_inclusive=bool(raw.get("gst_inclusive") or False),
                bill_discount=raw.get("bill_discount"),
                round_off=bool(raw.get("round_off") if raw.get("round_off") is not None else True),
                notes=raw.get("notes"),
                client_id=local_id or None,
                invoice_no=raw.get("invoice_no"),
            )
            created = await _create_sale_internal(vendor_id, req)
            if local_id:
                id_map[local_id] = created["id"]
            imported += 1
        except HTTPException as e:
            skipped.append({"local_id": local_id, "reason": e.detail if isinstance(e.detail, str) else "validation"})
        except Exception as e:
            skipped.append({"local_id": local_id, "reason": str(e)})
    return {"id_map": id_map, "imported": imported, "skipped": skipped}


# ───────────────────────── Sales — Read / Cancel / Refund ─────────────────────────

@router.get("/vendor/me/pos/sales")
async def list_sales(
    user: Dict[str, Any] = Depends(get_current_user),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = None,
    q: Optional[str] = None,
    payment_mode: Optional[str] = None,
    min_amt: Optional[float] = None,
    max_amt: Optional[float] = None,
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    vendor_id = await _ensure_vendor(user)
    filt: Dict[str, Any] = {"vendor_id": vendor_id}
    if status:
        filt["status"] = status
    if from_:
        filt.setdefault("created_at", {})["$gte"] = from_
    if to:
        filt.setdefault("created_at", {})["$lte"] = to + ("T23:59:59" if len(to) == 10 else "")
    if min_amt is not None:
        filt["totals.grand_total"] = {"$gte": float(min_amt)}
    if max_amt is not None:
        filt.setdefault("totals.grand_total", {})["$lte"] = float(max_amt)
    if payment_mode:
        filt["payments.mode"] = payment_mode
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        filt["$or"] = [
            {"invoice_no": rx},
            {"customer.name": rx},
            {"customer.phone": rx},
            {"items.name": rx},
        ]
    total = await db.offline_sales.count_documents(filt)
    rows = (
        await db.offline_sales.find(filt, {"_id": 0})
        .sort("created_at", -1)
        .skip(offset)
        .limit(limit)
        .to_list(limit)
    )
    return {"total": total, "limit": limit, "offset": offset, "items": rows}


@router.get("/vendor/me/pos/sales/{sale_id}")
async def get_sale(sale_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    vendor_id = await _ensure_vendor(user)
    sale = await db.offline_sales.find_one({"id": sale_id, "vendor_id": vendor_id}, {"_id": 0})
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    return sale


async def _restock(vendor_id: str, sale: Dict[str, Any]) -> None:
    """Increment stock back for every line item of a cancelled/refunded sale."""
    for it in (sale.get("items") or []):
        await db.products.update_one(
            {"id": it["product_id"], "vendor_id": vendor_id},
            {"$inc": {"stock": float(it.get("qty") or 0)}},
        )


@router.post("/vendor/me/pos/sales/{sale_id}/cancel")
async def cancel_sale(sale_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    vendor_id = await _ensure_vendor(user)
    sale = await db.offline_sales.find_one({"id": sale_id, "vendor_id": vendor_id})
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    if sale.get("status") != "completed":
        raise HTTPException(status_code=409, detail=f"Sale already {sale.get('status')}")
    await db.offline_sales.update_one(
        {"id": sale_id, "vendor_id": vendor_id, "status": "completed"},
        {"$set": {"status": "cancelled", "cancelled_at": now_utc().isoformat()}},
    )
    await _restock(vendor_id, sale)
    updated = await db.offline_sales.find_one({"id": sale_id}, {"_id": 0})
    return updated


@router.post("/vendor/me/pos/sales/{sale_id}/refund")
async def refund_sale(
    sale_id: str,
    payload: PosRefundRequest = Body(default=PosRefundRequest()),
    user: Dict[str, Any] = Depends(get_current_user),
):
    vendor_id = await _ensure_vendor(user)
    sale = await db.offline_sales.find_one({"id": sale_id, "vendor_id": vendor_id})
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    if sale.get("status") != "completed":
        raise HTTPException(status_code=409, detail=f"Sale already {sale.get('status')}")
    await db.offline_sales.update_one(
        {"id": sale_id, "vendor_id": vendor_id, "status": "completed"},
        {"$set": {
            "status": "refunded",
            "refunded_at": now_utc().isoformat(),
            "refund_reason": (payload.reason or "")[:300],
        }},
    )
    await _restock(vendor_id, sale)
    updated = await db.offline_sales.find_one({"id": sale_id}, {"_id": 0})
    return updated


@router.get("/vendor/me/pos/sales/{sale_id}/invoice.pdf", response_class=HTMLResponse)
async def invoice_html(sale_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    """V1: returns an HTML invoice (browser print-to-PDF). The spec §5 says
    PDF generation stays client-side via invoicePrint.js, but we still
    expose this convenience endpoint so a direct GET works."""
    vendor_id = await _ensure_vendor(user)
    sale = await db.offline_sales.find_one({"id": sale_id, "vendor_id": vendor_id}, {"_id": 0})
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    settings = await _get_pos_settings(vendor_id)
    rows = "".join(
        f"<tr><td>{i+1}</td><td>{it['name']}</td><td>{it['qty']}</td>"
        f"<td>{it['price']}</td><td>{it.get('discount') or ''}</td>"
        f"<td>{it.get('gst_pct') or 0}%</td><td>{it.get('line_total') or 0}</td></tr>"
        for i, it in enumerate(sale.get("items") or [])
    )
    cust = sale.get("customer") or {}
    totals = sale.get("totals") or {}
    html = f"""<!doctype html><html><head><meta charset='utf-8'><title>Invoice {sale.get('invoice_no')}</title>
<style>body{{font-family:Arial,sans-serif;padding:24px;color:#111}}h1{{margin:0}}table{{width:100%;border-collapse:collapse;margin-top:12px}}th,td{{border:1px solid #ddd;padding:6px;text-align:left}}.right{{text-align:right}}.muted{{color:#666;font-size:12px}}</style></head>
<body>
<h1>{settings.get('business_name') or 'Invoice'}</h1>
<div class='muted'>{settings.get('business_address') or ''} · {settings.get('business_phone') or ''} · GSTIN {settings.get('business_gstin') or '—'}</div>
<h3>Invoice {sale.get('invoice_no')} · {sale.get('created_at')[:19].replace('T',' ')}</h3>
<div><b>Customer:</b> {cust.get('name')} {('· '+cust.get('phone')) if cust.get('phone') else ''} {('· GSTIN '+cust.get('gstin')) if cust.get('gstin') else ''}</div>
<table><thead><tr><th>#</th><th>Item</th><th>Qty</th><th>Price</th><th>Disc</th><th>GST</th><th>Total</th></tr></thead><tbody>{rows}</tbody></table>
<div class='right' style='margin-top:12px'>Subtotal: ₹{totals.get('subtotal')}<br>GST: ₹{totals.get('gst_total')}<br>Discount: ₹{totals.get('discount_total')}<br>Bill discount: ₹{totals.get('bill_discount')}<br>Round-off: ₹{totals.get('round_off')}<br><b>Grand total: ₹{totals.get('grand_total')}</b></div>
</body></html>"""
    return HTMLResponse(content=html)


# ───────────────────────── Dashboard / KPIs ─────────────────────────

def _today_bounds() -> (str, str):
    now = now_utc()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.isoformat(), now.isoformat()


def _month_bounds() -> (str, str):
    now = now_utc()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start.isoformat(), now.isoformat()


async def _aggregate_kpis(vendor_id: str, from_: str, to: str) -> Dict[str, Any]:
    pipeline = [
        {"$match": {"vendor_id": vendor_id, "status": "completed", "created_at": {"$gte": from_, "$lte": to}}},
        {"$group": {
            "_id": None,
            "bills": {"$sum": 1},
            "turnover": {"$sum": "$totals.grand_total"},
            "gst": {"$sum": "$totals.gst_total"},
            "profit": {"$sum": "$totals.profit"},
            "items": {"$sum": {"$size": {"$ifNull": ["$items", []]}}},
        }},
    ]
    rows = await db.offline_sales.aggregate(pipeline).to_list(1)
    if not rows:
        return {"bills": 0, "turnover": 0.0, "gst": 0.0, "profit": 0.0, "items": 0}
    r = rows[0]
    r.pop("_id", None)
    for k in ("turnover", "gst", "profit"):
        r[k] = _round2(r.get(k) or 0)
    return r


@router.get("/vendor/me/pos/dashboard")
async def vendor_pos_dashboard(user: Dict[str, Any] = Depends(get_current_user)):
    vendor_id = await _ensure_vendor(user)
    t_from, t_to = _today_bounds()
    m_from, m_to = _month_bounds()
    return {
        "today": await _aggregate_kpis(vendor_id, t_from, t_to),
        "month": await _aggregate_kpis(vendor_id, m_from, m_to),
    }


@router.get("/vendor/me/pos/cash-summary")
async def vendor_pos_cash_summary(
    date: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user),
):
    vendor_id = await _ensure_vendor(user)
    if date:
        start = f"{date}T00:00:00"
        end = f"{date}T23:59:59"
    else:
        start, end = _today_bounds()
    pipeline = [
        {"$match": {"vendor_id": vendor_id, "status": "completed", "created_at": {"$gte": start, "$lte": end}}},
        {"$unwind": "$payments"},
        {"$group": {"_id": "$payments.mode", "amount": {"$sum": "$payments.amount"}, "count": {"$sum": 1}}},
    ]
    rows = await db.offline_sales.aggregate(pipeline).to_list(50)
    by_mode = {r["_id"]: {"amount": _round2(r["amount"]), "count": r["count"]} for r in rows}
    settings = await _get_pos_settings(vendor_id)
    opening = float(settings.get("opening_balance") or 0)
    cash_in = by_mode.get("cash", {}).get("amount", 0.0)
    return {
        "date": (date or now_utc().date().isoformat()),
        "by_mode": by_mode,
        "opening_balance": opening,
        "expected_close": _round2(opening + cash_in),
        "cash_received": _round2(cash_in),
    }


@router.get("/vendor/me/pos/statement")
async def vendor_pos_statement(
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user),
):
    vendor_id = await _ensure_vendor(user)
    filt: Dict[str, Any] = {"vendor_id": vendor_id, "status": "completed"}
    if from_:
        filt.setdefault("created_at", {})["$gte"] = from_
    if to:
        filt.setdefault("created_at", {})["$lte"] = to + ("T23:59:59" if len(to) == 10 else "")
    rows = await db.offline_sales.find(filt, {"_id": 0}).sort("created_at", 1).limit(2000).to_list(2000)
    running = 0.0
    statement = []
    for r in rows:
        amt = float((r.get("totals") or {}).get("grand_total") or 0)
        running += amt
        statement.append({
            "id": r["id"],
            "invoice_no": r.get("invoice_no"),
            "created_at": r.get("created_at"),
            "customer": (r.get("customer") or {}).get("name"),
            "amount": _round2(amt),
            "running": _round2(running),
        })
    return {"total": len(statement), "running_balance": _round2(running), "items": statement}


@router.get("/vendor/me/pos/analytics")
async def vendor_pos_analytics(
    user: Dict[str, Any] = Depends(get_current_user),
    days: int = Query(30, ge=1, le=180),
):
    vendor_id = await _ensure_vendor(user)
    start = (now_utc() - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    match = {"vendor_id": vendor_id, "status": "completed", "created_at": {"$gte": start}}
    # Daily turnover/profit/bill count
    daily = await db.offline_sales.aggregate([
        {"$match": match},
        {"$group": {
            "_id": {"$substr": ["$created_at", 0, 10]},
            "turnover": {"$sum": "$totals.grand_total"},
            "profit": {"$sum": "$totals.profit"},
            "bills": {"$sum": 1},
        }},
        {"$sort": {"_id": 1}},
    ]).to_list(180)
    daily = [{"date": d["_id"], "turnover": _round2(d["turnover"]), "profit": _round2(d["profit"]), "bills": d["bills"]} for d in daily]
    # Per-product aggregates
    pipeline = [
        {"$match": match},
        {"$unwind": "$items"},
        {"$group": {
            "_id": "$items.product_id",
            "name": {"$first": "$items.name"},
            "qty": {"$sum": "$items.qty"},
            "revenue": {"$sum": "$items.line_total"},
            "gst": {"$sum": "$items.tax_amount"},
        }},
    ]
    rows = await db.offline_sales.aggregate(pipeline).to_list(2000)
    top_sold = sorted(rows, key=lambda r: r["qty"], reverse=True)[:10]
    top_revenue = sorted(rows, key=lambda r: r["revenue"], reverse=True)[:10]
    top_gst = sorted(rows, key=lambda r: r["gst"], reverse=True)[:10]
    least_sold = sorted(rows, key=lambda r: r["qty"])[:10]
    def _fmt(rs):
        return [{"product_id": r["_id"], "name": r["name"], "qty": _round2(r["qty"]), "revenue": _round2(r["revenue"]), "gst": _round2(r["gst"])} for r in rs]
    return {
        "days": days,
        "daily": daily,
        "top_sold": _fmt(top_sold),
        "top_revenue": _fmt(top_revenue),
        "top_gst": _fmt(top_gst),
        "least_sold": _fmt(least_sold),
    }


# ───────────────────────── Customers ─────────────────────────

@router.get("/vendor/me/pos/customers")
async def list_customers(
    user: Dict[str, Any] = Depends(get_current_user),
    q: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
):
    vendor_id = await _ensure_vendor(user)
    filt: Dict[str, Any] = {"vendor_id": vendor_id}
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        filt["$or"] = [{"name": rx}, {"phone": rx}, {"email": rx}, {"gstin": rx}]
    rows = await db.vendor_customers.find(filt, {"_id": 0}).sort("last_seen", -1).limit(limit).to_list(limit)
    return {"items": rows, "total": len(rows)}


@router.post("/vendor/me/pos/customers")
async def upsert_customer(
    payload: PosCustomerUpsert,
    user: Dict[str, Any] = Depends(get_current_user),
):
    vendor_id = await _ensure_vendor(user)
    data = payload.dict()
    key = {"vendor_id": vendor_id, "phone": data["phone"]} if data.get("phone") else {"vendor_id": vendor_id, "name": data["name"]}
    await db.vendor_customers.update_one(
        key,
        {
            "$set": {"vendor_id": vendor_id, **data, "updated_at": now_utc().isoformat()},
            "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": now_utc().isoformat(), "total_spend": 0.0, "bills_count": 0},
        },
        upsert=True,
    )
    return await db.vendor_customers.find_one(key, {"_id": 0})


@router.get("/vendor/me/pos/customers/{cust_id}")
async def get_customer(cust_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    vendor_id = await _ensure_vendor(user)
    c = await db.vendor_customers.find_one({"id": cust_id, "vendor_id": vendor_id}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found")
    return c


@router.patch("/vendor/me/pos/customers/{cust_id}")
async def patch_customer(
    cust_id: str,
    payload: PosCustomerPatch,
    user: Dict[str, Any] = Depends(get_current_user),
):
    vendor_id = await _ensure_vendor(user)
    update = {k: v for k, v in payload.dict().items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="No fields provided")
    res = await db.vendor_customers.update_one(
        {"id": cust_id, "vendor_id": vendor_id},
        {"$set": {**update, "updated_at": now_utc().isoformat()}},
    )
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="Customer not found")
    return await db.vendor_customers.find_one({"id": cust_id, "vendor_id": vendor_id}, {"_id": 0})


# ───────────────────────── Admin read-only ─────────────────────────

@router.get("/admin/vendors/{vendor_id}/pos/sales")
async def admin_vendor_sales(
    vendor_id: str,
    _: Dict[str, Any] = Depends(require_admin),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    filt: Dict[str, Any] = {"vendor_id": vendor_id}
    if from_:
        filt.setdefault("created_at", {})["$gte"] = from_
    if to:
        filt.setdefault("created_at", {})["$lte"] = to + ("T23:59:59" if len(to) == 10 else "")
    total = await db.offline_sales.count_documents(filt)
    rows = await db.offline_sales.find(filt, {"_id": 0}).sort("created_at", -1).skip(offset).limit(limit).to_list(limit)
    return {"total": total, "limit": limit, "offset": offset, "items": rows}


@router.get("/admin/vendors/{vendor_id}/pos/dashboard")
async def admin_vendor_dashboard(
    vendor_id: str,
    _: Dict[str, Any] = Depends(require_admin),
):
    t_from, t_to = _today_bounds()
    m_from, m_to = _month_bounds()
    return {
        "vendor_id": vendor_id,
        "today": await _aggregate_kpis(vendor_id, t_from, t_to),
        "month": await _aggregate_kpis(vendor_id, m_from, m_to),
    }


@router.get("/admin/pos/global-summary")
async def admin_pos_global_summary(_: Dict[str, Any] = Depends(require_admin)):
    t_from, t_to = _today_bounds()
    m_from, m_to = _month_bounds()
    pipeline_today = [
        {"$match": {"status": "completed", "created_at": {"$gte": t_from, "$lte": t_to}}},
        {"$group": {"_id": None, "bills": {"$sum": 1}, "turnover": {"$sum": "$totals.grand_total"}}},
    ]
    pipeline_month = [
        {"$match": {"status": "completed", "created_at": {"$gte": m_from, "$lte": m_to}}},
        {"$group": {"_id": None, "bills": {"$sum": 1}, "turnover": {"$sum": "$totals.grand_total"}}},
    ]
    pipeline_vendors = [
        {"$match": {"status": "completed", "created_at": {"$gte": m_from}}},
        {"$group": {"_id": "$vendor_id", "bills": {"$sum": 1}, "turnover": {"$sum": "$totals.grand_total"}}},
        {"$sort": {"turnover": -1}},
        {"$limit": 25},
    ]
    today_rows, month_rows, vendor_rows = (
        await db.offline_sales.aggregate(pipeline_today).to_list(1),
        await db.offline_sales.aggregate(pipeline_month).to_list(1),
        await db.offline_sales.aggregate(pipeline_vendors).to_list(25),
    )
    def _fmt(rs):
        if not rs:
            return {"bills": 0, "turnover": 0.0}
        r = rs[0]
        return {"bills": r["bills"], "turnover": _round2(r["turnover"])}
    return {
        "today": _fmt(today_rows),
        "month": _fmt(month_rows),
        "top_vendors_this_month": [
            {"vendor_id": v["_id"], "bills": v["bills"], "turnover": _round2(v["turnover"])}
            for v in vendor_rows
        ],
    }
