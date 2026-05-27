"""
Phase 1 Session B validation — refresh tokens + single-session + device fingerprint.
Read-only verification against the live preview backend.
"""
import base64
import json
import os
import sys
import time
import requests

BASE = os.environ.get("BACKEND_BASE", "https://vendor-network-app-1.preview.emergentagent.com/api")
ADMIN = ("admin@app.com", "Admin@123")
TESTUSER = ("testuser@app.com", "Test@123")
QR = ("qrtest@app.com", "Qr@1234")

results = []  # (section, name, passed, detail)


def record(section, name, passed, detail=""):
    results.append((section, name, passed, detail))
    icon = "PASS" if passed else "FAIL"
    print(f"[{icon}] {section} :: {name} — {detail}")


def decode_jwt_payload(tok: str) -> dict:
    """Decode JWT without verifying signature (for claim inspection)."""
    try:
        mid = tok.split(".")[1]
        pad = "=" * (-len(mid) % 4)
        raw = base64.urlsafe_b64decode(mid + pad)
        return json.loads(raw.decode("utf-8"))
    except Exception as e:
        return {"_decode_err": str(e)}


def login(email, password):
    return requests.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=30)


def me(tok, extra_headers=None):
    h = {"Authorization": f"Bearer {tok}"}
    if extra_headers:
        h.update(extra_headers)
    return requests.get(f"{BASE}/auth/me", headers=h, timeout=30)


# ───────────────────────── 1) ISSUANCE ─────────────────────────────
print("\n=== SECTION 1: REFRESH TOKEN ISSUANCE ===")
r = login(*TESTUSER)
record("1", "POST /auth/login (testuser) = 200", r.status_code == 200, f"http={r.status_code}")
if r.status_code != 200:
    print("Cannot continue without login")
    sys.exit(1)
body = r.json()
record("1", "response has `token`", "token" in body, "")
record("1", "response has `refresh_token`", "refresh_token" in body, "")
record("1", "response has `user`", "user" in body, "")
T1 = body["token"]
RT1 = body["refresh_token"]

acc_claims = decode_jwt_payload(T1)
ref_claims = decode_jwt_payload(RT1)
record("1", "access type=access", acc_claims.get("type") == "access", f"type={acc_claims.get('type')}")
record("1", "access has sid", bool(acc_claims.get("sid")), f"sid={acc_claims.get('sid')}")
now = int(time.time())
acc_exp_delta = int(acc_claims.get("exp", 0)) - now
record("1", "access exp ~15min", 12 * 60 <= acc_exp_delta <= 20 * 60, f"delta={acc_exp_delta}s")
record("1", "refresh type=refresh", ref_claims.get("type") == "refresh", f"type={ref_claims.get('type')}")
record("1", "refresh same sid as access", ref_claims.get("sid") == acc_claims.get("sid"),
       f"acc={acc_claims.get('sid')} ref={ref_claims.get('sid')}")
ref_exp_delta = int(ref_claims.get("exp", 0)) - now
record("1", "refresh exp ~7 days",
       6 * 86400 <= ref_exp_delta <= 8 * 86400, f"delta={ref_exp_delta}s")
r = me(T1)
record("1", "access → /auth/me = 200", r.status_code == 200, f"http={r.status_code}")


