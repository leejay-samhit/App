"""
NetworkPay Backend Regression Suite
- Emergent Google Auth endpoints (callback HTML + exchange error paths)
- JWT auth, dashboard, network, KYC, bank, withdrawals, transactions
- Mock payment / referral payouts
- E-commerce: products, cart, orders
- Admin: users, KYC, withdrawals, transactions, settings, audit, analytics, stats, exports, orders, products
- RBAC: super_admin only PUT /admin/settings
"""

import os
import sys
import time
import uuid
import json
from typing import Optional, Dict, Any

import requests

# ---- Backend URL (public) ----
BACKEND_URL = "https://network-pay-1.preview.emergentagent.com"
API = f"{BACKEND_URL}/api"

ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"

results = []  # list of (name, status, info)

def log(name: str, ok: bool, info: str = ""):
    results.append((name, ok, info))
    icon = "PASS" if ok else "FAIL"
    print(f"[{icon}] {name} :: {info}")

def auth_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}

def unique_email(prefix: str = "user") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}@networkpay-test.com"


# =========================================================================
# 1. Emergent Google Auth endpoints
# =========================================================================
def test_google_auth_endpoints():
    print("\n=== Google Auth Endpoints ===")
    # GET callback returns 200 HTML
    r = requests.get(f"{API}/auth/google/callback")
    ok = r.status_code == 200 and "html" in r.headers.get("content-type", "").lower()
    log("GET /auth/google/callback returns 200 HTML", ok,
        f"status={r.status_code} ct={r.headers.get('content-type')}")

    # Invalid session -> 401
    r = requests.post(f"{API}/auth/google/exchange",
                      json={"session_id": "INVALID_TEST_SESSION_ID_12345"})
    detail = ""
    try:
        detail = r.json().get("detail", "")
    except Exception:
        pass
    ok = r.status_code == 401 and detail == "Invalid Google session"
    log("POST /auth/google/exchange invalid session -> 401", ok,
        f"status={r.status_code} detail={detail}")

    # Empty body -> 422
    r = requests.post(f"{API}/auth/google/exchange", json={})
    log("POST /auth/google/exchange empty body -> 422", r.status_code == 422,
        f"status={r.status_code}")

    # Missing session_id only referral_code -> 422
    r = requests.post(f"{API}/auth/google/exchange", json={"referral_code": "ADMIN001"})
    log("POST /auth/google/exchange missing session_id -> 422", r.status_code == 422,
        f"status={r.status_code}")

    # Invalid session WITH referral_code still returns 401 (referral_code only consumed once valid)
    r = requests.post(f"{API}/auth/google/exchange",
                      json={"session_id": "INVALID_TEST_SESSION_ID_67890",
                            "referral_code": "ADMIN001"})
    detail = ""
    try:
        detail = r.json().get("detail", "")
    except Exception:
        pass
    ok = r.status_code == 401 and detail == "Invalid Google session"
    log("POST /auth/google/exchange invalid session+referral -> 401", ok,
        f"status={r.status_code} detail={detail}")


