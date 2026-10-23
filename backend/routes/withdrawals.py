"""User-facing withdrawal endpoints.

Carved out of server.py during the Phase 2B modular refactor (2026-05-27).
The POST /withdrawals write endpoint was migrated on 2026-06-04 alongside
/wallet/transfer once the referral engine was ready to be extracted.

Endpoints
---------
  • POST /withdrawals      — request a new withdrawal (rate-limited)
  • GET  /withdrawals/me   — user history (opt-in pagination)
"""
import uuid
from datetime import timedelta
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request

from core import shop_money
from core.db import db
from core.security import get_current_user, require_clean_device
from core.utils import now_utc
from core.notifications import create_notification as _create_notification
from core.config import ADMIN_EMAIL
from core.rate_limit import limiter as _rate_limiter
from models import WithdrawalRequest

router = APIRouter()

# Minimum withdrawal floor (2026-06-01): ₹100. Anything below is rejected
# at the API layer with a friendly message.
# Phase 1 (Jun-2026) — sellers settle in ₹5,000 slabs.
MIN_WITHDRAWAL_AMOUNT = 5000.0
# Oct 2026 — riders settle from ₹1,000 (the owner's rule). The floor is now
# role-based so the delivery-partner wallet screen and this endpoint can
# never disagree: routes/delivery_partner.MIN_WITHDRAWAL is the same number.
MIN_WITHDRAWAL_DP = 1000.0
# Jun-2026 owner rule — every seller settlement carries a 2.56% transaction
# fee, collected into the System Wallet treasury's Revenue Ledger before the
# payout is raised. Riders and the admin company wallet are not charged.
WITHDRAWAL_FEE_PCT = 2.56


@router.post("/withdrawals")
@_rate_limiter.limit("5/hour")
async def request_withdrawal(
    request: Request,  # noqa: ARG001 — slowapi needs it in the signature
    payload: WithdrawalRequest,
    user: Dict[str, Any] = Depends(require_clean_device),
):
    # ── SELLER SETTLEMENT ONLY (MLM cutover, Jun-2026) ──────────────────
    # A Slangcart wallet is a marketplace wallet: customers SPEND it inside
    # the app, they do not cash it out. Only approved vendors (and admins)
    # may withdraw, because that is their genuine sales settlement.
    is_seller = bool(user.get("is_vendor") and user.get("is_vendor_approved"))
    is_admin = user.get("role") == "admin" or (user.get("email") or "").lower() == ADMIN_EMAIL.lower()
    # Oct 2026 — an approved DELIVERY PARTNER settles his delivery earnings
    # (personal wallet). His COD cash-in-hand is a separate pot he owes US,
    # and it is deliberately not withdrawable.
    is_rider = bool(
        user.get("is_delivery_partner") and user.get("is_delivery_partner_approved"),
    )
    if not (is_seller or is_admin or is_rider):
        raise HTTPException(
            status_code=403,
            detail=(
                "Your Slangcart wallet balance is used for purchases, cashback "
                "and refunds inside the app. Bank withdrawals are available to "
                "approved seller accounts for their sales settlement."
            ),
        )
    if user.get("wallet_frozen"):
        raise HTTPException(status_code=403, detail="Wallet is frozen. Contact support.")

    # ── Minimum settlement floor (Oct 2026) ─────────────────────────────
    # Enforced at the API layer so a client can never slip below the number
    # its wallet screen shows. Riders settle from ₹1,000; sellers/admins
    # settle in ₹5,000 slabs.
    floor = MIN_WITHDRAWAL_DP if (is_rider and not is_seller and not is_admin) else MIN_WITHDRAWAL_AMOUNT
    if payload.amount < floor:
        raise HTTPException(
            status_code=400,
            detail=f"The minimum settlement is ₹{int(floor):,}. Please raise a settlement of at least ₹{int(floor):,}.",
        )

    if not (user.get("upi_id") or user.get("bank_account")):
        raise HTTPException(status_code=400, detail="Add UPI or bank details first")

    # ── Which pot is being settled ───────────────────────────────────────
    # A seller settles their SHOP wallet (`vendor_earnings`); the admin
    # settles the company wallet. Eligibility is computed from the AVAILABLE
    # balance only — never from total/lifetime sales, pending money or
    # customer liability.
    wallet_field = shop_money.VENDOR_WALLET if is_seller else "wallet_balance"
    available = round(float(user.get(wallet_field) or 0), 2)
    if available < payload.amount:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Transaction could not be completed because the available balance "
                f"is insufficient (available ₹{available:,.2f}). No money has been deducted."
            ),
        )

    # One open settlement at a time — protects against a double-tapped
    # request and against a duplicated bank callback later on.
    #
    # Jun-2026 — the check below and the insert further down were two separate
    # steps, so four parallel taps all passed the check and the fee + cashback
    # recovery were taken three times over. A single atomic claim on the user
    # document now gates the whole settlement: whoever flips `settlement_busy`
    # from unset/stale to now owns it, everybody else is told to wait. The
    # stamp is released in `finally`, and a stale one (> 2 min, i.e. a crashed
    # request) can be taken over so nobody is locked out for good.
    lock_now = now_utc()
    stale_before = (lock_now - timedelta(minutes=2)).isoformat()
    claim = await db.users.update_one(
        {"id": user["id"], "$or": [
            {"settlement_busy_at": None},
            {"settlement_busy_at": {"$exists": False}},
            {"settlement_busy_at": {"$lt": stale_before}},
        ]},
        {"$set": {"settlement_busy_at": lock_now.isoformat()}},
    )
    if claim.modified_count != 1:
        raise HTTPException(
            status_code=409,
            detail="A settlement request is already being processed. Please wait a moment.",
        )
    try:
        return await _create_withdrawal(user, payload, is_seller, wallet_field)
    finally:
        await db.users.update_one(
            {"id": user["id"]}, {"$unset": {"settlement_busy_at": ""}},
        )


