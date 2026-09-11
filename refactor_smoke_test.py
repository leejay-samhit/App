"""
Phase 1 refactor smoke test — verifies models.py extraction does not break
request validation or core admin endpoints.
"""
import os
import sys
import json
import requests

BASE_URL = "https://slangcart-tracking.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"

results = []
def add(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}: {name} | {detail}")

# 1. Login (validates LoginRequest)
r = requests.post(f"{BASE_URL}/auth/login",
                  json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                  timeout=20)
add("1. POST /auth/login admin → 200 + token (LoginRequest)",
    r.status_code == 200 and "token" in r.json(),
    f"status={r.status_code}, keys={list(r.json().keys()) if r.status_code==200 else r.text[:200]}")
if r.status_code != 200:
    print("Cannot continue without admin token")
    sys.exit(1)
token = r.json()["token"]
H = {"Authorization": f"Bearer {token}"}

# 2. Register with bad payload (missing email) → 422 (validates RegisterRequest)
r = requests.post(f"{BASE_URL}/auth/register",
                  json={"name": "Bad", "password": "secret123"},  # missing email
                  timeout=20)
ok = r.status_code == 422
detail_ok = False
if ok:
    body = r.json()
    # FastAPI/Pydantic emits {"detail": [{"loc": [...], "msg": "...", "type": "..."}]}
    if isinstance(body.get("detail"), list) and any("email" in str(e.get("loc", [])) for e in body["detail"]):
        detail_ok = True
add("2. POST /auth/register missing email → 422 with email error (RegisterRequest)",
    ok and detail_ok,
    f"status={r.status_code}, body={r.text[:300]}")

# 3. PUT /admin/branding (validates BrandingPayload)
sample_branding = {
    "app_name": "Network pay",
    "tagline": "Refer & Earn — refactor smoke",
    "login_subtitle": "Welcome back",
    "colors": {"primary": "#1f6feb", "accent": "#22c55e"},
    "font": "inter",
}
r = requests.put(f"{BASE_URL}/admin/branding",
                 json=sample_branding, headers=H, timeout=20)
add("3. PUT /admin/branding sample payload → 200 (BrandingPayload)",
    r.status_code == 200,
    f"status={r.status_code}, body={r.text[:200]}")

# 4. /admin/users/{id}/wallet — credit then debit reverse (validates WalletAdjust)
# First find a non-admin user to use
r_users = requests.get(f"{BASE_URL}/admin/users?limit=200", headers=H, timeout=20)
target_user = None
if r_users.status_code == 200:
    body = r_users.json()
    items = body if isinstance(body, list) else body.get("items", [])
    for u in items:
        if u.get("email", "").lower() != ADMIN_EMAIL.lower() and u.get("role") != "admin":
            target_user = u
            break

if target_user:
    uid = target_user["id"]
    pre_bal = float(target_user.get("wallet_balance") or 0)
    # Credit ₹1
    r = requests.post(f"{BASE_URL}/admin/users/{uid}/wallet",
                      json={"amount": 1, "type": "credit", "reason": "refactor smoke"},
                      headers=H, timeout=20)
    credit_ok = r.status_code == 200
    add("4a. POST /admin/users/{id}/wallet credit ₹1 → 200 (WalletAdjust)",
        credit_ok,
        f"status={r.status_code}, body={r.text[:200]}, target={target_user.get('email')}")
    # Debit ₹1 to revert
    if credit_ok:
        r = requests.post(f"{BASE_URL}/admin/users/{uid}/wallet",
                          json={"amount": 1, "type": "debit", "reason": "refactor smoke reverse"},
                          headers=H, timeout=20)
        add("4b. POST /admin/users/{id}/wallet debit ₹1 reverse → 200",
            r.status_code == 200,
            f"status={r.status_code}, body={r.text[:200]}")
else:
    add("4. WalletAdjust test", False, "no non-admin user found to test against")

# 5. Admin smoke endpoints
for path in ["/admin/transactions", "/admin/system-wallet", "/admin/users", "/branding"]:
    # /branding is public
    headers = {} if path == "/branding" else H
    r = requests.get(f"{BASE_URL}{path}", headers=headers, timeout=20)
    add(f"5. GET {path} → 200", r.status_code == 200, f"status={r.status_code}")

# 6. Bad product create (missing name) → 422 (validates ProductCreate)
r = requests.post(f"{BASE_URL}/admin/products",
                  json={"price": 100, "image_url": "http://example.com/i.jpg"},  # no name
                  headers=H, timeout=20)
ok = r.status_code == 422
detail_ok = False
if ok:
    body = r.json()
    if isinstance(body.get("detail"), list) and any("name" in str(e.get("loc", [])) for e in body["detail"]):
        detail_ok = True
add("6. POST /admin/products missing name → 422 with name error (ProductCreate)",
    ok and detail_ok,
    f"status={r.status_code}, body={r.text[:300]}")

# Summary
print("\n=== SUMMARY ===")
total = len(results)
passed = sum(1 for _, ok, _ in results if ok)
print(f"Passed {passed}/{total}")
for name, ok, _ in results:
    print(f"  {'OK ' if ok else 'XX '} {name}")
sys.exit(0 if passed == total else 1)
