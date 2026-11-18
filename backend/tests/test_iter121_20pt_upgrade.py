# Iteration 121 — 20-point upgrade: admin delete, register phone, admin phone edit,
# mobile change OTP, account deletion lock, chat delivery threads, role apply (no payment),
# festival banner text + artwork, backup purge gate, financial invariants.
import os, time, uuid, random, hashlib, asyncio
from datetime import datetime, timezone, timedelta
import pytest, requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
import pymongo

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = os.environ["ADMIN_EMAIL"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]
mdb = pymongo.MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

S = {}  # shared state across ordered tests
RUN = uuid.uuid4().hex[:6]


def rand_phone():
    while True:
        p = "9" + "".join(random.choice("0123456789") for _ in range(9))
        if not mdb.users.find_one({"phone": p}):
            return p


def hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


def wallet_sum():
    r = list(mdb.users.aggregate([{"$group": {"_id": None, "s": {"$sum": "$wallet_balance"}}}]))
    return round(r[0]["s"], 2) if r else 0


def register(email, phone, name="TEST_user"):
    return requests.post(f"{API}/auth/register", json={
        "name": name, "email": email, "password": "Test@1234", "phone": phone}, timeout=30)


@pytest.fixture(scope="module", autouse=True)
def finance_guard():
    S["tx0"] = mdb.transactions.count_documents({})
    S["w0"] = wallet_sum()
    yield
    S["tx1"] = mdb.transactions.count_documents({})
    S["w1"] = wallet_sum()
    print(f"\nFINANCE tx {S['tx0']}->{S['tx1']} wallet {S['w0']}->{S['w1']}")
    # cleanup of throwaway users this run created (by id)
    for k in ("u1", "u2", "u3"):
        u = S.get(k)
        if u and mdb.users.find_one({"id": u["id"]}):
            tids = [t["id"] for t in mdb.tickets.find({"user_id": u["id"]}, {"id": 1})]
            mdb.ticket_messages.delete_many({"ticket_id": {"$in": tids}})
            mdb.tickets.delete_many({"id": {"$in": tids}})
            mdb.users.delete_one({"id": u["id"]})
    for tid in S.get("threads", []):
        mdb.chat_messages.delete_many({"thread_id": tid})
        mdb.chat_threads.delete_one({"id": tid})
    for aid in S.get("archives", []):
        mdb.deleted_user_archives.delete_one({"id": aid})


@pytest.fixture(scope="module")
def admin_tok():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["token"]


# ---------- BUG 2: register phone handling ----------
class TestRegister:
    def test_clean_register_normalises_plus91(self):
        p = rand_phone()
        fmt = f"+91 {p[:5]} {p[5:]}"
        r = register(f"test_i121_u1_{RUN}@example.com", fmt)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("token")
        assert d["user"].get("approval_status") == "approved"
        doc = mdb.users.find_one({"email": f"test_i121_u1_{RUN}@example.com"})
        assert doc["phone"] == p
        S["u1"] = {"id": doc["id"], "phone": p, "tok": d["token"], "email": doc["email"]}

    def test_duplicate_phone_not_500(self):
        r = register(f"test_i121_dup_{RUN}@example.com", S["u1"]["phone"])
        assert r.status_code in (400, 409), r.text
        assert "mobile" in r.json()["detail"].lower()

    def test_invalid_phone_400(self):
        r = register(f"test_i121_bad_{RUN}@example.com", "12345")
        assert r.status_code == 400, r.text

    def test_register_u2_u3(self):
        for k in ("u2", "u3"):
            p = rand_phone()
            r = register(f"test_i121_{k}_{RUN}@example.com", p)
            assert r.status_code == 200, r.text
            S[k] = {"id": r.json()["user"]["id"], "phone": p, "tok": r.json()["token"],
                    "email": f"test_i121_{k}_{RUN}@example.com"}


# ---------- REQ 7: role applications without membership ----------
class TestApplyNoPayment:
    @pytest.mark.parametrize("path,body", [
        ("/service/apply", {"service_name": "TEST svc", "service_category": "plumber", "pincode": "517501", "charge": 100}),
        ("/delivery-partner/apply", {"full_name": "TEST Dp", "phone": "9000000000"}),
        ("/vendor/apply", {"shop_name": "TEST shop"}),
    ])
    def test_apply_not_gated_by_membership(self, path, body):
        # valid-shape payload so the request reaches the membership gate (an empty body only 422s)
        r = requests.post(f"{API}{path}", json=body, headers=hdr(S["u2"]["tok"]), timeout=30)
        txt = r.text.lower()
        print(path, r.status_code, r.text[:200])
        for c in ("vendor_applications", "service_applications", "delivery_partner_applications", "dp_applications"):
            mdb[c].delete_many({"user_id": S["u2"]["id"]})
        assert "membership" not in txt and "only members" not in txt and "118" not in txt, r.text


