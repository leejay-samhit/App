"""Backend validation for the User Creation Source Tracking matrix.

Targets external preview URL. Read-only validation (creates a few
admin-created users but no code changes are made to the backend).

Run: python /app/backend_test.py
"""

import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

BASE = "https://vendor-network-app-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@app.com"
ADMIN_PASS = "Admin@123"
USER_EMAIL = "testuser@app.com"
USER_PASS = "Test@123"

CLIENT = httpx.Client(timeout=30.0)

PASS: List[str] = []
FAIL: List[str] = []
INFO: List[str] = []


def ok(label: str, detail: str = ""):
    PASS.append(f"PASS · {label}" + (f" — {detail}" if detail else ""))
    print(f"  [PASS] {label} {detail}")


def fail(label: str, detail: str = ""):
    FAIL.append(f"FAIL · {label}" + (f" — {detail}" if detail else ""))
    print(f"  [FAIL] {label} {detail}")


def info(label: str):
    INFO.append(label)
    print(f"  [INFO] {label}")


def login(email: str, password: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    r = CLIENT.post(f"{BASE}/auth/login", json={"email": email, "password": password})
    if r.status_code != 200:
        return None, {"status": r.status_code, "body": r.text[:300]}
    j = r.json()
    return j.get("token"), j


def H(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ─────────────── 1. SOURCE BREAKDOWN ENDPOINT ───────────────


def test_source_breakdown(admin_token: str, user_token: Optional[str]):
    print("\n[1] SOURCE BREAKDOWN ENDPOINT")
    # no-auth → 401
    r = CLIENT.get(f"{BASE}/admin/system-wallet/source-breakdown")
    if r.status_code in (401, 403):
        ok("no-auth → 401/403", f"got {r.status_code}")
    else:
        fail("no-auth gating", f"expected 401, got {r.status_code} — {r.text[:200]}")

    # non-admin → 403
    if user_token:
        r = CLIENT.get(
            f"{BASE}/admin/system-wallet/source-breakdown",
            headers=H(user_token),
        )
        if r.status_code == 403:
            ok("non-admin token → 403")
        else:
            fail("non-admin gating", f"expected 403, got {r.status_code} — {r.text[:200]}")

    # admin → 200 with the right shape
    r = CLIENT.get(
        f"{BASE}/admin/system-wallet/source-breakdown",
        headers=H(admin_token),
    )
    if r.status_code != 200:
        fail("admin GET → 200", f"got {r.status_code}: {r.text[:300]}")
        return None
    j = r.json()
    for k in ("rows", "totals", "fan_out", "generated_at"):
        if k not in j:
            fail("shape", f"missing key '{k}'")
            return None
    if not isinstance(j["rows"], list):
        fail("rows is list", f"got {type(j['rows']).__name__}")
        return None
    # rows objects shape
    for row in j["rows"]:
        for rk in ("source", "count", "amount"):
            if rk not in row:
                fail("row keys", f"row missing '{rk}': {row}")
                return None
    if "count" not in j["totals"] or "amount" not in j["totals"]:
        fail("totals shape", str(j["totals"]))
        return None
    if not isinstance(j["fan_out"], dict):
        fail("fan_out is dict", f"got {type(j['fan_out']).__name__}")
        return None

    sources_present = [r["source"] for r in j["rows"]]
    ok("admin GET → 200 + correct shape",
       f"rows={len(j['rows'])} sources={sources_present} totals={j['totals']}")
    if "razorpay" in sources_present:
        ok("backfill: 'razorpay' source present in rows")
    else:
        fail("backfill: 'razorpay' source missing", f"sources seen: {sources_present}")
    if "upi_manual" in sources_present:
        ok("backfill: 'upi_manual' source present in rows")
    else:
        fail("backfill: 'upi_manual' source missing", f"sources seen: {sources_present}")
    return j


# ─────────────── 2. BACKFILL VERIFICATION ───────────────


def test_backfill_users(admin_token: str):
    print("\n[2] BACKFILL VERIFICATION on legacy paid users")
    r = CLIENT.get(f"{BASE}/admin/users?limit=200", headers=H(admin_token))
    if r.status_code != 200:
        fail("GET /admin/users?limit=200", f"got {r.status_code}: {r.text[:200]}")
        return
    users = r.json()
    if not isinstance(users, list):
        fail("users list shape", f"got {type(users).__name__}")
        return
    info(f"received {len(users)} users from /admin/users?limit=200")

    paid = [u for u in users if u.get("registration_paid")]
    info(f"paid users among loaded page: {len(paid)}")

    razor_users = [u for u in paid if (u.get("payment_method") or "").startswith("razorpay")]
    upi_users = [u for u in paid if (u.get("payment_method") or "").startswith("upi_manual")]
    offline_users = [
        u for u in paid
        if (u.get("payment_method") or "").startswith("admin_offline")
        or u.get("payment_method") is None
    ]
    info(f"razorpay paid users: {len(razor_users)} | upi_manual: {len(upi_users)} | "
         f"admin_offline/null: {len(offline_users)}")

    def assert_source(label: str, lst: List[Dict[str, Any]], expected: str):
        bad = [u for u in lst if u.get("registration_source") != expected]
        if not bad:
            ok(f"backfill: {label} → registration_source == '{expected}' for all {len(lst)} users")
        else:
            samples = [{"email": u.get("email"),
                        "payment_method": u.get("payment_method"),
                        "registration_source": u.get("registration_source")}
                       for u in bad[:5]]
            fail(f"backfill: {label} mismatch", f"{len(bad)}/{len(lst)} wrong. samples={samples}")

    if razor_users:
        assert_source("razorpay paid users", razor_users, "razorpay")
    else:
        info("no razorpay paid users found on this page — skipping that assertion")
    if upi_users:
        assert_source("upi_manual paid users", upi_users, "upi_manual")
    else:
        info("no upi_manual paid users found on this page — skipping that assertion")
    if offline_users:
        assert_source("admin_offline/null paid users", offline_users, "offline_cash")
    else:
        info("no admin_offline/null paid users found on this page — skipping that assertion")


# ─────────────── 3. ADMIN CREATE USER WITH NEW SOURCE FIELD ───────────────


def fetch_user_by_q(admin_token: str, q: str) -> Optional[Dict[str, Any]]:
    r = CLIENT.get(f"{BASE}/admin/users", params={"q": q, "limit": 5}, headers=H(admin_token))
    if r.status_code != 200:
        return None
    arr = r.json()
    return arr[0] if arr else None


def create_user(admin_token: str, email: str, *, mark_paid: bool,
                source: Optional[str], label_tag: str) -> Optional[Dict[str, Any]]:
    body: Dict[str, Any] = {
        "name": f"Source Test {label_tag}",
        "email": email,
        "password": "Pass@1234",
        "mark_paid_offline": mark_paid,
    }
    if source is not None:
        body["registration_source"] = source
    r = CLIENT.post(f"{BASE}/admin/users/create", json=body, headers=H(admin_token))
    if r.status_code not in (200, 201):
        fail(f"create user [{label_tag}]", f"got {r.status_code}: {r.text[:300]}")
        return None
    j = r.json()
    return j


def test_admin_create_user_sources(admin_token: str):
    print("\n[3] ADMIN CREATE USER WITH registration_source")
    ts = int(time.time())
    created: Dict[str, Dict[str, Any]] = {}

    cases = [
        ("razorpay", True, "razorpay"),
        ("upi_manual", True, "upi_manual"),
        ("offline_cash", True, "offline_cash"),
        ("default", True, None),       # legacy caller, no field
        ("unpaid", False, None),       # mark_paid_offline=false
    ]
    for tag, mark_paid, src in cases:
        email = f"src-test-{tag}-{ts}@app.com"
        res = create_user(admin_token, email, mark_paid=mark_paid, source=src,
                          label_tag=tag)
        if not res:
            continue
        ok(f"create user [{tag}] mark_paid_offline={mark_paid} src={src} → 200")
        # Verify via /admin/users?q=
        time.sleep(0.3)
        u = fetch_user_by_q(admin_token, f"src-test-{tag}-{ts}")
        if not u:
            fail(f"lookup user [{tag}] via ?q=", "no user matched")
            continue
        created[tag] = u
        actual = u.get("registration_source")
        if tag == "razorpay":
            expected = "razorpay"
        elif tag == "upi_manual":
            expected = "upi_manual"
        elif tag == "offline_cash":
            expected = "offline_cash"
        elif tag == "default":
            expected = "offline_cash"
        elif tag == "unpaid":
            expected = None
        else:
            expected = "??"
        if actual == expected:
            ok(f"[{tag}] registration_source on user doc == {expected!r}")
        else:
            fail(f"[{tag}] wrong registration_source",
                 f"expected {expected!r} got {actual!r} (payment_method={u.get('payment_method')!r})")
    return created


# ─────────────── 4. BREAKDOWN INCREMENTS ───────────────


def get_breakdown(admin_token: str) -> Dict[str, Any]:
    r = CLIENT.get(f"{BASE}/admin/system-wallet/source-breakdown",
                   headers=H(admin_token))
    r.raise_for_status()
    return r.json()


def row_for(j: Dict[str, Any], source: str) -> Dict[str, Any]:
    for r in j.get("rows", []):
        if r.get("source") == source:
            return r
    return {"source": source, "count": 0, "amount": 0}


def test_breakdown_increments(admin_token: str):
    print("\n[4] BREAKDOWN INCREMENTS — create 2 offline_cash users")
    before = get_breakdown(admin_token)
    base = row_for(before, "offline_cash")
    info(f"BEFORE — offline_cash count={base.get('count')} amount={base.get('amount')}")
    ts = int(time.time())
    for i in range(2):
        email = f"inc-test-offline-{ts}-{i}@app.com"
        res = create_user(admin_token, email, mark_paid=True,
                          source="offline_cash", label_tag=f"inc-{i}")
        if not res:
            return
    time.sleep(0.5)
    after = get_breakdown(admin_token)
    af = row_for(after, "offline_cash")
    info(f"AFTER — offline_cash count={af.get('count')} amount={af.get('amount')}")
    dc = int(af.get("count") or 0) - int(base.get("count") or 0)
    da = float(af.get("amount") or 0) - float(base.get("amount") or 0)
    if dc == 2:
        ok("offline_cash count increased by exactly 2")
    else:
        fail("offline_cash count delta", f"expected +2 got +{dc}")
    if abs(da - 236.0) < 0.01:
        ok("offline_cash amount increased by ₹236 (2 × 118)")
    else:
        fail("offline_cash amount delta", f"expected +236.0 got +{da}")


# ─────────────── 5. REGRESSION CHECK ───────────────


def test_regressions(admin_token: str, user_token: Optional[str]):
    print("\n[5] REGRESSION CHECK")
    r = CLIENT.get(f"{BASE}/admin/users", params={"limit": 20}, headers=H(admin_token))
    if r.status_code == 200 and isinstance(r.json(), list):
        ok(f"/admin/users?limit=20 → 200 ({len(r.json())} items)")
    else:
        fail("/admin/users?limit=20", f"status={r.status_code}")

    r = CLIENT.get(f"{BASE}/admin/system-wallet", headers=H(admin_token))
    if r.status_code == 200:
        j = r.json()
        has_buckets = isinstance(j, dict) and (
            "wallet_buckets" in j or "buckets" in j or "balance" in j
        )
        ok(f"/admin/system-wallet → 200{' (buckets present)' if has_buckets else ''}")
        if not has_buckets:
            info(f"/admin/system-wallet shape: {list(j.keys()) if isinstance(j, dict) else type(j).__name__}")
    else:
        fail("/admin/system-wallet", f"status={r.status_code} body={r.text[:200]}")

    r = CLIENT.get(f"{BASE}/admin/audit-logs", headers=H(admin_token))
    if r.status_code == 200:
        ok("/admin/audit-logs → 200")
    else:
        fail("/admin/audit-logs", f"status={r.status_code}")

    # Fresh admin login → refresh_token present (use the same we already have? Avoid 429.)
    # Skip a second admin login — review brief explicitly says "ONE admin login".
    info("Skipped re-login for admin to respect 10/min/IP rate limit; "
         "refresh_token presence verified at start of run.")

    # withdrawal endpoint smoke for clean-device users:
    if user_token:
        r = CLIENT.post(
            f"{BASE}/withdrawals",
            headers=H(user_token),
            json={"amount": 1},  # small
        )
        # Either 200 or a business-rule 400/422 means the endpoint reachable.
        # 403 device_compromised would be a regression for clean device.
        if r.status_code in (200, 400, 422):
            ok(f"/withdrawals (clean-device user) → {r.status_code} (endpoint reachable)")
            info(f"withdraw body: {r.text[:200]}")
        elif r.status_code == 429:
            info(f"/withdrawals → 429 (rate-limited from prior testing); endpoint reachable")
        else:
            fail(f"/withdrawals regression", f"status={r.status_code} body={r.text[:200]}")


# ─────────────── 6. TRANSACTION TAGGING ───────────────


def test_transaction_tagging(admin_token: str, created: Dict[str, Dict[str, Any]]):
    print("\n[6] TRANSACTION TAGGING")
    if not created:
        fail("no created users from step 3", "")
        return
    # Pull a large slice of recent transactions
    r = CLIENT.get(
        f"{BASE}/admin/transactions",
        params={"include_pending": "true", "limit": 200},
        headers=H(admin_token),
    )
    if r.status_code != 200:
        fail("/admin/transactions GET", f"status={r.status_code}")
        return
    txns = r.json()
    info(f"loaded {len(txns)} txns from /admin/transactions")

    # For each tag we expect a registration_fee txn with source==tag
    for tag in ("razorpay", "upi_manual", "offline_cash", "default"):
        u = created.get(tag)
        if not u:
            continue
        uid = u.get("id")
        expected_src = "offline_cash" if tag == "default" else tag
        matches = [t for t in txns if t.get("user_id") == uid and t.get("type") == "registration_fee"]
        if not matches:
            # if not on first page, try a second page
            r2 = CLIENT.get(
                f"{BASE}/admin/transactions",
                params={"include_pending": "true", "limit": 200, "offset": 200},
                headers=H(admin_token),
            )
            if r2.status_code == 200:
                matches = [t for t in r2.json() if t.get("user_id") == uid and t.get("type") == "registration_fee"]
        if not matches:
            fail(f"txn lookup [{tag}]", f"no registration_fee txn for user_id={uid}")
            continue
        t = matches[0]
        if t.get("source") == expected_src:
            ok(f"txn [{tag}] source == {expected_src!r}")
        else:
            fail(f"txn [{tag}] source mismatch",
                 f"got {t.get('source')!r} expected {expected_src!r} status={t.get('status')!r}")

    # Unpaid user must NOT have a registration_fee txn
    u_unpaid = created.get("unpaid")
    if u_unpaid:
        uid = u_unpaid.get("id")
        matches = [t for t in txns if t.get("user_id") == uid and t.get("type") == "registration_fee"]
        if not matches:
            ok("unpaid user has no registration_fee txn (as expected)")
        else:
            fail("unpaid user has a registration_fee txn", str(matches[:1]))

    # Observation about old razorpay txns (documenting the brief's note)
    razor_old = [t for t in txns
                 if t.get("type") == "registration_fee"
                 and (t.get("payment_method") or "").startswith("razorpay")]
    if razor_old:
        tagged = [t for t in razor_old if t.get("source") == "razorpay"]
        info(f"EXISTING razorpay registration_fee txns on page: {len(razor_old)}, "
             f"of which source-tagged: {len(tagged)} (old txns are unstamped, "
             f"new txns are stamped — that is expected per the brief).")


# ─────────────── MAIN ───────────────


def main() -> int:
    print(f"BASE = {BASE}")
    print(f"==== Admin login (single use) ====")
    token, payload = login(ADMIN_EMAIL, ADMIN_PASS)
    if not token:
        print(f"  CANNOT LOGIN admin: {payload}")
        return 1
    refresh = (payload or {}).get("refresh_token")
    if refresh:
        ok("admin login → refresh_token present")
    else:
        fail("admin login missing refresh_token", str(list((payload or {}).keys())))

    print("==== User login (separate IP-shared bucket) ====")
    user_token = None
    try:
        utoken, _ = login(USER_EMAIL, USER_PASS)
        user_token = utoken
        if user_token:
            ok("testuser login → token")
        else:
            info(f"testuser login failed: {_}")
    except Exception as e:
        info(f"testuser login exception: {e}")

    test_source_breakdown(token, user_token)
    test_backfill_users(token)
    created = test_admin_create_user_sources(token)
    test_breakdown_increments(token)
    test_regressions(token, user_token)
    test_transaction_tagging(token, created or {})

    print("\n========== SUMMARY ==========")
    print(f"PASS: {len(PASS)}")
    print(f"FAIL: {len(FAIL)}")
    if FAIL:
        print("\nFAILURES:")
        for f in FAIL:
            print(f"  - {f}")
    return 0 if not FAIL else 2


if __name__ == "__main__":
    sys.exit(main())
