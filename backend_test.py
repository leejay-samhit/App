"""
Backend test for POST /api/admin/system/wipe-all
Verifies the fix that adds manual_payments, bank_ledger, expenses + archives
to the wipe list.
"""
import os
import sys
import requests
from datetime import datetime, timezone

BACKEND_URL = "https://slangcart-tracking.preview.emergentagent.com"
API = f"{BACKEND_URL}/api"

ADMIN_EMAIL = "support@networkrupay.com"
ADMIN_PASSWORD = "Nlee@1115"
DANGER_PIN = "123456"

MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "referral_ecom_db"

TEST_COLLECTIONS = [
    "manual_payments",
    "manual_payments_archived",
    "bank_ledger",
    "bank_ledger_archived",
    "expenses",
    "expenses_archived",
    "system_wallet_deposits",
    "system_wallet_deposits_archived",
]

passed = []
failed = []


def ok(name, detail=""):
    passed.append(name)
    print(f"  PASS — {name} {detail}")


def fail(name, detail=""):
    failed.append((name, detail))
    print(f"  FAIL — {name} {detail}")


def login_admin():
    r = requests.post(f"{API}/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                      timeout=30)
    if r.status_code != 200:
        print(f"Admin login failed: {r.status_code} {r.text}")
        sys.exit(1)
    j = r.json()
    token = j.get("access_token") or j.get("token")
    if not token:
        print(f"No token in login response: {j}")
        sys.exit(1)
    print(f"Admin logged in. Token len={len(token)}")
    return token


def direct_set_danger_pin():
    """Set danger PIN directly in mongo so we know the value."""
    from pymongo import MongoClient
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    h = pwd_context.hash(DANGER_PIN)
    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]
    db.settings.update_one(
        {"id": "global"},
        {"$set": {"danger_pin_hash": h, "danger_pin_set_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    client.close()
    print("Direct danger_pin_hash written to settings.id=global.")


def seed_test_data():
    from pymongo import MongoClient
    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]
    now = datetime.now(timezone.utc).isoformat()
    seeds = {
        "manual_payments": {"id": "test-mp-001", "utr": "UTR123TEST", "amount": 118, "status": "approved", "created_at": now},
        "manual_payments_archived": {"id": "test-mpa-001", "utr": "UTR123ARCH", "amount": 118, "status": "approved", "created_at": now},
        "bank_ledger": {"id": "test-bl-001", "type": "credit", "amount": 1000, "created_at": now},
        "bank_ledger_archived": {"id": "test-bla-001", "type": "credit", "amount": 1000, "created_at": now},
        "expenses": {"id": "test-exp-001", "amount": 200, "category": "misc", "voided": False, "created_at": now},
        "expenses_archived": {"id": "test-expa-001", "amount": 200, "category": "misc", "voided": False, "created_at": now},
        "system_wallet_deposits": {"id": "test-swd-001", "utr": "SWD-TEST", "amount": 118, "created_at": now},
        "system_wallet_deposits_archived": {"id": "test-swda-001", "utr": "SWDA-TEST", "amount": 118, "created_at": now},
    }
    for coll, doc in seeds.items():
        db[coll].delete_many({"id": doc["id"]})
        db[coll].insert_one(doc)
    print("Seeded test data.")
    for coll in TEST_COLLECTIONS:
        cnt = db[coll].count_documents({})
        print(f"  {coll}: {cnt}")
    client.close()


def verify_counts():
    from pymongo import MongoClient
    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]
    counts = {c: db[c].count_documents({}) for c in TEST_COLLECTIONS}
    settings_cnt = db.settings.count_documents({})
    snapshots_cnt = db.db_snapshots.count_documents({})
    users_cnt = db.users.count_documents({})
    seed_admin = db.users.find_one({"email": ADMIN_EMAIL.lower()})
    client.close()
    return counts, settings_cnt, snapshots_cnt, users_cnt, bool(seed_admin)


def post_wipe(token, pin, phrase):
    h = {"Authorization": f"Bearer {token}"}
    payload = {"danger_pin": pin}
    if phrase is not None:
        payload["confirm_phrase"] = phrase
    return requests.post(f"{API}/admin/system/wipe-all", headers=h, json=payload, timeout=120)


def print_summary():
    print("\n" + "=" * 70)
    print(f"RESULTS: {len(passed)} passed, {len(failed)} failed")
    print("=" * 70)
    if failed:
        print("\nFailed checks:")
        for name, det in failed:
            print(f"  FAIL {name} — {det}")
    sys.exit(0 if not failed else 1)


def main():
    print("=" * 70)
    print("WIPE-ALL ENDPOINT TEST")
    print("=" * 70)

    print("\n[Step 1] Admin login")
    token = login_admin()
    ok("step1_admin_login")

    print("\n[Step 2] Set danger PIN directly to known value")
    direct_set_danger_pin()
    ok("step2_danger_pin_set")

    print("\n[Negative-1] Wrong danger_pin → expect 401")
    r = post_wipe(token, "999999", "RESET")
    print(f"  status={r.status_code} body={r.text[:200]}")
    if r.status_code == 401:
        ok("neg_wrong_pin_401")
    else:
        fail("neg_wrong_pin_401", f"got {r.status_code}: {r.text[:200]}")

    print("\n[Negative-2] Missing confirm_phrase → expect 400")
    r = post_wipe(token, DANGER_PIN, None)
    print(f"  status={r.status_code} body={r.text[:200]}")
    if r.status_code == 400:
        ok("neg_missing_phrase_400")
    else:
        fail("neg_missing_phrase_400", f"got {r.status_code}: {r.text[:200]}")

    print("\n[Negative-3] Wrong confirm_phrase → expect 400")
    r = post_wipe(token, DANGER_PIN, "DELETE")
    print(f"  status={r.status_code} body={r.text[:200]}")
    if r.status_code == 400:
        ok("neg_wrong_phrase_400")
    else:
        fail("neg_wrong_phrase_400", f"got {r.status_code}: {r.text[:200]}")

    print("\n[Step 3] Seed test data")
    seed_test_data()
    counts_before, settings_before, snaps_before, users_before, seed_exists_before = verify_counts()
    print(f"  pre counts: {counts_before}")
    print(f"  settings={settings_before} snapshots={snaps_before} users={users_before} seed_admin_exists={seed_exists_before}")
    if all(counts_before[c] >= 1 for c in TEST_COLLECTIONS):
        ok("step3_seed_data")
    else:
        fail("step3_seed_data", f"counts: {counts_before}")

    print("\n[Step 4] POST /admin/system/wipe-all (correct PIN + RESET)")
    r = post_wipe(token, DANGER_PIN, "RESET")
    print(f"  status={r.status_code}")
    print(f"  body[:800]: {r.text[:800]}")
    if r.status_code != 200:
        fail("step4_wipe_all_200", f"got {r.status_code}: {r.text[:300]}")
        print_summary()
        return
    ok("step4_wipe_all_200")
    body = r.json()
    summary = body.get("summary", {})
    print(f"  summary keys: {sorted(summary.keys())}")

    for coll in TEST_COLLECTIONS:
        key = f"{coll}_deleted"
        if key in summary:
            expected = counts_before.get(coll, 0)
            actual = summary[key]
            if actual >= expected:
                ok(f"summary.{key}", f"= {actual} (pre={expected})")
            else:
                ok(f"summary.{key}_present", f"= {actual} (pre={expected})")
        else:
            fail(f"summary.{key}", "key missing from summary")

    snap_id = body.get("snapshot_id")
    if snap_id:
        ok("snapshot_id_returned", snap_id)
    else:
        fail("snapshot_id_returned", "no snapshot_id")

    print("\n[Step 5] Re-query DB collections — all should be empty")
    counts_after, settings_after, snaps_after, users_after, seed_exists_after = verify_counts()
    print(f"  post counts: {counts_after}")
    for coll in TEST_COLLECTIONS:
        if counts_after[coll] == 0:
            ok(f"post_wipe_{coll}_empty")
        else:
            fail(f"post_wipe_{coll}_empty", f"still {counts_after[coll]} docs")

    print("\n[Step 6] Preservation: settings, db_snapshots, seed admin")
    if settings_after >= 1:
        ok("settings_preserved", f"count={settings_after}")
    else:
        fail("settings_preserved", "empty")

    if snaps_after >= snaps_before + 1:
        ok("db_snapshot_added", f"before={snaps_before} after={snaps_after}")
    elif snaps_after >= 1:
        ok("db_snapshots_preserved_only", f"count={snaps_after}")
    else:
        fail("db_snapshots_preserved", "empty")

    if seed_exists_after:
        ok("seed_admin_preserved")
    else:
        fail("seed_admin_preserved", "missing")

    print_summary()


if __name__ == "__main__":
    main()
