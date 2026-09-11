"""Purchase-cashback engine — the ONE place cashback maths ever happens.

Business model (Jun-2026 cutover):

    REAL PURCHASE  →  SUCCESSFUL DELIVERY  →  CASHBACK  →  CUSTOMER WALLET

Cashback is earned on eligible marketplace purchases only. It never depends
on recruiting, referring, team size or network activity.

Hard rules enforced here
------------------------
* **Ceiling 10%.** `MAX_CASHBACK_PCT` clamps every vendor / product /
  campaign value. There is no code path that can pay more.
* **Only after delivery.** `settle_order_cashback` is called from the
  delivered-status transition, never at checkout.
* **Exactly once.** A `cashback_ledger` document keyed `CB:{order_id}` is
  inserted with a unique `_id` before any money moves, so duplicate
  delivery webhooks / retries / double taps cannot double-credit.
* **Never a negative seller wallet.** If the seller cannot fund it, the
  cashback becomes *pending*, or Slangcart fronts it and books a seller
  outstanding — the seller wallet is never pushed below zero.
* **Never destroy money.** Every credit has a matching debit; reversals are
  new rows, the original transaction is preserved.

Funding waterfall on delivery
-----------------------------
1. Seller wallet has the money            → seller wallet → customer wallet
2. Seller short, platform funding ON      → treasury → customer wallet, and
                                            a seller outstanding is booked
3. Seller short, platform funding OFF     → PENDING ("arriving soon"), admin
                                            can fund it manually later
"""
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from core.db import db
from core.utils import now_utc, get_settings

logger = logging.getLogger(__name__)

# HARD platform ceiling. Mirrors core.config.MAX_CASHBACK_PCT.
MAX_CASHBACK_PCT = 10.0


def clamp_pct(value: Any) -> float:
    """Coerce anything into a legal cashback percentage (0 .. 10)."""
    try:
        pct = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    if pct != pct or pct < 0:  # NaN or negative
        return 0.0
    return round(min(pct, MAX_CASHBACK_PCT), 2)


def cashback_amount(purchase_amount: float, pct: Any) -> float:
    """THE formula. Used by the product page, the cart, checkout and
    settlement so no two screens can ever disagree.

        cashback = eligible purchase amount × cashback % ÷ 100
    """
    try:
        base = float(purchase_amount or 0)
    except (TypeError, ValueError):
        return 0.0
    if base <= 0:
        return 0.0
    return round(base * clamp_pct(pct) / 100.0, 2)


def product_cashback_pct(product: Dict[str, Any], settings: Optional[Dict[str, Any]] = None) -> float:
    """Effective cashback % for a product. The vendor's own value wins; if
    they never set one the admin default applies. Both are clamped."""
    settings = settings or {}
    if not settings.get("cashback_enabled", True):
        return 0.0
    raw = product.get("cashback_pct")
    if raw in (None, ""):
        raw = settings.get("default_cashback_pct") or 0
    return clamp_pct(raw)


def order_cashback_total(order: Dict[str, Any]) -> float:
    """Cashback owed on an order, recomputed from the per-line percentages
    that were frozen onto the order at checkout (so a later vendor edit can
    never change what an existing customer was promised)."""
    total = 0.0
    for it in order.get("items") or []:
        total += cashback_amount(it.get("line_total"), it.get("cashback_pct"))
    return round(total, 2)


async def _txn(doc: Dict[str, Any]) -> None:
    await db.transactions.insert_one({"id": str(uuid.uuid4()), **doc})


