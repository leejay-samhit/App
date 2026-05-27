"""Phase 2B Iter 4 refactor regression test.

Validates 5 read endpoints moved from server.py into:
  • routes/wallet.py        — /transactions/me, /transactions/{id},
                              /transactions/{id}/invoice, /transactions/{id}/invoice.pdf
  • routes/withdrawals.py   — /withdrawals/me
  • routes/cart.py          — /cart, /cart/add, /cart/remove, /cart/clear, /orders/me

Plus regression checks on endpoints that STAYED in server.py.

Single login per role to respect 10/min/IP rate limit.
"""
from __future__ import annotations

import os
import sys
from typing import Dict, Optional

import requests


BASE = os.environ.get("BACKEND_URL", "https://vendor-network-app-1.preview.emergentagent.com").rstrip("/") + "/api"
ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"
USER_EMAIL = "testuser@app.com"
USER_PASSWORD = "Test@123"
QR_EMAIL = "qrtest@app.com"
QR_PASSWORD = "Qr@1234"


_results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    icon = "PASS" if ok else "FAIL"
    print(f"  [{icon}] {name}  {detail}")
    _results.append((name, ok, detail))


def login(email: str, password: str) -> Optional[dict]:
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=30)
    if r.status_code != 200:
        print(f"  login {email} HTTP {r.status_code}: {r.text[:200]}")
        return None
    return r.json()


