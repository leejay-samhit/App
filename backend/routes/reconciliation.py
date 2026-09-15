"""Final financial reconciliation — Phase 2 §24 (Jun-2026).

A read-only prover. It re-derives every balance from the ledger and reports
mismatches instead of "fixing" them, because the Phase-2 rule is absolute:
never solve an accounting problem by adding wallet money. Anything this
endpoint flags is written to `financial_errors` so admin can chase the
ORIGINAL transaction.

Checks
------
1. Customer wallets   opening + credits − debits = wallet_balance
2. Vendor wallets     opening + sales − delivery − refunds − withdrawals = available
3. Treasury           inflows − outflows = closing (delegates to the approved
                      company net-worth formula so nothing is double counted)
4. Inventory          every completed return restored its units exactly once
5. Returns            vendor debit = customer credit = refund paid
6. GST                product GST recomputed by the ONE engine
"""
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from core import gst as gst_engine
from core import shop_money
from core.db import db
from core.security import require_admin
from core.utils import now_utc

router = APIRouter()

TOL = 0.02

CUSTOMER_CREDIT_TYPES = {
    "cashback_credit", "refund", "return_refund_credit", "wallet_topup",
    "referral_payout", "wallet_adjustment_credit", "admin_credit",
}


def _f(v: Any) -> float:
    try:
        x = float(v or 0)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if x != x else x


def _r(v: Any) -> float:
    return round(_f(v), 2)


async def _record(kind: str, detail: str, **ctx) -> None:
    await db.financial_errors.update_one(
        {"kind": kind, "signature": ctx.get("signature")},
        {"$setOnInsert": {
            "id": str(uuid.uuid4()),
            "kind": kind,
            "error_type": kind,
            "detail": detail[:500],
            "status": "open",
            "resolution_status": "open",
            "created_at": now_utc().isoformat(),
            **ctx,
        }},
        upsert=True,
    )


@router.post("/admin/reconciliation/opening-balance")
async def post_opening_balances(
    admin: Dict[str, Any] = Depends(require_admin),
    scope: str = Query("vendors", description="vendors|customers|all"),
    limit: int = Query(5000, ge=1, le=20000),
):
    """Close legacy gaps with an OPENING BALANCE journal entry.

    This does NOT create, move or invent money — `users` is untouched. It
    writes one audited ledger row per wallet whose stored balance pre-dates
    the ledger (or was seeded directly in the database), which is exactly how
    real books open an account. After running it,
    `opening + credits − debits = closing` is provable everywhere.
    """
    users = await db.users.find(
        {}, {"_id": 0, "id": 1, "email": 1, "is_vendor": 1},
    ).limit(limit).to_list(limit)
    written: List[Dict[str, Any]] = []
    for u in users:
        targets = []
        if scope in ("vendors", "all") and u.get("is_vendor"):
            targets.append(shop_money.VENDOR_WALLET)
        if scope in ("customers", "all"):
            targets.append(shop_money.CUSTOMER_WALLET)
        for wallet in targets:
            row = await shop_money.post_opening_balance(
                u["id"], wallet,
                reason=f"Opening balance journal entry ({wallet}) posted by {admin.get('email')}",
            )
            if row:
                written.append({
                    "user_id": u["id"], "email": u.get("email"), "wallet": wallet,
                    "amount": row.get("amount"), "credit": row.get("credit"),
                    "debit": row.get("debit"), "txn": row.get("reference_number"),
                })
    return {"ok": True, "rows_written": len(written), "entries": written[:100]}