# ---------- BUG 4: admin edits phone ----------
class TestAdminPhone:
    def test_valid_phone_saved_normalised(self, admin_tok):
        mdb.users.update_one({"id": S["u3"]["id"]}, {"$set": {"phone_verified": True}})
        p = rand_phone()
        r = requests.patch(f"{API}/admin/users/{S['u3']['id']}", json={"phone": f"+91{p}"}, headers=hdr(admin_tok), timeout=30)
        assert r.status_code == 200, r.text
        doc = mdb.users.find_one({"id": S["u3"]["id"]})
        assert doc["phone"] == p and doc.get("phone_verified") is False
        S["u3"]["phone"] = p

    def test_duplicate_phone_4xx(self, admin_tok):
        r = requests.patch(f"{API}/admin/users/{S['u3']['id']}", json={"phone": S["u1"]["phone"]}, headers=hdr(admin_tok), timeout=30)
        assert 400 <= r.status_code < 500, r.text
        assert "already" in r.json()["detail"]

    def test_invalid_phone_400(self, admin_tok):
        r = requests.patch(f"{API}/admin/users/{S['u3']['id']}", json={"phone": "12345"}, headers=hdr(admin_tok), timeout=30)
        assert r.status_code == 400, r.text


# ---------- REQ 8: mobile change via OTP ----------
class TestMobileChange:
    def test_send_otp_validation(self):
        t = hdr(S["u2"]["tok"])
        r = requests.post(f"{API}/me/mobile/change/send-otp", json={"mobile": "1234567890"}, headers=t, timeout=30)
        assert r.status_code == 400, r.text
        r = requests.post(f"{API}/me/mobile/change/send-otp", json={"mobile": S["u2"]["phone"]}, headers=t, timeout=30)
        assert r.status_code == 400, r.text
        r = requests.post(f"{API}/me/mobile/change/send-otp", json={"mobile": S["u1"]["phone"]}, headers=t, timeout=30)
        assert r.status_code == 409, r.text

    def test_verify_changes_phone_keeps_identity(self):
        new = rand_phone()
        before = mdb.users.find_one({"id": S["u2"]["id"]})
        orders_before = mdb.orders.count_documents({"user_id": S["u2"]["id"]})
        salt = uuid.uuid4().hex
        now = datetime.now(timezone.utc)
        mdb.otp_codes.delete_many({"mobile": new})
        mdb.otp_codes.insert_one({"mobile": new, "otp_hash": hashlib.sha256(f"{salt}:{new}:424242".encode()).hexdigest(),
                                  "salt": salt, "purpose": "change", "attempts": 0, "consumed": False,
                                  "created_at": now.isoformat(), "expires_at": (now + timedelta(minutes=5)).isoformat()})
        t = hdr(S["u2"]["tok"])
        bad = requests.post(f"{API}/me/mobile/change/verify", json={"mobile": new, "otp": "111111"}, headers=t, timeout=30)
        assert bad.status_code == 400, bad.text
        r = requests.post(f"{API}/me/mobile/change/verify", json={"mobile": new, "otp": "424242"}, headers=t, timeout=30)
        assert r.status_code == 200, r.text
        after = mdb.users.find_one({"id": S["u2"]["id"]})
        assert after["phone"] == new and after.get("phone_verified") is True
        assert after["id"] == before["id"]
        assert (after.get("wallet_balance") or 0) == (before.get("wallet_balance") or 0)
        assert mdb.orders.count_documents({"user_id": S["u2"]["id"]}) == orders_before
        S["u2"]["phone"] = new


