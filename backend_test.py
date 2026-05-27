"""
Phase 3 Session A — Anti-tampering integrity reporting tests.

Tests /api/security/integrity-report verdict matrix + per-action guards on
financial endpoints (withdrawals + upi-manual). Read-only — no code changes.
"""
import os
import sys
import time
import json
import requests

BASE = os.environ.get("BACKEND_URL", "https://vendor-network-app-1.preview.emergentagent.com") + "/api"

ADMIN_EMAIL = "admin@app.com"
ADMIN_PW = "Admin@123"
USER_EMAIL = "testuser@app.com"
USER_PW = "Test@123"
QR_EMAIL = "qrtest@app.com"
QR_PW = "Qr@1234"

PASSES = []
FAILS = []


def ok(name, msg=""):
    PASSES.append(name)
    print(f"  ✅ {name}  {msg}")


def fail(name, msg=""):
    FAILS.append(f"{name}: {msg}")
    print(f"  ❌ {name}  {msg}")


def login(email, pw):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": pw}, timeout=20)
    if r.status_code == 429:
        print(f"   ⏳ 429 on login; sleeping 60s then retrying…")
        time.sleep(60)
        r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": pw}, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"Login failed for {email}: {r.status_code} {r.text}")
    j = r.json()
    return j.get("token") or j.get("access_token"), j.get("refresh_token"), j.get("user", {})


def post(path, token, body=None):
    h = {"Authorization": f"Bearer {token}"} if token else {}
    r = requests.post(f"{BASE}{path}", json=body or {}, headers=h, timeout=20)
    if r.status_code == 429:
        print(f"   ⏳ 429 on {path}; sleeping 65s…")
        time.sleep(65)
        r = requests.post(f"{BASE}{path}", json=body or {}, headers=h, timeout=20)
    return r


def get(path, token=None):
    h = {"Authorization": f"Bearer {token}"} if token else {}
    return requests.get(f"{BASE}{path}", headers=h, timeout=20)


def integrity_report(token, checks, build_type="dev-client", os_name="ios"):
    return post("/security/integrity-report", token, {
        "checks": checks,
        "build_type": build_type,
        "app_version": "1.0.0",
        "os": os_name,
    })


# ────────── LOGIN ALL THREE (single login each, rate-limit safe) ──────────
print("\n[BOOT] Logging in 3 accounts (single login each to respect 10/min rate limit)")
admin_tok, _, _ = login(ADMIN_EMAIL, ADMIN_PW)
print(f"  admin token len={len(admin_tok)}")
user_tok, user_refresh, user_doc = login(USER_EMAIL, USER_PW)
print(f"  testuser token len={len(user_tok)}")
qr_tok, _, qr_doc = login(QR_EMAIL, QR_PW)
print(f"  qrtest token len={len(qr_tok)}")


# ────────── TEST 1: BASIC ENDPOINT FLOW ──────────
print("\n[TEST 1] Basic endpoint flow")
r = integrity_report(user_tok, [])
if r.status_code == 200:
    j = r.json()
    if j.get("ok") is True and j.get("block_level") == "none" and j.get("reasons") == []:
        ok("1.1 empty checks → 200 + none/[]")
    else:
        fail("1.1 empty checks shape", f"got {j}")
else:
    fail("1.1 empty checks HTTP", f"{r.status_code} {r.text}")

r = requests.post(f"{BASE}/security/integrity-report", json={"checks": []}, timeout=20)
if r.status_code in (401, 403):
    ok(f"1.2 no auth → {r.status_code}")
else:
    fail("1.2 no auth", f"got {r.status_code} {r.text}")


# ────────── TEST 2: VERDICT MATRIX ──────────
print("\n[TEST 2] Verdict matrix (per-check severity ladder)")
matrix = [
    ("2a root_jailbreak",   [{"name": "root_jailbreak",  "passed": False, "available": True}], "read_only"),
    ("2b play_integrity",   [{"name": "play_integrity",  "passed": False, "available": True}], "hard_block"),
    ("2c ssl_pin",          [{"name": "ssl_pin",         "passed": False, "available": True}], "hard_block"),
    ("2d emulator",         [{"name": "emulator",        "passed": False, "available": True}], "warn"),
    ("2e developer_mode",   [{"name": "developer_mode",  "passed": False, "available": True}], "warn"),
    ("2f apk_signature",    [{"name": "apk_signature",   "passed": False, "available": True}], "hard_block"),
    ("2g available=false",  [{"name": "root_jailbreak",  "passed": False, "available": False}], "none"),
    ("2h mix emu+root",     [{"name": "emulator", "passed": False, "available": True},
                             {"name": "root_jailbreak", "passed": False, "available": True}], "read_only"),
    ("2i mix root+ssl",     [{"name": "root_jailbreak", "passed": False, "available": True},
                             {"name": "ssl_pin", "passed": False, "available": True}], "hard_block"),
]
for name, checks, expected in matrix:
    r = integrity_report(user_tok, checks)
    if r.status_code != 200:
        fail(name, f"HTTP {r.status_code} {r.text}")
        continue
    j = r.json()
    got = j.get("block_level")
    if got == expected:
        reasons = j.get("reasons") or []
        # for 2h verify both reasons present
        if name.startswith("2h"):
            has_emu = any("emulator" in s for s in reasons)
            has_root = any("root_jailbreak" in s for s in reasons)
            if has_emu and has_root:
                ok(name, f"block_level={got} reasons=both")
            else:
                fail(name, f"reasons missing one: {reasons}")
        else:
            ok(name, f"block_level={got}")
    else:
        fail(name, f"expected {expected}, got {got}; full={j}")


