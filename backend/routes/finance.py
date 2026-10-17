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
from datetime import timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from core.db import db
from core.security import require_admin, require_admin_role
from core.utils import now_utc, audit_log as _audit_log
from core import shop_money
from core.config import ADMIN_EMAIL


router = APIRouter()

# System-wallet buckets an adjustment may be attributed to. Mirrors
# server.SYSTEM_WALLET_BUCKETS (imported lazily would create a cycle).
SYSTEM_WALLET_BUCKETS = (
    "referral_commission", "direct_signup", "fee_residual", "direct_added",
    "service_margin", "shopping_margin", "gst_collected", "platform_fee_collected",
    "delivery_collected", "cashback_funded",
)

# Entry-GST percentage on customer-facing joining fees (GST-inclusive math:
# ₹118 gross → ₹18 GST). Mirrors server.REFERRAL_GST_PCT.
GST_PCT = 18.0


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
    # FIX (2026-05-30): Use the canonical `registration_fee` type — same
    # logic as `/admin/system-wallet/breakdown`. This counts ALL 3 sources
    # (razorpay / upi_manual / offline_cash) in one shot.
    PAID = ["paid", "success", "approved"]

    async def _sum_amount(match: Dict[str, Any]) -> float:
        agg = await db.transactions.aggregate([
            {"$match": match},
            {"$group": {"_id": None, "sum": {"$sum": "$amount"}}},
        ]).to_list(1)
        return float((agg or [{}])[0].get("sum") or 0)

    reg_fee_total = await _sum_amount({"type": "registration_fee", "status": {"$in": PAID}})

    # Per-source breakdown so admin sees where the joinings came from.
    reg_by_source_agg = await db.transactions.aggregate([
        {"$match": {"type": "registration_fee", "status": {"$in": PAID}}},
        {"$lookup": {"from": "users", "localField": "user_id", "foreignField": "id", "as": "_u"}},
        {"$unwind": {"path": "$_u", "preserveNullAndEmptyArrays": True}},
        {"$group": {
            "_id": {"$ifNull": ["$_u.registration_source", "razorpay"]},
            "sum": {"$sum": "$amount"},
            "count": {"$sum": 1},
        }},
    ]).to_list(10)
    reg_by_source = {row["_id"] or "razorpay": {"amount": float(row["sum"] or 0), "count": int(row["count"] or 0)} for row in reg_by_source_agg}
    # Always surface the 3 expected sources even when count==0 so the UI
    # can render a stable 3-row breakdown.
    for s in ("razorpay", "upi_manual", "offline_cash"):
        reg_by_source.setdefault(s, {"amount": 0.0, "count": 0})

    # Reversals subtract from revenue. Reversal txns carry `original_type`
    # so we can attribute the credit-back to the correct group.
    async def _reversals_for(original_types: list) -> float:
        agg = await db.transactions.aggregate([
            {"$match": {"type": "reversal", "original_type": {"$in": original_types}, "status": "success"}},
            {"$group": {"_id": None, "sum": {"$sum": "$amount"}}},
        ]).to_list(1)
        # Reversal amounts are stored negative; flip to positive for subtraction.
        return abs(float((agg or [{}])[0].get("sum") or 0))

    reg_reversed = await _reversals_for(["registration_fee"])
    registration_revenue = reg_fee_total - reg_reversed

    service_rev_agg = await _sum_amount({
        "type": {"$in": ["service_margin", "service_commission", "phone_reveal_invoice", "service_request_fee"]},
        "status": {"$in": PAID},
    })
    service_reversed = await _sum_amount({"type": "service_commission_reversal", "status": "success"})
    service_revenue = service_rev_agg - abs(service_reversed)

    platform_fee_revenue = await _sum_amount({"type": "platform_fee_collected", "status": {"$in": PAID}})
    platform_fee_revenue -= await _reversals_for(["platform_fee_collected"])

    shop_rev_agg = await _sum_amount({
        "type": {"$in": ["shop_purchase", "shop_revenue", "shopping_margin", "shop_commission"]},
        "status": {"$in": PAID},
    })
    shop_reversed = await _sum_amount({"type": "shop_commission_reversal", "status": "success"})
    shop_revenue = shop_rev_agg - abs(shop_reversed)

    # Sep-2026 — DELIVERY CHARGE REVENUE (the only slice of a marketplace
    # order that is genuinely ours). Rows are written net of 18% GST by
    # `shop_money.settle_delivery_fee`; the GST half lands in Group 3.
    # Free-delivery orders write no row at all, so they correctly contribute
    # ₹0 revenue and ₹0 net worth.
    delivery_rev_agg = await _sum_amount({
        "type": "delivery_charge_collected", "status": {"$in": PAID},
    })
    delivery_reversed = await _sum_amount({"type": "delivery_revenue_reversal", "status": {"$in": PAID}})
    delivery_revenue = round(delivery_rev_agg - abs(delivery_reversed), 2)

    # Bug-fix · 2026-05-31: platform_fee_revenue is NOT external revenue —
    # it's the 18% withheld INTERNALLY when L1-L10 payouts fire. Adding it
    # to gross_revenue double-counted the same rupee in both Group 1
    # (revenue) AND Group 4 (platform fee), inflating the Bank Tally
    # inflow and the Company Net Worth.
    #
    # New gross_revenue = registration + service + shop (NO platform fee).
    # Group 4 still surfaces platform_fee_revenue as an informational
    # sub-bucket so admins can see what portion of payouts the platform
    # retained, but it no longer flows into the Bank Tally inflow.
    gross_revenue = round(
        registration_revenue + service_revenue + shop_revenue + delivery_revenue,
        2,
    )

    # ── Group 2 — User Liability Wallet ───────────────────────────────
    rewards_agg = await db.users.aggregate([
        {"$match": {"role": {"$ne": "admin"}}},
        {"$group": {"_id": None, "sum": {"$sum": "$total_earned"}}},
    ]).to_list(1)
    total_reward_credits = float((rewards_agg or [{}])[0].get("sum") or 0)

    # Settled withdrawals — `admin_complete_withdrawal` &
    # `admin_approve_and_complete_withdrawal` write status="success".
    # We also accept legacy statuses ("approved", "paid", "completed") in case
    # any historical row used those labels.
    SETTLED_WITHDRAWAL_STATUSES = ["success", "approved", "paid", "completed"]
    withdrawn_agg = await db.withdrawals.aggregate([
        {"$match": {"status": {"$in": SETTLED_WITHDRAWAL_STATUSES}}},
        {"$group": {"_id": None, "sum": {"$sum": "$amount"}}},
    ]).to_list(1)
    total_withdrawals_settled = float((withdrawn_agg or [{}])[0].get("sum") or 0)

    user_balance_agg = await db.users.aggregate([
        {"$match": {"role": {"$ne": "admin"}}},
        {"$group": {"_id": None, "sum": {"$sum": "$wallet_balance"}}},
    ]).to_list(1)
    user_wallet_balance = float((user_balance_agg or [{}])[0].get("sum") or 0)

    # Sep-2026 — VENDOR PAYABLE is a liability too. `users.vendor_earnings`
    # is the shop wallet: money already collected from customers that we owe
    # sellers until they withdraw it. Leaving it out made every marketplace
    # order look like company profit.
    vendor_payable_agg = await db.users.aggregate([
        {"$match": {"vendor_earnings": {"$gt": 0}}},
        {"$group": {"_id": None, "sum": {"$sum": "$vendor_earnings"}, "count": {"$sum": 1}}},
    ]).to_list(1)
    vendor_payable = round(float((vendor_payable_agg or [{}])[0].get("sum") or 0), 2)
    vendor_payable_count = int((vendor_payable_agg or [{}])[0].get("count") or 0)

    total_liability = round(user_wallet_balance + vendor_payable, 2)

    # ── Group 3 — GST Ledger ──────────────────────────────────────────
    # Business rule (June-2026): the ₹18-of-₹118 ENTRY GST is recognised
    # ONLY for Razorpay-gateway joinings (real gateway collection with an
    # auto-generated payment id). UPI-manual / offline-cash / admin-marked
    # joinings are NOT shown in the GST ledger.
    #
    # The entry GST is DERIVED from Group-1 razorpay registration revenue
    # (fee × 18/118) — no extra ledger rows, no double counting. Legacy
    # `gst_collected` txns that represent entry GST are tagged
    # `gst_kind="registration_entry"` and excluded from the sum below;
    # what remains is service / POS / other GST.
    razorpay_reg_amount = float(reg_by_source.get("razorpay", {}).get("amount") or 0)
    registration_gst = round(razorpay_reg_amount * (GST_PCT / (100.0 + GST_PCT)), 2)

    other_gst_agg = await db.transactions.aggregate([
        {"$match": {
            "type": "gst_collected",
            "status": "success",
            "gst_kind": {"$ne": "registration_entry"},
            # Defensive: legacy rows written before the tag existed.
            "description": {"$not": {"$regex": "registration|direct signup", "$options": "i"}},
        }},
        {"$group": {"_id": None, "sum": {"$sum": "$amount"}}},
    ]).to_list(1)
    other_gst = float((other_gst_agg or [{}])[0].get("sum") or 0)

    gst_collected = round(registration_gst + other_gst, 2)

    gst_paid_agg = await db.expenses.aggregate([
        {"$match": {"category": "gst_paid", "status": "approved"}},
        {"$group": {"_id": None, "sum": {"$sum": "$amount"}}},
    ]).to_list(1)
    gst_paid = float((gst_paid_agg or [{}])[0].get("sum") or 0)

    gst_payable = round(gst_collected - gst_paid, 2)

    # ── Group 5 — Operating Expenses ──────────────────────────────────
    # NOTE (2026-06-01): `gst_paid` expenses are accounted under Group 3 (GST
    # Ledger) as a payable settlement, NOT as an operating cost. We exclude
    # them from Group 5 display so the admin doesn't see them counted twice
    # (once as expense, once as GST paid). The bank_tally_out math below
    # still uses `total_expenses` (inclusive of gst_paid) so the cash math
    # remains exact — paying GST is a real cash outflow.
    operating_exp_agg = await db.expenses.aggregate([
        {"$match": {"status": "approved", "category": {"$ne": "gst_paid"}}},
        {"$group": {"_id": None, "sum": {"$sum": "$amount"}}},
    ]).to_list(1)
    operating_expenses = float((operating_exp_agg or [{}])[0].get("sum") or 0)

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

    # ── Group 8 — Refund ledger (NEW, June 2026) ─────────────────────
    # Aggregates refund payouts. Bank-debit is recorded in db.bank_ledger
    # so it already flows through `bank_debits` below — we do not subtract
    # it again from net_worth.
    refund_agg = await db.refunds.aggregate([
        {"$group": {"_id": None,
                    "sum_total":    {"$sum": "$refund_amount"},
                    "sum_clawback": {"$sum": "$clawback_total"},
                    "sum_pf_rev":   {"$sum": "$platform_fee_reversed"},
                    "count":        {"$sum": 1}}},
    ]).to_list(1)
    r0 = (refund_agg or [{}])[0]
    refund_total       = float(r0.get("sum_total")    or 0)
    refund_clawback    = float(r0.get("sum_clawback") or 0)
    refund_pf_reversed = float(r0.get("sum_pf_rev")   or 0)
    refund_count       = int(r0.get("count")          or 0)

    # Aggregate outstanding refund_debt across all users (so admin can see
    # how much is still owed by uplines after clawbacks).
    debt_agg = await db.users.aggregate([
        {"$match": {"refund_debt": {"$gt": 0}}},
        {"$group": {"_id": None,
                    "sum":   {"$sum": "$refund_debt"},
                    "count": {"$sum": 1}}},
    ]).to_list(1)
    debt_total = float((debt_agg or [{}])[0].get("sum")   or 0)
    debt_count = int((debt_agg or [{}])[0].get("count") or 0)

    # ── Group 7 — Bank Ledger (Sep-2026: the ONLY cash source of truth) ──
    # Every rupee that entered or left the company bank account has exactly
    # one row in `bank_ledger`, so this figure IS the bank statement.
    from core import bank as bank_engine
    bank_tot = await bank_engine.totals()
    bank_credits = bank_tot["credits"]
    bank_debits = bank_tot["debits"]
    bank_balance = bank_tot["balance"]
    bank_by_category = await bank_engine.by_category()

    # ── Reversals & Adjustments aggregate (for the Bank-Tally reconciliation
    # at the top of the System Wallet). Reversals are stored with amount as
    # negative (they undo a credit). Manual adjustments may be ± and live
    # under type "manual_adjustment".
    rev_agg = await db.transactions.aggregate([
        {"$match": {"type": "reversal", "status": "success"}},
        {"$group": {"_id": None, "sum": {"$sum": "$amount"}, "count": {"$sum": 1}}},
    ]).to_list(1)
    reversals_count  = int((rev_agg or [{}])[0].get("count") or 0)
    reversals_amount = float((rev_agg or [{}])[0].get("sum") or 0)  # negative net

    # Oct-2026 — adjustments now move real money via shop_money, which always
    # stores `amount` positive and puts the direction in credit/debit. Sum the
    # signed net so a debit correction shows as an outflow, not an inflow.
    adj_agg = await db.transactions.aggregate([
        {"$match": {"type": {"$in": [
            "adjustment", "manual_adjustment",
            "manual_adjustment_credit", "manual_adjustment_debit",
        ]}, "status": "success"}},
        {"$group": {"_id": None, "count": {"$sum": 1}, "sum": {"$sum": {
            "$cond": [
                {"$or": [{"$gt": ["$credit", 0]}, {"$gt": ["$debit", 0]}]},
                {"$subtract": [{"$ifNull": ["$credit", 0]}, {"$ifNull": ["$debit", 0]}]},
                "$amount",
            ],
        }}}},
    ]).to_list(1)
    adjustments_count  = int((adj_agg or [{}])[0].get("count") or 0)
    adjustments_amount = float((adj_agg or [{}])[0].get("sum") or 0)  # signed

    # Pending collections = Razorpay-initiated payments not yet captured
    pending_collections_agg = await db.transactions.aggregate([
        {"$match": {"type": "registration_inflow", "status": "pending"}},
        {"$group": {"_id": None, "sum": {"$sum": "$amount"}}},
    ]).to_list(1)
    pending_collections = float((pending_collections_agg or [{}])[0].get("sum") or 0)

    # Compute a Bank Balance Tally that's reconciliation-aware. This is what
    # the System Wallet hero card displays. Includes reversals, adjustments
    # AND expenses (Bug-1 fix · 2026-05-30) — expenses MUST debit the bank.
    #   tally_in  = gross_revenue + utr_deposits + bank_credits + positive_adjustments
    #   tally_out = settled_withdrawals + bank_debits + abs(reversals)
    #               + abs(negative_adjustments) + total_expenses
    utr_dep_agg = await db.transactions.aggregate([
        {"$match": {"type": "system_deposit", "status": {"$in": PAID}}},
        {"$group": {"_id": None, "sum": {"$sum": "$amount"}}},
    ]).to_list(1)
    utr_deposits_total = float((utr_dep_agg or [{}])[0].get("sum") or 0)

    pos_adj = max(0.0, adjustments_amount)         # signed sum already
    neg_adj = max(0.0, -adjustments_amount)
    abs_reversals = abs(reversals_amount)

    # Sep-2026 — BANK TALLY IS NOW THE BANK LEDGER, FULL STOP.
    # It used to be re-derived from revenue tables, which (a) double-counted
    # every Razorpay receipt once bank rows existed and (b) could never be
    # reconciled against a real statement. Now:
    #
    #     inflow  = Σ bank_ledger credits      (money that actually arrived)
    #     outflow = Σ bank_ledger debits       (money that actually left)
    #     net     = the bank balance           (== bank statement)
    #
    # Cash that has NOT gone through the bank (offline registration cash,
    # COD still with sellers) is reported separately as `cash_on_hand` so
    # the two are never mixed.
    bank_tally_in = bank_credits
    bank_tally_out = bank_debits
    bank_tally_net = bank_balance

    # Cash-on-hand — physical / non-bank money the company holds. Offline
    # cash + UPI-manual joinings are collected by hand, so they are cash,
    # not bank. Shown next to the bank balance, never added into it.
    cash_reg_agg = await db.transactions.aggregate([
        {"$match": {"type": "registration_fee", "status": {"$in": PAID}}},
        {"$lookup": {"from": "users", "localField": "user_id", "foreignField": "id", "as": "_u"}},
        {"$unwind": {"path": "$_u", "preserveNullAndEmptyArrays": True}},
        {"$match": {"_u.registration_source": {"$in": ["offline_cash", "upi_manual"]}}},
        {"$group": {"_id": None, "sum": {"$sum": "$amount"}, "count": {"$sum": 1}}},
    ]).to_list(1)
    cash_registration = round(float((cash_reg_agg or [{}])[0].get("sum") or 0), 2)
    cash_registration_count = int((cash_reg_agg or [{}])[0].get("count") or 0)

    # COD cash physically held by a Slangcart DELIVERY PARTNER, not yet
    # remitted. Oct-2026 FIX — this used to count EVERY delivered COD order,
    # including the ones a seller delivered himself. That seller's cash is
    # his own money (he keeps item + delivery, we take nothing), so counting
    # it as company cash inflated both cash-on-hand and net worth and left
    # the owner staring at a number that had no bank entry behind it.
    cod_agg = await db.orders.aggregate([
        {"$match": {"status": "delivered", "cod_due": {"$gt": 0},
                    "dp_id": {"$nin": [None, ""]},
                    "cod_remitted": {"$ne": True},
                    "dp_cash_remitted": {"$ne": True}}},
        {"$group": {"_id": None, "sum": {"$sum": "$cod_due"}, "count": {"$sum": 1}}},
    ]).to_list(1)
    cod_in_field = round(float((cod_agg or [{}])[0].get("sum") or 0), 2)
    cod_in_field_count = int((cod_agg or [{}])[0].get("count") or 0)

    # Seller-collected COD — reported for visibility ONLY. It never enters
    # cash_on_hand or net worth because it is not our money.
    self_cod_agg = await db.orders.aggregate([
        {"$match": {"status": "delivered", "cod_due": {"$gt": 0},
                    "$or": [{"dp_id": None}, {"dp_id": ""}, {"dp_id": {"$exists": False}}]}},
        {"$group": {"_id": None, "sum": {"$sum": "$cod_due"}, "count": {"$sum": 1}}},
    ]).to_list(1)
    cod_with_sellers = round(float((self_cod_agg or [{}])[0].get("sum") or 0), 2)
    cod_with_sellers_count = int((self_cod_agg or [{}])[0].get("count") or 0)
    cash_on_hand = round(cash_registration + cod_in_field, 2)

    # Bug-3 fix · 2026-05-30: Use the reconciliation-aware Bank Tally Net
    # (true cash on hand) as the asset component instead of just Group-7's
    # manual bank_ledger balance. Otherwise the net-worth ignored every
    # rupee of registration / service / shop revenue.
    #
    #   Net Worth = Cash on hand (bank_tally_net)
    #             + Pending collections (receivables — money users owe us)
    #             − User wallet balance (liability — we owe users)
    #             − Pending withdrawals (liability — approved payouts queued)
    #             − GST payable (liability — owed to govt)
    # Sep-2026 net worth — assets we hold minus every rupee we owe:
    #
    #   Net Worth = bank balance (Group 7, == bank statement)
    #             + cash on hand (offline cash + COD not yet remitted)
    #             + pending collections (receivables)
    #             − customer wallet liability (Group 2)
    #             − vendor payable liability  (Group 2)
    #             − pending withdrawals       (Group 6)
    #             − GST payable               (Group 3)
    net_worth = round(
        bank_balance + cash_on_hand + pending_collections
        - user_wallet_balance - vendor_payable - pending_withdrawals - gst_payable,
        2,
    )

    # ── Oct-2026 — what the owner can actually SPEND ────────────────────
    # Rider cash-in-hand is money a delivery partner is still holding for
    # us; it is NOT in the bank, so it is reported for completeness but is
    # not subtracted from the bank balance.
    dp_cash_agg = await db.users.aggregate([
        {"$match": {"dp_cash_in_hand": {"$gt": 0}}},
        {"$group": {"_id": None, "sum": {"$sum": "$dp_cash_in_hand"}, "count": {"$sum": 1}}},
    ]).to_list(1)
    dp_cash_held = round(float((dp_cash_agg or [{}])[0].get("sum") or 0), 2)
    dp_cash_count = int((dp_cash_agg or [{}])[0].get("count") or 0)

    # Jun-2026 owner request — the Treasury showed cash-on-hand and the
    # customer wallet total but never said how much of the wallet liability
    # belongs to SELLERS vs RIDERS, so the owner could not tie the numbers
    # together. Both are reported below for clarity; neither changes the net
    # worth maths (vendor wallets were already subtracted as a liability and
    # rider cash was never an asset of ours).
    dp_wallet_agg = await db.users.aggregate([
        {"$match": {"is_delivery_partner": True, "wallet_balance": {"$gt": 0}}},
        {"$group": {"_id": None, "sum": {"$sum": "$wallet_balance"}, "count": {"$sum": 1}}},
    ]).to_list(1)
    dp_wallet_balance = round(float((dp_wallet_agg or [{}])[0].get("sum") or 0), 2)
    dp_wallet_count = int((dp_wallet_agg or [{}])[0].get("count") or 0)
    earmarked_total = round(
        vendor_payable + user_wallet_balance + pending_withdrawals + gst_payable, 2,
    )
    free_to_spend = round(bank_balance - earmarked_total, 2)

    return {
        "group_1_revenue": {
            "registration": round(registration_revenue, 2),
            "service":      round(service_revenue, 2),
            "platform_fee": round(platform_fee_revenue, 2),
            "shop":         round(shop_revenue, 2),
            "delivery":     delivery_revenue,
            "gross":        gross_revenue,
            # NEW: per-source breakdown of joinings so admins can see how
            # much came via Razorpay vs UPI manual vs Offline cash.
            "by_source": {
                "razorpay":     reg_by_source.get("razorpay",     {"amount": 0.0, "count": 0}),
                "upi_manual":   reg_by_source.get("upi_manual",   {"amount": 0.0, "count": 0}),
                "offline_cash": reg_by_source.get("offline_cash", {"amount": 0.0, "count": 0}),
            },
            "reversed": round(reg_reversed, 2),
        },
        "group_2_liability": {
            "total_reward_credits":       round(total_reward_credits, 2),
            "total_withdrawals_settled":  round(total_withdrawals_settled, 2),
            "available_user_balance":     round(user_wallet_balance, 2),
            # Sep-2026 — vendor payables are a liability of the same kind.
            "vendor_payable":             vendor_payable,
            "vendor_payable_sellers":     vendor_payable_count,
            "total_liability":            total_liability,
        },
        "group_3_gst": {
            "collected": round(gst_collected, 2),
            "paid":      round(gst_paid, 2),
            "payable":   gst_payable,
            # Sub-split so admin sees WHERE the GST came from.
            "registration_gst":        registration_gst,
            "registration_gst_base":   round(razorpay_reg_amount, 2),
            "registration_count":      int(reg_by_source.get("razorpay", {}).get("count") or 0),
            "other_gst":               round(other_gst, 2),
            "note": "Entry GST (18/118) counted for Razorpay gateway joinings only.",
        },
        "group_4_platform_fee": {
            "collected": round(platform_fee_revenue, 2),
        },
        "group_5_expenses": {
            "total": round(operating_expenses, 2),
            # Diagnostic: show what was hidden from this group because it
            # belongs to Group 3 (GST Ledger) as a payable settlement.
            "gst_paid_excluded": round(total_expenses - operating_expenses, 2),
        },
        "group_6_pending_withdrawals": {
            "pending_amount": round(pending_withdrawals, 2),
        },
        "group_7_bank": {
            "credits": round(bank_credits, 2),
            "debits":  round(bank_debits, 2),
            "balance": bank_balance,
            "by_category": bank_by_category,
            "note": "Every Razorpay receipt and every payout has one row here — this equals the bank statement.",
        },
        "group_8_refunds": {
            "total":                  round(refund_total, 2),
            "count":                  refund_count,
            "clawback_total":         round(refund_clawback, 2),
            "platform_fee_reversed":  round(refund_pf_reversed, 2),
            "outstanding_debt":       round(debt_total, 2),
            "outstanding_debt_users": debt_count,
        },
        # NEW: Top-of-screen Bank Balance Tally that respects reversals &
        # adjustments. Frontend hero card uses this directly.
        "bank_tally": {
            "inflow":           bank_tally_in,
            "outflow":          bank_tally_out,
            "net":              bank_tally_net,
            "utr_deposits":     round(utr_deposits_total, 2),
            "reversals_count":  reversals_count,
            "reversals_amount": round(abs_reversals, 2),
            "adjustments_count":  adjustments_count,
            "adjustments_amount": round(adjustments_amount, 2),
            # ── Oct-2026 — how much of the bank balance is actually SPENDABLE.
            # The tally only showed inflow/outflow, so the owner could see a
            # healthy bank balance without knowing that most of it is money
            # we owe sellers, riders and customers. Everything below is
            # already inside `net`; this just splits it.
            "earmarked": {
                "vendor_wallets":   vendor_payable,
                "vendor_count":     vendor_payable_count,
                "rider_cash":       dp_cash_held,
                "rider_count":      dp_cash_count,
                "customer_wallets": round(user_wallet_balance, 2),
                "pending_withdrawals": round(pending_withdrawals, 2),
                "gst_payable":      round(gst_payable, 2),
                "total":            earmarked_total,
            },
            "free_to_spend": free_to_spend,
            "free_note": (
                "Bank balance minus everything we owe sellers, riders, customers, "
                "pending withdrawals and GST. This is the only part safe to use for "
                "development or expenses."
            ),
            "formula": "Inflow (bank ledger credits) − Outflow (bank ledger debits) = bank statement balance",
        },
        "cash_on_hand": {
            "total":                cash_on_hand,
            "registration_cash":    cash_registration,
            "registration_count":   cash_registration_count,
            "cod_with_collectors":  cod_in_field,
            "cod_orders":           cod_in_field_count,
            # Informational — the seller's own money, never ours.
            "cod_with_sellers":     cod_with_sellers,
            "cod_with_sellers_orders": cod_with_sellers_count,
            # Jun-2026 — shown for clarity, NOT added to `total`: the rider's
            # cash pot is the same money as `cod_with_collectors`, seen from
            # the rider's ledger instead of the order's.
            "rider_cash_held":      dp_cash_held,
            "rider_count":          dp_cash_count,
            "rider_wallets":        dp_wallet_balance,
            "rider_wallet_count":   dp_wallet_count,
            "vendor_wallets":       vendor_payable,
            "vendor_wallet_count":  vendor_payable_count,
            "note": "Physical cash the company holds — offline/UPI-manual joinings plus COD a delivery partner still owes us. Seller-collected COD (own delivery) is shown separately and is NOT company money.",
        },
        "master": {
            "pending_collections": round(pending_collections, 2),
            "net_worth":           net_worth,
            "formula":             "bank_balance + cash_on_hand + pending − customer_wallet − vendor_payable − pending_withdrawals − gst_payable",
            "components": {
                "bank_balance":        bank_balance,
                "bank_tally_net":      bank_tally_net,
                "cash_on_hand":        cash_on_hand,
                "pending_collections": round(pending_collections, 2),
                "user_wallet_balance": round(user_wallet_balance, 2),
                "vendor_payable":      vendor_payable,
                "vendor_payable_sellers": vendor_payable_count,
                # Clarity rows — already inside the figures above, never
                # added on top of them.
                "rider_cash_held":     dp_cash_held,
                "rider_count":         dp_cash_count,
                "rider_wallets":       dp_wallet_balance,
                "rider_wallet_count":  dp_wallet_count,
                "total_liability":     total_liability,
                "pending_withdrawals": round(pending_withdrawals, 2),
                "gst_payable":         gst_payable,
            },
        },
        "generated_at": now_utc().isoformat(),
    }


