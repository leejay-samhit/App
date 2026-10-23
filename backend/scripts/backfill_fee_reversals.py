"""One-time backfill — rejected settlements that got their 2.56% fee back but
never had the revenue reversed (the reversal used to run only when the fee
credit landed in the same call).

Run once:  python3 scripts/backfill_fee_reversals.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import shop_money  # noqa: E402
from core.db import db  # noqa: E402


async def main() -> None:
    fixed = 0
    async for w in db.withdrawals.find(
        {"status": "rejected", "transaction_fee": {"$gt": 0.009}}
    ):
        wid = w["id"]
        fee = round(float(w.get("transaction_fee") or 0), 2)
        refunded = await db.transactions.find_one(
            {"idempotency_key": f"WDL_FEEBACK:{wid}"}
        )
        if not refunded:
            continue
        row = await shop_money.post(
            group="revenue_ledger",
            txn_type="reversal",
            amount=fee,
            debit=fee,
            idempotency_key=f"WDLFEEREV_REJECT:{wid}",
            vendor_id=w["user_id"],
            source_wallet="system_treasury",
            settlement_status="reversed",
            description=f"Withdrawal transaction fee reversed — settlement {wid[:8]} rejected",
            extra={"withdrawal_id": wid, "original_type": "platform_fee_collected",
                   "backfilled": True},
        )
        if row is not None:
            from server import credit_admin_bucket
            await credit_admin_bucket("platform_fee_collected", -fee,
                                      also_total_earned=False)
            fixed += 1
            print(f"reversed fee {fee} for {wid}")
    print(f"\nbackfilled {fixed} reversal(s)")


if __name__ == "__main__":
    asyncio.run(main())
