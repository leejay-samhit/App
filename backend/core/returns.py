"""Returns · Refunds · Inventory restoration — Phase 2 (Jun-2026).

THE one place a delivered shop order can travel backwards. Nothing else in
the codebase is allowed to move return money, restore stock or claw back
cashback, so App, Web, Vendor and Admin can never disagree.

Money model (owner's Phase-2 spec)
----------------------------------
* **Refund direction is always `vendor wallet → customer wallet`**, whatever
  the original payment method was (wallet, COD or Razorpay). COD cash was
  physically collected by the vendor, so the vendor is the payer; an online
  payment was already credited to the vendor, so the vendor is the payer
  there too. No money is ever *generated*, only moved back.
* **Partial returns refund the returned line only.** The amount comes from
  the line that was actually charged (`line_total ÷ qty × returned_qty`),
  never re-derived from the live product price.
* **Delivery charge is NOT refunded** unless
  `settings.return_delivery_refundable` is switched on, and then it is a
  separate ledger component — it is never mixed into the item refund.
* **Cashback is reversed pro-rata for the returned items only**, and only
  the part that was actually credited.
* **Vendor balance safety.** If the vendor wallet cannot cover the refund,
  NOTHING is deducted: the return parks in `refund_pending`, a vendor
  outstanding + a financial error are written, and admin resolves it.
* **Duplicate-proof.** Every money row carries an `idempotency_key`
  (unique index) and every stock restoration is claimed in
  `inventory_adjustments` with a unique `_id`, so a retried request, a
  double tap or a replayed webhook can only ever act once.

Flow
----
delivered → return_eligible → requested → approved → returned (picked up)
          → refunded (+ inventory restored) → completed
`rejected` and `refund_pending` are the two off-ramps.
"""
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from core import seq_ids, shop_money
from core.db import db
from core.utils import get_settings, now_utc

logger = logging.getLogger(__name__)

# Sep-2026 owner's rule — the return clock is MINUTES, not days:
#   * the CUSTOMER has 10 minutes after delivery to raise a return
#   * the VENDOR then has 24 hours to accept / collect it
# Both are settings-overridable but these are the shipped defaults.
DEFAULT_CUSTOMER_WINDOW_MINUTES = 10
DEFAULT_VENDOR_WINDOW_HOURS = 24
DEFAULT_WINDOW_DAYS = 7          # legacy fallback for pre-Sep-2026 settings

STAGES = (
    "delivered",
    "return_eligible",
    "requested",
    "vendor_review",
    "approved",
    "returned",
    "refund_processed",
    "inventory_restored",
    "completed",
)
OPEN_STATUSES = ("requested", "approved", "returned", "refund_pending")


class ReturnError(Exception):
    """A return could not be created/advanced. Carries a human message."""


async def ensure_indexes() -> None:
    try:
        await db.returns.create_index("order_id")
        await db.returns.create_index("user_id")
        await db.returns.create_index("vendor_id")
        await db.returns.create_index("status")
        await db.inventory_adjustments.create_index("return_id")
    except Exception as err:  # pragma: no cover
        logger.warning(f"returns index setup: {str(err)[:200]}")


# ── helpers ────────────────────────────────────────────────────────────

def _f(v: Any) -> float:
    try:
        x = float(v or 0)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if x != x else x


def _unit_charged(item: Dict[str, Any]) -> float:
    """What the customer was ACTUALLY charged per unit on this order line."""
    qty = int(_f(item.get("qty")) or 1)
    line = _f(item.get("line_total"))
    if line > 0 and qty > 0:
        return round(line / qty, 2)
    return round(_f(item.get("price")), 2)


def _line_key(item: Dict[str, Any]) -> str:
    return f"{item.get('product_id')}|{item.get('variant_id') or ''}"


async def _window_minutes() -> int:
    """How long the CUSTOMER has, after delivery, to raise a return."""
    s = await get_settings()
    raw = s.get("return_window_minutes")
    if raw is not None:
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            pass
    return DEFAULT_CUSTOMER_WINDOW_MINUTES


