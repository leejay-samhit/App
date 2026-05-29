"""
Backend regression — 4 small changes (2026-05-29):
  1. Demo seed safety (SEED_DEMO_USERS env-gated)
  2. /service/apply accepts service_subcategory_id (parent-id validated)
  3. /admin/service-applications/{aid}/approve propagates subcategory
  4. NEW POST /admin/purge-demo-users (super_admin only)
"""

import os
import sys
import time
import uuid
import json
import asyncio

import requests

BACKEND_URL = "https://vendor-network-app-1.preview.emergentagent.com"
API = f"{BACKEND_URL}/api"

ADMIN = {"email": "admin@app.com", "password": "Admin@123"}
USER  = {"email": "testuser@app.com", "password": "Test@123"}

results = []  # (label, passed, detail)

def log(label: str, passed: bool, detail: str = ""):
    mark = "PASS" if passed else "FAIL"
    print(f"[{mark}] {label}{(' — ' + detail) if detail else ''}")
    results.append((label, passed, detail))


def login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    r.raise_for_status()
    j = r.json()
    return j.get("token") or j.get("access_token")


def H(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


# ─────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────
print("\n=== SETUP ===")
admin_tok = login(**ADMIN)
log("Setup: admin login", True, f"token len={len(admin_tok)}")
user_tok = login(**USER)
log("Setup: testuser login", True, f"token len={len(user_tok)}")


# ─────────────────────────────────────────────────────────────────
# Test 1 — purge w/o auth → 401
# ─────────────────────────────────────────────────────────────────
print("\n=== TEST 1: purge no-auth ===")
r = requests.post(f"{API}/admin/purge-demo-users", timeout=30)
log("1. purge-demo-users no-auth -> 401", r.status_code == 401,
    f"status={r.status_code} body={r.text[:120]}")


# ─────────────────────────────────────────────────────────────────
# Test 2 — purge as regular user → 403
# ─────────────────────────────────────────────────────────────────
print("\n=== TEST 2: purge as regular user ===")
r = requests.post(f"{API}/admin/purge-demo-users", headers=H(user_tok), timeout=30)
log("2. purge-demo-users as regular user -> 403", r.status_code == 403,
    f"status={r.status_code} body={r.text[:160]}")


# ─────────────────────────────────────────────────────────────────
# Test 3 — purge as admin → 200 + shape
# ─────────────────────────────────────────────────────────────────
print("\n=== TEST 3: purge as admin ===")
r = requests.post(f"{API}/admin/purge-demo-users", headers=H(admin_tok), timeout=60)
ok = r.status_code == 200
body = {}
try:
    body = r.json()
except Exception:
    pass
shape_ok = (
    ok
    and body.get("ok") is True
    and isinstance(body.get("removed"), int)
    # emails may be omitted on the "none found" branch — accept either
    and ("emails" in body or body.get("removed") == 0)
)
log("3. purge-demo-users as admin -> 200 with shape {ok, removed, emails?}",
    shape_ok, f"status={r.status_code} body={json.dumps(body)[:240]}")


# ─────────────────────────────────────────────────────────────────
# Test 4 — GET /admin/service-categories
# ─────────────────────────────────────────────────────────────────
print("\n=== TEST 4: list service categories ===")
r = requests.get(f"{API}/admin/service-categories", headers=H(admin_tok), timeout=30)
ok = r.status_code == 200
cats = r.json().get("categories", []) if ok else []
CAT_ID = None
CAT2_ID = None
if cats:
    primary = next((c for c in cats if c.get("active", True)), cats[0])
    CAT_ID = primary["id"]
    for c in cats:
        if c.get("id") != CAT_ID:
            CAT2_ID = c["id"]
            break
log("4. GET /admin/service-categories -> 200, picked CAT_ID",
    ok and bool(CAT_ID),
    f"status={r.status_code} total={len(cats)} CAT_ID={CAT_ID} CAT2_ID={CAT2_ID}")


# ─────────────────────────────────────────────────────────────────
# Test 5 — POST /admin/service-subcategories
# ─────────────────────────────────────────────────────────────────
print("\n=== TEST 5: create subcategory ===")
suffix = uuid.uuid4().hex[:6]
sub_name = f"RefactorPhase2Sub-{suffix}"
payload5 = {"parent_id": CAT_ID, "name": sub_name, "icon": "droplet"}
r = requests.post(f"{API}/admin/service-subcategories", headers=H(admin_tok),
                  json=payload5, timeout=30)
ok = r.status_code == 200
body = r.json() if ok else {}
SUB_ID = (body.get("subcategory") or {}).get("id")
log("5. POST /admin/service-subcategories -> 200, SUB_ID captured",
    ok and bool(SUB_ID),
    f"status={r.status_code} SUB_ID={SUB_ID} name={sub_name}")

# Also create a subcategory under a *different* parent for the mismatch test (test 8)
SUB_WRONG_PARENT_ID = None
if CAT2_ID:
    r = requests.post(f"{API}/admin/service-subcategories", headers=H(admin_tok),
                      json={"parent_id": CAT2_ID, "name": f"MismatchSub-{suffix}", "icon": "x"},
                      timeout=30)
    if r.status_code == 200:
        SUB_WRONG_PARENT_ID = (r.json().get("subcategory") or {}).get("id")


# ─────────────────────────────────────────────────────────────────
# Test 6 — Prepare a clean user (no pending service application)
# We register a brand-new user and flip registration_paid via Mongo
# so we can call /service/apply.
# ─────────────────────────────────────────────────────────────────
print("\n=== TEST 6: prep clean user ===")

async def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    return db, client


CLEAN_EMAIL = f"phase2-clean-{suffix}@app.com"
CLEAN_PASS  = "Phase2@123"
r = requests.post(f"{API}/auth/register", json={
    "name": "Phase2 Clean",
    "email": CLEAN_EMAIL,
    "password": CLEAN_PASS,
    "phone": f"+91 9{int(time.time()) % 1000000000:09d}",
    "referral_code": "EARN",
}, timeout=30)
reg_ok = r.status_code == 200
log("6a. POST /auth/register fresh user", reg_ok,
    f"status={r.status_code} email={CLEAN_EMAIL} body={r.text[:160]}")


async def _flip(email):
    db, client = await _db()
    res = await db.users.update_one(
        {"email": email.lower()},
        {"$set": {"registration_paid": True, "approval_status": "approved"}},
    )
    u = await db.users.find_one({"email": email.lower()}, {"_id": 0, "id": 1, "email": 1, "registration_paid": 1, "approval_status": 1})
    client.close()
    return res.modified_count, u

mod, clean_user = asyncio.run(_flip(CLEAN_EMAIL))
log("6b. mark fresh user paid+approved (mongo)",
    bool(clean_user and clean_user.get("registration_paid")),
    f"modified={mod} user={clean_user}")

clean_tok = login(CLEAN_EMAIL, CLEAN_PASS) if reg_ok else None
log("6c. clean-user login", bool(clean_tok), f"token len={len(clean_tok) if clean_tok else 0}")


# ─────────────────────────────────────────────────────────────────
# Test 7 — /service/apply with valid subcategory
# ─────────────────────────────────────────────────────────────────
print("\n=== TEST 7: apply with valid subcategory ===")
apply_body = {
    "service_name": "PhaseTwoTest",
    "service_category": "WhateverName",
    "category_id": CAT_ID,
    "service_subcategory_id": SUB_ID,
    "pincode": "110001",
    "charge": 1,
    "languages": ["en"],
}
r = requests.post(f"{API}/service/apply", headers=H(clean_tok), json=apply_body, timeout=30)
ok = r.status_code == 200
body = r.json() if ok else {}
app7 = body.get("application", {})
APP_ID = app7.get("id")
got_sub_id = app7.get("service_subcategory_id")
got_sub_name = app7.get("service_subcategory_name")
all_ok = (
    ok
    and got_sub_id == SUB_ID
    and got_sub_name == sub_name
)
log("7. POST /service/apply (valid sub) -> 200 with sub_id+name stored",
    all_ok,
    f"status={r.status_code} sub_id={got_sub_id} sub_name={got_sub_name} APP_ID={APP_ID} body={r.text[:200]}")


# ─────────────────────────────────────────────────────────────────
# Test 8 — /service/apply with WRONG subcategory (parent mismatch)
# ─────────────────────────────────────────────────────────────────
print("\n=== TEST 8: apply with mismatched-parent subcategory ===")
WRONG_EMAIL = f"phase2-wrong-{suffix}@app.com"
WRONG_PASS  = "Phase2@123"
r = requests.post(f"{API}/auth/register", json={
    "name": "Phase2 Wrong",
    "email": WRONG_EMAIL,
    "password": WRONG_PASS,
    "phone": f"+91 8{int(time.time()) % 1000000000:09d}",
    "referral_code": "EARN",
}, timeout=30)
asyncio.run(_flip(WRONG_EMAIL))
wrong_tok = login(WRONG_EMAIL, WRONG_PASS)

mismatch_sub_id = SUB_WRONG_PARENT_ID or str(uuid.uuid4())
apply_body_wrong = {
    "service_name": "PhaseTwoMismatch",
    "service_category": "WhateverName",
    "category_id": CAT_ID,
    "service_subcategory_id": mismatch_sub_id,
    "pincode": "110001",
    "charge": 1,
    "languages": ["en"],
}
r = requests.post(f"{API}/service/apply", headers=H(wrong_tok), json=apply_body_wrong, timeout=30)
ok = r.status_code == 200
body = r.json() if ok else {}
app8 = body.get("application", {})
got_sub_id = app8.get("service_subcategory_id")
got_sub_name = app8.get("service_subcategory_name")
silent_ok = ok and got_sub_id is None and got_sub_name is None
log("8. POST /service/apply (wrong parent) -> 200 BUT sub silently nulled",
    silent_ok,
    f"status={r.status_code} sub_id={got_sub_id} sub_name={got_sub_name} mismatch_sub={mismatch_sub_id}")


# ─────────────────────────────────────────────────────────────────
# Test 9 — approve and verify user doc has sub fields
# ─────────────────────────────────────────────────────────────────
print("\n=== TEST 9: approve + verify user doc ===")
me_sub_id = None
me_sub_name = None
if APP_ID:
    r = requests.post(f"{API}/admin/service-applications/{APP_ID}/approve",
                      headers=H(admin_tok), timeout=30)
    approve_ok_flag = r.status_code == 200
    log("9a. POST /admin/service-applications/{id}/approve -> 200",
        approve_ok_flag, f"status={r.status_code} body={r.text[:160]}")
    r = requests.get(f"{API}/auth/me", headers=H(clean_tok), timeout=30)
    if r.status_code == 200:
        me = r.json()
        me_sub_id = me.get("service_subcategory_id")
        me_sub_name = me.get("service_subcategory_name")
    log("9b. user /auth/me has service_subcategory_id + name set",
        me_sub_id == SUB_ID and me_sub_name == sub_name,
        f"sub_id={me_sub_id} sub_name={me_sub_name}")
else:
    log("9. SKIPPED - no APP_ID from test 7", False)


# ─────────────────────────────────────────────────────────────────
# Test 10 — DELETE the subcategory
# ─────────────────────────────────────────────────────────────────
print("\n=== TEST 10: cleanup subcategory ===")
if SUB_ID:
    r = requests.delete(f"{API}/admin/service-subcategories/{SUB_ID}",
                        headers=H(admin_tok), timeout=30)
    log("10. DELETE /admin/service-subcategories/$SUB_ID -> 200",
        r.status_code == 200, f"status={r.status_code} body={r.text[:160]}")
else:
    log("10. SKIPPED - no SUB_ID", False)

if SUB_WRONG_PARENT_ID:
    requests.delete(f"{API}/admin/service-subcategories/{SUB_WRONG_PARENT_ID}",
                    headers=H(admin_tok), timeout=30)

# Cleanup the test users + applications
async def _cleanup():
    db, client = await _db()
    for e in [CLEAN_EMAIL.lower(), WRONG_EMAIL.lower()]:
        u = await db.users.find_one({"email": e}, {"_id": 0, "id": 1})
        if u:
            await db.service_applications.delete_many({"user_id": u["id"]})
            await db.users.delete_one({"id": u["id"]})
    client.close()

asyncio.run(_cleanup())
print("\n=== Cleanup done ===")


# ─────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────
print("\n" + "=" * 64)
print("SUMMARY")
print("=" * 64)
passed = sum(1 for _, ok, _ in results if ok)
total  = len(results)
for label, ok, detail in results:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
print(f"\n{passed}/{total} checks PASS")
sys.exit(0 if passed == total else 1)