# ---------- REQ 20: chat threads ----------
class TestChat:
    def test_no_shared_order_403(self):
        r = requests.post(f"{API}/chat/threads", json={"other_user_id": S["u2"]["id"]}, headers=hdr(S["u1"]["tok"]), timeout=30)
        assert r.status_code == 403, r.text

    def test_shared_order_opens_thread(self):
        oid = f"TEST_order_{RUN}"
        mdb.orders.insert_one({"id": oid, "user_id": S["u1"]["id"], "vendor_id": S["u2"]["id"], "status": "placed",
                               "items": [], "total": 0, "test": True, "created_at": datetime.now(timezone.utc).isoformat()})
        try:
            r = requests.post(f"{API}/chat/threads", json={"other_user_id": S["u2"]["id"]}, headers=hdr(S["u1"]["tok"]), timeout=30)
            assert r.status_code == 200, r.text
            S.setdefault("threads", []).append(r.json()["id"])
        finally:
            mdb.orders.delete_one({"id": oid})

    def test_approved_provider_opens_thread(self):
        prov = mdb.users.find_one({"$or": [{"is_service_provider": True}, {"service_status": "approved"}]}, {"id": 1})
        if not prov:
            pytest.skip("no approved provider")
        r = requests.post(f"{API}/chat/threads", json={"other_user_id": prov["id"]}, headers=hdr(S["u1"]["tok"]), timeout=30)
        assert r.status_code == 200, r.text
        S.setdefault("threads", []).append(r.json()["id"])

    def test_threads_list_flags_and_sort(self):
        r = requests.get(f"{API}/chat/threads", headers=hdr(S["u1"]["tok"]), timeout=30)
        assert r.status_code == 200, r.text
        items = r.json() if isinstance(r.json(), list) else r.json().get("threads", [])
        assert len(items) >= 1
        for t in items:
            assert "is_delivery_partner" in t, t.keys()
            assert "is_delivery_partner" in (t.get("other") or {})
        ts = [t.get("last_message_at") or "" for t in items]
        assert ts == sorted(ts, reverse=True), ts


# ---------- REQ 11+13: account deletion ----------
class TestAccountDeletion:
    def test_initial_state(self):
        r = requests.get(f"{API}/me/account-deletion", headers=hdr(S["u1"]["tok"]), timeout=30)
        assert r.status_code == 200 and r.json() == {"request": None, "account_locked": False}, r.text

    def test_confirm_false_400(self):
        r = requests.post(f"{API}/me/account-deletion", json={"reason": "x", "confirm": False}, headers=hdr(S["u1"]["tok"]), timeout=30)
        assert r.status_code == 400

    def test_request_locks_account(self):
        r = requests.post(f"{API}/me/account-deletion", json={"reason": "TEST_leaving", "confirm": True}, headers=hdr(S["u1"]["tok"]), timeout=30)
        assert r.status_code == 200, r.text
        tk = r.json()["ticket"]
        assert tk["category"] == "account_deletion"
        S["del_ticket"] = tk["id"]
        assert mdb.users.find_one({"id": S["u1"]["id"]})["is_blocked"] is True
        me = requests.get(f"{API}/auth/me", headers=hdr(S["u1"]["tok"]), timeout=30)
        assert me.status_code in (401, 403), me.text
        lg = requests.post(f"{API}/auth/login", json={"email": S["u1"]["email"], "password": "Test@1234"}, timeout=30)
        assert lg.status_code in (401, 403), lg.text

    def test_admin_cancel_unlocks(self, admin_tok):
        r = requests.post(f"{API}/admin/account-deletion/{S['del_ticket']}/cancel", headers=hdr(admin_tok), timeout=30)
        assert r.status_code == 200, r.text
        assert mdb.tickets.find_one({"id": S["del_ticket"]})["status"] == "closed"
        lg = requests.post(f"{API}/auth/login", json={"email": S["u1"]["email"], "password": "Test@1234"}, timeout=30)
        assert lg.status_code == 200, lg.text

    def test_ticket_endpoint_accepts_category(self):
        r = requests.post(f"{API}/tickets", json={"subject": "TEST_del via ticket", "message": "please delete",
                                                  "category": "account_deletion"}, headers=hdr(S["u3"]["tok"]), timeout=30)
        assert r.status_code in (200, 201), r.text

    def test_deletion_request_after_plain_ticket_still_locks(self):
        # edge: a plain /tickets row with category account_deletion must not stop the lock
        r = requests.post(f"{API}/me/account-deletion", json={"reason": "TEST", "confirm": True}, headers=hdr(S["u3"]["tok"]), timeout=30)
        assert r.status_code == 200, r.text
        assert mdb.users.find_one({"id": S["u3"]["id"]}).get("is_blocked") is True, r.json()


