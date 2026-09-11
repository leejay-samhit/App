"""Razorpay ONLINE payment for shop order checkout (Jun 2026).

Flow (mirrors the registration-fee flow, but for the cart):

  1. POST /orders/payment/start    → prices the cart SERVER-SIDE, works out how
     much the wallet covers and how much Razorpay must collect, creates the
     Razorpay order and stores an `order_payments` attempt (status=created).
  2. The app opens Razorpay Checkout with the returned order id.
  3. POST /orders/payment/verify   → HMAC-verifies `order_id|payment_id`,
     cross-checks amount/status with Razorpay (live mode only) and flips the
     attempt to status=paid.
  4. POST /orders/checkout with `payment_method=online|wallet_online` and
     `payment_id=<attempt id>` → server.py consumes the PAID attempt (once)
     and creates the per-vendor orders.

If step 4 ever fails after money was captured, the attempt stays `paid` and
un-consumed: GET /orders/payment/pending lets the app resume it instead of
charging the customer twice.
"""
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.db import db
from core.razorpay import create_order, fetch_payment, get_creds, verify_signature
from core.security import get_current_user
from core.utils import now_utc
from core.variants import effective_line_price, find_variant

router = APIRouter()


class StartOnlinePayment(BaseModel):
    # How much of the bill the wallet should cover (0 = pay everything online).
    wallet_amount: float = Field(default=0, ge=0)


class VerifyOnlinePayment(BaseModel):
    payment_id: str
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str = ""


async def _price_cart(user_id: str) -> float:
    """Authoritative cart total — never trust a client-sent amount."""
    rows = await db.cart_items.find({"user_id": user_id}, {"_id": 0}).to_list(1000)
    if not rows:
        raise HTTPException(status_code=400, detail="Cart is empty")
    pids = list({r.get("product_id") for r in rows if r.get("product_id")})
    products = {
        p["id"]: p
        async for p in db.products.find({"id": {"$in": pids}}, {"_id": 0, "images": 0, "description": 0})
    }
    total = 0.0
    for r in rows:
        p = products.get(r.get("product_id"))
        if not p:
            continue
        variant = find_variant(p, r.get("variant_id"))
        total += effective_line_price(p, variant) * float(r.get("qty") or 0)
    total = round(total, 2)
    if total <= 0:
        raise HTTPException(status_code=400, detail="Cart total invalid")
    return total


def _public(attempt: Dict[str, Any], creds: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "payment_id": attempt["id"],
        "razorpay_order_id": attempt["razorpay_order_id"],
        "amount": attempt["online_amount"],
        "amount_paise": int(round(attempt["online_amount"] * 100)),
        "wallet_amount": attempt["wallet_amount"],
        "total": attempt["cart_total"],
        "currency": "INR",
        "key_id": creds["key_id"] or "rzp_test_MOCK",
        "is_mock": creds["is_mock"],
        "status": attempt["status"],
    }


@router.post("/orders/payment/start")
async def start_online_payment(
    payload: StartOnlinePayment,
    user: Dict[str, Any] = Depends(get_current_user),
):
    total = await _price_cart(user["id"])
    balance = float(user.get("wallet_balance") or 0)
    if user.get("wallet_frozen"):
        balance = 0.0
    wallet_amount = round(min(float(payload.wallet_amount or 0), balance, total), 2)
    online_amount = round(total - wallet_amount, 2)
    if online_amount <= 0:
        raise HTTPException(
            status_code=400,
            detail="Your wallet already covers this order — pick the Wallet payment option.",
        )

    creds = await get_creds()
    prefill = {
        "name": user.get("name") or "",
        "email": user.get("email") or "",
        "contact": user.get("phone") or "",
    }

    # Keep at most ONE open attempt per user: re-tapping "Pay" refreshes the
    # pending row instead of littering the collection with phantom attempts.
    await db.order_payments.delete_many({"user_id": user["id"], "status": "created"})

    try:
        rzp_order_id = await create_order(
            int(round(online_amount * 100)),
            f"order_{user['id'][:12]}_{uuid.uuid4().hex[:6]}",
            notes={"user_id": user["id"], "kind": "shop_order"},
            creds=creds,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    attempt = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "cart_total": total,
        "wallet_amount": wallet_amount,
        "online_amount": online_amount,
        "razorpay_order_id": rzp_order_id,
        "razorpay_payment_id": None,
        "status": "created",
        "is_mock": creds["is_mock"],
        "consumed_order_group": None,
        "created_at": now_utc().isoformat(),
    }
    await db.order_payments.insert_one(dict(attempt))
    out = _public(attempt, creds)
    out["prefill"] = prefill
    out["description"] = f"Slangcart order · ₹{online_amount:.0f}"
    return out


