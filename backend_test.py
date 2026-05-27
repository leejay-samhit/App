"""
Phase 2B Modular Refactor — wallet/withdrawals/cart routes regression test.

Goal: confirm endpoints extracted into routes/wallet.py, routes/withdrawals.py
and routes/cart.py behave identically to their pre-refactor counterparts, and
that previously-working sibling endpoints (POST /withdrawals, POST
/wallet/transfer, GET /admin/system-wallet/breakdown) did not regress.

Run:  python /app/backend_test.py
Backend URL is read from /app/frontend/.env (EXPO_PUBLIC_BACKEND_URL).
"""

import os
import re
import sys
import json
import time
import traceback
from typing import Any, Dict, Optional

import requests


# ───────── config ─────────
def _load_backend_url() -> str:
    path = "/app/frontend/.env"
    base = None
    with open(path, "r") as fh:
        for line in fh:
            line = line.strip()
            for key in ("EXPO_PUBLIC_BACKEND_URL", "REACT_APP_BACKEND_URL", "EXPO_BACKEND_URL"):
                if line.startswith(key + "="):
                    base = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
            if base:
                break
    if not base:
        raise RuntimeError("No backend URL found in /app/frontend/.env")
    return base.rstrip("/") + "/api"


BASE = _load_backend_url()
ADMIN_EMAIL = "admin@app.com"
ADMIN_PASS = "Admin@123"
USER_EMAIL = "testuser@app.com"
USER_PASS = "Test@123"

results = []  # (name, passed, detail)


def record(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))
    icon = "PASS" if passed else "FAIL"
    print(f"[{icon}] {name}  {('— ' + detail) if detail else ''}")


def login(email: str, password: str) -> Optional[str]:
    try:
        r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=20)
        if r.status_code != 200:
            return None
        body = r.json()
        return body.get("access_token") or body.get("token")
    except Exception:
        return None


