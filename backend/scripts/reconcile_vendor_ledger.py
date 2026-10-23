"""One-time reconciliation — sellers whose stored shop-earnings balance does
not match their ledger, because early fixtures/scripts wrote `vendor_earnings`
directly without a transaction row.

The STORED balance is what the seller can actually withdraw, so it is treated
as the truth and a single explicit adjustment row is posted to explain the
gap. After this the Net worth screen reads "Balanced: YES" and every rupee has
a row behind it.

Run:  python3 scripts/reconcile_vendor_ledger.py [vendor_id]
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import shop_money  # noqa: E402
from core.db import db  # noqa: E402


async def fix(vendor_id: str) -> None:
    view = await shop_money.vendor_wallet_view(vendor_id)
    gap = round(float(view["available_balance"]) - float(view["ledger_balance"]), 2)
    if abs(gap) < 0.01:
        print(f"{vendor_id}: already balanced")
        return
    is_credit = gap > 0
    await shop_money.post(
        group="vendor_payable",
        txn_type="vendor_adjustment_credit" if is_credit else "vendor_adjustment_debit",
        amount=abs(gap),
        credit=abs(gap) if is_credit else 0.0,
        debit=0.0 if is_credit else abs(gap),
        idempotency_key=f"LEDGERFIX:{vendor_id}",
        user_id=vendor_id,
        vendor_id=vendor_id,
        settlement_status="adjusted",
        description=(
            f"Ledger reconciliation — ₹{abs(gap):,.2f} "
            f"{'added to' if is_credit else 'removed from'} the statement so it matches "
            f"the shop earnings balance (balance movements recorded before the ledger)"
        ),
        extra={"wallet_impact": "vendor_earnings_only", "reconciliation": True},
    )
    after = await shop_money.vendor_wallet_view(vendor_id)
    print(f"{vendor_id}: gap {gap} → stored {after['available_balance']} "
          f"ledger {after['ledger_balance']} in_sync {after['in_sync']}")


async def main() -> None:
    if len(sys.argv) > 1:
        await fix(sys.argv[1])
        return
    async for v in db.users.find({"is_vendor": True}, {"_id": 0, "id": 1}):
        await fix(v["id"])


if __name__ == "__main__":
    asyncio.run(main())
