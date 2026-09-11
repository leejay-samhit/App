"""Streamed backup file + one-account restore/merge — API test.

Covers the OOM fix (the whole backup now comes down as ONE streamed .json
instead of being stitched together in the app) and the per-account restore
that the Reset centre now offers.

Temporarily swaps the Danger PIN hash for a known value and restores the
original at the end.
"""
import asyncio
import json
import os
import sys

import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

BASE = os.environ.get("TEST_BASE", "http://localhost:8001/api")
ADMIN = (os.environ.get("ADMIN_EMAIL", "support@slangcart.com"), os.environ.get("ADMIN_PASSWORD", "3)Ywxtic"))
TEST_PIN = "135790"
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def mongo():
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return cli[os.environ.get("DB_NAME", "test_database")]


async def swap_pin(new_hash):
    db = mongo()
    doc = await db.settings.find_one({"id": "global"}, {"_id": 0, "danger_pin_hash": 1})
    old = (doc or {}).get("danger_pin_hash")
    await db.settings.update_one({"id": "global"}, {"$set": {"danger_pin_hash": new_hash}})
    return old


def main():
    tok = requests.post(f"{BASE}/auth/login", json={"email": ADMIN[0], "password": ADMIN[1]}, timeout=30).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}

    # ── 1. full-app streamed file -------------------------------------------
    man = requests.get(f"{BASE}/admin/backup/manifest", headers=h, timeout=60).json()
    r = requests.get(f"{BASE}/admin/backup/file", headers=h, stream=True, timeout=600)
    assert r.status_code == 200, r.text
    assert "attachment" in (r.headers.get("content-disposition") or ""), r.headers
    raw = b"".join(r.iter_content(65536))
    full = json.loads(raw)  # must be valid JSON end-to-end
    assert full["format"] == "slangcart.app-backup" and full["scope"] == "app", full.keys()
    got = sum(len(v) for v in full["collections"].values())
    assert got == man["total_documents"], f"streamed {got} docs, manifest said {man['total_documents']}"
    print(f"full app file OK — {len(raw)/1024/1024:.1f} MB, {got} docs, {len(full['collections'])} collections")

    # ── 2. one-account streamed file ----------------------------------------
    users = requests.get(f"{BASE}/admin/users", headers=h, params={"q": "testvendor@test.com"}, timeout=60).json()
    rows = users if isinstance(users, list) else (users.get("users") or users.get("items") or [])
    vid = [u for u in rows if u.get("email") == "testvendor@test.com"][0]["id"]
    amn = requests.get(f"{BASE}/admin/backup/account/{vid}/manifest", headers=h, timeout=60).json()
    ar = requests.get(f"{BASE}/admin/backup/account/{vid}/file", headers=h, stream=True, timeout=300)
    assert ar.status_code == 200, ar.text
    acct = json.loads(b"".join(ar.iter_content(65536)))
    assert acct["scope"] == "account" and acct["account"]["id"] == vid, acct["account"]
    agot = sum(len(v) for v in acct["collections"].values())
    assert agot == amn["total_documents"], f"streamed {agot}, manifest {amn['total_documents']}"
    print(f"account file OK — {agot} docs for {acct['account']['email']}")

    # ── 3. restore (merge) that account file back ---------------------------
    old_hash = asyncio.get_event_loop().run_until_complete(swap_pin(pwd.hash(TEST_PIN)))
    try:
        bad = requests.post(
            f"{BASE}/admin/backup/restore", headers=h,
            json={"collection": "products", "docs": [], "mode": "merge", "first_chunk": True, "danger_pin": "000000"},
            timeout=60,
        )
        assert bad.status_code == 401, f"wrong PIN accepted: {bad.status_code}"

        restored = 0
        for name, docs in acct["collections"].items():
            if not docs:
                continue
            step = 25 if name in ("products", "chat_messages", "offline_sales") else 200
            for i in range(0, len(docs), step):
                rr = requests.post(
                    f"{BASE}/admin/backup/restore", headers=h,
                    json={"collection": name, "docs": docs[i:i + step], "mode": "merge",
                          "first_chunk": i == 0, "danger_pin": TEST_PIN},
                    timeout=120,
                )
                assert rr.status_code == 200, f"{name}: {rr.status_code} {rr.text[:200]}"
                restored += (rr.json().get("inserted") or 0) + (rr.json().get("upserted") or 0)
        print(f"account merge-restore OK — {restored} records replayed")

        after = requests.get(f"{BASE}/admin/backup/account/{vid}/manifest", headers=h, timeout=60).json()
        assert after["total_documents"] >= amn["total_documents"], (after["total_documents"], amn["total_documents"])
        print("post-restore manifest still consistent:", after["total_documents"], "docs")
    finally:
        asyncio.get_event_loop().run_until_complete(swap_pin(old_hash))
        print("danger PIN hash restored")

    print("ALL ASSERTIONS PASSED")


if __name__ == "__main__":
    main()
