"""Iteration 106 — adversarial probes of the registration/payment hardening.

Written after the external review of iteration 105. Everything here hits the
running backend over HTTP the way a real client (or attacker) would.
Sync style (requests + threads) to match the other suites in this folder.
"""
import os
import random
import string
import uuid
import concurrent.futures as cf

import pytest
import requests
from pymongo import MongoClient

BASE = os.environ.get("PROBE_BASE", "http://localhost:8001/api")
TIMEOUT = 30


def _env(path, key):
    for ln in open(path):
        if ln.startswith(key + "="):
            return ln.split("=", 1)[1].strip().strip('"')
    raise KeyError(key)


MDB = MongoClient(_env("/app/backend/.env", "MONGO_URL"))[_env("/app/backend/.env", "DB_NAME")]
CREATED: list = []


def rnd(n: int = 7) -> str:
    return "".join(random.choice(string.ascii_lowercase) for _ in range(n))


def rnd_phone() -> str:
    """9xxxxxxxxx, kept clear of the seeded fixture numbers."""
    return "9" + "".join(random.choice("0123456789") for _ in range(9))


def make_user() -> dict:
    """Seed the account straight into Mongo and mint its token.

    /auth/register is rate limited to 5/min per IP (deliberately), and these
    probes need ~20 accounts, so going through HTTP would mean minutes of
    sleeping. The account shape is identical to what register writes.
    """
    import sys
    sys.path.insert(0, "/app/backend")
    from core.security import create_access_token, hash_password

    uid = str(uuid.uuid4())
    sid = str(uuid.uuid4())
    email = f"adv_{rnd()}@example.com"
    MDB.users.insert_one({
        "id": uid,
        "name": "Adversarial Probe",
        "email": email,
        "password": hash_password("Adv@Probe123"),
        "role": "user",
        "registration_paid": False,
        "approval_status": "pending",
        "active_session_ids": [sid],
        "referral_code": f"ADV{rnd(5).upper()}",
    })
    CREATED.append(uid)
    token = create_access_token(uid, email, "user", sid)
    return {"id": uid, "email": email, "token": token,
            "h": {"Authorization": f"Bearer {token}", "X-Client-Platform": "android"}}


def teardown_module(_module=None):
    if CREATED:
        MDB.users.delete_many({"id": {"$in": CREATED}})


def confirm_phone(u: dict, phone: str):
    return requests.post(f"{BASE}/auth/signup-gate/confirm", timeout=TIMEOUT,
                         json={"phone": phone}, headers=u["h"])


def me(u: dict) -> dict:
    r = requests.get(f"{BASE}/auth/me", timeout=TIMEOUT, headers=u["h"])
    assert r.status_code == 200, r.text[:200]
    return r.json()


# ─────────────────────────────── the five fixes ───────────────────────────────

def test_legacy_register_fee_endpoint_is_gone():
    u = make_user()
    r = requests.post(f"{BASE}/payment/register-fee", timeout=TIMEOUT, json={}, headers=u["h"])
    assert r.status_code == 404, f"register-fee still answers {r.status_code}: {r.text[:200]}"
    assert me(u).get("registration_paid") in (False, None)


def test_payment_routes_refuse_an_unverified_account():
    """No phone on file -> every registration-completing route must say 403."""
    u = make_user()
    for path, body in (
        ("/payment/skip-subscription", {}),
        ("/payment/create-order", {}),
        ("/payment/verify", {"razorpay_order_id": "order_fake",
                             "razorpay_payment_id": "pay_fake",
                             "razorpay_signature": "sig_fake"}),
    ):
        r = requests.post(f"{BASE}{path}", timeout=TIMEOUT, json=body, headers=u["h"])
        assert r.status_code == 403, f"{path} -> {r.status_code} {r.text[:160]}"

    body = me(u)
    assert body.get("registration_paid") in (False, None)
    assert body.get("subscription_active") in (False, None)


def test_one_number_cannot_be_claimed_by_two_accounts_in_parallel():
    """The unique index + 409 handling must survive a genuine race."""
    phone = rnd_phone()
    users = [make_user() for _ in range(5)]
    with cf.ThreadPoolExecutor(max_workers=5) as ex:
        results = list(ex.map(lambda u: confirm_phone(u, phone), users))
    codes = [r.status_code for r in results]
    assert codes.count(200) <= 1, f"more than one account won the number: {codes}"
    assert 200 in codes, f"nobody got the number: {codes}"

    owners = sum(1 for u in users if (me(u).get("phone") or "").endswith(phone[-10:]))
    assert owners == 1, f"{owners} accounts hold the same number"


def test_number_already_taken_is_refused_sequentially_too():
    phone = rnd_phone()
    first, second = make_user(), make_user()
    assert confirm_phone(first, phone).status_code == 200
    r = confirm_phone(second, phone)
    assert r.status_code == 409, f"second claim -> {r.status_code} {r.text[:160]}"
    assert not (me(second).get("phone") or "")