async def settle_order_cashback(
    order: Dict[str, Any],
    *,
    credit_admin_bucket,
    notify=None,
) -> Dict[str, Any]:
    """Credit the customer's cashback for a DELIVERED order. Idempotent.

    `credit_admin_bucket` and `notify` are injected so this module stays
    free of any import back into server.py.
    """
    order_id = order.get("id")
    if not order_id:
        return {"ok": False, "reason": "no_order_id"}

    settings = await get_settings()
    if not settings.get("cashback_enabled", True):
        return {"ok": True, "amount": 0.0, "reason": "cashback_disabled"}

    amount = order_cashback_total(order)
    if amount <= 0.009:
        return {"ok": True, "amount": 0.0, "reason": "no_eligible_cashback"}

    ts = now_utc().isoformat()
    ledger_id = f"CB:{order_id}"
    # ── DUPLICATE GUARD ──────────────────────────────────────────────────
    # Claim the order BEFORE any money moves. A second delivery
    # notification, webhook retry or concurrent request loses the race and
    # exits here, so cashback can never be paid twice.
    try:
        await db.cashback_ledger.insert_one({
            "_id": ledger_id,
            "order_id": order_id,
            "order_number": order.get("order_number"),
            "group_id": order.get("group_id"),
            "user_id": order.get("user_id"),
            "vendor_id": order.get("vendor_id"),
            "amount": amount,
            "status": "processing",
            "created_at": ts,
        })
    except Exception:
        existing = await db.cashback_ledger.find_one({"_id": ledger_id})
        return {
            "ok": True,
            "amount": float((existing or {}).get("amount") or 0),
            "status": (existing or {}).get("status"),
            "reason": "already_settled",
        }

    customer_id = order.get("user_id")
    vendor_id = order.get("vendor_id")
    order_no = order.get("order_number") or order_id[:8]
    vendor_name = order.get("vendor_name") or "the seller"

    # ── 1. Seller wallet funds it ────────────────────────────────────────
    funded_by = None
    if vendor_id:
        debited = await db.users.update_one(
            {"id": vendor_id, "wallet_balance": {"$gte": amount}},
            {"$inc": {"wallet_balance": -amount}},
        )
        if debited.modified_count == 1:
            funded_by = "vendor"
            await _txn({
                "user_id": vendor_id,
                "type": "cashback_funding",
                "amount": -amount,
                "status": "success",
                "description": f"Cashback funded for order {order_no}",
                "order_id": order_id,
                "cashback_ledger_id": ledger_id,
                "created_at": ts,
            })

    # ── 2. Slangcart fronts it, seller owes it back ──────────────────────
    if funded_by is None and settings.get("cashback_platform_funding_enabled", True):
        funded_by = "platform"
        await credit_admin_bucket("cashback_funded", -amount, also_total_earned=False)
        await _txn({
            "user_id": None,
            "type": "cashback_platform_funded",
            "amount": -amount,
            "status": "success",
            "description": (
                f"Slangcart funded cashback for order {order_no} — "
                f"recoverable from {vendor_name}"
            ),
            "order_id": order_id,
            "vendor_id": vendor_id,
            "cashback_ledger_id": ledger_id,
            "created_at": ts,
        })
        if vendor_id:
            await db.vendor_outstanding.insert_one({
                "id": str(uuid.uuid4()),
                "vendor_id": vendor_id,
                "vendor_name": vendor_name,
                "kind": "cashback",
                "amount": amount,
                "recovered": 0.0,
                "status": "open",
                "order_id": order_id,
                "order_number": order_no,
                "cashback_ledger_id": ledger_id,
                "created_at": ts,
            })
            await db.users.update_one(
                {"id": vendor_id},
                {"$inc": {"cashback_outstanding": amount}},
            )
            await _txn({
                "user_id": vendor_id,
                "type": "vendor_outstanding",
                "amount": 0.0,
                "outstanding_amount": amount,
                "status": "success",
                "description": (
                    f"Cashback outstanding \u20b9{amount:g} — Slangcart paid your "
                    f"customer for order {order_no}. Add money to settle."
                ),
                "order_id": order_id,
                "cashback_ledger_id": ledger_id,
                "created_at": ts,
            })

    # ── 3. Nobody can fund it → PENDING ──────────────────────────────────
    if funded_by is None:
        await db.cashback_ledger.update_one(
            {"_id": ledger_id},
            {"$set": {"status": "pending", "pending_reason": "vendor_wallet_short", "updated_at": ts}},
        )
        await _txn({
            "user_id": customer_id,
            "type": "cashback_pending",
            "amount": amount,
            "status": "pending",
            "description": f"Cashback arriving soon from {vendor_name} — order {order_no}",
            "order_id": order_id,
            "vendor_id": vendor_id,
            "cashback_ledger_id": ledger_id,
            "created_at": ts,
        })
        await db.orders.update_one(
            {"id": order_id},
            {"$set": {
                "cashback_amount": amount,
                "cashback_status": "pending",
                "cashback_vendor_name": vendor_name,
            }},
        )
        if notify:
            await notify(
                customer_id, "cashback", "Cashback arriving soon",
                f"\u20b9{amount:g} cashback for order {order_no} is on its way from {vendor_name}.",
            )
        return {"ok": True, "amount": amount, "status": "pending"}

    # ── Credit the customer ──────────────────────────────────────────────
    await db.users.update_one({"id": customer_id}, {"$inc": {"wallet_balance": amount}})
    await _txn({
        "user_id": customer_id,
        "type": "cashback_credit",
        "amount": amount,
        "status": "success",
        "description": f"Cashback on delivered order {order_no} from {vendor_name}",
        "order_id": order_id,
        "vendor_id": vendor_id,
        "funded_by": funded_by,
        "cashback_ledger_id": ledger_id,
        "created_at": ts,
    })
    await db.cashback_ledger.update_one(
        {"_id": ledger_id},
        {"$set": {"status": "paid", "funded_by": funded_by, "paid_at": ts}},
    )
    await db.orders.update_one(
        {"id": order_id},
        {"$set": {
            "cashback_amount": amount,
            "cashback_status": "paid",
            "cashback_funded_by": funded_by,
            "cashback_paid_at": ts,
        }},
    )
    if notify:
        await notify(
            customer_id, "cashback", f"\u20b9{amount:g} cashback credited",
            f"Your cashback for order {order_no} is in your Slangcart wallet.",
        )
    return {"ok": True, "amount": amount, "status": "paid", "funded_by": funded_by}


