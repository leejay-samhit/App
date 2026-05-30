"""Advanced Admin Finance & Accounting routes.

Created 2026-05-30 to power the multi-group System Wallet redesign:

  Group 1 — Revenue ledger
  Group 2 — User liability wallet
  Group 3 — GST ledger
  Group 4 — Platform fee ledger
  Group 5 — Expense ledger (NEW collection: db.expenses)
  Group 6 — Pending withdrawal wallet
  Group 7 — Bank ledger (NEW collection: db.bank_ledger)
  Master — Net-worth reconciliation formula

Plus:
  * Human-friendly TXN-NNNNNN display IDs (counter doc + helper)
  * Transaction REVERSE + ADJUST (never delete)
  * CSV exports for full ledger / expenses / bank

All endpoints require admin auth; mutating ones require super_admin role.
"""
from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from core.db import db
from core.security import require_admin, require_admin_role
from core.utils import now_utc, audit_log as _audit_log


router = APIRouter()


# ────────────────────────────────────────────────────────────────────
# TXN-NNNNNN sequential ID generator (Group A — Transaction Ledger)
# ────────────────────────────────────────────────────────────────────
async def next_txn_display_id() -> str:
    """Atomically increment a counter and return a TXN-NNNNNN string.

    The counter is stored in `db.counters` (doc id `txn_seq`). Starting
    value is 100_000 so the first emitted ID is `TXN-100001`.
    """
    res = await db.counters.find_one_and_update(
        {"_id": "txn_seq"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,  # type: ignore
    )
    base = 100_000
    seq = int((res or {}).get("seq") or 1) + base
    return f"TXN-{seq:06d}"


async def extract_client_audit(request: Request) -> Dict[str, Any]:
    """Pull IP / device_id / user_agent off the request headers. Frontend
    sends `X-Device-Id` explicitly; IP comes from `X-Forwarded-For` (proxy)
    or remote socket. Safe to call on every authenticated route."""
    ip = (
        request.headers.get("x-forwarded-for")
        or request.headers.get("x-real-ip")
        or (request.client.host if request.client else "")
    )
    if ip and "," in ip:
        ip = ip.split(",")[0].strip()
    return {
        "ip":         ip or None,
        "device_id":  request.headers.get("x-device-id") or None,
        "user_agent": request.headers.get("user-agent") or None,
    }


# ────────────────────────────────────────────────────────────────────
# Master Net-Worth reconciliation
# ────────────────────────────────────────────────────────────────────
@router.get("/admin/finance/net-worth")
async def admin_finance_net_worth(_: Dict[str, Any] = Depends(require_admin)):
    """Master reconciliation formula:

        net_worth =
              bank_balance
            + pending_collections
            − user_liability
            − pending_withdrawals
            − gst_payable

    Group readouts are computed from existing collections so no data
    migration is required.
    """
    # ── Group 1 — Revenue Ledger ──────────────────────────────────────
    reg_inflow_agg = await db.transactions.aggregate([
        {"$match": {"type": {"$in": ["registration_inflow", "direct_signup_credit"]}, "status": "success"}},
        {"$group": {"_id": None, "sum": {"$sum": "$gross_amount"}}},
    ]).to_list(1)
    registration_revenue = float((reg_inflow_agg or [{}])[0].get("sum") or 0)

    service_rev_agg = await db.transactions.aggregate([
        {"$match": {"type": {"$in": ["phone_reveal_invoice", "service_request_fee"]}, "status": "success"}},
        {"$group": {"_id": None, "sum": {"$sum": "$amount"}}},
    ]).to_list(1)
    service_revenue = float((service_rev_agg or [{}])[0].get("sum") or 0)

    pf_agg = await db.transactions.aggregate([
        {"$match": {"type": "platform_fee_collected", "status": "success"}},
        {"$group": {"_id": None, "sum": {"$sum": "$amount"}}},
    ]).to_list(1)
    platform_fee_revenue = float((pf_agg or [{}])[0].get("sum") or 0)

    shop_rev_agg = await db.transactions.aggregate([
        {"$match": {"type": {"$in": ["shop_purchase", "shop_revenue"]}, "status": "success"}},
        {"$group": {"_id": None, "sum": {"$sum": "$amount"}}},
    ]).to_list(1)
    shop_revenue = float((shop_rev_agg or [{}])[0].get("sum") or 0)

    gross_revenue = round(
        registration_revenue + service_revenue + platform_fee_revenue + shop_revenue,
        2,
    )

    # ── Group 2 — User Liability Wallet ───────────────────────────────
    rewards_agg = await db.users.aggregate([
        {"$match": {"role": {"$ne": "admin"}}},
        {"$group": {"_id": None, "sum": {"$sum": "$total_earned"}}},
    ]).to_list(1)
    total_reward_credits = float((rewards_agg or [{}])[0].get("sum") or 0)

    withdrawn_agg = await db.withdrawals.aggregate([
        {"$match": {"status": {"$in": ["approved", "paid", "completed"]}}},
        {"$group": {"_id": None, "sum": {"$sum": "$amount"}}},
    ]).to_list(1)
    total_withdrawals_settled = float((withdrawn_agg or [{}])[0].get("sum") or 0)

    user_balance_agg = await db.users.aggregate([
        {"$match": {"role": {"$ne": "admin"}}},
        {"$group": {"_id": None, "sum": {"$sum": "$wallet_balance"}}},
    ]).to_list(1)
    user_wallet_balance = float((user_balance_agg or [{}])[0].get("sum") or 0)

    # ── Group 3 — GST Ledger ──────────────────────────────────────────
    gst_collected_agg = await db.transactions.aggregate([
        {"$match": {"type": "gst_collected", "status": "success"}},
        {"$group": {"_id": None, "sum": {"$sum": "$amount"}}},
    ]).to_list(1)
    gst_collected = float((gst_collected_agg or [{}])[0].get("sum") or 0)

    gst_paid_agg = await db.expenses.aggregate([
        {"$match": {"category": "gst_paid", "status": "approved"}},
        {"$group": {"_id": None, "sum": {"$sum": "$amount"}}},
    ]).to_list(1)
    gst_paid = float((gst_paid_agg or [{}])[0].get("sum") or 0)

    gst_payable = round(gst_collected - gst_paid, 2)

    # ── Group 5 — Expenses ────────────────────────────────────────────
    exp_agg = await db.expenses.aggregate([
        {"$match": {"status": "approved"}},
        {"$group": {"_id": None, "sum": {"$sum": "$amount"}}},
    ]).to_list(1)
    total_expenses = float((exp_agg or [{}])[0].get("sum") or 0)

    # ── Group 6 — Pending withdrawals ─────────────────────────────────
    pw_agg = await db.withdrawals.aggregate([
        {"$match": {"status": "pending"}},
        {"$group": {"_id": None, "sum": {"$sum": "$amount"}}},
    ]).to_list(1)
    pending_withdrawals = float((pw_agg or [{}])[0].get("sum") or 0)

    # ── Group 7 — Bank Ledger ─────────────────────────────────────────
    bank_in = await db.bank_ledger.aggregate([
        {"$match": {"kind": "credit"}},
        {"$group": {"_id": None, "sum": {"$sum": "$amount"}}},
    ]).to_list(1)
    bank_credits = float((bank_in or [{}])[0].get("sum") or 0)

    bank_out = await db.bank_ledger.aggregate([
        {"$match": {"kind": "debit"}},
        {"$group": {"_id": None, "sum": {"$sum": "$amount"}}},
    ]).to_list(1)
    bank_debits = float((bank_out or [{}])[0].get("sum") or 0)

    bank_balance = round(bank_credits - bank_debits, 2)

    # Pending collections = Razorpay-initiated payments not yet captured
    pending_collections_agg = await db.transactions.aggregate([
        {"$match": {"type": "registration_inflow", "status": "pending"}},
        {"$group": {"_id": None, "sum": {"$sum": "$amount"}}},
    ]).to_list(1)
    pending_collections = float((pending_collections_agg or [{}])[0].get("sum") or 0)

    net_worth = round(
        bank_balance + pending_collections - user_wallet_balance - pending_withdrawals - gst_payable,
        2,
    )

    return {
        "group_1_revenue": {
            "registration": round(registration_revenue, 2),
            "service":      round(service_revenue, 2),
            "platform_fee": round(platform_fee_revenue, 2),
            "shop":         round(shop_revenue, 2),
            "gross":        gross_revenue,
        },
        "group_2_liability": {
            "total_reward_credits":       round(total_reward_credits, 2),
            "total_withdrawals_settled":  round(total_withdrawals_settled, 2),
            "available_user_balance":     round(user_wallet_balance, 2),
        },
        "group_3_gst": {
            "collected": round(gst_collected, 2),
            "paid":      round(gst_paid, 2),
            "payable":   gst_payable,
        },
        "group_4_platform_fee": {
            "collected": round(platform_fee_revenue, 2),
        },
        "group_5_expenses": {
            "total": round(total_expenses, 2),
        },
        "group_6_pending_withdrawals": {
            "pending_amount": round(pending_withdrawals, 2),
        },
        "group_7_bank": {
            "credits": round(bank_credits, 2),
            "debits":  round(bank_debits, 2),
            "balance": bank_balance,
        },
        "master": {
            "pending_collections": round(pending_collections, 2),
            "net_worth":           net_worth,
            "formula":             "bank + pending - liability - pending_withdrawals - gst_payable",
        },
        "generated_at": now_utc().isoformat(),
    }


# ────────────────────────────────────────────────────────────────────
# Reverse / Adjust transactions (never delete)
# ────────────────────────────────────────────────────────────────────
@router.post("/admin/transactions/{txn_id}/reverse")
async def reverse_transaction(
    txn_id: str,
    request: Request,
    payload: Dict[str, Any] | None = None,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    """Create a reversing transaction that nets the original to zero.

    Both txns are flagged with `reversed_by` / `reverses` so the audit
    trail remains intact. The original is NEVER deleted.
    """
    payload = payload or {}
    original = await db.transactions.find_one({"id": txn_id})
    if not original:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if original.get("reversed_by") or original.get("reverses"):
        raise HTTPException(status_code=400, detail="Transaction already reversed (or is itself a reversal)")
    reason = (payload.get("reason") or "").strip()
    if len(reason) < 4:
        raise HTTPException(status_code=400, detail="Reason is required (≥ 4 chars)")

    rev_id = str(uuid.uuid4())
    display = await next_txn_display_id()
    audit = await extract_client_audit(request)
    reverse_doc = {
        "id": rev_id,
        "display_id": display,
        "user_id": original.get("user_id"),
        "type": "reversal",
        "original_txn_id": original["id"],
        "original_type": original.get("type"),
        "amount": -float(original.get("amount") or 0),
        "gross_amount": -float(original.get("gross_amount") or 0) if original.get("gross_amount") is not None else None,
        "status": "success",
        "description": f"REVERSAL of {original.get('display_id') or original['id']}: {reason}",
        "reverses": original["id"],
        "reason": reason,
        "created_at": now_utc().isoformat(),
        "created_by_admin": admin["id"],
        **audit,
    }
    await db.transactions.insert_one(reverse_doc)
    await db.transactions.update_one(
        {"id": original["id"]},
        {"$set": {"reversed_by": rev_id, "reversed_at": now_utc().isoformat()}},
    )
    await _audit_log(admin, "transaction.reverse", "transaction", original["id"], {
        "reverse_id": rev_id, "reason": reason, "amount": original.get("amount"),
    })
    reverse_doc.pop("_id", None)
    return {"ok": True, "reversal": reverse_doc}


@router.post("/admin/transactions/adjust")
async def adjust_transaction(
    request: Request,
    payload: Dict[str, Any],
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    """Create a manual ADJUSTMENT entry without referencing a prior txn.

    Body:
        user_id: str            (target wallet — usually admin's own id)
        amount: float           (positive = credit, negative = debit)
        category: str           (e.g. "correction", "writeoff", "topup")
        description: str
        bucket: str (optional)  (which admin bucket to touch if user is admin)
    """
    user_id    = (payload.get("user_id") or "").strip()
    amount     = float(payload.get("amount") or 0)
    category   = (payload.get("category") or "correction").strip()
    description = (payload.get("description") or "").strip()
    if not user_id or amount == 0 or not description:
        raise HTTPException(status_code=400, detail="user_id, amount, description are all required")
    if not await db.users.find_one({"id": user_id}):
        raise HTTPException(status_code=404, detail="User not found")
    audit = await extract_client_audit(request)
    display = await next_txn_display_id()
    doc = {
        "id": str(uuid.uuid4()),
        "display_id": display,
        "user_id": user_id,
        "type": "adjustment",
        "category": category,
        "amount": amount,
        "status": "success",
        "description": f"ADJUST · {description}",
        "created_at": now_utc().isoformat(),
        "created_by_admin": admin["id"],
        **audit,
    }
    await db.transactions.insert_one(doc)
    await _audit_log(admin, "transaction.adjust", "transaction", doc["id"], {
        "amount": amount, "category": category, "description": description,
    })
    doc.pop("_id", None)
    return {"ok": True, "adjustment": doc}


# ────────────────────────────────────────────────────────────────────
# Expense Ledger CRUD (Group 5)
# ────────────────────────────────────────────────────────────────────
DEFAULT_EXPENSE_CATEGORIES = [
    "server_hosting", "sms_charges", "whatsapp_api", "staff_salary",
    "marketing", "legal_fees", "office_expenses", "payment_gateway",
    "refunds", "gst_paid", "other",
]


@router.get("/admin/expenses/categories")
async def list_expense_categories(_: Dict[str, Any] = Depends(require_admin)):
    custom = await db.expense_categories.find({}, {"_id": 0}).to_list(200)
    seen = {c["slug"] for c in custom if isinstance(c, dict)}
    seeded = [{"slug": s, "name": s.replace("_", " ").title(), "default": True} for s in DEFAULT_EXPENSE_CATEGORIES if s not in seen]
    return {"items": seeded + custom}


@router.get("/admin/expenses")
async def list_expenses(
    status: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 200,
    _: Dict[str, Any] = Depends(require_admin),
):
    filt: Dict[str, Any] = {}
    if status:   filt["status"] = status
    if category: filt["category"] = category
    rows = await db.expenses.find(filt, {"_id": 0}).sort("created_at", -1).to_list(max(1, min(limit, 1000)))
    return {"items": rows, "total": len(rows)}


@router.post("/admin/expenses")
async def create_expense(
    request: Request,
    payload: Dict[str, Any],
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "manager")),
):
    amount = float(payload.get("amount") or 0)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="amount must be > 0")
    category = (payload.get("category") or "other").strip()
    description = (payload.get("description") or "").strip()
    if not description:
        raise HTTPException(status_code=400, detail="description required")
    audit = await extract_client_audit(request)
    doc = {
        "id":          str(uuid.uuid4()),
        "display_id":  await next_txn_display_id(),
        "category":    category,
        "amount":      amount,
        "description": description,
        "vendor":      (payload.get("vendor") or "").strip()[:80] or None,
        "utr":         (payload.get("utr") or "").strip()[:40] or None,
        "reference":   (payload.get("reference") or "").strip()[:60] or None,
        "incurred_at": (payload.get("incurred_at") or now_utc().isoformat()),
        "status":      "approved",  # super_admin can directly approve; managers create as pending in v2
        "created_at":  now_utc().isoformat(),
        "created_by_admin": admin["id"],
        **audit,
    }
    await db.expenses.insert_one(doc)
    await _audit_log(admin, "expense.create", "expense", doc["id"], {
        "amount": amount, "category": category,
    })
    doc.pop("_id", None)
    return {"ok": True, "expense": doc}


