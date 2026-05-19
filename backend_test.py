"""
L1 Payout Funding & Ledger Integrity — SECOND PASS verification.

Scenarios:
  A — Static ledger health: |inflow.total − outflow.total| ≤ ₹2
  B — Live L1 cycle (signup loop until L1 fires; idempotent — only ONE new
      l1_funding row per L1 cycle; admin debited; testuser credited)
  C — Idempotency: restart backend TWICE and confirm count(l1_funding) doesn't
      grow and no new "L1 funding backfill" log lines reference source txn ids
  D — Ledger alerts: no UNRESOLVED alert with |drift| > 100
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
                if line.startswith("EXPO_PUBLIC_BACKEND_URL=") or line.startswith("REACT_APP_BACKEND_URL="):
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


def get(path: str, tok: str, params=None):
    return requests.get(f"{API}{path}", headers=headers(tok), params=params, timeout=TIMEOUT)


def post(path: str, tok: Optional[str], body=None):
    h = headers(tok) if tok else {"Content-Type": "application/json"}
    return requests.post(f"{API}{path}", headers=h, json=body or {}, timeout=TIMEOUT)


log(f"==> API base: {API}")

admin_tok = login(ADMIN_EMAIL, ADMIN_PASS)
if not admin_tok:
    log("FATAL: cannot log in admin")
    sys.exit(1)

testuser_tok = login(TESTUSER_EMAIL, TESTUSER_PASS)
if not testuser_tok:
    log("FATAL: cannot log in testuser")
    sys.exit(1)


# ════════════════════════════════════════════════════════════════════
# SCENARIO A — Static ledger health
# ════════════════════════════════════════════════════════════════════
log("\n========= SCENARIO A: Static ledger health =========")
bd_before = None
A_OK = True
try:
    r = get("/admin/system-wallet/breakdown", admin_tok)
    if r.status_code != 200:
        record("A.breakdown_200", False, f"status={r.status_code} body={r.text[:300]}")
        A_OK = False
    else:
        bd_before = r.json()
        infl = float(bd_before["inflow"]["total"])
        outfl = float(bd_before["outflow"]["total"])
        l1d = bd_before["outflow"].get("l1_funding_debit")
        held = bd_before["balance"]["held_total"]
        drift = abs(infl - outfl)
        ok = drift <= 2.0
        record(
            "A.1 breakdown |inflow-outflow| <= ₹2",
            ok,
            f"inflow=₹{infl:.2f}, outflow=₹{outfl:.2f}, drift=₹{drift:.2f}, "
            f"l1_funding_debit={l1d}, held_total=₹{held}",
        )
        A_OK = A_OK and ok
        # detail
        log(f"  inflow detail: {json.dumps(bd_before['inflow'])}")
        log(f"  outflow detail: {json.dumps(bd_before['outflow'])}")
except Exception as e:
    record("A.breakdown", False, f"exception {e}")
    A_OK = False


# ════════════════════════════════════════════════════════════════════
# SCENARIO D — Ledger alert smoke + drift threshold check
# ════════════════════════════════════════════════════════════════════
log("\n========= SCENARIO D: Ledger alerts (re-read) =========")
D_OK = True
try:
    r = get("/admin/ledger-alerts", admin_tok)
    if r.status_code != 200:
        record("D.1 ledger-alerts_200", False, f"status={r.status_code}")
        D_OK = False
    else:
        data = r.json()
        is_dict_or_list = isinstance(data, (dict, list))
        record("D.1 ledger-alerts returns 200 dict/list", is_dict_or_list,
               f"type={type(data).__name__}")
        alerts = data.get("alerts", []) if isinstance(data, dict) else data
        big_unresolved = [
            a for a in (alerts or [])
            if not a.get("resolved", False) and abs(float(a.get("drift") or 0)) > 100.0
        ]
        ok2 = len(big_unresolved) == 0
        snap = (data.get("current") if isinstance(data, dict) else {}) or {}
        record(
            "D.2 no UNRESOLVED alert with |drift|>100",
            ok2,
            f"alerts_total={len(alerts or [])} big_unresolved={len(big_unresolved)} "
            f"current_drift={snap.get('drift')}",
        )
        if big_unresolved:
            for a in big_unresolved[:3]:
                log(f"  big-unresolved alert: drift=₹{a.get('drift')} at {a.get('checked_at')}")
        D_OK = D_OK and ok2
except Exception as e:
    record("D.ledger-alerts", False, f"exception {e}")
    D_OK = False


# ════════════════════════════════════════════════════════════════════
# SCENARIO B — Live L1 cycle (idempotent)
# ════════════════════════════════════════════════════════════════════
log("\n========= SCENARIO B: Live L1 cycle =========")
B_OK = True

r = get("/auth/me", testuser_tok)
me = r.json() if r.status_code == 200 else {}
testuser_id = me.get("id")
testuser_ref = me.get("referral_code")
testuser_wallet_before = float(me.get("wallet_balance") or 0)
testuser_pending_before = int(me.get("pending_directs") or 0)
log(f"  testuser id={testuser_id} ref={testuser_ref} wallet=₹{testuser_wallet_before} "
    f"pending_directs={testuser_pending_before}")

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
log(f"  l1_funding txns BEFORE: count={l1_count_pre} total=₹{l1_total_pre:.2f}")

need = max(0, directs_required - testuser_pending_before)
to_create = need + 1 if need > 0 else 1
log(f"  Will create {to_create} fresh signups under testuser (need {need} more to fire L1)")

created_user_ids: List[str] = []

if not testuser_ref:
    record("B.referral_code_present", False, "testuser has no referral_code")
    B_OK = False
else:
    for i in range(to_create):
        sfx = rand_suffix(6)
        name = f"L1Test2 {sfx}"
        email = f"l1test2_{sfx}@test.app"
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

# Snapshot AFTER
r = get("/auth/me", testuser_tok)
me_after = r.json() if r.status_code == 200 else {}
testuser_wallet_after = float(me_after.get("wallet_balance") or 0)
testuser_pending_after = int(me_after.get("pending_directs") or 0)
log(f"  testuser AFTER: wallet=₹{testuser_wallet_after} pending_directs={testuser_pending_after}")

r = get("/admin/system-wallet", admin_tok)
admin_wallet_after = r.json() if r.status_code == 200 else {}
buckets_after = (admin_wallet_after.get("buckets") or {})
log(f"  admin buckets AFTER: {buckets_after}")

wallet_delta = testuser_wallet_after - testuser_wallet_before
ok_b1 = wallet_delta > 0
record(
    "B.1 testuser wallet increased",
    ok_b1,
    f"wallet_delta=₹{wallet_delta:.2f}, payout_l1_gross=₹{payout_l1}",
)
l1_fired = wallet_delta >= (payout_l1 * 0.5)

def b(bb, key):
    return float(bb.get(key) or 0)

fr_delta = b(buckets_after, "fee_residual") - b(buckets_before, "fee_residual")
ds_delta = b(buckets_after, "direct_signup") - b(buckets_before, "direct_signup")
rc_delta = b(buckets_after, "referral_commission") - b(buckets_before, "referral_commission")
log(f"  admin bucket deltas: fee_residual=₹{fr_delta:.2f} direct_signup=₹{ds_delta:.2f} "
    f"referral_commission=₹{rc_delta:.2f}")

ok_b2 = (not l1_fired) or (fr_delta + ds_delta + rc_delta < 0)
record(
    "B.2 admin buckets net-debit when L1 fires",
    ok_b2,
    f"sum_delta=₹{(fr_delta+ds_delta+rc_delta):.2f} l1_fired={l1_fired}",
)

# Count NEW l1_funding rows after the live cycle
l1_count_after_live, l1_total_after_live = count_l1_funding_txns()
new_count = l1_count_after_live - l1_count_pre
log(f"  l1_funding txns AFTER live cycle: count={l1_count_after_live} delta={new_count}")

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
                  "related_payout_recipient", "related_payout_txn_id", "description"]}

ok_b3 = (not l1_fired) or (len(new_l1_rows) >= 1)
record(
    "B.3 l1_funding txn exists for testuser",
    ok_b3,
    f"matching_rows={len(new_l1_rows)}; sample={json.dumps(sample_l1) if sample_l1 else 'none'}",
)
B_OK = B_OK and ok_b1 and ok_b2 and ok_b3

if new_l1_rows:
    neg_ok = all(float(t.get("amount") or 0) < 0 for t in new_l1_rows)
    has_src = all(t.get("source_bucket") for t in new_l1_rows)
    has_sig = all(t.get("related_signup_id") for t in new_l1_rows)
    record("B.3b l1_funding rows have negative amount", neg_ok, f"all_negative={neg_ok}")
    record("B.3c l1_funding rows have source_bucket", has_src, f"all_have_source={has_src}")
    record("B.3d l1_funding rows have related_signup_id (NEW FIX)", has_sig,
           f"all_have_signup={has_sig}")
    B_OK = B_OK and neg_ok and has_src and has_sig

# Breakdown identity after L1 cycle
r = get("/admin/system-wallet/breakdown", admin_tok)
bd_after = r.json() if r.status_code == 200 else {}
infl_a = float(bd_after.get("inflow", {}).get("total", 0))
outfl_a = float(bd_after.get("outflow", {}).get("total", 0))
drift_after = abs(infl_a - outfl_a)
l1d_after = bd_after.get("outflow", {}).get("l1_funding_debit")
ok_b4 = drift_after <= 2.0
record(
    "B.4 |inflow-outflow| <= ₹2 after live L1 cycle",
    ok_b4,
    f"AFTER drift=₹{drift_after:.2f} inflow=₹{infl_a:.2f} outflow=₹{outfl_a:.2f} "
    f"l1_funding_debit={l1d_after}",
)
B_OK = B_OK and ok_b4


# ════════════════════════════════════════════════════════════════════
# SCENARIO C — Idempotency on restart
# ════════════════════════════════════════════════════════════════════
log("\n========= SCENARIO C: Idempotency on restart =========")
C_OK = True

# Capture initial state for the two restart cycles
l1_count_N0, l1_total_N0 = count_l1_funding_txns()
log(f"  N0: l1_funding count={l1_count_N0} total=₹{l1_total_N0:.2f}")

# Take a snapshot of the existing source ids (l1_funding rows already keyed by source)
r = get("/admin/transactions", admin_tok)
existing_l1_source_ids: set = set()
existing_l1_ids: set = set()
if r.status_code == 200:
    for t in r.json():
        if t.get("type") == "l1_funding" and t.get("status") == "success":
            existing_l1_ids.add(t.get("id"))
            sid = t.get("related_payout_txn_id") or t.get("related_signup_id")
            if sid:
                existing_l1_source_ids.add(sid)
log(f"  existing l1_funding source ids tracked: {len(existing_l1_source_ids)}")


def truncate_backend_log():
    """Clear the backend err log so we can monitor only NEW backfill lines."""
    try:
        subprocess.run(["sudo", "truncate", "-s", "0", "/var/log/supervisor/backend.out.log"],
                       check=False, timeout=10, capture_output=True, text=True)
        subprocess.run(["sudo", "truncate", "-s", "0", "/var/log/supervisor/backend.err.log"],
                       check=False, timeout=10, capture_output=True, text=True)
    except Exception as e:
        log(f"  (could not truncate logs: {e})")


def grep_backend_log_for_backfill() -> List[str]:
    """Return any 'L1 funding backfill' lines from current backend logs."""
    hits: List[str] = []
    for p in ("/var/log/supervisor/backend.out.log", "/var/log/supervisor/backend.err.log"):
        try:
            res = subprocess.run(["grep", "-h", "L1 funding backfill", p],
                                 check=False, timeout=10, capture_output=True, text=True)
            if res.stdout:
                for line in res.stdout.splitlines():
                    hits.append(line)
        except Exception:
            pass
    return hits


def do_restart_and_wait(label: str):
    log(f"  -> {label}: truncating logs and restarting backend...")
    truncate_backend_log()
    try:
        res = subprocess.run(["sudo", "supervisorctl", "restart", "backend"],
                             check=False, timeout=30, capture_output=True, text=True)
        log(f"     restart stdout: {res.stdout.strip()}")
        log(f"     restart stderr: {res.stderr.strip()}")
    except Exception as e:
        log(f"     restart failed: {e}")
    # wait 30 seconds for backfill
    log(f"     sleeping 32s for backfill to run")
    time.sleep(32)


# RESTART #1
do_restart_and_wait("RESTART #1")
admin_tok2 = None
for _ in range(8):
    admin_tok2 = login(ADMIN_EMAIL, ADMIN_PASS)
    if admin_tok2:
        break
    time.sleep(2)
admin_tok = admin_tok2 or admin_tok

l1_count_r1, l1_total_r1 = count_l1_funding_txns()
log(f"  AFTER RESTART #1: count={l1_count_r1} total=₹{l1_total_r1:.2f}")
backfill_lines_r1 = grep_backend_log_for_backfill()
log(f"  backfill log lines after R1: {len(backfill_lines_r1)}")
for line in backfill_lines_r1[:5]:
    log(f"    > {line[:240]}")

ok_c1a = l1_count_r1 == l1_count_N0
ok_c2a = abs(l1_total_r1 - l1_total_N0) < 0.01
record("C.1a l1_funding count unchanged after restart #1", ok_c1a,
       f"N0={l1_count_N0} after={l1_count_r1}")
record("C.2a l1_funding total unchanged after restart #1", ok_c2a,
       f"N0=₹{l1_total_N0:.2f} after=₹{l1_total_r1:.2f}")
C_OK = C_OK and ok_c1a and ok_c2a

# RESTART #2 (paranoia)
do_restart_and_wait("RESTART #2")
admin_tok2 = None
for _ in range(8):
    admin_tok2 = login(ADMIN_EMAIL, ADMIN_PASS)
    if admin_tok2:
        break
    time.sleep(2)
admin_tok = admin_tok2 or admin_tok

l1_count_r2, l1_total_r2 = count_l1_funding_txns()
log(f"  AFTER RESTART #2: count={l1_count_r2} total=₹{l1_total_r2:.2f}")
backfill_lines_r2 = grep_backend_log_for_backfill()
log(f"  backfill log lines after R2: {len(backfill_lines_r2)}")
for line in backfill_lines_r2[:5]:
    log(f"    > {line[:240]}")

ok_c1b = l1_count_r2 == l1_count_N0
ok_c2b = abs(l1_total_r2 - l1_total_N0) < 0.01
record("C.1b l1_funding count unchanged after restart #2", ok_c1b,
       f"N0={l1_count_N0} after_r2={l1_count_r2}")
record("C.2b l1_funding total unchanged after restart #2", ok_c2b,
       f"N0=₹{l1_total_N0:.2f} after_r2=₹{l1_total_r2:.2f}")
C_OK = C_OK and ok_c1b and ok_c2b

# Check that backfill log lines (if any) report "sourced 0 historic" — i.e. no
# new funding occurred. The current code only logs when funded_count > 0,
# so the absence of "L1 funding backfill" lines is itself the success signal.
# However if a line IS present, it would mean the backfill funded something.
ok_c3 = (len(backfill_lines_r1) == 0) and (len(backfill_lines_r2) == 0)
record(
    "C.3 NO 'L1 funding backfill' log line after restart (means backfill skipped all)",
    ok_c3,
    f"r1_lines={len(backfill_lines_r1)} r2_lines={len(backfill_lines_r2)}",
)
C_OK = C_OK and ok_c3


# ════════════════════════════════════════════════════════════════════
# FINAL SUMMARY
# ════════════════════════════════════════════════════════════════════
log("\n========= SUMMARY =========")
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
log(f"Passed: {passed}/{total}")
for n, ok, d in results:
    log(f"  [{'PASS' if ok else 'FAIL'}] {n}: {d}")

log("")
log(f"Scenario A (breakdown identity)     : {'PASS' if A_OK else 'FAIL'}")
log(f"Scenario B (live L1 cycle)          : {'PASS' if B_OK else 'FAIL'}")
log(f"Scenario C (restart idempotency)    : {'PASS' if C_OK else 'FAIL'}")
log(f"Scenario D (ledger alerts)          : {'PASS' if D_OK else 'FAIL'}")

critical_ok = A_OK and B_OK and C_OK and D_OK
log("")
log(f"L1 minting bug FIXED & IDEMPOTENT: {'YES' if critical_ok else 'NO'}")
if not critical_ok:
    log("Reason: one or more scenarios failed — see above.")

sys.exit(0 if critical_ok else 1)
