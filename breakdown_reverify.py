"""Re-verify /api/admin/system-wallet/breakdown after the double-counting fix."""
import json
import requests
import sys

BASE = "https://vendor-network-app-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@app.com"
ADMIN_PASS = "Admin@123"

REQUIRED_INFLOW = {
    "registration_fee_total", "no_ref_signup_revenue", "with_ref_signup_revenue",
    "no_ref_count", "with_ref_count", "utr_deposits", "service_margin",
    "shop_margin", "total",
}
REQUIRED_OUTFLOW = {
    "to_user_wallets_referral_net", "to_admin_retained", "to_admin_gst_collected",
    "to_admin_direct_added", "to_admin_shop_margin", "to_admin_service_margin",
    "to_admin_via_cascade", "user_withdrawals_settled", "to_user_wallets_referral",
    "_legacy_to_admin_direct_signup", "_legacy_to_admin_fee_residual",
    "_legacy_to_admin_cascade_overflow", "_legacy_l1_funding_debit",
    "redistributed_total", "total",
}
REQUIRED_BALANCE = {"in_admin_wallet", "in_user_wallets", "held_total"}
REQUIRED_SETTINGS = {"registration_fee", "directs_required", "level_payouts"}


def assert_eq(name, a, b, tol=1.0):
    diff = abs(float(a) - float(b))
    status = "PASS" if diff <= tol else "FAIL"
    print(f"  [{status}] {name}: {a} vs {b}  (diff ₹{diff:.2f}, tol ₹{tol})")
    return status == "PASS"


def main():
    results = []

    # 1) Login
    r = requests.post(f"{BASE}/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
                      timeout=30)
    print(f"[LOGIN] status={r.status_code}")
    assert r.status_code == 200, r.text
    token = r.json().get("token") or r.json().get("access_token")
    assert token, f"No token in login response: {r.json()}"
    results.append(("Login admin", True))
    H = {"Authorization": f"Bearer {token}"}

    # 2) GET breakdown
    r = requests.get(f"{BASE}/admin/system-wallet/breakdown", headers=H, timeout=30)
    print(f"[BREAKDOWN] status={r.status_code}")
    assert r.status_code == 200, r.text
    data = r.json()
    print(json.dumps(data, indent=2))
    results.append(("GET breakdown 200", True))

    inflow = data.get("inflow", {})
    outflow = data.get("outflow", {})
    balance = data.get("balance", {})
    settings = data.get("settings", {})

    # 3) Payload shape - 30 keys
    print("\n=== PAYLOAD SHAPE CHECK ===")
    miss_in = REQUIRED_INFLOW - set(inflow.keys())
    miss_out = REQUIRED_OUTFLOW - set(outflow.keys())
    miss_bal = REQUIRED_BALANCE - set(balance.keys())
    miss_set = REQUIRED_SETTINGS - set(settings.keys())
    for label, miss in [("inflow", miss_in), ("outflow", miss_out),
                        ("balance", miss_bal), ("settings", miss_set)]:
        if miss:
            print(f"  [FAIL] missing {label} keys: {miss}")
            results.append((f"{label} keys", False))
        else:
            print(f"  [PASS] {label} has all required keys")
            results.append((f"{label} keys", True))

    # 4) Identities
    print("\n=== IDENTITY CHECKS ===")
    A = assert_eq("A) inflow.total == outflow.total",
                  inflow["total"], outflow["total"])
    B = assert_eq("B) inflow.total == held_total + user_withdrawals_settled",
                  inflow["total"],
                  balance["held_total"] + outflow["user_withdrawals_settled"])
    C = assert_eq("C) outflow.redistributed_total == outflow.total",
                  outflow["redistributed_total"], outflow["total"])
    D = assert_eq("D) held_total == in_admin_wallet + in_user_wallets",
                  balance["held_total"],
                  balance["in_admin_wallet"] + balance["in_user_wallets"])

    results.append(("Identity A inflow==outflow", A))
    results.append(("Identity B inflow==held+withdrawn", B))
    results.append(("Identity C redistributed==outflow.total", C))
    results.append(("Identity D held==admin+users", D))

    print("\n=== LIVE NUMBERS ===")
    print(f"  inflow.total              = ₹{inflow.get('total')}")
    print(f"  outflow.total             = ₹{outflow.get('total')}")
    print(f"  redistributed_total       = ₹{outflow.get('redistributed_total')}")
    print(f"  user_withdrawals_settled  = ₹{outflow.get('user_withdrawals_settled')}")
    print(f"  balance.held_total        = ₹{balance.get('held_total')}")
    print(f"  in_admin_wallet           = ₹{balance.get('in_admin_wallet')}")
    print(f"  in_user_wallets           = ₹{balance.get('in_user_wallets')}")

    print("\n=== SUMMARY ===")
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    for name, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