async def _create_withdrawal(
    user: Dict[str, Any], payload: WithdrawalRequest, is_seller: bool, wallet_field: str,
) -> Dict[str, Any]:
    """The settlement itself. Only ever runs inside the per-user claim above,
    so the cashback adjustment, the fee and the hold happen exactly once."""
    existing = await db.withdrawals.find_one(
        {"user_id": user["id"], "status": {"$in": ["pending", "approved", "processing"]}},
        {"_id": 0, "id": 1, "amount": 1},
    )
    if existing:
        raise HTTPException(
            status_code=400,
            detail=(
                f"You already have a settlement of ₹{float(existing.get('amount') or 0):,.0f} "
                f"in progress. Please wait for it to complete."
            ),
        )

    wid = str(uuid.uuid4())
    # ── Jun-2026 — what actually leaves the wallet on a seller settlement ──
    #
    #   requested  ₹X   (what the seller asked for, already covered by his
    #                    available balance)
    #     − cashback outstanding  → straight into the treasury (we fronted it)
    #     − 2.56% transaction fee → Revenue Ledger
    #     = net paid to his bank account
    #
    # Both deductions are taken from the SAME wallet, each with its own
    # idempotent ledger row keyed on this withdrawal id, so nothing can be
    # booked twice and every rupee is traceable from his Net Worth screen.
    cashback_recovered = 0.0
    fee = 0.0
    if is_seller:
        from server import credit_admin_bucket
        from core.cashback import recover_outstanding_from_wallet

        owed = round(float(user.get("cashback_outstanding") or 0), 2)
        if owed > 0.009:
            rec = await recover_outstanding_from_wallet(
                user["id"], min(owed, payload.amount),
                credit_admin_bucket=credit_admin_bucket,
                note="Cashback adjusted on settlement request",
                recorded_by=user.get("email"),
                # Keyed on THIS settlement so a replay can never recover twice.
                idempotency_key=f"CBRECOVER-WDL:{wid}",
            )
            cashback_recovered = round(float(rec.get("applied") or 0), 2)

        fee = round(payload.amount * WITHDRAWAL_FEE_PCT / 100.0, 2)
        net_payout = round(payload.amount - cashback_recovered - fee, 2)
        if net_payout <= 0.009:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"After adjusting ₹{cashback_recovered:,.2f} cashback outstanding and the "
                    f"{WITHDRAWAL_FEE_PCT:g}% transaction fee, nothing would be left to pay out. "
                    f"Please raise a larger settlement."
                ),
            )
        # Re-read: the recovery above has already left his wallet.
        fresh = await db.users.find_one(
            {"id": user["id"]}, {"_id": 0, shop_money.VENDOR_WALLET: 1},
        ) or {}
        left = round(float(fresh.get(shop_money.VENDOR_WALLET) or 0), 2)
        if left + 0.009 < round(fee + net_payout, 2):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"₹{cashback_recovered:,.2f} cashback outstanding was recovered from your "
                    f"wallet, leaving ₹{left:,.2f}. Please raise a settlement of at most that amount."
                ),
            )
        if fee > 0.009:
            try:
                fee_row = await shop_money.debit(
                    user["id"], shop_money.VENDOR_WALLET, fee,
                    idempotency_key=f"WDLFEE:{wid}",
                    group="revenue_ledger",
                    txn_type="withdrawal_transaction_fee",
                    vendor_id=user["id"],
                    destination_wallet="system_treasury",
                    settlement_status="settled",
                    description=(
                        f"Transaction fee {WITHDRAWAL_FEE_PCT:g}% on settlement "
                        f"₹{payload.amount:,.2f} — ₹{fee:,.2f} to Slangcart"
                    ),
                    extra={"wallet_impact": "vendor_earnings_only", "withdrawal_id": wid,
                           "fee_pct": WITHDRAWAL_FEE_PCT, "gross_amount": payload.amount},
                )
            except shop_money.InsufficientFunds as err:
                raise HTTPException(status_code=400, detail=str(err))
            if fee_row is not None:
                await credit_admin_bucket("platform_fee_collected", fee, also_total_earned=False)
                admin_doc = await db.users.find_one(
                    {"email": ADMIN_EMAIL.lower()}, {"_id": 0, "id": 1},
                )
                await shop_money.post(
                    group="revenue_ledger",
                    txn_type="platform_fee_collected",
                    amount=fee,
                    credit=fee,
                    idempotency_key=f"WDLFEEREV:{wid}",
                    user_id=(admin_doc or {}).get("id"),
                    vendor_id=user["id"],
                    shop_name=user.get("vendor_business_name") or user.get("shop_name") or user.get("name"),
                    destination_wallet="system_treasury",
                    settlement_status="settled",
                    description=(
                        f"Withdrawal transaction fee {WITHDRAWAL_FEE_PCT:g}% · settlement "
                        f"₹{payload.amount:,.2f} by {user.get('vendor_business_name') or user.get('name')}"
                    ),
                    extra={"withdrawal_id": wid, "fee_pct": WITHDRAWAL_FEE_PCT,
                           "gross_amount": payload.amount},
                )
    else:
        net_payout = round(payload.amount, 2)

    doc = {
        "id": wid,
        "user_id": user["id"],
        "user_name": user["name"],
        "user_email": user["email"],
        "amount": net_payout,
        "requested_amount": round(payload.amount, 2),
        "cashback_adjusted": cashback_recovered,
        "transaction_fee": fee,
        "transaction_fee_pct": WITHDRAWAL_FEE_PCT if is_seller else 0.0,
        "status": "pending",
        "upi_id": user.get("upi_id"),
        "bank_account": user.get("bank_account"),
        "ifsc": user.get("ifsc"),
        "account_holder": user.get("account_holder"),
        "created_at": now_utc().isoformat(),
        "processed_at": None,
    }
    doc["wallet_field"] = wallet_field
    await db.withdrawals.insert_one(doc)
    # Lock the requested amount out of the AVAILABLE balance, atomically and
    # fully ledgered. If it cannot be covered nothing is deducted and the
    # request is rolled back — a settlement can never create money.
    try:
        await shop_money.debit(
            user["id"], wallet_field, net_payout,
            idempotency_key=f"WDL:{wid}",
            group="withdrawal",
            txn_type="withdrawal_hold",
            vendor_id=user["id"] if is_seller else None,
            destination_wallet="pending_withdrawal",
            settlement_status="pending",
            description=(
                f"Settlement requested — ₹{net_payout:,.0f} moved to pending"
                + (f" (₹{payload.amount:,.0f} requested"
                   + (f", ₹{cashback_recovered:,.2f} cashback adjusted" if cashback_recovered > 0.009 else "")
                   + (f", ₹{fee:,.2f} transaction fee" if fee > 0.009 else "") + ")"
                   if (cashback_recovered > 0.009 or fee > 0.009) else "")
            ),
            extra={"withdrawal_id": wid,
                   "requested_amount": round(payload.amount, 2),
                   "cashback_adjusted": cashback_recovered,
                   "transaction_fee": fee,
                   **({"wallet_impact": "vendor_earnings_only"} if is_seller else {})},
        )
    except shop_money.InsufficientFunds as err:
        await db.withdrawals.delete_one({"id": wid})
        # The fee was taken a moment ago for a settlement that is not
        # happening — hand it straight back so the seller is never charged
        # for a request that failed.
        if fee > 0.009:
            back = await shop_money.credit(
                user["id"], wallet_field, fee,
                idempotency_key=f"WDLFEEBACK:{wid}",
                group="revenue_ledger",
                txn_type="withdrawal_transaction_fee_refund",
                vendor_id=user["id"],
                source_wallet="system_treasury",
                settlement_status="reversed",
                description=f"Transaction fee ₹{fee:,.2f} returned — settlement could not be raised",
                extra={"withdrawal_id": wid, "reverses_fee": True,
                       "wallet_impact": "vendor_earnings_only"},
            )
            if back is not None:
                from server import credit_admin_bucket as _cab
                await _cab("platform_fee_collected", -fee, also_total_earned=False)
                await shop_money.post(
                    group="revenue_ledger",
                    txn_type="reversal",
                    amount=fee,
                    debit=fee,
                    idempotency_key=f"WDLFEEREV_FAILED:{wid}",
                    vendor_id=user["id"],
                    source_wallet="system_treasury",
                    settlement_status="reversed",
                    description="Withdrawal transaction fee reversed — settlement could not be raised",
                    extra={"withdrawal_id": wid, "original_type": "platform_fee_collected"},
                )
        raise HTTPException(status_code=400, detail=str(err))
    await _create_notification(
        user["id"], "withdrawal", "Withdrawal requested",
        f"₹{int(net_payout)} withdrawal is pending admin approval."
        + (f" ₹{cashback_recovered:,.0f} cashback outstanding was adjusted." if cashback_recovered > 0.009 else "")
        + (f" Transaction fee ₹{fee:,.2f}." if fee > 0.009 else ""),
    )
    doc.pop("_id", None)
    return doc