# ────────────────────────────────────────────────────────────────────

# ────────────────────────────────────────────────────────────────────
# Group-level transaction drilldown
#
# Powers the "tap a group → see every txn that built that number" flow
# inside System Wallet. Returns a uniform shape across all 7 groups:
#
#   { title, subtotal, items: [{ id, display_id, type, amount, status,
#       description, created_at, ... }] }
#
# Groups 5 (expenses), 6 (pending withdrawals) and 7 (bank ledger) read
# from their respective collections; 1-4 read from db.transactions.
# ────────────────────────────────────────────────────────────────────
@router.get("/admin/finance/groups/{group_id}/transactions")
async def admin_finance_group_transactions(
    group_id: str,
    limit: int = 200,
    _: Dict[str, Any] = Depends(require_admin),
):
    limit = max(1, min(int(limit or 200), 500))
    PAID = ["paid", "success", "approved"]

    def _shape_txn(t: Dict[str, Any]) -> Dict[str, Any]:
        t.pop("_id", None)
        return {
            "id":           t.get("id"),
            "display_id":   t.get("display_id"),
            "type":         t.get("type"),
            "amount":       float(t.get("amount") or 0),
            "gross_amount": float(t.get("gross_amount")) if t.get("gross_amount") is not None else None,
            "gst_amount":   float(t.get("gst_amount")) if t.get("gst_amount") is not None else None,
            "status":       t.get("status"),
            "level":        t.get("level"),
            "description":  t.get("description") or "",
            "source":       t.get("source"),
            "user_id":      t.get("user_id"),
            "vendor_id":    t.get("vendor_id"),
            "shop_name":    t.get("shop_name"),
            "order_number": t.get("order_number"),
            "wallet":       "vendor" if t.get("wallet_impact") == "vendor_earnings_only" else "customer",
            "credit":       float(t.get("credit") or 0),
            "debit":        float(t.get("debit") or 0),
            "reversed_by":  t.get("reversed_by"),
            "reverses":     t.get("reverses"),
            "created_at":   t.get("created_at"),
        }

    # ── Group 1 — Revenue Ledger ─────────────────────────────────────
    if group_id == "group_1_revenue":
        match = {
            "type": {"$in": [
                "registration_fee", "service_margin", "service_commission",
                "phone_reveal_invoice", "service_request_fee",
                "platform_fee_collected",
                "shop_purchase", "shop_revenue", "shopping_margin", "shop_commission",
                # Sep-2026 — delivery revenue (net of 18% GST) belongs here.
                "delivery_charge_collected", "delivery_revenue_reversal",
            ]},
            "status": {"$in": PAID},
        }
        rows = await db.transactions.find(match).sort("created_at", -1).limit(limit).to_list(limit)
        subtotal = sum(float(r.get("amount") or 0) for r in rows)
        return {"title": "Group 1 · Revenue Ledger", "subtotal": round(subtotal, 2), "items": [_shape_txn(r) for r in rows]}

    # ── Group 2 — Liability wallet (customer wallets + vendor payables) ──
    # Sep-2026 — this used to match only 3 legacy referral types, so the
    # group showed a correct total with an empty list ("money untraceable").
    # It now lists EVERY row that moves a liability wallet: vendor sale
    # credits, top-ups, cashback, refunds, withdrawals and adjustments.
    if group_id == "group_2_liability":
        rows = await db.transactions.find({
            "type": {"$in": [
                # customer wallet
                "referral_payout", "direct_signup_credit", "wallet_topup",
                "cashback_credit", "cashback_reversal", "cashback_pending",
                "refund", "return_refund_credit", "payment_reconciliation_refund",
                "transfer_in", "transfer_out", "order",
                "admin_credit", "admin_debit",
                # vendor (shop) wallet
                "vendor_sale", "vendor_sale_reversal", "return_refund_debit",
                "cashback_funding", "cashback_funding_refund",
                "vendor_adjustment_credit", "vendor_adjustment_debit",
                # settlement out of either wallet
                "withdrawal", "withdrawal_hold", "withdrawal_refund",
            ]},
            "status": {"$in": PAID + ["processing", "pending"]},
        }).sort("created_at", -1).limit(limit).to_list(limit)
        for r in rows:
            r["level"] = "vendor" if r.get("wallet_impact") == "vendor_earnings_only" else "customer"
        subtotal = sum(float(r.get("amount") or 0) for r in rows)
        return {
            "title": "Group 2 · Liability Wallet (customers + vendors)",
            "subtotal": round(subtotal, 2),
            "items": [_shape_txn(r) for r in rows],
        }

    # ── Group 3 — GST Ledger ─────────────────────────────────────────
    # Entry GST is DERIVED per Razorpay joining (fee × 18/118) so every
    # gateway registration shows up as its own GST line. Non-entry GST
    # (service / POS) rows come straight from the ledger. `gst_paid`
    # expenses are shown as negative settlements.
    if group_id == "group_3_gst":
        reg_rows = await db.transactions.aggregate([
            {"$match": {"type": "registration_fee", "status": {"$in": PAID}}},
            {"$lookup": {"from": "users", "localField": "user_id", "foreignField": "id", "as": "_u"}},
            {"$unwind": {"path": "$_u", "preserveNullAndEmptyArrays": True}},
            {"$match": {"_u.registration_source": "razorpay"}},
            {"$sort": {"created_at": -1}},
            {"$limit": limit},
        ], allowDiskUse=True).to_list(limit)
        items = []
        for r in reg_rows:
            u = r.get("_u") or {}
            gross = float(r.get("amount") or 0)
            gst = round(gross * (GST_PCT / (100.0 + GST_PCT)), 2)
            items.append({
                "id":         r.get("id"),
                "display_id": f"GST-{str(r.get('id') or '').replace('-', '')[-6:].upper()}",
                "type":       "gst_collected · registration",
                "amount":     gst,
                "status":     "success",
                "source":     "razorpay",
                "user_id":    r.get("user_id"),
                "description": (
                    f"Entry GST 18% on ₹{gross:g} joining · {u.get('name') or u.get('email') or '—'}"
                    f" · {u.get('referral_code') or ''}"
                ),
                "created_at": r.get("paid_at") or r.get("created_at"),
            })
        rows = await db.transactions.find({
            "type": "gst_collected",
            "status": {"$in": PAID},
            "gst_kind": {"$ne": "registration_entry"},
            "description": {"$not": {"$regex": "registration|direct signup", "$options": "i"}},
        }).sort("created_at", -1).limit(limit).to_list(limit)
        gst_paid_exps = await db.expenses.find({
            "category": "gst_paid", "status": "approved",
        }).sort("created_at", -1).limit(limit).to_list(limit)
        items += [_shape_txn(r) for r in rows]
        for e in gst_paid_exps:
            e.pop("_id", None)
            items.append({
                "id":         e.get("id"),
                "display_id": e.get("display_id") or f"EXP-{(e.get('id') or '')[:6]}",
                "type":       "gst_paid",
                "amount":     -float(e.get("amount") or 0),
                "status":     "approved",
                "description": e.get("description") or "GST paid (expense)",
                "created_at": e.get("created_at"),
            })
        items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
        subtotal = sum(float(r.get("amount") or 0) for r in items)
        return {"title": "Group 3 · GST Ledger", "subtotal": round(subtotal, 2), "items": items[:limit]}

    # ── Group 4 — Platform Fee Ledger ────────────────────────────────
    if group_id == "group_4_platform_fee":
        rows = await db.transactions.find({
            "type": "platform_fee_collected",
            "status": {"$in": PAID},
        }).sort("created_at", -1).limit(limit).to_list(limit)
        subtotal = sum(float(r.get("amount") or 0) for r in rows)
        return {"title": "Group 4 · Platform Fee Ledger", "subtotal": round(subtotal, 2), "items": [_shape_txn(r) for r in rows]}

    # ── Group 5 — Expense Ledger (db.expenses) ───────────────────────
    # Excludes category=gst_paid because those are shown under Group 3.
    if group_id == "group_5_expenses":
        rows = await db.expenses.find({
            "status": "approved",
            "category": {"$ne": "gst_paid"},
        }).sort("created_at", -1).limit(limit).to_list(limit)
        items = []
        for e in rows:
            e.pop("_id", None)
            items.append({
                "id":         e.get("id"),
                "display_id": e.get("display_id") or f"EXP-{(e.get('id') or '')[:6]}",
                "type":       f"expense · {e.get('category') or 'other'}",
                "amount":     -float(e.get("amount") or 0),
                "status":     e.get("status") or "approved",
                "description": e.get("description") or "",
                "vendor":     e.get("vendor"),
                "category":   e.get("category"),
                "created_at": e.get("created_at"),
            })
        subtotal = sum(float(r.get("amount") or 0) for r in items)
        return {"title": "Group 5 · Expense Ledger", "subtotal": round(subtotal, 2), "items": items}

    # ── Group 6 — Pending Withdrawals (db.withdrawals) ───────────────
    if group_id == "group_6_pending_withdrawals":
        rows = await db.withdrawals.find({"status": "pending"}).sort("created_at", -1).limit(limit).to_list(limit)
        items = []
        for w in rows:
            w.pop("_id", None)
            items.append({
                "id":         w.get("id"),
                "display_id": w.get("display_id") or f"WD-{(w.get('id') or '')[:6]}",
                "type":       "withdrawal · pending",
                "amount":     -float(w.get("amount") or 0),
                "status":     w.get("status"),
                "description": f"Pending withdrawal · UPI {w.get('upi_id') or '—'} · user {w.get('user_email') or w.get('user_id')}",
                "user_id":    w.get("user_id"),
                "created_at": w.get("created_at"),
            })
        subtotal = sum(float(r.get("amount") or 0) for r in items)
        return {"title": "Group 6 · Pending Withdrawals", "subtotal": round(subtotal, 2), "items": items}

    # ── Group 7 — Bank Ledger (db.bank_ledger) ───────────────────────
    if group_id == "group_7_bank":
        rows = await db.bank_ledger.find({}).sort("created_at", -1).limit(limit).to_list(limit)
        items = []
        for b in rows:
            b.pop("_id", None)
            amt = float(b.get("amount") or 0)
            signed = amt if b.get("kind") == "credit" else -amt
            items.append({
                "id":         b.get("id"),
                "display_id": b.get("display_id") or f"BANK-{(b.get('id') or '')[:6]}",
                "type":       f"bank · {b.get('kind') or 'entry'}",
                "amount":     signed,
                "status":     b.get("status") or "success",
                "description": b.get("description") or "Bank ledger entry",
                "bank":       b.get("bank"),
                "utr":        b.get("utr"),
                "created_at": b.get("created_at"),
            })
        subtotal = sum(float(r.get("amount") or 0) for r in items)
        return {"title": "Group 7 · Bank Ledger", "subtotal": round(subtotal, 2), "items": items}

    # ── Group 8 — Refund Ledger (db.refunds) — June 2026 ─────────────
    if group_id == "group_8_refunds":
        rows = await db.refunds.find({}).sort("created_at", -1).limit(limit).to_list(limit)
        items = []
        for r in rows:
            r.pop("_id", None)
            items.append({
                "id":         r.get("id"),
                "display_id": r.get("display_id") or f"RFND-{(r.get('id') or '')[:6]}",
                "type":       "refund · paid" + (" + GST" if r.get("gst_refund") else ""),
                "amount":     -float(r.get("refund_amount") or 0),
                "status":     r.get("status") or "success",
                "description": (
                    f"Refund to {r.get('target_name') or r.get('target_email') or r.get('target_referral_id') or '—'}"
                    + (f" — {r.get('comments')}" if r.get("comments") else "")
                ),
                "target_user_id": r.get("target_user_id"),
                "clawback_total": float(r.get("clawback_total") or 0),
                "platform_fee_reversed": float(r.get("platform_fee_reversed") or 0),
                "final_action": r.get("final_action"),
                "created_at": r.get("created_at"),
            })
        subtotal = sum(float(rr.get("amount") or 0) for rr in items)
        return {"title": "Group 8 · Refund Ledger", "subtotal": round(subtotal, 2), "items": items}

    raise HTTPException(status_code=400, detail=f"Unknown group_id: {group_id}")


