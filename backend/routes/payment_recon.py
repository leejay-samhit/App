"""Razorpay webhook + payment reconciliation (Phase 1, Jun-2026).

Two guarantees live here:

1. **Server-side confirmation.** A payment is only ever believed because
   Razorpay told our SERVER (signed webhook) or because our server verified
   the signature itself — never because a client said so.
2. **A captured payment can never vanish.** Every online checkout writes a
   `payment_reconciliations` row the moment the money is claimed. It flips to
   `completed` when the order is created; anything left in `awaiting_order`
   is a real "paid but no order" case, listed here for admin with a safe
   resolve action (refund to wallet / close). The customer is NEVER charged
   again and the amount is never silently applied to a later order.

Idempotency: the webhook is keyed on the Razorpay payment id, so the same
event delivered ten times moves money zero extra times.
"""
import hashlib
import hmac
import logging
import os
import uuid
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from core import shop_money
from core.db import db
from core.razorpay import get_creds
from core.security import require_admin_role
from core.utils import now_utc

logger = logging.getLogger(__name__)
router = APIRouter()


def _webhook_secret() -> str:
    return (os.environ.get("RAZORPAY_WEBHOOK_SECRET") or "").strip()


def _valid_signature(body: bytes, signature: str, secret: str) -> bool:
    if not (signature and secret):
        return False
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature)


@router.post("/payment/webhook")
async def razorpay_webhook(request: Request):
    """Razorpay → us. Verified, idempotent, and it never creates money:
    it only marks the matching attempt as paid so the normal (already
    idempotent) flows can finish."""
    raw = await request.body()
    signature = request.headers.get("x-razorpay-signature") or ""
    secret = _webhook_secret()
    creds = await get_creds()

    if secret:
        if not _valid_signature(raw, signature, secret):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
    elif not creds["is_mock"]:
        # Live keys but no webhook secret configured — refuse rather than
        # trust an unsigned payload.
        raise HTTPException(status_code=401, detail="Webhook secret not configured")

    try:
        event = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Malformed webhook payload")

    entity = (((event.get("payload") or {}).get("payment") or {}).get("entity") or {})
    rzp_payment_id = entity.get("id") or ""
    rzp_order_id = entity.get("order_id") or ""
    amount = round(float(entity.get("amount") or 0) / 100.0, 2)
    kind = (event.get("event") or "").strip()

    if not rzp_payment_id:
        return {"ok": True, "ignored": "no_payment_id"}

    # ── Idempotency: one row per Razorpay payment id ──────────────────────
    try:
        await db.payment_webhook_events.insert_one({
            "_id": f"WH:{rzp_payment_id}:{kind}",
            "event": kind,
            "razorpay_payment_id": rzp_payment_id,
            "razorpay_order_id": rzp_order_id,
            "amount": amount,
            "received_at": now_utc().isoformat(),
        })
    except Exception:
        return {"ok": True, "duplicate": True}

    if kind not in ("payment.captured", "payment.authorized", "order.paid"):
        return {"ok": True, "ignored": kind}

    ts = now_utc().isoformat()
    marked = []
    for coll, label in ((db.order_payments, "order"), (db.wallet_topups, "wallet_topup")):
        res = await coll.update_one(
            {"razorpay_order_id": rzp_order_id, "status": "created"},
            {"$set": {
                "status": "paid",
                "razorpay_payment_id": rzp_payment_id,
                "paid_at": ts,
                "paid_via_webhook": True,
            }},
        )
        if res.modified_count:
            marked.append(label)
    return {"ok": True, "event": kind, "marked": marked}


# ── Admin reconciliation desk ──────────────────────────────────────────

