#!/usr/bin/env python3
"""Final regression after deployment-log cleanup fix."""
import os, sys, json
import requests

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://slangcart-tracking.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"

PASS, FAIL = [], []

def check(name, ok, detail=""):
    (PASS if ok else FAIL).append((name, detail))
    print(("PASS" if ok else "FAIL") + f" :: {name} :: {detail}")

# 1. GET /api/branding
try:
    r = requests.get(f"{API}/branding", timeout=20)
    ok = r.status_code == 200 and "app_name" in r.json()
    check("01 GET /branding -> 200", ok, f"status={r.status_code}")
except Exception as e:
    check("01 GET /branding", False, str(e))

# 2. POST /api/auth/login admin
admin_token = None
try:
    r = requests.post(f"{API}/auth/login", json={"email":"admin@app.com","password":"Admin@123"}, timeout=20)
    j = r.json() if r.status_code < 500 else {}
    admin_token = j.get("token") or j.get("access_token")
    ok = r.status_code == 200 and bool(admin_token)
    check("02 POST /auth/login (admin) -> 200 + token", ok, f"status={r.status_code} tokenLen={len(admin_token or '')}")
except Exception as e:
    check("02 POST /auth/login (admin)", False, str(e))

HDR = {"Authorization": f"Bearer {admin_token}"} if admin_token else {}

# 3. GET /api/auth/me
try:
    r = requests.get(f"{API}/auth/me", headers=HDR, timeout=20)
    ok = r.status_code == 200 and r.json().get("email") == "admin@app.com"
    check("03 GET /auth/me -> 200", ok, f"status={r.status_code}")
except Exception as e:
    check("03 GET /auth/me", False, str(e))

# 4. GET /api/products
try:
    r = requests.get(f"{API}/products", timeout=20)
    data = r.json() if r.status_code == 200 else None
    arr = data if isinstance(data, list) else (data.get("items") if isinstance(data, dict) else None)
    ok = r.status_code == 200 and isinstance(arr, list)
    check("04 GET /products -> 200 array", ok, f"status={r.status_code} len={len(arr) if isinstance(arr,list) else 'N/A'}")
except Exception as e:
    check("04 GET /products", False, str(e))

# 5. GET /api/products/by-source?source=trending&limit=3
try:
    r = requests.get(f"{API}/products/by-source", params={"source":"trending","limit":3}, timeout=20)
    data = r.json() if r.status_code == 200 else None
    arr = data if isinstance(data, list) else (data.get("items") if isinstance(data, dict) else None)
    ok = r.status_code == 200 and isinstance(arr, list)
    check("05 GET /products/by-source?source=trending&limit=3 -> 200 array (route-ordering)", ok,
          f"status={r.status_code} len={len(arr) if isinstance(arr,list) else 'N/A'} body={str(data)[:120]}")
except Exception as e:
    check("05 GET /products/by-source", False, str(e))

# 6. GET /api/shop-layout?scope=home (no auth)
try:
    r = requests.get(f"{API}/shop-layout", params={"scope":"home"}, timeout=20)
    data = r.json() if r.status_code == 200 else None
    items = data.get("items") if isinstance(data, dict) else None
    ok = r.status_code == 200 and isinstance(items, list)
    check("06 GET /shop-layout?scope=home (no auth) -> 200 items[]", ok,
          f"status={r.status_code} items_len={len(items) if isinstance(items,list) else 'N/A'}")
except Exception as e:
    check("06 GET /shop-layout?scope=home", False, str(e))

# 7. GET /api/services (no auth)
try:
    r = requests.get(f"{API}/services", timeout=20)
    ok = r.status_code == 200
    check("07 GET /services (no auth) -> 200", ok, f"status={r.status_code}")
except Exception as e:
    check("07 GET /services", False, str(e))

# 8. GET /api/services/categories (no auth)
try:
    r = requests.get(f"{API}/services/categories", timeout=20)
    ok = r.status_code == 200
    check("08 GET /services/categories (no auth) -> 200", ok, f"status={r.status_code}")
except Exception as e:
    check("08 GET /services/categories", False, str(e))

# 9. GET /api/pincodes/search?q=560001 (public) — confirm not 500
try:
    r = requests.get(f"{API}/pincodes/search", params={"q":"560001"}, timeout=20)
    ok = r.status_code in (200, 401, 403, 404, 405, 422)
    check("09 GET /pincodes/search?q=560001 -> not 500", ok, f"status={r.status_code}")
except Exception as e:
    check("09 GET /pincodes/search", False, str(e))

# 10. GET /api/admin/pincodes/search?q=515&limit=3
try:
    r = requests.get(f"{API}/admin/pincodes/search", params={"q":"515","limit":3}, headers=HDR, timeout=20)
    data = r.json() if r.status_code == 200 else None
    arr = data if isinstance(data, list) else (data.get("items") if isinstance(data, dict) else None)
    ok = r.status_code == 200 and isinstance(arr, list) and len(arr) > 0
    check("10 GET /admin/pincodes/search?q=515&limit=3 -> 200 non-empty", ok,
          f"status={r.status_code} len={len(arr) if isinstance(arr,list) else 'N/A'} sample={str(arr[:1]) if isinstance(arr,list) and arr else ''}")
except Exception as e:
    check("10 GET /admin/pincodes/search", False, str(e))

print("\n" + "="*70)
print(f"PASSED: {len(PASS)}/{len(PASS)+len(FAIL)}")
for n,d in FAIL:
    print(f"  FAIL: {n} — {d}")
print("="*70)
sys.exit(0 if not FAIL else 1)
