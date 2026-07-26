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
from core.utils import now_utc, get_settings
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
    if not user.get("registration_paid"):
        raise HTTPException(status_code=400, detail="Complete registration payment first")
    if user.get("approval_status", "approved") != "approved":
        raise HTTPException(
            status_code=403,
            detail="Account is awaiting admin approval. Withdrawals are disabled until approved.",
        )
    if user.get("wallet_frozen"):
        raise HTTPException(status_code=403, detail="Wallet is frozen. Contact support.")

    # ── L1 completion gate (2026-05-31) ─────────────────────────────────
    # Users who only have spillover / auto-aligned downline (i.e. NO real
    # direct referrals using their own code) CANNOT withdraw. They must
    # bring in `directs_required` true directs first to unlock L1, which
    # also unlocks withdrawals.
    settings = await get_settings()
    dr_required = int(settings.get("directs_required") or 5)
    if user.get("email", "").lower() != ADMIN_EMAIL.lower() and user.get("role") != "admin":
        true_directs = int(user.get("true_direct_count") or 0)
        if true_directs < dr_required:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unable to withdraw due to direct {dr_required} referral "
                    f"not joined. Please complete Level 1 then raise withdrawal "
                    f"request. (You have {true_directs}/{dr_required} direct "
                    f"referrals — bring in {dr_required - true_directs} more "
                    f"using your own referral code.)"
                ),
            )

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
