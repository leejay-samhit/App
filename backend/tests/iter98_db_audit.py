# Iteration 98 — read-only DB audit of FIX B (stale parked refunds) and FIX C (fee reversals)
import asyncio
import os
import sys
from collections import Counter

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv  # noqa: E402

load_dotenv("/app/backend/.env")
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


async def main():
    cols = await db.list_collection_names()
    print("has order_returns:", "order_returns" in cols, "| has returns:", "returns" in cols)
    print("\n== FIX B: rows closed by stale cleanup ==")
    async for r in db.vendor_outstanding.find({"closed_reason": "stale_parked_refund_cleanup"}, {"_id": 0}):
        ret = await db.returns.find_one({"id": r.get("return_id")}, {"_id": 0, "status": 1, "refund_status": 1, "refund_paid": 1})
        print(f"  {r['id'][:8]} amt={r.get('amount')} ret={str(r.get('return_id'))[:8]} -> returns: {ret}")
    print("\n== open vendor_outstanding by kind ==")
    async for g in db.vendor_outstanding.aggregate([{"$match": {"status": "open"}}, {"$group": {"_id": "$kind", "n": {"$sum": 1}, "amt": {"$sum": {"$subtract": ["$amount", {"$ifNull": ["$recovered", 0]}]}}}}]):
        print("  ", g)
    async for r in db.vendor_outstanding.find({"status": "open", "kind": "return_refund"}, {"_id": 0}):
        ret = await db.returns.find_one({"id": r.get("return_id")}, {"_id": 0, "status": 1, "refund_status": 1})
        print(f"  OPEN return_refund {r['id'][:8]} amt={r.get('amount')} -> {ret}")
    print("\n== returns pending refund (refund_status != paid, status approved/refund_pending) ==")
    n = 0
    async for ret in db.returns.find({"status": {"$nin": ["refunded", "rejected", "cancelled", "closed"]}, "refund_status": {"$ne": "paid"}}, {"_id": 0, "id": 1, "status": 1, "refund_status": 1, "vendor_id": 1}):
        open_row = await db.vendor_outstanding.find_one({"return_id": ret["id"], "status": "open"})
        n += 1
        if n <= 15:
            print(f"  {ret['id'][:8]} status={ret.get('status')} refund={ret.get('refund_status')} open_row={bool(open_row)}")
    print("  total:", n)
    cb = await db.users.aggregate([{"$match": {"cashback_outstanding": {"$gt": 0}}}, {"$group": {"_id": None, "s": {"$sum": "$cashback_outstanding"}, "n": {"$sum": 1}}}]).to_list(1)
    print("cashback_outstanding total:", cb)

    print("\n== FIX C: reversal rows on platform_fee_collected ==")
    neg = await db.transactions.count_documents({"type": "reversal", "amount": {"$lt": 0}})
    print("  negative reversal amounts remaining:", neg)
    rows = await db.transactions.find({"type": "reversal", "original_type": "platform_fee_collected", "status": "success"}, {"_id": 0, "amount": 1, "withdrawal_id": 1, "idempotency_key": 1}).to_list(1000)
    print("  fee reversal rows:", len(rows), "sum:", round(sum(abs(r.get("amount") or 0) for r in rows), 2))
    dup = Counter(r.get("withdrawal_id") for r in rows if r.get("withdrawal_id"))
    print("  withdrawals with >1 fee reversal:", {k: v for k, v in dup.items() if v > 1})
    rej = await db.withdrawals.find({"status": "rejected", "transaction_fee": {"$gt": 0}}, {"_id": 0, "id": 1, "transaction_fee": 1}).to_list(1000)
    missing = [w["id"] for w in rej if w["id"] not in dup]
    print(f"  rejected withdrawals with fee: {len(rej)} | missing reversal: {missing[:10]}")
    feeback = Counter()
    async for t in db.transactions.find({"type": "withdrawal_transaction_fee_refund"}, {"_id": 0, "withdrawal_id": 1}):
        feeback[t.get("withdrawal_id")] += 1
    print("  dup fee refunds:", {k: v for k, v in feeback.items() if v > 1})
    w = await db.withdrawals.find_one({"id": "276686a3-88cd-429c-8449-62fadbebcef2"}, {"_id": 0, "status": 1, "transaction_fee": 1})
    rv = await db.transactions.find({"type": "reversal", "withdrawal_id": "276686a3-88cd-429c-8449-62fadbebcef2"}, {"_id": 0, "amount": 1, "original_type": 1}).to_list(10)
    print("  276686a3:", w, "reversals:", rv)
    fees = await db.transactions.aggregate([{"$match": {"type": "platform_fee_collected", "status": {"$in": ["success", "paid", "completed"]}}}, {"$group": {"_id": None, "s": {"$sum": "$amount"}, "n": {"$sum": 1}}}]).to_list(1)
    print("  platform_fee_collected rows:", fees)
    print("\n== testvendor state ==")
    v = await db.users.find_one({"email": "testvendor@test.com"}, {"_id": 0, "id": 1, "cashback_outstanding": 1, "settlement_lock": 1, "settlement_lock_at": 1, "vendor_earnings_balance": 1})
    print("  ", v)
    print("  open withdrawals:", await db.withdrawals.count_documents({"user_id": v["id"], "status": {"$in": ["pending", "processing"]}}))
    print("  open outstanding:", await db.vendor_outstanding.count_documents({"vendor_id": v["id"], "status": "open"}))
    print("\n== duplicate idempotency keys in transactions ==")
    d = await db.transactions.aggregate([{"$match": {"idempotency_key": {"$nin": [None, ""]}}}, {"$group": {"_id": "$idempotency_key", "n": {"$sum": 1}}}, {"$match": {"n": {"$gt": 1}}}, {"$limit": 10}]).to_list(10)
    print("  ", d)


asyncio.run(main())
