"""Seed preview DB with registration-fee revenue rows across all 3 sources.

Used to verify the June-2026 Registration-fee revenue screen + GST maths.
Idempotent: re-running replaces the seeded users/transactions (tagged
`_seed_reg_revenue: True`).

Run:  cd /app/backend && python tests/seed_reg_revenue.py
"""
import asyncio
import os
import sys
import uuid
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

FEE = 118.0
PLAN = [
    ("razorpay", 3),
    ("upi_manual", 2),
    ("offline_cash", 2),
]


async def main():
    from core.utils import now_utc
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ.get("DB_NAME", "test_database")]

    await db.users.delete_many({"_seed_reg_revenue": True})
    await db.transactions.delete_many({"_seed_reg_revenue": True})

    now = now_utc()
    n = 0
    for source, count in PLAN:
        for i in range(count):
            n += 1
            uid = str(uuid.uuid4())
            ts = (now - timedelta(hours=n)).isoformat()
            await db.users.insert_one({
                "id": uid,
                "name": f"Seed {source} {i + 1}",
                "email": f"seed.{source}.{i + 1}@example.com",
                "phone": f"90000000{n:02d}",
                "role": "user",
                "referral_code": f"SEED{n:03d}",
                "referred_by": None,
                "registration_paid": True,
                "registration_source": source,
                "payment_method": source,
                "paid_at": ts,
                "wallet_balance": 0.0,
                "total_earned": 0.0,
                "direct_referrals_count": 0,
                "approval_status": "approved",
                "created_at": ts,
                "_seed_reg_revenue": True,
            })
            txn = {
                "id": str(uuid.uuid4()),
                "user_id": uid,
                "type": "registration_fee",
                "amount": FEE,
                "status": "paid",
                "source": source,
                "description": f"Registration fee via {source}",
                "created_at": ts,
                "paid_at": ts,
                "_seed_reg_revenue": True,
            }
            if source == "razorpay":
                txn["razorpay_payment_id"] = f"pay_SEED{n:06d}"
                txn["razorpay_order_id"] = f"order_SEED{n:06d}"
            else:
                txn["reference_number"] = f"UTRSEED{n:06d}"
            await db.transactions.insert_one(txn)

    # Filler rows so the paginated feed is NOT dominated by registration fees
    # (this is what caused the "only 1 user shows" bug).
    for i in range(30):
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": None,
            "type": "referral_payout",
            "amount": 10.0,
            "status": "success",
            "description": f"Filler payout {i}",
            "created_at": now.isoformat(),
            "_seed_reg_revenue": True,
        })

    print("seeded users:", await db.users.count_documents({"_seed_reg_revenue": True}))
    print("seeded reg fee txns:", await db.transactions.count_documents({"_seed_reg_revenue": True, "type": "registration_fee"}))


asyncio.run(main())