# ────────── TEST 3: PER-ACTION GUARD on /withdrawals ──────────
print("\n[TEST 3] Per-action guard — /api/withdrawals (testuser)")
# Step A: dirty (ssl_pin → hard_block)
r = integrity_report(user_tok, [{"name": "ssl_pin", "passed": False, "available": True}])
if r.status_code == 200 and r.json().get("block_level") == "hard_block":
    ok("3.0 dirty report applied")
else:
    fail("3.0 dirty report", f"{r.status_code} {r.text}")

# /withdrawals → expect 403 device_compromised
r = post("/withdrawals", user_tok, {"amount": 100})
print(f"   withdrawals after dirty: {r.status_code} {r.text[:300]}")
if r.status_code == 403:
    try:
        detail = r.json().get("detail")
        if isinstance(detail, dict) and detail.get("code") == "device_compromised" and detail.get("block_level") == "hard_block":
            ok("3.1 dirty → 403 device_compromised hard_block")
        else:
            fail("3.1 dirty → 403 shape", f"detail={detail}")
    except Exception as e:
        fail("3.1 dirty → 403 shape", f"json err {e} / body {r.text[:200]}")
else:
    fail("3.1 dirty withdrawal", f"expected 403, got {r.status_code} {r.text[:200]}")

# Step B: clean report
r = integrity_report(user_tok, [])
if r.status_code == 200 and r.json().get("block_level") == "none":
    ok("3.2 clean report applied")
else:
    fail("3.2 clean report", f"{r.status_code} {r.text}")

# /withdrawals after clean → must NOT be 403 device_compromised
r = post("/withdrawals", user_tok, {"amount": 100})
print(f"   withdrawals after clean: {r.status_code} {r.text[:300]}")
if r.status_code == 403:
    try:
        detail = r.json().get("detail")
        if isinstance(detail, dict) and detail.get("code") == "device_compromised":
            fail("3.3 clean withdrawal", f"STILL device_compromised: {detail}")
        else:
            ok("3.3 clean withdrawal", f"403 but NOT device_compromised: {detail}")
    except Exception:
        ok("3.3 clean withdrawal", f"403 with str body (not device_compromised JSON)")
else:
    # 400 (insufficient balance / no upi) or 200 — all fine, guard released
    ok("3.3 clean withdrawal", f"non-403 ({r.status_code}) — guard released")


# ────────── TEST 3b: /payment/upi-manual with qrtest ──────────
print("\n[TEST 3b] Per-action guard — /api/payment/upi-manual (qrtest)")
r = integrity_report(qr_tok, [{"name": "ssl_pin", "passed": False, "available": True}])
if r.status_code == 200 and r.json().get("block_level") == "hard_block":
    ok("3b.0 dirty report (qrtest) applied")
else:
    fail("3b.0 dirty report (qrtest)", f"{r.status_code} {r.text}")

r = post("/payment/upi-manual", qr_tok, {"utr": "FAKEUTR99TEST", "app_used": "gpay"})
print(f"   upi-manual after dirty: {r.status_code} {r.text[:300]}")
if r.status_code == 403:
    try:
        detail = r.json().get("detail")
        if isinstance(detail, dict) and detail.get("code") == "device_compromised":
            ok("3b.1 dirty upi-manual → 403 device_compromised")
        else:
            fail("3b.1 dirty upi-manual shape", f"detail={detail}")
    except Exception as e:
        fail("3b.1 dirty upi-manual shape", f"json err {e}")
else:
    fail("3b.1 dirty upi-manual", f"expected 403, got {r.status_code} {r.text[:200]}")

