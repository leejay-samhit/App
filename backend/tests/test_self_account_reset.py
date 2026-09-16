"""E2E test: super admin can CLEAR their own account (Sep-2026 fix),
self-DELETE stays blocked. Uses a temp super admin + temp danger PIN,
restores everything afterwards. Run:
  cd /app/backend && EXPO_BACKEND_URL=https://<preview> python3 tests/test_self_account_reset.py
"""
import asyncio
import os
import sys
import uuid

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = os.environ["EXPO_BACKEND_URL"].rstrip("/") + "/api"
TEMP_EMAIL = f"tempadmin-{uuid.uuid4().hex[:6]}@test.com"
TEMP_PW = "TempAdmin@123"
TEMP_PIN = "654321"

results = []


def check(name, ok, extra=""):
    results.append((name, ok, extra))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {extra}")


async def setup():
    from core.db import db
    from core.security import hash_password
    doc = await db.settings.find_one({"id": "global"}, {"_id": 0, "danger_pin_hash": 1})
    saved = (doc or {}).get("danger_pin_hash")
    await db.settings.update_one({"id": "global"}, {"$set": {"danger_pin_hash": hash_password(TEMP_PIN)}})
    uid = str(uuid.uuid4())
    await db.users.insert_one({
        "id": uid, "email": TEMP_EMAIL, "password_hash": hash_password(TEMP_PW),
        "name": "Temp Admin", "role": "admin", "admin_role": "super_admin",
        "referral_code": f"TMP{uuid.uuid4().hex[:8].upper()}",
        "wallet_balance": 500.0, "wallet_buckets": {"referral_commission": 500.0},
        "total_earned": 500.0, "is_active": True,
    })
    # give the account something to wipe
    await db.notifications.insert_one({"id": str(uuid.uuid4()), "user_id": uid, "title": "t"})
    return saved, uid


async def teardown(saved_hash, uid):
    from core.db import db
    if saved_hash:
        await db.settings.update_one({"id": "global"}, {"$set": {"danger_pin_hash": saved_hash}})
    await db.notifications.delete_many({"user_id": uid})
    await db.users.delete_one({"id": uid})
    from core.db import client
    client.close()


def login(email, pw):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": pw}, timeout=30)
    return r.json().get("token")


async def main():
    saved, uid = await setup()
    try:
        tok = login(TEMP_EMAIL, TEMP_PW)
        check("temp admin login", bool(tok))
        H = {"Authorization": f"Bearer {tok}"}

        # 1. self DELETE must be blocked with the new message
        r = requests.post(f"{BASE}/admin/system/account-reset", headers=H,
                          json={"danger_pin": TEMP_PIN, "user_id": uid, "mode": "delete",
                                "backup_downloaded": True}, timeout=30)
        check("self-delete blocked", r.status_code == 400 and "own admin account" in r.json().get("detail", ""),
              f"-> {r.status_code} {r.json().get('detail')}")

        # 2. self CLEAR must succeed
        r = requests.post(f"{BASE}/admin/system/account-reset", headers=H,
                          json={"danger_pin": TEMP_PIN, "user_id": uid, "mode": "clear",
                                "backup_downloaded": True}, timeout=30)
        d = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        check("self-clear allowed", r.status_code == 200 and d.get("ok"), f"-> {r.status_code} {str(d)[:160]}")

        # 3. account kept + wallet zeroed
        from core.db import db
        u = await db.users.find_one({"id": uid}, {"_id": 0})
        check("login kept", u is not None and u.get("email") == TEMP_EMAIL)
        check("wallet zeroed", float(u.get("wallet_balance") if u.get("wallet_balance") is not None else -1) == 0.0)
        buckets = u.get("wallet_buckets") or {}
        check("buckets zeroed", all(float(v or 0) == 0.0 for v in buckets.values()), str(buckets))

        # 4. owned data wiped
        n = await db.notifications.count_documents({"user_id": uid})
        check("owned data wiped", n == 0, f"notifications left: {n}")

        # 5. login still works after clear
        tok2 = login(TEMP_EMAIL, TEMP_PW)
        check("re-login after clear", bool(tok2))
    finally:
        await teardown(saved, uid)

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{'ALL PASS' if not failed else 'FAILURES: ' + ', '.join(failed)}")
    sys.exit(1 if failed else 0)


asyncio.run(main())
