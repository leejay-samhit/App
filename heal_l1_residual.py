"""Backfill missing fee_residual rows for L1-cycle signups.

For each user that triggered an L1 cycle (level=1 referral_payout with
related_signup_id set), the OLD code skipped writing a fee_residual entry
because it included L1 in the cascade-gross sum. The fee_residual should
have been ₹95.95 (= ₹118 - cascade_L2..L10 sum ≈ ₹22.05).

This script:
  1. Finds every with-ref signup that has NO fee_residual txn.
  2. Computes the correct residual = registration_fee - cascade(L2..L10 + overflow) gross.
  3. Credits admin.fee_residual bucket and writes the missing fee_residual txn.
  4. Skips if user.no_referral_signup == True (no-ref users don't get residuals).

Idempotent via users.fee_residual_backfilled flag.
"""
import asyncio
import os
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")
db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@app.com").lower()


async def main():
    settings = await db.settings.find_one({}) or {}
    fee = float(settings.get("registration_fee") or 118)

    admin = await db.users.find_one({"email": ADMIN_EMAIL})
    if not admin:
        print("[!] No admin found")
        return

    # Find with-ref approved users that don't have a fee_residual txn
    healed = 0
    healed_total = 0.0
    async for u in db.users.find({
        "no_referral_signup": False,
        "registration_paid": True,
        "approval_status": "approved",
        "commission_triggered": True,
    }, {"id": 1, "name": 1, "created_at": 1, "_id": 0}):
        existing = await db.transactions.find_one({
            "type": "fee_residual",
            "related_signup_id": u["id"],
        })
        if existing:
            continue
        # Compute cascade gross (L2..L10) for this user
        cascade_gross = 0.0
        async for t in db.transactions.find({
            "$or": [
                {"related_signup_id": u["id"]},
                {"description": {"$regex": u["name"][:20]},
                 "type": {"$in": ["referral_payout", "cascade_overflow"]},
                 "status": "success",
                 "created_at": {"$gte": u.get("created_at", "")}},
            ],
        }, {"_id": 0, "type": 1, "amount": 1, "gross_amount": 1, "level": 1}):
            if int(t.get("level") or 0) == 1:
                continue  # skip L1 (funded separately)
            if t.get("type") == "referral_payout":
                cascade_gross += float(t.get("gross_amount") or t.get("amount") or 0)
            elif t.get("type") == "cascade_overflow":
                cascade_gross += float(t.get("amount") or 0)
        residual = round(fee - cascade_gross, 2)
        if residual <= 0.01:
            continue

        # Credit admin and write txn
        await db.users.update_one(
            {"id": admin["id"]},
            {"$inc": {
                "wallet_buckets.fee_residual": residual,
                "wallet_balance": residual,
                "total_earned": residual,
            }},
        )
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": admin["id"],
            "type": "fee_residual",
            "amount": residual,
            "status": "success",
            "description": f"[Backfill] Fee residual ₹{residual} from {u['name']}'s signup (L1-cycle gap fix)",
            "related_signup_id": u["id"],
            "source_user_name": u["name"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "is_l1_cycle_backfill": True,
        })
        healed += 1
        healed_total += residual

    print(f"[ok] Healed {healed} L1-cycle signups, total residual injected: ₹{healed_total:.2f}")


asyncio.run(main())