def test_phone_format_variants_cannot_dodge_the_unique_index():
    """+91 / 0-prefix / spaced forms all normalise to the same 10 digits."""
    phone = rnd_phone()
    first = make_user()
    assert confirm_phone(first, phone).status_code == 200
    for variant in (f"+91{phone}", f"0{phone}", f"+91 {phone[:5]} {phone[5:]}", f" {phone} "):
        other = make_user()
        r = confirm_phone(other, variant)
        assert r.status_code == 409, f"variant {variant!r} -> {r.status_code} {r.text[:120]}"


def test_a_self_declared_number_is_never_labelled_truecaller():
    u = make_user()
    assert confirm_phone(u, rnd_phone()).status_code == 200
    st = requests.get(f"{BASE}/auth/signup-gate/status", timeout=TIMEOUT, headers=u["h"]).json()
    assert st.get("required") is False
    assert st.get("phone_verified_method") == "self_declared"
    assert st.get("phone_verified") is not True


# ───────────────────────────── payment security ─────────────────────────────

def test_callback_for_an_order_we_never_created_is_refused():
    u = make_user()
    assert confirm_phone(u, rnd_phone()).status_code == 200
    r = requests.post(f"{BASE}/payment/verify", timeout=TIMEOUT, headers=u["h"], json={
        "razorpay_order_id": "order_NEVER_CREATED_123",
        "razorpay_payment_id": "pay_madeup_123",
        "razorpay_signature": "deadbeef",
    })
    assert r.status_code in (400, 401, 503), r.text[:200]
    assert me(u).get("registration_paid") in (False, None)


def test_one_user_cannot_settle_another_users_order():
    victim, attacker = make_user(), make_user()
    assert confirm_phone(victim, rnd_phone()).status_code == 200
    assert confirm_phone(attacker, rnd_phone()).status_code == 200

    order = requests.post(f"{BASE}/payment/create-order", timeout=TIMEOUT, json={}, headers=victim["h"])
    if order.status_code == 503:
        pytest.skip("online payment switched off in this environment")
    assert order.status_code == 200, order.text[:200]
    oid = order.json()["order_id"]

    r = requests.post(f"{BASE}/payment/verify", timeout=TIMEOUT, headers=attacker["h"], json={
        "razorpay_order_id": oid,
        "razorpay_payment_id": "pay_stolen_123",
        "razorpay_signature": "deadbeef",
    })
    assert r.status_code in (400, 401, 403), f"attacker settled victim's order: {r.status_code}"
    assert me(attacker).get("registration_paid") in (False, None)


def test_free_path_grants_no_payment_dependent_benefit():
    u = make_user()
    assert confirm_phone(u, rnd_phone()).status_code == 200
    r = requests.post(f"{BASE}/payment/skip-subscription", timeout=TIMEOUT, json={}, headers=u["h"])
    assert r.status_code == 200, r.text[:200]

    body = me(u)
    assert body.get("registration_paid") in (False, None), "free path must not mark paid"
    assert body.get("subscription_active") in (False, None), "free path must not open the subscription"

    w = requests.get(f"{BASE}/wallet/summary", timeout=TIMEOUT, headers=u["h"])
    if w.status_code == 200:
        bal = w.json()
        total = float(bal.get("balance") or bal.get("available") or 0)
        assert total == 0, f"free account already holds wallet money: {bal}"

    wd = requests.post(f"{BASE}/withdrawals/request", timeout=TIMEOUT,
                       json={"amount": 100}, headers=u["h"])
    assert wd.status_code != 200, f"free account could request a withdrawal: {wd.text[:160]}"


# ───────────────────────────── truecaller surface ─────────────────────────────

def test_truecaller_routes_require_authentication():
    for path, method, body in (
        ("/auth/truecaller/availability", "GET", None),
        ("/auth/truecaller/start", "POST", {}),
        ("/auth/truecaller/verify", "POST",
         {"authorization_code": "x", "state": "y", "code_verifier": "z"}),
    ):
        if method == "GET":
            r = requests.get(f"{BASE}{path}", timeout=TIMEOUT)
        else:
            r = requests.post(f"{BASE}{path}", timeout=TIMEOUT, json=body)
        assert r.status_code in (401, 403), f"{path} open to anonymous: {r.status_code}"


def test_forged_truecaller_state_and_code_are_refused():
    u = make_user()
    r = requests.post(f"{BASE}/auth/truecaller/verify", timeout=TIMEOUT, headers=u["h"], json={
        "authorization_code": "totally-made-up",
        "state": "state-we-never-issued",
        "code_verifier": "verifier-we-never-issued",
    })
    assert r.status_code in (400, 401, 403, 503), r.text[:200]
    assert me(u).get("phone_verified") in (False, None)


def test_truecaller_bogus_code_is_never_accepted():
    u = make_user()
    start = requests.post(f"{BASE}/auth/truecaller/start", timeout=TIMEOUT, json={}, headers=u["h"])
    if start.status_code != 200:
        pytest.skip(f"start unavailable here ({start.status_code})")
    data = start.json()
    st = data.get("state")
    assert st
    for _ in range(2):
        r = requests.post(f"{BASE}/auth/truecaller/verify", timeout=TIMEOUT, headers=u["h"], json={
            "authorization_code": "bogus", "state": st,
            "code_verifier": data.get("code_verifier", "x"),
        })
        assert r.status_code != 200, "a bogus code was accepted"
    assert me(u).get("phone_verified") in (False, None)
