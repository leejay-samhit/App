# Iteration 105 — adversarial probes for the registration / Truecaller / payment-choice flow.
# Focus: what test_registration_flow.py missed (bypasses, races, idempotency, takeover shapes).
import base64
import hashlib
import os
import uuid
import concurrent.futures as cf
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient


def _env(path, key):
    for ln in open(path):
        if ln.startswith(key + "="):
            return ln.split("=", 1)[1].strip().strip('"')


BASE = (os.environ.get("EXPO_BACKEND_URL") or _env("/app/frontend/.env", "EXPO_PUBLIC_BACKEND_URL")).rstrip("/") + "/api"
MDB = MongoClient(_env("/app/backend/.env", "MONGO_URL"))[_env("/app/backend/.env", "DB_NAME")]
PW = "Reg@Flow123"
CREATED = []


def make_user(tag):
    import time
    email = f"regflow.it105.{tag}.{uuid.uuid4().hex[:6]}@example.com"
    for _ in range(12):  # register is rate limited 5/min per IP
        r = requests.post(f"{BASE}/auth/register", json={"name": f"TEST It105 {tag}", "email": email,
                                                         "password": PW, "role": "user"}, timeout=30)
        if r.status_code != 429:
            break
        time.sleep(10)
    assert r.status_code in (200, 201), r.text
    CREATED.append(email)
    for _ in range(12):
        lr = requests.post(f"{BASE}/auth/login", json={"email": email, "password": PW}, timeout=30)
        if lr.status_code != 429:
            break
        time.sleep(10)
    tok = lr.json()["token"]
    h = {"Authorization": f"Bearer {tok}", "X-Client-Platform": "android"}
    uid = requests.get(f"{BASE}/auth/me", headers=h, timeout=30).json()["id"]
    return h, uid, email


def rand_phone():
    return "9" + str(uuid.uuid4().int)[:9]


def gate(h, phone):
    return requests.post(f"{BASE}/auth/signup-gate/confirm", json={"phone": phone}, headers=h, timeout=30)


def status(h):
    return requests.get(f"{BASE}/auth/signup-gate/status", headers=h, timeout=30).json()


def mint_state(uid, minutes=5, used=None):
    st = "st_" + uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    MDB.truecaller_states.insert_one({"state": st, "user_id": uid, "code_verifier": "v" * 50,
                                      "purpose": "registration", "created_at": now.isoformat(),
                                      "expires_at": (now + timedelta(minutes=minutes)).isoformat(),
                                      "used_at": used})
    return st


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    ids = [u["id"] for u in MDB.users.find({"email": {"$in": CREATED}}, {"id": 1})]
    MDB.transactions.delete_many({"user_id": {"$in": ids}})
    MDB.truecaller_states.delete_many({"user_id": {"$in": ids}})
    MDB.users.delete_many({"email": {"$in": CREATED}})


# ── Auth on every endpoint
@pytest.mark.parametrize("method,path", [
    ("post", "/auth/truecaller/start"), ("post", "/auth/truecaller/verify"),
    ("get", "/auth/signup-gate/status"), ("post", "/auth/signup-gate/confirm"),
    ("post", "/payment/skip-subscription"), ("post", "/payment/create-order"),
    ("post", "/payment/verify"), ("get", "/payment/config"),
])
def test_requires_auth(method, path):
    r = getattr(requests, method)(f"{BASE}{path}", json={}, timeout=30)
    assert r.status_code in (401, 403), f"{path} -> {r.status_code}"


