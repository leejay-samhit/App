"""Turn a PAID recharge into a real order + the money rows behind it.

Jun-2026 owner report: a recharge took the customer's money and then
disappeared — the vendor never saw the request (so nobody could actually do
the recharge), the amount showed up neither in the System Wallet treasury nor
in the Bank Ledger, the seller's shop wallet was never credited, and paying
from the Slangcart wallet wasn't offered at all.

The fix is to stop treating a recharge as a stand-alone receipt and give it
the same skeleton a shop order has:

    orders            → the vendor's work queue (what number to recharge)
    vendor_sales      → the seller's sales ledger row
    transactions      → the buyer's wallet leg and/or UPI leg
    shop_money        → vendor shop-wallet credit (Group 2 liability)
    bank_ledger       → the online slice really landing in our bank (Group 7)

Nothing here invents new money rules; it calls the SAME engines the shop
checkout calls, so the treasury maths stays the one maths.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from core import bank, shop_money
from core.db import db
from core.utils import now_utc

logger = logging.getLogger(__name__)


def paid_via_for(wallet_paid: float, online_paid: float) -> str:
    if wallet_paid > 0.009 and online_paid > 0.009:
        return "wallet_online"
    if online_paid > 0.009:
        return "online"
    return "wallet"


async def book_recharge_order(
    user: Dict[str, Any],
    attempt: Dict[str, Any],
    recharge_id: str,
    *,
    razorpay_payment_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create the order + every money row for one paid recharge.

    Idempotent: keyed on `recharge_id` for the order and on the shop-money /
    bank ledger keys for the money, so a replayed verify can never book or
    credit twice.
    """
    existing = await db.orders.find_one({"recharge_id": recharge_id}, {"_id": 0})
    if existing:
        return existing

    amount = round(float(attempt.get("amount") or 0), 2)
    wallet_paid = round(float(attempt.get("wallet_amount") or 0), 2)
    online_paid = round(max(0.0, amount - wallet_paid), 2)
    ts = now_utc().isoformat()

    plan = await db.products.find_one(
        {"id": attempt.get("product_id")},
        {"_id": 0, "id": 1, "name": 1, "price": 1, "image_url": 1, "vendor_id": 1,
         "recharge_network": 1, "recharge_kind": 1},
    ) or {}
    vendor_id = plan.get("vendor_id")
    vendor_name = None
    if vendor_id:
        v = await db.users.find_one(
            {"id": vendor_id},
            {"_id": 0, "name": 1, "vendor_business_name": 1, "shop_name": 1},
        ) or {}
        vendor_name = v.get("vendor_business_name") or v.get("shop_name") or v.get("name")

    kind = attempt.get("kind") or "mobile"
    account = attempt.get("account") or ""
    label = "Mobile recharge" if kind == "mobile" else "DTH recharge"
    item = {
        "product_id": plan.get("id") or attempt.get("product_id"),
        "name": attempt.get("plan_name") or "Recharge",
        "image_url": plan.get("image_url") or "",
        "qty": 1,
        "unit_price": amount,
        "line_total": amount,
        "vendor_id": vendor_id,
        "vendor_share": amount,
        "platform_share": 0.0,
        "cashback_amount": 0.0,
    }

    order_id = str(uuid.uuid4())
    order = {
        "id": order_id,
        "order_number": f"RC-{recharge_id[:6].upper()}",
        "group_id": recharge_id,
        "split_index": 1,
        "split_count": 1,
        "user_id": user["id"],
        "vendor_id": vendor_id,
        "vendor_name": vendor_name,
        "items": [item],
        "total": amount,
        "goods_total": amount,
        "delivery_charge": 0.0,
        "delivery_free": True,
        "delivery_reason": "digital",
        "cashback_amount": 0.0,
        "cashback_status": "not_applicable",
        "wallet_paid": wallet_paid,
        "online_paid": online_paid,
        "cod_due": 0.0,
        "status": "placed",
        "status_history": [{
            "status": "placed", "at": ts,
            "by_name": user.get("name") or "Customer", "by_role": "customer",
        }],
        "paid_via": paid_via_for(wallet_paid, online_paid),
        "payment_status": "paid",
        "razorpay_payment_id": razorpay_payment_id if online_paid > 0.009 else None,
        # ── What makes this a recharge, not a parcel ────────────────────
        "order_kind": "recharge",
        "is_recharge": True,
        "recharge_id": recharge_id,
        "recharge_kind": kind,
        "recharge_account": account,
        "recharge_network": attempt.get("network"),
        "recharge_state": attempt.get("state"),
        # Nothing ships — the "address" is the number being recharged.
        "shipping_address": {
            "name": user.get("name") or "Customer",
            "phone": user.get("phone") or account,
            "line1": f"{label} · {account}",
            "city": "", "pincode": "",
        },
        "created_at": ts,
    }
    await db.orders.insert_one(dict(order))

    # ── Buyer ledger: one row per real payment leg ─────────────────────
    desc_tail = f"{attempt.get('plan_name') or 'Recharge'} · {account}"
    if wallet_paid > 0.009:
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": user["id"],
            "type": "recharge",
            "amount": -wallet_paid,
            "status": "success",
            "description": f"{desc_tail} — ₹{wallet_paid:,.2f} paid from Slangcart wallet",
            "payment_leg": "wallet",
            "order_id": order_id,
            "recharge_id": recharge_id,
            "created_at": ts,
        })
    if online_paid > 0.009:
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": user["id"],
            "type": "recharge_payment_upi",
            "amount": -online_paid,
            "status": "success",
            "description": (
                f"{desc_tail} — ₹{online_paid:,.2f} paid by UPI / card"
                + (f", ₹{wallet_paid:,.2f} from wallet" if wallet_paid > 0.009 else "")
            ),
            "payment_leg": "online",
            "payment_method": "razorpay",
            "razorpay_payment_id": razorpay_payment_id,
            "order_id": order_id,
            "recharge_id": recharge_id,
            # Straight from the buyer's bank to ours — no wallet involved.
            "wallet_impact": "informational",
            "created_at": ts,
        })

    # ── Seller side ────────────────────────────────────────────────────
    if vendor_id:
        await db.vendor_sales.insert_one({
            "id": str(uuid.uuid4()),
            "vendor_id": vendor_id,
            "order_id": order_id,
            "order_number": order["order_number"],
            "group_id": recharge_id,
            "buyer_id": user["id"],
            "buyer_email": user.get("email"),
            "product_id": item["product_id"],
            "product_name": item["name"],
            "product_image_url": item["image_url"],
            "qty": 1,
            "line_total": amount,
            "vendor_share": amount,
            "platform_share": 0.0,
            "commission_pct": 0.0,
            "order_kind": "recharge",
            "created_at": ts,
        })
        try:
            credited = await shop_money.credit_vendor_for_order(
                order, payment_id=attempt.get("id"),
            )
            if credited > 0.009:
                from core.cashback import auto_recover_from_vendor_credit
                from server import credit_admin_bucket
                await auto_recover_from_vendor_credit(
                    vendor_id, order, credit_admin_bucket=credit_admin_bucket,
                )
        except Exception as e:
            logger.warning(f"recharge vendor credit failed for {order_id}: {str(e)[:200]}")
            await shop_money.record_financial_error(
                "vendor_credit_failed", str(e), order_id=order_id, vendor_id=vendor_id,
            )

    # ── Bank Ledger: the online slice physically reached our account ───
    if online_paid > 0.009:
        await bank.post_bank(
            kind="credit",
            amount=online_paid,
            category="recharge_online",
            description=f"Recharge paid online · {desc_tail}",
            ref_key=f"RCHGPAY:{attempt['id']}",
            utr=razorpay_payment_id,
            user_id=user["id"],
            extra={
                "recharge_id": recharge_id,
                "order_id": order_id,
                "vendor_ids": [vendor_id] if vendor_id else [],
                "razorpay_payment_id": razorpay_payment_id,
                "razorpay_order_id": attempt.get("razorpay_order_id"),
            },
        )

    # ── Tell the people who have to act ────────────────────────────────
    try:
        from server import _create_notification, ADMIN_EMAIL
        if vendor_id:
            await _create_notification(
                vendor_id, "vendor", f"New {label.lower()} request",
                f"{account} · {item['name']} · ₹{amount:.0f} — do the recharge and mark it done.",
                extra={"order_id": order_id, "action_url": "/vendor/orders"},
            )
        admin_doc = await db.users.find_one({"email": ADMIN_EMAIL.lower()}, {"_id": 0, "id": 1})
        if admin_doc:
            await _create_notification(
                admin_doc["id"], "order", "New recharge",
                f"{order['order_number']} · {account} · ₹{amount:.0f}",
                extra={"order_id": order_id, "action_url": "/admin/orders"},
            )
    except Exception as e:
        logger.warning(f"recharge notification failed (non-blocking): {str(e)[:160]}")

    return order
