"""
System Wallet Breakdown Regression Test
========================================
Verifies that the /api/admin/system-wallet/breakdown endpoint payload
emits ALL required fields the new frontend UI consumes, plus identity checks.
"""

import sys
import requests

BASE = "https://vendor-network-app-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"

REQUIRED_INFLOW_KEYS = {
    "registration_fee_total", "no_ref_signup_revenue", "with_ref_signup_revenue",
    "no_ref_count", "with_ref_count", "utr_deposits", "service_margin",
    "shop_margin", "total"
}
REQUIRED_OUTFLOW_KEYS = {
    "to_user_wallets_referral_net", "to_admin_retained", "to_admin_gst_collected",
    "to_admin_direct_added", "to_admin_shop_margin", "to_admin_service_margin",
    "to_admin_via_cascade", "user_withdrawals_settled", "to_user_wallets_referral",
    "_legacy_to_admin_direct_signup", "_legacy_to_admin_fee_residual",
    "_legacy_to_admin_cascade_overflow", "_legacy_l1_funding_debit",
    "redistributed_total", "total"
}
REQUIRED_BALANCE_KEYS = {"in_admin_wallet", "in_user_wallets", "held_total"}
REQUIRED_SETTINGS_KEYS = {"registration_fee", "directs_required", "level_payouts"}

results = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    results.append((name, status, detail))
    marker = "PASS" if cond else "FAIL"
    print(f"  [{marker}] {name}: {detail}")
    return cond


