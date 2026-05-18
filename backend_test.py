"""
MLM Engine Option B + Ledger Alert endpoint regression tests.
Runner: python /app/backend_test.py
"""
import os
import sys
import time
import uuid
import json
import requests
from typing import Optional, Dict, Any, List

# ---- Config ----
FRONTEND_ENV_PATH = "/app/frontend/.env"
BASE_URL = None
for line in open(FRONTEND_ENV_PATH).read().splitlines():
    if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
        BASE_URL = line.split("=", 1)[1].strip().strip('"') + "/api"
if not BASE_URL:
    BASE_URL = "https://vendor-network-app-1.preview.emergentagent.com/api"
print(f"BASE_URL: {BASE_URL}")

ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"
TESTUSER_EMAIL = "testuser@app.com"
TESTUSER_PASSWORD = "Test@123"

PASSES: List[str] = []
FAILURES: List[str] = []


def _record(name: str, ok: bool, detail: str = ""):
    bar = "✅" if ok else "❌"
    line = f"{bar} {name}" + (f"  --  {detail}" if detail else "")
    print(line)
    if ok:
        PASSES.append(name)
    else:
        FAILURES.append(f"{name} :: {detail}")


def _req(method: str, path: str, *, token: Optional[str] = None, json_body: Any = None,
         params: Any = None, expect: Optional[int] = None) -> requests.Response:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{BASE_URL}{path}"
    r = requests.request(method, url, headers=headers, json=json_body, params=params, timeout=60)
    return r


# ---- Auth ----
def login(email: str, password: str) -> Optional[str]:
    r = _req("POST", "/auth/login", json_body={"email": email, "password": password})
    if r.status_code != 200:
        print(f"LOGIN FAIL {email}: {r.status_code} {r.text[:200]}")
        return None
    return r.json()["token"]


def register_user(name: str, email: str, password: str, referral_code: Optional[str] = None) -> Optional[Dict[str, Any]]:
    body = {"name": name, "email": email, "password": password}
    if referral_code:
        body["referral_code"] = referral_code
    r = _req("POST", "/auth/register", json_body=body)
    if r.status_code != 200:
        print(f"REGISTER FAIL {email}: {r.status_code} {r.text[:300]}")
        return None
    return r.json()


def get_me(token: str) -> Dict[str, Any]:
    r = _req("GET", "/auth/me", token=token)
    return r.json() if r.status_code == 200 else {}


def pay_register_fee(token: str) -> bool:
    r = _req("POST", "/payment/register-fee", token=token)
    return r.status_code == 200


def approve_user(admin_token: str, user_id: str) -> requests.Response:
    return _req("POST", f"/admin/approvals/{user_id}/approve", token=admin_token)


def get_admin_users(admin_token: str) -> List[Dict[str, Any]]:
    r = _req("GET", "/admin/users", token=admin_token)
    return r.json() if r.status_code == 200 else []


def find_user_by_email(admin_token: str, email: str) -> Optional[Dict[str, Any]]:
    for u in get_admin_users(admin_token):
        if (u.get("email") or "").lower() == email.lower():
            return u
    return None


def get_transactions(admin_token: str, txn_type: Optional[str] = None) -> List[Dict[str, Any]]:
    if txn_type:
        r = _req("GET", "/admin/transactions/filter", token=admin_token, params={"type": txn_type})
    else:
        r = _req("GET", "/admin/transactions", token=admin_token)
    return r.json() if r.status_code == 200 else []


