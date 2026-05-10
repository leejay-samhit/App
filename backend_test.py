"""Phase 2B refactor regression test.

Tests the 6 extracted endpoints + a few sanity checks on unrelated endpoints.
"""
from __future__ import annotations

import os
import sys
from typing import Dict

import requests

BASE = os.environ.get("BACKEND_URL", "https://network-pay-1.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"

ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"

TIMEOUT = 30
results = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    icon = "PASS" if ok else "FAIL"
    print(f"[{icon}] {name}" + (f" — {detail}" if detail else ""))


def login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()["token"]


def auth(tok: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


def main() -> int:
    try:
        admin_tok = login(ADMIN_EMAIL, ADMIN_PASSWORD)
        record("POST /auth/login (admin)", True, "200 OK")
    except Exception as e:
        record("POST /auth/login (admin)", False, f"login failed: {e}")
        return 1

    # ---------- 1) GET /api/branding (public) ----------
    try:
        r = requests.get(f"{API}/branding", timeout=TIMEOUT)
        ok = r.status_code == 200
        body = r.json() if ok else {}
        required_keys = {"app_name", "tagline", "colors", "font", "tabs"}
        missing = required_keys - set(body.keys())
        if ok and not missing:
            record("GET /branding", True, f"keys ok, app_name={body.get('app_name')!r}")
        else:
            record("GET /branding", False, f"status={r.status_code} missing={missing} body={r.text[:300]}")
    except Exception as e:
        record("GET /branding", False, str(e))

    # ---------- 2) PUT /api/admin/branding (super_admin partial update) ----------
    new_tagline = "refactor regression test"
    try:
        r = requests.put(
            f"{API}/admin/branding",
            json={"tagline": new_tagline},
            headers=auth(admin_tok),
            timeout=TIMEOUT,
        )
        ok = r.status_code == 200
        body = r.json() if ok else {}
        if ok and body.get("tagline") == new_tagline:
            record("PUT /admin/branding", True, f"tagline updated to {new_tagline!r}")
        else:
            record("PUT /admin/branding", False, f"status={r.status_code} body={r.text[:300]}")
    except Exception as e:
        record("PUT /admin/branding", False, str(e))

    # ---------- 3) POST /api/admin/branding/reset ----------
    try:
        r = requests.post(
            f"{API}/admin/branding/reset", headers=auth(admin_tok), timeout=TIMEOUT,
        )
        ok = r.status_code == 200
        body = r.json() if ok else {}
        if ok and body.get("tagline") and body.get("tagline") != new_tagline:
            record("POST /admin/branding/reset", True, f"reset ok, default tagline={body.get('tagline')!r}")
        else:
            record("POST /admin/branding/reset", False, f"status={r.status_code} body={r.text[:300]}")
    except Exception as e:
        record("POST /admin/branding/reset", False, str(e))

    # ---------- 4) GET /api/notifications/me ----------
    try:
        r = requests.get(f"{API}/notifications/me", headers=auth(admin_tok), timeout=TIMEOUT)
        ok = r.status_code == 200 and isinstance(r.json(), list)
        if ok:
            record("GET /notifications/me", True, f"array len={len(r.json())}")
        else:
            record("GET /notifications/me", False, f"status={r.status_code} body={r.text[:300]}")
    except Exception as e:
        record("GET /notifications/me", False, str(e))

    # ---------- 5) POST /api/notifications/me/read-all ----------
    try:
        r = requests.post(f"{API}/notifications/me/read-all", headers=auth(admin_tok), timeout=TIMEOUT)
        ok = r.status_code == 200 and r.json().get("ok") is True
        if ok:
            record("POST /notifications/me/read-all", True, "{ok:true}")
        else:
            record("POST /notifications/me/read-all", False, f"status={r.status_code} body={r.text[:300]}")
    except Exception as e:
        record("POST /notifications/me/read-all", False, str(e))

    # ---------- 6) GET /api/products (public, no auth) ----------
    try:
        r = requests.get(f"{API}/products", timeout=TIMEOUT)
        ok = r.status_code == 200 and isinstance(r.json(), list)
        if ok:
            arr = r.json()
            record("GET /products (public)", True, f"array len={len(arr)}")
        else:
            record("GET /products (public)", False, f"status={r.status_code} body={r.text[:300]}")
    except Exception as e:
        record("GET /products (public)", False, str(e))

    # ---------- Sanity: GET /api/admin/stats ----------
    try:
        r = requests.get(f"{API}/admin/stats", headers=auth(admin_tok), timeout=TIMEOUT)
        ok = r.status_code == 200
        record("GET /admin/stats", ok, f"status={r.status_code}" + (f" body[:120]={r.text[:120]}" if not ok else ""))
    except Exception as e:
        record("GET /admin/stats", False, str(e))

    # ---------- Sanity: GET /api/admin/users ----------
    try:
        r = requests.get(f"{API}/admin/users", headers=auth(admin_tok), timeout=TIMEOUT)
        ok = r.status_code == 200 and isinstance(r.json(), list)
        if ok:
            record("GET /admin/users", True, f"array len={len(r.json())}")
        else:
            record("GET /admin/users", False, f"status={r.status_code} body={r.text[:200]}")
    except Exception as e:
        record("GET /admin/users", False, str(e))

    # ---------- Sanity: GET /api/admin/pincodes/in-region (route-ordering regression) ----------
    try:
        r = requests.get(
            f"{API}/admin/pincodes/in-region",
            params={"state": "Telangana", "district": "Hyderabad"},
            headers=auth(admin_tok),
            timeout=TIMEOUT,
        )
        ok = r.status_code == 200
        if ok:
            body = r.json()
            total = body.get("total")
            record("GET /admin/pincodes/in-region", True, f"total={total} items_len={len(body.get('items') or [])}")
        else:
            record("GET /admin/pincodes/in-region", False, f"status={r.status_code} body={r.text[:200]}")
    except Exception as e:
        record("GET /admin/pincodes/in-region", False, str(e))

    # ---------- summary ----------
    print("\n========== RESULT SUMMARY ==========")
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'} — {n}{(' :: ' + d) if not ok and d else ''}")
    print(f"\n  Total: {passed}/{len(results)} passed, {failed} failed")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