def main():
    print("=" * 70)
    print("SYSTEM WALLET BREAKDOWN REGRESSION")
    print("=" * 70)

    print("\n[1] POST /auth/login (admin)")
    r = requests.post(f"{BASE}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=20)
    if r.status_code != 200:
        check("auth/login admin", False, f"HTTP {r.status_code}: {r.text[:200]}")
        return False
    token = r.json().get("token")
    check("auth/login admin", bool(token), f"got token len={len(token) if token else 0}")
    H = {"Authorization": f"Bearer {token}"}

    print("\n[2] GET /admin/system-wallet/breakdown")
    r = requests.get(f"{BASE}/admin/system-wallet/breakdown", headers=H, timeout=30)
    if r.status_code != 200:
        check("breakdown status 200", False, f"HTTP {r.status_code}: {r.text[:300]}")
        return False
    body = r.json()
    check("breakdown status 200", True, "200 OK")
    print(f"\n  Top-level keys: {sorted(body.keys())}")

    inflow = body.get("inflow") or {}
    outflow = body.get("outflow") or {}
    balance = body.get("balance") or {}
    settings = body.get("settings") or {}

    check("inflow section present", isinstance(inflow, dict) and len(inflow) > 0,
          f"keys={sorted(inflow.keys())}")
    check("outflow section present", isinstance(outflow, dict) and len(outflow) > 0,
          f"keys={sorted(outflow.keys())}")
    check("balance section present", isinstance(balance, dict) and len(balance) > 0,
          f"keys={sorted(balance.keys())}")
    check("settings section present", isinstance(settings, dict) and len(settings) > 0,
          f"keys={sorted(settings.keys())}")

    print("\n[3] Required key presence checks")
    missing_in = REQUIRED_INFLOW_KEYS - set(inflow.keys())
    check("inflow has all required keys", not missing_in,
          f"missing={sorted(missing_in)}" if missing_in else "all 9 present")
    missing_out = REQUIRED_OUTFLOW_KEYS - set(outflow.keys())
    check("outflow has all required keys", not missing_out,
          f"missing={sorted(missing_out)}" if missing_out else "all 15 present")
    missing_bal = REQUIRED_BALANCE_KEYS - set(balance.keys())
    check("balance has all required keys", not missing_bal,
          f"missing={sorted(missing_bal)}" if missing_bal else "all 3 present")
    missing_set = REQUIRED_SETTINGS_KEYS - set(settings.keys())
    check("settings has all required keys", not missing_set,
          f"missing={sorted(missing_set)}" if missing_set else "all 3 present")

    print("\n  --- inflow ---")
    for k in sorted(inflow.keys()):
        print(f"    {k} = {inflow[k]}")
    print("  --- outflow ---")
    for k in sorted(outflow.keys()):
        print(f"    {k} = {outflow[k]}")
    print("  --- balance ---")
    for k in sorted(balance.keys()):
        print(f"    {k} = {balance[k]}")
    print("  --- settings ---")
    for k in sorted(settings.keys()):
        print(f"    {k} = {settings[k]}")

    print("\n[4] IDENTITY CHECKS")
    TOL = 1.0
    inflow_total = float(inflow.get("total") or 0)
    outflow_total = float(outflow.get("total") or 0)
    held_total = float(balance.get("held_total") or 0)
    withdrawn = float(outflow.get("user_withdrawals_settled") or 0)
    redistributed = float(outflow.get("redistributed_total") or 0)
    in_admin = float(balance.get("in_admin_wallet") or 0)
    in_user = float(balance.get("in_user_wallets") or 0)

    diff1 = abs(inflow_total - (held_total + withdrawn))
    check(
        "Identity #1: inflow.total approximately equals held_total + user_withdrawals_settled",
        diff1 <= TOL,
        f"inflow={inflow_total}, held={held_total}, withdrawn={withdrawn}, diff=Rs.{diff1:.2f}",
    )

    diff2 = abs(outflow_total - inflow_total)
    check(
        "Identity #2: outflow.total approximately equals inflow.total",
        diff2 <= TOL,
        f"outflow={outflow_total}, inflow={inflow_total}, diff=Rs.{diff2:.2f}",
    )

    diff3 = abs((redistributed + withdrawn) - outflow_total)
    check(
        "Identity #3: redistributed_total + user_withdrawals_settled approximately equals outflow.total",
        diff3 <= TOL,
        f"redistributed={redistributed}, withdrawn={withdrawn}, outflow={outflow_total}, diff=Rs.{diff3:.2f}",
    )

    diff4 = abs(held_total - (in_admin + in_user))
    check(
        "Identity #4: held_total equals in_admin_wallet + in_user_wallets",
        diff4 <= TOL,
        f"held={held_total}, admin={in_admin}, user={in_user}, diff=Rs.{diff4:.2f}",
    )

    print("\n  Brief said live data:    inflow=Rs.14,750, held=Rs.14,650, withdrawn=Rs.100")
    print(f"  Actual right now:        inflow=Rs.{inflow_total}, held=Rs.{held_total}, withdrawn=Rs.{withdrawn}")

    print("\n[5] GET /admin/system-wallet (legacy contract)")
    r = requests.get(f"{BASE}/admin/system-wallet", headers=H, timeout=20)
    check("system-wallet status 200", r.status_code == 200, f"HTTP {r.status_code}")
    if r.status_code == 200:
        sw = r.json()
        check("system-wallet has buckets dict", isinstance(sw.get("buckets"), dict),
              f"buckets={list(sw.get('buckets', {}).keys())}")
        check("system-wallet has total key", "total" in sw, f"total={sw.get('total')}")

    print("\n[6] GET /admin/system-wallet/transactions?bucket=admin_wallet&limit=200")
    r = requests.get(f"{BASE}/admin/system-wallet/transactions",
                     headers=H, params={"bucket": "admin_wallet", "limit": 200}, timeout=20)
    check("transactions status 200", r.status_code == 200, f"HTTP {r.status_code}")
    if r.status_code == 200:
        txd = r.json()
        items = txd.get("items")
        check("transactions has items array", isinstance(items, list),
              f"count={len(items) if isinstance(items, list) else 'n/a'}")

    print("\n" + "=" * 70)
    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = sum(1 for _, s, _ in results if s == "FAIL")
    print(f"TOTAL: {passed}/{len(results)} PASS  |  {failed} FAIL")
    print("=" * 70)
    if failed:
        print("\nFAILED CHECKS:")
        for n, s, d in results:
            if s == "FAIL":
                print(f"  [FAIL] {n} -- {d}")
    return failed == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
