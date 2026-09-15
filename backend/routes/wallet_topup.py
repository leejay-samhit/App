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
from core.razorpay import (
    create_order, fetch_order_payments, fetch_payment, get_creds, verify_signature,
)
from core.security import get_current_user
from core.utils import now_utc, get_settings
from core import seq_ids, shop_money

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
    # Sep 2026 — open attempts are NO LONGER deleted. Deleting them is what
    # turned "Razorpay charged me" into "Top-up attempt not found": the
    # screen re-mounting (or a second tap) wiped the row the paid callback
    # was about to verify, so the money was collected and never credited.
    # Stale attempts are parked as `abandoned` and verify still accepts them.
    await db.wallet_topups.update_many(
        {"user_id": user["id"], "status": "created"},
        {"$set": {"status": "abandoned", "abandoned_at": now_utc().isoformat()}},
    )
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


async def _credit_topup(
    user: Dict[str, Any], attempt: Dict[str, Any], razorpay_payment_id: str, signature: str = "",
) -> Dict[str, Any]:
    """Claim the attempt, then credit the wallet — exactly once.

    The claim (`created|abandoned → paid`) is the guard: a double-tapped
    verify, a webhook retry, a recovery call and a flaky network can all race
    here and only ONE of them can move money. The credit itself goes through
    `shop_money.credit()` so the row carries credit/debit, previous/new
    balance and an idempotency key — that is what makes it show up correctly
    in the System Wallet user-liability group and reconcile in net worth.
    """
    amount = round(float(attempt["amount"]), 2)
    ts = now_utc().isoformat()
    claimed = await db.wallet_topups.update_one(
        {"id": attempt["id"], "status": {"$in": ["created", "abandoned"]}},
        {"$set": {
            "status": "paid",
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_signature": signature,
            "paid_at": ts,
        }},
    )
    if claimed.modified_count != 1:
        fresh_u = await db.users.find_one({"id": user["id"]}, {"_id": 0, "wallet_balance": 1})
        return {
            "ok": True, "already_verified": True, "amount": amount,
            "balance": round(float((fresh_u or {}).get("wallet_balance") or 0), 2),
        }

    row = await shop_money.credit(
        user["id"], shop_money.CUSTOMER_WALLET, amount,
        idempotency_key=f"TOPUP:{attempt['id']}",
        txn_type="wallet_topup",
        group="wallet",
        settlement_status="paid",
        payment_method="online",
        payment_id=razorpay_payment_id,
        description=f"Money added to wallet · ₹{amount:.0f}",
        extra={
            "razorpay_order_id": attempt.get("razorpay_order_id"),
            "razorpay_payment_id": razorpay_payment_id,
            "topup_id": attempt["id"],
        },
    )
    if not row:
        # The ledger refused to write a second row for this attempt (it was
        # already credited). Never leave the attempt marked paid with no
        # money: find the real credit and report it, or hand the attempt back
        # so it stays claimable.
        existing = await db.transactions.find_one(
            {"idempotency_key": f"TOPUP:{attempt['id']}"}, {"_id": 0},
        )
        if not existing:
            await db.wallet_topups.update_one(
                {"id": attempt["id"]},
                {"$set": {"status": "abandoned", "credit_failed_at": ts}},
            )
            raise HTTPException(
                status_code=503,
                detail="We could not credit your wallet just now. Nothing is lost — "
                       "tap Recover payment in a moment.",
            )
        row = existing
    short_code = row.get("reference_number") or row.get("id")
    # Asset side: the cash is in the company account, the wallet balance is
    # the matching liability — company net worth is unchanged by a top-up.
    await db.bank_ledger.update_one(
        {"topup_id": attempt["id"]},
        {"$setOnInsert": {
            "id": str(uuid.uuid4()),
            "kind": "credit",
            "amount": amount,
            "description": f"Wallet top-up by {user.get('name') or user.get('email')} ({short_code})",
            "category": "wallet_topup",
            "utr": razorpay_payment_id,
            "happened_at": ts,
            "created_at": ts,
            "user_id": user["id"],
            "topup_id": attempt["id"],
        }},
        upsert=True,
    )
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


