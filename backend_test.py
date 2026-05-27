"""
Phase 1 Session C — Pagination + search backend regression
READ-ONLY test (no destructive operations).
"""
import os
import sys
import time
import json
import requests

BASE = os.environ.get("BACKEND_BASE", "https://vendor-network-app-1.preview.emergentagent.com/api")

ADMIN = {"email": "admin@app.com", "password": "Admin@123"}
USER = {"email": "testuser@app.com", "password": "Test@123"}
QR = {"email": "qrtest@app.com", "password": "Qr@1234"}

results = []  # (name, passed, detail)

def rec(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'} :: {name} :: {detail}")

def login(creds):
    """Login once; tolerates 429 with single backoff."""
    for attempt in range(2):
        r = requests.post(f"{BASE}/auth/login", json=creds, timeout=30)
        if r.status_code == 429:
            print(f"  rate-limited on login {creds['email']}; sleeping 60s")
            time.sleep(60)
            continue
        r.raise_for_status()
        d = r.json()
        return d
    raise RuntimeError(f"login failed for {creds['email']}")

def hdr(tok):
    return {"Authorization": f"Bearer {tok}"}

def get(path, token, **params):
    return requests.get(f"{BASE}{path}", headers=hdr(token), params=params or None, timeout=30)


def main():
    print(f"BASE = {BASE}")
    # Single logins reused
    a = login(ADMIN)
    A_TOK = a.get("token") or a.get("access_token")
    A_REFRESH = a.get("refresh_token")
    print(f"admin token len={len(A_TOK) if A_TOK else None}; refresh={'yes' if A_REFRESH else 'no'}")

    u = login(USER)
    U_TOK = u.get("token") or u.get("access_token")
    print(f"user token len={len(U_TOK) if U_TOK else None}")

    # ───────────────────── 1) BACKWARD COMPAT ───────────────────────────────
    legacy = {}
    for label, path, tok in [
        ("u.transactions", "/transactions/me", U_TOK),
        ("u.withdrawals", "/withdrawals/me", U_TOK),
        ("a.users", "/admin/users", A_TOK),
        ("a.transactions", "/admin/transactions", A_TOK),
        ("a.withdrawals", "/admin/withdrawals", A_TOK),
    ]:
        r = get(path, tok)
        ok = r.status_code == 200 and isinstance(r.json(), list)
        rec(f"BC {label} legacy list", ok, f"HTTP {r.status_code} len={len(r.json()) if ok else 'n/a'}")
        if ok:
            legacy[label] = r.json()

    N_total = len(legacy.get("a.users", []))
    print(f"\nN_total(/admin/users) = {N_total}\n")

    # ───────────────────── 2) PAGINATION CORRECTNESS ────────────────────────
    def pagination_checks(label, path, tok, legacy_list):
        N = len(legacy_list)
        # ?limit=5&offset=0
        r = get(path, tok, limit=5, offset=0)
        ok = r.status_code == 200 and isinstance(r.json(), list) and len(r.json()) <= 5
        first_match = bool(legacy_list) and r.json() and r.json()[0].get("id") == legacy_list[0].get("id") if ok and N else (N == 0)
        rec(f"PG {label} limit=5 offset=0", ok and first_match,
            f"HTTP {r.status_code} got {len(r.json()) if ok else 'n/a'} first_match={first_match}")

        # ?limit=5&offset=5 (if N>=6)
        if N >= 6:
            r = get(path, tok, limit=5, offset=5)
            ok = r.status_code == 200 and isinstance(r.json(), list) and len(r.json()) <= 5
            match = ok and r.json() and r.json()[0].get("id") == legacy_list[5].get("id")
            rec(f"PG {label} limit=5 offset=5", ok and match,
                f"HTTP {r.status_code} got {len(r.json()) if ok else 'n/a'} item0_match_legacy[5]={match}")
        else:
            rec(f"PG {label} limit=5 offset=5", True, f"skipped (N={N})")

        # ?limit=5&offset=N_total → []
        r = get(path, tok, limit=5, offset=N)
        ok = r.status_code == 200 and isinstance(r.json(), list) and len(r.json()) == 0
        rec(f"PG {label} limit=5 offset={N}", ok, f"HTTP {r.status_code} len={len(r.json()) if r.status_code==200 else 'n/a'}")

        # ?limit=0 → legacy unbounded
        r = get(path, tok, limit=0)
        ok = r.status_code == 200 and isinstance(r.json(), list) and len(r.json()) == N
        rec(f"PG {label} limit=0 → unbounded", ok, f"HTTP {r.status_code} got={len(r.json()) if r.status_code==200 else 'n/a'} expected={N}")

        # ?limit=10000 → cap at 200 (won't matter if N<200)
        r = get(path, tok, limit=10000)
        ok = r.status_code == 200 and isinstance(r.json(), list) and len(r.json()) <= 200
        rec(f"PG {label} limit=10000 cap", ok, f"HTTP {r.status_code} len={len(r.json()) if r.status_code==200 else 'n/a'}")

    pagination_checks("a.users", "/admin/users", A_TOK, legacy.get("a.users", []))
    pagination_checks("a.transactions", "/admin/transactions", A_TOK, legacy.get("a.transactions", []))
    pagination_checks("a.withdrawals", "/admin/withdrawals", A_TOK, legacy.get("a.withdrawals", []))
    pagination_checks("u.transactions", "/transactions/me", U_TOK, legacy.get("u.transactions", []))
    pagination_checks("u.withdrawals", "/withdrawals/me", U_TOK, legacy.get("u.withdrawals", []))

    # ───────────────────── 3) SERVER-SIDE SEARCH on /admin/users ───────────
    r = get("/admin/users", A_TOK, q="admin", limit=20)
    ok = r.status_code == 200 and isinstance(r.json(), list)
    found_admin = ok and any(it.get("email") == "admin@app.com" for it in r.json())
    rec("SR q=admin contains admin@app.com", ok and found_admin,
        f"HTTP {r.status_code} len={len(r.json()) if ok else 'n/a'} found={found_admin}")

    r = get("/admin/users", A_TOK, q="testuser", limit=20)
    ok = r.status_code == 200 and isinstance(r.json(), list)
    found_user = ok and any(it.get("email") == "testuser@app.com" for it in r.json())
    rec("SR q=testuser contains testuser@app.com", ok and found_user,
        f"HTTP {r.status_code} len={len(r.json()) if ok else 'n/a'} found={found_user}")

    # regex-special chars
    r = get("/admin/users", A_TOK, q="$^*", limit=20)
    ok = r.status_code == 200 and isinstance(r.json(), list)
    rec("SR q=$^* (regex-escape)", ok,
        f"HTTP {r.status_code} len={len(r.json()) if ok else 'n/a'} (must NOT 500)")

    # non-matching phrase
    r = get("/admin/users", A_TOK, q="zzzz_nonmatching_phrase_xyz", limit=20)
    ok = r.status_code == 200 and isinstance(r.json(), list)
    rec("SR q=nonmatch drops count", ok and len(r.json()) < N_total,
        f"HTTP {r.status_code} len={len(r.json()) if ok else 'n/a'} vs N_total={N_total}")

    # ───────────── 4) STATUS FILTER + PAGINATION /admin/withdrawals ─────────
    r = get("/admin/withdrawals", A_TOK, status="success", limit=5)
    if r.status_code == 200 and isinstance(r.json(), list):
        items = r.json()
        ok = all(it.get("status") == "success" for it in items)
        rec("SF withdrawals status=success", ok, f"HTTP 200 len={len(items)} all_success={ok}")
    else:
        rec("SF withdrawals status=success", False, f"HTTP {r.status_code}")

    r = get("/admin/withdrawals", A_TOK, status="pending", limit=5)
    if r.status_code == 200 and isinstance(r.json(), list):
        items = r.json()
        ok = all(it.get("status") == "pending" for it in items)
        rec("SF withdrawals status=pending", ok, f"HTTP 200 len={len(items)} all_pending={ok}")
    else:
        rec("SF withdrawals status=pending", False, f"HTTP {r.status_code}")

    # ───────────── 5) include_pending + PAGINATION /admin/transactions ─────
    r = get("/admin/transactions", A_TOK, include_pending="true", limit=5)
    ok = r.status_code == 200 and isinstance(r.json(), list) and len(r.json()) <= 5
    rec("IP transactions include_pending=true limit=5", ok,
        f"HTTP {r.status_code} len={len(r.json()) if ok else 'n/a'}")

    r = get("/admin/transactions", A_TOK, limit=5)
    if r.status_code == 200 and isinstance(r.json(), list):
        items = r.json()
        bad = [it for it in items if it.get("status") in ("created", "failed")]
        rec("IP transactions default excludes created/failed", len(bad) == 0,
            f"HTTP 200 len={len(items)} bad_count={len(bad)}")
    else:
        rec("IP transactions default", False, f"HTTP {r.status_code}")

    # ───────────────────── 6) NO REGRESSIONS ────────────────────────────────
    r = requests.get(f"{BASE}/branding", timeout=30)
    rec("RG /branding (anon)", r.status_code == 200, f"HTTP {r.status_code}")

    r = requests.get(f"{BASE}/products", timeout=30)
    rec("RG /products", r.status_code == 200, f"HTTP {r.status_code}")

    r = get("/auth/me", A_TOK)
    rec("RG /auth/me (admin)", r.status_code == 200, f"HTTP {r.status_code}")

    # Admin login still works — but we already did one login; do not log in again to avoid 429.
    rec("RG admin login (already done)", bool(A_TOK), f"token_len={len(A_TOK) if A_TOK else 0}")

    # Refresh-token rotation — use already-captured A_REFRESH
    if A_REFRESH:
        r = requests.post(f"{BASE}/auth/refresh", json={"refresh_token": A_REFRESH}, timeout=30)
        ok = r.status_code == 200 and isinstance(r.json(), dict)
        body = r.json() if ok else {}
        new_acc = body.get("token") or body.get("access_token")
        new_ref = body.get("refresh_token")
        rotated = bool(new_acc) and bool(new_ref) and new_ref != A_REFRESH
        rec("RG /auth/refresh rotation", ok and rotated,
            f"HTTP {r.status_code} new_access={'y' if new_acc else 'n'} new_refresh={'y' if new_ref else 'n'} rotated={rotated}")
    else:
        rec("RG /auth/refresh rotation", False, "no refresh_token on login response")

    # ─────────────────────── SUMMARY ───────────────────────────────────────
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n========== SUMMARY {passed}/{total} ==========")
    for name, ok, detail in results:
        if not ok:
            print(f"  FAIL :: {name} :: {detail}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
