"""
L1 Payout Funding & Ledger Integrity verification.

Scenarios:
  A — Static ledger health (inflow ≈ outflow, no unresolved alerts)
  B — Live L1 cycle (signup loop until L1 fires; admin buckets debited; recipient wallet credited; l1_funding txn recorded)
  C — Idempotency (restart backend; backfill must not re-debit)
  D — Ledger alert smoke (endpoint returns dict)
"""
import os
import sys
import time
import json
import random
import string
import subprocess
from typing import Any, Dict, List, Optional, Tuple

import requests

# ----- Configuration -----
BASE = os.environ.get("BACKEND_URL", "").strip()
if not BASE:
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                line = line.strip()
                if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
                    BASE = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    except Exception:
        pass
if not BASE:
    BASE = "http://localhost:8001"
API = BASE.rstrip("/") + "/api"

ADMIN_EMAIL = "admin@app.com"
ADMIN_PASS = "Admin@123"
TESTUSER_EMAIL = "testuser@app.com"
TESTUSER_PASS = "Test@123"

TIMEOUT = 30

results: List[Tuple[str, bool, str]] = []


def log(msg: str):
    print(msg, flush=True)


def record(name: str, ok: bool, details: str = ""):
    status = "PASS" if ok else "FAIL"
    log(f"[{status}] {name}: {details}")
    results.append((name, ok, details))


def login(email: str, password: str) -> Optional[str]:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=TIMEOUT)
    if r.status_code != 200:
        log(f"  login {email} -> {r.status_code} {r.text[:200]}")
        return None
    return r.json().get("access_token") or r.json().get("token")


