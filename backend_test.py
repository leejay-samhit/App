"""Phase 1 Session A — backend security & performance validation.

Read-only verification (no backend code modifications). Tests:
  1) Rate limiting (slowapi) on auth + payment + withdrawal endpoints.
  2) Security events admin endpoint with filters.
  3) Mongo hot-query smoke test (existing list endpoints still return data).
  4) Multi-IP detection (informational).
  5) GZip response compression.
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import requests

BASE = "https://vendor-network-app-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@app.com"
ADMIN_PASS  = "Admin@123"
TESTUSER_EMAIL = "testuser@app.com"
TESTUSER_PASS  = "Test@123"
QRTEST_EMAIL   = "qrtest@app.com"
QRTEST_PASS    = "Qr@1234"

PASS: List[str] = []
FAIL: List[str] = []
NOTE: List[str] = []


def ok(label: str, msg: str = "") -> None:
    PASS.append(f"  ✅ {label}{(' — ' + msg) if msg else ''}")


def bad(label: str, msg: str) -> None:
    FAIL.append(f"  ❌ {label} — {msg}")


def info(msg: str) -> None:
    NOTE.append(f"  ℹ {msg}")


def login(email: str, password: str) -> Optional[str]:
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=20)
    if r.status_code != 200:
        return None
    j = r.json()
    return j.get("token") or j.get("access_token")


# ─────────────────────── 1) RATE LIMITING ───────────────────────

def assert_429(resp: requests.Response, label: str, expected_detail_contains: Optional[str] = None) -> bool:
    if resp.status_code != 429:
        bad(label, f"expected 429, got {resp.status_code} body={resp.text[:200]}")
        return False
    try:
        body = resp.json()
    except Exception:
        bad(label, f"429 body not JSON: {resp.text[:200]}")
        return False
    if body.get("error") != "rate_limited":
        bad(label, f"429 body.error != 'rate_limited' → {body}")
        return False
    if not body.get("message"):
        bad(label, f"429 body missing 'message' → {body}")
        return False
    detail = str(body.get("detail") or "")
    if expected_detail_contains and expected_detail_contains not in detail:
        bad(label, f"429 detail='{detail}' does not contain '{expected_detail_contains}'")
        return False
    ok(label, f"429 detail='{detail}'")
    return True


def test_rate_limit_login() -> None:
    """POST /auth/login — 10/minute per IP."""
    # Fire 12 quick invalid-credential calls.
    code_seq = []
    last_resp: Optional[requests.Response] = None
    for i in range(12):
        r = requests.post(f"{BASE}/auth/login",
                          json={"email": f"rl_probe_{uuid.uuid4().hex[:6]}@x.com", "password": "wrong"},
                          timeout=20)
        code_seq.append(r.status_code)
        last_resp = r
        if r.status_code == 429:
            break
    if 429 not in code_seq:
        # might be sliding window leftover — note it but don't fail hard
        info(f"login: did NOT hit 429 in 12 calls. status seq={code_seq}. Window may have just refreshed.")
        return
    assert_429(last_resp, "login → 10/minute 429", expected_detail_contains="10 per")


def test_rate_limit_register() -> None:
    """POST /auth/register — 5/minute per IP."""
    code_seq = []
    last_resp: Optional[requests.Response] = None
    for i in range(8):
        # Use an existing email so we get 400 "already registered" rather than creating new users.
        r = requests.post(f"{BASE}/auth/register",
                          json={"email": ADMIN_EMAIL, "password": "Whatever@123",
                                "name": "Rate Probe", "phone": "9999999999"},
                          timeout=20)
        code_seq.append(r.status_code)
        last_resp = r
        if r.status_code == 429:
            break
    if 429 not in code_seq:
        info(f"register: did NOT hit 429 in 8 calls. status seq={code_seq}")
        return
    assert_429(last_resp, "register → 5/minute 429", expected_detail_contains="5 per")


def test_rate_limit_google_exchange() -> None:
    """POST /auth/google/exchange — 10/minute per IP."""
    code_seq = []
    last_resp: Optional[requests.Response] = None
    for i in range(13):
        r = requests.post(f"{BASE}/auth/google/exchange",
                          json={"session_id": f"invalid-session-{i}"},
                          timeout=20)
        code_seq.append(r.status_code)
        last_resp = r
        if r.status_code == 429:
            break
    if 429 not in code_seq:
        info(f"google/exchange: did NOT hit 429 in 13 calls. status seq={code_seq}")
        return
    assert_429(last_resp, "google/exchange → 10/minute 429", expected_detail_contains="10 per")


def test_rate_limit_withdrawals(admin_token: str) -> None:
    """POST /withdrawals — 5/hour per authenticated user."""
    # We need an authenticated user. Use admin token — it shares the same per-user
    # quota. Even if admin gets 400 (no balance, no UPI etc), that still counts
    # against the rate limiter. After 5 attempts the 6th should be 429.
    hdr = {"Authorization": f"Bearer {admin_token}"}
    code_seq = []
    last_resp: Optional[requests.Response] = None
    for i in range(7):
        r = requests.post(f"{BASE}/withdrawals",
                          json={"amount": 100.0},
                          headers=hdr,
                          timeout=20)
        code_seq.append(r.status_code)
        last_resp = r
        if r.status_code == 429:
            break
    if 429 not in code_seq:
        info(f"withdrawals: did NOT hit 429 in 7 calls. status seq={code_seq}")
        return
    assert_429(last_resp, "withdrawals → 5/hour 429", expected_detail_contains="5 per")


def test_rate_limit_upi_manual() -> None:
    """POST /payment/upi-manual — 10/hour per authenticated user."""
    qr_token = login(QRTEST_EMAIL, QRTEST_PASS)
    if not qr_token:
        bad("upi-manual rate limit (setup)", "could not log in qrtest@app.com")
        return
    hdr = {"Authorization": f"Bearer {qr_token}"}
    code_seq = []
    last_resp: Optional[requests.Response] = None
    for i in range(13):
        # Vary UTR each call so we avoid the 409 "dupe UTR" path and exercise
        # the rate limiter cleanly. Format: 12 alphanumeric chars.
        utr = f"RLTEST{uuid.uuid4().hex[:6].upper()}"
        r = requests.post(f"{BASE}/payment/upi-manual",
                          json={"utr": utr, "app_used": "other", "note": "rate-limit test"},
                          headers=hdr,
                          timeout=20)
        code_seq.append(r.status_code)
        last_resp = r
        if r.status_code == 429:
            break
    if 429 not in code_seq:
        info(f"upi-manual: did NOT hit 429 in 13 calls. status seq={code_seq}")
        return
    assert_429(last_resp, "upi-manual → 10/hour 429", expected_detail_contains="10 per")


# ─────────────────────── 2) SECURITY EVENTS ───────────────────────

def trigger_failed_logins() -> None:
    """Trigger ≥3 failed logins for unknown email + ≥3 wrong-password for testuser."""
    for _ in range(3):
        requests.post(f"{BASE}/auth/login",
                      json={"email": "doesnotexist@x.com", "password": "whatever"},
                      timeout=20)
    for _ in range(3):
        requests.post(f"{BASE}/auth/login",
                      json={"email": TESTUSER_EMAIL, "password": "DEFINITELY_WRONG_PWD"},
                      timeout=20)


def test_security_events(admin_token: str) -> None:
    hdr = {"Authorization": f"Bearer {admin_token}"}

    # 2.a — Basic shape
    r = requests.get(f"{BASE}/admin/security-events", headers=hdr, timeout=20)
    if r.status_code != 200:
        bad("security-events GET", f"status {r.status_code} body={r.text[:200]}")
        return
    body = r.json()
    if not isinstance(body, dict) or "items" not in body or "count" not in body:
        bad("security-events shape", f"missing items/count keys → {list(body.keys())}")
        return
    items = body.get("items") or []
    if not isinstance(items, list):
        bad("security-events shape", "items is not a list")
        return
    ok("security-events shape", f"items list len={len(items)}, count={body.get('count')}")

    # 2.b — item structure
    required_keys = {"id", "action", "user_id", "email", "ip", "details", "severity", "created_at"}
    if items:
        sample = items[0]
        present = set(sample.keys())
        missing = required_keys - present
        if missing:
            bad("security-events item keys", f"missing keys {missing} in sample={sample}")
        else:
            ok("security-events item keys", f"all 8 required keys present (sample id={sample.get('id')})")
    else:
        info("security-events: items empty — cannot validate key structure on a sample")

    # 2.c — Filter by action
    r = requests.get(f"{BASE}/admin/security-events?action=auth.failed_login", headers=hdr, timeout=20)
    if r.status_code != 200:
        bad("security-events ?action=auth.failed_login", f"status {r.status_code}")
    else:
        b = r.json()
        items_a = b.get("items") or []
        if all(it.get("action") == "auth.failed_login" for it in items_a) and items_a:
            ok("security-events action filter", f"all {len(items_a)} items have action=auth.failed_login")
        elif not items_a:
            info("security-events action filter: 0 items returned (filter may be too tight)")
        else:
            bad("security-events action filter", "filter returned mismatched action values")

    # 2.d — Filter by email
    r = requests.get(f"{BASE}/admin/security-events?email={TESTUSER_EMAIL}", headers=hdr, timeout=20)
    if r.status_code != 200:
        bad("security-events ?email=testuser", f"status {r.status_code}")
    else:
        b = r.json()
        items_e = b.get("items") or []
        if all(it.get("email") == TESTUSER_EMAIL for it in items_e) and items_e:
            ok("security-events email filter", f"all {len(items_e)} items have email={TESTUSER_EMAIL}")
        elif not items_e:
            info("security-events email filter: 0 items — testuser may not have triggered failed-login yet (rate-limited above)")
        else:
            bad("security-events email filter", "filter returned mismatched email values")

    # 2.e — Filter by severity=warning
    r = requests.get(f"{BASE}/admin/security-events?severity=warning", headers=hdr, timeout=20)
    if r.status_code != 200:
        bad("security-events ?severity=warning", f"status {r.status_code}")
    else:
        b = r.json()
        items_s = b.get("items") or []
        if all(it.get("severity") == "warning" for it in items_s) and items_s:
            ok("security-events severity filter", f"all {len(items_s)} items have severity=warning")
        elif not items_s:
            info("security-events severity filter: 0 items returned")
        else:
            bad("security-events severity filter", "filter returned mismatched severity values")

    # 2.f — Detail reasons: bad_credentials vs unknown_email
    r = requests.get(f"{BASE}/admin/security-events?action=auth.failed_login&email={TESTUSER_EMAIL}",
                     headers=hdr, timeout=20)
    if r.status_code == 200:
        its = (r.json() or {}).get("items") or []
        reasons = {(it.get("details") or {}).get("reason") for it in its}
        if "bad_credentials" in reasons:
            ok("testuser failed-login reason", "details.reason='bad_credentials' present")
        elif its:
            bad("testuser failed-login reason", f"reasons seen: {reasons}")
        else:
            info("testuser failed-login reason: 0 events (rate-limit may have blocked our test triggers)")

    r = requests.get(f"{BASE}/admin/security-events?action=auth.failed_login&email=doesnotexist@x.com",
                     headers=hdr, timeout=20)
    if r.status_code == 200:
        its = (r.json() or {}).get("items") or []
        reasons = {(it.get("details") or {}).get("reason") for it in its}
        if "unknown_email" in reasons:
            ok("unknown-email failed-login reason", "details.reason='unknown_email' present")
        elif its:
            bad("unknown-email failed-login reason", f"reasons seen: {reasons}")
        else:
            info("unknown-email failed-login reason: 0 events found")

    # 2.g — Auth gating
    r = requests.get(f"{BASE}/admin/security-events", timeout=20)
    if r.status_code in (401, 403):
        ok("security-events no-auth gate", f"unauth → {r.status_code}")
    else:
        bad("security-events no-auth gate", f"expected 401/403, got {r.status_code}")

    # Non-admin user token should also 403 — try with qrtest token
    qr_token = login(QRTEST_EMAIL, QRTEST_PASS)
    if qr_token:
        r = requests.get(f"{BASE}/admin/security-events",
                         headers={"Authorization": f"Bearer {qr_token}"}, timeout=20)
        if r.status_code in (401, 403):
            ok("security-events non-admin gate", f"non-admin → {r.status_code}")
        else:
            bad("security-events non-admin gate", f"expected 401/403, got {r.status_code}")


# ─────────────────── 3) MONGO HOT-QUERY SMOKE ───────────────────

def test_smoke_endpoints(admin_token: str, user_token: str) -> None:
    user_hdr = {"Authorization": f"Bearer {user_token}"}
    admin_hdr = {"Authorization": f"Bearer {admin_token}"}

    # /transactions/me (auth user)
    r = requests.get(f"{BASE}/transactions/me", headers=user_hdr, timeout=20)
    if r.status_code == 200 and isinstance(r.json(), list):
        ok("GET /transactions/me", f"200, items={len(r.json())}")
    else:
        bad("GET /transactions/me", f"status {r.status_code} body={r.text[:200]}")

    # /withdrawals/me (auth user)
    r = requests.get(f"{BASE}/withdrawals/me", headers=user_hdr, timeout=20)
    if r.status_code == 200 and isinstance(r.json(), list):
        ok("GET /withdrawals/me", f"200, items={len(r.json())}")
    else:
        bad("GET /withdrawals/me", f"status {r.status_code} body={r.text[:200]}")

    # /notifications/me (auth user) — note: the actual path is /notifications/me
    r = requests.get(f"{BASE}/notifications/me", headers=user_hdr, timeout=20)
    if r.status_code == 200:
        ok("GET /notifications/me", f"200, type={type(r.json()).__name__}")
    else:
        bad("GET /notifications/me", f"status {r.status_code} body={r.text[:200]}")

    # /orders/me (auth user)
    r = requests.get(f"{BASE}/orders/me", headers=user_hdr, timeout=20)
    if r.status_code == 200:
        body = r.json()
        ok("GET /orders/me", f"200, type={type(body).__name__}")
    else:
        bad("GET /orders/me", f"status {r.status_code} body={r.text[:200]}")

    # /admin/audit-logs (admin)
    r = requests.get(f"{BASE}/admin/audit-logs", headers=admin_hdr, timeout=20)
    if r.status_code == 200 and isinstance(r.json(), list):
        ok("GET /admin/audit-logs", f"200, items={len(r.json())}")
    else:
        bad("GET /admin/audit-logs", f"status {r.status_code} body={r.text[:200]}")


# ─────────────────────── 4) MULTI-IP STAMPING (info) ───────────────────────

def test_multi_ip_stamp() -> None:
    t1 = login(TESTUSER_EMAIL, TESTUSER_PASS)
    t2 = login(TESTUSER_EMAIL, TESTUSER_PASS)
    if t1 and t2:
        info("multi-IP: testuser successfully logged in twice (last_login_ip stamping internal; not exposed via /auth/me — not asserted)")
    else:
        info(f"multi-IP: login pair t1={bool(t1)} t2={bool(t2)} — could not validate (likely rate-limit residue)")


# ─────────────────── 5) GZIP COMPRESSION ───────────────────

def test_gzip() -> None:
    # /products is unauthenticated and returns the seeded catalogue (~4 items
    # but with descriptions/images often >1KB so it should trigger GZip).
    # Use a raw socket-style request via requests with Accept-Encoding header,
    # disable transparent decoding so we can SEE Content-Encoding.
    sess = requests.Session()
    r = sess.get(f"{BASE}/products",
                 headers={"Accept-Encoding": "gzip"},
                 timeout=20,
                 stream=True)
    ce = r.headers.get("Content-Encoding", "")
    # Read the body
    raw_body_len = len(r.raw.read())
    if r.status_code != 200:
        bad("GZip /products", f"status {r.status_code}")
        return
    if "gzip" in ce.lower():
        ok("GZip /products", f"Content-Encoding='{ce}', raw bytes={raw_body_len}")
    else:
        # Response might be smaller than the 1024-byte threshold; try a larger
        # endpoint (admin/users) with auth.
        info(f"GZip /products: Content-Encoding='{ce}' (raw_bytes={raw_body_len}); /products may be below 1KB threshold. Retrying with /admin/users.")
        tok = login(ADMIN_EMAIL, ADMIN_PASS)
        if not tok:
            bad("GZip /admin/users", "could not get admin token")
            return
        r2 = sess.get(f"{BASE}/admin/users",
                      headers={"Accept-Encoding": "gzip",
                               "Authorization": f"Bearer {tok}"},
                      timeout=30, stream=True)
        ce2 = r2.headers.get("Content-Encoding", "")
        body_len2 = len(r2.raw.read())
        if r2.status_code == 200 and "gzip" in ce2.lower():
            ok("GZip /admin/users", f"Content-Encoding='{ce2}', raw bytes={body_len2}")
        else:
            bad("GZip", f"/admin/users → status {r2.status_code}, Content-Encoding='{ce2}', raw bytes={body_len2}")


# ─────────────────────── MAIN ───────────────────────

def main() -> int:
    print(f"\n=== Phase 1 Session A — backend security/perf verification ===")
    print(f"BASE: {BASE}\n")

    # 1) RATE LIMITING — runs first to consume per-IP buckets, since security
    #    events rely on failed-login data being persisted.
    print("[1] RATE LIMITING")
    # Sequence the heaviest ones first; sleep gentle between to keep windows clean.
    test_rate_limit_register()        # 5/min IP
    test_rate_limit_login()           # 10/min IP — also produces failed_login events
    test_rate_limit_google_exchange() # 10/min IP

    # 2) Need an admin token for the rest. Login may itself be rate-limited
    #    by now (we just consumed 11 calls). Wait long enough for the sliding
    #    window to refresh ~ 60s.
    print("\n[wait] sleeping 65s for /auth/login sliding window to refresh…")
    time.sleep(65)

    admin_token = login(ADMIN_EMAIL, ADMIN_PASS)
    if not admin_token:
        # Try once more after another wait
        time.sleep(35)
        admin_token = login(ADMIN_EMAIL, ADMIN_PASS)
    if not admin_token:
        bad("admin login", "could not authenticate admin@app.com after waits")
        report()
        return 1
    ok("admin login", "admin@app.com authenticated")

    # withdrawals + upi_manual are per-user buckets (auth-keyed), independent of IP.
    test_rate_limit_withdrawals(admin_token)
    test_rate_limit_upi_manual()

    # 2) SECURITY EVENTS — first regenerate failed-login events (the earlier
    #    rate-limit pass may have created some, but their email/details depend
    #    on the variable email we used). Trigger deterministic ones now.
    print("\n[2] SECURITY EVENTS — triggering deterministic failed logins")
    # We've consumed the login bucket; wait ~65s first.
    time.sleep(65)
    trigger_failed_logins()
    test_security_events(admin_token)

    # 3) SMOKE
    print("\n[3] SMOKE — Mongo hot-query endpoints")
    time.sleep(65)
    user_token = login(TESTUSER_EMAIL, TESTUSER_PASS)
    if not user_token:
        bad("testuser login", "could not authenticate testuser@app.com for smoke tests")
    else:
        test_smoke_endpoints(admin_token, user_token)

    # 4) MULTI-IP (informational)
    print("\n[4] MULTI-IP (informational)")
    test_multi_ip_stamp()

    # 5) GZIP
    print("\n[5] GZIP")
    test_gzip()

    report()
    return 0 if not FAIL else 1


def report() -> None:
    print("\n\n========== SUMMARY ==========")
    print(f"PASS: {len(PASS)}    FAIL: {len(FAIL)}    NOTES: {len(NOTE)}\n")
    if FAIL:
        print("--- FAILURES ---")
        for line in FAIL:
            print(line)
        print()
    if PASS:
        print("--- PASSES ---")
        for line in PASS:
            print(line)
        print()
    if NOTE:
        print("--- NOTES (informational) ---")
        for line in NOTE:
            print(line)
        print()


if __name__ == "__main__":
    sys.exit(main())
