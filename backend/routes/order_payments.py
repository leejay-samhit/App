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
import re
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.db import db
from core.razorpay import create_order, fetch_payment, get_creds, verify_signature
from core.security import get_current_user
from core.utils import now_utc, get_settings
from core.delivery_charges import compute_cart_delivery
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


async def _price_cart(user_id: str) -> Dict[str, float]:
    """Authoritative payable total — NEVER trust a client-sent amount.

    Phase-1 fix: this used to price the GOODS only, while checkout showed
    goods + delivery, so Razorpay collected ₹470 for a ₹500 order. The same
    delivery engine the checkout screen uses now runs here, so the gateway
    amount is always exactly what the customer was shown:

        items + delivery − wallet portion = online amount
    """
    rows = await db.cart_items.find({"user_id": user_id}, {"_id": 0}).to_list(1000)
    if not rows:
        raise HTTPException(status_code=400, detail="Cart is empty")
    pids = list({r.get("product_id") for r in rows if r.get("product_id")})
    products = {
        p["id"]: p
        async for p in db.products.find({"id": {"$in": pids}}, {"_id": 0, "images": 0, "description": 0})
    }
    groups: Dict[str, Dict[str, Any]] = {}
    goods = 0.0
    for r in rows:
        p = products.get(r.get("product_id"))
        if not p:
            continue
        variant = find_variant(p, r.get("variant_id"))
        line = round(effective_line_price(p, variant) * float(r.get("qty") or 0), 2)
        goods += line
        vkey = p.get("vendor_id") or "__no_vendor__"
        g = groups.setdefault(vkey, {
            "vendor_key": vkey,
            "vendor_id": p.get("vendor_id"),
            "subtotal": 0.0,
            "free_delivery": True,
        })
        g["subtotal"] = round(g["subtotal"] + line, 2)
        g["free_delivery"] = g["free_delivery"] and bool(p.get("free_delivery"))
    goods = round(goods, 2)
    if goods <= 0:
        raise HTTPException(status_code=400, detail="Cart total invalid")

    settings = await get_settings()
    vendor_docs: Dict[str, Any] = {}
    for vkey in groups:
        if vkey == "__no_vendor__":
            continue
        vd = await db.users.find_one(
            {"id": vkey},
            {"_id": 0, "id": 1, "delivery_charge_flat": 1, "delivery_free_threshold": 1},
        )
        if vd:
            vendor_docs[vkey] = vd
    quote = compute_cart_delivery(list(groups.values()), settings, vendor_docs)
    delivery = round(float(quote.get("total") or 0), 2)
    return {"goods": goods, "delivery": delivery, "total": round(goods + delivery, 2)}


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
    priced = await _price_cart(user["id"])
    total = priced["total"]
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
        "goods_total": priced["goods"],
        "delivery_total": priced["delivery"],
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
    out["goods_total"] = priced["goods"]
    out["delivery_total"] = priced["delivery"]
    out["description"] = f"Slangcart order · ₹{online_amount:.0f}"
    return out


class RechargeStart(BaseModel):
    kind: str                       # "mobile" | "dth"
    product_id: str
    account: str                    # mobile number, or DTH subscriber id
    state: Optional[str] = None
    network: Optional[str] = None
    # Jun-2026 — how much of the plan to pay out of the Slangcart wallet.
    # The rest goes to Razorpay, exactly like the shop checkout split.
    wallet_amount: float = 0.0


class RechargeWalletPay(BaseModel):
    """Pay for a plan entirely from the Slangcart wallet (no gateway)."""
    kind: str
    product_id: str
    account: str
    state: Optional[str] = None
    network: Optional[str] = None


class RechargeVerify(BaseModel):
    payment_id: str
    razorpay_order_id: Optional[str] = None
    razorpay_payment_id: Optional[str] = None
    razorpay_signature: Optional[str] = None


