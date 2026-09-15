"""Add money to the Slangcart wallet (Jun-2026).

Tapping "Add money" used to open the ₹118 SUBSCRIPTION screen, which is a
completely different product — the customer wanted to load their wallet, not
buy a subscription. This module is the real top-up flow:

    enter amount (₹10 … ₹5,000)  →  Razorpay  →  wallet credited

Rules
-----
* **Server prices it.** The client sends an amount, we clamp it against the
  configured min / max and re-check it at verify time from OUR stored
  attempt, never from the request body.
* **Max ₹5,000 per top-up** (owner's rule), tunable via
  `settings.wallet_topup_max`.
* **Credited exactly once.** The wallet credit happens inside a
  `created → paid` status claim on the attempt document, so a double-tapped
  verify, a webhook retry and a flaky network can never credit twice.
* **Books stay exact.** Real cash landed in the company account, and the
  customer now holds a wallet balance we owe them, so the top-up writes a
  `bank_ledger` CREDIT (asset) alongside the wallet credit (liability).
  Company net worth is therefore unchanged by a top-up, which is correct.
"""
import logging
import uuid
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.db import db
from core.razorpay import create_order, fetch_payment, get_creds, verify_signature
from core.security import get_current_user
from core.utils import now_utc, get_settings
from core import seq_ids

logger = logging.getLogger(__name__)
router = APIRouter()

MIN_TOPUP = 10.0
DEFAULT_MAX_TOPUP = 5000.0
PRESETS = [100, 250, 500, 1000, 2000, 5000]


async def _limits() -> Dict[str, float]:
    settings = await get_settings()
    try:
        top = float(settings.get("wallet_topup_max") or DEFAULT_MAX_TOPUP)
    except (TypeError, ValueError):
        top = DEFAULT_MAX_TOPUP
    top = max(MIN_TOPUP, min(top, 100000.0))
    return {"min": MIN_TOPUP, "max": round(top, 2)}


class StartTopup(BaseModel):
    amount: float = Field(..., gt=0)


class VerifyTopup(BaseModel):
    payment_id: str
    razorpay_order_id: str = ""
    razorpay_payment_id: str
    razorpay_signature: str = ""


@router.get("/wallet/topup/config")
async def topup_config(user: Dict[str, Any] = Depends(get_current_user)):
    lim = await _limits()
    creds = await get_creds()
    return {
        "min_amount": lim["min"],
        "max_amount": lim["max"],
        "presets": [p for p in PRESETS if p <= lim["max"]],
        "balance": round(float(user.get("wallet_balance") or 0), 2),
        "wallet_frozen": bool(user.get("wallet_frozen")),
        "key_id": creds["key_id"] or "rzp_test_MOCK",
        "is_mock": creds["is_mock"],
        "currency": "INR",
    }


@router.post("/wallet/topup/start")
async def start_topup(payload: StartTopup, user: Dict[str, Any] = Depends(get_current_user)):
    if user.get("wallet_frozen"):
        raise HTTPException(status_code=403, detail="Your wallet is frozen. Please contact support.")
    lim = await _limits()
    amount = round(float(payload.amount or 0), 2)
    if amount < lim["min"]:
        raise HTTPException(status_code=400, detail=f"Minimum top-up is ₹{lim['min']:.0f}.")
    if amount > lim["max"]:
        raise HTTPException(
            status_code=400,
            detail=f"You can add up to ₹{lim['max']:.0f} in one go.",
        )

    creds = await get_creds()
    # One open attempt per user — re-tapping "Add money" refreshes it.
    await db.wallet_topups.delete_many({"user_id": user["id"], "status": "created"})
    try:
        rzp_order_id = await create_order(
            int(round(amount * 100)),
            f"topup_{user['id'][:12]}_{uuid.uuid4().hex[:6]}",
            notes={"user_id": user["id"], "kind": "wallet_topup"},
            creds=creds,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    attempt = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "amount": amount,
        "razorpay_order_id": rzp_order_id,
        "razorpay_payment_id": None,
        "status": "created",
        "is_mock": creds["is_mock"],
        "created_at": now_utc().isoformat(),
    }
    await db.wallet_topups.insert_one(dict(attempt))
    return {
        "payment_id": attempt["id"],
        "razorpay_order_id": rzp_order_id,
        "amount": amount,
        "amount_paise": int(round(amount * 100)),
        "currency": "INR",
        "key_id": creds["key_id"] or "rzp_test_MOCK",
        "is_mock": creds["is_mock"],
        "description": f"Slangcart wallet top-up · ₹{amount:.0f}",
        "prefill": {
            "name": user.get("name") or "",
            "email": user.get("email") or "",
            "contact": user.get("phone") or "",
        },
    }


