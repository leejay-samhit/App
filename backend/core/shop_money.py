"""Shop-order money engine — Phase 1 (Jun-2026).

THE one place shop money moves. Checkout, the delivered transition, the
cancel/refund paths and the vendor dashboards all call in here, so App, Web,
Admin and Vendor can never disagree: the backend is the only calculator.

Money model (owner's Phase-1 spec)
----------------------------------
* **No shop commission.** The vendor is entitled to 100 % of the goods value.
* **Vendor is credited the PREPAID money only** (wallet slice + Razorpay
  slice, delivery included). Cash-on-delivery money is collected physically
  by the vendor, so it is NEVER credited into a wallet and never faked into
  the customer's wallet.
* **Delivery fee is settled ONCE, on successful delivery**: vendor wallet →
  system treasury, and a Revenue-Ledger row for delivery-charge revenue.
  Free delivery ⇒ ₹0 moves and no revenue row is written.
* **Never negative, never partial, never duplicated.** Every debit is a
  conditional `$inc` guarded by the available balance; every posting carries
  an `idempotency_key` with a unique index, so a repeated webhook, a double
  tap or a retried status change can only ever move money once.

Vendor wallet
-------------
`users.vendor_earnings` IS the vendor wallet (shop money is deliberately kept
off `wallet_balance`, which is customer/referral money). Available balance =
opening + valid credits − valid debits, and every row stores
`previous_balance` / `new_balance` so the UI can never drift from the DB.
"""
import logging
import uuid
from typing import Any, Dict, List, Optional

from core.db import db
from core.utils import now_utc
from core import seq_ids
from core import gst as gst_engine

logger = logging.getLogger(__name__)

VENDOR_WALLET = "vendor_earnings"          # the vendor wallet field
CUSTOMER_WALLET = "wallet_balance"
# Delivery charges are collected GST-INCLUSIVE at 18%.
DELIVERY_GST_PCT = 18.0


class InsufficientFunds(Exception):
    """A debit was refused because the wallet could not cover it. NOTHING
    has been deducted — the caller must surface a financial error."""

    def __init__(self, wallet: str, owner_id: str, needed: float, available: float):
        self.wallet, self.owner_id = wallet, owner_id
        self.needed, self.available = needed, available
        super().__init__(
            f"Transaction could not be completed because the available balance "
            f"is insufficient (needed ₹{needed:.2f}, available ₹{available:.2f}). "
            f"No money has been deducted."
        )


async def ensure_indexes() -> None:
    """Idempotency is enforced by the DATABASE, not by hopeful code."""
    try:
        await db.transactions.create_index(
            "idempotency_key", unique=True, sparse=True, name="uniq_idem_key",
        )
    except Exception as err:  # pragma: no cover
        logger.warning(f"ledger index setup: {str(err)[:200]}")


async def _balance(owner_id: str, wallet: str) -> float:
    u = await db.users.find_one({"id": owner_id}, {"_id": 0, wallet: 1})
    return round(float((u or {}).get(wallet) or 0), 2)