# ────────────────────────────────────────────────────────────────────
# Reset endpoints — wipe Bank Ledger / Expense Ledger.
#
# DESTRUCTIVE. Super-admin only. Audit-logged. The frontend uses a
# type-to-confirm modal ("RESET") to gate this action.
#
# We intentionally archive into a `<col>_archived` collection rather
# than hard-delete, so the data is recoverable if you call support.
# ────────────────────────────────────────────────────────────────────
@router.post("/admin/bank-ledger/reset")
async def admin_reset_bank_ledger(admin: Dict[str, Any] = Depends(require_admin_role("super_admin"))):
    rows = await db.bank_ledger.find({}).to_list(10000)
    archived = 0
    if rows:
        for r in rows:
            r["_archived_at"] = now_utc().isoformat()
            r["_archived_by"] = admin.get("email") or admin.get("id")
        await db.bank_ledger_archived.insert_many(rows)
        archived = len(rows)
    res = await db.bank_ledger.delete_many({})
    # Audit
    try:
        from server import _audit_log
        await _audit_log(admin, "finance.bank_ledger.reset", "bank_ledger", "all",
                          {"archived": archived, "deleted": res.deleted_count})
    except Exception:
        pass
    return {"ok": True, "archived": archived, "deleted": res.deleted_count}


