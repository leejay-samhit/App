# Iteration 98 — investigate rejected withdrawals whose fee has no reversal row
import asyncio, os, sys
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from motor.motor_asyncio import AsyncIOMotorClient
db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

async def main():
    rev_ids = {t.get("withdrawal_id") async for t in db.transactions.find({"type": "reversal", "original_type": "platform_fee_collected"}, {"withdrawal_id": 1})}
    tot_unrev_fee = 0
    async for w in db.withdrawals.find({"status": "rejected", "transaction_fee": {"$gt": 0}}, {"_id": 0}):
        if w["id"] in rev_ids:
            continue
        fee_rows = await db.transactions.find({"withdrawal_id": w["id"]}, {"_id": 0, "type": 1, "amount": 1, "status": 1, "idempotency_key": 1}).to_list(50)
        types = [(r["type"], r.get("amount"), r.get("status")) for r in fee_rows]
        has_fee = any(r["type"] == "platform_fee_collected" for r in fee_rows)
        if has_fee:
            tot_unrev_fee += w["transaction_fee"]
        print(w["id"][:8], w.get("created_at", "")[:19], "fee", w["transaction_fee"], "user", w["user_id"][:8], "has_fee_row", has_fee)
        for t in types:
            print("     ", t)
    print("fee collected but never reversed on rejected withdrawals:", tot_unrev_fee)
    # platform_fee rows w/o withdrawal_id
    n = await db.transactions.count_documents({"type": "platform_fee_collected", "withdrawal_id": {"$in": [None, ""]}})
    print("platform_fee_collected rows without withdrawal_id:", n)
    s = await db.admin_wallet.find_one({}, {"_id": 0}) if "admin_wallet" in await db.list_collection_names() else None
    print("admin_wallet:", {k: v for k, v in (s or {}).items() if "platform" in k or "group_1" in k})

asyncio.run(main())
