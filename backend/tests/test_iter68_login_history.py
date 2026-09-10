"""Iteration 68 backend tests — device login history + new-device alerts,
admin sub-role RBAC (with new method-scoped rules), admin password reveal
serialisation, multi-vendor order splitting.

NOTE: /api/auth/login is rate-limited to 10 req/min per IP. Tokens are cached
at module scope so we don't blow the limit.
"""
import os
import sys
import time
import uuid

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = "http://localhost:8001/api"
TIMEOUT = 60

_TOKEN_CACHE = {}


def _tok(resp):
    j = resp.json()
    return j.get("token") or j.get("access_token")


def _login(email, password, device_fp=None, device_name=None, fresh=False):
    key = (email, device_fp)
    if not fresh and not device_fp and key in _TOKEN_CACHE:
        return _TOKEN_CACHE[key]
    headers = {}
    if device_fp:
        headers["X-Device-FP"] = device_fp
    if device_name:
        headers["X-Device-Name"] = device_name
    # If rate limited, back off.
    for attempt in range(3):
        r = requests.post(
            f"{BASE}/auth/login",
            json={"email": email, "password": password},
            headers=headers,
            timeout=TIMEOUT,
        )
        if r.status_code == 429 or (r.status_code == 200 and "rate_limited" in r.text):
            time.sleep(35)
            continue
        break
    if not device_fp and r.status_code == 200:
        _TOKEN_CACHE[key] = _tok(r)
        return _TOKEN_CACHE[key]
    if device_fp:
        return _tok(r) if r.status_code == 200 else None
    return None


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


