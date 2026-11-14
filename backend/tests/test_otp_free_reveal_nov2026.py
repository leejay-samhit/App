# Nov-2026: OTPly WhatsApp OTP sign-in, Truecaller removal, free provider phone reveal, no ₹118 gate
import os, uuid, hashlib, secrets, time
from datetime import datetime, timezone, timedelta
import pytest, requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv('/app/frontend/.env')
load_dotenv('/app/backend/.env')
BASE_URL = (os.environ.get('EXPO_BACKEND_URL') or os.environ.get('EXPO_PUBLIC_BACKEND_URL')).rstrip('/')
API = f"{BASE_URL}/api"
db = MongoClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]

ADMIN = ("support@slangcart.com", "3)Ywxtic")
BUYER = ("testbuyer@test.com", "Test@1234")
REAL_SEND_NO = "9999912301"     # only number that triggers a real WhatsApp send
NEW_NO_A = "9999912302"
NEW_NO_B = "9999912303"
RATE_NO = "9999912304"
PROVIDER_ID = "22c44148-a5d3-417b-9c89-4d024c9b504a"
CREATED_USERS = []


def _h(salt, mobile, otp):
    return hashlib.sha256(f"{salt}:{mobile}:{otp}".encode()).hexdigest()


def plant_code(mobile, otp="123456", attempts=0):
    now = datetime.now(timezone.utc)
    salt = secrets.token_hex(16)
    db.otp_codes.delete_many({"mobile": mobile})
    db.otp_codes.insert_one({"mobile": mobile, "otp_hash": _h(salt, mobile, otp), "salt": salt,
                             "purpose": "login", "attempts": attempts, "consumed": False,
                             "created_at": (now - timedelta(seconds=120)).isoformat(),
                             "expires_at": (now + timedelta(seconds=180)).isoformat()})


def login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    return j.get("token") or j.get("access_token")


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    for uid in CREATED_USERS:
        db.users.delete_one({"id": uid, "auth_method": "mobile_otp"})
        db.phone_reveal_invoices.delete_many({"user_id": uid})
        db.sessions.delete_many({"user_id": uid})
    for m in (REAL_SEND_NO, NEW_NO_A, NEW_NO_B, RATE_NO):
        db.otp_codes.delete_many({"mobile": m})
    db.otp_requests.delete_many({"mobile": RATE_NO, "test_seed": True})


# ---- A. OTP send validation ----
class TestOtpSend:
    @pytest.mark.parametrize("bad", ["123", "5999912301", "99999123011", "abcdefghij"])
    def test_invalid_numbers_400(self, bad):
        r = requests.post(f"{API}/auth/otp/send", json={"mobile": bad}, timeout=30)
        assert r.status_code == 400, r.text
        assert "valid" in r.json()["detail"].lower()

    def test_real_send_then_cooldown_and_normalisation(self):
        db.otp_codes.delete_many({"mobile": REAL_SEND_NO})
        r = requests.post(f"{API}/auth/otp/send", json={"mobile": REAL_SEND_NO}, timeout=40)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["sent"] is True and j["expires_in"] == 300 and j["resend_in"] == 60
        row = db.otp_codes.find_one({"mobile": REAL_SEND_NO})
        assert row and set(["otp_hash", "salt"]).issubset(row)
        assert not any(k in row for k in ("otp", "code", "plain"))
        assert len(row["otp_hash"]) == 64
        # cooldown — also proves +91 / 0 / spaced prefixes normalise to the same number
        for variant in (REAL_SEND_NO, "+91" + REAL_SEND_NO, "0" + REAL_SEND_NO, "+91 99999 12301"):
            r2 = requests.post(f"{API}/auth/otp/send", json={"mobile": variant}, timeout=30)
            assert r2.status_code == 429, (variant, r2.text)
            assert "wait" in r2.json()["detail"].lower()

    def test_hourly_rate_limit(self):
        now = datetime.now(timezone.utc).isoformat()
        db.otp_codes.delete_many({"mobile": RATE_NO})
        db.otp_requests.insert_many([{"mobile": RATE_NO, "ip": "", "created_at": now, "test_seed": True} for _ in range(5)])
        r = requests.post(f"{API}/auth/otp/send", json={"mobile": RATE_NO}, timeout=30)
        assert r.status_code == 429, r.text
        assert "hour" in r.json()["detail"].lower()