@router.post("/admin/expenses/reset")
async def admin_reset_expenses(admin: Dict[str, Any] = Depends(require_admin_role("super_admin"))):
    rows = await db.expenses.find({}).to_list(10000)
    archived = 0
    if rows:
        for r in rows:
            r["_archived_at"] = now_utc().isoformat()
            r["_archived_by"] = admin.get("email") or admin.get("id")
        await db.expenses_archived.insert_many(rows)
        archived = len(rows)
    res = await db.expenses.delete_many({})
    try:
        from server import _audit_log
        await _audit_log(admin, "finance.expenses.reset", "expenses", "all",
                          {"archived": archived, "deleted": res.deleted_count})
    except Exception:
        pass
    return {"ok": True, "archived": archived, "deleted": res.deleted_count}


@router.post("/admin/payment-history/reset")
async def admin_reset_payment_history(admin: Dict[str, Any] = Depends(require_admin_role("super_admin"))):
    """Wipe UPI manual payments audit history + system wallet deposit log.

    Bug-fix · 2026-05-31: The original 2-button reset (bank ledger / expenses)
    left `manual_payments` (UPI approval audit) and `system_wallet_deposits`
    (UTR receipt log) untouched, so the admin couldn't fully reset the books.
    This endpoint archives + clears both collections in one shot.

    Does NOT touch:
      - `transactions`  (accounting ledger truth)
      - `users`          (user wallets)
      - `withdrawals`    (live withdrawal queue)
    """
    summary: Dict[str, int] = {}
    for col_name, archive_name in [
        ("manual_payments",         "manual_payments_archived"),
        ("system_wallet_deposits",  "system_wallet_deposits_archived"),
    ]:
        col      = db[col_name]
        archive  = db[archive_name]
        rows     = await col.find({}).to_list(10000)
        if rows:
            stamp_iso = now_utc().isoformat()
            for r in rows:
                r["_archived_at"] = stamp_iso
                r["_archived_by"] = admin.get("email") or admin.get("id")
            await archive.insert_many(rows)
        deleted = (await col.delete_many({})).deleted_count
        summary[col_name] = {"archived": len(rows), "deleted": deleted}
    try:
        from server import _audit_log
        await _audit_log(admin, "finance.payment_history.reset", "payment_history", "all", summary)
    except Exception:
        pass
    return {"ok": True, **summary}





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
    """Create a manual ADJUSTMENT that actually MOVES money.

    Oct-2026 FIX — this used to insert a `transactions` row and nothing else:
    no wallet was touched, so "adjustment money" was a number on a screen
    that no refund and no cashback could ever spend, while still shifting the
    reconciliation display. It now posts through the real ledger
    (`shop_money.credit` / `shop_money.debit`), so the balance it claims to
    create genuinely exists, is spendable, and is traceable row-by-row.

    Body:
        user_id: str            (target wallet owner)
        amount: float           (positive = credit, negative = debit)
        wallet: str (optional)  "wallet_balance" (default) | "vendor_earnings"
        category: str           (e.g. "correction", "writeoff", "topup")
        description: str
        bucket: str (optional)  admin system-wallet bucket to attribute it to
    """
    user_id    = (payload.get("user_id") or "").strip()
    amount     = round(float(payload.get("amount") or 0), 2)
    category   = (payload.get("category") or "correction").strip()
    description = (payload.get("description") or "").strip()
    wallet     = (payload.get("wallet") or shop_money.CUSTOMER_WALLET).strip()
    if not user_id or amount == 0 or not description:
        raise HTTPException(status_code=400, detail="user_id, amount, description are all required")
    if wallet not in (shop_money.CUSTOMER_WALLET, shop_money.VENDOR_WALLET):
        raise HTTPException(status_code=400, detail="wallet must be wallet_balance or vendor_earnings")
    target = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    audit = await extract_client_audit(request)
    key = f"ADJUST:{uuid.uuid4().hex}"
    common = dict(
        group="adjustment",
        settlement_status="adjusted",
        description=f"ADJUST · {description}",
        extra={
            "category": category,
            "created_by_admin": admin["id"],
            "created_by_email": admin.get("email"),
            **({"wallet_impact": "vendor_earnings_only"} if wallet == shop_money.VENDOR_WALLET else {}),
            **audit,
        },
    )
    try:
        if amount > 0:
            row = await shop_money.credit(
                user_id, wallet, amount,
                idempotency_key=key, txn_type="manual_adjustment_credit", **common,
            )
        else:
            row = await shop_money.debit(
                user_id, wallet, abs(amount),
                idempotency_key=key, txn_type="manual_adjustment_debit", **common,
            )
    except shop_money.InsufficientFunds as err:
        raise HTTPException(status_code=400, detail=str(err))
    if row is None:
        raise HTTPException(status_code=409, detail="This adjustment was already posted.")

    # When the money lands on the company account, attribute it to a
    # system-wallet bucket so the Treasury breakdown stays explainable.
    # `shop_money.credit` already moved `wallet_balance`, so we only touch
    # the bucket counter here — never the balance again (no double entry).
    is_company = (target.get("role") == "admin") or (
        (target.get("email") or "").lower() == ADMIN_EMAIL.lower()
    )
    if is_company and wallet == shop_money.CUSTOMER_WALLET:
        bucket = (payload.get("bucket") or "direct_added").strip()
        if bucket in SYSTEM_WALLET_BUCKETS:
            await db.users.update_one(
                {"id": user_id}, {"$inc": {f"wallet_buckets.{bucket}": amount}},
            )

    await _audit_log(admin, "transaction.adjust", "transaction", row["id"], {
        "amount": amount, "category": category, "description": description,
        "wallet": wallet, "target": target.get("email"),
        "new_balance": row.get("new_balance"),
    })
    return {"ok": True, "adjustment": row}


# ────────────────────────────────────────────────────────────────────
# Expense Ledger CRUD (Group 5)
# ────────────────────────────────────────────────────────────────────
DEFAULT_EXPENSE_CATEGORIES = [
    "server_hosting", "sms_charges", "whatsapp_api", "staff_salary",
    "marketing", "legal_fees", "office_expenses", "payment_gateway",
    # June 2026 — "refunds" moved out of Group 5 into its own Group 8 ledger
    # (db.refunds). Keep "gst_paid" + "other" here.
    "gst_paid", "other",
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