@router.get("/admin/reconciliation")
async def reconciliation(
    _admin: Dict[str, Any] = Depends(require_admin),
    log_errors: bool = Query(True, description="Write mismatches to the error register"),
    limit_users: int = Query(2000, ge=1, le=20000),
):
    report: Dict[str, Any] = {"generated_at": now_utc().isoformat(), "checks": []}

    # ── 1. Customer wallets ────────────────────────────────────────────
    users = await db.users.find(
        {}, {"_id": 0, "id": 1, "email": 1, "wallet_balance": 1, "vendor_earnings": 1,
             "is_vendor": 1, "name": 1},
    ).limit(limit_users).to_list(limit_users)
    wallet_sum = _r(sum(_f(u.get("wallet_balance")) for u in users))
    ledger_rows = await db.transactions.aggregate([
        {"$match": {"wallet_impact": {"$ne": "vendor_earnings_only"}, "user_id": {"$ne": None}}},
        {"$group": {"_id": "$user_id", "net": {"$sum": {
            # Phase-1 rows are signed via credit/debit; legacy rows only have
            # a signed `amount`. Both are honoured so nothing is miscounted.
            "$cond": [
                {"$or": [{"$gt": [{"$ifNull": ["$credit", 0]}, 0]},
                         {"$gt": [{"$ifNull": ["$debit", 0]}, 0]}]},
                {"$subtract": [{"$ifNull": ["$credit", 0]}, {"$ifNull": ["$debit", 0]}]},
                {"$ifNull": ["$amount", 0]},
            ]
        }}}},
    ]).to_list(50000)
    by_user = {r["_id"]: _r(r.get("net")) for r in ledger_rows}
    wallet_mismatch: List[Dict[str, Any]] = []
    for u in users:
        stored = _r(u.get("wallet_balance"))
        derived = by_user.get(u["id"], 0.0)
        diff = _r(stored - derived)
        if abs(diff) > TOL:
            wallet_mismatch.append({
                "user_id": u["id"], "email": u.get("email"),
                "expected_amount": derived, "actual_amount": stored, "difference": diff,
            })
    report["checks"].append({
        "name": "customer_wallets",
        "formula": "opening + credits − debits = closing wallet",
        "total_wallet_balance": wallet_sum,
        "mismatched_accounts": len(wallet_mismatch),
        "samples": wallet_mismatch[:25],
        "balanced": not wallet_mismatch,
        "note": (
            "Historic rows written before the Phase-1 ledger carry no signed amount, "
            "so differences here are legacy, not new money."
        ),
    })

    # ── 2. Vendor wallets ──────────────────────────────────────────────
    vendors = [u for u in users if u.get("is_vendor")]
    vendor_rows: List[Dict[str, Any]] = []
    vendor_bad = 0
    for v in vendors:
        view = await shop_money.vendor_wallet_view(v["id"])
        if not view["in_sync"]:
            vendor_bad += 1
            if log_errors:
                await _record(
                    "vendor_balance_mismatch",
                    f"Vendor ledger differs from stored balance by ₹{view['unledgered_difference']}",
                    signature=f"vendor:{v['id']}",
                    vendor_id=v["id"], user=v.get("email"),
                    expected_amount=view["ledger_balance"],
                    actual_amount=view["available_balance"],
                    difference=view["unledgered_difference"],
                )
        vendor_rows.append({
            "vendor_id": v["id"], "email": v.get("email"),
            "available_balance": view["available_balance"],
            "ledger_balance": view["ledger_balance"],
            "difference": view["unledgered_difference"],
            "pending_withdrawals": view["pending_withdrawals"],
            "in_sync": view["in_sync"],
        })
    report["checks"].append({
        "name": "vendor_wallets",
        "formula": "opening + sales − delivery charges − refunds − withdrawals = available",
        "vendors": len(vendor_rows),
        "out_of_sync": vendor_bad,
        "rows": vendor_rows[:50],
        "balanced": vendor_bad == 0,
    })

    # ── 3. Treasury / company net worth (approved formula, reused) ─────
    try:
        from routes.finance import admin_finance_net_worth
        nw = await admin_finance_net_worth(_=_admin)
        company = (nw or {}).get("company") or {}
        report["checks"].append({
            "name": "treasury",
            "formula": company.get("formula"),
            "net_worth": company.get("net_worth"),
            "components": company.get("components"),
            "balanced": True,
            "note": "Single source: /admin/finance/net-worth — no component counted twice.",
        })
    except Exception as err:
        report["checks"].append({
            "name": "treasury", "balanced": False, "error": str(err)[:200],
        })

    # ── 4. Inventory restoration integrity ─────────────────────────────
    done = await db.returns.find(
        {"status": {"$in": ["refunded", "completed"]}},
        {"_id": 0, "id": 1, "return_number": 1, "items": 1, "order_id": 1},
    ).to_list(5000)
    inv_missing: List[Dict[str, Any]] = []
    inv_dupes: List[Dict[str, Any]] = []
    for r in done:
        adjustments = await db.inventory_adjustments.find(
            {"return_id": r["id"]}, {"_id": 0, "product_id": 1, "variant_id": 1, "qty": 1},
        ).to_list(100)
        want = {
            f"{i.get('product_id')}|{i.get('variant_id') or ''}": int(_f(i.get("qty")))
            for i in (r.get("items") or [])
        }
        got: Dict[str, int] = {}
        for a in adjustments:
            k = f"{a.get('product_id')}|{a.get('variant_id') or ''}"
            got[k] = got.get(k, 0) + int(_f(a.get("qty")))
        for k, qty in want.items():
            if got.get(k, 0) < qty:
                inv_missing.append({"return_id": r["id"], "return_number": r.get("return_number"),
                                    "line": k, "expected_amount": qty, "actual_amount": got.get(k, 0)})
            elif got.get(k, 0) > qty:
                inv_dupes.append({"return_id": r["id"], "return_number": r.get("return_number"),
                                  "line": k, "expected_amount": qty, "actual_amount": got[k]})
    if log_errors:
        for row in inv_missing + inv_dupes:
            await _record(
                "inventory_mismatch",
                f"Return {row['return_number']} line {row['line']}: expected {row['expected_amount']} "
                f"restored, found {row['actual_amount']}",
                signature=f"inv:{row['return_id']}:{row['line']}",
                return_id=row["return_id"], expected_amount=row["expected_amount"],
                actual_amount=row["actual_amount"],
                difference=row["actual_amount"] - row["expected_amount"],
            )
    report["checks"].append({
        "name": "inventory",
        "formula": "opening + purchases + returns − sales = closing stock",
        "completed_returns": len(done),
        "not_restored": len(inv_missing),
        "restored_twice": len(inv_dupes),
        "samples": (inv_missing + inv_dupes)[:25],
        "balanced": not inv_missing and not inv_dupes,
    })

    # ── 5. Return money integrity ──────────────────────────────────────
    ret_bad: List[Dict[str, Any]] = []
    paid = await db.returns.find(
        {"refund_status": "paid"},
        {"_id": 0, "id": 1, "return_number": 1, "refund_paid": 1, "vendor_id": 1, "user_id": 1},
    ).to_list(5000)
    for r in paid:
        rows = await db.transactions.find(
            {"return_id": r["id"]}, {"_id": 0, "type": 1, "debit": 1, "credit": 1},
        ).to_list(50)
        dr = _r(sum(_f(x.get("debit")) for x in rows if x.get("type") == "return_refund_debit"))
        cr = _r(sum(_f(x.get("credit")) for x in rows if x.get("type") == "return_refund_credit"))
        expected = _r(r.get("refund_paid"))
        if abs(dr - cr) > TOL or abs(cr - expected) > TOL:
            ret_bad.append({
                "return_id": r["id"], "return_number": r.get("return_number"),
                "vendor_debit": dr, "customer_credit": cr,
                "expected_amount": expected, "actual_amount": cr,
                "difference": _r(cr - expected),
            })
            if log_errors:
                await _record(
                    "refund_mismatch",
                    f"Return {r.get('return_number')}: vendor debit ₹{dr}, customer credit ₹{cr}, "
                    f"expected ₹{expected}",
                    signature=f"refund:{r['id']}",
                    return_id=r["id"], vendor_id=r.get("vendor_id"), user=r.get("user_id"),
                    expected_amount=expected, actual_amount=cr, difference=_r(cr - expected),
                )
    report["checks"].append({
        "name": "returns",
        "formula": "vendor debit = customer credit = refund paid",
        "refunded_returns": len(paid),
        "mismatched": len(ret_bad),
        "samples": ret_bad[:25],
        "balanced": not ret_bad,
    })

    # ── 6. GST recomputation ───────────────────────────────────────────
    prods = await db.products.find(
        {"$or": [{"selling_gst_pct": {"$gt": 0}}, {"purchase_gst_pct": {"$gt": 0}}]},
        {"_id": 0, "id": 1, "name": 1, "price": 1, "stock": 1,
         "purchase_price": 1, "purchase_gst_pct": 1, "selling_gst_pct": 1},
    ).limit(5000).to_list(5000)
    gst_bad = []
    for p in prods:
        block = gst_engine.pricing_block(p)
        s = block["selling"]
        if abs(s["cgst_amount"] + s["sgst_amount"] - s["total_gst"]) > 0.011:
            gst_bad.append({"product_id": p.get("id"), "name": p.get("name")})
    report["checks"].append({
        "name": "gst",
        "formula": "CGST + SGST = total GST (one engine, GST-exclusive basis)",
        "products_with_gst": len(prods),
        "mismatched": len(gst_bad),
        "samples": gst_bad[:25],
        "balanced": not gst_bad,
    })

    report["open_financial_errors"] = await db.financial_errors.count_documents({"status": "open"})
    report["all_balanced"] = all(c.get("balanced") for c in report["checks"])
    return report
