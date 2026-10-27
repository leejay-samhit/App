"""Jun-2026 owner batch — the return/refund cashback bug.

A ₹5,000 item with 10% cashback cost the customer ₹4,500 of real money, so a
return pays back ₹4,500 from the SELLER's wallet and nothing touches the
treasury. Nobody is a rupee up or down afterwards.

Run:  python3 tests/test_jun2026_refund_math.py
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.db import db  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, extra=""):
    (PASS if ok else FAIL).append(name)
    print(f"{'PASS' if ok else 'FAIL'} · {name}" + (f" — {extra}" if extra else ""))


VID = "1115f762-0a4f-474e-bbdb-6227a06f08b1"
BUYER = "627cdc0d-c7f9-4d0b-8b9c-5b1d0d9cfd7f"   # testbuyer@test.com


async def _bal(uid, field):
    u = await db.users.find_one({"id": uid}, {"_id": 0, field: 1}) or {}
    return round(float(u.get(field) or 0), 2)


async def main() -> None:
    ts = datetime.now(timezone.utc).isoformat()
    buyer = await db.users.find_one({"email": "testbuyer@test.com"}, {"_id": 0, "id": 1})
    buyer_id = buyer["id"]

    order_id = f"TESTRET-{uuid.uuid4().hex[:8]}"
    item = {
        "product_id": f"TESTP-{uuid.uuid4().hex[:6]}",
        "name": "Refund math test item",
        "price": 5000.0, "qty": 1, "line_total": 5000.0,
        "vendor_id": VID, "vendor_name": "Test Shop",
        "cashback_pct": 10.0, "cashback_amount": 500.0,
    }
    await db.orders.insert_one({
        "id": order_id, "order_number": f"TR{uuid.uuid4().hex[:5].upper()}",
        "user_id": buyer_id, "vendor_id": VID, "vendor_name": "Test Shop",
        "items": [item], "total": 5000.0, "subtotal": 5000.0,
        "delivery_charge": 0.0, "status": "delivered", "paid_via": "wallet",
        "payment_status": "paid", "cashback_status": "paid",
        "created_at": ts, "delivered_at": ts,
    })
    # The cashback was credited to the customer and fronted by the platform,
    # then recovered from the seller — exactly what happens on delivery.
    await db.cashback_ledger.insert_one({
        "_id": f"CB:{order_id}", "order_id": order_id, "order_number": "TR-TEST",
        "user_id": buyer_id, "vendor_id": VID, "amount": 500.0,
        "status": "paid", "funded_by": "platform", "reversed_total": 0.0,
        "created_at": ts,
    })
    await db.transactions.insert_one({
        "id": str(uuid.uuid4()), "user_id": buyer_id, "order_id": order_id,
        "type": "cashback_credit", "amount": 500.0, "status": "success",
        "description": "test cashback", "created_at": ts,
    })

    ret_id = str(uuid.uuid4())
    await db.returns.insert_one({
        "id": ret_id, "return_number": f"RT{uuid.uuid4().hex[:5].upper()}",
        "order_id": order_id, "order_number": "TR-TEST",
        "user_id": buyer_id, "vendor_id": VID, "vendor_name": "Test Shop",
        "status": "returned", "refund_status": "pending",
        "refund_amount": 5000.0, "delivery_refund": 0.0,
        "cashback_reversal_expected": 500.0,
        "items": [{**item, "refund_amount": 5000.0, "cashback_reversal": 500.0}],
        "created_at": ts,
    })

    # Make sure the seller can cover it — through the LEDGER, never by writing
    # the balance directly, or the statement stops tying out.
    from core import shop_money
    need = round(5000.0 - await _bal(VID, "vendor_earnings"), 2)
    if need > 0:
        await shop_money.credit(
            VID, shop_money.VENDOR_WALLET, need,
            idempotency_key=f"REFUNDTEST-FUND:{order_id}",
            group="vendor_payable", txn_type="vendor_adjustment_credit",
            vendor_id=VID, settlement_status="adjusted",
            description=f"Automated test funding — ₹{need:g} so the refund test can run",
            extra={"wallet_impact": "vendor_earnings_only", "test_fixture": True},
        )

    cust_before = await _bal(buyer_id, "wallet_balance")
    vend_before = await _bal(VID, "vendor_earnings")
    admin = await db.users.find_one({"email": "support@slangcart.com"},
                                    {"_id": 0, "id": 1, "wallet_buckets": 1})
    adm_before = {k: round(float(v or 0), 2)
                  for k, v in (admin.get("wallet_buckets") or {}).items()}

    from core.returns import process_refund
    from server import credit_admin_bucket, _create_notification

    ret = await db.returns.find_one({"id": ret_id}, {"_id": 0})
    out = await process_refund(
        ret, credit_admin_bucket=credit_admin_bucket, notify=_create_notification,
        actor={"id": "test", "email": "test"},
    )

    cust_after = await _bal(buyer_id, "wallet_balance")
    vend_after = await _bal(VID, "vendor_earnings")
    admin2 = await db.users.find_one({"email": "support@slangcart.com"},
                                     {"_id": 0, "wallet_buckets": 1})
    adm_after = {k: round(float(v or 0), 2)
                 for k, v in (admin2.get("wallet_buckets") or {}).items()}

    check("the refund paid is ₹4,500, not ₹5,000",
          abs(round(float(out.get("refund_amount") or 0), 2) - 4500.0) < 0.02, str(out.get("refund_amount")))
    check("the customer is credited ₹4,500",
          abs((cust_after - cust_before) - 4500.0) < 0.02, f"{cust_before} → {cust_after}")
    check("the customer KEEPS the ₹500 cashback (no wallet claw-back)",
          await db.transactions.count_documents(
              {"order_id": order_id, "type": "cashback_reversal"}) == 0)
    check("the seller pays exactly ₹4,500",
          abs((vend_before - vend_after) - 4500.0) < 0.02, f"{vend_before} → {vend_after}")
    moved = {k: round(adm_after.get(k, 0) - v, 2)
             for k, v in adm_before.items() if abs(adm_after.get(k, 0) - v) > 0.009}
    moved.update({k: round(v, 2) for k, v in adm_after.items()
                  if k not in adm_before and abs(v) > 0.009})
    check("NOTHING moved in the treasury", not moved, str(moved))
    check("the netting is on the statement",
          await db.transactions.count_documents(
              {"order_id": order_id, "type": "cashback_netted_off_refund"}) == 1)
    o = await db.orders.find_one({"id": order_id}, {"_id": 0, "cashback_recoverable": 1})
    check("no leftover 'recoverable' that would be collected again",
          round(float((o or {}).get("cashback_recoverable") or 0), 2) == 0.0, str(o))
    vo = await db.vendor_outstanding.count_documents({"return_id": ret_id, "status": "open"})
    check("no parked row — the seller paid it, there is nothing to reconcile", vo == 0, str(vo))
    r2 = await db.returns.find_one({"id": ret_id}, {"_id": 0, "refund_status": 1, "refund_paid": 1})
    check("the return reads as refunded",
          (r2 or {}).get("refund_status") == "paid"
          and abs(round(float((r2 or {}).get("refund_paid") or 0), 2) - 4500.0) < 0.02, str(r2))

    # replay
    ret2 = await db.returns.find_one({"id": ret_id}, {"_id": 0})
    await process_refund(ret2, credit_admin_bucket=credit_admin_bucket,
                         notify=_create_notification, actor={"id": "test"})
    check("refunding twice pays nothing twice",
          abs(await _bal(buyer_id, "wallet_balance") - cust_after) < 0.02)

    # everyone is square: customer out 5,000 → back 500 + 4,500
    check("every rupee is accounted for",
          abs((cust_after - cust_before) + 500.0 - 5000.0) < 0.02,
          "customer paid 5000, holds 500 cashback + 4500 refund")

    # cleanup
    await db.orders.delete_one({"id": order_id})
    await db.returns.delete_one({"id": ret_id})
    await db.cashback_ledger.delete_one({"_id": f"CB:{order_id}"})
    # Only the row the test seeded itself — the engine's own refund rows stay,
    # otherwise the balances move without their ledger entries.
    await db.transactions.delete_many({"order_id": order_id, "type": "cashback_credit"})
    # NOTE: the refund itself is left in place on purpose. Undoing real
    # wallet movements with extra rows is what used to leave the seller's
    # statement out of step with his balance; the test only removes the
    # documents it created.
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", ", ".join(FAIL))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
