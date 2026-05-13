"""Regression test for bcrypt-safe verify_password fix.

Tests POST /api/auth/login under several edge cases:
1. Valid existing admin login → 200
2. Valid existing test user login → 200
3. Wrong password → 401
4. Nonexistent email → 401
5. User missing password_hash (Google OAuth-only) → 401, NOT 500
6. User with malformed password_hash → 401, NOT 500
7. Register then login round-trip → 200
"""
import os
import sys
import uuid
import asyncio
from pathlib import Path

import requests

# Resolve backend URL from the frontend .env (per system prompt rules)
FRONTEND_ENV = Path("/app/frontend/.env")
BACKEND_URL = None
for line in FRONTEND_ENV.read_text().splitlines():
    if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
        BACKEND_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")
        break
if not BACKEND_URL:
    print("ERROR: Could not resolve EXPO_PUBLIC_BACKEND_URL from /app/frontend/.env")
    sys.exit(1)

BASE = f"{BACKEND_URL}/api"
print(f"Using backend: {BASE}\n")

results = []  # list[ tuple(case_name, passed, status_code, body) ]


def record(name, passed, status, body):
    results.append((name, passed, status, body))
    flag = "PASS" if passed else "FAIL"
    print(f"[{flag}] {name}  →  HTTP {status}  body={body!r}")


# ---------- Mongo direct access for setup/cleanup ----------
sys.path.insert(0, "/app/backend")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "referral_ecom_db")
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


async def insert_test_user(doc):
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    await db.users.insert_one(doc)
    client.close()


async def delete_test_user(email):
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    res = await db.users.delete_many({"email": email})
    client.close()
    return res.deleted_count


# ---------- TEST CASES ----------

# Case 1: admin valid login
def case_1_admin_valid():
    r = requests.post(f"{BASE}/auth/login", json={"email": "admin@app.com", "password": "Admin@123"}, timeout=15)
    try:
        body = r.json()
    except Exception:
        body = r.text
    ok = r.status_code == 200 and isinstance(body, dict) and "token" in body
    record("1. admin valid (admin@app.com / Admin@123)", ok, r.status_code, str(body)[:200])


# Case 2: testuser valid login
def case_2_testuser_valid():
    r = requests.post(f"{BASE}/auth/login", json={"email": "testuser@app.com", "password": "Test@123"}, timeout=15)
    try:
        body = r.json()
    except Exception:
        body = r.text
    ok = r.status_code == 200 and isinstance(body, dict) and "token" in body
    record("2. testuser valid (testuser@app.com / Test@123)", ok, r.status_code, str(body)[:200])


# Case 3: wrong password
def case_3_wrong_password():
    r = requests.post(f"{BASE}/auth/login", json={"email": "admin@app.com", "password": "WrongPass!999"}, timeout=15)
    try:
        body = r.json()
    except Exception:
        body = r.text
    ok = r.status_code == 401 and isinstance(body, dict) and body.get("detail") == "Invalid credentials"
    record("3. wrong password for admin → 401", ok, r.status_code, str(body)[:200])


# Case 4: nonexistent email
def case_4_nonexistent_email():
    r = requests.post(f"{BASE}/auth/login", json={"email": f"nobody-{uuid.uuid4().hex[:8]}@nowhere-xyz.com", "password": "Whatever@1"}, timeout=15)
    try:
        body = r.json()
    except Exception:
        body = r.text
    ok = r.status_code == 401 and isinstance(body, dict) and body.get("detail") == "Invalid credentials"
    record("4. nonexistent email → 401", ok, r.status_code, str(body)[:200])


# Case 5: user exists but no password_hash (Google-OAuth-only simulation)
def case_5_no_password_hash():
    uid = f"test-nopw-{uuid.uuid4().hex[:8]}"
    email = f"nopw-{uuid.uuid4().hex[:6]}@test.example"
    doc = {
        "id": uid,
        "email": email,
        "name": "Google OAuth User",
        "role": "user",
        "admin_role": None,
        "google_id": "g-test-1",
        "auth_provider": "google",
        "approval_status": "approved",
        "is_blocked": False,
        # NO password_hash field at all
    }
    try:
        asyncio.run(insert_test_user(doc))
        r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": "AnyPassword@123"}, timeout=15)
        try:
            body = r.json()
        except Exception:
            body = r.text
        # MUST be 401 and NOT 500
        ok = r.status_code == 401 and isinstance(body, dict) and body.get("detail") == "Invalid credentials"
        record("5. user with NO password_hash field → 401 (not 500)", ok, r.status_code, str(body)[:200])
    finally:
        n = asyncio.run(delete_test_user(email))
        print(f"   cleanup: deleted {n} user(s) for {email}")


# Case 6: user exists with malformed password_hash
def case_6_malformed_password_hash():
    uid = f"test-bad-{uuid.uuid4().hex[:8]}"
    email = f"badhash-{uuid.uuid4().hex[:6]}@test.example"
    doc = {
        "id": uid,
        "email": email,
        "name": "Malformed Hash User",
        "role": "user",
        "admin_role": None,
        "password_hash": "not-a-real-bcrypt-hash",  # malformed
        "approval_status": "approved",
        "is_blocked": False,
    }
    try:
        asyncio.run(insert_test_user(doc))
        r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": "AnyPassword@123"}, timeout=15)
        try:
            body = r.json()
        except Exception:
            body = r.text
        ok = r.status_code == 401 and isinstance(body, dict) and body.get("detail") == "Invalid credentials"
        record("6. user with MALFORMED password_hash → 401 (not 500)", ok, r.status_code, str(body)[:200])
    finally:
        n = asyncio.run(delete_test_user(email))
        print(f"   cleanup: deleted {n} user(s) for {email}")


# Case 7: register then login round-trip
def case_7_register_login_roundtrip():
    email = f"regress-{uuid.uuid4().hex[:8]}@regression-example.com"
    pwd = "Regress@2026"
    payload = {"name": "Regression Test User", "email": email, "password": pwd, "phone": "9000000000"}
    r = requests.post(f"{BASE}/auth/register", json=payload, timeout=15)
    if r.status_code != 200:
        record("7a. register new user → 200", False, r.status_code, r.text[:200])
        return
    try:
        rbody = r.json()
    except Exception:
        rbody = r.text
    record("7a. register new user → 200", True, r.status_code, str(rbody)[:120])

    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": pwd}, timeout=15)
    try:
        body = r.json()
    except Exception:
        body = r.text
    ok = r.status_code == 200 and isinstance(body, dict) and "token" in body
    record("7b. login with newly-registered creds → 200", ok, r.status_code, str(body)[:120])

    # cleanup
    n = asyncio.run(delete_test_user(email))
    print(f"   cleanup: deleted {n} user(s) for {email}")


def main():
    case_1_admin_valid()
    case_2_testuser_valid()
    case_3_wrong_password()
    case_4_nonexistent_email()
    case_5_no_password_hash()
    case_6_malformed_password_hash()
    case_7_register_login_roundtrip()

    total = len(results)
    passed = sum(1 for _, p, _, _ in results if p)
    print("\n" + "=" * 70)
    print(f"SUMMARY: {passed}/{total} PASS")
    for name, p, status, body in results:
        flag = "✅" if p else "❌"
        print(f"  {flag} {name}  (HTTP {status})")
    print("=" * 70)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