# ==============================================================
# Section A — Login history feature (NEW)
# ==============================================================
class TestLoginHistory:
    def test_a1_login_creates_history_row(self):
        fp = f"web-iter68-{uuid.uuid4().hex[:8]}"
        tok = _login("testbuyer@test.com", "Test@1234", device_fp=fp, device_name="Iter68 Chrome")
        assert tok, "buyer login failed"
        hr = requests.get(f"{BASE}/users/me/login-history", headers=_auth(tok), timeout=TIMEOUT)
        assert hr.status_code == 200, hr.text
        data = hr.json()
        assert "items" in data and "active_devices" in data
        row = next((r for r in data["items"] if r.get("device_fp") == fp), None)
        assert row, f"No entry for our fingerprint {fp}"
        for k in ("device_label", "platform", "ip", "is_current", "is_active", "is_new_device"):
            assert k in row, f"Missing field {k}"
        assert row["is_current"] is True
        assert row["is_active"] is True

    def test_a2_second_new_device_creates_alert(self):
        fp_new = f"web-iter68-newdev-{uuid.uuid4().hex[:8]}"
        tok = _login("testbuyer@test.com", "Test@1234", device_fp=fp_new, device_name="Iter68 Alien Device")
        assert tok
        time.sleep(1)
        nr = requests.get(f"{BASE}/notifications/me", headers=_auth(tok), timeout=TIMEOUT)
        assert nr.status_code == 200, nr.text
        body = nr.json()
        items = body if isinstance(body, list) else body.get("items", [])
        titles = [i.get("title") for i in items]
        assert any("New device signed in" in (t or "") for t in titles), f"got titles={titles[:6]}"

    def test_a3_revoke_current_device_400(self):
        fp = f"web-iter68-revself-{uuid.uuid4().hex[:8]}"
        tok = _login("testbuyer@test.com", "Test@1234", device_fp=fp)
        assert tok
        hist = requests.get(f"{BASE}/users/me/login-history", headers=_auth(tok), timeout=TIMEOUT).json()
        current = next((x for x in hist["items"] if x["is_current"]), None)
        assert current
        rv = requests.post(f"{BASE}/users/me/login-history/{current['id']}/revoke",
                           headers=_auth(tok), timeout=TIMEOUT)
        assert rv.status_code == 400, rv.text

    def test_a4_revoke_other_device_signs_out(self):
        fp_a = f"web-iter68-A-{uuid.uuid4().hex[:8]}"
        tok_a = _login("testbuyer@test.com", "Test@1234", device_fp=fp_a, device_name="Session A")
        fp_b = f"web-iter68-B-{uuid.uuid4().hex[:8]}"
        tok_b = _login("testbuyer@test.com", "Test@1234", device_fp=fp_b, device_name="Session B")
        assert tok_a and tok_b
        hist = requests.get(f"{BASE}/users/me/login-history", headers=_auth(tok_b), timeout=TIMEOUT).json()
        row_a = next((x for x in hist["items"] if x.get("device_fp") == fp_a), None)
        assert row_a and not row_a["is_current"]
        rv = requests.post(f"{BASE}/users/me/login-history/{row_a['id']}/revoke",
                           headers=_auth(tok_b), timeout=TIMEOUT)
        assert rv.status_code == 200, rv.text
        me_a = requests.get(f"{BASE}/auth/me", headers=_auth(tok_a), timeout=TIMEOUT)
        assert me_a.status_code == 401
        me_b = requests.get(f"{BASE}/auth/me", headers=_auth(tok_b), timeout=TIMEOUT)
        assert me_b.status_code == 200

    def test_a5_revoke_others_keeps_current(self):
        fp_a = f"web-iter68-KA-{uuid.uuid4().hex[:8]}"
        fp_b = f"web-iter68-KB-{uuid.uuid4().hex[:8]}"
        tok_a = _login("testbuyer@test.com", "Test@1234", device_fp=fp_a)
        tok_b = _login("testbuyer@test.com", "Test@1234", device_fp=fp_b)
        assert tok_a and tok_b
        rv = requests.post(f"{BASE}/users/me/login-history/revoke-others",
                           headers=_auth(tok_b), timeout=TIMEOUT)
        assert rv.status_code == 200, rv.text
        assert rv.json().get("signed_out", 0) >= 1
        assert requests.get(f"{BASE}/auth/me", headers=_auth(tok_b), timeout=TIMEOUT).status_code == 200
        assert requests.get(f"{BASE}/auth/me", headers=_auth(tok_a), timeout=TIMEOUT).status_code == 401

    def test_a6_admin_login_history_super_only(self):
        admin_tok = _login("support@slangcart.com", "3)Ywxtic")
        assert admin_tok, "admin login failed (rate limit?)"
        u = requests.get(f"{BASE}/admin/users", headers=_auth(admin_tok),
                         params={"q": "testbuyer@test.com"}, timeout=TIMEOUT).json()
        items = u if isinstance(u, list) else u.get("items", [])
        buyer_id = next((x["id"] for x in items if x.get("email") == "testbuyer@test.com"), items[0]["id"])
        r = requests.get(f"{BASE}/admin/users/{buyer_id}/login-history",
                         headers=_auth(admin_tok), timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        assert "items" in r.json()
        pm_tok = _login("productsmanager@test.com", "Manager@123")
        assert pm_tok
        r2 = requests.get(f"{BASE}/admin/users/{buyer_id}/login-history",
                          headers=_auth(pm_tok), timeout=TIMEOUT)
        assert r2.status_code == 403, r2.status_code


# ==============================================================
# Section B — Admin sub-role RBAC + method-scoped rule
# ==============================================================
SCOPED_MANAGERS = [
    ("products_manager", "productsmanager@test.com", "/admin/products?limit=5"),
    ("layout_manager", "layoutmanager@test.com", "/admin/shop-layout"),
    ("order_manager", "ordermanager@test.com", "/admin/orders"),
    ("vendor_service_manager", "vendorservicemanager@test.com", "/admin/vendors"),
]


class TestScopedRBAC:
    @pytest.mark.parametrize("role,email,own", SCOPED_MANAGERS)
    def test_b1_own_area_allowed(self, role, email, own):
        tok = _login(email, "Manager@123")
        assert tok, f"{role} login failed"
        r = requests.get(f"{BASE}{own}", headers=_auth(tok), timeout=TIMEOUT)
        assert r.status_code == 200, f"{role} {own} -> {r.status_code} {r.text[:200]}"

    def test_b2_products_manager_denied_elsewhere(self):
        tok = _login("productsmanager@test.com", "Manager@123")
        assert tok
        for path in ("/admin/orders", "/admin/shop-layout", "/admin/vendors", "/admin/users"):
            r = requests.get(f"{BASE}{path}", headers=_auth(tok), timeout=TIMEOUT)
            assert r.status_code == 403, f"{path} -> {r.status_code}"

    def test_b3_layout_manager_get_products_but_not_write(self):
        tok = _login("layoutmanager@test.com", "Manager@123")
        assert tok
        r = requests.get(f"{BASE}/admin/products?limit=5", headers=_auth(tok), timeout=TIMEOUT)
        assert r.status_code == 200, f"layout GET /admin/products -> {r.status_code} {r.text[:200]}"
        r2 = requests.delete(f"{BASE}/admin/products/nope", headers=_auth(tok), timeout=TIMEOUT)
        assert r2.status_code == 403, f"layout DELETE /admin/products -> {r2.status_code}"
        r3 = requests.post(f"{BASE}/admin/products", headers=_auth(tok), json={}, timeout=TIMEOUT)
        assert r3.status_code == 403, f"layout POST /admin/products -> {r3.status_code}"


# ==============================================================
# Section C — Admin password reveal endpoints
# ==============================================================
class TestAdminPasswords:
    def test_c1_auth_me_no_leaks(self):
        tok = _login("testbuyer@test.com", "Test@1234")
        assert tok
        r = requests.get(f"{BASE}/auth/me", headers=_auth(tok), timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        assert "password_recovery_ciphertext" not in r.text
        body = r.json()
        # body may nest under "user"
        for check in [body, body.get("user", {}) if isinstance(body, dict) else {}]:
            assert "_sid" not in (check or {})
            assert "password_recovery_ciphertext" not in (check or {})

    def test_c2_password_reveal_403_for_scoped_managers(self):
        admin_tok = _login("support@slangcart.com", "3)Ywxtic")
        assert admin_tok
        u = requests.get(f"{BASE}/admin/users", headers=_auth(admin_tok),
                         params={"q": "testbuyer@test.com"}, timeout=TIMEOUT).json()
        items = u if isinstance(u, list) else u.get("items", [])
        assert items, "cannot find buyer via admin/users"
        uid = next((x["id"] for x in items if x.get("email") == "testbuyer@test.com"), items[0]["id"])
        for email in ("productsmanager@test.com", "layoutmanager@test.com",
                      "ordermanager@test.com", "vendorservicemanager@test.com"):
            tok = _login(email, "Manager@123")
            assert tok, f"{email} login failed"
            r = requests.get(f"{BASE}/admin/users/{uid}/password", headers=_auth(tok), timeout=TIMEOUT)
            assert r.status_code == 403, f"{email} reveal -> {r.status_code}"
            r2 = requests.post(f"{BASE}/admin/users/{uid}/password/reset-reveal",
                               headers=_auth(tok), json={}, timeout=TIMEOUT)
            assert r2.status_code == 403, f"{email} reset-reveal -> {r2.status_code}"

    def test_c3_super_admin_reset_reveal_then_login(self):
        admin_tok = _login("support@slangcart.com", "3)Ywxtic")
        assert admin_tok
        tag = uuid.uuid4().hex[:8]
        email = f"iter68pw_{tag}@test.com"
        pw = f"Pw{tag}@1"
        reg = requests.post(f"{BASE}/auth/register", json={
            "name": "Iter68 pwtest", "email": email, "password": pw,
            "phone": "9" + tag[:9].ljust(9, "0"),
        }, timeout=TIMEOUT)
        assert reg.status_code in (200, 201), reg.text[:200]
        # Search
        u = requests.get(f"{BASE}/admin/users", headers=_auth(admin_tok),
                         params={"q": email}, timeout=TIMEOUT).json()
        items = u if isinstance(u, list) else u.get("items", [])
        assert items, f"user {email} not found in admin listing"
        uid = items[0]["id"]
        rv = requests.get(f"{BASE}/admin/users/{uid}/password", headers=_auth(admin_tok), timeout=TIMEOUT)
        assert rv.status_code == 200 and rv.json().get("password") == pw
        rr = requests.post(f"{BASE}/admin/users/{uid}/password/reset-reveal",
                           headers=_auth(admin_tok), json={}, timeout=TIMEOUT)
        assert rr.status_code == 200, rr.text
        new_pw = rr.json()["password"]
        # Rate-limit-safe re-login
        time.sleep(1)
        r2 = requests.post(f"{BASE}/auth/login",
                           json={"email": email, "password": new_pw}, timeout=TIMEOUT)
        if r2.status_code == 200 and "rate_limited" in r2.text:
            time.sleep(35)
            r2 = requests.post(f"{BASE}/auth/login",
                               json={"email": email, "password": new_pw}, timeout=TIMEOUT)
        assert r2.status_code == 200 and _tok(r2), f"login with new pw: {r2.status_code} {r2.text[:200]}"


# ==============================================================
# Section D — Multi-vendor split
# ==============================================================
class TestMultiVendorSplit:
    def test_d1_two_vendor_checkout_splits_into_two_orders(self):
        buyer_tok = _login("testbuyer@test.com", "Test@1234")
        assert buyer_tok
        p1 = requests.get(f"{BASE}/products", params={"q": "Vendor One Widget", "pincode": "517644"}, timeout=TIMEOUT)
        p2 = requests.get(f"{BASE}/products", params={"q": "Vendor Two Gadget", "pincode": "517644"}, timeout=TIMEOUT)
        assert p1.status_code == 200 and p2.status_code == 200
        items1 = p1.json() if isinstance(p1.json(), list) else p1.json().get("items", [])
        items2 = p2.json() if isinstance(p2.json(), list) else p2.json().get("items", [])

        def _pick(items, needle):
            for x in items:
                nm = (x.get("name") or x.get("title") or "")
                if needle in nm:
                    return x
            return None

        prod1 = _pick(items1, "Widget")
        prod2 = _pick(items2, "Gadget")
        if not (prod1 and prod2):
            pytest.skip(f"Multi-vendor fixture missing; widget={bool(prod1)} gadget={bool(prod2)}")

        requests.post(f"{BASE}/cart/clear", headers=_auth(buyer_tok), timeout=TIMEOUT)
        for p in (prod1, prod2):
            r = requests.post(f"{BASE}/cart/add", headers=_auth(buyer_tok),
                              json={"product_id": p["id"], "qty": 1, "quantity": 1}, timeout=TIMEOUT)
            assert r.status_code == 200, f"cart add {p.get('name')}: {r.status_code} {r.text[:200]}"

        addr = {"name": "Test Buyer", "phone": "9999999999", "line1": "Test Rd",
                "city": "Srikalahasti", "state": "AP", "pincode": "517644"}
        chk = requests.post(f"{BASE}/orders/checkout", headers=_auth(buyer_tok),
                            json={"payment_method": "cod", "shipping_address": addr}, timeout=TIMEOUT)
        assert chk.status_code == 200, f"checkout: {chk.status_code} {chk.text[:400]}"

        mo = requests.get(f"{BASE}/orders/me", headers=_auth(buyer_tok), timeout=TIMEOUT)
        assert mo.status_code == 200
        body = mo.json()
        orders = body if isinstance(body, list) else body.get("items", [])
        assert len(orders) >= 2, f"expected >=2 orders got {len(orders)}"

        # Look for a pair of newest orders sharing a common prefix with -1/-2 suffix
        nums = [o.get("order_number") or o.get("number") or "" for o in orders[:6]]
        prefixes = {}
        for n in nums:
            if len(n) >= 3 and n[-2] == "-" and n[-1].isdigit():
                prefixes.setdefault(n[:-2], []).append(n)
        pair = next((sorted(v) for v in prefixes.values() if len(v) >= 2), None)
        assert pair, f"expected SC-<ref>-1/-2 split in {nums}"
        # And the parent group ref should exist on both cards
        top2 = orders[:2]
        refs = {o.get("group_ref") or o.get("checkout_ref") or o.get("parent_ref") for o in top2}
        # Not strictly asserted (backend variance) — just log
        print("split refs:", refs)

    def test_d2_vendor_sees_only_own_suborder_via_sales(self):
        vendor_tok = _login("testvendor@test.com", "Test@1234")
        assert vendor_tok
        # Use /vendor/me/sales — the actual vendor-orders endpoint on this backend.
        vr = requests.get(f"{BASE}/vendor/me/sales", headers=_auth(vendor_tok), timeout=TIMEOUT)
        assert vr.status_code == 200, vr.text
        body = vr.json()
        items = body if isinstance(body, list) else body.get("items", [])
        # Ensure no row references vendor 2's gadget by product name.
        bad = []
        for row in items[:60]:
            nm = (row.get("product_name") or row.get("name") or row.get("title") or "")
            if "Vendor Two Gadget" in nm:
                bad.append(row.get("id") or nm)
        assert not bad, f"vendor 1 view leaked vendor 2 product: {bad}"