# ---------- BUG 1: admin delete user scoped archive ----------
class TestAdminDelete:
    def test_delete_user_scoped(self, admin_tok):
        # unrelated ticket by u2
        r = requests.post(f"{API}/tickets", json={"subject": "TEST_unrelated", "message": "keep me", "category": "other"},
                          headers=hdr(S["u2"]["tok"]), timeout=30)
        assert r.status_code in (200, 201), r.text
        other_tid = (r.json().get("ticket") or r.json())["id"]
        other_msgs = mdb.ticket_messages.count_documents({"ticket_id": other_tid})
        u3_tids = [t["id"] for t in mdb.tickets.find({"user_id": S["u3"]["id"]}, {"id": 1})]
        assert u3_tids
        t0 = time.time()
        d = requests.delete(f"{API}/admin/users/{S['u3']['id']}", headers=hdr(admin_tok), timeout=60)
        el = time.time() - t0
        assert d.status_code == 200, d.text
        print("delete took", round(el, 2), d.json())
        assert el < 15
        body = d.json()
        assert "cascade" in str(body)
        arc = mdb.deleted_user_archives.find_one({"user_id": S["u3"]["id"]})
        assert arc and arc["data"]["users"][0]["id"] == S["u3"]["id"]
        S.setdefault("archives", []).append(arc["id"])
        assert mdb.users.find_one({"id": S["u3"]["id"]}) is None
        assert mdb.tickets.count_documents({"id": {"$in": u3_tids}}) == 0
        assert mdb.ticket_messages.count_documents({"ticket_id": {"$in": u3_tids}}) == 0
        assert mdb.tickets.find_one({"id": other_tid}) is not None
        assert mdb.ticket_messages.count_documents({"ticket_id": other_tid}) == other_msgs


# ---------- REQ 16/17: festival ----------
class TestFestival:
    @pytest.mark.parametrize("fid", ["deepavali", "ugadi", "independence_day", "ganesh_chaturthi", "dussehra",
                                     "maha_shivaratri", "ramzan", "christmas", "new_year", "sankranti"])
    def test_banner_artwork(self, fid):
        r = requests.get(f"{API}/festival-artwork/{fid}/banner", timeout=60)
        assert r.status_code == 200, f"{fid} {r.status_code}"
        assert r.headers.get("content-type", "").startswith("image/")
        assert len(r.content) > 1000

    def test_banner_text_and_apply(self, admin_tok):
        backup = mdb.settings.find_one({"id": "branding"})
        try:
            t = hdr(admin_tok)
            body = {"festival_id": "deepavali", "title": "TEST Happy Diwali", "subtitle": "TEST sub", "align": "center",
                    "title_size": 22, "height": 160}
            r = requests.put(f"{API}/admin/festival-theme/banner-text", json=body, headers=t, timeout=30)
            assert r.status_code == 200, r.text
            g = requests.get(f"{API}/admin/festival-theme/banner-text", headers=t, timeout=30).json()
            assert g["items"]["deepavali"]["title"] == "TEST Happy Diwali"
            assert g["items"]["deepavali"]["align"] == "center"
            assert requests.put(f"{API}/admin/festival-theme/banner-text", json={**body, "align": "middle"}, headers=t, timeout=30).status_code == 400
            assert requests.put(f"{API}/admin/festival-theme/banner-text", json={**body, "title_color": "red"}, headers=t, timeout=30).status_code == 400
            a = requests.post(f"{API}/admin/festival-theme/apply", json={"festival_id": "deepavali"}, headers=t, timeout=30)
            assert a.status_code == 200, a.text
            fest = a.json().get("festival") or {}
            assert (fest.get("banner_text") or {}).get("title") == "TEST Happy Diwali", a.json()
        finally:
            if backup:
                mdb.settings.replace_one({"_id": backup["_id"]}, backup)


# ---------- DEPLOY FIX: purge gate (destructive call itself NOT executed) ----------
class TestPurge:
    def test_purge_requires_super_admin(self):
        r = requests.post(f"{API}/admin/backups/purge-old?keep=10", headers=hdr(S["u2"]["tok"]), timeout=30)
        assert r.status_code in (401, 403), r.text


# ---------- financial invariant ----------
class TestZFinance:
    def test_finance_unchanged(self):
        assert mdb.transactions.count_documents({}) == S["tx0"]
        assert wallet_sum() == S["w0"]