async def fund_pending_cashback(
    order_id: str,
    *,
    credit_admin_bucket,
    notify=None,
    by: str = "admin",
) -> Dict[str, Any]:
    """Admin-controlled manual funding of a PENDING cashback. Slangcart pays
    the customer now and books the amount as recoverable from the seller."""
    ledger_id = f"CB:{order_id}"
    row = await db.cashback_ledger.find_one({"_id": ledger_id})
    if not row:
        return {"ok": False, "reason": "not_found"}
    if row.get("status") != "pending":
        return {"ok": False, "reason": f"status_is_{row.get('status')}"}

    amount = round(float(row.get("amount") or 0), 2)
    if amount <= 0.009:
        return {"ok": False, "reason": "zero_amount"}

    # Re-claim atomically so two admins tapping at once cannot both pay.
    claim = await db.cashback_ledger.update_one(
        {"_id": ledger_id, "status": "pending"},
        {"$set": {"status": "processing"}},
    )
    if claim.modified_count != 1:
        return {"ok": False, "reason": "already_processing"}

    ts = now_utc().isoformat()
    customer_id = row.get("user_id")
    vendor_id = row.get("vendor_id")
    order_no = row.get("order_number") or order_id[:8]
    vendor = await db.users.find_one({"id": vendor_id}, {"_id": 0, "store_name": 1, "name": 1}) if vendor_id else None
    vendor_name = (vendor or {}).get("store_name") or (vendor or {}).get("name") or "the seller"

    # Prefer the seller's own money if it has arrived since.
    funded_by = None
    if vendor_id:
        debited = await db.users.update_one(
            {"id": vendor_id, "wallet_balance": {"$gte": amount}},
            {"$inc": {"wallet_balance": -amount}},
        )
        if debited.modified_count == 1:
            funded_by = "vendor"
            await _txn({
                "user_id": vendor_id,
                "type": "cashback_funding",
                "amount": -amount,
                "status": "success",
                "description": f"Cashback funded for order {order_no} (released by admin)",
                "order_id": order_id,
                "cashback_ledger_id": ledger_id,
                "created_at": ts,
            })

    if funded_by is None:
        funded_by = "platform"
        await credit_admin_bucket("cashback_funded", -amount, also_total_earned=False)
        await _txn({
            "user_id": None,
            "type": "cashback_platform_funded",
            "amount": -amount,
            "status": "success",
            "description": (
                f"Slangcart funded pending cashback for order {order_no} "
                f"(manual release by {by}) — recoverable from {vendor_name}"
            ),
            "order_id": order_id,
            "vendor_id": vendor_id,
            "cashback_ledger_id": ledger_id,
            "created_at": ts,
        })
        if vendor_id:
            await db.vendor_outstanding.insert_one({
                "id": str(uuid.uuid4()),
                "vendor_id": vendor_id,
                "vendor_name": vendor_name,
                "kind": "cashback",
                "amount": amount,
                "recovered": 0.0,
                "status": "open",
                "order_id": order_id,
                "order_number": order_no,
                "cashback_ledger_id": ledger_id,
                "manual_release_by": by,
                "created_at": ts,
            })
            await db.users.update_one({"id": vendor_id}, {"$inc": {"cashback_outstanding": amount}})

    await db.users.update_one({"id": customer_id}, {"$inc": {"wallet_balance": amount}})
    await _txn({
        "user_id": customer_id,
        "type": "cashback_credit",
        "amount": amount,
        "status": "success",
        "description": f"Cashback on order {order_no} from {vendor_name}",
        "order_id": order_id,
        "vendor_id": vendor_id,
        "funded_by": funded_by,
        "cashback_ledger_id": ledger_id,
        "created_at": ts,
    })
    # Close the pending placeholder so the wallet never shows it twice.
    await db.transactions.update_many(
        {"order_id": order_id, "type": "cashback_pending", "status": "pending"},
        {"$set": {"status": "settled", "settled_at": ts}},
    )
    await db.cashback_ledger.update_one(
        {"_id": ledger_id},
        {"$set": {"status": "paid", "funded_by": funded_by, "paid_at": ts, "released_by": by}},
    )
    await db.orders.update_one(
        {"id": order_id},
        {"$set": {"cashback_status": "paid", "cashback_funded_by": funded_by, "cashback_paid_at": ts}},
    )
    if notify:
        await notify(
            customer_id, "cashback", f"\u20b9{amount:g} cashback credited",
            f"Your pending cashback for order {order_no} has been released.",
        )
    return {"ok": True, "amount": amount, "funded_by": funded_by}