@router.get("/admin/finance/reconciliations")
async def list_reconciliations(
    status: str = "open",
    _: Dict[str, Any] = Depends(require_admin_role("super_admin", "finance")),
):
    """Every captured payment that has no order behind it (plus resolved
    history when `status=all`)."""
    q: Dict[str, Any] = {}
    if status == "open":
        q["status"] = {"$in": ["awaiting_order", "open"]}
    elif status != "all":
        q["status"] = status
    rows = await db.payment_reconciliations.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)

    # Belt-and-braces: a paid-but-unconsumed attempt with no row at all.
    orphans = await db.order_payments.find(
        {"status": "paid", "consumed_order_group": None}, {"_id": 0},
    ).sort("paid_at", -1).to_list(200)
    known = {r.get("payment_id") for r in rows}
    for a in orphans:
        if a["id"] in known:
            continue
        rows.append({
            "payment_id": a["id"],
            "razorpay_order_id": a.get("razorpay_order_id"),
            "razorpay_payment_id": a.get("razorpay_payment_id"),
            "user_id": a.get("user_id"),
            "amount": round(float(a.get("online_amount") or 0), 2),
            "intended_total": round(float(a.get("cart_total") or 0), 2),
            "status": "awaiting_order",
            "created_at": a.get("paid_at") or a.get("created_at"),
            "source": "attempt_scan",
        })
    total = round(sum(float(r.get("amount") or 0) for r in rows
                      if r.get("status") in ("awaiting_order", "open")), 2)
    return {"reconciliations": rows, "open_total": total, "count": len(rows)}


class ResolveBody(BaseModel):
    action: str            # "refund_to_wallet" | "close"
    note: str = ""


@router.post("/admin/finance/reconciliations/{payment_id}/resolve")
async def resolve_reconciliation(
    payment_id: str,
    body: ResolveBody,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "finance")),
):
    if body.action not in ("refund_to_wallet", "close"):
        raise HTTPException(status_code=400, detail="action must be refund_to_wallet or close")
    if len((body.note or "").strip()) < 3:
        raise HTTPException(status_code=400, detail="A note is required for every resolution")

    attempt = await db.order_payments.find_one({"id": payment_id}, {"_id": 0})
    row = await db.payment_reconciliations.find_one({"_id": f"PAY:{payment_id}"}, {"_id": 0})
    if not attempt and not row:
        raise HTTPException(status_code=404, detail="Payment not found")
    if attempt and attempt.get("consumed_order_group"):
        raise HTTPException(status_code=400, detail="This payment already produced an order")

    amount = round(float((attempt or row or {}).get("online_amount")
                         or (row or {}).get("amount") or 0), 2)
    user_id = (attempt or row or {}).get("user_id")
    ts = now_utc().isoformat()
    refunded = 0.0

    if body.action == "refund_to_wallet":
        if not user_id or amount <= 0.009:
            raise HTTPException(status_code=400, detail="Nothing to refund on this payment")
        credited = await shop_money.credit(
            user_id, shop_money.CUSTOMER_WALLET, amount,
            idempotency_key=f"RECON:{payment_id}",
            group="customer_liability",
            txn_type="payment_reconciliation_refund",
            payment_id=payment_id,
            payment_method="online",
            settlement_status="refunded",
            description=(
                f"Payment ₹{amount:.0f} refunded to wallet — order could not be "
                f"created ({body.note.strip()})"
            ),
        )
        refunded = amount if credited else 0.0

    await db.payment_reconciliations.update_one(
        {"_id": f"PAY:{payment_id}"},
        {"$set": {
            "status": "refunded" if body.action == "refund_to_wallet" else "closed",
            "resolution": body.action,
            "resolution_note": body.note.strip(),
            "resolved_by": admin.get("email"),
            "resolved_at": ts,
            "refunded_amount": refunded,
        },
         "$setOnInsert": {
            "payment_id": payment_id,
            "user_id": user_id,
            "amount": amount,
            "created_at": ts,
        }},
        upsert=True,
    )
    if attempt:
        await db.order_payments.update_one(
            {"id": payment_id},
            {"$set": {"status": "reconciled", "reconciled_at": ts}},
        )
    await db.audit_logs.insert_one({
        "id": str(uuid.uuid4()),
        "admin_id": admin.get("id"),
        "admin_email": admin.get("email"),
        "action": f"reconciliation.{body.action}",
        "target_type": "payment",
        "target_id": payment_id,
        "meta": {"amount": amount, "refunded": refunded, "note": body.note.strip()},
        "created_at": ts,
    })
    return {"ok": True, "refunded": refunded, "status": body.action}


@router.get("/admin/finance/errors")
async def list_financial_errors(
    _: Dict[str, Any] = Depends(require_admin_role("super_admin", "finance")),
):
    """Money movements that were REFUSED (e.g. a delivery fee a vendor
    wallet could not cover). Nothing was deducted — these need a human."""
    rows = await db.financial_errors.find({}, {"_id": 0}).sort("created_at", -1).to_list(300)
    return {"errors": rows, "open": len([r for r in rows if r.get("status") == "open"])}