# clean for qrtest
r = integrity_report(qr_tok, [])
if r.status_code == 200 and r.json().get("block_level") == "none":
    ok("3b.2 clean report (qrtest) applied")
else:
    fail("3b.2 clean report (qrtest)", f"{r.status_code} {r.text}")

r = post("/payment/upi-manual", qr_tok, {"utr": "FAKEUTR99TEST", "app_used": "gpay"})
print(f"   upi-manual after clean: {r.status_code} {r.text[:300]}")
if r.status_code == 403:
    try:
        detail = r.json().get("detail")
        if isinstance(detail, dict) and detail.get("code") == "device_compromised":
            fail("3b.3 clean upi-manual", f"STILL device_compromised: {detail}")
        else:
            ok("3b.3 clean upi-manual", f"403 but NOT device_compromised")
    except Exception:
        ok("3b.3 clean upi-manual", "403 non-JSON device_compromised")
else:
    ok("3b.3 clean upi-manual", f"non-device-compromised ({r.status_code})")


# ────────── TEST 4: read_only blocks finances ──────────
print("\n[TEST 4] read_only also blocks finances (testuser, root_jailbreak)")
r = integrity_report(user_tok, [{"name": "root_jailbreak", "passed": False, "available": True}])
if r.status_code == 200 and r.json().get("block_level") == "read_only":
    ok("4.0 read_only report applied")
else:
    fail("4.0 read_only report", f"{r.status_code} {r.text}")

r = post("/withdrawals", user_tok, {"amount": 100})
print(f"   withdrawals read_only: {r.status_code} {r.text[:300]}")
if r.status_code == 403:
    try:
        detail = r.json().get("detail")
        if isinstance(detail, dict) and detail.get("code") == "device_compromised" and detail.get("block_level") == "read_only":
            ok("4.1 read_only → 403 device_compromised read_only")
        else:
            fail("4.1 read_only shape", f"detail={detail}")
    except Exception as e:
        fail("4.1 read_only shape", f"json err {e}")
else:
    fail("4.1 read_only withdrawal", f"expected 403 got {r.status_code} {r.text[:200]}")

# restore clean for testuser
r = integrity_report(user_tok, [])
if r.status_code == 200 and r.json().get("block_level") == "none":
    ok("4.2 clean report after read_only applied")
else:
    fail("4.2 clean report after read_only", f"{r.status_code} {r.text}")


# ────────── TEST 5: SECURITY EVENTS LOG ──────────
print("\n[TEST 5] Security events log (admin view)")
r = get("/admin/security-events?action=integrity.hard_block&limit=5", admin_tok)
if r.status_code == 200:
    j = r.json()
    items = j.get("items") or []
    if len(items) >= 1 and items[0].get("severity") == "critical":
        details = items[0].get("details") or {}
        if isinstance(details.get("reasons"), list):
            ok("5.1 hard_block events present", f"n={len(items)} sev=critical reasons={details.get('reasons')}")
        else:
            fail("5.1 hard_block details.reasons", f"got {details}")
    else:
        fail("5.1 hard_block events", f"count={len(items)} first={items[:1]}")
else:
    fail("5.1 hard_block events HTTP", f"{r.status_code} {r.text}")

r = get("/admin/security-events?action=integrity.read_only&limit=5", admin_tok)
if r.status_code == 200:
    j = r.json()
    items = j.get("items") or []
    if len(items) >= 1 and items[0].get("severity") == "warning":
        ok("5.2 read_only events present", f"n={len(items)} sev=warning")
    else:
        fail("5.2 read_only events", f"count={len(items)} first={items[:1]}")
else:
    fail("5.2 read_only events HTTP", f"{r.status_code} {r.text}")

# 5.3 clean reports should NOT create events
r_before = get("/admin/security-events?limit=1000", admin_tok)
count_before = len((r_before.json() or {}).get("items") or [])
r2 = integrity_report(user_tok, [])
r_after = get("/admin/security-events?limit=1000", admin_tok)
count_after = len((r_after.json() or {}).get("items") or [])
if count_after == count_before:
    ok("5.3 clean report writes NO event", f"count_before={count_before} after={count_after}")
else:
    fail("5.3 clean report event-noise", f"before={count_before} after={count_after} (delta {count_after-count_before})")


# ────────── TEST 6: USER DOC STAMP via /auth/me ──────────
print("\n[TEST 6] User doc integrity_status stamp")
# We just stamped clean above. Submit one dirty, then check, then clean, then check.
r = integrity_report(user_tok, [{"name": "ssl_pin", "passed": False, "available": True}])
ok("6.0 dirty report queued") if r.status_code == 200 else fail("6.0 dirty", r.text)