async def reverse_order_cashback(
    order: Dict[str, Any],
    reason: str,
    *,
    credit_admin_bucket,
    notify=None,
) -> Dict[str, Any]:
    """Claw back cashback when a delivered order is returned.

    Owner rule: ALWAYS claw back the full cashback. Whatever the wallet
    cannot cover becomes `cashback_recoverable` on the order, and the
    refund-payout code nets it off the money handed back to the customer —
    so the customer can never keep cashback on a product they returned, and
    the books stay exact either way.

    Returns `{reversed, from_wallet, netted_off_refund}`.
    """
    order_id = order.get("id")
    ledger_id = f"CB:{order_id}"
    row = await db.cashback_ledger.find_one({"_id": ledger_id})
    if not row:
        return {"reversed": 0.0, "from_wallet": 0.0, "netted_off_refund": 0.0, "reason": "no_cashback"}

    settings = await get_settings()
    if not settings.get("cashback_clawback_on_return", True):
        return {"reversed": 0.0, "from_wallet": 0.0, "netted_off_refund": 0.0, "reason": "clawback_disabled"}

    ts = now_utc().isoformat()
    amount = round(float(row.get("amount") or 0), 2)
    status = row.get("status")
    customer_id = row.get("user_id")
    vendor_id = row.get("vendor_id")
    order_no = row.get("order_number") or str(order_id)[:8]

    # Never-credited cashback: just cancel the promise, no money moves.
    if status != "paid":
        await db.cashback_ledger.update_one(
            {"_id": ledger_id},
            {"$set": {"status": "cancelled", "cancelled_at": ts, "cancel_reason": reason}},
        )
        await db.transactions.update_many(
            {"order_id": order_id, "type": "cashback_pending", "status": "pending"},
            {"$set": {"status": "cancelled", "cancelled_at": ts}},
        )
        await db.orders.update_one({"id": order_id}, {"$set": {"cashback_status": "cancelled"}})
        return {"reversed": 0.0, "from_wallet": 0.0, "netted_off_refund": 0.0, "reason": "was_not_paid"}

    # Take what the wallet can cover, atomically, without ever going below 0.
    cust = await db.users.find_one({"id": customer_id}, {"_id": 0, "wallet_balance": 1})
    held = round(float((cust or {}).get("wallet_balance") or 0), 2)
    from_wallet = round(max(0.0, min(amount, held)), 2)
    shortfall = round(amount - from_wallet, 2)
    if from_wallet > 0:
        await db.users.update_one({"id": customer_id}, {"$inc": {"wallet_balance": -from_wallet}})
        await _txn({
            "user_id": customer_id,
            "type": "cashback_reversal",
            "amount": -from_wallet,
            "status": "success",
            "description": f"Cashback reversed on returned order {order_no} — {reason}",
            "order_id": order_id,
            "cashback_ledger_id": ledger_id,
            "reverses_cashback": True,
            "created_at": ts,
        })

    # Give the funder their money back for the part we recovered in cash.
    funded_by = row.get("funded_by")
    if from_wallet > 0:
        if funded_by == "vendor" and vendor_id:
            await db.users.update_one({"id": vendor_id}, {"$inc": {"wallet_balance": from_wallet}})
            await _txn({
                "user_id": vendor_id,
                "type": "cashback_funding_refund",
                "amount": from_wallet,
                "status": "success",
                "description": f"Cashback funding returned — order {order_no} was returned",
                "order_id": order_id,
                "cashback_ledger_id": ledger_id,
                "created_at": ts,
            })
        elif funded_by == "platform":
            await credit_admin_bucket("cashback_funded", from_wallet, also_total_earned=False)
            await _txn({
                "user_id": None,
                "type": "cashback_vendor_recovery",
                "amount": from_wallet,
                "status": "success",
                "description": f"Fronted cashback recovered — order {order_no} was returned",
                "order_id": order_id,
                "vendor_id": vendor_id,
                "cashback_ledger_id": ledger_id,
                "created_at": ts,
            })
            if vendor_id:
                await db.vendor_outstanding.update_many(
                    {"cashback_ledger_id": ledger_id, "status": "open"},
                    {"$set": {"status": "closed_on_return", "closed_at": ts},
                     "$inc": {"recovered": from_wallet}},
                )
                await db.users.update_one(
                    {"id": vendor_id},
                    {"$inc": {"cashback_outstanding": -from_wallet}},
                )

    await db.cashback_ledger.update_one(
        {"_id": ledger_id},
        {"$set": {
            "status": "reversed",
            "reversed_at": ts,
            "reverse_reason": reason,
            "reversed_from_wallet": from_wallet,
            "reverse_shortfall": shortfall,
        }},
    )
    await db.orders.update_one(
        {"id": order_id},
        {"$set": {
            "cashback_status": "reversed",
            "cashback_reversed_at": ts,
            # The refund payout MUST subtract this before paying the
            # customer back by UPI / cash.
            "cashback_recoverable": shortfall,
        }},
    )
    if notify and amount > 0:
        tail = (
            f" \u20b9{shortfall:g} will be deducted from your refund."
            if shortfall > 0.009 else ""
        )
        await notify(
            customer_id, "cashback", "Cashback reversed",
            f"\u20b9{amount:g} cashback for order {order_no} was reversed because the "
            f"order was returned.{tail}",
        )
    return {
        "reversed": amount,
        "from_wallet": from_wallet,
        "netted_off_refund": shortfall,
        "funded_by": funded_by,
    }


