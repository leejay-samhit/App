# Iteration 124 — chat search fixes: 60-char limit, admin-block + chat-block + approval filters on
# every path (name / code / user_id), no codes leaked to non-admins, search by user_id relationship,
# admin delete shared archive budget + truncated, finance invariant.
import os, time, uuid, random
import pytest, requests
from dotenv import load_dotenv
import pymongo

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = os.environ["ADMIN_EMAIL"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]
mdb = pymongo.MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
S = {}
RUN = uuid.uuid4().hex[:6]
PW = "Test@1234"
PFX = f"TEST_i124{RUN}"


def rand_phone():
    while True:
        p = random.choice("6789") + "".join(random.choice("0123456789") for _ in range(9))
        if not mdb.users.find_one({"phone": p}):
            return p


def hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


def wallet_sum():
    r = list(mdb.users.aggregate([{"$group": {"_id": None, "s": {"$sum": "$wallet_balance"}}}]))
    return round(r[0]["s"], 2) if r else 0


def search(tok, term=None, user_id=None):
    p = {}
    if term is not None:
        p["code"] = term
    if user_id is not None:
        p["user_id"] = user_id
    return requests.get(f"{API}/chat/search", params=p, headers=hdr(tok), timeout=30)


def new_user(key, name):
    email = f"test_i124_{key}_{RUN}@example.com"
    r = requests.post(f"{API}/auth/register", json={"name": name, "email": email,
                                                    "password": PW, "phone": rand_phone()}, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    S[key] = {"id": d["user"]["id"], "tok": d["token"], "email": email, "name": name,
              "code": mdb.users.find_one({"id": d["user"]["id"]})["referral_code"]}
    return S[key]


@pytest.fixture(scope="module", autouse=True)
def guard():
    S["tx0"] = mdb.transactions.count_documents({})
    S["w0"] = wallet_sum()
    yield
    print(f"\nFINANCE tx {S['tx0']}->{mdb.transactions.count_documents({})} wallet {S['w0']}->{wallet_sum()}")
    ids = [S[k]["id"] for k in ("s1", "s2", "s3", "bl", "st") if S.get(k)]
    for uid in ids:
        mdb.chat_blocks.delete_many({"blocker_id": uid})
        mdb.chat_requests.delete_many({"from_user_id": uid})
        mdb.chat_threads.delete_many({"participants": uid})
        mdb.notifications.delete_many({"user_id": uid})
        mdb.users.delete_one({"id": uid})
    for aid in S.get("archives", []):
        mdb.deleted_user_archives.delete_one({"id": aid})


@pytest.fixture(scope="module")
def admin_tok():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["token"]


class TestA_Setup:
    def test_register(self):
        new_user("s1", f"{PFX}Self")
        new_user("s2", f"{PFX}Peer")
        new_user("s3", f"{PFX}Pal")
        new_user("bl", f"{PFX}Banned")
        new_user("st", f"{PFX}Status")
        mdb.users.update_one({"id": S["s2"]["id"]}, {"$set": {"address": {"city": "TEST_Tirupati"}}})


# (a) length limit
class TestB_Length:
    def test_40_chars_not_422(self):
        r = search(S["s1"]["tok"], "Venkata Ramana Reddy Kumar Srinivasa Rao"[:40])
        assert r.status_code in (200, 404), r.text

    def test_60_chars_not_422(self):
        r = search(S["s1"]["tok"], "x" * 60)
        assert r.status_code == 404, r.text

    def test_61_chars_422(self):
        assert search(S["s1"]["tok"], "x" * 61).status_code == 422

    def test_missing_both_400(self):
        r = search(S["s1"]["tok"])
        assert r.status_code == 400, r.text
        r2 = search(S["s1"]["tok"], "   ")
        assert r2.status_code == 400, r2.text


# (b) admin-blocked
class TestC_AdminBlocked:
    def test_found_before_block(self):
        r = search(S["s1"]["tok"], S["bl"]["code"])
        assert r.status_code == 200 and r.json()["user"]["id"] == S["bl"]["id"], r.text

    def test_blocked_hidden_everywhere(self, admin_tok):
        b = requests.post(f"{API}/admin/users/{S['bl']['id']}/block", json={"reason": "TEST_i124"},
                          headers=hdr(admin_tok), timeout=30)
        assert b.status_code == 200, b.text
        assert search(S["s1"]["tok"], S["bl"]["code"]).status_code == 404
        assert search(S["s1"]["tok"], S["bl"]["code"].lower()).status_code == 404
        assert search(S["s1"]["tok"], S["bl"]["name"]).status_code == 404
        assert search(S["s1"]["tok"], user_id=S["bl"]["id"]).status_code == 404


# (c) chat-blocked by the searcher
class TestD_ChatBlocked:
    def test_chat_blocked_hidden_by_name_code_id(self):
        b = requests.post(f"{API}/chat/block/{S['s3']['id']}", headers=hdr(S["s1"]["tok"]), timeout=30)
        assert b.status_code == 200, b.text
        try:
            assert search(S["s1"]["tok"], S["s3"]["name"]).status_code == 404
            assert search(S["s1"]["tok"], S["s3"]["code"]).status_code == 404
            assert search(S["s1"]["tok"], user_id=S["s3"]["id"]).status_code == 404
            # a third party (s2) can still find s3
            assert search(S["s2"]["tok"], S["s3"]["code"]).status_code == 200
        finally:
            u = requests.delete(f"{API}/chat/block/{S['s3']['id']}", headers=hdr(S["s1"]["tok"]), timeout=30)
            assert u.status_code == 200, u.text
        assert search(S["s1"]["tok"], S["s3"]["code"]).status_code == 200


# (d) approval status
class TestE_Status:
    @pytest.mark.parametrize("status", ["pending", "rejected", "suspended"])
    def test_status_hidden(self, status):
        mdb.users.update_one({"id": S["st"]["id"]}, {"$set": {"status": status}})
        try:
            assert search(S["s1"]["tok"], S["st"]["code"]).status_code == 404, status
            assert search(S["s1"]["tok"], S["st"]["name"]).status_code == 404, status
            assert search(S["s1"]["tok"], user_id=S["st"]["id"]).status_code == 404, status
        finally:
            mdb.users.update_one({"id": S["st"]["id"]}, {"$set": {"status": "approved"}})

    def test_approved_visible(self):
        r = search(S["s1"]["tok"], S["st"]["code"])
        assert r.status_code == 200, r.text


# (e) ambiguous list privacy
class TestF_Ambiguous:
    def test_non_admin_no_codes(self):
        r = search(S["s1"]["tok"], PFX)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["relationship"] == "ambiguous"
        ids = {m["id"] for m in d["matches"]}
        assert S["s1"]["id"] not in ids and S["bl"]["id"] not in ids
        assert {S["s2"]["id"], S["s3"]["id"], S["st"]["id"]} <= ids
        for m in d["matches"]:
            assert "referral_code" not in m and "sponsor_code" not in m, m
            for k in ("city", "is_vendor", "is_service_provider", "is_delivery_partner"):
                assert k in m, m
        peer = next(m for m in d["matches"] if m["id"] == S["s2"]["id"])
        assert peer["city"] == "TEST_Tirupati"
        S["amb_raw"] = r.text

    def test_non_admin_raw_text_no_codes(self):
        for k in ("s2", "s3", "st"):
            assert S[k]["code"] not in S["amb_raw"]

    def test_admin_sees_codes(self, admin_tok):
        r = search(admin_tok, PFX)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["relationship"] == "ambiguous"
        peer = next(m for m in d["matches"] if m["id"] == S["s2"]["id"])
        assert peer.get("referral_code") == S["s2"]["code"]


# search by user_id relationship
class TestG_ByUserId:
    def test_can_request(self):
        r = search(S["s1"]["tok"], user_id=S["s2"]["id"])
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["user"]["id"] == S["s2"]["id"] and d["relationship"] == "can_request"
        assert d["thread_id"] is None

    def test_request_pending(self):
        q = requests.post(f"{API}/chat/request", json={"to_user_id": S["s2"]["id"], "message": "TEST_hi"},
                          headers=hdr(S["s1"]["tok"]), timeout=30)
        assert q.status_code == 200, q.text
        S["req"] = q.json()["id"]
        d = search(S["s1"]["tok"], user_id=S["s2"]["id"]).json()
        assert d["relationship"] == "request_pending" and d["request_id"] == S["req"], d
        d2 = search(S["s2"]["tok"], user_id=S["s1"]["id"]).json()
        assert d2["relationship"] == "request_pending"

    def test_already_chatting(self):
        a = requests.post(f"{API}/chat/request/{S['req']}/accept", headers=hdr(S["s2"]["tok"]), timeout=30)
        assert a.status_code == 200, a.text
        tid = a.json()["thread_id"]
        d = search(S["s1"]["tok"], user_id=S["s2"]["id"]).json()
        assert d["relationship"] == "already_chatting" and d["thread_id"] == tid, d
        # resending a request now fails with a clear 400 (what the app used to hit silently)
        q = requests.post(f"{API}/chat/request", json={"to_user_id": S["s2"]["id"]},
                          headers=hdr(S["s1"]["tok"]), timeout=30)
        assert q.status_code == 400

    def test_unknown_id_404(self):
        assert search(S["s1"]["tok"], user_id=f"nope-{RUN}").status_code == 404

    def test_self_id_not_200(self):
        assert search(S["s1"]["tok"], user_id=S["s1"]["id"]).status_code in (400, 404)


# admin delete — shared budget + truncated
class TestH_AdminDelete:
    def test_delete_with_shared_budget(self, admin_tok):
        uid = S["st"]["id"]
        blob = "x" * 900_000
        mdb.notifications.insert_many([{"id": f"TEST_n{RUN}{i}", "user_id": uid, "title": "TEST_big",
                                        "body": blob} for i in range(6)])
        mdb.cart_items.insert_many([{"id": f"TEST_c{RUN}{i}", "user_id": uid, "note": blob} for i in range(6)])
        t0 = time.time()
        d = requests.delete(f"{API}/admin/users/{uid}", headers=hdr(admin_tok), timeout=60)
        el = time.time() - t0
        print("delete", d.status_code, round(el, 2), d.text[:300])
        assert d.status_code == 200, d.text
        assert el < 10
        arc = mdb.deleted_user_archives.find_one({"user_id": uid})
        assert arc is not None
        S.setdefault("archives", []).append(arc["id"])
        tr = arc.get("truncated")
        print("truncated", tr, {k: len(v) for k, v in arc["data"].items()})
        kept = len(arc["data"].get("cart_items", [])) + len(arc["data"].get("notifications", []))
        assert 0 < kept < 12, kept
        assert sum(tr.values()) == 12 - kept, tr
        assert mdb.users.find_one({"id": uid}) is None
        assert mdb.notifications.count_documents({"user_id": uid}) == 0
        S["st"] = None
        S["resp_truncated"] = d.json()

    def test_response_reports_truncated(self):
        body = S["resp_truncated"]
        print("resp", body)
        assert "truncated" in str(body)


class TestZFinance:
    def test_finance_unchanged(self):
        assert mdb.transactions.count_documents({}) == S["tx0"]
        assert wallet_sum() == S["w0"]