def headers(tok: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def rand_suffix(n=8) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


log(f"==> API base: {API}")

admin_tok = login(ADMIN_EMAIL, ADMIN_PASS)
if not admin_tok:
    log("FATAL: cannot log in admin")
    sys.exit(1)

testuser_tok = login(TESTUSER_EMAIL, TESTUSER_PASS)
if not testuser_tok:
    log("FATAL: cannot log in testuser")
    sys.exit(1)


def get(path: str, tok: str, params=None):
    return requests.get(f"{API}{path}", headers=headers(tok), params=params, timeout=TIMEOUT)


def post(path: str, tok: Optional[str], body=None):
    h = headers(tok) if tok else {"Content-Type": "application/json"}
    return requests.post(f"{API}{path}", headers=h, json=body or {}, timeout=TIMEOUT)


# SCENARIO A
log("\n========= SCENARIO A: Static ledger health =========")
bd_before = None
try:
    r = get("/admin/system-wallet/breakdown", admin_tok)
    if r.status_code != 200:
        record("A.breakdown_200", False, f"status={r.status_code} body={r.text[:300]}")
    else:
        bd_before = r.json()
        infl = bd_before["inflow"]["total"]
        outfl = bd_before["outflow"]["total"]
        l1d = bd_before["outflow"].get("l1_funding_debit")
        held = bd_before["balance"]["held_total"]
        drift = abs(infl - outfl)
        record(
            "A.1 breakdown.inflow~=outflow",
            drift <= 1.0,
            f"inflow={infl}, outflow={outfl}, drift={drift:.2f}, l1_funding_debit={l1d}, held_total={held}",
        )
except Exception as e:
    record("A.breakdown", False, f"exception {e}")

try:
    r = get("/admin/ledger-alerts", admin_tok)
    if r.status_code != 200:
        record("A.2 ledger-alerts_200", False, f"status={r.status_code}")
    else:
        data = r.json()
        alerts = data.get("alerts", [])
        unresolved_big = [a for a in alerts if not a.get("resolved", False) and abs(a.get("drift", 0)) > 1.0]
        snap = data.get("current") or {}
        record(
            "A.2 no unresolved drift alerts >1",
            len(unresolved_big) == 0,
            f"alerts_total={len(alerts)} unresolved_drift_gt_1={len(unresolved_big)} current_drift={snap.get('drift')}",
        )
except Exception as e:
    record("A.ledger-alerts", False, f"exception {e}")


# SCENARIO D — smoke
log("\n========= SCENARIO D: Ledger alert smoke =========")
try:
    r = get("/admin/ledger-alerts", admin_tok)
    is_dict_or_list = r.status_code == 200 and isinstance(r.json(), (dict, list))
    record("D.1 ledger-alerts returns 200 dict/list", is_dict_or_list,
           f"status={r.status_code} type={type(r.json()).__name__ if r.status_code==200 else 'na'}")
except Exception as e:
    record("D.1 ledger-alerts smoke", False, f"exception {e}")


# SCENARIO B
log("\n========= SCENARIO B: Live L1 cycle =========")

r = get("/auth/me", testuser_tok)
me = r.json() if r.status_code == 200 else {}
testuser_id = me.get("id")
testuser_ref = me.get("referral_code")
testuser_wallet_before = float(me.get("wallet_balance") or 0)
testuser_pending_before = int(me.get("pending_directs") or 0)
log(f"  testuser id={testuser_id} ref={testuser_ref} wallet={testuser_wallet_before} pending_directs={testuser_pending_before}")

r = get("/admin/system-wallet", admin_tok)
admin_wallet_before = r.json() if r.status_code == 200 else {}
buckets_before = (admin_wallet_before.get("buckets") or {})
log(f"  admin buckets BEFORE: {buckets_before}")

r = get("/admin/settings", admin_tok)
settings = r.json() if r.status_code == 200 else {}
directs_required = int(settings.get("directs_required") or 4)
reg_fee = float(settings.get("registration_fee") or 100)
payout_l1 = float(settings.get("payout_l1") or 0)
log(f"  settings: directs_required={directs_required} reg_fee={reg_fee} payout_l1={payout_l1}")


def count_l1_funding_txns() -> Tuple[int, float]:
    r = get("/admin/transactions", admin_tok)
    if r.status_code != 200:
        return -1, 0.0
    items = r.json()
    rows = [t for t in items if t.get("type") == "l1_funding" and t.get("status") == "success"]
    total = sum(float(t.get("amount") or 0) for t in rows)
    return len(rows), total


l1_count_pre, l1_total_pre = count_l1_funding_txns()
log(f"  l1_funding txns BEFORE: count={l1_count_pre} total={l1_total_pre}")

need = max(0, directs_required - testuser_pending_before)
to_create = need + 1 if need > 0 else 1
log(f"  Will create {to_create} fresh signups under testuser (need {need} more to fire L1)")

created_user_ids: List[str] = []
created_emails: List[str] = []

if not testuser_ref:
    record("B.referral_code_present", False, "testuser has no referral_code")
else:
    for i in range(to_create):
        sfx = rand_suffix(6)
        name = f"L1Test {sfx}"
        email = f"l1test_{sfx}@test.app"
        phone = f"9{random.randint(10**8, 10**9 - 1)}"
        password = "Test@1234"

        r = requests.post(f"{API}/auth/register", json={
            "name": name, "email": email, "password": password,
            "phone": phone, "referral_code": testuser_ref,
        }, timeout=TIMEOUT)
        if r.status_code != 200:
            record(f"B.signup_{i+1}", False, f"register {r.status_code} {r.text[:200]}")
            continue
        sub = r.json()
        new_id = (sub.get("user") or {}).get("id") or sub.get("id")
        if not new_id:
            r2 = get("/admin/users", admin_tok)
            for u in (r2.json() if r2.status_code == 200 else []):
                if u.get("email") == email:
                    new_id = u.get("id")
                    break
        created_user_ids.append(new_id)
        created_emails.append(email)

        new_tok = login(email, password)
        if not new_tok:
            record(f"B.login_{i+1}", False, "new user login failed")
            continue
        r = post("/payment/register-fee", new_tok, {})
        if r.status_code not in (200, 201):
            record(f"B.payfee_{i+1}", False, f"register-fee {r.status_code} {r.text[:200]}")
            continue
        r = post(f"/admin/approvals/{new_id}/approve", admin_tok, {})
        if r.status_code != 200:
            record(f"B.approve_{i+1}", False, f"approve {r.status_code} {r.text[:200]}")
            continue
        log(f"  signup #{i+1} done id={new_id} email={email}")

r = get("/auth/me", testuser_tok)
me_after = r.json() if r.status_code == 200 else {}
testuser_wallet_after = float(me_after.get("wallet_balance") or 0)
testuser_pending_after = int(me_after.get("pending_directs") or 0)
log(f"  testuser AFTER: wallet={testuser_wallet_after} pending_directs={testuser_pending_after}")

r = get("/admin/system-wallet", admin_tok)
admin_wallet_after = r.json() if r.status_code == 200 else {}
buckets_after = (admin_wallet_after.get("buckets") or {})
log(f"  admin buckets AFTER: {buckets_after}")

wallet_delta = testuser_wallet_after - testuser_wallet_before
record(
    "B.1 testuser wallet increased",
    wallet_delta > 0,
    f"wallet_delta={wallet_delta:.2f}, payout_l1_gross=₹{payout_l1}",
)
l1_fired = wallet_delta >= (payout_l1 * 0.5)


def b(buckets, key):
    return float(buckets.get(key) or 0)


fr_delta = b(buckets_after, "fee_residual") - b(buckets_before, "fee_residual")
ds_delta = b(buckets_after, "direct_signup") - b(buckets_before, "direct_signup")
rc_delta = b(buckets_after, "referral_commission") - b(buckets_before, "referral_commission")
log(f"  admin bucket deltas: fee_residual={fr_delta:.2f} direct_signup={ds_delta:.2f} referral_commission={rc_delta:.2f}")

# Find sample l1_funding rows for testuser
r = get("/admin/transactions", admin_tok)
new_l1_rows = []
if r.status_code == 200:
    rows = [t for t in r.json() if t.get("type") == "l1_funding" and t.get("status") == "success"]
    new_l1_rows = [t for t in rows if t.get("related_payout_recipient") == testuser_id]
sample_l1 = None
if new_l1_rows:
    sample_l1 = {k: new_l1_rows[0].get(k) for k in
                 ["id", "type", "amount", "source_bucket", "related_signup_id",
                  "related_payout_recipient", "description"]}

record(
    "B.2 admin buckets net-debit when L1 fires",
    (not l1_fired) or (fr_delta + ds_delta + rc_delta < 0),
    f"sum_delta={fr_delta+ds_delta+rc_delta:.2f} l1_fired={l1_fired}",
)

record(
    "B.3 l1_funding txn exists for testuser",
    (not l1_fired) or (len(new_l1_rows) >= 1),
    f"matching_rows={len(new_l1_rows)}; sample={json.dumps(sample_l1) if sample_l1 else 'none'}",
)
if new_l1_rows:
    neg_ok = all(float(t.get("amount") or 0) < 0 for t in new_l1_rows)
    has_src = all(t.get("source_bucket") for t in new_l1_rows)
    has_sig = all(t.get("related_signup_id") for t in new_l1_rows)
    record("B.3b l1_funding rows have negative amount", neg_ok, f"all_negative={neg_ok}")
    record("B.3c l1_funding rows have source_bucket", has_src, f"all_have_source={has_src}")
    record("B.3d l1_funding rows have related_signup_id", has_sig, f"all_have_signup={has_sig}")

r = get("/admin/system-wallet/breakdown", admin_tok)
bd_after = r.json() if r.status_code == 200 else {}
infl_a = bd_after.get("inflow", {}).get("total", 0)
outfl_a = bd_after.get("outflow", {}).get("total", 0)
drift_after = abs(infl_a - outfl_a)
l1d_after = bd_after.get("outflow", {}).get("l1_funding_debit")
infl_b = (bd_before or {}).get("inflow", {}).get("total", 0)
outfl_b = (bd_before or {}).get("outflow", {}).get("total", 0)
drift_before = abs(infl_b - outfl_b)
record(
    "B.4 inflow~=outflow after live L1 cycle",
    drift_after <= 1.0,
    f"BEFORE drift={drift_before:.2f} AFTER drift={drift_after:.2f} "
    f"inflow={infl_a} outflow={outfl_a} l1_funding_debit={l1d_after}"
)


# SCENARIO C — Idempotency
log("\n========= SCENARIO C: Idempotency =========")
l1_count_pre_restart, l1_total_pre_restart = count_l1_funding_txns()
log(f"  l1_funding BEFORE restart: count={l1_count_pre_restart} total={l1_total_pre_restart}")

try:
    res = subprocess.run(["sudo", "supervisorctl", "restart", "backend"],
                         check=False, timeout=30, capture_output=True, text=True)
    log(f"  restart stdout: {res.stdout.strip()}")
    log(f"  restart stderr: {res.stderr.strip()}")
    log("  sleeping 12s for backfill to run")
    time.sleep(12)
except Exception as e:
    log(f"  restart failed: {e}")

# Re-login (token should still work but be safe)
admin_tok2 = None
for _ in range(5):
    admin_tok2 = login(ADMIN_EMAIL, ADMIN_PASS)
    if admin_tok2:
        break
    time.sleep(2)
admin_tok = admin_tok2 or admin_tok

l1_count_post_restart, l1_total_post_restart = count_l1_funding_txns()
log(f"  l1_funding AFTER restart : count={l1_count_post_restart} total={l1_total_post_restart}")

record(
    "C.1 l1_funding count unchanged after restart",
    l1_count_post_restart == l1_count_pre_restart,
    f"before={l1_count_pre_restart} after={l1_count_post_restart}",
)
record(
    "C.2 l1_funding total unchanged after restart",
    abs(l1_total_post_restart - l1_total_pre_restart) < 0.01,
    f"before={l1_total_pre_restart:.2f} after={l1_total_post_restart:.2f}",
)


# Final
log("\n========= SUMMARY =========")
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
log(f"Passed: {passed}/{total}")
for n, ok, d in results:
    log(f"  [{'PASS' if ok else 'FAIL'}] {n}: {d}")

critical_keys = [
    "A.1 breakdown.inflow~=outflow",
    "B.1 testuser wallet increased",
    "B.3 l1_funding txn exists for testuser",
    "B.4 inflow~=outflow after live L1 cycle",
    "C.1 l1_funding count unchanged after restart",
    "C.2 l1_funding total unchanged after restart",
]
crit_pass = all(any(n == k and ok for n, ok, _ in results) for k in critical_keys)
log("")
log(f"L1 minting bug FIXED: {'YES' if crit_pass else 'NO'}")
if not crit_pass:
    log("Reason: one or more critical scenarios failed — see above.")

sys.exit(0 if crit_pass else 1)
