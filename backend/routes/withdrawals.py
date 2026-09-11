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
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request

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
MIN_WITHDRAWAL_AMOUNT = 100.0


@router.post("/withdrawals")
@_rate_limiter.limit("5/hour")
async def request_withdrawal(
    request: Request,  # noqa: ARG001 — slowapi needs it in the signature
    payload: WithdrawalRequest,
    user: Dict[str, Any] = Depends(require_clean_device),
):
    if float(payload.amount) < MIN_WITHDRAWAL_AMOUNT:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Minimum withdrawal amount is ₹{int(MIN_WITHDRAWAL_AMOUNT)}. "
                f"Please enter an amount of ₹{int(MIN_WITHDRAWAL_AMOUNT)} or more."
            ),
        )
    # ── SELLER SETTLEMENT ONLY (MLM cutover, Jun-2026) ──────────────────
    # A Slangcart wallet is a marketplace wallet: customers SPEND it inside
    # the app, they do not cash it out. Only approved vendors (and admins)
    # may withdraw, because that is their genuine sales settlement.
    is_seller = bool(user.get("is_vendor") and user.get("is_vendor_approved"))
    is_admin = user.get("role") == "admin" or (user.get("email") or "").lower() == ADMIN_EMAIL.lower()
    if not (is_seller or is_admin):
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

    if user.get("wallet_balance", 0) < payload.amount:
        raise HTTPException(status_code=400, detail="Insufficient balance")
    if not (user.get("upi_id") or user.get("bank_account")):
        raise HTTPException(status_code=400, detail="Add UPI or bank details first")

    wid = str(uuid.uuid4())
    doc = {
        "id": wid,
        "user_id": user["id"],
        "user_name": user["name"],
        "user_email": user["email"],
        "amount": payload.amount,
        "status": "pending",
        "upi_id": user.get("upi_id"),
        "bank_account": user.get("bank_account"),
        "ifsc": user.get("ifsc"),
        "account_holder": user.get("account_holder"),
        "created_at": now_utc().isoformat(),
        "processed_at": None,
    }
    await db.withdrawals.insert_one(doc)
    # Lock the requested amount from wallet.
    await db.users.update_one(
        {"id": user["id"]},
        {"$inc": {"wallet_balance": -payload.amount}},
    )
    await _create_notification(
        user["id"], "withdrawal", "Withdrawal requested",
        f"₹{int(payload.amount)} withdrawal is pending admin approval.",
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