@router.post("/wallet/topup/verify")
async def verify_topup(payload: VerifyTopup, user: Dict[str, Any] = Depends(get_current_user)):
    # Resolve the attempt by OUR id, or by either Razorpay id — a client that
    # lost its local attempt id must still be able to claim its own payment.
    or_terms: list = [{"id": payload.payment_id}]
    if payload.razorpay_order_id:
        or_terms.append({"razorpay_order_id": payload.razorpay_order_id})
    if payload.razorpay_payment_id:
        or_terms.append({"razorpay_payment_id": payload.razorpay_payment_id})
    attempt = await db.wallet_topups.find_one(
        {"user_id": user["id"], "$or": or_terms}, {"_id": 0}, sort=[("created_at", -1)],
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
    if attempt["status"] not in ("created", "abandoned"):
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
            # A bad signature is NOT proof the money wasn't taken, so the
            # attempt is left claimable and the client is told to recover.
            raise HTTPException(
                status_code=401,
                detail="We could not confirm that payment signature. If your money was "
                       "debited, tap Recover payment — nothing is lost.",
            )
        rzp = await fetch_payment(payload.razorpay_payment_id, creds)
        if rzp:
            status = (rzp.get("status") or "").lower()
            if status not in ("captured", "authorized"):
                raise HTTPException(status_code=400, detail=f"Payment is not captured (status: {status})")
            expected_paise = int(round(amount * 100))
            if int(rzp.get("amount") or 0) not in (0, expected_paise):
                raise HTTPException(status_code=400, detail="Payment amount does not match the top-up")

    return await _credit_topup(user, attempt, payload.razorpay_payment_id, payload.razorpay_signature)


class RecoverTopup(BaseModel):
    payment_id: str = ""
    razorpay_order_id: str = ""
    razorpay_payment_id: str = ""


@router.get("/wallet/topup/pending")
async def pending_topups(user: Dict[str, Any] = Depends(get_current_user)):
    """Unfinished top-ups this customer can still recover."""
    rows = await db.wallet_topups.find(
        {"user_id": user["id"], "status": {"$in": ["created", "abandoned"]}},
        {"_id": 0, "razorpay_signature": 0},
    ).sort("created_at", -1).limit(10).to_list(10)
    return {"items": rows, "total": len(rows)}


@router.post("/wallet/topup/recover")
async def recover_topup(payload: RecoverTopup, user: Dict[str, Any] = Depends(get_current_user)):
    """"Razorpay took my money but the app said it failed."

    Instead of believing the client's checkout callback, this asks RAZORPAY
    what actually happened to the order. If Razorpay reports a captured (or
    authorised) payment, the wallet is credited exactly once through the same
    claim as verify — so recovery can be tapped repeatedly with no risk of
    double credit. If Razorpay reports nothing captured, NO money is created:
    the attempt stays open and admin can see it in the reconciliation list.
    """
    or_terms: list = [{"status": {"$in": ["created", "abandoned"]}}]
    if payload.payment_id:
        or_terms = [{"id": payload.payment_id}]
    elif payload.razorpay_order_id:
        or_terms = [{"razorpay_order_id": payload.razorpay_order_id}]
    elif payload.razorpay_payment_id:
        or_terms = [{"razorpay_payment_id": payload.razorpay_payment_id}]
    attempt = await db.wallet_topups.find_one(
        {"user_id": user["id"], "$or": or_terms}, {"_id": 0}, sort=[("created_at", -1)],
    )
    if not attempt:
        raise HTTPException(status_code=404, detail="No top-up to recover")
    if attempt["status"] == "paid":
        fresh = await db.users.find_one({"id": user["id"]}, {"_id": 0, "wallet_balance": 1})
        return {
            "ok": True, "already_verified": True, "amount": attempt["amount"],
            "balance": round(float((fresh or {}).get("wallet_balance") or 0), 2),
        }

    creds = await get_creds()
    if creds["is_mock"]:
        # Test mode has no gateway to ask; the attempt itself is the proof.
        return await _credit_topup(
            user, attempt,
            payload.razorpay_payment_id or f"pay_MOCK_RECOVER_{uuid.uuid4().hex[:10]}",
        )

    paid = None
    for p in await fetch_order_payments(attempt["razorpay_order_id"], creds):
        if (p.get("status") or "").lower() in ("captured", "authorized"):
            paid = p
            break
    if not paid and payload.razorpay_payment_id:
        one = await fetch_payment(payload.razorpay_payment_id, creds)
        if one and (one.get("status") or "").lower() in ("captured", "authorized"):
            if one.get("order_id") in (None, attempt["razorpay_order_id"]):
                paid = one
    if not paid:
        raise HTTPException(
            status_code=409,
            detail="Razorpay has no successful payment for this top-up yet. If your bank "
                   "shows a debit, it will either auto-refund or our team can release it — "
                   "nothing has been lost.",
        )
    expected_paise = int(round(float(attempt["amount"]) * 100))
    if int(paid.get("amount") or 0) not in (0, expected_paise):
        raise HTTPException(status_code=400, detail="The captured amount does not match this top-up")
    return await _credit_topup(user, attempt, str(paid.get("id") or ""))
