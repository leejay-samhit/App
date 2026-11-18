# Iteration 125 — chat-request guards, admin-delete archive order + truncated,
# and the money invariants. Run with ADMIN_PASSWORD exported.
import os
import random
import uuid

import pymongo
import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = os.environ["ADMIN_EMAIL"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]
PW = "Passw0rd!23"
RUN = uuid.uuid4().hex[:6]
mdb = pymongo.MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

S = {}


def rand_phone():
    while True:
        p = "9" + "".join(random.choice("0123456789") for _ in range(9))
        if not mdb.users.find_one({"phone": p}):
            return p


def hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


def new_user(key, name):
    r = requests.post(
        f"{API}/auth/register",
        json={"name": name, "email": f"test_i125_{key}_{RUN}@example.com", "password": PW, "phone": rand_phone()},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    S[key] = {"tok": r.json()["token"], "id": r.json()["user"]["id"], "name": name}
    return S[key]


@pytest.fixture(scope="module", autouse=True)
def money_guard():
    before = (
        mdb.transactions.count_documents({}),
        round(sum(u.get("wallet_balance") or 0 for u in mdb.users.find({}, {"wallet_balance": 1})), 2),
    )
    yield
    after = (
        mdb.transactions.count_documents({}),
        round(sum(u.get("wallet_balance") or 0 for u in mdb.users.find({}, {"wallet_balance": 1})), 2),
    )
    print(f"\nFINANCE tx {before[0]}->{after[0]} wallet {before[1]}->{after[1]}")
    assert before == after, "financial state changed during the test run"


@pytest.fixture(scope="module", autouse=True)
def setup(money_guard):
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, r.text
    S["admin"] = {"tok": r.json()["token"]}
    new_user("a", f"TEST_i125{RUN}Alpha")
    new_user("b", f"TEST_i125{RUN}Bravo")
    yield
    for key in ("a", "b"):
        if key in S:
            requests.delete(f"{API}/admin/users/{S[key]['id']}", headers=hdr(S["admin"]["tok"]), timeout=60)


class TestChatRequestGuards:
    def test_normal_request_works(self):
        r = requests.post(
            f"{API}/chat/request", json={"to_user_id": S["b"]["id"]}, headers=hdr(S["a"]["tok"]), timeout=30,
        )
        assert r.status_code == 200, r.text
        S["req_id"] = r.json()["id"]

    def test_blocked_target_is_404(self):
        mdb.users.update_one({"id": S["b"]["id"]}, {"$set": {"is_blocked": True}})
        try:
            r = requests.post(
                f"{API}/chat/request", json={"to_user_id": S["b"]["id"]}, headers=hdr(S["a"]["tok"]), timeout=30,
            )
            assert r.status_code == 404, r.text
        finally:
            mdb.users.update_one({"id": S["b"]["id"]}, {"$set": {"is_blocked": False}})

    @pytest.mark.parametrize("status", ["pending", "rejected", "suspended"])
    def test_unapproved_target_is_404(self, status):
        mdb.users.update_one({"id": S["b"]["id"]}, {"$set": {"status": status}})
        try:
            r = requests.post(
                f"{API}/chat/request", json={"to_user_id": S["b"]["id"]}, headers=hdr(S["a"]["tok"]), timeout=30,
            )
            assert r.status_code == 404, r.text
        finally:
            mdb.users.update_one({"id": S["b"]["id"]}, {"$unset": {"status": ""}})

    def test_chat_block_either_direction_is_403(self):
        for blocker, blocked in ((S["a"]["id"], S["b"]["id"]), (S["b"]["id"], S["a"]["id"])):
            mdb.chat_blocks.insert_one({"id": str(uuid.uuid4()), "blocker_id": blocker, "blocked_id": blocked})
            try:
                r = requests.post(
                    f"{API}/chat/request", json={"to_user_id": S["b"]["id"]}, headers=hdr(S["a"]["tok"]), timeout=30,
                )
                assert r.status_code == 403, r.text
            finally:
                mdb.chat_blocks.delete_many({"blocker_id": blocker, "blocked_id": blocked})


class TestAdminDeleteArchive:
    def test_archives_money_records_first(self):
        victim = new_user("victim", f"TEST_i125{RUN}Victim")
        uid = victim["id"]
        # Seed rows the archive must keep, plus noise it may drop.
        mdb.transactions.insert_one({
            "id": f"t_{RUN}", "user_id": uid, "amount": 0, "type": "test_marker",
            "status": "success", "description": "archive order probe",
        })
        mdb.orders.insert_one({"id": f"o_{RUN}", "user_id": uid, "total": 0, "status": "test"})
        mdb.notifications.insert_many([
            {"id": f"n_{RUN}_{i}", "user_id": uid, "title": "x" * 200} for i in range(50)
        ])
        try:
            r = requests.delete(f"{API}/admin/users/{uid}", headers=hdr(S["admin"]["tok"]), timeout=60)
            assert r.status_code == 200, r.text
            body = r.json()
            assert "truncated" in body
            arc = mdb.deleted_user_archives.find_one({"user_id": uid})
            assert arc, "no archive written"
            data = arc["data"]
            assert any(t["id"] == f"t_{RUN}" for t in data.get("transactions", []))
            assert any(o["id"] == f"o_{RUN}" for o in data.get("orders", []))
            assert mdb.users.find_one({"id": uid}) is None
        finally:
            S.pop("victim", None)
            mdb.transactions.delete_many({"id": f"t_{RUN}"})
            mdb.orders.delete_many({"id": f"o_{RUN}"})
            mdb.notifications.delete_many({"user_id": uid})
            mdb.deleted_user_archives.delete_many({"user_id": uid})
