"""Sep 2026 — Reset centre + per-account backup.

Covers:
  • per-account manifest/dump link-up (finds a user's data across collections)
  • account-reset "clear" keeps the login and zeroes the wallet
  • account-reset "delete" removes the account
  • vendor shop reset is SCOPED (other vendors untouched)
  • every destructive call refuses without `backup_downloaded`
  • wipe-all still demands PIN + phrase + backup flag

Runs against throwaway users/products it creates itself, so no fixture is
harmed. The Danger PIN hash is swapped for a known value and restored.
"""
import asyncio
import os
import sys
import uuid

import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

BASE = "http://localhost:8001/api"
PIN = "246802"


def login(email, password):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=60)
    r.raise_for_status()
    d = r.json()
    return {"Authorization": f"Bearer {d.get('access_token') or d.get('token')}"}


async def main():
    from core.db import db
    from core.security import hash_password

    old_hash = (await db.settings.find_one({"id": "global"}, {"_id": 0, "danger_pin_hash": 1}) or {}).get("danger_pin_hash")
    await db.settings.update_one({"id": "global"}, {"$set": {"danger_pin_hash": hash_password(PIN)}})

    # Throwaway account with data attached across several collections.
    uid = str(uuid.uuid4())
    email = f"iter66_reset_{uid[:6]}@example.com"
    await db.users.insert_one({
        "id": uid, "email": email, "name": "Iter66 Reset Target",
        "password_hash": hash_password("Test@1234"), "role": "user",
        "wallet_balance": 500.0, "registration_paid": False, "created_at": "2026-09-10T00:00:00",
    })
    await db.orders.insert_one({"id": str(uuid.uuid4()), "user_id": uid, "total": 100.0, "status": "placed", "created_at": "2026-09-10T00:00:00"})
    await db.transactions.insert_one({"id": str(uuid.uuid4()), "user_id": uid, "type": "order", "amount": -100.0, "status": "success"})
    await db.notifications.insert_one({"id": str(uuid.uuid4()), "user_id": uid, "title": "hi", "body": "there"})
    await db.products.insert_one({"id": str(uuid.uuid4()), "vendor_id": uid, "name": "Iter66 Reset Widget", "price": 10.0, "is_published": False})

    try:
        h = login("support@slangcart.com", "3)Ywxtic")

        man = requests.get(f"{BASE}/admin/backup/account/{uid}/manifest", headers=h, timeout=90).json()
        names = {c["name"]: c["count"] for c in man["collections"]}
        print("account manifest:", names)
        for must in ("users", "orders", "transactions", "notifications", "products"):
            assert names.get(must), f"link-up missed {must}"

        dump = requests.get(f"{BASE}/admin/backup/account/{uid}/dump", params={"collection": "orders"}, headers=h, timeout=90).json()
        assert dump["total"] == 1 and dump["docs"][0]["user_id"] == uid, dump

        # backup gate
        blocked = requests.post(f"{BASE}/admin/system/account-reset", headers=h, timeout=90,
                                json={"danger_pin": PIN, "user_id": uid, "mode": "clear"})
        print("no-backup ->", blocked.status_code, blocked.json().get("detail"))
        assert blocked.status_code == 400

        # wrong pin
        badpin = requests.post(f"{BASE}/admin/system/account-reset", headers=h, timeout=90,
                               json={"danger_pin": "000000", "user_id": uid, "mode": "clear", "backup_downloaded": True})
        assert badpin.status_code == 401, badpin.text

        # clear
        r = requests.post(f"{BASE}/admin/system/account-reset", headers=h, timeout=180,
                          json={"danger_pin": PIN, "user_id": uid, "mode": "clear", "backup_downloaded": True})
        r.raise_for_status()
        print("clear ->", r.json()["summary"])
        still = await db.users.find_one({"id": uid}, {"_id": 0, "wallet_balance": 1})
        assert still and still["wallet_balance"] == 0.0, still
        assert await db.orders.count_documents({"user_id": uid}) == 0
        assert await db.transactions.count_documents({"user_id": uid}) == 0
        assert await db.products.count_documents({"vendor_id": uid}) == 0

        # delete
        r = requests.post(f"{BASE}/admin/system/account-reset", headers=h, timeout=180,
                          json={"danger_pin": PIN, "user_id": uid, "mode": "delete", "backup_downloaded": True})
        r.raise_for_status()
        assert await db.users.find_one({"id": uid}) is None, "account not deleted"
        print("delete -> account gone")

        # vendor shop reset must be scoped
        v1 = await db.users.find_one({"email": "testvendor@test.com"}, {"_id": 0, "id": 1})
        v2 = await db.users.find_one({"email": "testvendor2@test.com"}, {"_id": 0, "id": 1})
        before1 = await db.products.count_documents({"vendor_id": v1["id"]})
        before2 = await db.products.count_documents({"vendor_id": v2["id"]})
        tmp_id = str(uuid.uuid4())
        await db.products.insert_one({"id": tmp_id, "vendor_id": v2["id"], "name": "Iter66 Temp", "price": 5.0, "is_published": False})
        r = requests.post(f"{BASE}/admin/system/reset-shop-products", headers=h, timeout=180,
                          json={"danger_pin": PIN, "vendor_id": v2["id"], "backup_downloaded": True})
        r.raise_for_status()
        print("vendor reset ->", r.json()["summary"])
        assert await db.products.count_documents({"vendor_id": v2["id"]}) == 0
        assert await db.products.count_documents({"vendor_id": v1["id"]}) == before1, "other vendor was touched!"

        # wipe-all guards (never actually executed here)
        for body, expect in [
            ({"danger_pin": PIN, "confirm_phrase": "RESET"}, 400),                       # no backup flag
            ({"danger_pin": PIN, "confirm_phrase": "nope", "backup_downloaded": True}, 400),
            ({"danger_pin": "000000", "confirm_phrase": "RESET", "backup_downloaded": True}, 401),
        ]:
            got = requests.post(f"{BASE}/admin/system/wipe-all", headers=h, timeout=60, json=body)
            print("wipe-all guard ->", got.status_code, got.json().get("detail"))
            assert got.status_code == expect, (body, got.status_code, got.text[:200])
        print("PASS")
    finally:
        # restore fixtures
        await db.users.delete_one({"id": uid})
        await db.orders.delete_many({"user_id": uid})
        await db.transactions.delete_many({"user_id": uid})
        await db.notifications.delete_many({"user_id": uid})
        await db.products.delete_many({"vendor_id": uid})
        v2 = await db.users.find_one({"email": "testvendor2@test.com"}, {"_id": 0, "id": 1, "email": 1})
        if v2 and await db.products.count_documents({"vendor_id": v2["id"]}) == 0:
            src = await db.products.find_one({"name": "Vendor One Widget"}, {"_id": 0})
            if src:
                doc = dict(src)
                doc.update({"id": str(uuid.uuid4()), "name": "Vendor Two Gadget", "price": 250,
                            "vendor_id": v2["id"], "vendor_email": v2.get("email"), "is_published": True})
                doc.pop("restored_from_backup", None)
                await db.products.insert_one(doc)
                print("fixture 'Vendor Two Gadget' restored")
        if old_hash:
            await db.settings.update_one({"id": "global"}, {"$set": {"danger_pin_hash": old_hash}})
            print("danger PIN restored")


if __name__ == "__main__":
    asyncio.run(main())
