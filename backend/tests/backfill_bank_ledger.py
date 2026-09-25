"""One-time, idempotent bank-ledger backfill (Sep-2026).

Before this, only wallet top-ups wrote a `bank_ledger` row, so the System
Wallet's Bank Balance could never be tallied against a real bank statement.
This walks every historical money event that touched the company bank
account and writes the missing row — keyed by `ref_key`, so running it
twice changes nothing.

Covered:
  * wallet top-ups            (existing rows get their `ref_key` stamped)
  * shop orders paid online   → credit  (liability: owed to the vendor)
  * registration fees (gateway) → credit (revenue)
  * settled withdrawals       → debit

Run:  cd /app/backend && python3 -m tests.backfill_bank_ledger
"""
import asyncio
import sys

from core import bank
from core.db import client, db


async def main() -> None:
    await bank.ensure_indexes()
    stats = {"topup_keyed": 0, "order_credits": 0, "reg_credits": 0, "withdrawal_debits": 0}

    # 1. Stamp ref_key on the legacy top-up rows so they are never duplicated.
    async for row in db.bank_ledger.find({"ref_key": {"$exists": False}}, {"_id": 1, "topup_id": 1, "id": 1}):
        key = f"TOPUP:{row['topup_id']}" if row.get("topup_id") else f"LEGACY:{row.get('id')}"
        await db.bank_ledger.update_one({"_id": row["_id"]}, {"$set": {"ref_key": key}})
        stats["topup_keyed"] += 1

    # 2. Shop orders paid online — money arrived in our bank.
    async for a in db.order_payments.find(
        {"status": "paid", "online_amount": {"$gt": 0}}, {"_id": 0},
    ):
        u = await db.users.find_one({"id": a.get("user_id")}, {"_id": 0, "name": 1, "email": 1})
        row = await bank.post_bank(
            kind="credit",
            amount=float(a.get("online_amount") or 0),
            category="shop_order_online",
            description=f"Shop order paid online · {(u or {}).get('name') or (u or {}).get('email') or a.get('user_id')}",
            ref_key=f"ORDERPAY:{a['id']}",
            utr=a.get("razorpay_payment_id"),
            user_id=a.get("user_id"),
            happened_at=a.get("paid_at") or a.get("created_at"),
            extra={"order_group_id": a.get("consumed_order_group"),
                   "backfilled": True,
                   "razorpay_payment_id": a.get("razorpay_payment_id"),
                   "razorpay_order_id": a.get("razorpay_order_id")},
        )
        if row:
            stats["order_credits"] += 1

    # 3. Registration fees collected through the gateway.
    async for t in db.transactions.find(
        {"type": "registration_fee", "status": {"$in": ["paid", "success", "approved"]}},
        {"_id": 0},
    ):
        u = await db.users.find_one(
            {"id": t.get("user_id")}, {"_id": 0, "name": 1, "email": 1, "registration_source": 1},
        ) or {}
        if (u.get("registration_source") or "razorpay") != "razorpay":
            continue          # offline / UPI-manual cash never hit the bank
        key = f"REGFEE:{t.get('razorpay_order_id') or t.get('id')}"
        row = await bank.post_bank(
            kind="credit",
            amount=float(t.get("amount") or 0),
            category="registration_fee",
            description=f"Registration fee · {u.get('name') or u.get('email') or t.get('user_id')}",
            ref_key=key,
            utr=t.get("reference_number") or t.get("razorpay_payment_id"),
            user_id=t.get("user_id"),
            happened_at=t.get("paid_at") or t.get("created_at"),
            extra={"backfilled": True},
        )
        if row:
            stats["reg_credits"] += 1

    # 4. Settled withdrawals — money left our bank.
    async for w in db.withdrawals.find(
        {"status": {"$in": ["success", "approved", "paid", "completed"]}}, {"_id": 0},
    ):
        row = await bank.post_bank(
            kind="debit",
            amount=float(w.get("amount") or 0),
            category="withdrawal_payout",
            description=f"Payout to {w.get('user_name') or w.get('user_email') or w.get('user_id')}",
            ref_key=f"WDLPAY:{w['id']}",
            utr=w.get("reference_number"),
            user_id=w.get("user_id"),
            payment_method="bank_transfer",
            happened_at=w.get("completed_at") or w.get("processed_at") or w.get("created_at"),
            extra={"backfilled": True},
        )
        if row:
            stats["withdrawal_debits"] += 1

    tot = await bank.totals()
    print("backfill:", stats)
    print("bank ledger now:", tot)
    print("by category:", await bank.by_category())
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
    sys.exit(0)