@router.get("/withdrawals/me")
async def my_withdrawals(
    user: Dict[str, Any] = Depends(get_current_user),
    limit: int = 0,
    offset: int = 0,
):
    """User withdrawal history. Pagination is opt-in: when limit is omitted
    (or 0) we return the legacy unbounded list (capped at 1000) so existing
    clients keep working. New FE infinite-scroll passes limit=20."""
    cursor = db.withdrawals.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1)
    if limit and limit > 0:
        cursor = cursor.skip(max(0, offset)).limit(min(limit, 200))
        return await cursor.to_list(min(limit, 200))
    return await cursor.to_list(1000)


@router.get("/vendor/me/wallet")
async def vendor_wallet_summary(user: Dict[str, Any] = Depends(get_current_user)):
    """THE vendor wallet figure. Derived from the ledger (opening + credits −
    debits) and compared with the stored balance, so the app, the vendor web
    panel and the database can never show three different numbers.

    `min_withdrawal` / `can_withdraw` are returned by the backend too — the
    frontend must not decide eligibility on its own.
    """
    is_seller = bool(user.get("is_vendor") and user.get("is_vendor_approved"))
    if not is_seller:
        raise HTTPException(status_code=403, detail="Seller accounts only")
    view = await shop_money.vendor_wallet_view(user["id"])
    outstanding = await db.vendor_outstanding.aggregate([
        {"$match": {"vendor_id": user["id"], "status": "open"}},
        {"$group": {"_id": None, "s": {"$sum": {"$subtract": ["$amount", "$recovered"]}}}},
    ]).to_list(1)
    view["outstanding"] = round(float((outstanding or [{}])[0].get("s") or 0), 2)
    view["min_withdrawal"] = MIN_WITHDRAWAL_AMOUNT
    view["has_payout_method"] = bool(user.get("upi_id") or user.get("bank_account"))
    view["can_withdraw"] = bool(
        view["available_balance"] >= MIN_WITHDRAWAL_AMOUNT
        and view["pending_withdrawals"] <= 0.009
        and view["has_payout_method"]
        and not user.get("wallet_frozen")
    )
    # Sep-2026 — the app's Wallet screen reads these. `available` is the
    # SHOP wallet (`vendor_earnings`); the personal/shopping wallet is
    # reported alongside it and is never mixed in.
    view["available"] = view["available_balance"]
    view["shop_wallet"] = view["available_balance"]
    view["personal_wallet"] = round(float(user.get("wallet_balance") or 0), 2)
    cod_rows = await db.orders.find(
        {"vendor_id": user["id"], "cod_due": {"$gt": 0},
         "status": {"$in": ["placed", "confirmed", "shipped", "out_for_delivery"]}},
        {"_id": 0, "cod_due": 1},
    ).to_list(20000)
    view["cod_to_collect"] = round(sum(float(o.get("cod_due") or 0) for o in cod_rows), 2)
    view["wallet_frozen"] = bool(user.get("wallet_frozen"))
    # Jun-2026 — what a settlement will actually cost, so the seller sees the
    # same arithmetic the API applies: cashback we fronted comes off first,
    # then the transaction fee, and the rest reaches his bank.
    view["cashback_outstanding"] = round(float(user.get("cashback_outstanding") or 0), 2)
    view["withdrawal_fee_pct"] = WITHDRAWAL_FEE_PCT
    view["payout_promise"] = (
        "Approved settlements are deposited to your bank within 24 hours on banking days."
    )
    view["withdraw_blocked_reason"] = (
        "Wallet is frozen — contact support." if user.get("wallet_frozen")
        else "Add a UPI ID or bank account to settle your sales." if not view["has_payout_method"]
        else "You already have a settlement in progress." if view["pending_withdrawals"] > 0.009
        else "" if view["available_balance"] >= MIN_WITHDRAWAL_AMOUNT
        else f"You need at least ₹{int(MIN_WITHDRAWAL_AMOUNT):,} in shop earnings to raise a settlement."
    )
    return view
