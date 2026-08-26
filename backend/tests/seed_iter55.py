"""Seed fixtures for the Iter-55 multi-vendor split checkout test.

Creates a SECOND approved vendor in the same delivery pincode (517644) with
one published product, and tops up the CI buyer's wallet so the Wallet+COD
combo path can be exercised end-to-end.
Idempotent — safe to re-run.
"""
import asyncio
import os
import uuid

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

PIN = "517644"
V2_EMAIL = "testvendor2@test.com"


async def main():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ.get("DB_NAME", "test_database")]

    v1 = await db.users.find_one({"id": "1115f762-0a4f-474e-bbdb-6227a06f08b1"}, {"_id": 0})
    assert v1, "primary CI vendor missing"

    v2 = await db.users.find_one({"email": V2_EMAIL}, {"_id": 0})
    if not v2:
        v2 = dict(v1)
        v2.update({
            "id": str(uuid.uuid4()),
            "email": V2_EMAIL,
            "name": "Test Vendor Two",
            "vendor_business_name": "Vendor Two Store",
            "shop_name": "Vendor Two Store",
            "referral_code": f"V2{uuid.uuid4().hex[:6].upper()}",
        })
        v2.pop("_id", None)
        await db.users.insert_one(v2)
        print("created vendor2", v2["id"])
    else:
        print("vendor2 exists", v2["id"])

    for vid, nm, price in ((v1["id"], "Vendor One Widget", 100.0), (v2["id"], "Vendor Two Gadget", 250.0)):
        existing = await db.products.find_one({"vendor_id": vid, "name": nm}, {"_id": 0, "id": 1})
        if existing:
            await db.products.update_one({"id": existing["id"]}, {"$set": {"stock": 50, "is_published": True}})
            print("product ok", nm, existing["id"])
            continue
        base = await db.products.find_one({"vendor_id": v1["id"]}, {"_id": 0})
        doc = dict(base or {})
        doc.update({
            "id": str(uuid.uuid4()),
            "name": nm,
            "vendor_id": vid,
            "price": price,
            "stock": 50,
            "is_published": True,
            "delivery_available": True,
            "store_pincode": PIN,
        })
        doc.pop("_id", None)
        await db.products.insert_one(doc)
        print("created product", nm, doc["id"])

    res = await db.users.update_one(
        {"email": "testbuyer@test.com"},
        {"$set": {"wallet_balance": 5000.0, "pincode": PIN, "wallet_frozen": False}},
    )
    print("buyer topped up:", res.modified_count)


asyncio.run(main())