# ─────────────────────────────────────────────────────────────────
# Test main
# ─────────────────────────────────────────────────────────────────
def main():
    # ---- Pre: log in admin + testuser ----
    print("\n── PRE: AUTH ──")
    admin_token = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    if not admin_token:
        print("FATAL: admin login failed.")
        sys.exit(1)
    _record("admin login", True)

    testuser_token = login(TESTUSER_EMAIL, TESTUSER_PASSWORD)
    if not testuser_token:
        print("FATAL: testuser login failed.")
        sys.exit(1)
    _record("testuser login", True)

    testuser_me = get_me(testuser_token)
    testuser_id = testuser_me.get("id")
    testuser_code = testuser_me.get("referral_code")
    testuser_payouts = int(testuser_me.get("payouts_received") or 0)
    print(f"testuser id={testuser_id} code={testuser_code} payouts_received={testuser_payouts}")

    # Settings — fetch directs_required
    r = _req("GET", "/admin/settings", token=admin_token)
    settings = r.json() if r.status_code == 200 else {}
    directs_required = int(settings.get("directs_required") or 4)
    payout_l1 = float(settings.get("payout_l1") or 400)
    print(f"settings: directs_required={directs_required} payout_l1={payout_l1}")
    _record("GET /admin/settings", r.status_code == 200,
            f"status={r.status_code} directs_required={directs_required}")

    # Create finance/non-admin token for C.2 — register a fresh user and use that token
    nonadmin_email = f"nonadmin_{uuid.uuid4().hex[:6]}@test.app"
    nonadmin_reg = register_user("NonAdmin Tester", nonadmin_email, "Tester@123")
    nonadmin_token = nonadmin_reg["token"] if nonadmin_reg else None

    # ──────────────────────────────────────────────────────────────
    # SCENARIO A: per-level payout idempotency
    # ──────────────────────────────────────────────────────────────
    print("\n── SCENARIO A: Per-level payout idempotency ──")
    # Create 2 fresh users sponsored by testuser (so cascade hits testuser → admin chain).
    fresh_users = []
    for i in range(2):
        u_email = f"idem_{uuid.uuid4().hex[:6]}@test.app"
        u_name = f"IdemTest{i+1}"
        reg = register_user(u_name, u_email, "Tester@123", referral_code=testuser_code)
        if not reg:
            _record(f"A: register fresh user {i+1}", False, "register failed")
            continue
        u_token = reg["token"]
        # pay register fee
        if not pay_register_fee(u_token):
            _record(f"A: pay register-fee {u_name}", False)
            continue
        _record(f"A: register + pay fee {u_name}", True, f"email={u_email}")
        fresh_users.append({"name": u_name, "email": u_email, "id": reg["user"]["id"], "token": u_token})

    # Snapshot transactions BEFORE approve so we can diff
    before_txns = get_transactions(admin_token, txn_type="referral_payout")
    before_count = len(before_txns)

    # Approve each user
    for fu in fresh_users:
        r1 = approve_user(admin_token, fu["id"])
        ok1 = r1.status_code == 200
        _record(f"A: approve {fu['name']}", ok1, f"status={r1.status_code} body={r1.text[:120]}")

        # Second approve should be a no-op
        r2 = approve_user(admin_token, fu["id"])
        # endpoint returns 200 with already_approved=True
        body2 = r2.json() if r2.headers.get("content-type","").startswith("application/json") else {}
        is_noop = r2.status_code == 200 and (body2.get("already_approved") is True or body2.get("ok") is True)
        _record(f"A: re-approve {fu['name']} is no-op",
                is_noop, f"status={r2.status_code} body={r2.text[:150]}")

    # Verify: for each signup, each (recipient, level) tuple appears exactly once
    after_txns = get_transactions(admin_token, txn_type="referral_payout")
    new_txns = [t for t in after_txns if t not in before_txns]
    # Filter by source_user_name OR description matching fresh_users names
    for fu in fresh_users:
        # find all referral_payout txns triggered by THIS signup
        related = [t for t in after_txns if (t.get("source_user_name") == fu["name"]) or
                   (fu["name"] in (t.get("description") or ""))]
        # Group by (user_id, level)
        seen = {}
        dup = False
        for t in related:
            key = (t.get("user_id"), t.get("level"))
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > 1:
                dup = True
        _record(f"A: no duplicate (recipient, level) txns for {fu['name']}",
                not dup, f"groups={seen}")

    # ──────────────────────────────────────────────────────────────
    # SCENARIO B: signup spillover fields
    # ──────────────────────────────────────────────────────────────
    print("\n── SCENARIO B: spillover fields on signup ──")
    spill_email = f"spill_{uuid.uuid4().hex[:6]}@test.app"
    spill_name = "Spillover Test"
    spill_reg = register_user(spill_name, spill_email, "Tester@123", referral_code=testuser_code)
    if not spill_reg:
        _record("B: register spillover user", False)
    else:
        spill_user_id = spill_reg["user"]["id"]
        admin_view = find_user_by_email(admin_token, spill_email)
        if not admin_view:
            _record("B: admin can see new user", False)
        else:
            sponsor_id = admin_view.get("sponsor_id")
            ref_owner_id = admin_view.get("referral_owner_id")
            ref_owner_code = admin_view.get("referral_owner_code")
            no_ref = admin_view.get("no_referral_signup")
            print(f"   sponsor_id={sponsor_id}")
            print(f"   referral_owner_id={ref_owner_id}  (testuser_id={testuser_id})")
            print(f"   referral_owner_code={ref_owner_code}  (testuser_code={testuser_code})")
            print(f"   no_referral_signup={no_ref}  testuser_payouts={testuser_payouts}")

            _record("B: referral_owner_id == testuser.id",
                    ref_owner_id == testuser_id,
                    f"got {ref_owner_id} expected {testuser_id}")
            _record("B: referral_owner_code == testuser.referral_code",
                    ref_owner_code == testuser_code,
                    f"got {ref_owner_code} expected {testuser_code}")
            _record("B: sponsor_id is set",
                    bool(sponsor_id), f"sponsor_id={sponsor_id}")
            _record("B: no_referral_signup is False (had real referral)",
                    no_ref is False, f"got {no_ref}")

            # Sub-check: if testuser had payouts_received==0, then no spillover should fire
            # (sponsor_id == referral_owner_id). If >=1, spillover MAY have fired.
            if testuser_payouts == 0:
                _record("B.3: on payouts_received=0, sponsor_id == referral_owner_id (no spillover)",
                        sponsor_id == ref_owner_id,
                        f"sponsor_id={sponsor_id} owner_id={ref_owner_id}")
            else:
                print(f"   NOTE: testuser already has payouts_received={testuser_payouts}; "
                      f"spillover may have fired. Reported field structure is correct regardless.")
                # Still record this as informational PASS as long as fields are set
                _record("B.3: spillover field structure correct (testuser.payouts_received>=1)",
                        bool(sponsor_id) and bool(ref_owner_id),
                        "spillover field structure verified")

    # ──────────────────────────────────────────────────────────────
    # SCENARIO C: Ledger alert endpoints
    # ──────────────────────────────────────────────────────────────
    print("\n── SCENARIO C: Ledger Alert endpoints ──")
    r = _req("GET", "/admin/ledger-alerts", token=admin_token)
    _record("C.1: GET /admin/ledger-alerts (admin) 200", r.status_code == 200,
            f"status={r.status_code}")
    if r.status_code == 200:
        body = r.json()
        # shape: current, alerts[], check_interval_seconds=300, drift_threshold=1.0
        cur = body.get("current") or {}
        cur_keys = set(cur.keys())
        expected_cur_keys = {"inflow", "withdrawals_out", "expected_held", "held", "drift", "checked_at"}
        _record("C.1: current has all required keys",
                expected_cur_keys.issubset(cur_keys),
                f"missing={expected_cur_keys - cur_keys}")
        _record("C.1: alerts is array",
                isinstance(body.get("alerts"), list),
                f"type={type(body.get('alerts')).__name__}")
        _record("C.1: check_interval_seconds == 300",
                body.get("check_interval_seconds") == 300,
                f"got={body.get('check_interval_seconds')}")
        _record("C.1: drift_threshold == 1.0",
                float(body.get("drift_threshold") or 0) == 1.0,
                f"got={body.get('drift_threshold')}")

    # C.2: access gating
    r_anon = _req("GET", "/admin/ledger-alerts")
    _record("C.2: anonymous → 401/403", r_anon.status_code in (401, 403),
            f"status={r_anon.status_code}")

    if nonadmin_token:
        r_nu = _req("GET", "/admin/ledger-alerts", token=nonadmin_token)
        _record("C.2: non-admin user token → 403",
                r_nu.status_code == 403,
                f"status={r_nu.status_code} body={r_nu.text[:120]}")

    # C.3: resolve unknown id -> 404
    fake_alert_id = f"fake-{uuid.uuid4().hex[:8]}"
    r_unk = _req("POST", f"/admin/ledger-alerts/{fake_alert_id}/resolve", token=admin_token)
    _record("C.3: resolve unknown alert id → 404",
            r_unk.status_code == 404,
            f"status={r_unk.status_code} body={r_unk.text[:120]}")
    # C.3b: non-admin → 403
    if nonadmin_token:
        r_unk_nu = _req("POST", f"/admin/ledger-alerts/{fake_alert_id}/resolve", token=nonadmin_token)
        _record("C.3: non-admin POST resolve → 403",
                r_unk_nu.status_code == 403,
                f"status={r_unk_nu.status_code}")

    # ──────────────────────────────────────────────────────────────
    # SCENARIO D: Regression
    # ──────────────────────────────────────────────────────────────
    print("\n── SCENARIO D: Regression of existing flows ──")
    # D.1: system-wallet/breakdown
    r = _req("GET", "/admin/system-wallet/breakdown", token=admin_token)
    ok = r.status_code == 200 and isinstance(r.json(), dict) and "inflow" in r.json() and "outflow" in r.json()
    _record("D.1: GET /admin/system-wallet/breakdown 200 with schema",
            ok, f"status={r.status_code}")

    # D.2: /admin/reconcile-ledgers — the test brief mentioned this path,
    # but the implemented path is /admin/system-wallet/reconcile. Test both.
    r1 = _req("POST", "/admin/reconcile-ledgers", token=admin_token)
    r2 = _req("POST", "/admin/system-wallet/reconcile", token=admin_token)
    _record("D.2: POST /admin/system-wallet/reconcile 200",
            r2.status_code == 200, f"status={r2.status_code} body={r2.text[:150]}")
    if r1.status_code != 200:
        print(f"   NOTE: POST /admin/reconcile-ledgers does NOT exist (status={r1.status_code}). "
              f"The actual path is /admin/system-wallet/reconcile.")

    # D.3: signup with NO referral
    nr_email = f"noref_{uuid.uuid4().hex[:6]}@test.app"
    nr_name = "NoRefTester"
    nr_reg = register_user(nr_name, nr_email, "Tester@123")  # no referral_code
    if not nr_reg:
        _record("D.3: register no-ref user", False)
    else:
        nr_view = find_user_by_email(admin_token, nr_email)
        if not nr_view:
            _record("D.3: admin can see no-ref user", False)
        else:
            print(f"   no-ref: sponsor_id={nr_view.get('sponsor_id')} owner_id={nr_view.get('referral_owner_id')} "
                  f"no_referral_signup={nr_view.get('no_referral_signup')}")
            _record("D.3: no_referral_signup is True",
                    nr_view.get("no_referral_signup") is True,
                    f"got {nr_view.get('no_referral_signup')}")
            _record("D.3: sponsor_id is set (placement)",
                    bool(nr_view.get("sponsor_id")),
                    f"sponsor_id={nr_view.get('sponsor_id')}")
            _record("D.3: referral_owner_id == sponsor_id (no-ref → owner=placement)",
                    nr_view.get("referral_owner_id") == nr_view.get("sponsor_id"),
                    f"sponsor_id={nr_view.get('sponsor_id')} owner_id={nr_view.get('referral_owner_id')}")

    # ──────────────────────────────────────────────────────────────
    # Summary
    # ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print(f"PASSED: {len(PASSES)}   FAILED: {len(FAILURES)}")
    print("=" * 70)
    if FAILURES:
        print("\nFAILURES:")
        for f in FAILURES:
            print(f"  - {f}")
    return len(FAILURES)


if __name__ == "__main__":
    sys.exit(main())
