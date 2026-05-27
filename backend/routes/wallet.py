"""User wallet endpoints — transaction history + transaction detail + GST invoices.

Carved out of server.py during the Phase 2B modular refactor (2026-05-27).
Behaviour is identical to the previous in-server.py definitions; only the
file location changed. See server.py git history for the full evolution.

WHY THESE ENDPOINTS ARE TOGETHER
--------------------------------
They share the same "read a user's financial history" surface area:
  • /transactions/me               — paginated list
  • /transactions/{id}              — single row with counter-party enrichment
  • /transactions/{id}/invoice      — GST invoice HTML
  • /transactions/{id}/invoice.pdf  — GST invoice PDF

The WRITE endpoint /wallet/transfer is deliberately NOT moved here — it
touches _trigger_referral_commissions which still lives in server.py
(see TODO at the top of server.py — commission engine extraction is the
next refactor wave).
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import HTMLResponse

from core.db import db
from core.security import get_current_user
from invoices import (
    invoice_html as _build_invoice_html,
    invoice_pdf as _build_invoice_pdf,
    invoice_number_for as _invoice_number_for,
    is_invoiceable as _is_invoiceable,
)

router = APIRouter()


# ────────────────── /transactions/me ──────────────────
@router.get("/transactions/me")
async def my_transactions(
    user: Dict[str, Any] = Depends(get_current_user),
    include_pending: bool = False,
    limit: int = 0,
    offset: int = 0,
):
    """User wallet history. By default we hide pre-payment / failed registration
    rows (status in {created, failed}) so the wallet view shows only money that
    actually moved. Pass ?include_pending=true to see all rows for debugging.

    Pagination: opt-in via limit (1..200) + offset. Omit to get the legacy
    unbounded list (capped at 1000)."""
    q: Dict[str, Any] = {"user_id": user["id"]}
    if not include_pending:
        q["status"] = {"$nin": ["created", "failed"]}
    cursor = db.transactions.find(q, {"_id": 0}).sort("created_at", -1)
    if limit and limit > 0:
        cursor = cursor.skip(max(0, offset)).limit(min(limit, 200))
        return await cursor.to_list(min(limit, 200))
    return await cursor.to_list(1000)


# ────────────────── Helpers ──────────────────
def _auto_remarks_for(tx: Dict[str, Any]) -> str:
    """Generate a human-readable summary line for any transaction. Used by
    the transaction-detail modal so users always see context even if the
    underlying `description` is terse or absent (older rows).

    Returns a string suitable for direct rendering — already includes
    rupee sign, sign (+/-), and any counter-party / reference / level
    we can pull out of the txn doc."""
    t = (tx.get("type") or "").lower()
    amt = tx.get("amount") or 0
    sign = "+" if (amt or 0) >= 0 else "-"
    abs_amt = abs(float(amt or 0))
    src = tx.get("source_user_name") or ""
    ref = tx.get("reference_number") or ""
    lvl = tx.get("level")
    pretty = {
        "registration_fee": f"Registration fee paid · ₹{int(abs_amt)}",
        "referral_payout": f"Level {lvl} referral payout from {src or 'a downline member'} · {sign}₹{int(abs_amt)}",
        "service_booking": f"Service booking · {sign}₹{int(abs_amt)}{(' · ref ' + ref) if ref else ''}",
        "service_earning": f"Service earning · {sign}₹{int(abs_amt)}",
        "service_commission": f"Service platform fee from {src or 'customer'} · {sign}₹{int(abs_amt)}",
        "shop_commission": f"Shop margin from order {tx.get('order_id', '')[:8]} · {sign}₹{int(abs_amt)}",
        "vendor_sale": f"Vendor share · {sign}₹{int(abs_amt)}",
        "order": f"Shop order placed · {sign}₹{int(abs_amt)}",
        "admin_credit": tx.get("remarks") or f"Credit ₹{int(abs_amt)} from admin",
        "admin_debit": tx.get("remarks") or f"Debit ₹{int(abs_amt)} by admin",
        "system_deposit": f"System wallet top-up · UTR {ref or 'n/a'} · {sign}₹{int(abs_amt)}",
        "withdrawal": f"Withdrawal · {sign}₹{int(abs_amt)}{(' · UTR ' + ref) if ref else ''}",
    }
    return pretty.get(t, tx.get("description") or f"{t.replace('_', ' ').title()} · {sign}₹{int(abs_amt)}")


async def _resolve_invoice_data(txn_id: str, user: Dict[str, Any]):
    """Shared helper for both invoice HTML + PDF endpoints. Fetches the
    txn, enforces permissions, resolves owner/counter/branding. Raises
    HTTPException(404|403|400) on failure — the caller doesn't need to
    duplicate error handling."""
    tx = await db.transactions.find_one({"id": txn_id}, {"_id": 0})
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    is_owner = tx.get("user_id") == user["id"]
    is_admin_view = user.get("role") == "admin" and user.get("admin_role") in ("super_admin", "finance")
    if not is_owner and not is_admin_view:
        raise HTTPException(status_code=403, detail="Not allowed")
    if not _is_invoiceable(tx):
        raise HTTPException(status_code=400, detail="No invoice available for this transaction type")
    owner = await db.users.find_one(
        {"id": tx.get("user_id")},
        {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1, "referral_code": 1},
    )
    counter: Optional[Dict[str, Any]] = None
    if tx.get("from_admin_id"):
        counter = await db.users.find_one({"id": tx["from_admin_id"]}, {"_id": 0, "id": 1, "name": 1, "email": 1})
    elif tx.get("booking_id"):
        booking = await db.service_bookings.find_one({"id": tx["booking_id"]}, {"_id": 0})
        if booking:
            other_id = booking["provider_id"] if tx.get("user_id") == booking.get("customer_id") else booking.get("customer_id")
            counter = await db.users.find_one({"id": other_id}, {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1, "referral_code": 1})
    elif tx.get("order_id"):
        order = await db.orders.find_one({"id": tx["order_id"]}, {"_id": 0})
        if order and order.get("user_id") != tx.get("user_id"):
            counter = await db.users.find_one({"id": order.get("user_id")}, {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1, "referral_code": 1})
    branding_doc = await db.settings.find_one({"id": "branding"}, {"_id": 0}) or {}
    return tx, owner, counter, branding_doc


# ────────────────── /transactions/{txn_id} ──────────────────
@router.get("/transactions/{txn_id}")
async def transaction_detail(txn_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    """Return a single transaction with enriched counter-party info + auto-remarks.
    Visible to: the owning user, super_admin, manager, support, and finance roles."""
    tx = await db.transactions.find_one({"id": txn_id}, {"_id": 0})
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    is_owner = tx.get("user_id") == user["id"]
    is_admin_view = user.get("role") == "admin" and user.get("admin_role") in ("super_admin", "finance", "manager", "support")
    if not is_owner and not is_admin_view:
        raise HTTPException(status_code=403, detail="Not allowed")

    owner = await db.users.find_one({"id": tx.get("user_id")}, {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1, "referral_code": 1})

    counter: Optional[Dict[str, Any]] = None
    counter_role = ""
    if tx.get("from_admin_id"):
        c = await db.users.find_one({"id": tx["from_admin_id"]}, {"_id": 0, "id": 1, "name": 1, "email": 1, "admin_role": 1})
        if c:
            counter = c
            counter_role = "admin"
    elif tx.get("booking_id"):
        booking = await db.service_bookings.find_one({"id": tx["booking_id"]}, {"_id": 0})
        if booking:
            other_id = booking["provider_id"] if tx.get("user_id") == booking.get("customer_id") else booking.get("customer_id")
            other_role = "provider" if tx.get("user_id") == booking.get("customer_id") else "customer"
            c = await db.users.find_one({"id": other_id}, {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1, "referral_code": 1})
            if c:
                counter = c
                counter_role = other_role
    elif tx.get("order_id"):
        order = await db.orders.find_one({"id": tx["order_id"]}, {"_id": 0})
        if order and order.get("user_id") != tx.get("user_id"):
            c = await db.users.find_one({"id": order.get("user_id")}, {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1, "referral_code": 1})
            if c:
                counter = c
                counter_role = "buyer"

    return {
        "transaction": tx,
        "owner": owner,
        "counter_party": counter,
        "counter_role": counter_role,
        "auto_remarks": _auto_remarks_for(tx),
        "utr": tx.get("reference_number"),
        "invoice_number": _invoice_number_for(tx),
        "invoiceable": _is_invoiceable(tx),
    }


# ────────────────── GST invoices ──────────────────
@router.get("/transactions/{txn_id}/invoice", response_class=HTMLResponse)
async def transaction_invoice_html(txn_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    """HTML invoice — what the WebView modal in admin/system-wallet renders."""
    tx, owner, counter, branding = await _resolve_invoice_data(txn_id, user)
    html = _build_invoice_html(tx, owner, branding, counter)
    return HTMLResponse(content=html, status_code=200)


@router.get("/transactions/{txn_id}/invoice.pdf")
async def transaction_invoice_pdf(txn_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    """PDF invoice — downloaded via Linking.openURL from the FE."""
    tx, owner, counter, branding = await _resolve_invoice_data(txn_id, user)
    pdf_bytes = _build_invoice_pdf(tx, owner, branding, counter)
    inv_no = _invoice_number_for(tx).replace("/", "-")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{inv_no}.pdf"',
            "Cache-Control": "no-store",
        },
    )