# =========================================================================
# 2. Auth: register, login, /auth/me, /auth/logout
# =========================================================================
def test_auth_basic():
    print("\n=== Basic Auth ===")
    out = {}
    # Admin login
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    ok = r.status_code == 200 and "token" in r.json()
    log("Admin login", ok, f"status={r.status_code}")
    if not ok:
        return None
    out["admin_token"] = r.json()["token"]
    out["admin_user"] = r.json()["user"]

    # Register user A (referred by ADMIN001)
    email_a = unique_email("alice")
    r = requests.post(f"{API}/auth/register",
                      json={"name": "Alice Sharma", "email": email_a,
                            "password": "Secret@123", "phone": "9876543210",
                            "referral_code": "ADMIN001"})
    ok = r.status_code == 200 and "token" in r.json()
    log("Register user A (referred by ADMIN001)", ok, f"status={r.status_code}")
    if not ok:
        return None
    out["a_token"] = r.json()["token"]
    out["a_user"] = r.json()["user"]
    out["a_email"] = email_a

    # Register user B (referred by A)
    email_b = unique_email("bob")
    r = requests.post(f"{API}/auth/register",
                      json={"name": "Bob Patel", "email": email_b,
                            "password": "Secret@123",
                            "referral_code": out["a_user"]["referral_code"]})
    ok = r.status_code == 200
    log("Register user B (referred by A)", ok, f"status={r.status_code}")
    out["b_token"] = r.json()["token"]
    out["b_user"] = r.json()["user"]

    # Duplicate email -> 400
    r = requests.post(f"{API}/auth/register",
                      json={"name": "x", "email": email_a, "password": "Secret@123"})
    log("Register duplicate email -> 400", r.status_code == 400, f"status={r.status_code}")

    # Invalid referral code -> 400
    r = requests.post(f"{API}/auth/register",
                      json={"name": "x", "email": unique_email("x"),
                            "password": "Secret@123",
                            "referral_code": "INVALIDXX"})
    log("Register invalid referral -> 400", r.status_code == 400, f"status={r.status_code}")

    # Login wrong password -> 401
    r = requests.post(f"{API}/auth/login", json={"email": email_a, "password": "wrong"})
    log("Login wrong password -> 401", r.status_code == 401, f"status={r.status_code}")

    # /auth/me
    r = requests.get(f"{API}/auth/me", headers=auth_headers(out["a_token"]))
    log("/auth/me with valid token", r.status_code == 200 and r.json().get("email") == email_a,
        f"status={r.status_code}")

    # /auth/me without token -> 401
    r = requests.get(f"{API}/auth/me")
    log("/auth/me no token -> 401", r.status_code == 401, f"status={r.status_code}")

    # /auth/logout
    r = requests.post(f"{API}/auth/logout", headers=auth_headers(out["a_token"]))
    log("/auth/logout", r.status_code == 200, f"status={r.status_code}")

    return out


# =========================================================================
# 3. User: dashboard, network, kyc, bank, withdrawals, transactions
# =========================================================================
def test_user_endpoints(ctx):
    print("\n=== User Endpoints ===")
    a_tok = ctx["a_token"]
    b_tok = ctx["b_token"]

    # Dashboard
    r = requests.get(f"{API}/users/me/dashboard", headers=auth_headers(a_tok))
    ok = r.status_code == 200 and "wallet_balance" in r.json() and "tier" in r.json()
    log("GET /users/me/dashboard", ok, f"status={r.status_code}")

    # Network
    r = requests.get(f"{API}/users/me/network", headers=auth_headers(a_tok))
    ok = r.status_code == 200 and "children" in r.json()
    log("GET /users/me/network", ok, f"status={r.status_code}")

    # KYC submit (valid)
    r = requests.post(f"{API}/users/me/kyc",
                      headers=auth_headers(a_tok),
                      json={"full_name": "Alice Sharma", "aadhaar": "123456789012",
                            "pan": "ABCDE1234F"})
    log("POST /users/me/kyc valid", r.status_code == 200 and r.json().get("status") == "pending",
        f"status={r.status_code}")

    # KYC submit (bad aadhaar)
    r = requests.post(f"{API}/users/me/kyc",
                      headers=auth_headers(a_tok),
                      json={"full_name": "x", "aadhaar": "123",
                            "pan": "ABCDE1234F"})
    log("POST /users/me/kyc bad aadhaar -> 400", r.status_code == 400, f"status={r.status_code}")

    # GET KYC
    r = requests.get(f"{API}/users/me/kyc", headers=auth_headers(a_tok))
    log("GET /users/me/kyc", r.status_code == 200 and r.json().get("status") == "pending",
        f"status={r.status_code}")

    # Bank update
    r = requests.post(f"{API}/users/me/bank",
                      headers=auth_headers(a_tok),
                      json={"upi_id": "alice@upi", "bank_account": "1234567890",
                            "ifsc": "HDFC0000001", "account_holder": "Alice Sharma"})
    ok = r.status_code == 200 and r.json().get("upi_id") == "alice@upi"
    log("POST /users/me/bank", ok, f"status={r.status_code}")

    # Bank empty -> 400
    r = requests.post(f"{API}/users/me/bank", headers=auth_headers(a_tok), json={})
    log("POST /users/me/bank empty -> 400", r.status_code == 400, f"status={r.status_code}")

    # Withdrawal without registration_paid -> 400
    r = requests.post(f"{API}/withdrawals", headers=auth_headers(a_tok), json={"amount": 100})
    log("POST /withdrawals before reg fee -> 400", r.status_code == 400, f"status={r.status_code}")

    # Pay registration fee for B (so admin gets L1 referral count + maybe payout)
    r = requests.post(f"{API}/payment/register-fee", headers=auth_headers(b_tok))
    log("POST /payment/register-fee for B", r.status_code == 200, f"status={r.status_code}")

    # Pay registration fee for A
    r = requests.post(f"{API}/payment/register-fee", headers=auth_headers(a_tok))
    log("POST /payment/register-fee for A", r.status_code == 200, f"status={r.status_code}")

    # Re-pay -> 400
    r = requests.post(f"{API}/payment/register-fee", headers=auth_headers(a_tok))
    log("POST /payment/register-fee duplicate -> 400", r.status_code == 400, f"status={r.status_code}")

    # Transactions list
    r = requests.get(f"{API}/transactions/me", headers=auth_headers(a_tok))
    ok = r.status_code == 200 and isinstance(r.json(), list)
    log("GET /transactions/me", ok, f"status={r.status_code} count={len(r.json()) if ok else '?'}")

    # Withdrawals: insufficient balance -> 400
    r = requests.post(f"{API}/withdrawals", headers=auth_headers(a_tok), json={"amount": 999999})
    log("POST /withdrawals insufficient balance -> 400", r.status_code == 400, f"status={r.status_code}")

    # Withdrawals list (empty for A)
    r = requests.get(f"{API}/withdrawals/me", headers=auth_headers(a_tok))
    log("GET /withdrawals/me", r.status_code == 200 and isinstance(r.json(), list),
        f"status={r.status_code}")