async def _vendor_window_hours() -> int:
    """How long the VENDOR has, after delivery, to accept/collect a return."""
    s = await get_settings()
    raw = s.get("return_vendor_window_hours")
    if raw is not None:
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            pass
    return DEFAULT_VENDOR_WINDOW_HOURS


def _shift(delivered_at: Optional[str], *, minutes: int = 0, hours: int = 0) -> Optional[str]:
    if not delivered_at:
        return None
    from datetime import datetime, timedelta, timezone
    try:
        dt = datetime.fromisoformat(str(delivered_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt + timedelta(minutes=minutes, hours=hours)).isoformat()


def _still_open(deadline: Optional[str]) -> Tuple[bool, int]:
    """(within window, whole seconds left) for an ISO deadline."""
    if not deadline:
        return False, 0
    from datetime import datetime, timezone
    try:
        dl = datetime.fromisoformat(deadline)
    except ValueError:
        return False, 0
    if dl.tzinfo is None:
        dl = dl.replace(tzinfo=timezone.utc)
    gap = (dl - now_utc()).total_seconds()
    return (gap > 0), max(0, int(gap))


async def returned_qty_map(order_id: str) -> Dict[str, int]:
    """product|variant → quantity already returned (or in an open return),
    so the same unit can never be returned twice."""
    rows = await db.returns.find(
        {"order_id": order_id, "status": {"$nin": ["rejected", "cancelled"]}},
        {"_id": 0, "items": 1},
    ).to_list(500)
    out: Dict[str, int] = {}
    for r in rows:
        for it in r.get("items") or []:
            k = f"{it.get('product_id')}|{it.get('variant_id') or ''}"
            out[k] = out.get(k, 0) + int(_f(it.get("qty")))
    return out


async def order_return_state(order: Dict[str, Any]) -> Dict[str, Any]:
    """Everything the UI needs to decide between Cancel / Return / nothing.

    Sep-2026 two-clock model:
      * customer clock — 10 minutes from delivery to RAISE a return
      * vendor clock   — 24 hours from delivery to ACCEPT / collect it
    A DELIVERED order inside the customer clock shows **Return** (never
    Cancel). Past it, it is simply **Completed** for the customer, while the
    vendor can still act on anything already raised until their 24 h is up.
    """
    minutes = await _window_minutes()
    vendor_hours = await _vendor_window_hours()
    status = (order.get("status") or "").lower()
    delivered = status == "delivered"
    delivered_at = order.get("delivered_at")
    deadline = _shift(delivered_at, minutes=minutes)
    vendor_deadline = _shift(delivered_at, hours=vendor_hours)
    within, seconds_left = _still_open(deadline)
    vendor_within, vendor_seconds_left = _still_open(vendor_deadline)
    done = await returned_qty_map(order.get("id") or "")
    items: List[Dict[str, Any]] = []
    for it in order.get("items") or []:
        qty = int(_f(it.get("qty")) or 1)
        used = int(done.get(_line_key(it), 0))
        items.append({
            "product_id": it.get("product_id"),
            "variant_id": it.get("variant_id"),
            "variant_label": it.get("variant_label") or "",
            "name": it.get("name"),
            "image_url": it.get("image_url") or "",
            "qty": qty,
            "returned_qty": used,
            "returnable_qty": max(0, qty - used),
            "unit_price": _unit_charged(it),
            "line_total": round(_f(it.get("line_total")), 2),
            "cashback_pct": round(_f(it.get("cashback_pct")), 2),
        })
    any_returnable = any(i["returnable_qty"] > 0 for i in items)
    eligible = bool(delivered and within and any_returnable)
    return {
        # Customer clock
        "return_window_minutes": minutes,
        "delivered_at": delivered_at,
        "return_deadline": deadline,
        "seconds_left": seconds_left if delivered else 0,
        "minutes_left": (seconds_left + 59) // 60 if delivered else 0,
        "return_eligible": eligible,
        "window_expired": bool(delivered and deadline and not within),
        # Vendor clock
        "vendor_window_hours": vendor_hours,
        "vendor_return_deadline": vendor_deadline,
        "vendor_seconds_left": vendor_seconds_left if delivered else 0,
        "vendor_hours_left": (vendor_seconds_left + 3599) // 3600 if delivered else 0,
        "vendor_can_act": bool(delivered and vendor_within),
        "vendor_window_expired": bool(delivered and vendor_deadline and not vendor_within),
        "can_cancel": status == "placed" and not order.get("delivery_info_updated_at"),
        "display_status": (
            "completed" if (delivered and (not within or not any_returnable)) else status
        ),
        "items": items,
        "has_returns": any(i["returned_qty"] > 0 for i in items),
    }


def _stage(name: str, actor_name: str, actor_role: str, note: str = "") -> Dict[str, Any]:
    return {
        "stage": name,
        "at": now_utc().isoformat(),
        "by_name": actor_name,
        "by_role": actor_role,
        "note": note or "",
    }


async def _push_stage(return_id: str, stage: Dict[str, Any], **set_fields) -> None:
    upd: Dict[str, Any] = {"$push": {"timeline": stage}}
    if set_fields:
        upd["$set"] = {**set_fields, "updated_at": stage["at"]}
    await db.returns.update_one({"id": return_id}, upd)


# ── 1. Create the return request ───────────────────────────────────────

async def create_return(
    order: Dict[str, Any],
    customer: Dict[str, Any],
    requested: List[Dict[str, Any]],
    reason: str,
    comments: str = "",
) -> Dict[str, Any]:
    """Customer asks to send item(s) back. Validates the 7-day window, the
    quantities and that nothing is being returned twice."""
    state = await order_return_state(order)
    if (order.get("status") or "").lower() != "delivered":
        raise ReturnError("Only delivered orders can be returned.")
    if state["window_expired"]:
        raise ReturnError(
            f"The {state['return_window_minutes']}-minute return window for this order has closed."
        )
    by_key = {f"{i['product_id']}|{i.get('variant_id') or ''}": i for i in state["items"]}

    lines: List[Dict[str, Any]] = []
    refund_total = 0.0
    cashback_expected = 0.0
    for req in requested or []:
        key = f"{req.get('product_id')}|{req.get('variant_id') or ''}"
        src = by_key.get(key)
        if not src:
            raise ReturnError("That product is not part of this order.")
        qty = int(_f(req.get("qty")) or 0)
        if qty <= 0:
            continue
        if qty > src["returnable_qty"]:
            raise ReturnError(
                f"{src['name']}: only {src['returnable_qty']} unit(s) can still be returned."
            )
        line_refund = round(src["unit_price"] * qty, 2)
        cb = round(line_refund * src["cashback_pct"] / 100.0, 2)
        lines.append({
            "product_id": src["product_id"],
            "variant_id": src["variant_id"],
            "variant_label": src["variant_label"],
            "name": src["name"],
            "image_url": src["image_url"],
            "qty": qty,
            "unit_price": src["unit_price"],
            "refund_amount": line_refund,
            "cashback_pct": src["cashback_pct"],
            "cashback_reversal": cb,
            "original_line_total": src["line_total"],
        })
        refund_total = round(refund_total + line_refund, 2)
        cashback_expected = round(cashback_expected + cb, 2)

    if not lines:
        raise ReturnError("Pick at least one item to return.")

    settings = await get_settings()
    delivery_refundable = bool(settings.get("return_delivery_refundable", False))
    # Delivery is refunded only when the WHOLE order goes back and the
    # policy allows it — and always as its own ledger component.
    ordered_units = sum(int(i["qty"]) for i in state["items"])
    returned_units = sum(int(i["returned_qty"]) for i in state["items"])
    full_return = (returned_units + sum(int(li["qty"]) for li in lines)) >= ordered_units
    delivery_refund = (
        round(_f(order.get("delivery_charge")), 2)
        if (delivery_refundable and full_return) else 0.0
    )

    return_id = str(uuid.uuid4())
    ref = await seq_ids.get_or_create("refund", return_id)
    ts = now_utc().isoformat()
    actor = customer.get("name") or customer.get("email") or "Customer"
    doc = {
        "id": return_id,
        "return_number": ref,
        "order_id": order.get("id"),
        "order_number": order.get("order_number"),
        "group_id": order.get("group_id"),
        "user_id": order.get("user_id"),
        "customer_name": customer.get("name"),
        "customer_email": customer.get("email"),
        "vendor_id": order.get("vendor_id"),
        "vendor_name": order.get("vendor_name"),
        "items": lines,
        "item_refund": refund_total,
        "delivery_refund": delivery_refund,
        "delivery_refundable": delivery_refundable,
        "refund_amount": round(refund_total + delivery_refund, 2),
        "cashback_reversal_expected": cashback_expected,
        "cashback_reversed": 0.0,
        "cashback_netted_off_refund": 0.0,
        "refund_paid": 0.0,
        "full_return": bool(full_return),
        "reason": reason,
        "comments": comments or "",
        "original_payment_method": order.get("paid_via"),
        "original_payment_id": order.get("razorpay_payment_id") or order.get("payment_id"),
        "refund_method": "customer_wallet",
        "status": "requested",
        "refund_status": "not_started",
        "inventory_restored": False,
        "delivered_at": order.get("delivered_at"),
        "return_deadline": state["return_deadline"],
        "timeline": [
            _stage("delivered", actor, "system", "Order delivered"),
            _stage("return_eligible", actor, "system",
                   f"Eligible until {str(state['return_deadline'])[:10]}"),
            _stage("requested", actor, "customer", reason),
            _stage("vendor_review", order.get("vendor_name") or "Seller", "system",
                   "Awaiting seller review"),
        ],
        "created_at": ts,
        "updated_at": ts,
    }
    await db.returns.insert_one(dict(doc))
    await db.orders.update_one(
        {"id": order.get("id")},
        {"$set": {"has_returns": True, "last_return_id": return_id,
                  "return_status": "requested"}},
    )
    doc.pop("_id", None)
    return doc


# ── 2. Vendor review ───────────────────────────────────────────────────

async def decide_return(
    ret: Dict[str, Any], approve: bool, actor: Dict[str, Any], note: str = "",
) -> Dict[str, Any]:
    if ret.get("status") != "requested":
        raise ReturnError(f"This return is already {ret.get('status')}.")
    name = (
        actor.get("vendor_business_name") or actor.get("shop_name")
        or actor.get("name") or actor.get("email") or "Seller"
    )
    role = "admin" if actor.get("admin_role") or actor.get("is_admin") else "seller"
    if approve:
        await _push_stage(
            ret["id"], _stage("approved", name, role, note),
            status="approved", approved_at=now_utc().isoformat(), decision_note=note,
        )
        await db.orders.update_one({"id": ret["order_id"]}, {"$set": {"return_status": "approved"}})
    else:
        await _push_stage(
            ret["id"], _stage("rejected", name, role, note),
            status="rejected", rejected_at=now_utc().isoformat(), decision_note=note,
        )
        await db.orders.update_one({"id": ret["order_id"]}, {"$set": {"return_status": "rejected"}})
    return await db.returns.find_one({"id": ret["id"]}, {"_id": 0})


async def mark_product_returned(ret: Dict[str, Any], actor: Dict[str, Any], note: str = "") -> Dict[str, Any]:
    """Seller confirms the goods are physically back in the shop."""
    if ret.get("status") != "approved":
        raise ReturnError("The return must be approved before the product can be received.")
    name = (
        actor.get("vendor_business_name") or actor.get("shop_name")
        or actor.get("name") or actor.get("email") or "Seller"
    )
    await _push_stage(
        ret["id"], _stage("returned", name, "seller", note or "Product received back"),
        status="returned", product_returned_at=now_utc().isoformat(),
    )
    await db.orders.update_one({"id": ret["order_id"]}, {"$set": {"return_status": "returned"}})
    return await db.returns.find_one({"id": ret["id"]}, {"_id": 0})


# ── 3. Inventory restoration ───────────────────────────────────────────

async def restore_inventory(ret: Dict[str, Any], *, txn_id: Optional[str] = None) -> Dict[str, Any]:
    """Returned units go back on the shelf. Claimed per (return, line) in
    `inventory_adjustments`, so a duplicate API call restores nothing."""
    restored: List[Dict[str, Any]] = []
    for it in ret.get("items") or []:
        qty = int(_f(it.get("qty")))
        if qty <= 0:
            continue
        claim_id = f"INV:{ret['id']}:{it.get('product_id')}:{it.get('variant_id') or '-'}"
        try:
            await db.inventory_adjustments.insert_one({
                "_id": claim_id,
                "id": str(uuid.uuid4()),
                "kind": "return_restock",
                "product_id": it.get("product_id"),
                "variant_id": it.get("variant_id"),
                "product_name": it.get("name"),
                "order_id": ret.get("order_id"),
                "order_number": ret.get("order_number"),
                "return_id": ret.get("id"),
                "return_number": ret.get("return_number"),
                "vendor_id": ret.get("vendor_id"),
                "qty": qty,
                "txn_id": txn_id,
                "created_at": now_utc().isoformat(),
            })
        except Exception:
            continue                       # already restored — never twice
        if it.get("variant_id"):
            await db.products.update_one(
                {"id": it["product_id"], "variants.id": it["variant_id"]},
                {"$inc": {"variants.$.stock": qty, "stock": qty}},
            )
        else:
            await db.products.update_one({"id": it["product_id"]}, {"$inc": {"stock": qty}})
        fresh = await db.products.find_one({"id": it["product_id"]}, {"_id": 0, "stock": 1})
        restored.append({
            "product_id": it["product_id"],
            "variant_id": it.get("variant_id"),
            "qty": qty,
            "new_stock": int(_f((fresh or {}).get("stock"))),
        })
    if restored:
        await _push_stage(
            ret["id"],
            _stage("inventory_restored", "Slangcart", "system",
                   f"{sum(r['qty'] for r in restored)} unit(s) back in stock"),
            inventory_restored=True,
            inventory_restored_at=now_utc().isoformat(),
            inventory_rows=restored,
        )
    elif not ret.get("inventory_restored"):
        await db.returns.update_one({"id": ret["id"]}, {"$set": {"inventory_restored": True}})
    return {"restored": restored}


# ── 4. Refund ──────────────────────────────────────────────────────────

async def process_refund(
    ret: Dict[str, Any], *, credit_admin_bucket, notify=None, actor: Optional[Dict[str, Any]] = None,
    company_funded: bool = False,
) -> Dict[str, Any]:
    """Vendor wallet → customer wallet, exactly once, never negative.

    Order of operations matters:
      1. Reverse the cashback actually credited for the returned items. Any
         shortfall the customer's wallet could not cover is netted off the
         refund (so a customer can never keep cashback on a returned item).
      2. Debit the vendor for the NET payout. Insufficient balance parks the
         return in `refund_pending` with nothing deducted.
      3. Credit the customer.
      4. Restore stock, referencing the refund transaction.

    `company_funded=True` (admin only) covers a short seller out of the
    company treasury so the customer is never left waiting. The rupees are
    NOT forgiven: the same amount is booked as a vendor outstanding, which
    admin recovers from the seller's future sales.
    """
    return_id = ret["id"]
    if ret.get("refund_status") == "paid":
        return {"ok": True, "already": True, "refund_amount": _f(ret.get("refund_paid"))}
    if ret.get("status") not in ("returned", "refund_pending"):
        raise ReturnError("The product must be received back before the refund can be processed.")

    vendor_id = ret.get("vendor_id")
    customer_id = ret.get("user_id")
    gross = round(_f(ret.get("refund_amount")), 2)
    order = await db.orders.find_one({"id": ret.get("order_id")}, {"_id": 0}) or {}

    # 1 ── cashback claw-back for the returned lines only
    netted = round(_f(ret.get("cashback_netted_off_refund")), 2)
    reversed_cb = round(_f(ret.get("cashback_reversed")), 2)
    if ret.get("cashback_status") != "handled":
        try:
            from core.cashback import reverse_partial_cashback
            cb = await reverse_partial_cashback(
                order, round(_f(ret.get("cashback_reversal_expected")), 2),
                reason=f"return {ret.get('return_number')}",
                return_id=return_id,
                credit_admin_bucket=credit_admin_bucket,
                notify=notify,
            )
            reversed_cb = round(_f(cb.get("reversed")), 2)
            netted = round(_f(cb.get("netted_off_refund")), 2)
        except Exception as err:            # never block the refund on cashback
            logger.warning(f"return cashback reversal failed {return_id}: {str(err)[:200]}")
            await shop_money.record_financial_error(
                "return_cashback_reversal_failed", str(err),
                return_id=return_id, order_id=ret.get("order_id"),
            )
        await db.returns.update_one(
            {"id": return_id},
            {"$set": {"cashback_status": "handled", "cashback_reversed": reversed_cb,
                      "cashback_netted_off_refund": netted}},
        )

    payout = round(max(0.0, gross - netted), 2)
    ts = now_utc().isoformat()
    common = {
        "group": "returns",
        "order_id": ret.get("order_id"),
        "order_number": ret.get("order_number"),
        "vendor_id": vendor_id,
        "shop_name": ret.get("vendor_name"),
        "payment_id": ret.get("original_payment_id"),
        "payment_method": ret.get("original_payment_method"),
        "delivery_charge": round(_f(ret.get("delivery_refund")), 2),
        "extra": {
            "return_id": return_id,
            "return_number": ret.get("return_number"),
            "reverses_order": ret.get("order_id"),
        },
    }

    # 2 ── vendor debit (balance-safe)
    debit_row = None
    funded_by_company = 0.0
    if payout > 0.009 and vendor_id:
        try:
            debit_row = await shop_money.debit(
                vendor_id, shop_money.VENDOR_WALLET, payout,
                idempotency_key=f"RETURNDEBIT:{return_id}",
                txn_type="return_refund_debit",
                destination_wallet=shop_money.CUSTOMER_WALLET,
                settlement_status="refunded",
                description=(
                    f"Refund to customer for return {ret.get('return_number')} "
                    f"(order {ret.get('order_number')})"
                ),
                **{**common, "extra": {**common["extra"], "wallet_impact": "vendor_earnings_only"}},
            )
        except shop_money.InsufficientFunds as err:
            if not company_funded:
                await db.returns.update_one(
                    {"id": return_id},
                    {"$set": {"status": "refund_pending", "refund_status": "pending",
                              "refund_blocked_reason": "vendor_balance_short",
                              "refund_needed": payout, "updated_at": ts}},
                )
                await _push_stage(
                    return_id,
                    _stage("refund_pending", "Slangcart", "system",
                           f"Seller balance short — ₹{payout:.2f} refund awaiting admin"),
                )
                # Jun-2026 — ONE open row per return, however many times the
                # refund is retried. It used to insert a fresh row on every
                # attempt, so a seller's outstanding grew with each retry.
                await db.vendor_outstanding.update_one(
                    {"return_id": return_id, "kind": "return_refund"},
                    {"$set": {
                        "vendor_id": vendor_id,
                        "vendor_name": ret.get("vendor_name"),
                        "amount": payout,
                        "status": "open",
                        "order_id": ret.get("order_id"),
                        "order_number": ret.get("order_number"),
                        "updated_at": ts,
                    }, "$setOnInsert": {
                        "id": str(uuid.uuid4()), "recovered": 0.0, "created_at": ts,
                    }},
                    upsert=True,
                )
                await shop_money.record_financial_error(
                    "return_refund_unfunded", str(err),
                    return_id=return_id, order_id=ret.get("order_id"), vendor_id=vendor_id,
                    expected_amount=payout, actual_amount=round(err.available, 2),
                    difference=round(payout - err.available, 2),
                )
                await db.orders.update_one(
                    {"id": ret["order_id"]}, {"$set": {"return_status": "refund_pending"}},
                )
                # One nudge per return, not one per retry.
                already_nudged = await db.notifications.find_one({
                    "user_id": vendor_id,
                    "title": "Refund blocked — add money",
                    "return_id": return_id,
                })
                if notify and not already_nudged:
                    await notify(
                        vendor_id, "vendor", "Refund blocked — add money",
                        f"₹{payout:.0f} refund for return {ret.get('return_number')} could not be "
                        f"paid because your balance is short. Add money to clear it.",
                        extra={"return_id": return_id, "action_url": "/vendor/returns"},
                    )
                return {"ok": False, "reason": "vendor_balance_short", "needed": payout}

            # ── Company covers the shortfall (admin decision) ───────────
            # Take whatever the seller DOES have, then top up from the
            # treasury and book the top-up as a recoverable outstanding.
            from_vendor = round(min(payout, max(0.0, err.available)), 2)
            if from_vendor > 0.009:
                debit_row = await shop_money.debit(
                    vendor_id, shop_money.VENDOR_WALLET, from_vendor,
                    idempotency_key=f"RETURNDEBIT:{return_id}",
                    txn_type="return_refund_debit",
                    destination_wallet=shop_money.CUSTOMER_WALLET,
                    settlement_status="refunded",
                    description=(
                        f"Partial refund from seller balance for return "
                        f"{ret.get('return_number')} (order {ret.get('order_number')})"
                    ),
                    **{**common, "extra": {**common["extra"], "wallet_impact": "vendor_earnings_only"}},
                )
            funded_by_company = round(payout - from_vendor, 2)
            await shop_money.post(
                group="returns",
                txn_type="refund_company_funded",
                amount=funded_by_company,
                debit=funded_by_company,
                idempotency_key=f"RETURNCOMPANY:{return_id}",
                user_id=(actor or {}).get("id"),
                vendor_id=vendor_id,
                order_id=ret.get("order_id"),
                order_number=ret.get("order_number"),
                source_wallet="system_treasury",
                destination_wallet=shop_money.CUSTOMER_WALLET,
                settlement_status="company_funded",
                description=(
                    f"Company funded ₹{funded_by_company:.2f} of return "
                    f"{ret.get('return_number')} — recoverable from seller"
                ),
                extra={"return_id": return_id, "recoverable": True},
            )
            await credit_admin_bucket("shopping_margin", -funded_by_company, also_total_earned=False)
            # The "seller was short" row is replaced by the company-funded
            # one: the debt is the same rupees, now owed to the treasury.
            await db.vendor_outstanding.update_many(
                {"return_id": return_id, "kind": "return_refund", "status": "open"},
                {"$set": {"status": "superseded", "settled_at": ts,
                          "superseded_by": "return_refund_company_funded"}},
            )
            await db.vendor_outstanding.update_one(
                {"return_id": return_id, "kind": "return_refund_company_funded"},
                {"$set": {
                    "vendor_id": vendor_id,
                    "vendor_name": ret.get("vendor_name"),
                    "amount": funded_by_company,
                    "status": "open",
                    "order_id": ret.get("order_id"),
                    "order_number": ret.get("order_number"),
                    "updated_at": ts,
                }, "$setOnInsert": {
                    "id": str(uuid.uuid4()), "recovered": 0.0, "created_at": ts,
                }},
                upsert=True,
            )
            if notify:
                await notify(
                    vendor_id, "vendor", "Slangcart paid your refund",
                    f"₹{funded_by_company:.0f} of return {ret.get('return_number')} was paid by "
                    f"Slangcart because your balance was short. It will be recovered from your "
                    f"next sales.",
                )

    # 3 ── customer credit
    credit_row = None
    if payout > 0.009 and customer_id:
        credit_row = await shop_money.credit(
            customer_id, shop_money.CUSTOMER_WALLET, payout,
            idempotency_key=f"RETURNCREDIT:{return_id}",
            txn_type="return_refund_credit",
            source_wallet=shop_money.VENDOR_WALLET,
            settlement_status="refunded",
            description=(
                f"Refund received for return {ret.get('return_number')} "
                f"(order {ret.get('order_number')})"
                + (f" · ₹{netted:g} cashback recovered" if netted > 0.009 else "")
            ),
            **common,
        )

    txn_id = (credit_row or debit_row or {}).get("id")
    await db.returns.update_one(
        {"id": return_id},
        {"$set": {
            "status": "refunded",
            "refund_status": "paid",
            "refund_paid": payout,
            "refund_gross": gross,
            "refund_txn_id": txn_id,
            "vendor_debit_txn_id": (debit_row or {}).get("id"),
            "customer_credit_txn_id": (credit_row or {}).get("id"),
            "refunded_at": ts,
            "refund_blocked_reason": None,
            "refund_company_funded": funded_by_company,
            "updated_at": ts,
        }},
    )
    # The refund went through — any "seller balance short" row for this
    # return is now history.
    await db.vendor_outstanding.update_many(
        {"return_id": return_id, "kind": "return_refund", "status": "open"},
        {"$set": {"status": "settled", "settled_at": ts}},
    )
    await _push_stage(
        return_id,
        _stage("refund_processed",
               (actor or {}).get("name") or "Slangcart", "system",
               f"₹{payout:.2f} credited to the customer wallet"),
    )

    # 4 ── inventory
    await restore_inventory(
        await db.returns.find_one({"id": return_id}, {"_id": 0}) or ret, txn_id=txn_id,
    )

    # ── complete
    await _push_stage(
        return_id, _stage("completed", "Slangcart", "system", "Return closed"),
        status="completed", completed_at=now_utc().isoformat(),
    )
    remaining = await db.returns.count_documents(
        {"order_id": ret["order_id"], "status": {"$in": list(OPEN_STATUSES)}},
    )
    order_set: Dict[str, Any] = {"return_status": "completed" if not remaining else "partial"}
    if ret.get("full_return"):
        order_set["status"] = "returned"
        order_set["returned_at"] = ts
    await db.orders.update_one({"id": ret["order_id"]}, {"$set": order_set})

    if notify and customer_id:
        await notify(
            customer_id, "order", "Refund credited",
            f"₹{payout:.0f} for return {ret.get('return_number')} is in your Slangcart wallet.",
        )
    return {
        "ok": True,
        "refund_amount": payout,
        "gross": gross,
        "cashback_recovered": netted,
        "txn_id": txn_id,
    }


# ── 5. Reconciliation of one return (every rupee traceable) ────────────

async def return_audit(return_id: str) -> Dict[str, Any]:
    ret = await db.returns.find_one({"id": return_id}, {"_id": 0})
    if not ret:
        raise ReturnError("Return not found")
    rows = await db.transactions.find(
        {"return_id": return_id}, {"_id": 0},
    ).sort("created_at", 1).to_list(200)
    inv = await db.inventory_adjustments.find(
        {"return_id": return_id}, {"_id": 0},
    ).to_list(200)
    vendor_debit = round(sum(_f(r.get("debit")) for r in rows if r.get("type") == "return_refund_debit"), 2)
    customer_credit = round(sum(_f(r.get("credit")) for r in rows if r.get("type") == "return_refund_credit"), 2)
    expected = round(_f(ret.get("refund_paid")), 2)
    return {
        "return": ret,
        "transactions": rows,
        "inventory_adjustments": inv,
        "vendor_debit": vendor_debit,
        "customer_credit": customer_credit,
        "expected_refund": expected,
        "balanced": abs(vendor_debit - customer_credit) < 0.02 and abs(customer_credit - expected) < 0.02,
    }