# ───────────────────────── 2) REFRESH ROTATION ────────────────────
print("\n=== SECTION 2: /auth/refresh ROTATION ===")
r = requests.post(f"{BASE}/auth/refresh", json={"refresh_token": RT1}, timeout=30)
record("2", "POST /auth/refresh valid = 200", r.status_code == 200, f"http={r.status_code} body={r.text[:200]}")
T2 = None
if r.status_code == 200:
    refbody = r.json()
    record("2", "has new token", "token" in refbody, "")
    record("2", "has new refresh_token", "refresh_token" in refbody, "")
    T2 = refbody["token"]
    acc2_claims = decode_jwt_payload(T2)
    record("2", "new sid differs",
           acc2_claims.get("sid") and acc2_claims.get("sid") != acc_claims.get("sid"),
           f"old={acc_claims.get('sid')} new={acc2_claims.get('sid')}")

    r2 = me(T1)
    d = ""
    try:
        d = r2.json().get("detail", "")
    except Exception:
        pass
    record("2", "OLD access T1 → 401 session_revoked",
           r2.status_code == 401 and d == "session_revoked", f"http={r2.status_code} detail={d}")

    r3 = me(T2)
    record("2", "NEW access T2 → 200", r3.status_code == 200, f"http={r3.status_code}")

    r4 = requests.post(f"{BASE}/auth/refresh", json={"refresh_token": RT1}, timeout=30)
    d4 = ""
    try:
        d4 = r4.json().get("detail", "")
    except Exception:
        pass
    record("2", "OLD refresh RT1 reused → 401",
           r4.status_code == 401 and d4 in ("session_revoked", "refresh_invalid"),
           f"http={r4.status_code} detail={d4}")

r = requests.post(f"{BASE}/auth/refresh", json={"refresh_token": "this.is.garbage"}, timeout=30)
d = ""
try:
    d = r.json().get("detail", "")
except Exception:
    pass
record("2", "garbage → 401 refresh_invalid",
       r.status_code == 401 and d == "refresh_invalid", f"http={r.status_code} detail={d}")

r = requests.post(f"{BASE}/auth/refresh", json={"refresh_token": "abc"}, timeout=30)
d = ""
try:
    d = r.json().get("detail", "")
except Exception:
    pass
record("2", "malformed → 401",
       r.status_code == 401 and d in ("refresh_invalid", "refresh_expired"),
       f"http={r.status_code} detail={d}")


# ───────────────────────── 3) SINGLE-SESSION ──────────────────────
print("\n=== SECTION 3: SINGLE-SESSION ===")
r_a = login(*TESTUSER)
record("3", "login #1 = 200", r_a.status_code == 200, f"http={r_a.status_code}")
T_A = r_a.json()["token"]
time.sleep(0.5)
r_b = login(*TESTUSER)
record("3", "login #2 = 200", r_b.status_code == 200, f"http={r_b.status_code}")
T_B = r_b.json()["token"]

r1 = me(T_A)
d = ""
try:
    d = r1.json().get("detail", "")
except Exception:
    pass
record("3", "T1 → 401 session_revoked",
       r1.status_code == 401 and d == "session_revoked", f"http={r1.status_code} detail={d}")
r2 = me(T_B)
record("3", "T2 → 200", r2.status_code == 200, f"http={r2.status_code}")


# ───────────────────────── 4) LOGOUT ──────────────────────────────
print("\n=== SECTION 4: LOGOUT INVALIDATES ===")
r = login(*TESTUSER)
T = r.json()["token"]
rm = me(T)
record("4", "fresh T → /auth/me = 200", rm.status_code == 200, f"http={rm.status_code}")
rl = requests.post(f"{BASE}/auth/logout", headers={"Authorization": f"Bearer {T}"}, timeout=30)
record("4", "POST /auth/logout = 200", rl.status_code == 200, f"http={rl.status_code}")
rmm = me(T)
d = ""
try:
    d = rmm.json().get("detail", "")
except Exception:
    pass
record("4", "T after logout → 401 session_revoked",
       rmm.status_code == 401 and d == "session_revoked", f"http={rmm.status_code} detail={d}")


# ───────────────────────── 5) DEVICE FINGERPRINT ──────────────────
print("\n=== SECTION 5: DEVICE FINGERPRINT ===")
r = login(*TESTUSER)
T = r.json()["token"]
rA = me(T, {"X-Device-FP": "fp-A-1234567890123456"})
record("5", "FP-A → 200", rA.status_code == 200, f"http={rA.status_code}")
rB = me(T, {"X-Device-FP": "fp-B-9999999999999999"})
record("5", "FP-B (different) → 200 (no block)",
       rB.status_code == 200, f"http={rB.status_code}")