async def post(
    *,
    group: str,
    txn_type: str,
    amount: float,
    idempotency_key: str,
    user_id: Optional[str] = None,
    debit: float = 0.0,
    credit: float = 0.0,
    previous_balance: Optional[float] = None,
    new_balance: Optional[float] = None,
    source_wallet: Optional[str] = None,
    destination_wallet: Optional[str] = None,
    order_id: Optional[str] = None,
    order_number: Optional[str] = None,
    vendor_id: Optional[str] = None,
    shop_name: Optional[str] = None,
    payment_id: Optional[str] = None,
    payment_method: Optional[str] = None,
    cashback_pct: float = 0.0,
    cashback_amount: float = 0.0,
    delivery_charge: float = 0.0,
    gst: float = 0.0,
    settlement_status: str = "settled",
    remarks: str = "",
    description: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Write ONE fully-described ledger row. Returns None when the row
    already existed (i.e. the operation was a replay)."""
    txn_id = str(uuid.uuid4())
    ref = await seq_ids.get_or_create("txn", txn_id)
    doc: Dict[str, Any] = {
        "id": txn_id,
        "short_id": ref,
        "reference_number": ref,
        "idempotency_key": idempotency_key,
        "created_at": now_utc().isoformat(),
        "txn_group": group,
        "type": txn_type,
        "user_id": user_id,
        "vendor_id": vendor_id,
        "shop_name": shop_name,
        "order_id": order_id,
        "order_number": order_number,
        "payment_id": payment_id,
        "payment_method": payment_method,
        "source_wallet": source_wallet,
        "destination_wallet": destination_wallet,
        "debit": round(float(debit or 0), 2),
        "credit": round(float(credit or 0), 2),
        "amount": round(float(amount or 0), 2),
        "previous_balance": None if previous_balance is None else round(previous_balance, 2),
        "new_balance": None if new_balance is None else round(new_balance, 2),
        "cashback_pct": round(float(cashback_pct or 0), 2),
        "cashback_amount": round(float(cashback_amount or 0), 2),
        "delivery_charge": round(float(delivery_charge or 0), 2),
        "gst": round(float(gst or 0), 2),
        "settlement_status": settlement_status,
        "status": "success",
        "remarks": remarks or description,
        "description": description or remarks,
        **(extra or {}),
    }
    try:
        await db.transactions.insert_one(doc)
    except Exception as err:
        if "duplicate" in str(err).lower() or "E11000" in str(err):
            return None
        raise
    doc.pop("_id", None)
    return doc


async def credit(
    owner_id: str, wallet: str, amount: float, *, idempotency_key: str, **fields,
) -> Optional[Dict[str, Any]]:
    """Add money to a wallet and ledger it. Replay-safe."""
    amount = round(float(amount or 0), 2)
    if not owner_id or amount <= 0.009:
        return None
    # Claim the key FIRST — if the row already exists the money already moved.
    before = await _balance(owner_id, wallet)
    row = await post(
        amount=amount, credit=amount, idempotency_key=idempotency_key,
        user_id=owner_id, previous_balance=before, new_balance=round(before + amount, 2),
        destination_wallet=wallet, **fields,
    )
    if row is None:
        return None
    await db.users.update_one({"id": owner_id}, {"$inc": {wallet: amount}})
    return row


async def debit(
    owner_id: str, wallet: str, amount: float, *, idempotency_key: str, **fields,
) -> Optional[Dict[str, Any]]:
    """Take money out of a wallet. NEVER goes negative, never partially
    completes: the `$inc` is conditional on the balance covering it, and if
    it does not, `InsufficientFunds` is raised with nothing deducted."""
    amount = round(float(amount or 0), 2)
    if not owner_id or amount <= 0.009:
        return None
    if await db.transactions.find_one({"idempotency_key": idempotency_key}, {"_id": 1}):
        return None                              # replay — already deducted
    before = await _balance(owner_id, wallet)
    res = await db.users.update_one(
        {"id": owner_id, wallet: {"$gte": amount}},
        {"$inc": {wallet: -amount}},
    )
    if res.modified_count != 1:
        raise InsufficientFunds(wallet, owner_id, amount, before)
    row = await post(
        amount=amount, debit=amount, idempotency_key=idempotency_key,
        user_id=owner_id, previous_balance=before, new_balance=round(before - amount, 2),
        source_wallet=wallet, **fields,
    )
    if row is None:
        # Lost a race on the ledger row — give the money straight back so a
        # deduction can never exist without its ledger entry.
        await db.users.update_one({"id": owner_id}, {"$inc": {wallet: amount}})
        return None
    return row


async def post_opening_balance(
    owner_id: str, wallet: str, *, reason: str = "Opening balance journal entry",
) -> Optional[Dict[str, Any]]:
    """Explain a balance the ledger cannot account for, WITHOUT moving money.

    A wallet that pre-dates the ledger (or that was seeded directly in the
    database) shows an `unledgered_difference`. Real books close that with an
    OPENING BALANCE journal entry, and so do we: one audited row for the
    difference, so `opening + credits − debits = available` becomes provable.
    Nothing is credited or debited — `users` is untouched.
    """
    rows = await db.transactions.find(
        {"user_id": owner_id, "wallet_impact": "vendor_earnings_only"}
        if wallet == VENDOR_WALLET else
        {"user_id": owner_id,
         "wallet_impact": {"$nin": ["vendor_earnings_only", "informational"]}},
        {"_id": 0, "credit": 1, "debit": 1, "amount": 1},
    ).to_list(50000)
    net = 0.0
    for r in rows:
        c, d = float(r.get("credit") or 0), float(r.get("debit") or 0)
        net += (c - d) if (c or d) else float(r.get("amount") or 0)
    stored = await _balance(owner_id, wallet)
    diff = round(stored - net, 2)
    if abs(diff) < 0.02:
        return None
    return await post(
        group="opening_balance",
        txn_type="opening_balance",
        amount=abs(diff),
        credit=diff if diff > 0 else 0.0,
        debit=-diff if diff < 0 else 0.0,
        idempotency_key=f"OPENING:{wallet}:{owner_id}:{uuid.uuid4().hex[:8]}",
        user_id=owner_id,
        previous_balance=round(net, 2),
        new_balance=stored,
        destination_wallet=wallet if diff > 0 else None,
        source_wallet=wallet if diff < 0 else None,
        settlement_status="opening",
        description=reason,
        extra=({"wallet_impact": "vendor_earnings_only"} if wallet == VENDOR_WALLET else {}),
    )


async def record_financial_error(kind: str, detail: str, **ctx) -> None:
    """A money movement that could NOT be completed. Surfaced to admin so it
    is investigated instead of silently swallowed."""
    await db.financial_errors.insert_one({
        "id": str(uuid.uuid4()),
        "kind": kind,
        "detail": detail[:500],
        "status": "open",
        "created_at": now_utc().isoformat(),
        **ctx,
    })


# ── Order-level operations ──────────────────────────────────────────────

def prepaid_amount(order: Dict[str, Any]) -> float:
    """What the customer has ALREADY paid for this sub-order (wallet slice +
    online slice, delivery included). COD money is physical cash and is
    deliberately excluded."""
    total = round(float(order.get("total") or 0), 2)
    cod = round(float(order.get("cod_due") or 0), 2)
    return round(max(0.0, total - cod), 2)


async def credit_vendor_for_order(order: Dict[str, Any], *, payment_id: Optional[str] = None) -> float:
    """Credit the vendor the prepaid money for a sub-order. Exactly once."""
    vendor_id = order.get("vendor_id")
    amount = prepaid_amount(order)
    if not vendor_id or amount <= 0.009:
        return 0.0
    row = await credit(
        vendor_id, VENDOR_WALLET, amount,
        idempotency_key=f"VENDORSALE:{order['id']}",
        group="vendor_payable",
        txn_type="vendor_sale",
        order_id=order.get("id"),
        order_number=order.get("order_number"),
        vendor_id=vendor_id,
        shop_name=order.get("vendor_name"),
        payment_id=payment_id or order.get("payment_id"),
        payment_method=order.get("paid_via"),
        delivery_charge=float(order.get("delivery_charge") or 0),
        settlement_status="credited",
        description=f"Sale credited for order {order.get('order_number') or order.get('id')}",
        extra={"wallet_impact": "vendor_earnings_only"},
    )
    return amount if row else 0.0


async def credit_vendor_cod_on_delivery(order: Dict[str, Any]) -> float:
    """Oct 2026 — COD delivered by a DELIVERY PARTNER.

    The rider (not the seller) took the customer's cash, so the seller has
    received nothing physically: the company is holding his money. On the
    `delivered` transition we therefore credit the seller the FULL cash
    collected — exactly the same as the prepaid path — and the caller then
    lets `settle_delivery_fee` take the delivery charge back as revenue.
    Net result: the seller keeps precisely the item value and can withdraw
    it, while the rider's cash-in-hand stays a liability until he remits.

    Exactly once per order (`VENDORCOD:<order_id>`). Returns the amount.
    """
    order_id = order.get("id")
    vendor_id = order.get("vendor_id")
    cash = round(float(order.get("cod_due") or 0), 2)
    if not vendor_id or cash <= 0.009:
        return 0.0
    row = await credit(
        vendor_id, VENDOR_WALLET, cash,
        idempotency_key=f"VENDORCOD:{order_id}",
        group="vendor_payable",
        txn_type="vendor_sale",
        order_id=order_id,
        order_number=order.get("order_number"),
        vendor_id=vendor_id,
        shop_name=order.get("vendor_name"),
        payment_method=order.get("paid_via"),
        delivery_charge=float(order.get("delivery_charge") or 0),
        settlement_status="credited",
        description=(
            f"Cash-on-delivery collected by delivery partner — credited for "
            f"order {order.get('order_number') or order_id}"
        ),
        extra={"wallet_impact": "vendor_earnings_only", "cod_credit": True},
    )
    return cash if row else 0.0


async def record_vendor_cod_self_collected(order: Dict[str, Any]) -> float:
    """Oct-2026 — COD delivered by the SELLER himself (no rider mapped).

    The seller physically took the customer's cash, so there is no money for
    us to move: crediting his withdrawable wallet would create the same
    rupee twice (once in his pocket, once as a company liability). We write
    ONE informational ledger row instead, so the cash is fully traceable in
    his Net Worth without ever touching a balance.

    Tagged `wallet_impact="informational"`, which every wallet
    reconciliation deliberately ignores. Exactly once per order.
    """
    order_id = order.get("id")
    vendor_id = order.get("vendor_id")
    cash = round(float(order.get("cod_due") or 0), 2)
    if not vendor_id or cash <= 0.009:
        return 0.0
    fee = round(float(order.get("delivery_charge") or 0), 2)
    row = await post(
        group="vendor_self_collected",
        txn_type="vendor_cod_self_collected",
        amount=cash,
        idempotency_key=f"VENDORCODSELF:{order_id}",
        user_id=vendor_id,
        vendor_id=vendor_id,
        shop_name=order.get("vendor_name"),
        order_id=order_id,
        order_number=order.get("order_number"),
        payment_method=order.get("paid_via"),
        delivery_charge=fee,
        settlement_status="collected_by_seller",
        description=(
            f"Cash collected by the seller on his own delivery — ₹{cash:,.2f} "
            f"(incl. ₹{fee:,.2f} delivery) · order "
            f"{order.get('order_number') or order_id}. Slangcart takes nothing."
        ),
        extra={
            "wallet_impact": "informational",
            "self_delivered": True,
            "delivery_charge_kept_by_vendor": fee,
            "company_share": 0.0,
        },
    )
    return cash if row else 0.0


async def settle_dp_commission(order: Dict[str, Any], pct: float) -> Dict[str, Any]:
    """Oct 2026 — the rider's pay: a % of the delivery charge, admin-set.

    Computed on the GST-EXCLUSIVE delivery revenue so the company can never
    pay out the GST it owes the government. The money is credited to the
    rider's PERSONAL wallet (`wallet_balance`) — never his cash-in-hand pot —
    so it lands in the customer/partner liability group and he can raise a
    withdrawal request on it. Exactly once per order (`DPCOMM:<order_id>`).
    """
    order_id = order.get("id")
    dp_id = order.get("dp_id")
    fee = round(float(order.get("delivery_charge") or 0), 2)
    pct = max(0.0, min(float(pct or 0), 100.0))
    if not dp_id or fee <= 0.009 or pct <= 0:
        return {"credited": 0.0, "pct": pct}
    base = round(float(gst_engine.split_inclusive(fee, DELIVERY_GST_PCT)["base_amount"]), 2)
    amount = round(base * pct / 100.0, 2)
    if amount <= 0.009:
        return {"credited": 0.0, "pct": pct}
    row = await credit(
        dp_id, CUSTOMER_WALLET, amount,
        idempotency_key=f"DPCOMM:{order_id}",
        group="dp_payable",
        txn_type="dp_delivery_commission",
        order_id=order_id,
        order_number=order.get("order_number"),
        vendor_id=order.get("vendor_id"),
        shop_name=order.get("vendor_name"),
        source_wallet="system_treasury",
        delivery_charge=fee,
        settlement_status="credited",
        description=(
            f"Delivery earning — {pct:g}% of ₹{base:.2f} delivery revenue "
            f"· order {order.get('order_number') or order_id}"
        ),
        extra={"dp_commission_pct": pct, "delivery_revenue_base": base},
    )
    return {"credited": amount if row else 0.0, "pct": pct, "base": base}


async def reverse_dp_commission(order: Dict[str, Any], reason: str) -> float:
    """Undo the rider's earning when a delivered order is cancelled/returned."""
    order_id = order.get("id")
    dp_id = order.get("dp_id")
    paid = await db.transactions.find_one(
        {"idempotency_key": f"DPCOMM:{order_id}"}, {"_id": 0, "amount": 1},
    )
    amount = round(float((paid or {}).get("amount") or 0), 2)
    if not dp_id or amount <= 0.009:
        return 0.0
    try:
        row = await debit(
            dp_id, CUSTOMER_WALLET, amount,
            idempotency_key=f"DPCOMM_REV:{order_id}",
            group="dp_payable",
            txn_type="dp_delivery_commission_reversal",
            order_id=order_id,
            order_number=order.get("order_number"),
            destination_wallet="system_treasury",
            settlement_status="reversed",
            description=f"Delivery earning reversed — {reason}",
        )
        return amount if row else 0.0
    except InsufficientFunds as err:
        await record_financial_error(
            "dp_commission_reversal_unfunded", str(err),
            order_id=order_id, amount=amount,
        )
        return 0.0


async def settle_delivery_fee(
    order: Dict[str, Any], *, credit_admin_bucket, admin_id: Optional[str] = None,
) -> Dict[str, Any]:
    """On successful delivery: vendor wallet → system treasury for the
    delivery charge, plus the Revenue-Ledger row. Exactly once per order.

    Free delivery (₹0) moves nothing and writes no revenue row.
    If the vendor wallet cannot cover the fee NOTHING is deducted; a seller
    outstanding + a financial error are recorded for admin to chase.
    """
    order_id = order.get("id")
    fee = round(float(order.get("delivery_charge") or 0), 2)
    vendor_id = order.get("vendor_id")
    if fee <= 0.009:
        return {"settled": True, "amount": 0.0, "reason": "free_delivery"}
    if order.get("delivery_settled"):
        return {"settled": True, "amount": 0.0, "reason": "already_settled"}

    # ── Oct-2026 OWNER RULE — no rider, no delivery charge ──────────────
    # Slangcart only earns the delivery charge when SLANGCART delivered,
    # i.e. when a mapped delivery partner carried the parcel. A seller who
    # is not mapped to a rider takes the whole job (and the whole risk) on
    # himself, so the company collects ₹0: nothing leaves his wallet, no
    # delivery-revenue row and no GST row is written. Previously this ran
    # for every order, which silently pulled the fee out of a
    # self-delivering seller's wallet (or raised a bogus outstanding
    # against him) and booked revenue the company never earned.
    if not order.get("dp_id"):
        await db.orders.update_one(
            {"id": order_id},
            {"$set": {
                "delivery_settled": True,
                "delivery_settled_at": now_utc().isoformat(),
                "delivery_settlement_status": "vendor_self_delivery",
                "delivery_charge_kept_by_vendor": fee,
            }},
        )
        return {"settled": True, "amount": 0.0, "reason": "vendor_self_delivery",
                "kept_by_vendor": fee}

    ts = now_utc().isoformat()
    try:
        row = await debit(
            vendor_id, VENDOR_WALLET, fee,
            idempotency_key=f"DELFEE:{order_id}",
            group="delivery_revenue",
            txn_type="delivery_charge_paid",
            order_id=order_id,
            order_number=order.get("order_number"),
            vendor_id=vendor_id,
            shop_name=order.get("vendor_name"),
            destination_wallet="system_treasury",
            payment_method=order.get("paid_via"),
            delivery_charge=fee,
            settlement_status="settled",
            description=f"Delivery charge paid to Slangcart for order {order.get('order_number') or order_id}",
            extra={"wallet_impact": "vendor_earnings_only"},
        )
    except InsufficientFunds as err:
        # Oct-2026 — ONE row per order, however many times the delivery is
        # retried. It used to insert a fresh row on every attempt, so moving
        # an order delivered → shipped → delivered while the wallet was short
        # left the same ₹20 fee owed two or three times over.
        await db.vendor_outstanding.update_one(
            {"order_id": order_id, "kind": "delivery_fee"},
            {"$set": {
                "vendor_id": vendor_id,
                "vendor_name": order.get("vendor_name"),
                "amount": fee,
                "status": "open",
                "order_number": order.get("order_number"),
                "updated_at": ts,
            }, "$setOnInsert": {
                "id": str(uuid.uuid4()), "recovered": 0.0, "created_at": ts,
            }},
            upsert=True,
        )
        await record_financial_error(
            "delivery_fee_unfunded", str(err),
            order_id=order_id, vendor_id=vendor_id, amount=fee,
        )
        await db.orders.update_one(
            {"id": order_id},
            {"$set": {"delivery_settlement_status": "outstanding", "delivery_outstanding": fee}},
        )
        return {"settled": False, "amount": 0.0, "reason": "vendor_balance_short", "outstanding": fee}

    if row is None:
        return {"settled": True, "amount": 0.0, "reason": "already_settled"}

    # The fee is PAID now, so a row parked by an earlier short attempt must
    # not stay open — otherwise the same rupees are recovered a second time.
    await db.vendor_outstanding.update_many(
        {"order_id": order_id, "kind": "delivery_fee", "status": "open"},
        {"$set": {"status": "closed", "closed_at": ts,
                  "closed_reason": "delivery_fee_paid"}},
    )

    # Treasury + Revenue Ledger (Group 1 · delivery-charge revenue).
    #
    # Sep-2026 — the delivery charge the customer paid is GST-INCLUSIVE, so
    # it is split before it is recognised:
    #     revenue (Group 1) = fee × 100/118
    #     GST     (Group 3) = fee × 18/118
    # Revenue + GST always add back to exactly the cash collected, so there
    # is one movement and no double entry.
    split = gst_engine.split_inclusive(fee, DELIVERY_GST_PCT)
    rev_base = round(float(split["base_amount"]), 2)
    rev_gst = round(float(split["total_gst"]), 2)
    await credit_admin_bucket("delivery_collected", fee, also_total_earned=False)
    await post(
        group="revenue_ledger",
        txn_type="delivery_charge_collected",
        amount=rev_base,
        credit=rev_base,
        idempotency_key=f"DELREV:{order_id}",
        user_id=admin_id,
        vendor_id=vendor_id,
        order_id=order_id,
        order_number=order.get("order_number"),
        destination_wallet="system_treasury",
        delivery_charge=fee,
        gst=rev_gst,
        payment_method=order.get("paid_via"),
        description=(
            f"Delivery charge revenue · order {order.get('order_number') or order_id} "
            f"· ₹{fee:.2f} incl. GST ({DELIVERY_GST_PCT:g}%)"
        ),
        extra={"gross_amount": fee, "gst_amount": rev_gst, "gst_pct": DELIVERY_GST_PCT},
    )
    if rev_gst > 0.009:
        await post(
            group="gst_ledger",
            txn_type="gst_collected",
            amount=rev_gst,
            credit=rev_gst,
            idempotency_key=f"DELGST:{order_id}",
            user_id=admin_id,
            vendor_id=vendor_id,
            order_id=order_id,
            order_number=order.get("order_number"),
            destination_wallet="system_treasury",
            gst=rev_gst,
            description=(
                f"GST {DELIVERY_GST_PCT:g}% on delivery charge ₹{fee:.2f} "
                f"· order {order.get('order_number') or order_id}"
            ),
            extra={"gst_kind": "delivery_charge", "gross_amount": fee,
                   "taxable_value": rev_base, "gst_pct": DELIVERY_GST_PCT},
        )
    await db.orders.update_one(
        {"id": order_id},
        {"$set": {
            "delivery_settled": True,
            "delivery_settled_at": ts,
            "delivery_settlement_status": "settled",
        }},
    )
    return {"settled": True, "amount": fee}


async def reverse_order_money(
    order: Dict[str, Any], reason: str, *, credit_admin_bucket, admin_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Cancellation / return: undo exactly what was actually posted for this
    order — the recorded vendor credit and, if it was already settled, the
    delivery fee. Amounts come from the LEDGER, never re-derived, so a
    reversal can never differ from the original movement."""
    order_id = order.get("id")
    vendor_id = order.get("vendor_id")
    out = {"vendor_reversed": 0.0, "delivery_reversed": 0.0}

    credited = await db.transactions.find_one(
        {"idempotency_key": f"VENDORSALE:{order_id}"}, {"_id": 0, "amount": 1},
    )
    amount = round(float((credited or {}).get("amount") or 0), 2)
    # Oct 2026 — a COD order delivered by a rider was ALSO credited to the
    # seller (VENDORCOD). Reverse whatever the ledger actually posted.
    cod_credited = await db.transactions.find_one(
        {"idempotency_key": f"VENDORCOD:{order_id}"}, {"_id": 0, "amount": 1},
    )
    amount = round(amount + float((cod_credited or {}).get("amount") or 0), 2)
    out["dp_commission_reversed"] = await reverse_dp_commission(order, reason)
    if vendor_id and amount > 0.009:
        try:
            row = await debit(
                vendor_id, VENDOR_WALLET, amount,
                idempotency_key=f"VENDORSALE_REV:{order_id}",
                group="vendor_payable",
                txn_type="vendor_sale_reversal",
                order_id=order_id,
                order_number=order.get("order_number"),
                vendor_id=vendor_id,
                settlement_status="reversed",
                description=f"Sale reversed — {reason} (order {order.get('order_number') or order_id})",
                extra={"wallet_impact": "vendor_earnings_only"},
            )
            if row:
                out["vendor_reversed"] = amount
        except InsufficientFunds as err:
            await record_financial_error(
                "vendor_sale_reversal_unfunded", str(err),
                order_id=order_id, vendor_id=vendor_id, amount=amount,
            )

    if order.get("delivery_settled"):
        fee = round(float(order.get("delivery_charge") or 0), 2)
        if fee > 0.009:
            row = await credit(
                vendor_id, VENDOR_WALLET, fee,
                idempotency_key=f"DELFEE_REV:{order_id}",
                group="delivery_revenue",
                txn_type="delivery_charge_reversal",
                order_id=order_id,
                order_number=order.get("order_number"),
                vendor_id=vendor_id,
                source_wallet="system_treasury",
                delivery_charge=fee,
                settlement_status="reversed",
                description=f"Delivery charge returned — {reason}",
                extra={"wallet_impact": "vendor_earnings_only"},
            )
            if row:
                await credit_admin_bucket("delivery_collected", -fee, also_total_earned=False)
                # Reverse the revenue + GST recognition too, so Group 1 and
                # Group 3 never keep income for a delivery that was undone.
                rsplit = gst_engine.split_inclusive(fee, DELIVERY_GST_PCT)
                await post(
                    group="revenue_ledger",
                    txn_type="delivery_revenue_reversal",
                    amount=round(float(rsplit["base_amount"]), 2),
                    debit=round(float(rsplit["base_amount"]), 2),
                    idempotency_key=f"DELREV_REV:{order_id}",
                    user_id=admin_id,
                    vendor_id=vendor_id,
                    order_id=order_id,
                    order_number=order.get("order_number"),
                    source_wallet="system_treasury",
                    delivery_charge=fee,
                    description=f"Delivery revenue reversed — {reason}",
                    extra={"original_type": "delivery_charge_collected"},
                )
                if float(rsplit["total_gst"]) > 0.009:
                    await post(
                        group="gst_ledger",
                        txn_type="gst_reversal",
                        amount=round(float(rsplit["total_gst"]), 2),
                        debit=round(float(rsplit["total_gst"]), 2),
                        idempotency_key=f"DELGST_REV:{order_id}",
                        user_id=admin_id,
                        vendor_id=vendor_id,
                        order_id=order_id,
                        order_number=order.get("order_number"),
                        source_wallet="system_treasury",
                        gst=round(float(rsplit["total_gst"]), 2),
                        description=f"Delivery GST reversed — {reason}",
                        extra={"gst_kind": "delivery_charge", "original_type": "gst_collected"},
                    )
                await db.orders.update_one(
                    {"id": order_id},
                    {"$set": {"delivery_settled": False, "delivery_settlement_status": "reversed"}},
                )
                out["delivery_reversed"] = fee
    return out


async def vendor_wallet_view(vendor_id: str) -> Dict[str, Any]:
    """Opening + credits − debits = available, straight off the ledger, so
    the vendor UI and the DB can never show different numbers.

    Rows written before Phase 1 (and any manual admin adjustment) carry no
    `credit`/`debit` fields, so their direction is derived from the txn type.
    Anything the ledger cannot explain is reported honestly as
    `unledgered_difference` rather than silently hidden.
    """
    CREDIT_TYPES = {
        "vendor_sale", "delivery_charge_reversal", "withdrawal_refund",
        "cashback_funding_refund", "vendor_adjustment_credit", "opening_balance",
    }
    DEBIT_TYPES = {
        "vendor_sale_reversal", "delivery_charge_paid", "withdrawal_hold",
        "cashback_funding", "vendor_adjustment_debit", "return_refund_debit",
    }
    rows: List[Dict[str, Any]] = await db.transactions.find(
        {"user_id": vendor_id, "wallet_impact": "vendor_earnings_only"},
        {"_id": 0, "credit": 1, "debit": 1, "amount": 1, "type": 1},
    ).to_list(50000)
    credits = debits = 0.0
    for r in rows:
        c, d = float(r.get("credit") or 0), float(r.get("debit") or 0)
        if c or d:
            credits += c
            debits += d
            continue
        amt = abs(float(r.get("amount") or 0))
        if r.get("type") in DEBIT_TYPES:
            debits += amt
        elif r.get("type") in CREDIT_TYPES:
            credits += amt
    credits, debits = round(credits, 2), round(debits, 2)
    ledger_balance = round(credits - debits, 2)
    stored = await _balance(vendor_id, VENDOR_WALLET)
    pending = await db.withdrawals.aggregate([
        {"$match": {"user_id": vendor_id, "status": {"$in": ["pending", "approved", "processing"]}}},
        {"$group": {"_id": None, "s": {"$sum": "$amount"}}},
    ]).to_list(1)
    diff = round(stored - ledger_balance, 2)
    return {
        "available_balance": stored,
        "ledger_credits": credits,
        "ledger_debits": debits,
        "ledger_balance": ledger_balance,
        "unledgered_difference": diff,
        "pending_withdrawals": round(float((pending or [{}])[0].get("s") or 0), 2),
        "in_sync": abs(diff) < 0.02,
    }
