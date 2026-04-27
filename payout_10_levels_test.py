"""
Test the NEW 10-level payout structure in NetworkPay backend.

Scenarios A-H from review request.
"""
import os
import sys
import time
import uuid
import requests
from typing import Dict, Any, List, Optional

BASE = "https://network-pay-1.preview.emergentagent.com"
API = BASE + "/api"
ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"

PASS = 0
FAIL = 0
FAILURES: List[str] = []
CREATED_USER_IDS: List[str] = []


def log(label: str, ok: bool, detail: str = ""):
    global PASS, FAIL
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {label}" + (f" -- {detail}" if detail else ""))
    if ok:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(f"{label} :: {detail}")


def check(label: str, cond: bool, detail: str = ""):
    log(label, bool(cond), detail)
    return bool(cond)


def admin_login() -> str:
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json()["token"]


def auth_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


DEFAULTS = {
    "payout_l1": 400.0,
    "payout_l2": 100.0,
    "payout_l3": 50.0,
    "payout_l4": 25.0,
    "payout_l5": 15.0,
    "payout_l6": 10.0,
    "payout_l7": 8.0,
    "payout_l8": 5.0,
    "payout_l9": 3.0,
    "payout_l10": 2.0,
}


def get_settings(t: str) -> Dict[str, Any]:
    r = requests.get(f"{API}/admin/settings", headers=auth_headers(t), timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def put_settings(t: str, body: Dict[str, Any]):
    return requests.put(f"{API}/admin/settings", headers=auth_headers(t), json=body, timeout=15)


def register_user(name: str, email: str, password: str, ref_code: Optional[str]) -> Dict[str, Any]:
    body = {"name": name, "email": email, "password": password}
    if ref_code:
        body["referral_code"] = ref_code
    r = requests.post(f"{API}/auth/register", json=body, timeout=15)
    assert r.status_code == 200, f"register failed for {email}: {r.status_code} {r.text}"
    data = r.json()
    CREATED_USER_IDS.append(data["user"]["id"])
    return data


def pay_register_fee(token: str):
    r = requests.post(f"{API}/payment/register-fee", headers=auth_headers(token), timeout=15)
    assert r.status_code == 200, f"pay register-fee failed: {r.status_code} {r.text}"
    return r.json()


def admin_approve(t_admin: str, user_id: str):
    r = requests.post(f"{API}/admin/approvals/{user_id}/approve", headers=auth_headers(t_admin), timeout=15)
    assert r.status_code == 200, f"approve {user_id} failed: {r.status_code} {r.text}"
    return r.json()


def get_user_admin(t_admin: str, user_id: str) -> Dict[str, Any]:
    r = requests.get(f"{API}/admin/users", headers=auth_headers(t_admin), timeout=20)
    r.raise_for_status()
    for u in r.json():
        if u["id"] == user_id:
            return u
    raise RuntimeError(f"user {user_id} not found in admin list")


def cleanup(t_admin: str):
    print("\n--- Cleanup ---")
    for uid in CREATED_USER_IDS:
        try:
            r = requests.delete(f"{API}/admin/users/{uid}", headers=auth_headers(t_admin), timeout=15)
            print(f"DELETE user {uid} -> {r.status_code}")
        except Exception as e:
            print(f"cleanup error for {uid}: {e}")


def restore_defaults(t_admin: str):
    body = dict(DEFAULTS)
    body["directs_required"] = 4
    r = put_settings(t_admin, body)
    return r


# ---------------- Scenarios ----------------

def scenario_A(t_admin: str):
    print("\n=== A: GET /admin/settings includes payout_l1..l10 ===")
    s = get_settings(t_admin)
    for i in range(1, 11):
        key = f"payout_l{i}"
        ok = key in s and isinstance(s[key], (int, float)) and s[key] >= 0
        check(f"A.{i} settings has {key} as float>=0", ok, f"value={s.get(key)}")
    check("A.dr directs_required present and >=1", isinstance(s.get("directs_required"), int) and s["directs_required"] >= 1,
          f"directs_required={s.get('directs_required')}")
    return s


def scenario_B(t_admin: str):
    print("\n=== B: PUT /admin/settings updates l4..l10 only ===")
    before = get_settings(t_admin)
    body = {
        "payout_l4": 50, "payout_l5": 40, "payout_l6": 30,
        "payout_l7": 20, "payout_l8": 10, "payout_l9": 5, "payout_l10": 1,
    }
    r = put_settings(t_admin, body)
    check("B.1 PUT returns 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    if r.status_code != 200:
        return
    after = r.json()
    for k, v in body.items():
        check(f"B.{k} updated to {v}", float(after.get(k, -1)) == float(v), f"got {after.get(k)}")
    for k in ("payout_l1", "payout_l2", "payout_l3"):
        check(f"B.preserved {k}", float(after.get(k)) == float(before.get(k)),
              f"before={before.get(k)} after={after.get(k)}")


def scenario_C(t_admin: str):
    print("\n=== C: PUT /admin/settings negative -> 422 ===")
    r = put_settings(t_admin, {"payout_l5": -5})
    check("C negative payout_l5 -> 422", r.status_code == 422, f"got {r.status_code}: {r.text[:200]}")


def scenario_D(t_admin: str):
    print("\n=== D: Restore defaults via PUT ===")
    body = dict(DEFAULTS)
    body["directs_required"] = 4
    r = put_settings(t_admin, body)
    check("D PUT defaults -> 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        s = r.json()
        for k, v in DEFAULTS.items():
            check(f"D.{k} == {v}", float(s.get(k)) == float(v), f"got {s.get(k)}")
        check("D.directs_required == 4", s.get("directs_required") == 4, f"got {s.get('directs_required')}")


def scenario_E(t_admin: str):
    print("\n=== E: dashboard.level_payouts is dict l1..l10 ===")
    suffix = uuid.uuid4().hex[:6]
    email = f"l10_e_{suffix}@test.com"
    reg = register_user("Dashboard Tester", email, "Pass@123", None)
    token = reg["token"]
    user_id = reg["user"]["id"]
    pay_register_fee(token)
    admin_approve(t_admin, user_id)

    r = requests.get(f"{API}/users/me/dashboard", headers=auth_headers(token), timeout=15)
    check("E.1 dashboard 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    if r.status_code != 200:
        return
    d = r.json()
    lp = d.get("level_payouts")
    check("E.2 level_payouts is dict", isinstance(lp, dict), f"got {type(lp).__name__}")
    if isinstance(lp, dict):
        expected_keys = {f"l{i}" for i in range(1, 11)}
        check("E.3 keys l1..l10", set(lp.keys()) == expected_keys, f"got {sorted(lp.keys())}")
        s = get_settings(t_admin)
        for i in range(1, 11):
            check(f"E.4.l{i} matches settings", float(lp.get(f"l{i}")) == float(s.get(f"payout_l{i}")),
                  f"dashboard={lp.get(f'l{i}')} settings={s.get(f'payout_l{i}')}")


def build_chain(t_admin: str, depth: int, tag: str) -> List[Dict[str, Any]]:
    """Build a chain of `depth` users U1->U2->...->Udepth where each Uk is sponsored by U(k-1)."""
    print(f"\n--- Building chain of depth {depth} ({tag}) ---")
    chain: List[Dict[str, Any]] = []
    suffix = uuid.uuid4().hex[:6]
    prev_ref_code: Optional[str] = None
    for k in range(1, depth + 1):
        email = f"chn_{tag}_{suffix}_u{k}@test.com"
        reg = register_user(f"Chain {tag} U{k}", email, "Pass@123", prev_ref_code)
        chain.append({
            "k": k,
            "email": email,
            "user_id": reg["user"]["id"],
            "token": reg["token"],
            "referral_code": reg["user"]["referral_code"],
        })
        prev_ref_code = reg["user"]["referral_code"]

    # Pay registration for each, then approve each in order
    for u in chain:
        pay_register_fee(u["token"])
    for u in chain:
        admin_approve(t_admin, u["user_id"])
    return chain


def scenario_F(t_admin: str):
    print("\n=== F: 10-level cascade — defaults ===")
    # Ensure defaults restored
    body = dict(DEFAULTS)
    body["directs_required"] = 4
    put_settings(t_admin, body)
    s_before = get_settings(t_admin)
    directs_required = s_before["directs_required"]
    print(f"directs_required = {directs_required}")

    chain = build_chain(t_admin, 11, "F")
    # chain[0] = U1 (top), chain[10] = U11 (bottom)
    # When U11 is approved:
    # U10 gets L1 cycle credit, U9 gets L2, ..., U1 gets L10

    # Capture wallet states AFTER everyone approved (the cascade should already be complete)
    snapshot = {}
    for u in chain:
        au = get_user_admin(t_admin, u["user_id"])
        snapshot[u["k"]] = {
            "wallet": au.get("wallet_balance", 0.0),
            "total_earned": au.get("total_earned", 0.0),
            "direct_referrals_count": au.get("direct_referrals_count", 0),
            "payouts_received": au.get("payouts_received", 0),
        }
        print(f"  U{u['k']}: wallet={snapshot[u['k']]['wallet']} total_earned={snapshot[u['k']]['total_earned']} directs={snapshot[u['k']]['direct_referrals_count']}")

    # ---- Verify each upline level credit ----
    # NOTE: Each Uk (k<11) has been approved BEFORE Uk+1 - so Uk gets credits from
    # all approvals of its descendants in the chain that happened AFTER it was approved.
    # When U2 approved: U1 receives L1 (count=1, no cycle), no L2..L10 (no upline above U1)
    # When U3 approved: U2 gets L1 (count=1), U1 gets L2 (=100)
    # When U4 approved: U3->L1(count=1), U2->L2(=100), U1->L3(=50)
    # When U5 approved: U4->L1, U3->L2, U2->L3, U1->L4(=25)
    # ... etc.
    # When U11 approved: U10->L1(count=1), U9->L2(=100), U8->L3(=50), U7->L4(=25),
    #                    U6->L5(=15), U5->L6(=10), U4->L7(=8), U3->L8(=5), U2->L9(=3), U1->L10(=2)

    # Direct referral counts: each Uk (1..10) sponsors exactly one user (U(k+1)),
    # so direct_referrals_count == 1 for U1..U10, and 0 for U11.
    for u in chain[:10]:
        check(f"F.directs U{u['k']}.directs==1", snapshot[u["k"]]["direct_referrals_count"] == 1,
              f"got {snapshot[u['k']]['direct_referrals_count']}")
    check("F.directs U11.directs==0", snapshot[11]["direct_referrals_count"] == 0,
          f"got {snapshot[11]['direct_referrals_count']}")

    # Compute expected wallet for each Uk
    # Uk receives, when U(k+1)..U11 are approved (one per descendant approval):
    #   from U(k+1) approval: as upline at L1
    #   from U(k+2) approval: as upline at L2
    #   ...
    #   from U(k+j) approval: as upline at L_j
    # L1 only fires every directs_required-th. With directs_required=4 and only 1 direct
    # per upline (count=1), L1 NEVER fires (1 % 4 != 0). So no L1 cycle payouts.
    # L2..L10 fire on every qualifying activation. So each Uk gets L2 (when U(k+2)
    # approved) + L3 (when U(k+3) approved) + ... up to L_min(11-k, 10)

    expected = {}
    for k in range(1, 12):
        total = 0.0
        # j = 1 means immediate (L1 cycle); j>=2 means L_j
        for j in range(2, 11):  # L2..L10 only fire per-activation
            descendant_idx = k + j  # the user whose approval triggers level j credit to Uk
            if descendant_idx <= 11:
                total += s_before[f"payout_l{j}"]
        # If directs_required=1 it would also include L1 cycle credits — not the case here
        expected[k] = total

    for k in range(1, 12):
        actual = snapshot[k]["wallet"]
        check(f"F.wallet U{k} == {expected[k]}", abs(actual - expected[k]) < 0.001,
              f"got {actual}, expected {expected[k]}")

    # Specifically per review request: check the cascade triggered by U11's approval
    # by examining transactions for the level 2..10 payouts that mention U11's name.
    # (Each transaction.description contains the source user's name.)
    print("\n--- Verifying U11-trigger transactions ---")
    expected_levels_for_u11 = {
        # upline_k -> level credited when U11 approved
        10: 1, 9: 2, 8: 3, 7: 4, 6: 5, 5: 6, 4: 7, 3: 8, 2: 9, 1: 10,
    }
    u11_name = f"Chain F U11"
    for upline_k, level in expected_levels_for_u11.items():
        upline_id = chain[upline_k - 1]["user_id"]
        r = requests.get(f"{API}/transactions/me", headers=auth_headers(chain[upline_k - 1]["token"]), timeout=15)
        if r.status_code != 200:
            check(f"F.U{upline_k} txn list 200", False, f"got {r.status_code}")
            continue
        txns = r.json()
        # find a referral_payout txn at given level mentioning U11
        match = None
        for t in txns:
            if t.get("type") == "referral_payout" and t.get("level") == level and u11_name in (t.get("description") or ""):
                match = t
                break
        if level == 1:
            # L1 cycle: should NOT have fired (count=1, dr=4)
            check(f"F.U{upline_k} L1-from-U11 NOT present (cycle)", match is None,
                  f"unexpected L1 txn: {match}")
        else:
            check(f"F.U{upline_k} L{level}-from-U11 present", match is not None,
                  f"no matching txn; sample: {[t for t in txns if t.get('type')=='referral_payout'][:3]}")
            if match:
                exp_amt = s_before[f"payout_l{level}"]
                check(f"F.U{upline_k} L{level} amount=={exp_amt}", abs(match["amount"] - exp_amt) < 0.001,
                      f"got {match['amount']}")
    return chain


def scenario_G(t_admin: str):
    print("\n=== G: Disable L5 (payout_l5=0) and verify L5 doesn't fire ===")
    body = dict(DEFAULTS)
    body["directs_required"] = 4
    body["payout_l5"] = 0
    r = put_settings(t_admin, body)
    check("G.0 PUT payout_l5=0 -> 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    s_before = get_settings(t_admin)
    check("G.s payout_l5 is 0", float(s_before["payout_l5"]) == 0.0, f"got {s_before.get('payout_l5')}")

    chain = build_chain(t_admin, 11, "G")
    # When U11 approved, U6 should receive L5 normally — but with L5=0, U6 gets no L5 credit.
    # Also U6 still gets credits from earlier L1 (from U7), L2 (from U8), etc.
    # And no L5 transaction should exist anywhere.

    u6_id = chain[5]["user_id"]
    u6_token = chain[5]["token"]
    r = requests.get(f"{API}/transactions/me", headers=auth_headers(u6_token), timeout=15)
    check("G.U6 txn 200", r.status_code == 200)
    txns = r.json() if r.status_code == 200 else []
    # No level-5 referral_payout txn should exist for U6
    l5_for_u6 = [t for t in txns if t.get("type") == "referral_payout" and t.get("level") == 5]
    check("G.U6 has NO L5 txn", len(l5_for_u6) == 0, f"got {l5_for_u6}")

    # Check overall: scan all chain users — none should have L5 referral_payout
    for u in chain:
        r = requests.get(f"{API}/transactions/me", headers=auth_headers(u["token"]), timeout=15)
        if r.status_code != 200:
            continue
        l5 = [t for t in r.json() if t.get("type") == "referral_payout" and t.get("level") == 5]
        check(f"G.U{u['k']} no L5 payout", len(l5) == 0, f"got {l5}")

    # Verify wallets reflect L5=0
    s = s_before
    expected = {}
    for k in range(1, 12):
        total = 0.0
        for j in range(2, 11):
            descendant_idx = k + j
            if descendant_idx <= 11:
                total += s[f"payout_l{j}"]
        expected[k] = total

    for u in chain:
        au = get_user_admin(t_admin, u["user_id"])
        actual = au.get("wallet_balance", 0.0)
        check(f"G.wallet U{u['k']} == {expected[u['k']]}", abs(actual - expected[u['k']]) < 0.001,
              f"got {actual}, expected {expected[u['k']]}")


def scenario_H(t_admin: str):
    print("\n=== H: Restore defaults at end ===")
    body = dict(DEFAULTS)
    body["directs_required"] = 4
    r = put_settings(t_admin, body)
    check("H restore defaults -> 200", r.status_code == 200, f"got {r.status_code}")
    s = get_settings(t_admin)
    for k, v in DEFAULTS.items():
        check(f"H.{k} == default {v}", float(s.get(k)) == float(v), f"got {s.get(k)}")


# ---- Light regression sanity checks (approval gate + KYC + admin mgmt + super-pwd + wipe) ----
def regression_checks(t_admin: str):
    print("\n=== Regression sanity ===")

    # 1. Approval gate: pending withdrawals get 403
    suffix = uuid.uuid4().hex[:6]
    email = f"reg_pend_{suffix}@test.com"
    reg = register_user("Reg Pending", email, "Pass@123", None)
    token = reg["token"]
    user_id = reg["user"]["id"]
    pay_register_fee(token)
    r = requests.post(f"{API}/withdrawals", headers=auth_headers(token), json={"amount": 100}, timeout=15)
    check("REG approval-gate withdraw -> 403", r.status_code == 403, f"got {r.status_code}: {r.text[:200]}")

    # Approve, then non-403
    admin_approve(t_admin, user_id)
    r = requests.post(f"{API}/withdrawals", headers=auth_headers(token), json={"amount": 100000}, timeout=15)
    check("REG post-approve withdraw -> 400 (insufficient)", r.status_code == 400, f"got {r.status_code}: {r.text[:200]}")

    # 2. KYC submit (text-only)
    r = requests.post(f"{API}/users/me/kyc", headers=auth_headers(token), json={
        "full_name": "Reg Pending", "aadhaar": "123456789012", "pan": "ABCDE1234F",
    }, timeout=15)
    check("REG KYC submit -> 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    r = requests.get(f"{API}/users/me/kyc", headers=auth_headers(token), timeout=15)
    check("REG KYC GET status==pending", r.status_code == 200 and r.json().get("status") == "pending",
          f"got {r.text[:200]}")

    # 3. Admin management list
    r = requests.get(f"{API}/admin/admins", headers=auth_headers(t_admin), timeout=15)
    check("REG /admin/admins 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        emails = [a.get("email") for a in data]
        check("REG admin@app.com in admins", ADMIN_EMAIL in emails, f"got {emails[:5]}")
        # No password hash leaked
        leaked = any("password_hash" in a for a in data)
        check("REG no password_hash leaked", not leaked)

    # 4. Super-password status
    r = requests.get(f"{API}/admin/super-password", headers=auth_headers(t_admin), timeout=15)
    check("REG super-password GET 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")

    # 5. Wipe-users gate (must NOT actually wipe — bad confirm)
    r = requests.post(f"{API}/admin/system/wipe-users",
                      headers=auth_headers(t_admin),
                      json={"confirm": "WRONG", "keep_admins": True, "super_password": "ignored"},
                      timeout=15)
    check("REG wipe-users bad confirm -> 400", r.status_code == 400, f"got {r.status_code}: {r.text[:200]}")


# ---------------- Main ----------------

def main():
    print(f"Backend: {BASE}")
    t_admin = admin_login()
    print(f"Admin token: {t_admin[:20]}...")

    try:
        scenario_A(t_admin)
        scenario_B(t_admin)
        scenario_C(t_admin)
        scenario_D(t_admin)
        scenario_E(t_admin)
        scenario_F(t_admin)
        scenario_G(t_admin)
        scenario_H(t_admin)
        regression_checks(t_admin)
    finally:
        # Always restore defaults and cleanup
        try:
            restore_defaults(t_admin)
        except Exception as e:
            print(f"restore_defaults error: {e}")
        cleanup(t_admin)

    print(f"\n========== RESULT: {PASS} passed, {FAIL} failed ==========")
    if FAILURES:
        print("\nFailures:")
        for f in FAILURES:
            print(f"  - {f}")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
