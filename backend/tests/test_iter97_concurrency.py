# Iter97 — FIX 1/2/3 independent re-verification: settlement lock (8 parallel),
# stale-lock takeover, fee refund on reject, 5 parallel cashback recoveries.
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import pytest
import requests
from pymongo import MongoClient


def _env(path, key):
    for ln in open(path):
        if ln.startswith(key + "="):
            return ln.split("=", 1)[1].strip().strip('"')


BASE = (os.environ.get("EXPO_BACKEND_URL") or _env("/app/frontend/.env", "EXPO_PUBLIC_BACKEND_URL")).rstrip("/") + "/api"
db = MongoClient(_env("/app/backend/.env", "MONGO_URL"))[_env("/app/backend/.env", "DB_NAME")]
VID = "1115f762-0a4f-474e-bbdb-6227a06f08b1"


def tok(e, p):
    d = requests.post(f"{BASE}/auth/login", json={"email": e, "password": p}, timeout=60).json()
    return {"Authorization": f"Bearer {d.get('access_token') or d.get('token')}"}


@pytest.fixture(scope="module")
def H():
    return {"a": tok("support@slangcart.com", "3)Ywxtic"), "v": tok("testvendor@test.com", "Test@1234")}


def bal():
    return round(float(db.users.find_one({"id": VID})["vendor_earnings"]), 2)


def reject_open(H):
    for w in db.withdrawals.find({"user_id": VID, "status": {"$in": ["pending", "processing"]}}):
        requests.post(f"{BASE}/admin/withdrawals/{w['id']}/reject", headers=H["a"], json={"reason": "TEST_iter97"}, timeout=60)


def seed_cb(amount):
    rid = "TEST_iter97_" + uuid.uuid4().hex[:8]
    db.vendor_outstanding.insert_one({"id": rid, "vendor_id": VID, "kind": "cashback", "status": "open",
                                      "amount": amount, "recovered": 0,
                                      "created_at": datetime.now(timezone.utc).isoformat()})
    db.users.update_one({"id": VID}, {"$inc": {"cashback_outstanding": amount}})
    return rid


def test_parallel_settlements_8(H):
    reject_open(H)
    db.users.update_one({"id": VID}, {"$unset": {"settlement_busy_at": ""}})
    assert bal() >= 5100, f"vendor balance too low {bal()}"
    seed_cb(40)
    b0 = bal()
    with ThreadPoolExecutor(8) as ex:
        rs = list(ex.map(lambda _: requests.post(f"{BASE}/withdrawals", headers=H["v"], json={"amount": 5000}, timeout=90), range(8)))
    codes = sorted(r.status_code for r in rs)
    print("codes", codes)
    ok = [r for r in rs if r.status_code == 200]
    assert len(ok) == 1, codes
    wid = ok[0].json()["id"]
    assert db.withdrawals.count_documents({"user_id": VID, "status": "pending"}) == 1
    assert round(b0 - bal(), 2) == 5000
    fee_rows = db.transactions.count_documents({"type": "withdrawal_transaction_fee", "withdrawal_id": wid}) or \
        db.transactions.count_documents({"type": "withdrawal_transaction_fee", "idempotency_key": {"$regex": wid}})
    rec_rows = db.transactions.count_documents({"type": "cashback_recovery", "idempotency_key": f"CBRECOVER-WDL:{wid}"})
    print("fee rows", fee_rows, "recovery rows", rec_rows, "cb_out", db.users.find_one({"id": VID}).get("cashback_outstanding"))
    assert fee_rows == 1 and rec_rows == 1
    assert round(float(db.users.find_one({"id": VID}).get("cashback_outstanding") or 0), 2) == 0
    assert not db.users.find_one({"id": VID}).get("settlement_busy_at")
    # reject: payout + fee back (cashback recovered stays recovered)
    b1 = bal()
    r = requests.post(f"{BASE}/admin/withdrawals/{wid}/reject", headers=H["a"], json={"reason": "TEST_iter97"}, timeout=60)
    assert r.status_code == 200, r.text
    b2 = bal()
    print("reject refund", round(b2 - b1, 2))
    r = requests.post(f"{BASE}/admin/withdrawals/{wid}/reject", headers=H["a"], json={"reason": "replay"}, timeout=60)
    assert bal() == b2
    assert round(b2 - b0, 2) == -40, f"after reject vendor is down {round(b0-b2,2)} (expected only the 40 cashback)"


def test_lock_release_and_stale(H):
    reject_open(H)
    db.users.update_one({"id": VID}, {"$set": {"settlement_busy_at": datetime.now(timezone.utc).isoformat()}})
    r = requests.post(f"{BASE}/withdrawals", headers=H["v"], json={"amount": 5000}, timeout=60)
    # 429 = the 5/hour settlement rate limit kicked in first (also a refusal).
    if r.status_code == 429:
        import pytest
        # do not leave the seeded lock behind on testvendor
        db.users.update_one({"id": VID}, {"$unset": {"settlement_busy_at": ""}})
        pytest.skip("settlement rate limit reached — rerun in an hour")
    assert r.status_code == 409, r.text
    db.users.update_one({"id": VID}, {"$set": {"settlement_busy_at": (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()}})
    r = requests.post(f"{BASE}/withdrawals", headers=H["v"], json={"amount": 5000}, timeout=60)
    assert r.status_code == 200, r.text
    assert not db.users.find_one({"id": VID}).get("settlement_busy_at")
    reject_open(H)


def test_parallel_recoveries_5(H):
    prev = round(float(db.users.find_one({"id": VID}).get("cashback_outstanding") or 0), 2)
    rid = seed_cb(60)
    b0 = bal()
    u = f"{BASE}/admin/cashback/outstanding/{VID}/recover"
    with ThreadPoolExecutor(5) as ex:
        rs = list(ex.map(lambda _: requests.post(u, headers=H["a"], json={"amount": 60}, timeout=90), range(5)))
    print("codes", [r.status_code for r in rs], [r.text[:80] for r in rs])
    out = round(float(db.users.find_one({"id": VID}).get("cashback_outstanding") or 0), 2)
    assert out == 0, out
    assert round(b0 - bal(), 2) == round(60 + prev, 2)
    assert round(sum(float(r.json().get("applied") or 0) for r in rs if r.status_code == 200), 2) == round(60 + prev, 2)
    row = db.vendor_outstanding.find_one({"id": rid})
    print("row", row.get("status"), row.get("recovered"))
    assert row["status"] == "settled" and round(row["recovered"], 2) == 60
