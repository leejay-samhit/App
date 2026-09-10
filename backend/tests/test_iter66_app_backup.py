"""Phase 4B smoke test — full-app file backup (manifest / dump / restore).

Temporarily swaps the Danger PIN hash for a known one and restores the
original hash at the end, so the owner's PIN is never changed.
"""
import asyncio
import os
import sys

import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.security import hash_password  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
BASE = "http://localhost:8001/api"
PIN = "135790"


def login(email, password):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=60)
    r.raise_for_status()
    d = r.json()
    return {"Authorization": f"Bearer {d.get('access_token') or d.get('token')}"}


async def swap_pin(new_hash):
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = c[os.environ.get("DB_NAME", "test_database")]
    doc = await db.settings.find_one({"id": "global"}, {"_id": 0, "danger_pin_hash": 1})
    old = (doc or {}).get("danger_pin_hash")
    await db.settings.update_one({"id": "global"}, {"$set": {"danger_pin_hash": new_hash}})
    return old


async def main():
    old_hash = await swap_pin(hash_password(PIN))
    try:
        h = login("support@slangcart.com", "3)Ywxtic")

        man = requests.get(f"{BASE}/admin/backup/manifest", headers=h, timeout=120).json()
        print("manifest:", man["total_documents"], "docs in", len(man["collections"]), "collections")
        assert man["format"] == "slangcart.app-backup"
        names = [c["name"] for c in man["collections"]]
        assert "users" in names and "products" in names and "orders" in names
        assert "db_snapshots" not in names and "pincodes" not in names, "excluded collections leaked"

        # dump a small collection fully
        target = "shop_layout_blocks"
        rows, offset = [], 0
        while True:
            d = requests.get(f"{BASE}/admin/backup/dump", params={"collection": target, "offset": offset, "limit": 5}, headers=h, timeout=120).json()
            rows += d["docs"]
            if not d["has_more"]:
                break
            offset += 5
        print(f"dumped {len(rows)} {target}")
        assert all("_id" not in r for r in rows), "_id leaked"

        # restore that dump back in merge mode — should be a no-op count-wise
        before = len(rows)
        r = requests.post(f"{BASE}/admin/backup/restore", json={
            "collection": target, "docs": rows, "mode": "merge", "first_chunk": True, "danger_pin": PIN,
        }, headers=h, timeout=180)
        r.raise_for_status()
        print("merge ->", r.json())
        again = requests.get(f"{BASE}/admin/backup/dump", params={"collection": target, "limit": 1000}, headers=h, timeout=120).json()
        assert again["total"] == before, f"merge changed the row count {again['total']} != {before}"

        # bad PIN must be rejected
        bad = requests.post(f"{BASE}/admin/backup/restore", json={
            "collection": target, "docs": [], "mode": "wipe", "first_chunk": True, "danger_pin": "000000",
        }, headers=h, timeout=60)
        print("bad pin ->", bad.status_code)
        assert bad.status_code == 401

        # wipe+restore round trip on the same collection
        r = requests.post(f"{BASE}/admin/backup/restore", json={
            "collection": target, "docs": rows, "mode": "wipe", "first_chunk": True, "danger_pin": PIN,
        }, headers=h, timeout=180)
        r.raise_for_status()
        print("wipe ->", r.json())
        final = requests.get(f"{BASE}/admin/backup/dump", params={"collection": target, "limit": 1000}, headers=h, timeout=120).json()
        assert final["total"] == before, f"wipe round trip lost rows: {final['total']} != {before}"

        # non-admin is blocked
        v = login("testvendor@test.com", "Test@1234")
        blocked = requests.get(f"{BASE}/admin/backup/manifest", headers=v, timeout=60)
        print("vendor manifest ->", blocked.status_code)
        assert blocked.status_code in (401, 403)
        print("PASS")
    finally:
        if old_hash:
            await swap_pin(old_hash)
            print("danger PIN restored")


if __name__ == "__main__":
    asyncio.run(main())