# =========================================================================
# 4. E-commerce: products, cart, orders
# =========================================================================
def test_ecommerce(ctx):
    print("\n=== E-commerce ===")
    a_tok = ctx["a_token"]
    admin_tok = ctx["admin_token"]

    # Products list (public-ish, requires no auth)
    r = requests.get(f"{API}/products")
    ok = r.status_code == 200 and isinstance(r.json(), list) and len(r.json()) > 0
    log("GET /products", ok, f"status={r.status_code} count={len(r.json()) if ok else '?'}")
    if not ok:
        return
    products = r.json()
    ctx["product_id"] = products[0]["id"]
    ctx["product_price"] = products[0]["price"]

    # Cart add
    r = requests.post(f"{API}/cart/add", headers=auth_headers(a_tok),
                      json={"product_id": ctx["product_id"], "qty": 2})
    log("POST /cart/add", r.status_code == 200, f"status={r.status_code}")

    # Cart add invalid product -> 404
    r = requests.post(f"{API}/cart/add", headers=auth_headers(a_tok),
                      json={"product_id": "no-such", "qty": 1})
    log("POST /cart/add invalid product -> 404", r.status_code == 404, f"status={r.status_code}")

    # Cart get
    r = requests.get(f"{API}/cart", headers=auth_headers(a_tok))
    ok = r.status_code == 200 and r.json()["count"] >= 2
    log("GET /cart", ok, f"status={r.status_code}")

    # Cart remove
    r = requests.post(f"{API}/cart/remove", headers=auth_headers(a_tok),
                      json={"product_id": ctx["product_id"]})
    log("POST /cart/remove", r.status_code == 200, f"status={r.status_code}")

    # Cart clear
    r = requests.post(f"{API}/cart/clear", headers=auth_headers(a_tok))
    log("POST /cart/clear", r.status_code == 200, f"status={r.status_code}")

    # Checkout empty cart -> 400
    r = requests.post(f"{API}/orders/checkout", headers=auth_headers(a_tok))
    log("POST /orders/checkout empty -> 400", r.status_code == 400, f"status={r.status_code}")

    # Credit A's wallet via admin so we can checkout
    a_id = ctx["a_user"]["id"]
    needed = ctx["product_price"] + 100
    r = requests.post(f"{API}/admin/users/{a_id}/wallet",
                      headers=auth_headers(admin_tok),
                      json={"amount": needed, "type": "credit", "reason": "test top-up"})
    log("Admin credit wallet for checkout", r.status_code == 200, f"status={r.status_code}")

    # Add product back, checkout
    requests.post(f"{API}/cart/add", headers=auth_headers(a_tok),
                  json={"product_id": ctx["product_id"], "qty": 1})
    r = requests.post(f"{API}/orders/checkout", headers=auth_headers(a_tok))
    ok = r.status_code == 200 and r.json().get("status") == "placed"
    log("POST /orders/checkout success", ok, f"status={r.status_code}")
    if ok:
        ctx["order_id"] = r.json()["id"]

    # GET /orders/me
    r = requests.get(f"{API}/orders/me", headers=auth_headers(a_tok))
    ok = r.status_code == 200 and isinstance(r.json(), list) and len(r.json()) >= 1
    log("GET /orders/me", ok, f"status={r.status_code}")