ra = login(*ADMIN)
record("5", "admin login = 200", ra.status_code == 200, f"http={ra.status_code}")
ADMIN_T = ra.json()["token"] if ra.status_code == 200 else ""
time.sleep(1)
rs = requests.get(
    f"{BASE}/admin/security-events",
    params={"action": "auth.device_change", "email": "testuser@app.com", "limit": 20},
    headers={"Authorization": f"Bearer {ADMIN_T}"},
    timeout=30,
)
record("5", "GET /admin/security-events = 200", rs.status_code == 200, f"http={rs.status_code}")
if rs.status_code == 200:
    items = rs.json().get("items", [])
    found = None
    for ev in items:
        det = ev.get("details") or {}
        if ev.get("severity") == "warning" and det.get("previous_fp") and det.get("new_fp"):
            found = ev
            break
    record("5", "device_change event with truncated previous_fp + new_fp + severity=warning",
           found is not None,
           f"count={len(items)} sample_details={(items[0].get('details') if items else None)}")


# ───────────────────────── 6) RATE LIMIT ──────────────────────────
print("\n=== SECTION 6: RATE LIMIT /auth/refresh ===")
hit_429 = False
last_resp = None
last_body = None
count_to_429 = 0
for i in range(40):
    r = requests.post(f"{BASE}/auth/refresh", json={"refresh_token": "garbage"}, timeout=10)
    count_to_429 = i + 1
    if r.status_code == 429:
        hit_429 = True
        last_resp = r
        try:
            last_body = r.json()
        except Exception:
            last_body = r.text[:300]
        break
    last_resp = r
record("6", ">30 rapid /auth/refresh calls → 429",
       hit_429, f"hit_at_call={count_to_429} body={last_body}")
if hit_429:
    record("6", "429 body is JSON dict (friendly shape)",
           isinstance(last_body, dict), f"body={last_body}")


# ───────────────────────── 7) BACKWARDS-COMPAT ────────────────────
print("\n=== SECTION 7: BACKWARDS-COMPAT (missing field) ===")
time.sleep(3)
r = requests.post(f"{BASE}/auth/refresh", json={}, timeout=30)
d = ""
try:
    d = r.json().get("detail", "")
except Exception:
    pass
record("7", "missing refresh_token → 401 or 422",
       r.status_code in (401, 422), f"http={r.status_code} detail={d}")


# ───────────────────────── 8) NO REGRESSIONS ──────────────────────
print("\n=== SECTION 8: NO REGRESSIONS ===")
r = requests.get(f"{BASE}/products", timeout=30)
record("8", "GET /products anon = 200", r.status_code == 200, f"http={r.status_code}")

r = requests.get(f"{BASE}/branding", timeout=30)
record("8", "GET /branding = 200", r.status_code == 200, f"http={r.status_code}")

ra = login(*ADMIN)
if ra.status_code == 200:
    ADMIN_T = ra.json()["token"]
r = requests.get(f"{BASE}/admin/audit-logs", headers={"Authorization": f"Bearer {ADMIN_T}"}, timeout=30)
record("8", "GET /admin/audit-logs (admin) = 200", r.status_code == 200, f"http={r.status_code}")

r = login(*ADMIN)
record("8", "admin can still log in", r.status_code == 200, f"http={r.status_code}")


# ─────────── REPORT ───────────
print("\n=== FINAL REPORT ===")
total = len(results)
passed = sum(1 for (_, _, p, _) in results if p)
failed = total - passed
print(f"\nTOTAL: {passed}/{total} passed ({failed} failed)")
if failed:
    print("\nFAILED:")
    for (s, n, p, d) in results:
        if not p:
            print(f"  [{s}] {n} — {d}")
sys.exit(0 if failed == 0 else 1)
