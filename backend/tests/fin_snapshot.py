# Financial reconciliation snapshot (wallet totals, txn counts) — Nov 2026 OTP/free-reveal iteration
import os, asyncio, json, sys
from dotenv import load_dotenv
load_dotenv('/app/backend/.env')
from motor.motor_asyncio import AsyncIOMotorClient


async def snap():
    db = AsyncIOMotorClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
    out = {}
    agg = await db.users.aggregate([{"$group": {"_id": None, "t": {"$sum": "$wallet_balance"}}}]).to_list(1)
    out["wallets_total"] = round(agg[0]["t"], 2) if agg else 0
    out["transactions"] = await db.transactions.count_documents({})
    c = await db.transactions.aggregate([{"$match": {"status": "success", "amount": {"$gt": 0}}}, {"$group": {"_id": None, "t": {"$sum": "$amount"}}}]).to_list(1)
    d = await db.transactions.aggregate([{"$match": {"status": "success", "amount": {"$lt": 0}}}, {"$group": {"_id": None, "t": {"$sum": "$amount"}}}]).to_list(1)
    out["success_credits"] = round(c[0]["t"], 2) if c else 0
    out["success_debits"] = round(d[0]["t"], 2) if d else 0
    out["phone_reveal_invoices"] = await db.phone_reveal_invoices.count_documents({})
    out["users"] = await db.users.count_documents({})
    out["reveal_txns"] = await db.transactions.count_documents({"type": {"$in": ["phone_reveal_fee", "service_margin", "gst_collected"]}})
    out["reg_txns"] = await db.transactions.count_documents({"type": {"$regex": "registration|membership"}})
    return out

if __name__ == "__main__":
    print(json.dumps(asyncio.run(snap())))