def _clean_account(kind: str, raw: str) -> str:
    """Validate + normalise the number being recharged."""
    if kind not in ("mobile", "dth"):
        raise HTTPException(status_code=400, detail="kind must be mobile or dth")
    account = re.sub(r"\s+", "", raw or "")
    if kind == "mobile":
        digits = re.sub(r"\D+", "", account)[-10:]
        if len(digits) != 10 or digits[0] not in "6789":
            raise HTTPException(status_code=400, detail="Enter a valid 10-digit mobile number.")
        return digits
    if len(account) < 6:
        raise HTTPException(status_code=400, detail="Enter a valid subscriber / customer ID.")
    return account


async def _recharge_plan(product_id: str) -> Dict[str, Any]:
    plan = await db.products.find_one(
        {"id": product_id, "active": {"$ne": False}},
        {"_id": 0, "id": 1, "name": 1, "price": 1, "recharge_kind": 1,
         "recharge_network": 1, "recharge_state": 1, "vendor_id": 1, "subcategory": 1},
    )
    if not plan:
        raise HTTPException(status_code=404, detail="That recharge plan is no longer available.")
    if round(float(plan.get("price") or 0), 2) <= 0:
        raise HTTPException(status_code=400, detail="This plan has no price set.")
    return plan


@router.post("/recharge/pay/wallet")
async def pay_recharge_from_wallet(
    payload: RechargeWalletPay,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Jun-2026 — pay for a plan straight from the Slangcart wallet.

    No gateway, so there is no bank row: the money is already ours. The
    wallet debit is atomic (guarded on the balance) so a double tap cannot
    book two recharges, and the booking itself goes through the SAME
    `book_recharge_order` the online path uses — same order, same seller
    credit, same ledger rows.
    """
    account = _clean_account(payload.kind, payload.account)
    plan = await _recharge_plan(payload.product_id)
    amount = round(float(plan["price"]), 2)
    if user.get("wallet_frozen"):
        raise HTTPException(status_code=400, detail="Your wallet is frozen — contact support.")
    balance = round(float(user.get("wallet_balance") or 0), 2)
    if balance + 0.009 < amount:
        raise HTTPException(
            status_code=400,
            detail=f"Wallet has ₹{balance:,.2f} — ₹{round(amount - balance, 2):,.2f} short. Pay online instead.",
        )

    attempt = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "kind": payload.kind,
        "product_id": plan["id"],
        "plan_name": plan.get("name") or "Recharge",
        "account": account,
        "state": payload.state or plan.get("recharge_state"),
        "network": payload.network or plan.get("recharge_network"),
        "amount": amount,
        "wallet_amount": amount,
        "online_amount": 0.0,
        "razorpay_order_id": None,
        "razorpay_payment_id": None,
        "status": "created",
        "method": "wallet",
        "is_mock": False,
        "created_at": now_utc().isoformat(),
    }
    await db.recharge_payments.insert_one(dict(attempt))

    debited = await db.users.update_one(
        {"id": user["id"], "wallet_balance": {"$gte": amount}},
        {"$inc": {"wallet_balance": -amount}},
    )
    if debited.modified_count == 0:
        await db.recharge_payments.update_one(
            {"id": attempt["id"]},
            {"$set": {"status": "failed", "failed_reason": "insufficient_wallet"}},
        )
        raise HTTPException(status_code=400, detail="Wallet balance changed — please try again.")

    recharge_id = str(uuid.uuid4())
    await db.recharge_payments.update_one(
        {"id": attempt["id"]},
        {"$set": {"status": "paid", "recharge_id": recharge_id,
                  "paid_at": now_utc().isoformat()}},
    )
    doc = {
        "id": recharge_id,
        "user_id": user["id"],
        "kind": attempt["kind"],
        "product_id": attempt["product_id"],
        "plan_name": attempt["plan_name"],
        "account": account,
        "state": attempt.get("state"),
        "network": attempt.get("network"),
        "amount": amount,
        "wallet_amount": amount,
        "online_amount": 0.0,
        "status": "processing",
        "payment_id": attempt["id"],
        "paid_via": "wallet",
        "created_at": now_utc().isoformat(),
    }
    await db.recharges.insert_one(dict(doc))
    from core.recharge_order import book_recharge_order
    order = await book_recharge_order(user, attempt, recharge_id)
    await db.recharges.update_one(
        {"id": recharge_id},
        {"$set": {"order_id": order.get("id"), "order_number": order.get("order_number")}},
    )
    return {
        "ok": True, "recharge_id": recharge_id, "account": account, "amount": amount,
        "plan_name": attempt["plan_name"], "status": "processing", "paid_via": "wallet",
        "order_id": order.get("id"), "order_number": order.get("order_number"),
    }


@router.post("/recharge/payment/start")
async def start_recharge_payment(
    payload: RechargeStart,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Oct-2026 — pay-online for a recharge plan.

    A recharge is not a shop order: nothing ships, there is no cart and no
    delivery charge, so it gets its own attempt row and its own verify step.
    The money path is identical to the shop flow (same Razorpay creds, same
    signature + amount verification, same mock-mode behaviour in preview),
    which is exactly why it reuses these helpers instead of inventing a
    second payment pipeline.
    """
    if payload.kind not in ("mobile", "dth"):
        raise HTTPException(status_code=400, detail="kind must be mobile or dth")
    account = _clean_account(payload.kind, payload.account)

    plan = await _recharge_plan(payload.product_id)
    amount = round(float(plan.get("price") or 0), 2)

    # Jun-2026 — wallet + UPI split, same rule as the shop checkout: the
    # wallet can cover part (or all but a rupee) of the plan, Razorpay
    # collects the rest. A FULL wallet payment goes through
    # /recharge/pay/wallet instead, which needs no gateway at all.
    balance = 0.0 if user.get("wallet_frozen") else round(float(user.get("wallet_balance") or 0), 2)
    wallet_amount = round(min(max(0.0, float(payload.wallet_amount or 0)), balance, amount), 2)
    online_amount = round(amount - wallet_amount, 2)
    if online_amount <= 0.009:
        raise HTTPException(
            status_code=400,
            detail="Your wallet covers this plan — use the Pay from wallet option.",
        )

    creds = await get_creds()
    await db.recharge_payments.delete_many({"user_id": user["id"], "status": "created"})
    try:
        rzp_order_id = await create_order(
            int(round(online_amount * 100)),
            f"rchg_{user['id'][:12]}_{uuid.uuid4().hex[:6]}",
            notes={"user_id": user["id"], "kind": "recharge",
                   "account": account, "plan": plan["id"]},
            creds=creds,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    attempt = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "kind": payload.kind,
        "product_id": plan["id"],
        "plan_name": plan.get("name") or "Recharge",
        "account": account,
        "state": payload.state or plan.get("recharge_state"),
        "network": payload.network or plan.get("recharge_network"),
        "amount": amount,
        "wallet_amount": wallet_amount,
        "online_amount": online_amount,
        "razorpay_order_id": rzp_order_id,
        "razorpay_payment_id": None,
        "status": "created",
        "method": "wallet_online" if wallet_amount > 0.009 else "online",
        "is_mock": creds["is_mock"],
        "created_at": now_utc().isoformat(),
    }
    await db.recharge_payments.insert_one(dict(attempt))
    # NOTE: deliberately NOT using `_public` — that helper shapes a SHOP
    # order attempt (cart_total, wallet_amount, delivery_total), none of
    # which exist on a recharge. Building the payload here keeps the two
    # flows from leaking each other's fields.
    return {
        "payment_id": attempt["id"],
        "razorpay_order_id": rzp_order_id,
        "amount_paise": int(round(online_amount * 100)),
        "amount": amount,
        "online_amount": online_amount,
        "wallet_amount": wallet_amount,
        "key_id": creds["key_id"],
        "is_mock": creds["is_mock"],
        "account": account,
        "plan_name": attempt["plan_name"],
        "network": attempt.get("network"),
        "state": attempt.get("state"),
        "description": f"{attempt['plan_name']} · {account}",
        "prefill": {
            "name": user.get("name") or "",
            "email": user.get("email") or "",
            "contact": user.get("phone") or account,
        },
    }


@router.post("/recharge/payment/verify")
async def verify_recharge_payment(
    payload: RechargeVerify,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Confirm the Razorpay payment and book the recharge.

    Idempotent: a repeated call on an already-paid attempt returns the same
    recharge instead of charging or booking twice.
    """
    attempt = await db.recharge_payments.find_one(
        {"id": payload.payment_id, "user_id": user["id"]}, {"_id": 0},
    )
    if not attempt:
        raise HTTPException(status_code=404, detail="Payment attempt not found")
    if attempt["status"] == "paid":
        return {"ok": True, "already_verified": True,
                "recharge_id": attempt.get("recharge_id"),
                "account": attempt["account"], "amount": attempt["amount"]}
    if attempt["status"] != "created":
        raise HTTPException(status_code=400, detail=f"Payment attempt is {attempt['status']}")
    if payload.razorpay_order_id and payload.razorpay_order_id != attempt["razorpay_order_id"]:
        raise HTTPException(status_code=400, detail="Payment order mismatch")
    if not payload.razorpay_payment_id:
        raise HTTPException(status_code=400, detail="Missing Razorpay payment id")

    creds = await get_creds()
    if not creds["is_mock"]:
        if not verify_signature(
            attempt["razorpay_order_id"], payload.razorpay_payment_id,
            payload.razorpay_signature, creds["key_secret"],
        ):
            await db.recharge_payments.update_one(
                {"id": attempt["id"]},
                {"$set": {"status": "failed", "failed_reason": "bad_signature"}},
            )
            raise HTTPException(status_code=401, detail="Invalid payment signature")
        rzp = await fetch_payment(payload.razorpay_payment_id, creds)
        if rzp:
            status = (rzp.get("status") or "").lower()
            if status not in ("captured", "authorized"):
                raise HTTPException(status_code=400, detail=f"Payment is not captured (status: {status})")
            expected_paise = int(round(attempt["amount"] * 100))
            if int(rzp.get("amount") or 0) not in (0, expected_paise):
                raise HTTPException(status_code=400, detail="Payment amount does not match the plan")

    # Jun-2026 — a wallet + UPI split pays its wallet slice here, once the
    # gateway leg is confirmed. Atomic and guarded on the balance, so the
    # recharge is never booked against money the wallet no longer has.
    wallet_slice = round(float(attempt.get("wallet_amount") or 0), 2)
    if wallet_slice > 0.009:
        debited = await db.users.update_one(
            {"id": user["id"], "wallet_balance": {"$gte": wallet_slice}},
            {"$inc": {"wallet_balance": -wallet_slice}},
        )
        if debited.modified_count == 0:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Your wallet no longer has ₹{wallet_slice:,.2f}. You have NOT been "
                    f"charged twice — contact support with this payment id."
                ),
            )

    # Claim the attempt first — the guarded update is what makes a double
    # tap (or a webhook racing the client) impossible to double-book.
    recharge_id = str(uuid.uuid4())
    claimed = await db.recharge_payments.update_one(
        {"id": attempt["id"], "status": "created"},
        {"$set": {
            "status": "paid",
            "razorpay_payment_id": payload.razorpay_payment_id,
            "razorpay_signature": payload.razorpay_signature,
            "recharge_id": recharge_id,
            "paid_at": now_utc().isoformat(),
        }},
    )
    if claimed.modified_count == 0:
        fresh = await db.recharge_payments.find_one({"id": attempt["id"]}, {"_id": 0})
        return {"ok": True, "already_verified": True,
                "recharge_id": (fresh or {}).get("recharge_id"),
                "account": attempt["account"], "amount": attempt["amount"]}

    doc = {
        "id": recharge_id,
        "user_id": user["id"],
        "kind": attempt["kind"],
        "product_id": attempt["product_id"],
        "plan_name": attempt["plan_name"],
        "account": attempt["account"],
        "state": attempt.get("state"),
        "network": attempt.get("network"),
        "amount": attempt["amount"],
        "wallet_amount": wallet_slice,
        "online_amount": round(float(attempt.get("online_amount") or attempt["amount"]), 2),
        "status": "processing",
        "payment_id": attempt["id"],
        "paid_via": "wallet_online" if wallet_slice > 0.009 else "online",
        "razorpay_payment_id": payload.razorpay_payment_id,
        "created_at": now_utc().isoformat(),
    }
    await db.recharges.insert_one(dict(doc))

    # Jun-2026 FIX — a paid recharge now becomes a real ORDER: the seller
    # sees the number to recharge, his shop wallet is credited, the online
    # money lands in the Bank Ledger and both payment legs show in the
    # customer's transactions. Before this, the money vanished from every
    # report the moment it was taken.
    from core.recharge_order import book_recharge_order
    order = await book_recharge_order(
        user, attempt, recharge_id, razorpay_payment_id=payload.razorpay_payment_id,
    )
    await db.recharges.update_one(
        {"id": recharge_id},
        {"$set": {"order_id": order.get("id"), "order_number": order.get("order_number")}},
    )
    return {"ok": True, "recharge_id": recharge_id,
            "account": attempt["account"], "amount": attempt["amount"],
            "plan_name": attempt["plan_name"], "status": "processing",
            "wallet_amount": wallet_slice,
            "order_id": order.get("id"), "order_number": order.get("order_number")}


@router.get("/recharge/history")
async def recharge_history(user: Dict[str, Any] = Depends(get_current_user)):
    """Past recharges, newest first, each one ready to REPEAT.

    Jun-2026 — the row carries everything the pay flow needs (plan id, kind,
    circle, operator, the number) plus whether the plan is still live and at
    what price, so "Repeat" is one tap and never sends the shopper to a plan
    that has since been pulled or re-priced.
    """
    rows = await db.recharges.find(
        {"user_id": user["id"]}, {"_id": 0},
    ).sort("created_at", -1).limit(50).to_list(50)
    pids = [r.get("product_id") for r in rows if r.get("product_id")]
    plans: Dict[str, Any] = {}
    if pids:
        async for p in db.products.find(
            {"id": {"$in": pids}},
            {"_id": 0, "id": 1, "name": 1, "price": 1, "active": 1, "is_published": 1,
             "description": 1, "recharge_data": 1, "recharge_validity": 1, "recharge_calls": 1},
        ):
            plans[p["id"]] = p
    from routes.recharge import plan_highlights
    networks: Dict[str, Any] = {}
    async for o in db.recharge_options.find({"group": "network"}, {"_id": 0}):
        networks[o.get("slug")] = o
    out = []
    for r in rows:
        plan = plans.get(r.get("product_id") or "") or {}
        live = bool(plan) and plan.get("active") is not False and plan.get("is_published") is not False
        net = networks.get(r.get("network") or "") or {}
        out.append({
            **r,
            "network_name": net.get("name") or r.get("network") or "",
            "network_logo": net.get("image_url") or None,
            "can_repeat": live,
            "current_price": round(float(plan.get("price") or 0), 2) if live else None,
            "price_changed": bool(live and abs(float(plan.get("price") or 0) - float(r.get("amount") or 0)) > 0.009),
            "highlights": plan_highlights(plan) if plan else {"data": "", "validity": "", "calls": ""},
        })
    return {"items": out}


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
