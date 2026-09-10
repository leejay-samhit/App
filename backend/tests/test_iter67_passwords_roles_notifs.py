"""Sep 2026 — admin password tools, scoped admin roles, notifications.

1. a NEW signup keeps a recoverable copy → super admin can read it back
2. legacy accounts (no copy) answer 409 and must use Reset & reveal
3. Reset & reveal returns a working password (bcrypt login still verifies)
4. a products_manager can reach ONLY the products area (403 elsewhere)
5. chat messages and orders now create in-app notification rows
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


def login(email, password):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=60)
    return r


async def main():
    from core.db import db
    from core.security import hash_password, verify_password

    h = login("support@slangcart.com", "3)Ywxtic").json()
    ah = {"Authorization": f"Bearer {h.get('access_token') or h.get('token')}"}

    # ── 1. new signup → recoverable
    tag = uuid.uuid4().hex[:8]
    email = f"iter67_{tag}@example.com"
    pw = f"Pw{tag}@1"
    reg = requests.post(f"{BASE}/auth/register", json={
        "name": "Iter67 User", "email": email, "password": pw, "phone": "9" + tag[:9].ljust(9, "0"),
    }, timeout=90)
    print("register:", reg.status_code)
    assert reg.status_code in (200, 201), reg.text[:300]
    new_user = await db.users.find_one({"email": email}, {"_id": 0, "id": 1})
    uid = new_user["id"]
    got = requests.get(f"{BASE}/admin/users/{uid}/password", headers=ah, timeout=60)
    print("reveal new signup:", got.status_code, got.json().get("password") == pw)
    assert got.status_code == 200 and got.json()["password"] == pw

    # list endpoints must never leak the ciphertext
    lst = requests.get(f"{BASE}/admin/users", headers=ah, params={"q": email}, timeout=60).text
    assert "password_recovery_ciphertext" not in lst and "password_hash" not in lst, "leak in /admin/users"

    # ── 2. legacy account → 409
    legacy_id = str(uuid.uuid4())
    await db.users.insert_one({"id": legacy_id, "email": f"legacy_{tag}@example.com", "name": "Legacy",
                               "referral_code": f"LG{tag.upper()}",
                               "password_hash": hash_password("Legacy@123"), "role": "user"})
    lg = requests.get(f"{BASE}/admin/users/{legacy_id}/password", headers=ah, timeout=60)
    print("legacy reveal:", lg.status_code, lg.json().get("detail", "")[:60])
    assert lg.status_code == 409

    # ── 3. reset & reveal
    rr = requests.post(f"{BASE}/admin/users/{legacy_id}/password/reset-reveal", headers=ah, json={}, timeout=90)
    assert rr.status_code == 200, rr.text
    temp = rr.json()["password"]
    fresh = await db.users.find_one({"id": legacy_id})
    assert verify_password(temp, fresh["password_hash"]), "generated password doesn't verify"
    again = requests.get(f"{BASE}/admin/users/{legacy_id}/password", headers=ah, timeout=60).json()
    print("reset & reveal:", temp[:4] + "…", "readable again:", again.get("password") == temp)
    assert again.get("password") == temp

    # ── 4. scoped role
    pm = requests.post(f"{BASE}/admin/users/{uid}/promote", headers=ah,
                       json={"admin_role": "products_manager"}, timeout=60)
    print("promote products_manager:", pm.status_code, pm.text[:120] if pm.status_code != 200 else "")
    assert pm.status_code == 200, pm.text
    pr = login(email, pw).json()
    ph = {"Authorization": f"Bearer {pr.get('access_token') or pr.get('token')}"}
    checks = {
        "/admin/products?limit=5": 200,
        "/admin/users": 403,
        "/admin/orders": 403,
        "/admin/shop-layout": 403,
        "/admin/backup/manifest": 403,
    }
    for path, expect in checks.items():
        got = requests.get(BASE + path, headers=ph, timeout=90)
        print(f"  products_manager {path} -> {got.status_code} (want {expect})")
        assert got.status_code == expect, (path, got.status_code, got.text[:150])
    # a super admin's own reveal endpoint must stay closed to them
    blocked = requests.get(f"{BASE}/admin/users/{legacy_id}/password", headers=ph, timeout=60)
    assert blocked.status_code == 403, blocked.status_code

    # ── 5. notifications
    before_chat = await db.notifications.count_documents({"kind": "chat"})
    b = login("testbuyer@test.com", "Test@1234").json()
    bh = {"Authorization": f"Bearer {b.get('access_token') or b.get('token')}"}
    v = await db.users.find_one({"email": "testvendor@test.com"}, {"_id": 0, "id": 1})
    th = requests.post(f"{BASE}/chat/threads", headers=bh, json={"other_user_id": v["id"]}, timeout=60)
    assert th.status_code == 200, th.text
    tid = th.json()["id"]
    msg = requests.post(f"{BASE}/chat/{tid}/messages", headers=bh,
                        json={"text": "iter67 notification check"}, timeout=60)
    print("chat message:", msg.status_code)
    assert msg.status_code == 200, msg.text
    after_chat = await db.notifications.count_documents({"kind": "chat"})
    print("chat notifications:", before_chat, "->", after_chat)
    assert after_chat > before_chat, "no bell entry for a new chat message"
    vend_note = await db.notifications.find_one({"user_id": v["id"], "kind": "chat"})
    assert vend_note, "vendor didn't get the chat notification"

    print("PASS")

    # cleanup
    await db.users.delete_many({"id": {"$in": [uid, legacy_id]}})
    await db.notifications.delete_many({"user_id": {"$in": [uid, legacy_id]}})
    await db.chat_messages.delete_many({"text": "iter67 notification check"})


if __name__ == "__main__":
    asyncio.run(main())