# ---- A. OTP verify errors ----
class TestOtpVerifyErrors:
    def test_no_code_400(self):
        db.otp_codes.delete_many({"mobile": NEW_NO_B})
        r = requests.post(f"{API}/auth/otp/verify", json={"mobile": NEW_NO_B, "otp": "111111"}, timeout=30)
        assert r.status_code == 400 and "request a new code" in r.json()["detail"].lower()

    def test_wrong_codes_lockout_on_real_row(self):
        row = db.otp_codes.find_one({"mobile": REAL_SEND_NO})
        if not row:
            pytest.skip("real-send row missing")
        msgs = []
        for _ in range(5):
            r = requests.post(f"{API}/auth/otp/verify", json={"mobile": REAL_SEND_NO, "otp": "000000"}, timeout=30)
            assert r.status_code == 400, r.text
            msgs.append(r.json()["detail"])
        print(msgs)
        assert "4 attempts left" in msgs[0] and "1 attempt left" in msgs[3]
        # code must be dead now — even after 5 wrong attempts
        r = requests.post(f"{API}/auth/otp/verify", json={"mobile": REAL_SEND_NO, "otp": "000000"}, timeout=30)
        assert r.status_code in (400, 429), r.text
        print("6th:", r.status_code, r.json()["detail"])
        assert db.otp_codes.count_documents({"mobile": REAL_SEND_NO}) == 0


