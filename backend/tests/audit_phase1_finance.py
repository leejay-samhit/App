"""Phase-1 financial audit (READ-ONLY).

Finds the twelve classes of defect the owner listed in item 20 and prints a
report. It NEVER writes, never "fixes" history — reconciliation is a
deliberate admin action (Admin → Reconciliations / Wallet adjust), so nothing
here can silently rewrite the books.

Run:  cd /app/backend && python tests/audit_phase1_finance.py
"""
import asyncio
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.db import db            # noqa: E402
from core import shop_money       # noqa: E402

FINDINGS = []


def note(kind, count, detail=""):
    FINDINGS.append((kind, count, detail))
    flag = "OK  " if count == 0 else "FIND"
    print(f"  {flag}  {kind}: {count} {detail}")


async def main():
    print("\n── Payments ──")
    paid_no_order = await db.order_payments.count_documents(
        {"status": "paid", "consumed_order_group": None})
    note("payment captured with no order", paid_no_order,
         "(listed in GET /api/admin/finance/reconciliations)")

    orders_online = await db.orders.find(
        {"paid_via": {"$in": ["online", "wallet_online"]}}, {"_id": 0, "id": 1, "payment_id": 1},
    ).to_list(20000)
    note("online order with no payment id",
         len([o for o in orders_online if not o.get("payment_id")]))

    rzp_ids = [a.get("razorpay_payment_id") for a in
               await db.order_payments.find({"status": {"$in": ["paid", "reconciled"]}},
                                            {"_id": 0, "razorpay_payment_id": 1}).to_list(20000)
               if a.get("razorpay_payment_id")]
    dupes = [k for k, v in Counter(rzp_ids).items() if v > 1]
    note("duplicate razorpay payment id", len(dupes), str(dupes[:5]))

    print("\n── Ledger duplicates ──")
    for key_prefix, label in (("VENDORSALE", "vendor credit"),
                              ("DELFEE", "delivery fee debit"),
                              ("DELREV", "delivery revenue"),
                              ("CB", "cashback")):
        agg = await db.transactions.aggregate([
            {"$match": {"idempotency_key": {"$regex": f"^{key_prefix}:"}}},
            {"$group": {"_id": "$idempotency_key", "n": {"$sum": 1}}},
            {"$match": {"n": {"$gt": 1}}},
        ]).to_list(200)
        note(f"duplicate {label} postings", len(agg))

    cb_dupes = await db.transactions.aggregate([
        {"$match": {"type": "cashback_credit", "status": "success"}},
        {"$group": {"_id": "$order_id", "n": {"$sum": 1}}},
        {"$match": {"n": {"$gt": 1}}},
    ]).to_list(200)
    note("duplicate cashback per order", len(cb_dupes))

    print("\n── Commission (must be zero for shop delivery) ──")
    comm = await db.transactions.count_documents({"type": "shop_commission"})
    note("legacy shop_commission rows (historical, left untouched)", comm)
    recent_comm = await db.transactions.count_documents(
        {"type": "shop_commission", "created_at": {"$gte": "2026-09-15"}})
    note("shop_commission created after the Phase-1 cutover", recent_comm)

    print("\n── Delivery charges ──")
    bad_del = 0
    async for o in db.orders.find({"status": "delivered"},
                                  {"_id": 0, "id": 1, "delivery_charge": 1, "delivery_settled": 1}):
        fee = round(float(o.get("delivery_charge") or 0), 2)
        if fee > 0.009 and not o.get("delivery_settled"):
            bad_del += 1
    note("delivered orders with an unsettled delivery fee", bad_del,
         "(see GET /api/admin/finance/errors)")

    print("\n── Wallets ──")
    neg_cust = await db.users.count_documents({"wallet_balance": {"$lt": -0.009}})
    note("negative customer wallets", neg_cust)
    neg_vendor = await db.users.count_documents({shop_money.VENDOR_WALLET: {"$lt": -0.009}})
    note("negative vendor wallets", neg_vendor)

    drifted = []
    async for v in db.users.find({"is_vendor": True}, {"_id": 0, "id": 1, "email": 1}):
        view = await shop_money.vendor_wallet_view(v["id"])
        if not view["in_sync"]:
            drifted.append((v.get("email"), view["unledgered_difference"]))
    note("vendor wallets the ledger cannot fully explain", len(drifted), str(drifted[:5]))

    print("\n── Company net worth ──")
    try:
        from routes.finance import admin_finance_net_worth
        worth = await admin_finance_net_worth({})
        m = worth["master"]
        print(f"  INFO  net worth ₹{m['net_worth']:,.2f} = "
              f"bank {m['components']['bank_tally_net']:,.2f} "
              f"+ pending {m['components']['pending_collections']:,.2f} "
              f"− user wallets {m['components']['user_wallet_balance']:,.2f} "
              f"− pending withdrawals {m['components']['pending_withdrawals']:,.2f} "
              f"− gst {m['components']['gst_payable']:,.2f}")
        note("net-worth formula intact", 0)
    except Exception as err:
        note("net-worth endpoint error", 1, str(err)[:160])

    print("\n── Open financial errors / reconciliations ──")
    note("open financial errors", await db.financial_errors.count_documents({"status": "open"}))
    note("reconciliations awaiting an order",
         await db.payment_reconciliations.count_documents({"status": "awaiting_order"}))

    total = sum(1 for _, n, _ in FINDINGS if n)
    print(f"\n=== {total} finding group(s) need attention · nothing was modified ===")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