def auth(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


print(f"\nBASE = {BASE}\n")

print("=== LOGIN (single login per role) ===")
admin_body = login(ADMIN_EMAIL, ADMIN_PASSWORD)
record("Login admin", admin_body is not None)
testuser_body = login(USER_EMAIL, USER_PASSWORD)
record("Login testuser", testuser_body is not None)
qruser_body = login(QR_EMAIL, QR_PASSWORD)
record("Login qrtest", qruser_body is not None)

if not (admin_body and testuser_body and qruser_body):
    print("\nCannot continue without all three logins — aborting.")
    sys.exit(1)

admin_token = admin_body.get("token") or admin_body.get("access_token")
testuser_token = testuser_body.get("token") or testuser_body.get("access_token")
qruser_token = qruser_body.get("token") or qruser_body.get("access_token")
admin_refresh = admin_body.get("refresh_token")

# ────────── 1) GET /transactions/me ──────────
print("\n=== 1) GET /transactions/me  (routes/wallet.py) ===")
r = requests.get(f"{BASE}/transactions/me", headers=auth(testuser_token), timeout=30)
default_list = r.json() if r.status_code == 200 else []
record("transactions/me default → 200 array", r.status_code == 200 and isinstance(default_list, list), f"HTTP {r.status_code} len={len(default_list)}")

if len(default_list) >= 2:
    dates = [t.get("created_at") or "" for t in default_list]
    sorted_ok = all(dates[i] >= dates[i + 1] for i in range(len(dates) - 1))
    record("transactions/me newest-first", sorted_ok, f"first={dates[0]} last={dates[-1]}")
else:
    record("transactions/me newest-first", True, f"only {len(default_list)} rows — vacuous")

r = requests.get(f"{BASE}/transactions/me?limit=5&offset=0", headers=auth(testuser_token), timeout=30)
page1 = r.json() if r.status_code == 200 else []
record("transactions/me ?limit=5&offset=0 ≤5", r.status_code == 200 and len(page1) <= 5, f"HTTP {r.status_code} len={len(page1)}")

r = requests.get(f"{BASE}/transactions/me?limit=5&offset=5", headers=auth(testuser_token), timeout=30)
page2 = r.json() if r.status_code == 200 else []
record("transactions/me ?limit=5&offset=5 ≤5", r.status_code == 200 and len(page2) <= 5, f"HTTP {r.status_code} len={len(page2)}")

r = requests.get(f"{BASE}/transactions/me?limit=0", headers=auth(testuser_token), timeout=30)
unbounded = r.json() if r.status_code == 200 else []
record("transactions/me ?limit=0 unbounded", r.status_code == 200 and isinstance(unbounded, list), f"HTTP {r.status_code} len={len(unbounded)}")

r = requests.get(f"{BASE}/transactions/me?include_pending=true", headers=auth(testuser_token), timeout=30)
with_pending = r.json() if r.status_code == 200 else []
record("transactions/me ?include_pending=true", r.status_code == 200 and isinstance(with_pending, list), f"HTTP {r.status_code} len={len(with_pending)} (≥ default {len(default_list)})")

r = requests.get(f"{BASE}/transactions/me", timeout=30)
record("transactions/me no-auth → 401", r.status_code in (401, 403), f"HTTP {r.status_code}")


# Helper: fetch admin's own transactions and an invoiceable registration_fee txn
# (from admin/transactions feed) so we can validate the routes even though testuser
# happens to have 0 txns in this env.
admin_my_txns_resp = requests.get(f"{BASE}/transactions/me?include_pending=true&limit=20", headers=auth(admin_token), timeout=30)
admin_my_txns = admin_my_txns_resp.json() if admin_my_txns_resp.status_code == 200 else []
admin_owned_id = admin_my_txns[0].get("id") if admin_my_txns else None

admin_feed_resp = requests.get(f"{BASE}/admin/transactions?limit=50", headers=auth(admin_token), timeout=30)
admin_feed = admin_feed_resp.json() if admin_feed_resp.status_code == 200 else []
# pick a registration_fee paid txn (invoiceable) NOT owned by admin / testuser / qruser
admin_user_id = admin_my_txns[0]["user_id"] if admin_my_txns else None
foreign_invoiceable = None
foreign_invoiceable_owner_email = None
for t in admin_feed:
    if t.get("type") == "registration_fee" and t.get("status") == "paid":
        if t.get("user_id") != admin_user_id:
            foreign_invoiceable = t
            foreign_invoiceable_owner_email = t.get("user_email")
            break

# ────────── 2) GET /transactions/{txn_id} ──────────
print("\n=== 2) GET /transactions/{txn_id}  (routes/wallet.py) ===")
sample_id = default_list[0].get("id") if default_list else admin_owned_id

if sample_id and admin_owned_id:
    # As owner (admin viewing one of its own txns)
    r = requests.get(f"{BASE}/transactions/{admin_owned_id}", headers=auth(admin_token), timeout=30)
    body = r.json() if r.status_code == 200 else {}
    required_keys = {"transaction", "owner", "counter_party", "counter_role", "auto_remarks", "utr", "invoice_number", "invoiceable"}
    record("transactions/{id} as owner → 200", r.status_code == 200, f"HTTP {r.status_code} owner=admin")
    record("transactions/{id} payload shape", required_keys.issubset(body.keys()), f"missing={required_keys - set(body.keys())}")

    # As admin viewing a DIFFERENT user's txn → 200 (admin_view branch)
    if foreign_invoiceable:
        r = requests.get(f"{BASE}/transactions/{foreign_invoiceable['id']}", headers=auth(admin_token), timeout=30)
        record("transactions/{id} as admin (other user's txn) → 200", r.status_code == 200, f"HTTP {r.status_code}")
    else:
        record("transactions/{id} as admin (other user's txn) → 200", False, "no foreign txn available")

    # As a different non-admin user → 403 (use qrtest against admin's txn OR against a foreign txn)
    target_for_403 = foreign_invoiceable["id"] if foreign_invoiceable else admin_owned_id
    r = requests.get(f"{BASE}/transactions/{target_for_403}", headers=auth(qruser_token), timeout=30)
    record("transactions/{id} as DIFFERENT non-admin → 403", r.status_code == 403, f"HTTP {r.status_code}")
else:
    record("transactions/{id} as owner → 200", False, "no sample available")
    record("transactions/{id} payload shape", False, "no sample")
    record("transactions/{id} as admin (other user's txn) → 200", False, "no sample")
    record("transactions/{id} as DIFFERENT non-admin → 403", False, "no sample")

r = requests.get(f"{BASE}/transactions/nonexistent-id-zzz-999", headers=auth(testuser_token), timeout=30)
record("transactions/{id} nonexistent → 404", r.status_code == 404, f"HTTP {r.status_code}")


# ────────── 3) GET /transactions/{txn_id}/invoice (HTML) ──────────
print("\n=== 3) GET /transactions/{txn_id}/invoice  (routes/wallet.py) ===")
invoiceable_id = foreign_invoiceable["id"] if foreign_invoiceable else None
non_invoiceable_id = None
# search admin's own txns for a non-invoiceable type
for t in admin_my_txns:
    if t.get("type") in ("withdrawal", "referral_payout", "cascade_overflow", "fee_residual", "direct_signup_credit", "gst_collected") and not non_invoiceable_id:
        non_invoiceable_id = t.get("id")
        break

if invoiceable_id:
    # Owner test impossible (we don't have that user's password), so test via admin_view (allowed)
    r = requests.get(f"{BASE}/transactions/{invoiceable_id}/invoice", headers=auth(admin_token), timeout=30)
    ctype = r.headers.get("content-type", "")
    record("invoice HTML as owner/admin → 200", r.status_code == 200, f"HTTP {r.status_code} (admin_view used since no test user owns a registration_fee txn)")
    record("invoice HTML content-type text/html", "text/html" in ctype, f"ctype={ctype}")

    r = requests.get(f"{BASE}/transactions/{invoiceable_id}/invoice", timeout=30)
    record("invoice HTML no-auth → 401", r.status_code in (401, 403), f"HTTP {r.status_code}")

    r = requests.get(f"{BASE}/transactions/{invoiceable_id}/invoice", headers=auth(qruser_token), timeout=30)
    record("invoice HTML other non-admin → 403", r.status_code == 403, f"HTTP {r.status_code}")
else:
    record("invoice HTML as owner/admin → 200", False, "no registration_fee paid txn in admin feed")

if non_invoiceable_id:
    r = requests.get(f"{BASE}/transactions/{non_invoiceable_id}/invoice", headers=auth(admin_token), timeout=30)
    record("invoice non-invoiceable txn no 5xx", r.status_code < 500, f"HTTP {r.status_code}")
else:
    record("invoice non-invoiceable txn no 5xx", True, "no non-invoiceable txn to test — skip")


# ────────── 4) GET /transactions/{txn_id}/invoice.pdf ──────────
print("\n=== 4) GET /transactions/{txn_id}/invoice.pdf  (routes/wallet.py) ===")
if invoiceable_id:
    r = requests.get(f"{BASE}/transactions/{invoiceable_id}/invoice.pdf", headers=auth(admin_token), timeout=60)
    ctype = r.headers.get("content-type", "")
    cdisp = r.headers.get("content-disposition", "")
    record("invoice.pdf as owner/admin → 200", r.status_code == 200, f"HTTP {r.status_code}")
    record("invoice.pdf content-type application/pdf", "application/pdf" in ctype, f"ctype={ctype}")
    record("invoice.pdf Content-Disposition has filename", "filename=" in cdisp, f"cdisp={cdisp[:80]}")

    r = requests.get(f"{BASE}/transactions/{invoiceable_id}/invoice.pdf", headers=auth(qruser_token), timeout=30)
    record("invoice.pdf other non-admin → 403", r.status_code == 403, f"HTTP {r.status_code}")
else:
    record("invoice.pdf as owner/admin → 200", False, "no invoiceable txn")


# ────────── 5) GET /withdrawals/me ──────────
print("\n=== 5) GET /withdrawals/me  (routes/withdrawals.py) ===")
r = requests.get(f"{BASE}/withdrawals/me", headers=auth(testuser_token), timeout=30)
wd_default = r.json() if r.status_code == 200 else []
record("withdrawals/me default 200", r.status_code == 200 and isinstance(wd_default, list), f"HTTP {r.status_code} len={len(wd_default)}")

r = requests.get(f"{BASE}/withdrawals/me?limit=3", headers=auth(testuser_token), timeout=30)
wd_p1 = r.json() if r.status_code == 200 else []
record("withdrawals/me ?limit=3 ≤3", r.status_code == 200 and len(wd_p1) <= 3, f"HTTP {r.status_code} len={len(wd_p1)}")

r = requests.get(f"{BASE}/withdrawals/me?limit=3&offset=3", headers=auth(testuser_token), timeout=30)
wd_p2 = r.json() if r.status_code == 200 else []
record("withdrawals/me ?limit=3&offset=3 ≤3", r.status_code == 200 and len(wd_p2) <= 3, f"HTTP {r.status_code} len={len(wd_p2)}")

r = requests.get(f"{BASE}/withdrawals/me", timeout=30)
record("withdrawals/me no-auth → 401", r.status_code in (401, 403), f"HTTP {r.status_code}")


# ────────── 6) Cart endpoints ──────────
print("\n=== 6) Cart endpoints  (routes/cart.py) ===")
r = requests.get(f"{BASE}/cart", headers=auth(testuser_token), timeout=30)
cart0 = r.json() if r.status_code == 200 else {}
required_cart = {"items", "total", "count"}
record("GET /cart → 200 shape", r.status_code == 200 and required_cart.issubset(cart0.keys()), f"HTTP {r.status_code} keys={list(cart0.keys()) if isinstance(cart0, dict) else cart0}")
original_count = cart0.get("count", 0) if isinstance(cart0, dict) else 0

r = requests.get(f"{BASE}/products", timeout=30)
products_raw = r.json() if r.status_code == 200 else []
products = products_raw if isinstance(products_raw, list) else products_raw.get("items", [])
record("GET /products → 200", r.status_code == 200 and len(products) > 0, f"HTTP {r.status_code} count={len(products)}")

product_id = None
for p in products:
    if p.get("is_in_stock") and (p.get("stock") or 0) > 0:
        product_id = p.get("id")
        break
if not product_id and products:
    product_id = products[0].get("id")

if product_id:
    r = requests.post(f"{BASE}/cart/add", json={"product_id": product_id, "qty": 1}, headers=auth(testuser_token), timeout=30)
    add_ok = r.status_code == 200 and r.json().get("ok") is True
    record("POST /cart/add → 200 {ok:true}", add_ok, f"HTTP {r.status_code} body={r.text[:120]}")

    r = requests.get(f"{BASE}/cart", headers=auth(testuser_token), timeout=30)
    cart1 = r.json() if r.status_code == 200 else {}
    record("GET /cart after add (count incremented)", cart1.get("count", -1) > original_count, f"orig={original_count} now={cart1.get('count')}")

    r = requests.post(f"{BASE}/cart/remove", json={"product_id": product_id}, headers=auth(testuser_token), timeout=30)
    record("POST /cart/remove → 200", r.status_code == 200 and r.json().get("ok") is True, f"HTTP {r.status_code}")

    r = requests.get(f"{BASE}/cart", headers=auth(testuser_token), timeout=30)
    cart2 = r.json() if r.status_code == 200 else {}
    record("GET /cart after remove (back to original)", cart2.get("count", -1) == original_count, f"orig={original_count} now={cart2.get('count')}")

    r = requests.post(f"{BASE}/cart/clear", headers=auth(testuser_token), timeout=30)
    record("POST /cart/clear → 200", r.status_code == 200 and r.json().get("ok") is True, f"HTTP {r.status_code}")

    r = requests.get(f"{BASE}/cart", headers=auth(testuser_token), timeout=30)
    cart3 = r.json() if r.status_code == 200 else {}
    record("GET /cart after clear (items=[])", cart3.get("items") == [] and cart3.get("count", -1) == 0, f"items_len={len(cart3.get('items', []))} count={cart3.get('count')}")
else:
    record("cart add/remove/clear flow", False, "no product available")

r = requests.get(f"{BASE}/cart", timeout=30)
record("GET /cart no-auth → 401", r.status_code in (401, 403), f"HTTP {r.status_code}")
r = requests.post(f"{BASE}/cart/add", json={"product_id": product_id or "x", "qty": 1}, timeout=30)
record("POST /cart/add no-auth → 401", r.status_code in (401, 403), f"HTTP {r.status_code}")
r = requests.post(f"{BASE}/cart/remove", json={"product_id": product_id or "x"}, timeout=30)
record("POST /cart/remove no-auth → 401", r.status_code in (401, 403), f"HTTP {r.status_code}")
r = requests.post(f"{BASE}/cart/clear", timeout=30)
record("POST /cart/clear no-auth → 401", r.status_code in (401, 403), f"HTTP {r.status_code}")


# ────────── 7) GET /orders/me ──────────
print("\n=== 7) GET /orders/me  (routes/cart.py) ===")
r = requests.get(f"{BASE}/orders/me", headers=auth(testuser_token), timeout=30)
record("orders/me as testuser → 200 array", r.status_code == 200 and isinstance(r.json(), list), f"HTTP {r.status_code} len={len(r.json()) if r.status_code==200 else 'n/a'}")

r = requests.get(f"{BASE}/orders/me", timeout=30)
record("orders/me no-auth → 401", r.status_code in (401, 403), f"HTTP {r.status_code}")


# ────────── 8) REGRESSION ──────────
print("\n=== 8) REGRESSION (endpoints still in server.py) ===")

# Admin source-breakdown FIRST (before refresh, in case refresh invalidates the access token)
r = requests.get(f"{BASE}/admin/system-wallet/source-breakdown", headers=auth(admin_token), timeout=30)
record("GET /admin/system-wallet/source-breakdown 200", r.status_code == 200, f"HTTP {r.status_code}")

# /products + /shop-categories
r = requests.get(f"{BASE}/products", timeout=30)
record("GET /products 200", r.status_code == 200, f"HTTP {r.status_code}")
r = requests.get(f"{BASE}/shop-categories", timeout=30)
record("GET /shop-categories 200", r.status_code == 200, f"HTTP {r.status_code}")

# POST /withdrawals (works OR expected 400 for ineligible)
r = requests.post(f"{BASE}/withdrawals", json={"amount": 1}, headers=auth(testuser_token), timeout=30)
record("POST /withdrawals still works or expected 400/422", r.status_code in (200, 400, 422), f"HTTP {r.status_code} body={r.text[:160]}")

# POST /orders/checkout (works OR expected 400)
r = requests.post(f"{BASE}/orders/checkout", headers=auth(testuser_token), timeout=30)
record("POST /orders/checkout still works or expected 400", r.status_code in (200, 400, 422), f"HTTP {r.status_code} body={r.text[:160]}")

# POST /wallet/transfer (works OR expected 400). Use the model field 'recipient'.
r = requests.post(f"{BASE}/wallet/transfer", json={"recipient": "ADMIN001", "amount": 1}, headers=auth(testuser_token), timeout=30)
record("POST /wallet/transfer still works or expected 400", r.status_code in (200, 400, 403, 404, 422), f"HTTP {r.status_code} body={r.text[:160]}")

# Already validated /auth/login above. Validate /auth/refresh rotates LAST (it may invalidate tokens).
if admin_refresh:
    r = requests.post(f"{BASE}/auth/refresh", json={"refresh_token": admin_refresh}, timeout=30)
    body = r.json() if r.status_code == 200 else {}
    new_refresh = body.get("refresh_token")
    record("POST /auth/refresh → 200", r.status_code == 200, f"HTTP {r.status_code}")
    record("auth/refresh rotates refresh_token", bool(new_refresh) and new_refresh != admin_refresh, f"rotated={new_refresh != admin_refresh}")
else:
    record("POST /auth/refresh → 200", False, "no refresh_token on initial login response")
    record("auth/refresh rotates refresh_token", False, "no refresh_token")


# ────────── Summary ──────────
print("\n" + "=" * 70)
total = len(_results)
passed = sum(1 for _, ok, _ in _results if ok)
print(f"PHASE 2B ITER 4 REGRESSION: {passed}/{total} PASS")
print("=" * 70)
if passed < total:
    print("\nFAILURES:")
    for name, ok, detail in _results:
        if not ok:
            print(f"  [FAIL] {name}  {detail}")