# ── Truecaller start: verifier never leaves server, client cannot inject state/verifier
def test_start_hides_verifier_and_ignores_client_values():
    h, uid, _ = make_user("start")
    r = requests.post(f"{BASE}/auth/truecaller/start",
                      json={"state": "client-state", "code_verifier": "client-verifier-xyz"}, headers=h, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "code_verifier" not in r.text and "verifier" not in body
    assert body["state"] != "client-state"
    row = MDB.truecaller_states.find_one({"state": body["state"]})
    assert row["user_id"] == uid and row["code_verifier"] != "client-verifier-xyz"
    exp = base64.urlsafe_b64encode(hashlib.sha256(row["code_verifier"].encode()).digest()).decode().rstrip("=")
    assert body["code_challenge"] == exp


# ── Truecaller verify rejections
def test_verify_rejections_never_set_verified():
    h, uid, _ = make_user("tcv")
    _, other, _ = make_user("tcv_other")
    cases = {
        "forged": ("nope-" + uuid.uuid4().hex, 400),
        "other_user": (mint_state(other), 400),
        "expired": (mint_state(uid, minutes=-1), 400),
        "replayed": (mint_state(uid, used=datetime.now(timezone.utc).isoformat()), 400),
        "fake_code": (mint_state(uid), 401),
    }
    for name, (st, want) in cases.items():
        r = requests.post(f"{BASE}/auth/truecaller/verify",
                          json={"state": st, "authorization_code": "fake", "code_verifier": "x",
                                "phone_verified": True, "phone": "9999999999"}, headers=h, timeout=30)
        assert r.status_code == want, f"{name}: {r.status_code} {r.text}"
    u = MDB.users.find_one({"id": uid})
    assert not u.get("phone_verified") and u.get("phone_verified_method") != "truecaller"


# ── Manual fallback is self_declared, not verified
def test_manual_entry_self_declared():
    h, uid, _ = make_user("manual")
    assert status(h)["registration_status"] == "pending_verification"
    r = gate(h, rand_phone())
    assert r.status_code == 200, r.text
    s = status(h)
    assert s["phone_verified"] is False and s["phone_verified_method"] == "self_declared"
    assert s["registration_status"] == "verified" and s["registration_path"] == "undecided"


# ── Duplicate number via gate
def test_duplicate_phone_gate_conflict():
    h1, _, _ = make_user("dup1")
    h2, _, _ = make_user("dup2")
    p = rand_phone()
    assert gate(h1, p).status_code == 200
    c = requests.post(f"{BASE}/auth/signup-gate/check", json={"phone": "+91 " + p}, headers=h2, timeout=30).json()
    assert c["ok"] is False and c["conflict"]["reason"] == "phone_taken"
    assert gate(h2, "0" + p).status_code == 409


# ── RACE: two accounts confirming the same new number concurrently
def test_parallel_phone_link_race():
    users = [make_user(f"race{i}") for i in range(4)]
    p = rand_phone()
    with cf.ThreadPoolExecutor(4) as ex:
        codes = list(ex.map(lambda u: gate(u[0], p).status_code, users))
    owners = MDB.users.count_documents({"phone": p})
    assert owners == 1, f"RACE: {owners} accounts own {p}; statuses={codes}"


# ── Takeover shape: truecaller-verified account must not swap number via the manual gate
def test_verified_account_cannot_swap_via_manual_gate():
    h, uid, _ = make_user("swap")
    orig = rand_phone()
    MDB.users.update_one({"id": uid}, {"$set": {"phone": orig, "phone_verified": True,
                                                "phone_verified_method": "truecaller",
                                                "signup_gate_confirmed_at": datetime.now(timezone.utc).isoformat()}})
    r = gate(h, rand_phone())
    u = MDB.users.find_one({"id": uid})
    assert not (u["phone"] != orig and u.get("phone_verified")), \
        f"verified flag kept while phone swapped via /signup-gate/confirm (HTTP {r.status_code})"


# ── Backend must enforce the gate before payment choices
def test_payment_choices_require_gate():
    h, uid, _ = make_user("nogate")
    r1 = requests.post(f"{BASE}/payment/skip-subscription", headers=h, timeout=30)
    r2 = requests.post(f"{BASE}/payment/create-order", headers=h, timeout=30)
    assert r1.status_code >= 400 and r2.status_code >= 400, \
        f"gate not enforced server-side: skip={r1.status_code} create-order={r2.status_code}"


# ── Legacy instant 'register-fee' must not grant paid status without a payment
def test_legacy_register_fee_bypass():
    h, uid, _ = make_user("legacy")
    gate(h, rand_phone())
    r = requests.post(f"{BASE}/payment/register-fee", headers=h, timeout=30)
    u = MDB.users.find_one({"id": uid})
    assert not u.get("registration_paid"), f"/payment/register-fee marked paid with no payment (HTTP {r.status_code})"


# ── Continue Without Fee: no money rows, no cashback
def test_skip_creates_no_transactions():
    h, uid, _ = make_user("skip")
    gate(h, rand_phone())
    before = MDB.transactions.count_documents({"user_id": uid})
    r = requests.post(f"{BASE}/payment/skip-subscription", headers=h, timeout=30)
    assert r.status_code == 200 and r.json()["subscription_skipped"] is True
    r = requests.post(f"{BASE}/payment/skip-subscription", headers=h, timeout=30)  # repeat
    assert r.status_code == 200
    u = MDB.users.find_one({"id": uid})
    assert u.get("subscription_skipped") and not u.get("registration_paid")
    assert MDB.transactions.count_documents({"user_id": uid}) == before == 0
    assert float(u.get("wallet_balance") or 0) == 0
    s = status(h)
    assert s["registration_status"] == "free_registration" and s["registration_path"] == "free"


# ── Payment config/order uniqueness
def test_config_and_unique_orders():
    h, uid, _ = make_user("cfg")
    gate(h, rand_phone())
    c = requests.get(f"{BASE}/payment/config", headers=h, timeout=30).json()
    assert c["amount"] == 118 and c["amount_paise"] == 11800
    o1 = requests.post(f"{BASE}/payment/create-order", headers=h, timeout=30).json()["order_id"]
    o2 = requests.post(f"{BASE}/payment/create-order", headers=h, timeout=30).json()["order_id"]
    assert o1 != o2
    assert MDB.transactions.count_documents({"user_id": uid, "type": "registration_fee", "status": "created"}) == 1


# ── Verify must reject unknown / other-user order ids
def test_verify_rejects_foreign_order():
    h, uid, _ = make_user("foreign")
    h2, _, _ = make_user("foreign2")
    gate(h, rand_phone()); gate(h2, rand_phone())
    o_other = requests.post(f"{BASE}/payment/create-order", headers=h2, timeout=30).json()["order_id"]
    for oid in ("order_MOCK_made_up", o_other):
        r = requests.post(f"{BASE}/payment/verify", json={"razorpay_order_id": oid, "razorpay_payment_id": "pay_x",
                                                          "razorpay_signature": "sig"}, headers=h, timeout=30)
        assert r.status_code == 400, f"{oid}: {r.status_code}"
    assert not MDB.users.find_one({"id": uid}).get("registration_paid")


# ── Concurrency + repeat callback: exactly one settlement, one cashback, already_processed on repeat
def test_parallel_and_repeat_callbacks():
    h, uid, _ = make_user("par")
    gate(h, rand_phone())
    oid = requests.post(f"{BASE}/payment/create-order", headers=h, timeout=30).json()["order_id"]
    body = {"razorpay_order_id": oid, "razorpay_payment_id": "pay_" + uuid.uuid4().hex[:10], "razorpay_signature": "sig"}
    with cf.ThreadPoolExecutor(6) as ex:
        res = list(ex.map(lambda _: requests.post(f"{BASE}/payment/verify", json=body, headers=h, timeout=60), range(6)))
    codes = [r.status_code for r in res]
    # Exactly ONE call may actually settle; retries of the same order now get a
    # calm 200 {already_processed: true} instead of a 400, which is the right
    # answer for a gateway retry. What must stay singular is the MONEY, which
    # the assertions below check (one fee row, one ₹50 cashback, ₹50 wallet).
    settled_now = [
        r for r in res
        if r.status_code == 200 and not (r.json() or {}).get("already_processed")
    ]
    assert len(settled_now) == 1, f"parallel codes {codes}, settled {len(settled_now)}"
    assert all(c in (200, 400) for c in codes), f"parallel codes {codes}"
    fee_rows = MDB.transactions.count_documents({"user_id": uid, "type": "registration_fee"})
    cb = list(MDB.transactions.find({"user_id": uid, "type": "subscription_cashback"}, {"_id": 0, "amount": 1}))
    u = MDB.users.find_one({"id": uid})
    assert fee_rows == 1, f"fee rows {fee_rows}"
    assert len(cb) == 1 and abs(float(cb[0]["amount"]) - 50) < 0.01, f"cashback rows {cb}"
    assert abs(float(u.get("wallet_balance") or 0) - 50) < 0.01, f"wallet {u.get('wallet_balance')}"
    total_rows = MDB.transactions.count_documents({"user_id": uid})
    rep = requests.post(f"{BASE}/payment/verify", json=body, headers=h, timeout=30)
    assert MDB.transactions.count_documents({"user_id": uid}) == total_rows
    s = status(h)
    assert s["registration_status"] == "payment_success" and s["registration_path"] == "paid"
    assert rep.status_code == 200 and rep.json().get("already_processed") is True, \
        f"repeat callback -> {rep.status_code} {rep.text[:120]} (expected already_processed)"


# ── Free path then subscribe later still works (no double state)
def test_skip_then_pay_later():
    h, uid, _ = make_user("later")
    gate(h, rand_phone())
    requests.post(f"{BASE}/payment/skip-subscription", headers=h, timeout=30)
    oid = requests.post(f"{BASE}/payment/create-order", headers=h, timeout=30).json()["order_id"]
    r = requests.post(f"{BASE}/payment/verify", json={"razorpay_order_id": oid, "razorpay_payment_id": "pay_l",
                                                      "razorpay_signature": "s"}, headers=h, timeout=60)
    assert r.status_code == 200, r.text
    s = status(h)
    assert s["registration_status"] == "payment_success" and s["registration_path"] == "paid"
