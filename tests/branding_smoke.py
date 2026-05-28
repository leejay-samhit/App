"""Branding smoke test after admin/branding.tsx UI extension."""
import json
import requests

BASE = "https://vendor-network-app-1.preview.emergentagent.com/api"

results = []

def log(name, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}  {detail}")
    results.append((name, ok, detail))

# Login admin
r = requests.post(f"{BASE}/auth/login", json={"email": "admin@app.com", "password": "Admin@123"}, timeout=30)
assert r.status_code == 200, f"admin login {r.status_code} {r.text}"
_b = r.json(); admin_token = _b.get("access_token") or _b.get("token")
H_ADMIN = {"Authorization": f"Bearer {admin_token}"}

# Login testuser
r = requests.post(f"{BASE}/auth/login", json={"email": "testuser@app.com", "password": "Test@123"}, timeout=30)
assert r.status_code == 200, f"user login {r.status_code} {r.text}"
_b2 = r.json(); user_token = _b2.get("access_token") or _b2.get("token")
H_USER = {"Authorization": f"Bearer {user_token}"}

# 1. PUT /api/admin/branding with full payload
payload = {
    "app_name": "NetworkPay",
    "gradient": {"start": "#0A0E27", "middle": "#1E2A78", "end": "#5B21B6", "glow": "#06B6D4"},
    "button_style": "pill",
    "home_banner_b64": "https://images.unsplash.com/photo-1542744173-8e7e53415bb0",
}
r = requests.put(f"{BASE}/admin/branding", json=payload, headers=H_ADMIN, timeout=30)
body = r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text
ok = r.status_code == 200
log("1. PUT /admin/branding full payload -> 200", ok, f"status={r.status_code}")
if ok:
    g = body.get("gradient") or {}
    grad_ok = all(g.get(k) == payload["gradient"][k] for k in ("start", "middle", "end", "glow"))
    log("1a. gradient echoed full obj", grad_ok, f"gradient={g}")
    log("1b. button_style=='pill'", body.get("button_style") == "pill", f"button_style={body.get('button_style')}")
    log("1c. home_banner_b64 echoed", body.get("home_banner_b64") == payload["home_banner_b64"], f"home_banner_b64={body.get('home_banner_b64')}")
else:
    print("BODY:", body)

# 2. GET /api/branding (public)
r = requests.get(f"{BASE}/branding", timeout=30)
ok = r.status_code == 200
body = r.json()
log("2. GET /branding public -> 200", ok)
if ok:
    log("2a. gradient present", "gradient" in body and isinstance(body["gradient"], dict), f"gradient={body.get('gradient')}")
    log("2b. button_style present", "button_style" in body, f"button_style={body.get('button_style')}")
    log("2c. home_banner_b64 present", "home_banner_b64" in body, f"home_banner_b64={body.get('home_banner_b64')}")

# 3. PUT /api/admin/branding {button_style: 'square'}
r = requests.put(f"{BASE}/admin/branding", json={"button_style": "square"}, headers=H_ADMIN, timeout=30)
ok = r.status_code == 200
log("3. PUT button_style='square' -> 200", ok, f"status={r.status_code}")
if ok:
    log("3a. button_style updated to 'square'", r.json().get("button_style") == "square", f"got={r.json().get('button_style')}")
else:
    print("BODY:", r.text)

# 4. PUT button_style='round' (invalid) -> 400
r = requests.put(f"{BASE}/admin/branding", json={"button_style": "round"}, headers=H_ADMIN, timeout=30)
ok = r.status_code == 400
log("4. PUT button_style='round' -> 400", ok, f"status={r.status_code} body={r.text[:200]}")

# 5. PUT home_banner_b64='' (clear) -> 200, null or empty
r = requests.put(f"{BASE}/admin/branding", json={"home_banner_b64": ""}, headers=H_ADMIN, timeout=30)
ok = r.status_code == 200
log("5. PUT home_banner_b64='' -> 200", ok, f"status={r.status_code}")
if ok:
    hb = r.json().get("home_banner_b64")
    log("5a. home_banner_b64 is null/empty", hb in (None, ""), f"home_banner_b64={hb!r}")
else:
    print("BODY:", r.text)

# 6. Regression: GET /admin/service-analytics
r = requests.get(f"{BASE}/admin/service-analytics", headers=H_ADMIN, timeout=30)
ok = r.status_code == 200
log("6. GET /admin/service-analytics -> 200", ok, f"status={r.status_code} body[:150]={r.text[:150]}")

# 7. Regression: GET /payment/config (testuser) amount >= 118
r = requests.get(f"{BASE}/payment/config", headers=H_USER, timeout=30)
ok = r.status_code == 200
log("7. GET /payment/config -> 200", ok, f"status={r.status_code}")
if ok:
    body = r.json()
    amt = body.get("amount")
    log("7a. amount >= 118", isinstance(amt, (int, float)) and amt >= 118, f"amount={amt}, body={body}")
else:
    print("BODY:", r.text)

# Restore: set button_style back to 'pill' to leave branding consistent with prior state
requests.put(f"{BASE}/admin/branding", json={"button_style": "pill"}, headers=H_ADMIN, timeout=30)

print("\n=== SUMMARY ===")
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"{passed}/{total} PASS")
for name, ok, detail in results:
    if not ok:
        print(f"  FAIL: {name}  {detail}")