# =========================================================================
# 5. Admin endpoints
# =========================================================================
def test_admin_endpoints(ctx):
    print("\n=== Admin Endpoints ===")
    admin_tok = ctx["admin_token"]
    a_id = ctx["a_user"]["id"]
    b_id = ctx["b_user"]["id"]

    # Users list
    r = requests.get(f"{API}/admin/users", headers=auth_headers(admin_tok))
    ok = r.status_code == 200 and isinstance(r.json(), list)
    log("GET /admin/users", ok, f"status={r.status_code} count={len(r.json()) if ok else '?'}")

    # Edit user (PATCH)
    r = requests.patch(f"{API}/admin/users/{a_id}",
                       headers=auth_headers(admin_tok),
                       json={"phone": "9999999999"})
    log("PATCH /admin/users/{id} phone", r.status_code == 200 and r.json().get("phone") == "9999999999",
        f"status={r.status_code}")

    # Block / unblock
    r = requests.post(f"{API}/admin/users/{b_id}/block",
                      headers=auth_headers(admin_tok),
                      json={"reason": "test block"})
    log("POST /admin/users/{id}/block", r.status_code == 200, f"status={r.status_code}")

    r = requests.post(f"{API}/admin/users/{b_id}/unblock",
                      headers=auth_headers(admin_tok))
    log("POST /admin/users/{id}/unblock", r.status_code == 200, f"status={r.status_code}")

    # Wallet credit
    r = requests.post(f"{API}/admin/users/{a_id}/wallet",
                      headers=auth_headers(admin_tok),
                      json={"amount": 500, "type": "credit", "reason": "bonus"})
    log("POST /admin/users/{id}/wallet credit", r.status_code == 200, f"status={r.status_code}")

    # Wallet freeze toggle (twice -> back to unfrozen)
    r = requests.post(f"{API}/admin/users/{a_id}/wallet/freeze",
                      headers=auth_headers(admin_tok))
    ok1 = r.status_code == 200
    r = requests.post(f"{API}/admin/users/{a_id}/wallet/freeze",
                      headers=auth_headers(admin_tok))
    log("POST /admin/users/{id}/wallet/freeze toggle x2", ok1 and r.status_code == 200,
        f"status={r.status_code}")

    # KYC list (any)
    r = requests.get(f"{API}/admin/kyc", headers=auth_headers(admin_tok))
    log("GET /admin/kyc", r.status_code == 200, f"status={r.status_code}")

    # KYC list pending
    r = requests.get(f"{API}/admin/kyc?status=pending", headers=auth_headers(admin_tok))
    log("GET /admin/kyc?status=pending", r.status_code == 200, f"status={r.status_code}")

    # We'll approve A's KYC (already submitted)
    r = requests.post(f"{API}/admin/kyc/{a_id}/approve",
                      headers=auth_headers(admin_tok))
    log("POST /admin/kyc/{id}/approve", r.status_code == 200, f"status={r.status_code}")

    # Submit B KYC then reject
    r = requests.post(f"{API}/users/me/kyc",
                      headers=auth_headers(ctx["b_token"]),
                      json={"full_name": "Bob Patel", "aadhaar": "987654321098",
                            "pan": "FGHIJ5678K"})
    submitted = r.status_code == 200
    r = requests.post(f"{API}/admin/kyc/{b_id}/reject",
                      headers=auth_headers(admin_tok),
                      json={"reason": "documents unclear"})
    log("POST /admin/kyc/{id}/reject (after fresh submit)", submitted and r.status_code == 200,
        f"status={r.status_code}")

    # Withdrawals: create one for A then approve another for B (need wallet)
    # First withdrawal: create one for A (has balance from credit)
    r = requests.post(f"{API}/withdrawals", headers=auth_headers(ctx["a_token"]),
                      json={"amount": 50})
    ok_w = r.status_code == 200
    wid = r.json().get("id") if ok_w else None
    log("POST /withdrawals (A)", ok_w, f"status={r.status_code}")

    # Admin list withdrawals pending
    r = requests.get(f"{API}/admin/withdrawals?status=pending",
                     headers=auth_headers(admin_tok))
    log("GET /admin/withdrawals?status=pending", r.status_code == 200, f"status={r.status_code}")

    # Approve
    if wid:
        r = requests.post(f"{API}/admin/withdrawals/{wid}/approve",
                          headers=auth_headers(admin_tok))
        log("POST /admin/withdrawals/{id}/approve", r.status_code == 200, f"status={r.status_code}")

    # Create another withdrawal for A and reject it
    r = requests.post(f"{API}/withdrawals", headers=auth_headers(ctx["a_token"]),
                      json={"amount": 25})
    if r.status_code == 200:
        wid2 = r.json()["id"]
        r = requests.post(f"{API}/admin/withdrawals/{wid2}/reject",
                          headers=auth_headers(admin_tok))
        log("POST /admin/withdrawals/{id}/reject", r.status_code == 200, f"status={r.status_code}")
    else:
        log("POST /admin/withdrawals reject (setup)", False,
            f"setup withdrawal failed status={r.status_code}")

    # Transactions list & filter
    r = requests.get(f"{API}/admin/transactions", headers=auth_headers(admin_tok))
    log("GET /admin/transactions", r.status_code == 200 and isinstance(r.json(), list),
        f"status={r.status_code}")
    r = requests.get(f"{API}/admin/transactions/filter?type=registration_fee",
                     headers=auth_headers(admin_tok))
    log("GET /admin/transactions/filter?type=registration_fee", r.status_code == 200,
        f"status={r.status_code}")

    # Settings GET (any admin, super_admin OK)
    r = requests.get(f"{API}/admin/settings", headers=auth_headers(admin_tok))
    log("GET /admin/settings", r.status_code == 200 and "registration_fee" in r.json(),
        f"status={r.status_code}")

    # Settings PUT super_admin
    r = requests.put(f"{API}/admin/settings", headers=auth_headers(admin_tok),
                     json={"payout_l1": 400})
    log("PUT /admin/settings super_admin", r.status_code == 200, f"status={r.status_code}")

    # Audit logs
    r = requests.get(f"{API}/admin/audit-logs", headers=auth_headers(admin_tok))
    log("GET /admin/audit-logs", r.status_code == 200 and isinstance(r.json(), list),
        f"status={r.status_code}")

    # Analytics
    r = requests.get(f"{API}/admin/analytics?days=7", headers=auth_headers(admin_tok))
    log("GET /admin/analytics?days=7", r.status_code == 200 and "kpis" in r.json(),
        f"status={r.status_code}")

    # Stats
    r = requests.get(f"{API}/admin/stats", headers=auth_headers(admin_tok))
    log("GET /admin/stats", r.status_code == 200 and "total_users" in r.json(),
        f"status={r.status_code}")

    # Exports
    for kind in ("users", "transactions", "withdrawals", "orders"):
        r = requests.get(f"{API}/admin/export/{kind}", headers=auth_headers(admin_tok))
        ok = r.status_code == 200 and "text/csv" in r.headers.get("content-type", "")
        log(f"GET /admin/export/{kind}", ok,
            f"status={r.status_code} ct={r.headers.get('content-type')}")

    # Order status update
    if ctx.get("order_id"):
        r = requests.patch(f"{API}/admin/orders/{ctx['order_id']}/status",
                           headers=auth_headers(admin_tok),
                           json={"status": "shipped"})
        log("PATCH /admin/orders/{id}/status shipped", r.status_code == 200, f"status={r.status_code}")
    else:
        log("PATCH /admin/orders/{id}/status shipped", False, "no order_id from earlier")

    # Products create
    r = requests.post(f"{API}/admin/products",
                      headers=auth_headers(admin_tok),
                      json={"name": "Test Product " + uuid.uuid4().hex[:6],
                            "price": 199, "image_url": "https://example.com/p.jpg",
                            "description": "test", "stock": 10})
    log("POST /admin/products", r.status_code == 200, f"status={r.status_code}")


