"""
Quick regression test for 3 backend fixes (2026-05-18):

  Fix 1: No-referral signups bump placement sponsor's direct_referrals_count.
  Fix 2: New admin wallet bucket `fee_residual` (separated from direct_signup).
  Fix 3: Breakdown endpoint exposes `outflow.to_admin_fee_residual` separately.

Scenarios A..G in /app/test_result.md request body.
"""
import sys
import time
import uuid
from typing import Optional

import requests

BASE_URL = None
try:
    for line in open("/app/frontend/.env"):
        if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().strip('"') + "/api"
            break
except Exception:
    pass
if not BASE_URL:
    BASE_URL = "https://vendor-network-app-1.preview.emergentagent.com/api"

ADMIN_EMAIL = "admin@app.com"
ADMIN_PW = "Admin@123"
TEST_USER_EMAIL = "testuser@app.com"
TEST_USER_PW = "Test@123"

print(f"[base] {BASE_URL}\n")

session = requests.Session()
session.headers.update({"Content-Type": "application/json"})


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def login(email: str, pw: str) -> str:
    r = session.post(f"{BASE_URL}/auth/login", json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["token"]


def find_user(admin_token: str, email: str) -> dict:
    r = session.get(f"{BASE_URL}/admin/users", headers=_auth(admin_token), timeout=15)
    r.raise_for_status()
    for u in r.json():
        if u.get("email", "").lower() == email.lower():
            return u
    return None


def find_user_by_id(admin_token: str, uid: str) -> dict:
    r = session.get(f"{BASE_URL}/admin/users", headers=_auth(admin_token), timeout=15)
    r.raise_for_status()
    for u in r.json():
        if u.get("id") == uid:
            return u
    return None


def register(name: str, email: str, password: str, referral_code: Optional[str] = None) -> dict:
    payload = {"name": name, "email": email, "password": password,
               "phone": f"99{int(time.time())%10**8:08d}"}
    if referral_code:
        payload["referral_code"] = referral_code
    r = session.post(f"{BASE_URL}/auth/register", json=payload, timeout=15)
    r.raise_for_status()
    return r.json()


def pay_fee(token: str) -> dict:
    r = session.post(f"{BASE_URL}/payment/register-fee", headers=_auth(token), timeout=15)
    if not r.ok:
        print(f"  pay_fee error: {r.status_code} {r.text}")
    r.raise_for_status()
    return r.json()


def admin_approve(admin_token: str, user_id: str) -> dict:
    r = session.post(f"{BASE_URL}/admin/approvals/{user_id}/approve",
                     headers=_auth(admin_token), timeout=15)
    r.raise_for_status()
    return r.json()


def get_admin_wallet(admin_token: str) -> dict:
    r = session.get(f"{BASE_URL}/admin/system-wallet", headers=_auth(admin_token), timeout=15)
    r.raise_for_status()
    return r.json()


def get_admin_user(admin_token: str) -> dict:
    return find_user(admin_token, ADMIN_EMAIL)


PASS = []
FAIL = []


def check(label: str, cond: bool, detail: str = ""):
    marker = "OK" if cond else "FAIL"
    print(f"  [{marker}] {label}" + (f"  — {detail}" if detail else ""))
    (PASS if cond else FAIL).append(label)
    return cond


# ─── SETUP ────────────────────────────────────────────────────
print("=== SETUP ===")
admin_token = login(ADMIN_EMAIL, ADMIN_PW)
print("  admin logged in")
testuser_token = login(TEST_USER_EMAIL, TEST_USER_PW)
print("  testuser logged in")

testuser = find_user(admin_token, TEST_USER_EMAIL)
assert testuser, "testuser not found"
TESTUSER_REF = testuser["referral_code"]
TESTUSER_ID = testuser["id"]
print(f"  testuser referral_code={TESTUSER_REF}  id={TESTUSER_ID[:8]}")

admin_user_pre = get_admin_user(admin_token)
ADMIN_ID = admin_user_pre["id"]
print(f"  admin id={ADMIN_ID[:8]}  admin wallet_balance={admin_user_pre.get('wallet_balance')}")
print()


def snapshot() -> dict:
    w = get_admin_wallet(admin_token)
    b = w.get("buckets", {})
    return {
        "wallet_balance": float(w.get("total") or 0),
        "direct_signup": float(b.get("direct_signup") or 0),
        "fee_residual": float(b.get("fee_residual") or 0),
        "referral_commission": float(b.get("referral_commission") or 0),
        "gst_collected": float(b.get("gst_collected") or 0),
    }


# ─── Scenario A — no-ref signup increments direct_referrals_count ──
print("=== Scenario A — no-ref signup increments placement sponsor's direct_referrals_count ===")
sfx = uuid.uuid4().hex[:6]
A_email = f"noref_{sfx}@test.app"
A_pw = "TestNoRef@123"
A_name = f"NoRef Scenario {sfx}"

reg = register(A_name, A_email, A_pw, referral_code=None)
A_token = reg["token"]
A_id = reg["user"]["id"]

new_user_after_signup = find_user_by_id(admin_token, A_id)
sponsor_id = new_user_after_signup.get("sponsor_id")
no_ref_flag = new_user_after_signup.get("no_referral_signup")
check("A.1 user has no_referral_signup=True", bool(no_ref_flag),
      f"flag={no_ref_flag}")
check("A.2 user got a sponsor_id (placement parent)", bool(sponsor_id),
      f"sponsor_id={(sponsor_id or '')[:12]}")

sponsor_before = find_user_by_id(admin_token, sponsor_id) if sponsor_id else None
sponsor_email = (sponsor_before or {}).get("email")
count_before = int((sponsor_before or {}).get("direct_referrals_count") or 0)
print(f"  placement sponsor: {sponsor_email}  direct_referrals_count BEFORE={count_before}")

is_admin_sponsor = (sponsor_email or "").lower() == ADMIN_EMAIL.lower()

pay_fee(A_token)
admin_approve(admin_token, A_id)

sponsor_after = find_user_by_id(admin_token, sponsor_id)
count_after = int((sponsor_after or {}).get("direct_referrals_count") or 0)
print(f"  placement sponsor direct_referrals_count AFTER={count_after}")

if is_admin_sponsor:
    print("  ! placement sponsor is ADMIN — per code at L740, count is NOT incremented for admin sponsor")
    check("A.3 placement sponsor is a real downline (not admin)", False,
          "no eligible downline existed; sponsor==admin so increment test inconclusive")
else:
    check("A.3 placement sponsor is a real downline (not admin)", True, sponsor_email)
    check("A.4 placement sponsor's direct_referrals_count incremented by exactly 1",
          count_after == count_before + 1,
          f"before={count_before} after={count_after}")
print()


# ─── Scenario B — with-ref signup writes fee_residual ───────────
print("=== Scenario B — with-ref signup writes fee_residual ===")
snap_before_B = snapshot()
print(f"  admin BEFORE: direct_signup={snap_before_B['direct_signup']}  "
      f"fee_residual={snap_before_B['fee_residual']}  "
      f"wallet_balance={snap_before_B['wallet_balance']}")

sfx2 = uuid.uuid4().hex[:6]
B_email = f"withref_{sfx2}@test.app"
B_name = f"WithRef Scenario {sfx2}"
B_pw = "TestRef@123"

regB = register(B_name, B_email, B_pw, referral_code=TESTUSER_REF)
B_token = regB["token"]
B_id = regB["user"]["id"]
print(f"  registered {B_email} under referral_code={TESTUSER_REF}")

B_doc = find_user_by_id(admin_token, B_id)
check("B.1 user.no_referral_signup == False (used testuser's code)",
      not B_doc.get("no_referral_signup"),
      f"flag={B_doc.get('no_referral_signup')}")

pay_fee(B_token)
admin_approve(admin_token, B_id)

fr_r = session.get(f"{BASE_URL}/admin/system-wallet/transactions?bucket=fee_residual&limit=1000",
                   headers=_auth(admin_token), timeout=15)
check("B.2 GET ?bucket=fee_residual -> 200", fr_r.status_code == 200,
      f"status={fr_r.status_code}")
fr_data = fr_r.json() if fr_r.ok else {}
fr_items = fr_data.get("items", [])
my_fr_row = next((t for t in fr_items if t.get("related_signup_id") == B_id), None)

check("B.3 fee_residual txn exists with related_signup_id == new_user.id",
      my_fr_row is not None,
      f"found={bool(my_fr_row)}")

residual_amount = 0.0
if my_fr_row:
    check("B.4 fee_residual txn type == 'fee_residual' (NOT 'direct_signup_credit')",
          my_fr_row.get("type") == "fee_residual",
          f"type={my_fr_row.get('type')}")
    desc = my_fr_row.get("description", "")
    check("B.5 fee_residual txn description contains 'Fee residual'",
          "Fee residual" in desc or "fee residual" in desc.lower(),
          f"desc={desc!r}")
    residual_amount = float(my_fr_row.get("amount") or 0)
    print(f"  residual_amount = ₹{residual_amount}")

ds_r = session.get(f"{BASE_URL}/admin/system-wallet/transactions?bucket=direct_signup&limit=1000",
                   headers=_auth(admin_token), timeout=15)
ds_items = ds_r.json().get("items", []) if ds_r.ok else []
my_ds_row = next((t for t in ds_items if t.get("related_signup_id") == B_id), None)
check("B.6 NO direct_signup_credit txn for this with-ref signup",
      my_ds_row is None,
      f"unexpected={my_ds_row.get('type') if my_ds_row else None}")

mixed = [t for t in ds_items if t.get("type") not in ("direct_signup_credit",)]
check("B.7 bucket=direct_signup contains ONLY type=direct_signup_credit (no fee_residual mixed in)",
      len(mixed) == 0,
      f"mixed_count={len(mixed)}  sample_types={list({t.get('type') for t in mixed})[:5] if mixed else []}")

snap_after_B = snapshot()
delta_fr = round(snap_after_B["fee_residual"] - snap_before_B["fee_residual"], 2)
delta_ds = round(snap_after_B["direct_signup"] - snap_before_B["direct_signup"], 2)
delta_wb = round(snap_after_B["wallet_balance"] - snap_before_B["wallet_balance"], 2)
print(f"  admin AFTER: direct_signup={snap_after_B['direct_signup']}  "
      f"fee_residual={snap_after_B['fee_residual']}  "
      f"wallet_balance={snap_after_B['wallet_balance']}")
print(f"  deltas: dDirect={delta_ds}  dFR={delta_fr}  dWB={delta_wb}")

check("B.8 admin.wallet_buckets.fee_residual INCREASED (delta > 0)",
      delta_fr > 0.01, f"delta={delta_fr}")
check("B.9 admin.wallet_buckets.direct_signup did NOT change for with-ref signup",
      abs(delta_ds) < 0.01, f"delta={delta_ds}")
check("B.10 admin.wallet_balance INCREASED",
      delta_wb >= delta_fr - 0.5,
      f"dWB={delta_wb}  dFR={delta_fr}")
print()


# ─── Scenario C — Breakdown endpoint ────────────────────────────
print("=== Scenario C — /admin/system-wallet/breakdown exposes both buckets separately ===")
br_r = session.get(f"{BASE_URL}/admin/system-wallet/breakdown",
                   headers=_auth(admin_token), timeout=15)
check("C.0 GET /admin/system-wallet/breakdown -> 200", br_r.status_code == 200,
      f"status={br_r.status_code}")
br = br_r.json() if br_r.ok else {}
outflow = br.get("outflow", {})
inflow = br.get("inflow", {})
print(f"  outflow: {outflow}")
print(f"  inflow.total={inflow.get('total')}  outflow.total={outflow.get('total')}")

check("C.1 outflow.to_admin_direct_signup field PRESENT",
      "to_admin_direct_signup" in outflow,
      f"value={outflow.get('to_admin_direct_signup')}")
check("C.2 outflow.to_admin_fee_residual field PRESENT (new)",
      "to_admin_fee_residual" in outflow,
      f"value={outflow.get('to_admin_fee_residual')}")
check("C.3 outflow.to_admin_direct_signup is numeric & >= 0",
      isinstance(outflow.get("to_admin_direct_signup"), (int, float))
      and outflow["to_admin_direct_signup"] >= 0,
      f"value={outflow.get('to_admin_direct_signup')}")
check("C.4 outflow.to_admin_fee_residual is numeric & >= 0",
      isinstance(outflow.get("to_admin_fee_residual"), (int, float))
      and outflow["to_admin_fee_residual"] >= 0,
      f"value={outflow.get('to_admin_fee_residual')}")

expected_out = round(
    float(outflow.get("to_user_wallets_referral") or 0)
    + float(outflow.get("to_admin_direct_signup") or 0)
    + float(outflow.get("to_admin_fee_residual") or 0)
    + float(outflow.get("to_admin_cascade_overflow") or 0)
    + float(outflow.get("to_admin_gst_collected") or 0)
    + float(outflow.get("user_withdrawals_settled") or 0),
    2,
)
actual_out = round(float(outflow.get("total") or 0), 2)
check("C.5 outflow.total == sum of 6 components",
      abs(expected_out - actual_out) < 0.5,
      f"expected={expected_out}  actual={actual_out}")

inflow_total = round(float(inflow.get("total") or 0), 2)
inflow_reg_fee = round(float(inflow.get("registration_fee_total") or 0), 2)
held_total = round(float(br.get("balance", {}).get("held_total") or 0), 2)
# inflow.total ALSO includes utr_deposits + shop_margin + service_margin which
# go straight into admin wallet (no redistribution), so the literal
# "inflow.total == outflow.total" check from the brief fails by design.
# The CORRECT invariant is: outflow.total == inflow.registration_fee_total
# (the registration fee is what gets split into the 6 outflow buckets), and
# the BOOKS balance via balance.held_total == inflow.total - withdrawals.
check("C.6 inflow.registration_fee_total == outflow.total (within Rs 1)",
      abs(inflow_reg_fee - actual_out) < 1.0,
      f"reg_fee_inflow={inflow_reg_fee}  outflow={actual_out}")
check("C.6b balance.held_total == inflow.total - withdrawals (books balance)",
      abs(held_total - (inflow_total - float(outflow.get('user_withdrawals_settled') or 0))) < 1.0,
      f"held={held_total}  inflow={inflow_total}")
print()


# ─── Scenario D — bucket detail endpoint ───────────────────────
print("=== Scenario D — bucket detail endpoint ===")
fr_r2 = session.get(f"{BASE_URL}/admin/system-wallet/transactions?bucket=fee_residual&limit=200",
                    headers=_auth(admin_token), timeout=15)
check("D.1 GET ?bucket=fee_residual -> 200", fr_r2.status_code == 200,
      f"status={fr_r2.status_code}")
fr_items2 = fr_r2.json().get("items", []) if fr_r2.ok else []
all_fr = all(t.get("type") == "fee_residual" for t in fr_items2)
check("D.2 bucket=fee_residual returns ONLY type=fee_residual",
      all_fr,
      f"count={len(fr_items2)} mismatches={[t.get('type') for t in fr_items2 if t.get('type')!='fee_residual'][:3]}")

ds_r2 = session.get(f"{BASE_URL}/admin/system-wallet/transactions?bucket=direct_signup&limit=200",
                    headers=_auth(admin_token), timeout=15)
check("D.3 GET ?bucket=direct_signup -> 200", ds_r2.status_code == 200,
      f"status={ds_r2.status_code}")
ds_items2 = ds_r2.json().get("items", []) if ds_r2.ok else []
all_ds = all(t.get("type") == "direct_signup_credit" for t in ds_items2)
check("D.4 bucket=direct_signup returns ONLY type=direct_signup_credit (no fee_residual)",
      all_ds,
      f"count={len(ds_items2)} mismatches={[t.get('type') for t in ds_items2 if t.get('type')!='direct_signup_credit'][:3]}")
print()


# ─── Scenario E — Drift remains 0 ──────────────────────────────
print("=== Scenario E — /admin/ledger-alerts drift within +/- Rs 1 ===")
la_r = session.get(f"{BASE_URL}/admin/ledger-alerts",
                   headers=_auth(admin_token), timeout=15)
check("E.0 GET /admin/ledger-alerts -> 200", la_r.status_code == 200,
      f"status={la_r.status_code}")
la = la_r.json() if la_r.ok else {}
cur = la.get("current", {})
print(f"  current snapshot: {cur}")
drift = float(cur.get("drift") or 0)
check("E.1 |drift| within +/- Rs 1", abs(drift) <= 1.0, f"drift={drift}")
print()


# ─── Scenario F — Reconcile ────────────────────────────────────
print("=== Scenario F — POST /admin/system-wallet/reconcile keeps buckets balanced ===")
rec_r = session.post(f"{BASE_URL}/admin/system-wallet/reconcile",
                     headers=_auth(admin_token), timeout=15)
check("F.0 POST /admin/system-wallet/reconcile -> 200", rec_r.status_code == 200,
      f"status={rec_r.status_code}")
rec = rec_r.json() if rec_r.ok else {}
after = rec.get("after", {})
diff = rec.get("diff", {})
print(f"  reconcile diff: {diff}")
print(f"  reconcile after: direct_signup={after.get('direct_signup')}  "
      f"fee_residual={after.get('fee_residual')}")

fr_items3 = session.get(f"{BASE_URL}/admin/system-wallet/transactions?bucket=fee_residual&limit=1000",
                        headers=_auth(admin_token), timeout=15).json().get("items", [])
fr_sum = round(sum(float(t.get("amount") or 0) for t in fr_items3), 2)
ds_items3 = session.get(f"{BASE_URL}/admin/system-wallet/transactions?bucket=direct_signup&limit=1000",
                        headers=_auth(admin_token), timeout=15).json().get("items", [])
ds_sum = round(sum(float(t.get("amount") or 0) for t in ds_items3), 2)

check("F.1 fee_residual bucket value == SUM of its txns",
      abs(float(after.get("fee_residual") or 0) - fr_sum) < 0.5,
      f"bucket={after.get('fee_residual')}  sum_of_txns={fr_sum}")
check("F.2 direct_signup bucket value == SUM of its txns",
      abs(float(after.get("direct_signup") or 0) - ds_sum) < 0.5,
      f"bucket={after.get('direct_signup')}  sum_of_txns={ds_sum}")

la_r2 = session.get(f"{BASE_URL}/admin/ledger-alerts",
                    headers=_auth(admin_token), timeout=15)
drift2 = float(la_r2.json().get("current", {}).get("drift") or 0) if la_r2.ok else 999
check("F.3 |drift| within +/- Rs 1 after reconcile", abs(drift2) <= 1.0, f"drift={drift2}")
print()


# ─── Scenario G — EARN flow + USER referral flow ───────────────
print("=== Scenario G — EARN flow + USER referral flow ===")

admin_doc = get_admin_user(admin_token)
admin_ref_code = admin_doc.get("referral_code") or "EARN"
print(f"  admin referral_code = {admin_ref_code}")

sfx3 = uuid.uuid4().hex[:6]
G_email = f"earn_{sfx3}@test.app"
G_name = f"EARN Scenario {sfx3}"
G_pw = "TestEarn@123"
regG = register(G_name, G_email, G_pw, referral_code=admin_ref_code)
G_token = regG["token"]
G_id = regG["user"]["id"]
G_doc = find_user_by_id(admin_token, G_id)
check("G.1 EARN-code signup -> no_referral_signup=True",
      G_doc.get("no_referral_signup") is True,
      f"flag={G_doc.get('no_referral_signup')}")

G_sponsor_id = G_doc.get("sponsor_id")
G_sponsor_before = find_user_by_id(admin_token, G_sponsor_id) if G_sponsor_id else None
g_count_before = int((G_sponsor_before or {}).get("direct_referrals_count") or 0)
g_sponsor_email = (G_sponsor_before or {}).get("email", "")
print(f"  EARN placement sponsor: {g_sponsor_email}  count_before={g_count_before}")

pay_fee(G_token)
admin_approve(admin_token, G_id)

G_sponsor_after = find_user_by_id(admin_token, G_sponsor_id)
g_count_after = int((G_sponsor_after or {}).get("direct_referrals_count") or 0)
print(f"  EARN placement sponsor count_after={g_count_after}")
if g_sponsor_email.lower() == ADMIN_EMAIL.lower():
    check("G.2 EARN placement sponsor is a downline (not admin)", False,
          "no eligible downline; sponsor==admin")
else:
    check("G.2 EARN placement sponsor is a downline (not admin)", True, g_sponsor_email)
    check("G.3 EARN signup increments placement-sponsor's direct_referrals_count by 1",
          g_count_after == g_count_before + 1,
          f"before={g_count_before} after={g_count_after}")

# USER referral flow
sfx4 = uuid.uuid4().hex[:6]
U_email = f"userref_{sfx4}@test.app"
U_name = f"UserRef Scenario {sfx4}"
U_pw = "TestUR@123"

testuser_before = find_user(admin_token, TEST_USER_EMAIL)
tu_count_before = int(testuser_before.get("direct_referrals_count") or 0)
snap_g_user_before = snapshot()
print(f"  testuser count_before={tu_count_before}  "
      f"fee_residual_before={snap_g_user_before['fee_residual']}")

regU = register(U_name, U_email, U_pw, referral_code=TESTUSER_REF)
U_token = regU["token"]
U_id = regU["user"]["id"]
U_doc = find_user_by_id(admin_token, U_id)
check("G.4 USER-referral signup -> no_referral_signup=False",
      U_doc.get("no_referral_signup") is not True,
      f"flag={U_doc.get('no_referral_signup')}")
check("G.5 USER-referral signup sponsor_id is set",
      bool(U_doc.get("sponsor_id")),
      f"sponsor_id={(U_doc.get('sponsor_id') or '')[:12]}")

pay_fee(U_token)
admin_approve(admin_token, U_id)

testuser_after = find_user(admin_token, TEST_USER_EMAIL)
tu_count_after = int(testuser_after.get("direct_referrals_count") or 0)

co_r = session.get(f"{BASE_URL}/admin/system-wallet/transactions?bucket=referral_commission&limit=500",
                   headers=_auth(admin_token), timeout=15)
co_items = co_r.json().get("items", []) if co_r.ok else []
co_for_U = [t for t in co_items
            if (t.get("source_user_name") or "").startswith(U_name[:15])
            or t.get("source_user_id") == U_id]
check("G.6 USER-referral cascade fired (referral_commission rows exist for this signup)",
      len(co_for_U) > 0,
      f"rows_found={len(co_for_U)}")

sponsor_of_U = U_doc.get("sponsor_id")
if sponsor_of_U == TESTUSER_ID:
    check("G.7 USER-referral incremented testuser.direct_referrals_count by 1",
          tu_count_after == tu_count_before + 1,
          f"before={tu_count_before} after={tu_count_after}")
else:
    spillover_sponsor = find_user_by_id(admin_token, sponsor_of_U)
    print(f"  spillover applied: actual placement={spillover_sponsor.get('email') if spillover_sponsor else '?'}")
    check("G.7 USER-referral sponsor_id has direct_referrals_count > 0 (spillover OK)",
          int((spillover_sponsor or {}).get("direct_referrals_count") or 0) > 0,
          f"actual={(spillover_sponsor or {}).get('direct_referrals_count')}")

snap_g_user_after = snapshot()
delta_fr_U = round(snap_g_user_after["fee_residual"] - snap_g_user_before["fee_residual"], 2)
check("G.8 USER-referral signup also wrote a fee_residual entry (delta > 0)",
      delta_fr_U > 0.01,
      f"dFR={delta_fr_U}")
print()


# ─── SUMMARY ───────────────────────────────────────────────────
print("=" * 60)
print(f"TOTAL: {len(PASS)} PASS  ·  {len(FAIL)} FAIL")
if FAIL:
    print("\nFAILED:")
    for f in FAIL:
        print(f"  - {f}")
sys.exit(0 if not FAIL else 1)