@router.delete("/admin/expenses/{expense_id}")
async def delete_expense(
    expense_id: str,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    """Soft-delete: mark as void rather than removing (audit trail)."""
    exp = await db.expenses.find_one({"id": expense_id})
    if not exp:
        raise HTTPException(status_code=404, detail="Not found")
    await db.expenses.update_one(
        {"id": expense_id},
        {"$set": {"status": "void", "voided_at": now_utc().isoformat(), "voided_by": admin["id"]}},
    )
    await _audit_log(admin, "expense.void", "expense", expense_id, {})
    return {"ok": True}


# ────────────────────────────────────────────────────────────────────
# Bank Ledger CRUD (Group 7)
# ────────────────────────────────────────────────────────────────────
@router.get("/admin/bank-ledger")
async def list_bank_ledger(
    limit: int = 200,
    _: Dict[str, Any] = Depends(require_admin),
):
    rows = await db.bank_ledger.find({}, {"_id": 0}).sort("happened_at", -1).to_list(max(1, min(limit, 1000)))
    cr = sum(float(r.get("amount") or 0) for r in rows if r.get("kind") == "credit")
    dr = sum(float(r.get("amount") or 0) for r in rows if r.get("kind") == "debit")
    return {
        "items": rows, "total": len(rows),
        "credits": round(cr, 2), "debits": round(dr, 2), "balance": round(cr - dr, 2),
    }


@router.post("/admin/bank-ledger")
async def add_bank_entry(
    request: Request,
    payload: Dict[str, Any],
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "manager")),
):
    kind = (payload.get("kind") or "").strip().lower()
    if kind not in ("credit", "debit"):
        raise HTTPException(status_code=400, detail="kind must be 'credit' or 'debit'")
    amount = float(payload.get("amount") or 0)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="amount must be > 0")
    description = (payload.get("description") or "").strip()
    if not description:
        raise HTTPException(status_code=400, detail="description required")
    audit = await extract_client_audit(request)
    doc = {
        "id":          str(uuid.uuid4()),
        "display_id":  await next_txn_display_id(),
        "kind":        kind,
        "amount":      amount,
        "description": description,
        "utr":         (payload.get("utr") or "").strip()[:40] or None,
        "bank":        (payload.get("bank") or "").strip()[:60] or None,
        "happened_at": (payload.get("happened_at") or now_utc().isoformat()),
        "category":    (payload.get("category") or "general").strip(),
        "created_at":  now_utc().isoformat(),
        "created_by_admin": admin["id"],
        **audit,
    }
    await db.bank_ledger.insert_one(doc)
    await _audit_log(admin, f"bank.{kind}", "bank_ledger", doc["id"], {"amount": amount})
    doc.pop("_id", None)
    return {"ok": True, "entry": doc}


