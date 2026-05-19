"""Quick ledger snapshot dump."""
import asyncio, os
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")
db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]

async def main():
    # Sum by transaction type
    types_agg = await db.transactions.aggregate([
        {"$match": {"status": {"$in": ["success", "paid", "approved"]}}},
        {"$group": {"_id": "$type", "total": {"$sum": "$amount"}, "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]).to_list(100)
    print("=== TRANSACTIONS BY TYPE ===")
    for t in types_agg:
        print(f"  {t['_id']:35s}  ₹{float(t['total']):>10.2f}  ({t['count']} rows)")

    # Admin wallet buckets
    admin = await db.users.find_one({"email": "admin@app.com"})
    print(f"\n=== ADMIN WALLET ===")
    print(f"  wallet_balance: ₹{admin.get('wallet_balance'):.2f}")
    for b, v in (admin.get("wallet_buckets") or {}).items():
        if v:
            print(f"  {b:30s}  ₹{float(v):.2f}")

    # All users wallet sum
    agg = await db.users.aggregate([
        {"$match": {"role": "user"}},
        {"$group": {"_id": None, "total": {"$sum": "$wallet_balance"}, "n": {"$sum": 1}}},
    ]).to_list(1)
    print(f"\n=== USER WALLETS ===")
    print(f"  total balance: ₹{float(agg[0]['total']):.2f}  ({agg[0]['n']} users)")

    # Money-flow identity check
    async def s(q): 
        r = await db.transactions.aggregate([{"$match": q}, {"$group": {"_id": None, "t": {"$sum": "$amount"}}}]).to_list(1)
        return float(r[0]["t"]) if r else 0
    reg = await s({"type": "registration_fee", "status": {"$in": ["paid", "success", "approved"]}})
    utr = await s({"type": "system_deposit", "status": {"$in": ["paid", "success", "approved"]}})
    shop = await s({"type": {"$in": ["shopping_margin", "shop_commission"]}, "status": "success"})
    serv = await s({"type": {"$in": ["service_margin", "service_commission"]}, "status": "success"})
    revs = await s({"type": {"$in": ["shop_commission_reversal", "service_commission_reversal"]}, "status": "success"})
    inflow = reg + utr + shop + serv - abs(revs)
    wd = abs(await s({"type": "withdrawal", "status": "success"}))
    held = float(admin.get("wallet_balance") or 0) + float(agg[0]["total"])
    print(f"\n=== IDENTITY CHECK ===")
    print(f"  Inflow:   ₹{inflow:.2f}  (reg ₹{reg:.2f} + utr ₹{utr:.2f} + shop ₹{shop:.2f} + serv ₹{serv:.2f} - rev ₹{abs(revs):.2f})")
    print(f"  Withdraw: ₹{wd:.2f}")
    print(f"  Held:     ₹{held:.2f}")
    print(f"  Drift:    ₹{held - (inflow - wd):.2f}  (Held - (Inflow - Withdraw))")

asyncio.run(main())
