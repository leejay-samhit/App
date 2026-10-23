"""One-time repair — settlements that were REJECTED before the 2.56%
transaction fee was refundable kept the fee: the seller never got it back and
the treasury still counts it as revenue.

For every rejected withdrawal with a fee and no `WDL_FEEBACK` row:
  1. credit the fee back to the wallet it was taken from (keyed, replay-safe)
  2. post the keyed `reversal` row so the Revenue Ledger drops back
  3. decrement the platform_fee bucket off that reversal row

Run once:  python3 scripts/backfill_rejected_fee_refunds.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import shop_money  # noqa: E402
from core.db import db  # noqa: E402


async def main() -> None:
    fixed = 0
    total = 0.0
    async for w in db.withdrawals.find(
        {"status": "rejected", "transaction_fee": {"$gt": 0.009}}
    ):
        wid = w["id"]
        fee = round(float(w.get("transaction_fee") or 0), 2)
        wallet = w.get("wallet_field") or "wallet_balance"
        back = await shop_money.credit(
            w["user_id"], wallet, fee,
            idempotency_key=f"WDL_FEEBACK:{wid}",
            group="revenue_ledger",
            txn_type="withdrawal_transaction_fee_refund",
            vendor_id=w["user_id"],
            source_wallet="system_treasury",
            settlement_status="rejected",
            description=f"Transaction fee ₹{fee:,.2f} returned — settlement rejected",
            extra={"withdrawal_id": wid, "reverses_fee": True, "backfilled": True,
                   **({"wallet_impact": "vendor_earnings_only"}
                      if wallet == shop_money.VENDOR_WALLET else {})},
        )
        rev = await shop_money.post(
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
        if rev is not None:
            from server import credit_admin_bucket
            await credit_admin_bucket("platform_fee_collected", -fee,
                                      also_total_earned=False)
        if back is not None or rev is not None:
            fixed += 1
            total = round(total + fee, 2)
            print(f"{wid}  fee={fee}  refunded={back is not None}  reversed={rev is not None}")
    print(f"\nrepaired {fixed} settlement(s), {total} returned")


if __name__ == "__main__":
    asyncio.run(main())
