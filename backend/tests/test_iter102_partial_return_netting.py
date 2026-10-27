"""Iter102 — FIX 3b: partial returns of a multi-line order net off only the
returned line's cashback, and several partial returns cannot over-net.

Run:  python3 tests/test_iter102_partial_return_netting.py
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.db import db  # noqa: E402

PASS, FAIL = [], []
VID = "1115f762-0a4f-474e-bbdb-6227a06f08b1"


def check(name, ok, extra=""):
    (PASS if ok else FAIL).append(name)
    print(f"{'PASS' if ok else 'FAIL'} · {name}" + (f" — {extra}" if extra else ""))


async def _bal(uid, field):
    u = await db.users.find_one({"id": uid}, {"_id": 0, field: 1}) or {}
    return round(float(u.get(field) or 0), 2)


async def main():
    from core import shop_money
    from core.returns import process_refund
    from server import credit_admin_bucket, _create_notification

    ts = datetime.now(timezone.utc).isoformat()
    buyer_id = (await db.users.find_one({"email": "testbuyer@test.com"}, {"_id": 0, "id": 1}))["id"]
    oid = f"TESTPRT-{uuid.uuid4().hex[:8]}"
    a = {"product_id": "TESTA", "name": "Line A", "price": 3000.0, "qty": 1, "line_total": 3000.0,
         "vendor_id": VID, "cashback_pct": 10.0, "cashback_amount": 300.0}
    b = {"product_id": "TESTB", "name": "Line B", "price": 2000.0, "qty": 1, "line_total": 2000.0,
         "vendor_id": VID, "cashback_pct": 10.0, "cashback_amount": 200.0}
    await db.orders.insert_one({
        "id": oid, "order_number": "TPRT", "user_id": buyer_id, "vendor_id": VID,
        "items": [a, b], "total": 5000.0, "subtotal": 5000.0, "delivery_charge": 0.0,
        "status": "delivered", "paid_via": "wallet", "payment_status": "paid",
        "cashback_status": "paid", "created_at": ts,
    })
    # Ledger holds only ₹400 actually credited (e.g. capped) — so expected 300+200 must not over-net.
    await db.cashback_ledger.insert_one({
        "_id": f"CB:{oid}", "order_id": oid, "order_number": "TPRT", "user_id": buyer_id,
        "vendor_id": VID, "amount": 400.0, "status": "paid", "funded_by": "platform",
        "reversed_total": 0.0, "created_at": ts,
    })
    need = round(4700.0 - await _bal(VID, "vendor_earnings"), 2)
    if need > 0:
        await shop_money.credit(
            VID, shop_money.VENDOR_WALLET, need, idempotency_key=f"PRTTEST-FUND:{oid}",
            group="vendor_payable", txn_type="vendor_adjustment_credit", vendor_id=VID,
            settlement_status="adjusted", description=f"Automated test funding ₹{need:g} (partial return test)",
            extra={"wallet_impact": "vendor_earnings_only", "test_fixture": True},
        )

    adm0 = (await db.users.find_one({"email": "support@slangcart.com"}, {"_id": 0, "wallet_buckets": 1})).get("wallet_buckets") or {}
    rets = []
    for line, cb in ((a, 300.0), (b, 200.0), (b, 200.0)):
        rid = str(uuid.uuid4())
        await db.returns.insert_one({
            "id": rid, "return_number": f"RT{uuid.uuid4().hex[:5]}", "order_id": oid,
            "order_number": "TPRT", "user_id": buyer_id, "vendor_id": VID, "status": "returned",
            "refund_status": "pending", "refund_amount": line["price"], "delivery_refund": 0.0,
            "cashback_reversal_expected": cb,
            "items": [{**line, "refund_amount": line["price"], "cashback_reversal": cb}], "created_at": ts,
        })
        rets.append(rid)

    expected = [(2700.0, 300.0, "partially_reversed"), (1900.0, 100.0, "reversed"), (2000.0, 0.0, "reversed")]
    for i, rid in enumerate(rets):
        c0, v0 = await _bal(buyer_id, "wallet_balance"), await _bal(VID, "vendor_earnings")
        out = await process_refund(await db.returns.find_one({"id": rid}, {"_id": 0}),
                                   credit_admin_bucket=credit_admin_bucket, notify=_create_notification,
                                   actor={"id": "test"})
        c1, v1 = await _bal(buyer_id, "wallet_balance"), await _bal(VID, "vendor_earnings")
        pay, net, st = expected[i]
        led = await db.cashback_ledger.find_one({"_id": f"CB:{oid}"})
        check(f"return {i+1}: refund {pay}", abs(float(out.get("refund_amount") or 0) - pay) < 0.02, str(out.get("refund_amount")))
        check(f"return {i+1}: customer +{pay}", abs((c1 - c0) - pay) < 0.02, f"{c0}->{c1}")
        check(f"return {i+1}: seller -{pay}", abs((v0 - v1) - pay) < 0.02, f"{v0}->{v1}")
        r = await db.returns.find_one({"id": rid}, {"_id": 0, "cashback_netted_off_refund": 1})
        check(f"return {i+1}: netted {net}", abs(float(r.get("cashback_netted_off_refund") or 0) - net) < 0.02, str(r))
        check(f"return {i+1}: ledger status {st}", led.get("status") == st, f"{led.get('status')} rt={led.get('reversed_total')}")
    led = await db.cashback_ledger.find_one({"_id": f"CB:{oid}"})
    check("never over-nets (reversed_total <= amount)", float(led["reversed_total"]) <= 400.0 + 0.01, str(led["reversed_total"]))
    check("no wallet claw-back rows", await db.transactions.count_documents({"order_id": oid, "type": "cashback_reversal"}) == 0)
    check("memo rows = 2 (third nets nothing)",
          await db.transactions.count_documents({"order_id": oid, "type": "cashback_netted_off_refund"}) == 2)
    check("no open vendor_outstanding", await db.vendor_outstanding.count_documents({"order_id": oid, "status": "open"}) == 0)
    o = await db.orders.find_one({"id": oid}, {"_id": 0, "cashback_recoverable": 1})
    check("no cashback_recoverable", float((o or {}).get("cashback_recoverable") or 0) == 0)
    adm1 = (await db.users.find_one({"email": "support@slangcart.com"}, {"_id": 0, "wallet_buckets": 1})).get("wallet_buckets") or {}
    moved = {k: round(float(adm1.get(k) or 0) - float(adm0.get(k) or 0), 2) for k in set(adm0) | set(adm1)
             if abs(float(adm1.get(k) or 0) - float(adm0.get(k) or 0)) > 0.009}
    check("treasury untouched", not moved, str(moved))

    await db.orders.delete_one({"id": oid})
    await db.returns.delete_many({"id": {"$in": rets}})
    await db.cashback_ledger.delete_one({"_id": f"CB:{oid}"})
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", ", ".join(FAIL))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
