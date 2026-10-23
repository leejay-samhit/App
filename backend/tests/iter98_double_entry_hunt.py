# Iter98 — hunt for double entries across buyer / vendor / admin / rider ledgers
import asyncio, os
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from motor.motor_asyncio import AsyncIOMotorClient
db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

CHECKS = [
    ("return_refund_credit", "return_id"), ("return_refund_debit", "return_id"), ("refund_company_funded", "return_id"),
    ("cashback_credit", "order_id"), ("cashback_recovery", "order_id"), ("vendor_sale", "order_id"),
    ("delivery_charge_paid", "order_id"), ("delivery_charge_collected", "order_id"), ("dp_delivery_commission", "order_id"),
    ("recharge", "order_id"), ("withdrawal_hold", "withdrawal_id"), ("withdrawal_refund", "withdrawal_id"),
    ("withdrawal_transaction_fee", "withdrawal_id"), ("platform_fee_collected", "withdrawal_id"),
    ("withdrawal_transaction_fee_refund", "withdrawal_id"), ("reversal", "withdrawal_id"), ("order_payment", "order_id"),
]


async def main():
    for t, key in CHECKS:
        agg = await db.transactions.aggregate([
            {"$match": {"type": t, key: {"$nin": [None, ""]}, "status": {"$nin": ["failed", "reversed_void"]}}},
            {"$group": {"_id": {"k": f"${key}", "u": "$user_id"}, "n": {"$sum": 1}, "amt": {"$sum": "$amount"}}},
            {"$match": {"n": {"$gt": 1}}},
        ]).to_list(200)
        total = await db.transactions.count_documents({"type": t})
        recent = [a for a in agg]
        print(f"{t:36s} total={total:5d} dup_groups={len(agg)}", [(str(a['_id']['k'])[:10], a['n'], a['amt']) for a in recent[:4]])


asyncio.run(main())