# =========================================================================
# 6. RBAC: non-super_admin cannot PUT /api/admin/settings
# =========================================================================
def test_rbac(ctx):
    print("\n=== RBAC Settings ===")
    admin_tok = ctx["admin_token"]

    # Promote user A to admin with admin_role=manager
    a_id = ctx["a_user"]["id"]
    r = requests.patch(f"{API}/admin/users/{a_id}",
                       headers=auth_headers(admin_tok),
                       json={"role": "admin", "admin_role": "manager"})
    promoted = r.status_code == 200
    log("Promote A to admin/manager (setup)", promoted, f"status={r.status_code}")
    if not promoted:
        return

    # Login A again to get a new token with role=admin
    r = requests.post(f"{API}/auth/login",
                      json={"email": ctx["a_email"], "password": "Secret@123"})
    if r.status_code != 200:
        log("Manager re-login (setup)", False, f"status={r.status_code}")
        return
    manager_tok = r.json()["token"]

    # Manager tries to GET /admin/settings -> 200 allowed
    r = requests.get(f"{API}/admin/settings", headers=auth_headers(manager_tok))
    log("Manager GET /admin/settings allowed", r.status_code == 200, f"status={r.status_code}")

    # Manager tries to PUT /admin/settings -> 403
    r = requests.put(f"{API}/admin/settings",
                     headers=auth_headers(manager_tok),
                     json={"payout_l1": 401})
    log("Manager PUT /admin/settings -> 403", r.status_code == 403, f"status={r.status_code}")

    # Demote back
    r = requests.patch(f"{API}/admin/users/{a_id}",
                       headers=auth_headers(admin_tok),
                       json={"role": "user", "admin_role": None})
    # Demoting via None requires a different approach since None is filtered out;
    # we'll just leave admin_role=manager but role=user
    r = requests.patch(f"{API}/admin/users/{a_id}",
                       headers=auth_headers(admin_tok),
                       json={"role": "user"})
    log("Demote A back to user (cleanup)", r.status_code == 200, f"status={r.status_code}")


# =========================================================================
# Main
# =========================================================================
def main():
    print(f"Backend URL: {BACKEND_URL}")

    # 1. Google Auth (no creds needed)
    test_google_auth_endpoints()

    # 2. Auth basic
    ctx = test_auth_basic()
    if not ctx:
        print("FATAL: cannot proceed without auth")
        sys.exit(1)

    # 3. User
    test_user_endpoints(ctx)

    # 4. E-commerce
    test_ecommerce(ctx)

    # 5. Admin
    test_admin_endpoints(ctx)

    # 6. RBAC
    test_rbac(ctx)

    # Summary
    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    failed = total - passed
    print("\n========================================")
    print(f"PASSED: {passed}/{total}    FAILED: {failed}")
    print("========================================")
    if failed:
        print("\nFailed tests:")
        for name, ok, info in results:
            if not ok:
                print(f"  - {name} :: {info}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