@router.post("/wallet/topup/verify")
async def verify_topup(payload: VerifyTopup, user: Dict[str, Any] = Depends(get_current_user)):
    attempt = await db.wallet_topups.find_one(
        {"id": payload.payment_id, "user_id": user["id"]}, {"_id": 0},
    )
    if not attempt:
        raise HTTPException(status_code=404, detail="Top-up attempt not found")
    if attempt["status"] == "paid":
        return {
            "ok": True,
            "already_verified": True,
            "amount": attempt["amount"],
            "balance": round(float(user.get("wallet_balance") or 0), 2),
        }
    if attempt["status"] != "created":
        raise HTTPException(status_code=400, detail=f"This top-up is {attempt['status']}")
    if payload.razorpay_order_id and payload.razorpay_order_id != attempt["razorpay_order_id"]:
        raise HTTPException(status_code=400, detail="Payment order mismatch")
    if not payload.razorpay_payment_id:
        raise HTTPException(status_code=400, detail="Missing Razorpay payment id")

    amount = round(float(attempt["amount"]), 2)
    creds = await get_creds()
    if not creds["is_mock"]:
        if not verify_signature(
            attempt["razorpay_order_id"],
            payload.razorpay_payment_id,
            payload.razorpay_signature,
            creds["key_secret"],
        ):
            await db.wallet_topups.update_one(
                {"id": attempt["id"]},
                {"$set": {"status": "failed", "failed_reason": "bad_signature"}},
            )
            raise HTTPException(status_code=401, detail="Invalid payment signature")
        rzp = await fetch_payment(payload.razorpay_payment_id, creds)
        if rzp:
            status = (rzp.get("status") or "").lower()
            if status not in ("captured", "authorized"):
                raise HTTPException(status_code=400, detail=f"Payment is not captured (status: {status})")
            expected_paise = int(round(amount * 100))
            if int(rzp.get("amount") or 0) not in (0, expected_paise):
                raise HTTPException(status_code=400, detail="Payment amount does not match the top-up")

    ts = now_utc().isoformat()
    # CLAIM the attempt before any money moves — this is what makes the
    # credit exactly-once under retries and double taps.
    claimed = await db.wallet_topups.update_one(
        {"id": attempt["id"], "status": "created"},
        {"$set": {
            "status": "paid",
            "razorpay_payment_id": payload.razorpay_payment_id,
            "razorpay_signature": payload.razorpay_signature,
            "paid_at": ts,
        }},
    )
    if claimed.modified_count != 1:
        fresh = await db.wallet_topups.find_one({"id": attempt["id"]}, {"_id": 0})
        return {"ok": True, "already_verified": True, "amount": float((fresh or {}).get("amount") or 0)}

    await db.users.update_one({"id": user["id"]}, {"$inc": {"wallet_balance": amount}})
    txn_id = str(uuid.uuid4())
    short_code = await seq_ids.get_or_create("txn", txn_id)
    await db.transactions.insert_one({
        "id": txn_id,
        "short_id": short_code,
        "user_id": user["id"],
        "type": "wallet_topup",
        "amount": amount,
        "status": "success",
        "description": f"Money added to wallet · ₹{amount:.0f}",
        "reference_number": short_code,
        "razorpay_order_id": attempt["razorpay_order_id"],
        "razorpay_payment_id": payload.razorpay_payment_id,
        "topup_id": attempt["id"],
        "created_at": ts,
    })
    # Asset side: the cash is in the company account, the wallet balance is
    # the matching liability — net worth unchanged.
    await db.bank_ledger.insert_one({
        "id": str(uuid.uuid4()),
        "kind": "credit",
        "amount": amount,
        "description": f"Wallet top-up by {user.get('name') or user.get('email')} ({short_code})",
        "category": "wallet_topup",
        "utr": payload.razorpay_payment_id,
        "happened_at": ts,
        "created_at": ts,
        "user_id": user["id"],
    })
    try:
        from core.notifications import create_notification
        await create_notification(
            user["id"], "wallet", f"₹{amount:.0f} added to your wallet",
            "Your Slangcart wallet has been topped up successfully.",
            extra={"action_url": "/(tabs)/wallet"},
        )
    except Exception as e:  # pragma: no cover — never block the credit
        logger.warning(f"topup notification failed: {e}")

    fresh_user = await db.users.find_one({"id": user["id"]}, {"_id": 0, "wallet_balance": 1})
    return {
        "ok": True,
        "amount": amount,
        "reference": short_code,
        "balance": round(float((fresh_user or {}).get("wallet_balance") or 0), 2),
    }