# ────────────────────────────────────────────────────────────────────
# CSV Exports (Step 4)
# ────────────────────────────────────────────────────────────────────
def _csv_stream(rows: list, fields: list) -> StreamingResponse:
    def gen():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(fields)
        for r in rows:
            w.writerow([r.get(f, "") for f in fields])
        buf.seek(0)
        yield buf.read()
    return StreamingResponse(
        gen(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="export-{now_utc().strftime("%Y%m%d-%H%M%S")}.csv"'},
    )


@router.get("/admin/finance/export/transactions")
async def export_transactions(
    days: int = 90,
    _: Dict[str, Any] = Depends(require_admin),
):
    cutoff = (now_utc() - timedelta(days=max(1, days))).isoformat()
    rows = await db.transactions.find(
        {"created_at": {"$gte": cutoff}}, {"_id": 0}
    ).sort("created_at", -1).to_list(20000)
    fields = [
        "display_id", "id", "type", "level", "amount", "gross_amount", "gst_amount",
        "platform_fee_amount", "status", "user_id", "source_user_name", "reference_number",
        "description", "ip", "device_id", "created_at",
    ]
    return _csv_stream(rows, fields)


@router.get("/admin/finance/export/expenses")
async def export_expenses(_: Dict[str, Any] = Depends(require_admin)):
    rows = await db.expenses.find({}, {"_id": 0}).sort("created_at", -1).to_list(20000)
    fields = ["display_id", "category", "amount", "vendor", "utr", "reference",
              "description", "status", "incurred_at", "created_at"]
    return _csv_stream(rows, fields)


@router.get("/admin/finance/export/bank")
async def export_bank(_: Dict[str, Any] = Depends(require_admin)):
    rows = await db.bank_ledger.find({}, {"_id": 0}).sort("happened_at", -1).to_list(20000)
    fields = ["display_id", "kind", "amount", "bank", "utr", "category",
              "description", "happened_at", "created_at"]
    return _csv_stream(rows, fields)