def auth(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ───────── 1. AUTH ─────────
print(f"\n=== BASE: {BASE} ===\n")
admin_tok = login(ADMIN_EMAIL, ADMIN_PASS)
record("1.admin_login", bool(admin_tok), f"token_len={len(admin_tok or '')}")
user_tok = login(USER_EMAIL, USER_PASS)
record("1.user_login", bool(user_tok), f"token_len={len(user_tok or '')}")

if not admin_tok or not user_tok:
    print("\nAUTH FAILED — aborting remaining tests.")
    sys.exit(1)


# ───────── 2. /transactions/me ─────────
try:
    r = requests.get(f"{BASE}/transactions/me", headers=auth(user_tok), timeout=20)
    ok = r.status_code == 200 and isinstance(r.json(), list)
    txs_default = r.json() if ok else []
    record("2a.transactions/me default", ok, f"status={r.status_code} count={len(txs_default) if ok else 0}")
except Exception as e:
    record("2a.transactions/me default", False, f"exc={e}")
    txs_default = []

try:
    r = requests.get(f"{BASE}/transactions/me?include_pending=true", headers=auth(user_tok), timeout=20)
    ok = r.status_code == 200 and isinstance(r.json(), list)
    txs_pending = r.json() if ok else []
    # include_pending should be >= default count
    cmp_ok = ok and len(txs_pending) >= len(txs_default)
    record("2b.transactions/me include_pending=true", cmp_ok, f"status={r.status_code} count={len(txs_pending) if ok else 0} vs default={len(txs_default)}")
except Exception as e:
    record("2b.transactions/me include_pending=true", False, f"exc={e}")

try:
    r = requests.get(f"{BASE}/transactions/me?limit=10&offset=0", headers=auth(user_tok), timeout=20)
    body = r.json() if r.status_code == 200 else None
    ok = r.status_code == 200 and isinstance(body, list) and len(body) <= 10
    record("2c.transactions/me limit=10&offset=0", ok, f"status={r.status_code} count={len(body) if isinstance(body, list) else 'n/a'}")
except Exception as e:
    record("2c.transactions/me limit=10&offset=0", False, f"exc={e}")


# Pick a txn id we can use for detail/invoice tests. Prefer an invoiceable one.
sample_txn = None
invoiceable_txn = None
non_invoiceable_txn = None  # status in {created, failed} -> not invoiceable

# Fetch all txns (admin scope, include_pending so we see created/failed rows too)
try:
    r = requests.get(f"{BASE}/admin/transactions?include_pending=true&limit=200", headers=auth(admin_tok), timeout=20)
    admin_txs = r.json() if r.status_code == 200 else []
    if isinstance(admin_txs, dict):
        admin_txs = admin_txs.get("items", [])
except Exception:
    admin_txs = []

# Search for invoiceable txn (registration_fee or service_booking with status not in created/failed)
for t in admin_txs:
    if not sample_txn:
        sample_txn = t
    ttype = (t.get("type") or "").lower()
    status = (t.get("status") or "").lower()
    if not invoiceable_txn and ttype in ("registration_fee", "service_booking") and status not in ("created", "failed"):
        invoiceable_txn = t
    # Non-invoiceable per is_invoiceable() = type not in INVOICEABLE list.
    # Easiest reliable non-invoiceable: status=created/failed registration_fee → won't render invoice
    # But really the check is on TYPE — look for an unknown / non-listed type. Use 'order' if present (NOT in invoiceable list).
    if not non_invoiceable_txn and ttype == "order":
        non_invoiceable_txn = t


# ───────── 3. /transactions/{id} enriched detail ─────────
if sample_txn:
    txn_id = sample_txn["id"]
    # Use the owner's token to fetch — if owner is admin, use admin_tok, else find via user
    owner_tok = admin_tok if sample_txn.get("user_id") and admin_txs and any(t["id"] == txn_id for t in admin_txs) else user_tok
    # Use admin token (super_admin can read any txn per route logic)
    try:
        r = requests.get(f"{BASE}/transactions/{txn_id}", headers=auth(admin_tok), timeout=20)
        body = r.json() if r.status_code == 200 else {}
        keys_ok = (
            r.status_code == 200
            and "transaction" in body
            and "auto_remarks" in body
            and "counter_party" in body
            and "invoiceable" in body
        )
        record("3.transactions/{id} enriched detail", keys_ok,
               f"status={r.status_code} keys={list(body.keys()) if isinstance(body, dict) else 'n/a'}")
    except Exception as e:
        record("3.transactions/{id} enriched detail", False, f"exc={e}")
else:
    record("3.transactions/{id} enriched detail", False, "no sample transaction found in admin/user history")


# ───────── 4. /transactions/{id}/invoice (HTML) ─────────
if invoiceable_txn:
    inv_id = invoiceable_txn["id"]
    try:
        r = requests.get(f"{BASE}/transactions/{inv_id}/invoice", headers=auth(admin_tok), timeout=20)
        ok = r.status_code == 200 and ("text/html" in (r.headers.get("content-type", "")).lower() or "<html" in r.text.lower())
        record("4a.invoice HTML (invoiceable txn)", ok,
               f"status={r.status_code} ctype={r.headers.get('content-type','')} body_head={r.text[:60]!r}")
    except Exception as e:
        record("4a.invoice HTML (invoiceable txn)", False, f"exc={e}")
else:
    record("4a.invoice HTML (invoiceable txn)", False, "no registration_fee or service_booking txn found")

# Negative — non-invoiceable should 400. Use the non_invoiceable_txn found above (e.g. 'order' type)
non_inv = non_invoiceable_txn

if non_inv:
    try:
        r = requests.get(f"{BASE}/transactions/{non_inv['id']}/invoice", headers=auth(admin_tok), timeout=20)
        record("4b.invoice non-invoiceable -> 400", r.status_code == 400,
               f"status={r.status_code} body={r.text[:120]}")
    except Exception as e:
        record("4b.invoice non-invoiceable -> 400", False, f"exc={e}")
else:
    record("4b.invoice non-invoiceable -> 400", False, "no non-invoiceable txn found to test 400 path")


# ───────── 5. /withdrawals/me ─────────
try:
    r = requests.get(f"{BASE}/withdrawals/me", headers=auth(user_tok), timeout=20)
    ok = r.status_code == 200 and isinstance(r.json(), list)
    base_w = r.json() if ok else []
    record("5a.withdrawals/me (default)", ok, f"status={r.status_code} count={len(base_w) if ok else 0}")
except Exception as e:
    record("5a.withdrawals/me (default)", False, f"exc={e}")

try:
    r = requests.get(f"{BASE}/withdrawals/me?limit=5&offset=0", headers=auth(user_tok), timeout=20)
    body = r.json() if r.status_code == 200 else None
    ok = r.status_code == 200 and isinstance(body, list) and len(body) <= 5
    record("5b.withdrawals/me limit=5&offset=0", ok, f"status={r.status_code} count={len(body) if isinstance(body, list) else 'n/a'}")
except Exception as e:
    record("5b.withdrawals/me limit=5&offset=0", False, f"exc={e}")


# ───────── 6. Cart flow ─────────
# First find any product to add
try:
    r = requests.get(f"{BASE}/products", timeout=20)
    products = r.json() if r.status_code == 200 else []
    if isinstance(products, dict):
        products = products.get("items", [])
    sample_product = next((p for p in products if p.get("stock", 0) > 0), products[0] if products else None)
except Exception:
    sample_product = None

if not sample_product:
    record("6.cart flow setup", False, "no product available")
else:
    pid = sample_product["id"]
    # Start clean
    requests.post(f"{BASE}/cart/clear", headers=auth(user_tok), timeout=20)

    try:
        r = requests.post(f"{BASE}/cart/add", headers=auth(user_tok),
                          json={"product_id": pid, "qty": 1}, timeout=20)
        record("6a.cart/add", r.status_code == 200 and r.json().get("ok") is True,
               f"status={r.status_code} body={r.text[:80]}")
    except Exception as e:
        record("6a.cart/add", False, f"exc={e}")

    try:
        r = requests.get(f"{BASE}/cart", headers=auth(user_tok), timeout=20)
        body = r.json() if r.status_code == 200 else {}
        ok = (r.status_code == 200 and isinstance(body, dict)
              and "count" in body and "total" in body and body.get("count", 0) >= 1)
        record("6b.cart GET (after add)", ok, f"status={r.status_code} count={body.get('count')} total={body.get('total')}")
    except Exception as e:
        record("6b.cart GET (after add)", False, f"exc={e}")

    try:
        r = requests.post(f"{BASE}/cart/remove", headers=auth(user_tok),
                          json={"product_id": pid}, timeout=20)
        record("6c.cart/remove", r.status_code == 200 and r.json().get("ok") is True,
               f"status={r.status_code} body={r.text[:80]}")
    except Exception as e:
        record("6c.cart/remove", False, f"exc={e}")

    # Add again to test clear
    requests.post(f"{BASE}/cart/add", headers=auth(user_tok),
                  json={"product_id": pid, "qty": 2}, timeout=20)
    try:
        r = requests.post(f"{BASE}/cart/clear", headers=auth(user_tok), timeout=20)
        record("6d.cart/clear", r.status_code == 200 and r.json().get("ok") is True,
               f"status={r.status_code} body={r.text[:80]}")
    except Exception as e:
        record("6d.cart/clear", False, f"exc={e}")

    try:
        r = requests.get(f"{BASE}/cart", headers=auth(user_tok), timeout=20)
        body = r.json() if r.status_code == 200 else {}
        ok = r.status_code == 200 and body.get("count", -1) == 0
        record("6e.cart GET count==0 after clear", ok,
               f"status={r.status_code} count={body.get('count')}")
    except Exception as e:
        record("6e.cart GET count==0 after clear", False, f"exc={e}")


# ───────── 7. /orders/me ─────────
try:
    r = requests.get(f"{BASE}/orders/me", headers=auth(user_tok), timeout=20)
    ok = r.status_code == 200 and isinstance(r.json(), list)
    record("7.orders/me", ok, f"status={r.status_code} count={len(r.json()) if ok else 'n/a'}")
except Exception as e:
    record("7.orders/me", False, f"exc={e}")


# ───────── 8. Negative tests ─────────
try:
    r = requests.get(f"{BASE}/transactions/bogus-id-does-not-exist", headers=auth(admin_tok), timeout=20)
    record("8a.transactions/{bogus} -> 404", r.status_code == 404,
           f"status={r.status_code} body={r.text[:80]}")
except Exception as e:
    record("8a.transactions/{bogus} -> 404", False, f"exc={e}")

# Auth-less endpoint hits
for ep in ["/transactions/me", "/withdrawals/me", "/cart", "/orders/me"]:
    try:
        r = requests.get(f"{BASE}{ep}", timeout=20)
        record(f"8b.{ep} no-auth -> 401/403", r.status_code in (401, 403),
               f"status={r.status_code}")
    except Exception as e:
        record(f"8b.{ep} no-auth -> 401/403", False, f"exc={e}")


# ───────── 9. Sibling regression checks ─────────
# 9a. POST /withdrawals with valid amount — should 200 OR 4xx (not 5xx). Many users won't have wallet
try:
    r = requests.post(f"{BASE}/withdrawals", headers=auth(user_tok),
                      json={"amount": 100}, timeout=20)
    ok = r.status_code < 500
    record("9a.POST /withdrawals no-5xx", ok, f"status={r.status_code} body={r.text[:120]}")
except Exception as e:
    record("9a.POST /withdrawals no-5xx", False, f"exc={e}")

# 9b. POST /wallet/transfer with bogus payload — must 4xx (not 5xx)
try:
    r = requests.post(f"{BASE}/wallet/transfer", headers=auth(user_tok),
                      json={"to_email": "doesnotexist-xyz@nowhere.invalid", "amount": 1}, timeout=20)
    ok = 400 <= r.status_code < 500
    record("9b.POST /wallet/transfer bogus -> 4xx (not 5xx)", ok,
           f"status={r.status_code} body={r.text[:120]}")
except Exception as e:
    record("9b.POST /wallet/transfer bogus -> 4xx (not 5xx)", False, f"exc={e}")

# 9c. GET /admin/system-wallet/breakdown
try:
    r = requests.get(f"{BASE}/admin/system-wallet/breakdown", headers=auth(admin_tok), timeout=30)
    body = r.json() if r.status_code == 200 else {}
    ok = r.status_code == 200 and "inflow" in body and "outflow" in body
    record("9c.admin/system-wallet/breakdown", ok,
           f"status={r.status_code} keys={list(body.keys()) if isinstance(body, dict) else 'n/a'}")
except Exception as e:
    record("9c.admin/system-wallet/breakdown", False, f"exc={e}")


# ============================================================
# 10. LEDGER DRIFT — Offline pre-credit reversal (2026-06 fix)
# ============================================================
# Verifies the fix in admin_create_user (line ~3992) + _trigger_referral_commissions
# (line ~879) that reverses the `direct_added` pre-credit when an admin-offline
# created user (mark_paid_offline=True) is approved, preventing double-count
# drift in [LEDGER ALERT].

import uuid as _uuid


def _get_admin_user_doc():
    """Look up admin's user doc via GET /admin/users (limit/q filter)."""
    try:
        r = requests.get(f"{BASE}/admin/users?q=admin@app.com",
                         headers=auth(admin_tok), timeout=20)
        if r.status_code != 200:
            return None
        users = r.json()
        if isinstance(users, dict):
            users = users.get("items", [])
        for u in users:
            if (u.get("email") or "").lower() == ADMIN_EMAIL:
                return u
    except Exception:
        return None
    return None


def _get_user_doc_by_email(email: str):
    try:
        r = requests.get(f"{BASE}/admin/users?q={email}",
                         headers=auth(admin_tok), timeout=20)
        if r.status_code != 200:
            return None
        users = r.json()
        if isinstance(users, dict):
            users = users.get("items", [])
        for u in users:
            if (u.get("email") or "").lower() == email.lower():
                return u
    except Exception:
        return None
    return None


def _get_system_wallet():
    r = requests.get(f"{BASE}/admin/system-wallet", headers=auth(admin_tok), timeout=20)
    if r.status_code != 200:
        return None
    return r.json()


def _get_breakdown():
    r = requests.get(f"{BASE}/admin/system-wallet/breakdown",
                     headers=auth(admin_tok), timeout=30)
    if r.status_code != 200:
        return None
    return r.json()


def _compute_drift(bd):
    """drift = inflow_total - (held_total + withdrawals_settled).
    Healthy ledger: |drift| <= ₹1.
    """
    if not bd:
        return None
    inflow = float(bd.get("inflow", {}).get("total") or 0)
    held = float(bd.get("balance", {}).get("held_total") or 0)
    withdrawn = float(bd.get("outflow", {}).get("user_withdrawals_settled") or 0)
    return round(inflow - held - withdrawn, 2)


def _find_reversal_txn_for_user(user_id: str, admin_id: str):
    """GET /admin/transactions and search for the admin_debit reversal row.

    Filters by admin's user_id, type=admin_debit, is_offline_reversal=True,
    and source_user_id == user_id.
    """
    try:
        r = requests.get(
            f"{BASE}/admin/transactions?include_pending=true&limit=500",
            headers=auth(admin_tok), timeout=30,
        )
        if r.status_code != 200:
            return None
        rows = r.json()
        if isinstance(rows, dict):
            rows = rows.get("items", [])
        for t in rows:
            if (t.get("type") == "admin_debit"
                and t.get("is_offline_reversal") is True
                and t.get("source_user_id") == user_id
                and t.get("user_id") == admin_id):
                return t
        return None
    except Exception:
        return None


# ----- Pre-flight: fetch admin's referral code, settings -----
admin_doc = _get_admin_user_doc()
admin_ref_code = (admin_doc or {}).get("referral_code")
admin_id_val = (admin_doc or {}).get("id")
record("10.0a.admin_doc_lookup", bool(admin_doc and admin_ref_code and admin_id_val),
       f"ref_code={admin_ref_code} id={admin_id_val}")

bd0 = _get_breakdown()
fee_amount = float((bd0 or {}).get("settings", {}).get("registration_fee") or 0)
record("10.0b.registration_fee_setting", fee_amount > 0,
       f"fee={fee_amount}")


# =============================================================
# 10.1  Offline-create WITH sponsor (full happy path)
# =============================================================
suffix = _uuid.uuid4().hex[:8]
sponsor_email = f"vinay.kumar.sp.{suffix}@networktest.in"
sponsor_payload = {
    "name": "Vinay Kumar Sponsor",
    "email": sponsor_email,
    "password": "Sponsor@2026",
    "phone": "9000010001",
    "referral_code": admin_ref_code,   # placement under admin
    "mark_paid_offline": True,
    "registration_source": "offline_cash",
}

# Capture BEFORE state
sw_before = _get_system_wallet()
da_before = float((sw_before or {}).get("buckets", {}).get("direct_added") or 0)
admin_total_before = float((sw_before or {}).get("total") or 0)
bd_before = _get_breakdown()
drift_before = _compute_drift(bd_before)
record("10.1a.before_state_capture",
       sw_before is not None and bd_before is not None,
       f"direct_added={da_before} admin_total={admin_total_before} drift={drift_before}")

# (a) POST /admin/users/create
try:
    r = requests.post(f"{BASE}/admin/users/create",
                      headers=auth(admin_tok),
                      json=sponsor_payload, timeout=30)
    body = r.json() if r.status_code == 200 else {}
    user_id_with_sponsor = (body.get("user") or {}).get("id")
    record("10.1b.admin_create_user_with_sponsor",
           r.status_code == 200 and bool(user_id_with_sponsor),
           f"status={r.status_code} uid={user_id_with_sponsor} body_keys={list(body.keys())}")
except Exception as e:
    record("10.1b.admin_create_user_with_sponsor", False, f"exc={e}")
    user_id_with_sponsor = None

# (b) Verify offline_pre_credit_amount is set on the user doc
if user_id_with_sponsor:
    udoc = _get_user_doc_by_email(sponsor_email)
    opc = float((udoc or {}).get("offline_pre_credit_amount") or 0)
    record("10.1c.offline_pre_credit_amount_set",
           udoc is not None and abs(opc - fee_amount) < 0.01,
           f"opc={opc} expected={fee_amount} user_found={bool(udoc)}")
else:
    record("10.1c.offline_pre_credit_amount_set", False, "no user_id from create step")

# (c+d) Admin state right after create (direct_added should have INCREASED by fee)
sw_after_create = _get_system_wallet()
da_after_create = float((sw_after_create or {}).get("buckets", {}).get("direct_added") or 0)
record("10.1d.direct_added_increased_after_create",
       abs((da_after_create - da_before) - fee_amount) < 0.5,
       f"da_before={da_before} da_after_create={da_after_create} diff={round(da_after_create - da_before, 2)} expected≈{fee_amount}")

# (e) Approve the user
if user_id_with_sponsor:
    try:
        r = requests.post(f"{BASE}/admin/approvals/{user_id_with_sponsor}/approve",
                          headers=auth(admin_tok), timeout=30)
        record("10.1e.approve_user_with_sponsor",
               r.status_code == 200,
               f"status={r.status_code} body={r.text[:120]}")
    except Exception as e:
        record("10.1e.approve_user_with_sponsor", False, f"exc={e}")
else:
    record("10.1e.approve_user_with_sponsor", False, "no user_id")

# (f) Verify direct_added DECREASED by ~fee (back to ~da_before level)
sw_after_approve = _get_system_wallet()
da_after_approve = float((sw_after_approve or {}).get("buckets", {}).get("direct_added") or 0)
record("10.1f.direct_added_reversed_after_approve",
       abs(da_after_approve - da_before) < 0.5,
       f"da_before={da_before} da_after_create={da_after_create} da_after_approve={da_after_approve} "
       f"delta_vs_before={round(da_after_approve - da_before, 2)}")

# (g) Verify admin_debit reversal txn exists with is_offline_reversal=True
if user_id_with_sponsor:
    rev_txn = _find_reversal_txn_for_user(user_id_with_sponsor, admin_id_val)
    desc_ok = bool(rev_txn and "Offline pre-credit reversal" in (rev_txn.get("description") or ""))
    amt_ok = bool(rev_txn and abs(abs(float(rev_txn.get("amount") or 0)) - fee_amount) < 0.5)
    record("10.1g.admin_debit_reversal_txn_exists",
           bool(rev_txn) and desc_ok and amt_ok,
           f"found={bool(rev_txn)} desc_ok={desc_ok} amt_ok={amt_ok} "
           f"amount={(rev_txn or {}).get('amount')} desc={(rev_txn or {}).get('description','')[:80]}")
else:
    record("10.1g.admin_debit_reversal_txn_exists", False, "no user_id")

# (h) offline_pre_credit_amount should be GONE
if user_id_with_sponsor:
    udoc2 = _get_user_doc_by_email(sponsor_email)
    opc2 = udoc2.get("offline_pre_credit_amount") if udoc2 else "(no_user)"
    record("10.1h.offline_pre_credit_amount_unset_after_approve",
           udoc2 is not None and ("offline_pre_credit_amount" not in udoc2 or udoc2.get("offline_pre_credit_amount") in (None, 0, 0.0)),
           f"opc_after={opc2} keys_has_field={('offline_pre_credit_amount' in (udoc2 or {}))}")
else:
    record("10.1h.offline_pre_credit_amount_unset_after_approve", False, "no user_id")

# (i) Drift should be ≤ ₹1 (HEALED or stable)
bd_after = _get_breakdown()
drift_after = _compute_drift(bd_after)
record("10.1i.drift_within_1_rupee_after_approve",
       drift_after is not None and abs(drift_after) <= 1.0,
       f"drift_before={drift_before} drift_after={drift_after}")


# =============================================================
# 10.2  Offline-create WITHOUT sponsor (no_referral_signup=False,
#       sponsor_id=None → reversal must SKIP, pre-credit stays)
# =============================================================
suffix2 = _uuid.uuid4().hex[:8]
no_spons_email = f"asha.patel.ns.{suffix2}@networktest.in"
no_spons_payload = {
    "name": "Asha Patel NoSponsor",
    "email": no_spons_email,
    "password": "NoSpon@2026",
    "phone": "9000020002",
    "mark_paid_offline": True,
    "registration_source": "offline_cash",
    # NO referral_code
}

# Capture state BEFORE create (use post-10.1 state as new baseline)
sw_b2 = _get_system_wallet()
da_b2 = float((sw_b2 or {}).get("buckets", {}).get("direct_added") or 0)
bd_b2 = _get_breakdown()
drift_b2 = _compute_drift(bd_b2)

# (a) Create
try:
    r = requests.post(f"{BASE}/admin/users/create",
                      headers=auth(admin_tok),
                      json=no_spons_payload, timeout=30)
    body = r.json() if r.status_code == 200 else {}
    user_id_no_sponsor = (body.get("user") or {}).get("id")
    record("10.2a.admin_create_user_no_sponsor",
           r.status_code == 200 and bool(user_id_no_sponsor),
           f"status={r.status_code} uid={user_id_no_sponsor}")
except Exception as e:
    record("10.2a.admin_create_user_no_sponsor", False, f"exc={e}")
    user_id_no_sponsor = None

# (b) offline_pre_credit_amount is set
if user_id_no_sponsor:
    udoc = _get_user_doc_by_email(no_spons_email)
    opc = float((udoc or {}).get("offline_pre_credit_amount") or 0)
    has_no_sponsor = (udoc or {}).get("sponsor_id") in (None, "", 0)
    record("10.2b.no_sponsor_pre_credit_set",
           udoc is not None and abs(opc - fee_amount) < 0.01 and has_no_sponsor,
           f"opc={opc} sponsor_id={(udoc or {}).get('sponsor_id')!r}")
else:
    record("10.2b.no_sponsor_pre_credit_set", False, "no user_id")

# capture direct_added after create
sw_b2c = _get_system_wallet()
da_b2_after_create = float((sw_b2c or {}).get("buckets", {}).get("direct_added") or 0)

# (c) Approve
if user_id_no_sponsor:
    try:
        r = requests.post(f"{BASE}/admin/approvals/{user_id_no_sponsor}/approve",
                          headers=auth(admin_tok), timeout=30)
        record("10.2c.approve_no_sponsor_user",
               r.status_code == 200,
               f"status={r.status_code} body={r.text[:120]}")
    except Exception as e:
        record("10.2c.approve_no_sponsor_user", False, f"exc={e}")
else:
    record("10.2c.approve_no_sponsor_user", False, "no user_id")

# (d) direct_added UNCHANGED across approval (no reversal happened)
sw_b2_after = _get_system_wallet()
da_b2_after = float((sw_b2_after or {}).get("buckets", {}).get("direct_added") or 0)
record("10.2d.direct_added_unchanged_no_sponsor",
       abs(da_b2_after - da_b2_after_create) < 0.5,
       f"da_after_create={da_b2_after_create} da_after_approve={da_b2_after} "
       f"delta={round(da_b2_after - da_b2_after_create, 2)} (should be 0)")

# (e) NO admin_debit reversal txn for this user
if user_id_no_sponsor:
    rev_txn_ns = _find_reversal_txn_for_user(user_id_no_sponsor, admin_id_val)
    record("10.2e.no_reversal_txn_for_no_sponsor_user",
           rev_txn_ns is None,
           f"unexpected_txn={rev_txn_ns}")
else:
    record("10.2e.no_reversal_txn_for_no_sponsor_user", False, "no user_id")

# (f) Drift stable (within ₹1 of pre-create snapshot)
bd_b2_after = _get_breakdown()
drift_b2_after = _compute_drift(bd_b2_after)
record("10.2f.drift_stable_no_sponsor",
       drift_b2_after is not None and abs(drift_b2_after) <= 1.0,
       f"drift_before={drift_b2} drift_after={drift_b2_after}")


# =============================================================
# 10.3  Online register flow (no marker should be set)
# =============================================================
suffix3 = _uuid.uuid4().hex[:8]
online_email = f"online.user.{suffix3}@networktest.in"
try:
    r = requests.post(f"{BASE}/auth/register",
                      json={
                          "name": "Online Reg User",
                          "email": online_email,
                          "password": "Online@2026",
                          "phone": "9000030003",
                          # No referral_code → falls into no_referral_signup path
                      }, timeout=30)
    ok_reg = r.status_code in (200, 201)
    record("10.3a.online_register_ok",
           ok_reg,
           f"status={r.status_code} body={r.text[:120]}")
except Exception as e:
    record("10.3a.online_register_ok", False, f"exc={e}")
    ok_reg = False

if ok_reg:
    udoc_online = _get_user_doc_by_email(online_email)
    has_field = "offline_pre_credit_amount" in (udoc_online or {})
    field_val = (udoc_online or {}).get("offline_pre_credit_amount")
    # Acceptable: field absent OR explicitly None/0
    no_marker = (not has_field) or (field_val in (None, 0, 0.0))
    record("10.3b.online_register_no_offline_marker",
           udoc_online is not None and no_marker,
           f"user_found={bool(udoc_online)} has_field={has_field} val={field_val!r}")
else:
    record("10.3b.online_register_no_offline_marker", False, "register failed")


# =============================================================
# 10.4  Backend log sanity check (no 5xx / [LEDGER ALERT] in test window)
# =============================================================
import subprocess as _sp
try:
    full_err = _sp.run(
        ["tail", "-n", "1200", "/var/log/supervisor/backend.err.log"],
        capture_output=True, text=True, timeout=10,
    ).stdout or ""
    # Scope to log entries AFTER the most recent "Started server process"
    # marker so we only see the post-fix-deploy window relevant to this run.
    parts = full_err.split("Started server process")
    post_restart = parts[-1] if len(parts) > 1 else full_err
except Exception:
    post_restart = ""

has_5xx = "Internal Server Error" in post_restart or " 500 " in post_restart
has_traceback = "Traceback (most recent call last)" in post_restart
has_ledger_alert = "[LEDGER ALERT]" in post_restart
record("10.4.backend_logs_clean_no_new_alerts",
       not has_5xx and not has_traceback and not has_ledger_alert,
       f"post_restart_window — has_5xx={has_5xx} has_traceback={has_traceback} has_ledger_alert={has_ledger_alert}")


# ───────── Summary ─────────
print("\n" + "=" * 70)
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"SUMMARY: {passed}/{total} PASS\n")
for name, ok, detail in results:
    if not ok:
        print(f"  FAIL  {name}  — {detail}")
print("=" * 70)
sys.exit(0 if passed == total else 1)