async def recover_vendor_outstanding(
    vendor_id: str,
    amount: float,
    *,
    credit_admin_bucket,
    note: str = "Seller settled outstanding cashback",
) -> Dict[str, Any]:
    """Apply money a seller has paid Slangcart against their open cashback
    outstanding, oldest first. The customer is NEVER credited again — this
    only settles the debt between the seller and the platform."""
    remaining = round(max(0.0, float(amount or 0)), 2)
    if remaining <= 0.009:
        return {"applied": 0.0, "rows": 0}

    ts = now_utc().isoformat()
    applied = 0.0
    rows = 0
    cursor = db.vendor_outstanding.find(
        {"vendor_id": vendor_id, "status": "open", "kind": "cashback"},
    ).sort("created_at", 1)
    async for row in cursor:
        if remaining <= 0.009:
            break
        owed = round(float(row.get("amount") or 0) - float(row.get("recovered") or 0), 2)
        if owed <= 0.009:
            await db.vendor_outstanding.update_one(
                {"id": row["id"]}, {"$set": {"status": "settled", "settled_at": ts}},
            )
            continue
        take = round(min(owed, remaining), 2)
        remaining = round(remaining - take, 2)
        applied = round(applied + take, 2)
        rows += 1
        fully = take >= owed - 0.009
        await db.vendor_outstanding.update_one(
            {"id": row["id"]},
            {"$inc": {"recovered": take},
             "$set": {"status": "settled" if fully else "open",
                      **({"settled_at": ts} if fully else {})}},
        )

    if applied > 0:
        await db.users.update_one({"id": vendor_id}, {"$inc": {"cashback_outstanding": -applied}})
        await credit_admin_bucket("cashback_funded", applied, also_total_earned=False)
        await _txn({
            "user_id": vendor_id,
            "type": "cashback_vendor_recovery",
            "amount": applied,
            "status": "success",
            "description": f"{note} \u2014 \u20b9{applied:g} recovered",
            "vendor_id": vendor_id,
            "created_at": ts,
        })
    return {"applied": applied, "rows": rows, "unapplied": remaining}


async def customer_cashback_summary(user_id: str) -> Dict[str, Any]:
    """Wallet-screen figures. Derived from the ledger, so it always matches
    what the transactions list shows."""
    async def _sum(match: Dict[str, Any]) -> float:
        agg = await db.transactions.aggregate([
            {"$match": match},
            {"$group": {"_id": None, "t": {"$sum": "$amount"}}},
        ]).to_list(1)
        return round(float(agg[0]["t"]), 2) if agg else 0.0

    credited = await _sum({"user_id": user_id, "type": "cashback_credit", "status": "success"})
    reversed_amt = abs(await _sum({"user_id": user_id, "type": "cashback_reversal", "status": "success"}))
    pending = await _sum({"user_id": user_id, "type": "cashback_pending", "status": "pending"})
    pending_rows = await db.cashback_ledger.find(
        {"user_id": user_id, "status": "pending"},
        {"_id": 0, "order_number": 1, "amount": 1, "vendor_id": 1},
    ).to_list(50)
    return {
        "cashback_earned": round(credited - reversed_amt, 2),
        "pending_cashback": pending,
        "pending_orders": pending_rows,
    }