# ---- B. OTP sign-in end to end ----
class TestOtpSignIn:
    def test_new_number_creates_free_user_and_resign_same_user(self):
        db.users.delete_many({"phone": NEW_NO_A, "auth_method": "mobile_otp"})
        plant_code(NEW_NO_A, "246810")
        r = requests.post(f"{API}/auth/otp/verify", json={"mobile": "+91" + NEW_NO_A, "otp": "246810", "name": "TEST_Otp User"}, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        assert {"token", "refresh_token", "user", "created"} <= set(j)
        assert j["created"] is True
        uid = j["user"]["id"]
        CREATED_USERS.append(uid)
        u = db.users.find_one({"id": uid})
        assert u["registration_paid"] is False and u["approval_status"] == "approved"
        assert u["phone_verified"] is True and u["phone"] == NEW_NO_A
        assert not u.get("sponsor_id") and not u.get("referred_by")
        me = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {j['token']}"}, timeout=30)
        assert me.status_code == 200 and me.json().get("id", me.json().get("user", {}).get("id")) == uid
        # replay of the same code must fail (single use)
        r2 = requests.post(f"{API}/auth/otp/verify", json={"mobile": NEW_NO_A, "otp": "246810"}, timeout=30)
        assert r2.status_code == 400
        # sign in again -> same user
        plant_code(NEW_NO_A, "135790")
        r3 = requests.post(f"{API}/auth/otp/verify", json={"mobile": NEW_NO_A, "otp": "135790"}, timeout=30)
        assert r3.status_code == 200, r3.text
        assert r3.json()["created"] is False and r3.json()["user"]["id"] == uid
        assert db.users.count_documents({"phone": NEW_NO_A}) == 1

    def test_second_brand_new_number_also_creates_user(self):
        """Unique indexes on users.email / users.referral_code must not break a 2nd mobile-only signup."""
        db.users.delete_many({"phone": NEW_NO_B, "auth_method": "mobile_otp"})
        plant_code(NEW_NO_B, "975310")
        r = requests.post(f"{API}/auth/otp/verify", json={"mobile": NEW_NO_B, "otp": "975310"}, timeout=30)
        print(r.status_code, r.text[:300])
        assert r.status_code == 200, r.text
        CREATED_USERS.append(r.json()["user"]["id"])

    def test_blocked_account_refused_403(self):
        u = db.users.find_one({"phone": NEW_NO_A, "auth_method": "mobile_otp"})
        if not u:
            pytest.skip("no TEST otp user")
        db.users.update_one({"id": u["id"]}, {"$set": {"is_blocked": True, "email": "testotpblock@example.com"}})
        try:
            plant_code(NEW_NO_A, "112233")
            r = requests.post(f"{API}/auth/otp/verify", json={"mobile": NEW_NO_A, "otp": "112233"}, timeout=30)
            assert r.status_code == 403, r.text
            d = r.json()["detail"]
            print(d)
            assert "TEST_Otp User" in d and "te***" in d and "testotpblock@example.com" not in d
        finally:
            db.users.update_one({"id": u["id"]}, {"$set": {"is_blocked": False, "email": ""}})


# ---- C/D. Truecaller + ₹118 gate removed ----
class TestRemovedRoutes:
    @pytest.mark.parametrize("method,path", [
        ("get", "/auth/truecaller/availability_status"), ("post", "/auth/truecaller/start"),
        ("post", "/auth/truecaller/verify-sim-back"), ("get", "/sim-binding/status"),
        ("post", "/sim-binding/verify"), ("get", "/admin/sim-binding"),
    ])
    def test_404(self, method, path):
        r = getattr(requests, method)(f"{API}{path}", json={}, timeout=30)
        assert r.status_code == 404, (path, r.status_code)

    def test_signup_gate_status_clean(self):
        tok = login(*BUYER)
        r = requests.get(f"{API}/auth/signup-gate/status", headers={"Authorization": f"Bearer {tok}"}, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        print(j)
        assert "truecaller_available" not in j and "fallback_code" not in j


# ---- E. Free provider phone reveal + chat with no SIM gate ----
class TestFreeReveal:
    def _otp_user_token(self):
        u = db.users.find_one({"phone": NEW_NO_A, "auth_method": "mobile_otp"})
        if not u:
            pytest.skip("no zero-balance TEST user")
        plant_code(NEW_NO_A, "424242")
        r = requests.post(f"{API}/auth/otp/verify", json={"mobile": NEW_NO_A, "otp": "424242"}, timeout=30)
        assert r.status_code == 200
        return r.json()["token"], u["id"]

    def test_reveal_config_zero(self):
        tok = login(*BUYER)
        r = requests.get(f"{API}/services/reveal-config", headers={"Authorization": f"Bearer {tok}"}, timeout=30)
        j = r.json()
        assert r.status_code == 200 and j["fee"] == 0 and j["total"] == 0 and j["free_for_everyone"] is True

    def test_reveal_free_zero_balance_and_chat(self):
        tok, uid = self._otp_user_token()
        H = {"Authorization": f"Bearer {tok}"}
        txn_before = db.transactions.count_documents({})
        r = requests.post(f"{API}/services/{PROVIDER_ID}/reveal-phone", json={}, headers=H, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json().get("provider_phone")
        assert db.users.find_one({"id": uid})["wallet_balance"] == 0
        assert db.transactions.count_documents({}) == txn_before
        assert db.transactions.count_documents({"user_id": uid}) == 0
        # chat: start thread + send message, no SIM gate
        t = requests.post(f"{API}/chat/threads", json={"other_user_id": PROVIDER_ID}, headers=H, timeout=30)
        assert t.status_code == 200, t.text
        tj = t.json()
        tid = tj.get("id") or tj.get("thread", {}).get("id") or tj.get("thread_id")
        m = requests.post(f"{API}/chat/{tid}/messages", json={"text": "TEST_hello from otp user"}, headers=H, timeout=30)
        assert m.status_code == 200, m.text
        with open("/tmp/test_thread_id", "w") as f:
            f.write(tid)

    def test_reveal_403_when_not_shared(self):
        tok, _ = self._otp_user_token()
        prov = db.users.find_one({"id": PROVIDER_ID})
        orig = prov.get("share_phone", "__missing__")
        db.users.update_one({"id": PROVIDER_ID}, {"$set": {"share_phone": False}})
        db.phone_reveal_invoices.delete_many({"user_id": _, "provider_id": PROVIDER_ID})
        try:
            r = requests.post(f"{API}/services/{PROVIDER_ID}/reveal-phone", json={}, headers={"Authorization": f"Bearer {tok}"}, timeout=30)
            assert r.status_code == 403, r.text
        finally:
            if orig == "__missing__":
                db.users.update_one({"id": PROVIDER_ID}, {"$unset": {"share_phone": ""}})
            else:
                db.users.update_one({"id": PROVIDER_ID}, {"$set": {"share_phone": orig}})


# ---- G. Regression ----
class TestRegression:
    def test_admin_and_buyer_login_me(self):
        for creds in (ADMIN, BUYER):
            tok = login(*creds)
            r = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {tok}"}, timeout=30)
            assert r.status_code == 200

    def test_admin_system_wallet(self):
        tok = login(*ADMIN)
        r = requests.get(f"{API}/admin/system-wallet", headers={"Authorization": f"Bearer {tok}"}, timeout=30)
        assert r.status_code == 200, r.text