@router.post("/orders/payment/verify")
async def verify_online_payment(
    payload: VerifyOnlinePayment,
    user: Dict[str, Any] = Depends(get_current_user),
):
    attempt = await db.order_payments.find_one(
        {"id": payload.payment_id, "user_id": user["id"]}, {"_id": 0},
    )
    if not attempt:
        raise HTTPException(status_code=404, detail="Payment attempt not found")
    if attempt["status"] == "paid":
        return {"ok": True, "payment_id": attempt["id"], "already_verified": True}
    if attempt["status"] != "created":
        raise HTTPException(status_code=400, detail=f"Payment attempt is {attempt['status']}")
    # Always trust OUR stored order id, never the one echoed by the client.
    if payload.razorpay_order_id and payload.razorpay_order_id != attempt["razorpay_order_id"]:
        raise HTTPException(status_code=400, detail="Payment order mismatch")
    if not payload.razorpay_payment_id:
        raise HTTPException(status_code=400, detail="Missing Razorpay payment id")

    creds = await get_creds()
    if not creds["is_mock"]:
        if not verify_signature(
            attempt["razorpay_order_id"],
            payload.razorpay_payment_id,
            payload.razorpay_signature,
            creds["key_secret"],
        ):
            await db.order_payments.update_one(
                {"id": attempt["id"]}, {"$set": {"status": "failed", "failed_reason": "bad_signature"}},
            )
            raise HTTPException(status_code=401, detail="Invalid payment signature")
        rzp = await fetch_payment(payload.razorpay_payment_id, creds)
        if rzp:
            status = (rzp.get("status") or "").lower()
            if status not in ("captured", "authorized"):
                raise HTTPException(status_code=400, detail=f"Payment is not captured (status: {status})")
            expected_paise = int(round(attempt["online_amount"] * 100))
            if int(rzp.get("amount") or 0) not in (0, expected_paise):
                raise HTTPException(status_code=400, detail="Payment amount does not match the order")
    elif not payload.razorpay_payment_id:
        raise HTTPException(status_code=400, detail="Missing Razorpay payment id")

    await db.order_payments.update_one(
        {"id": attempt["id"], "status": "created"},
        {"$set": {
            "status": "paid",
            "razorpay_payment_id": payload.razorpay_payment_id,
            "razorpay_signature": payload.razorpay_signature,
            "paid_at": now_utc().isoformat(),
        }},
    )
    return {
        "ok": True,
        "payment_id": attempt["id"],
        "online_amount": attempt["online_amount"],
        "wallet_amount": attempt["wallet_amount"],
    }


@router.get("/orders/payment/pending")
async def pending_online_payment(user: Dict[str, Any] = Depends(get_current_user)):
    """A paid-but-not-yet-placed attempt, so the app can resume instead of
    asking the customer to pay a second time."""
    attempt = await db.order_payments.find_one(
        {"user_id": user["id"], "status": "paid", "consumed_order_group": None},
        {"_id": 0},
        sort=[("paid_at", -1)],
    )
    if not attempt:
        return {"pending": None}
    return {
        "pending": {
            "payment_id": attempt["id"],
            "online_amount": attempt["online_amount"],
            "wallet_amount": attempt["wallet_amount"],
            "total": attempt["cart_total"],
            "paid_at": attempt.get("paid_at"),
        },
    }


async def consume_paid_attempt(
    user_id: str,
    payment_id: str,
    expected_online: float,
    expected_wallet: float,
) -> Dict[str, Any]:
    """Claim a verified attempt for an order. Raises if it can't be used.

    Called from POST /orders/checkout. The `consumed_order_group: None`
    condition makes this single-use, so a double-tapped checkout can't place
    two sets of orders against one payment.
    """
    attempt = await db.order_payments.find_one({"id": payment_id, "user_id": user_id}, {"_id": 0})
    if not attempt:
        raise HTTPException(status_code=400, detail="Online payment not found. Please pay again.")
    if attempt["status"] != "paid":
        raise HTTPException(status_code=400, detail="This payment has not been verified yet.")
    if attempt.get("consumed_order_group"):
        raise HTTPException(status_code=400, detail="This payment was already used for an order.")
    if abs(float(attempt["online_amount"]) - float(expected_online)) > 1.0:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Your cart changed after paying (paid ₹{attempt['online_amount']:.0f} online, "
                f"now ₹{expected_online:.0f}). Contact support — you have not been charged twice."
            ),
        )
    if abs(float(attempt["wallet_amount"]) - float(expected_wallet)) > 1.0:
        raise HTTPException(status_code=400, detail="Wallet split changed after payment. Please retry.")
    return attempt


async def mark_attempt_consumed(payment_id: str, group_id: str) -> None:
    await db.order_payments.update_one(
        {"id": payment_id, "consumed_order_group": None},
        {"$set": {"consumed_order_group": group_id, "consumed_at": now_utc().isoformat()}},
    )