r = get("/auth/me", user_tok)
if r.status_code == 200:
    j = r.json()
    # serialize_user wraps as `user`? Let me check both shapes
    if "user" in j:
        u = j["user"]
    else:
        u = j
    integ = u.get("integrity_status") or {}
    if integ.get("block_level") == "hard_block" and isinstance(integ.get("reasons"), list) and integ.get("last_check_at") and "build_type" in integ and "os" in integ:
        ok("6.1 dirty → user.integrity_status populated", f"block_level={integ.get('block_level')} reasons={integ.get('reasons')}")
    else:
        fail("6.1 integrity_status fields", f"got {integ}")
else:
    fail("6.1 /auth/me", f"{r.status_code} {r.text}")

# clean and re-check
r = integrity_report(user_tok, [])
ok("6.2 clean report queued") if r.status_code == 200 else fail("6.2 clean", r.text)
r = get("/auth/me", user_tok)
if r.status_code == 200:
    u = r.json().get("user") or r.json()
    integ = u.get("integrity_status") or {}
    if integ.get("block_level") == "none":
        ok("6.3 clean → integrity_status.block_level=none")
    else:
        fail("6.3 integrity_status clean", f"got {integ}")
else:
    fail("6.3 /auth/me clean", f"{r.status_code} {r.text}")


# ────────── TEST 7: BACKWARDS-COMPAT (legacy user never reported) ──────────
print("\n[TEST 7] Backwards-compat: admin has never reported integrity")
# Admin should not have integrity_status set OR have block_level=none (since
# admin hasn't called integrity-report this session, ideally no field at all,
# but at minimum non-blocking).
r = get("/auth/me", admin_tok)
if r.status_code == 200:
    u = r.json().get("user") or r.json()
    integ = u.get("integrity_status")
    print(f"   admin.integrity_status = {integ}")

# /withdrawals should NOT be 403 device_compromised (admin has wallet so other errors fine)
r = post("/withdrawals", admin_tok, {"amount": 100})
print(f"   admin /withdrawals: {r.status_code} {r.text[:300]}")
if r.status_code == 403:
    try:
        detail = r.json().get("detail")
        if isinstance(detail, dict) and detail.get("code") == "device_compromised":
            fail("7.1 admin (no integrity report) blocked", f"detail={detail}")
        else:
            ok("7.1 admin not device_compromised", f"403 but other reason: {detail}")
    except Exception:
        ok("7.1 admin not device_compromised", "403 non-JSON")
else:
    ok("7.1 admin not device_compromised", f"got {r.status_code} (NOT device_compromised)")


# ────────── TEST 8: NO REGRESSIONS ──────────
print("\n[TEST 8] No regressions")
# 8.1 /auth/refresh works
r = requests.post(f"{BASE}/auth/refresh", json={"refresh_token": user_refresh}, timeout=20)
if r.status_code == 200 and r.json().get("token"):
    ok("8.1 /auth/refresh still works", f"new token len={len(r.json()['token'])}")
else:
    fail("8.1 /auth/refresh", f"{r.status_code} {r.text}")

# 8.2 pagination on /admin/users
r = get("/admin/users?limit=5&offset=0", admin_tok)
if r.status_code == 200:
    items = r.json() if isinstance(r.json(), list) else r.json().get("items") or []
    if len(items) <= 5:
        ok("8.2 /admin/users pagination", f"len={len(items)}")
    else:
        fail("8.2 /admin/users pagination", f"len {len(items)} > 5")
else:
    fail("8.2 /admin/users", f"{r.status_code} {r.text[:200]}")

# 8.3 /auth/login 429 after 10/min — we already burned 3 logins at start.
# To verify rate-limit, fire 12 BAD logins rapidly. If 429 appears anywhere, pass.
print("   Firing 12 bad logins to verify 10/min rate-limit…")
seen_429 = False
for i in range(12):
    rr = requests.post(f"{BASE}/auth/login", json={"email": "ratelimit_probe@nx.com", "password": "x"}, timeout=10)
    if rr.status_code == 429:
        seen_429 = True
        print(f"      attempt {i+1}: 429 ✓")
        break
    print(f"      attempt {i+1}: {rr.status_code}")
if seen_429:
    ok("8.3 /auth/login rate-limit 10/min")
else:
    fail("8.3 /auth/login rate-limit", "no 429 in 12 attempts")


# ─────────────── SUMMARY ───────────────
print("\n" + "=" * 60)
print(f"PASSED: {len(PASSES)}")
print(f"FAILED: {len(FAILS)}")
if FAILS:
    print("\nFailures:")
    for f in FAILS:
        print(f"  • {f}")
sys.exit(0 if not FAILS else 1)
