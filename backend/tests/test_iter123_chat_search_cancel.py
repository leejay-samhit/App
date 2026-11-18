# Iteration 123 — chat name search (exact code / unique name / ambiguous / 404 / self+blocked excluded),
# deletion-cancel `unlocked` honesty, admin block clears deletion_ticket_id, admin delete archive, finance invariant.
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


def search(tok, term):
    return requests.get(f"{API}/chat/search", params={"code": term}, headers=hdr(tok), timeout=30)


def new_user(key, name):
    email = f"test_i123_{key}_{RUN}@example.com"
    r = requests.post(f"{API}/auth/register", json={"name": name, "email": email,
                                                    "password": PW, "phone": rand_phone()}, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    S[key] = {"id": d["user"]["id"], "tok": d["token"], "email": email, "name": name}
    return S[key]


@pytest.fixture(scope="module", autouse=True)
def guard():
    S["tx0"] = mdb.transactions.count_documents({})
    S["w0"] = wallet_sum()
    yield
    print(f"\nFINANCE tx {S['tx0']}->{mdb.transactions.count_documents({})} wallet {S['w0']}->{wallet_sum()}")
    for k in ("s1", "s2", "bl", "dl"):
        u = S.get(k)
        if not u:
            continue
        tids = [t["id"] for t in mdb.tickets.find({"user_id": u["id"]}, {"id": 1})]
        mdb.ticket_messages.delete_many({"ticket_id": {"$in": tids}})
        mdb.tickets.delete_many({"id": {"$in": tids}})
        mdb.chat_blocks.delete_many({"blocker_id": u["id"]})
        mdb.users.delete_one({"id": u["id"]})
    for aid in S.get("archives", []):
        mdb.deleted_user_archives.delete_one({"id": aid})


@pytest.fixture(scope="module")
def admin_tok():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["token"]


# ---------- chat search by name or code ----------
class TestChatSearch:
    def test_register(self):
        new_user("s1", f"TEST_i123Self{RUN}")
        new_user("s2", f"TEST_i123Peer{RUN}")
        new_user("bl", f"TEST_i123Locked{RUN}")
        new_user("dl", f"TEST_i123Del{RUN}")

    def test_exact_code_wins(self):
        tv2 = mdb.users.find_one({"name": "Test Vendor Two"}, {"referral_code": 1, "id": 1})
        assert tv2 and tv2.get("referral_code")
        r = search(S["s1"]["tok"], tv2["referral_code"].lower())
        assert r.status_code == 200, r.text
        assert r.json()["user"]["id"] == tv2["id"]
        assert r.json()["relationship"] in ("can_request", "request_pending", "already_chatting")

    def test_unique_name(self):
        r = search(S["s1"]["tok"], "Test Vendor Two")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["relationship"] != "ambiguous" and d["user"]["name"] == "Test Vendor Two"

    def test_unique_name_prefix_case_insensitive(self):
        r = search(S["s1"]["tok"], f"test_i123peer{RUN}"[:20])
        assert r.status_code == 200, r.text
        assert r.json()["user"]["id"] == S["s2"]["id"]

    @pytest.mark.parametrize("term", ["Test", "buyer"])
    def test_ambiguous(self, term):
        r = search(S["s1"]["tok"], term)
        print(term, r.status_code, r.text[:300])
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["relationship"] == "ambiguous" and d["user"] is None
        assert len(d["matches"]) > 1
        assert S["s1"]["id"] not in [m["id"] for m in d["matches"]]

    def test_nothing_matches(self):
        r = search(S["s1"]["tok"], "zzqxnomatch")
        assert r.status_code == 404
        assert r.json()["detail"] == "Nobody matches that name or code."

    def test_regex_chars_safe(self):
        r = search(S["s1"]["tok"], ".*(((")
        assert r.status_code == 404, r.text

    def test_self_excluded_by_name(self):
        r = search(S["s1"]["tok"], S["s1"]["name"])
        assert r.status_code == 404, r.text

    def test_admin_blocked_user_excluded(self, admin_tok):
        b = requests.post(f"{API}/admin/users/{S['bl']['id']}/block", json={"reason": "TEST_i123"},
                          headers=hdr(admin_tok), timeout=30)
        assert b.status_code == 200, b.text
        r = search(S["s1"]["tok"], S["bl"]["name"][:20])
        assert r.status_code == 404, r.text

    def test_long_full_name_not_422(self):
        # a real full name can be > 20 chars; search should not reject it with a raw 422
        r = search(S["s1"]["tok"], "Venkata Ramana Reddy Kumar")
        print("long name", r.status_code, r.text[:150])
        assert r.status_code in (200, 404), r.text

    def test_admin_blocked_user_by_code(self):
        code = mdb.users.find_one({"id": S["bl"]["id"]})["referral_code"]
        r = search(S["s1"]["tok"], code)
        print("blocked by code", r.status_code, r.text[:200])
        assert r.status_code == 404, "admin-blocked user still findable by exact referral code"

    def test_chat_blocked_user_excluded(self):
        b = requests.post(f"{API}/chat/block/{S['s2']['id']}", headers=hdr(S["s1"]["tok"]), timeout=30)
        assert b.status_code == 200, b.text
        r = search(S["s1"]["tok"], S["s2"]["name"])
        print("chat-blocked", r.status_code, r.text[:200])
        requests.delete(f"{API}/chat/block/{S['s2']['id']}", headers=hdr(S["s1"]["tok"]), timeout=30)
        assert r.status_code == 404, "user the caller blocked in chat is still returned by search"

    def test_short_term_rejected(self):
        # Nov-2026: min_length was dropped so a NAME can be searched; a
        # 1-character term simply finds nobody.
        assert search(S["s1"]["tok"], "a").status_code == 404


# ---------- deletion cancel honesty + admin block ownership ----------
class TestDeletionCancel:
    def test_cancel_reports_unlocked_true_then_false(self, admin_tok):
        u = S["dl"]
        r = requests.post(f"{API}/me/account-deletion", json={"confirm": True}, headers=hdr(u["tok"]), timeout=30)
        assert r.status_code == 200, r.text
        tid = r.json()["ticket"]["id"]
        S["t1"] = tid
        c = requests.post(f"{API}/admin/account-deletion/{tid}/cancel", headers=hdr(admin_tok), timeout=30)
        assert c.status_code == 200 and c.json()["unlocked"] is True, c.text
        assert mdb.users.find_one({"id": u["id"]})["is_blocked"] is False
        c2 = requests.post(f"{API}/admin/account-deletion/{tid}/cancel", headers=hdr(admin_tok), timeout=30)
        assert c2.status_code == 200 and c2.json()["unlocked"] is False, c2.text

    def test_unknown_ticket_404(self, admin_tok):
        c = requests.post(f"{API}/admin/account-deletion/nope-{RUN}/cancel", headers=hdr(admin_tok), timeout=30)
        assert c.status_code == 404

    def test_admin_block_clears_deletion_ticket(self, admin_tok):
        u = S["dl"]
        lg = requests.post(f"{API}/auth/login", json={"email": u["email"], "password": PW}, timeout=30)
        assert lg.status_code == 200, lg.text
        r = requests.post(f"{API}/me/account-deletion", json={"confirm": True},
                          headers=hdr(lg.json()["token"]), timeout=30)
        assert r.status_code == 200, r.text
        tid = r.json()["ticket"]["id"]
        assert mdb.users.find_one({"id": u["id"]})["deletion_ticket_id"] == tid
        b = requests.post(f"{API}/admin/users/{u['id']}/block", json={"reason": "TEST_i123 admin"},
                          headers=hdr(admin_tok), timeout=30)
        assert b.status_code == 200
        doc = mdb.users.find_one({"id": u["id"]})
        assert doc["is_blocked"] is True and doc.get("deletion_ticket_id") is None
        c = requests.post(f"{API}/admin/account-deletion/{tid}/cancel", headers=hdr(admin_tok), timeout=30)
        assert c.status_code == 200 and c.json()["unlocked"] is False, c.text
        doc = mdb.users.find_one({"id": u["id"]})
        assert doc["is_blocked"] is True and doc["block_reason"] == "TEST_i123 admin"
        assert requests.post(f"{API}/auth/login", json={"email": u["email"], "password": PW},
                             timeout=30).status_code == 403


# ---------- admin delete archive ----------
class TestAdminDelete:
    def test_delete_fast_with_truncated(self, admin_tok):
        uid = S["dl"]["id"]
        t0 = time.time()
        d = requests.delete(f"{API}/admin/users/{uid}", headers=hdr(admin_tok), timeout=60)
        el = time.time() - t0
        print("delete", d.status_code, round(el, 2))
        assert d.status_code == 200, d.text
        assert el < 10
        arc = mdb.deleted_user_archives.find_one({"user_id": uid})
        assert arc is not None
        S.setdefault("archives", []).append(arc["id"])
        assert isinstance(arc.get("truncated"), dict) and arc["truncated"] == {}
        assert arc["data"]["users"][0]["id"] == uid
        assert len(arc["data"].get("tickets", [])) >= 2
        assert mdb.users.find_one({"id": uid}) is None


class TestZFinance:
    def test_finance_unchanged(self):
        assert mdb.transactions.count_documents({}) == S["tx0"]
        assert wallet_sum() == S["w0"]
