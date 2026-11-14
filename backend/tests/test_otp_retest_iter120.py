# Iter-120 retest: multi mobile signups (partial email index), register w/o invite, takeover guard, complete-profile
import os, uuid, hashlib, secrets
from datetime import datetime, timezone, timedelta
import pytest, requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv('/app/frontend/.env')
load_dotenv('/app/backend/.env')
BASE_URL = (os.environ.get('EXPO_BACKEND_URL') or os.environ.get('EXPO_PUBLIC_BACKEND_URL')).rstrip('/')
API = f"{BASE_URL}/api"
db = MongoClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]

NEW_NOS = ["9999912305", "9999912306", "9999912307"]
LEGACY_NO = "9999912308"
MOBILE_ONLY_NO = "9999912309"
RUN = uuid.uuid4().hex[:6]
CREATED = []          # user ids created by this run
STATE = {}


def _h(salt, mobile, otp):
    return hashlib.sha256(f"{salt}:{mobile}:{otp}".encode()).hexdigest()


def plant(mobile, otp="123456"):
    now = datetime.now(timezone.utc)
    salt = secrets.token_hex(16)
    db.otp_codes.delete_many({"mobile": mobile})
    db.otp_codes.insert_one({"mobile": mobile, "otp_hash": _h(salt, mobile, otp), "salt": salt,
                             "purpose": "login", "attempts": 0, "consumed": False,
                             "created_at": (now - timedelta(seconds=90)).isoformat(),
                             "expires_at": (now + timedelta(seconds=200)).isoformat()})


def verify(mobile, otp="123456", **extra):
    plant(mobile, otp)
    return requests.post(f"{API}/auth/otp/verify", json={"mobile": mobile, "otp": otp, **extra}, timeout=30)


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    for uid in CREATED:
        db.users.delete_one({"id": uid})
        db.sessions.delete_many({"user_id": uid})
        db.login_history.delete_many({"user_id": uid})
    for m in NEW_NOS + [LEGACY_NO, MOBILE_ONLY_NO]:
        db.otp_codes.delete_many({"mobile": m})


# ---- 1. Three brand-new mobile signups in a row ----
class TestThreeSignups:
    def test_three_new_accounts(self):
        ids, codes = set(), set()
        for m in NEW_NOS:
            assert db.users.count_documents({"phone": m}) == 0
            r = verify(m)
            print(m, r.status_code, r.text[:200])
            assert r.status_code == 200, r.text
            j = r.json()
            assert j["created"] is True and j["needs_profile"] is True
            uid = j["user"]["id"]
            CREATED.append(uid)
            u = db.users.find_one({"id": uid})
            assert "email" not in u
            assert u["registration_paid"] is False and u["approval_status"] == "approved"
            assert not u.get("sponsor_id") and not u.get("referred_by")
            assert u.get("referral_code")
            ids.add(uid); codes.add(u["referral_code"])
            STATE.setdefault("tokens", []).append(j["token"])
        assert len(ids) == 3 and len(codes) == 3

    def test_email_still_unique_on_register(self):
        email = f"test_dup_{RUN}@example.com"
        p = {"name": "TEST_Dup", "email": email, "password": "Test@1234", "referral_code": "BOGUS999"}
        r1 = requests.post(f"{API}/auth/register", json=p, timeout=30)
        assert r1.status_code == 200, r1.text   # stale referral_code ignored
        uid = r1.json()["user"]["id"]; CREATED.append(uid)
        u = db.users.find_one({"id": uid})
        assert not u.get("referred_by") and not u.get("sponsor_id")
        STATE["email_user"] = (email, uid)
        r2 = requests.post(f"{API}/auth/register", json={**p, "email": email.upper()}, timeout=30)
        print("dup:", r2.status_code, r2.text)
        assert 400 <= r2.status_code < 500


