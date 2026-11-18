# Iteration 122 — follow-up fixes: role apply w/o membership (REQ7), deletion lock
# revokes live sessions (REQ11/13), ticket-first deletion still locks, scoped unlock,
# admin-blocked token rejected everywhere, admin delete archive `truncated`, finance invariant.
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


def login(email):
    return requests.post(f"{API}/auth/login", json={"email": email, "password": PW}, timeout=30)


def new_user(key):
    email = f"test_i122_{key}_{RUN}@example.com"
    p = rand_phone()
    r = requests.post(f"{API}/auth/register", json={"name": f"TEST_{key}", "email": email,
                                                    "password": PW, "phone": p}, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    S[key] = {"id": d["user"]["id"], "tok": d["token"], "email": email,
              "refresh": d.get("refresh_token")}
    return S[key]


@pytest.fixture(scope="module", autouse=True)
def guard():
    S["tx0"] = mdb.transactions.count_documents({})
    S["w0"] = wallet_sum()
    yield
    print(f"\nFINANCE tx {S['tx0']}->{mdb.transactions.count_documents({})} wallet {S['w0']}->{wallet_sum()}")
    for k in ("r1", "r2", "d1", "d2", "b1"):
        u = S.get(k)
        if not u:
            continue
        for c in ("vendor_applications", "service_applications", "delivery_partner_applications"):
            mdb[c].delete_many({"user_id": u["id"]})
        tids = [t["id"] for t in mdb.tickets.find({"user_id": u["id"]}, {"id": 1})]
        mdb.ticket_messages.delete_many({"ticket_id": {"$in": tids}})
        mdb.tickets.delete_many({"id": {"$in": tids}})
        mdb.users.delete_one({"id": u["id"]})
    for aid in S.get("archives", []):
        mdb.deleted_user_archives.delete_one({"id": aid})


@pytest.fixture(scope="module")
def admin_tok():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["token"]


# ---------- REQ 7: every role open to a free account ----------
class TestApplyFree:
    def test_register_users(self):
        for k in ("r1", "r2", "d1", "d2", "b1"):
            new_user(k)

    def test_vendor_apply(self):
        r = requests.post(f"{API}/vendor/apply", headers=hdr(S["r1"]["tok"]), timeout=30, json={
            "shop_name": "TEST_i122 Shop", "pincode": "517501", "city": "Tirupati", "state": "Andhra Pradesh",
            "store_address": "TEST street", "location": {"type": "Point", "coordinates": [79.4192, 13.6288]},
            "delivery_radius_km": 5, "delivery_radius_mode": "radius", "delivery_available": True})
        print("vendor", r.status_code, r.text[:200])
        assert "only members" not in r.text.lower() and "membership" not in r.text.lower()
        assert r.status_code == 200, r.text
        assert mdb.vendor_applications.find_one({"user_id": S["r1"]["id"], "status": "pending"})

    def test_service_apply(self):
        r = requests.post(f"{API}/service/apply", headers=hdr(S["r1"]["tok"]), timeout=30, json={
            "service_name": "TEST_i122 plumbing", "service_category": "Plumber", "pincode": "517501",
            "charge": 199, "languages": ["en", "te"]})
        print("service", r.status_code, r.text[:200])
        assert "only members" not in r.text.lower() and "membership" not in r.text.lower()
        assert r.status_code == 200, r.text
        assert mdb.service_applications.find_one({"user_id": S["r1"]["id"], "status": "pending"})

    def test_dp_apply(self):
        r = requests.post(f"{API}/delivery-partner/apply", headers=hdr(S["r2"]["tok"]), timeout=30, json={
            "full_name": "TEST_i122 Rider", "phone": "9876500000", "vehicle_type": "bike",
            "vehicle_number": "AP03AB1234", "delivery_radius_km": 5, "pincodes": ["517501"],
            "city": "Tirupati", "state": "Andhra Pradesh"})
        print("dp", r.status_code, r.text[:200])
        assert "only members" not in r.text.lower() and "membership" not in r.text.lower()
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "pending"


# ---------- REQ 11/13: deletion lock ends live sessions ----------
class TestDeletionLock:
    def test_direct_request_revokes_token(self):
        u = S["d1"]
        assert requests.get(f"{API}/cart", headers=hdr(u["tok"]), timeout=30).status_code == 200
        r = requests.post(f"{API}/me/account-deletion", json={"reason": "TEST", "confirm": True},
                          headers=hdr(u["tok"]), timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["account_locked"] is True
        S["d1_ticket"] = r.json()["ticket"]["id"]
        me = requests.get(f"{API}/auth/me", headers=hdr(u["tok"]), timeout=30)
        cart = requests.get(f"{API}/cart", headers=hdr(u["tok"]), timeout=30)
        print("me", me.status_code, me.text[:120], "cart", cart.status_code)
        assert me.status_code == 403, me.text
        assert cart.status_code == 403, cart.text
        assert login(u["email"]).status_code == 403
        doc = mdb.users.find_one({"id": u["id"]})
        assert doc["active_session_ids"] == [] and doc.get("active_session_id") is None

    def test_refresh_token_rejected_when_locked(self):
        if not S["d1"].get("refresh"):
            pytest.skip("no refresh token on register")
        r = requests.post(f"{API}/auth/refresh", json={"refresh_token": S["d1"]["refresh"]}, timeout=30)
        assert r.status_code in (401, 403), r.text

    def test_cancel_unlocks_and_login_works(self, admin_tok):
        r = requests.post(f"{API}/admin/account-deletion/{S['d1_ticket']}/cancel", headers=hdr(admin_tok), timeout=30)
        assert r.status_code == 200, r.text
        doc = mdb.users.find_one({"id": S["d1"]["id"]})
        assert doc["is_blocked"] is False and doc.get("deletion_ticket_id") is None
        lg = login(S["d1"]["email"])
        assert lg.status_code == 200, lg.text
        assert requests.get(f"{API}/auth/me", headers=hdr(lg.json()["token"]), timeout=30).status_code == 200

    def test_ticket_first_then_request_locks(self):
        u = S["d2"]
        t = requests.post(f"{API}/tickets", json={"subject": "TEST_i122 delete me", "message": "please delete",
                                                  "category": "account_deletion"}, headers=hdr(u["tok"]), timeout=30)
        assert t.status_code in (200, 201), t.text
        r = requests.post(f"{API}/me/account-deletion", json={"confirm": True}, headers=hdr(u["tok"]), timeout=30)
        assert r.status_code == 200, r.text
        assert r.json().get("already_requested") is True and r.json().get("account_locked") is True
        assert mdb.users.find_one({"id": u["id"]})["is_blocked"] is True
        assert requests.get(f"{API}/auth/me", headers=hdr(u["tok"]), timeout=30).status_code == 403
        assert requests.get(f"{API}/cart", headers=hdr(u["tok"]), timeout=30).status_code == 403
        assert login(u["email"]).status_code == 403


# ---------- scoped unlock + admin block everywhere ----------
class TestScopedUnlockAndBlock:
    def test_stale_ticket_does_not_lift_admin_block(self, admin_tok):
        u = S["b1"]
        r = requests.post(f"{API}/me/account-deletion", json={"confirm": True}, headers=hdr(u["tok"]), timeout=30)
        assert r.status_code == 200, r.text
        tid = r.json()["ticket"]["id"]
        assert requests.post(f"{API}/admin/account-deletion/{tid}/cancel", headers=hdr(admin_tok), timeout=30).status_code == 200
        lg = login(u["email"])
        assert lg.status_code == 200, lg.text
        S["b1"]["tok"] = lg.json()["token"]
        b = requests.post(f"{API}/admin/users/{u['id']}/block", json={"reason": "TEST_i122 admin block"},
                          headers=hdr(admin_tok), timeout=30)
        assert b.status_code == 200, b.text
        c = requests.post(f"{API}/admin/account-deletion/{tid}/cancel", headers=hdr(admin_tok), timeout=30)
        print("stale cancel", c.status_code, c.text)
        doc = mdb.users.find_one({"id": u["id"]})
        assert doc["is_blocked"] is True and doc["block_reason"] == "TEST_i122 admin block"
        assert login(u["email"]).status_code == 403

    @pytest.mark.parametrize("method,path", [("GET", "/auth/me"), ("GET", "/cart"), ("GET", "/orders/me"),
                                             ("GET", "/me/account-deletion"), ("GET", "/tickets/me"),
                                             ("GET", "/chat/threads"), ("GET", "/notifications/me")])
    def test_blocked_token_rejected(self, method, path):
        r = requests.request(method, f"{API}{path}", headers=hdr(S["b1"]["tok"]), timeout=30)
        assert r.status_code == 403, f"{path} {r.status_code} {r.text[:150]}"


# ---------- admin delete archive honesty ----------
class TestAdminDeleteArchive:
    def test_delete_has_truncated(self, admin_tok):
        uid = S["b1"]["id"]
        t0 = time.time()
        d = requests.delete(f"{API}/admin/users/{uid}", headers=hdr(admin_tok), timeout=60)
        el = time.time() - t0
        print("delete", d.status_code, round(el, 2))
        assert d.status_code == 200, d.text
        assert el < 10
        arc = mdb.deleted_user_archives.find_one({"user_id": uid})
        assert arc is not None
        S.setdefault("archives", []).append(arc["id"])
        assert "truncated" in arc and isinstance(arc["truncated"], dict), arc.keys()
        assert arc["data"]["users"][0]["id"] == uid
        assert mdb.users.find_one({"id": uid}) is None


class TestZFinance:
    def test_finance_unchanged(self):
        assert mdb.transactions.count_documents({}) == S["tx0"]
        assert wallet_sum() == S["w0"]