# ---- 5. Takeover guard ----
class TestTakeover:
    def test_legacy_unverified_with_password_409(self):
        email = f"test_legacy_{RUN}@example.com"
        r = requests.post(f"{API}/auth/register", json={"name": "TEST_Legacy", "email": email,
                          "password": "Test@1234", "phone": LEGACY_NO}, timeout=30)
        assert r.status_code == 200, r.text
        uid = r.json()["user"]["id"]; CREATED.append(uid)
        assert not db.users.find_one({"id": uid}).get("phone_verified")
        sess_before = list(db.users.find_one({"id": uid}).get("active_session_ids") or [])
        v = verify(LEGACY_NO)
        print("409:", v.status_code, v.text)
        assert v.status_code == 409
        body = v.text
        assert email not in body and "token" not in v.json()
        assert "te***" in body or "*" in body
        assert list(db.users.find_one({"id": uid}).get("active_session_ids") or []) == sess_before
        STATE["legacy"] = uid

    def test_legacy_after_verified_signs_in(self):
        uid = STATE.get("legacy") or pytest.skip("no legacy")
        db.users.update_one({"id": uid}, {"$set": {"phone_verified": True}})
        v = verify(LEGACY_NO)
        assert v.status_code == 200, v.text
        assert v.json()["user"]["id"] == uid and v.json()["created"] is False

    def test_mobile_only_unverified_signs_in(self):
        uid = str(uuid.uuid4())
        db.users.insert_one({"id": uid, "name": "TEST_MobileOnly", "phone": MOBILE_ONLY_NO, "role": "user",
                             "referral_code": "TST" + RUN.upper(), "wallet_balance": 0.0,
                             "is_blocked": False, "created_at": datetime.now(timezone.utc).isoformat()})
        CREATED.append(uid)
        v = verify(MOBILE_ONLY_NO)
        assert v.status_code == 200, v.text
        assert v.json()["user"]["id"] == uid
        assert db.users.find_one({"id": uid})["phone_verified"] is True


# ---- 6. complete-profile ----
class TestCompleteProfile:
    def _h(self):
        toks = STATE.get("tokens") or pytest.skip("no tokens")
        return {"Authorization": f"Bearer {toks[0]}"}

    def test_short_name_400(self):
        r = requests.post(f"{API}/auth/otp/complete-profile", json={"name": "A"}, headers=self._h(), timeout=30)
        assert r.status_code == 400, r.text

    def test_email_clash_409(self):
        for e in ("testbuyer@test.com", "TestBuyer@Test.com"):
            r = requests.post(f"{API}/auth/otp/complete-profile", json={"name": "TEST_Prof", "email": e},
                              headers=self._h(), timeout=30)
            assert r.status_code == 409, (e, r.text)

    def test_invalid_email_format(self):
        r = requests.post(f"{API}/auth/otp/complete-profile", json={"name": "TEST_Prof", "email": "notanemail"},
                          headers=self._h(), timeout=30)
        print("invalid email ->", r.status_code, r.text[:200])
        STATE["invalid_email_status"] = r.status_code
        # reset in case it was accepted
        db.users.update_one({"id": CREATED[0]}, {"$unset": {"email": ""}})
        assert r.status_code in (400, 422), "complete-profile accepts malformed email"

    def test_save_ok_and_needs_profile_false(self):
        email = f"test_prof_{RUN}@example.com"
        r = requests.post(f"{API}/auth/otp/complete-profile", json={"name": "TEST_Prof Name", "email": email},
                          headers=self._h(), timeout=30)
        assert r.status_code == 200, r.text
        u = db.users.find_one({"id": CREATED[0]})
        assert u["name"] == "TEST_Prof Name" and u["email"] == email and u["profile_complete"] is True
        v = verify(NEW_NOS[0])
        assert v.status_code == 200 and v.json()["needs_profile"] is False and v.json()["created"] is False

    def test_name_only_second_user(self):
        toks = STATE.get("tokens")
        r = requests.post(f"{API}/auth/otp/complete-profile", json={"name": "TEST_NameOnly"},
                          headers={"Authorization": f"Bearer {toks[1]}"}, timeout=30)
        assert r.status_code == 200, r.text
        assert "email" not in db.users.find_one({"id": CREATED[1]})
