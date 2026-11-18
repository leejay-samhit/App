"""Nov 2026 — Vendor edit-requests, geo, product pincode filter, checkout guard.

Covers:
  1. Vendor edit-request submission / listing / approve / reject
  2. Geo forward/reverse/pincode endpoints (Nominatim proxy)
  3. Public products ?pincode= filter
  4. /orders/checkout out_of_delivery_zone guard

Runs against the live backend at BASE_URL (localhost:8001).
"""
from __future__ import annotations
import os
import uuid
import time
import pytest
import requests

BASE_URL = (os.environ.get("BACKEND_URL_OVERRIDE") or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "support@networkrupay.com"
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

# Shared state populated by fixtures / early tests
STATE: dict = {
    "admin_token": None,
    "vendor_token": None,
    "vendor_id": None,
    "vendor_email": None,
    "vendor_app_id": None,
    "vendor_edit_request_id": None,
    "product_id": None,
}

VENDOR_PINCODE = "500001"       # Hyderabad
CUSTOMER_BAD_PINCODE = "600001"  # Chennai — should be blocked


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ────────────────────────────────────────────────────────────
# Fixtures: admin login → create+approve vendor → apply → approve app → publish a product
# ────────────────────────────────────────────────────────────
@pytest.fixture(scope="module", autouse=True)
def bootstrap_admin_and_vendor():
    # 1. Admin login
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    STATE["admin_token"] = r.json()["token"]
    admin_h = _auth(STATE["admin_token"])

    # 2. Create a fresh vendor user via admin/users/create
    suffix = uuid.uuid4().hex[:6]
    vendor_email = f"test_vendor_{suffix}@test.com"
    vendor_password = "Vendor@1234"
    r = requests.post(
        f"{API}/admin/users/create",
        headers=admin_h,
        json={
            "name": f"TEST Vendor {suffix}",
            "email": vendor_email,
            "password": vendor_password,
            "phone": "9999900001",
            "mark_paid_offline": True,
            "registration_source": "offline_cash",
        },
        timeout=15,
    )
    assert r.status_code in (200, 201), f"admin_create_user failed: {r.status_code} {r.text}"
    body = r.json()
    vendor_id = body.get("user", {}).get("id") or body.get("id")
    if not vendor_id:
        # fall back: look up in admin/users
        r2 = requests.get(f"{API}/admin/users", headers=admin_h, params={"q": vendor_email}, timeout=15)
        if r2.status_code == 200:
            users = r2.json().get("users") or r2.json().get("items") or []
            for u in users:
                if u.get("email") == vendor_email:
                    vendor_id = u["id"]; break
    assert vendor_id, f"could not resolve created vendor id: {body}"
    STATE["vendor_id"] = vendor_id
    STATE["vendor_email"] = vendor_email

    # 3. Approve the user via /admin/approvals/{id}/approve
    r = requests.post(f"{API}/admin/approvals/{vendor_id}/approve", headers=admin_h, timeout=15)
    assert r.status_code in (200, 201), f"approve user failed: {r.status_code} {r.text}"

    # 4. Vendor login
    r = requests.post(f"{API}/auth/login", json={"email": vendor_email, "password": vendor_password}, timeout=15)
    assert r.status_code == 200, f"vendor login failed: {r.status_code} {r.text}"
    STATE["vendor_token"] = r.json()["token"]
    vendor_h = _auth(STATE["vendor_token"])

    # 5. Vendor applies with location details
    r = requests.post(
        f"{API}/vendor/apply",
        headers=vendor_h,
        json={
            "shop_name": f"TEST Shop {suffix}",
            "pincode": VENDOR_PINCODE,
            "state": "Telangana",
            "district": "Hyderabad",
            "city": "Hyderabad",
            "store_address": "TEST Store, MG Road",
            "delivery_radius_km": 15,
            "delivery_radius_mode": "pincode",
            "delivery_available": True,
            "location": {"type": "Point", "coordinates": [78.4867, 17.3850]},
        },
        timeout=15,
    )
    assert r.status_code in (200, 201), f"vendor apply failed: {r.status_code} {r.text}"

    # find the pending application id via admin
    r = requests.get(f"{API}/admin/vendor-applications", headers=admin_h, params={"status": "pending"}, timeout=15)
    assert r.status_code == 200
    apps = r.json().get("items") or r.json().get("applications") or r.json()
    app_id = None
    for a in apps if isinstance(apps, list) else []:
        if a.get("user_id") == vendor_id:
            app_id = a["id"]; break
    assert app_id, f"vendor application not visible to admin: {apps}"
    STATE["vendor_app_id"] = app_id

    # 6. Admin approves the application
    r = requests.post(f"{API}/admin/vendor-applications/{app_id}/approve", headers=admin_h, timeout=15)
    assert r.status_code in (200, 201), f"admin approve vendor failed: {r.status_code} {r.text}"

    # 7. Vendor creates a product (which should carry store_pincode from user doc)
    r = requests.post(
        f"{API}/vendor/me/products",
        headers=vendor_h,
        json={
            "name": f"TEST Nov26 Product {suffix}",
            "price": 999.0,
            "image_url": "https://example.com/x.jpg",
            "description": "test",
            "stock": 10,
            "category": "General",
        },
        timeout=15,
    )
    assert r.status_code in (200, 201), f"vendor create product failed: {r.status_code} {r.text}"
    prod = r.json()
    STATE["product_id"] = prod["id"]
    assert prod.get("store_pincode") == VENDOR_PINCODE, f"store_pincode not stamped on new product: {prod.get('store_pincode')}"

    # admin publishes it so it's visible in /products
    r = requests.patch(
        f"{API}/admin/products/{prod['id']}",
        headers=admin_h,
        json={"is_published": True},
        timeout=15,
    )
    assert r.status_code in (200, 201), f"admin publish failed: {r.status_code} {r.text}"

    yield

    # Cleanup — best effort
    try:
        requests.delete(f"{API}/admin/products/{STATE['product_id']}", headers=admin_h, timeout=10)
        requests.delete(f"{API}/admin/users/{vendor_id}", headers=admin_h, timeout=10)
    except Exception:
        pass


# ────────────────────────────────────────────────────────────
# 1. Vendor edit-requests
# ────────────────────────────────────────────────────────────
class TestVendorEditRequests:
    def test_submit_edit_request(self):
        vh = _auth(STATE["vendor_token"])
        r = requests.post(
            f"{API}/vendor/edit-requests",
            headers=vh,
            json={"shop_name": "TEST Shop Renamed", "note": "brand refresh"},
            timeout=15,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        assert body["status"] == "pending"
        assert body["changes"]["shop_name"] == "TEST Shop Renamed"
        assert "current" in body and "shop_name" in body["current"]
        STATE["vendor_edit_request_id"] = body["id"]

    def test_second_pending_submission_blocked(self):
        vh = _auth(STATE["vendor_token"])
        r = requests.post(
            f"{API}/vendor/edit-requests",
            headers=vh,
            json={"description": "another change"},
            timeout=15,
        )
        assert r.status_code == 400, f"expected 400 got {r.status_code} {r.text}"
        assert "pending" in r.text.lower()

    def test_mine_returns_history(self):
        vh = _auth(STATE["vendor_token"])
        r = requests.get(f"{API}/vendor/edit-requests/mine", headers=vh, timeout=15)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        items = r.json()["items"]
        assert len(items) >= 1
        assert any(x["id"] == STATE["vendor_edit_request_id"] for x in items)

    def test_admin_list_pending(self):
        ah = _auth(STATE["admin_token"])
        r = requests.get(f"{API}/admin/vendor-edit-requests", headers=ah, params={"status": "pending"}, timeout=15)
        assert r.status_code == 200
        items = r.json()["items"]
        assert any(x["id"] == STATE["vendor_edit_request_id"] for x in items)

    def test_admin_approve_applies_changes(self):
        ah = _auth(STATE["admin_token"])
        req_id = STATE["vendor_edit_request_id"]
        r = requests.post(f"{API}/admin/vendor-edit-requests/{req_id}/approve", headers=ah, timeout=15)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        assert r.json()["status"] == "approved"

    def test_second_request_after_approval_allowed_with_pincode_change(self):
        """Now that no pending exists, submit a pincode change; then approve
        it and verify products get denormalised store_pincode."""
        vh = _auth(STATE["vendor_token"])
        new_pin = "560001"  # Bangalore
        r = requests.post(
            f"{API}/vendor/edit-requests",
            headers=vh,
            json={"pincode": new_pin},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        req_id = r.json()["id"]

        ah = _auth(STATE["admin_token"])
        r = requests.post(f"{API}/admin/vendor-edit-requests/{req_id}/approve", headers=ah, timeout=15)
        assert r.status_code == 200, r.text

        # Verify the vendor's product now carries the new pincode
        r = requests.get(f"{API}/products/{STATE['product_id']}", timeout=15)
        assert r.status_code == 200
        assert r.json().get("store_pincode") == new_pin, f"product not denormalised: {r.json().get('store_pincode')}"

        # Reset back to VENDOR_PINCODE so downstream checkout tests still work
        r = requests.post(f"{API}/vendor/edit-requests", headers=vh, json={"pincode": VENDOR_PINCODE}, timeout=15)
        assert r.status_code == 200, r.text
        req_id2 = r.json()["id"]
        r = requests.post(f"{API}/admin/vendor-edit-requests/{req_id2}/approve", headers=ah, timeout=15)
        assert r.status_code == 200

    def test_reject_flow(self):
        vh = _auth(STATE["vendor_token"])
        r = requests.post(f"{API}/vendor/edit-requests", headers=vh, json={"description": "yet another"}, timeout=15)
        assert r.status_code == 200, r.text
        req_id = r.json()["id"]

        ah = _auth(STATE["admin_token"])
        r = requests.post(
            f"{API}/admin/vendor-edit-requests/{req_id}/reject",
            headers=ah,
            json={"reason": "test"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "rejected"
        assert r.json()["reject_reason"] == "test"

    def test_non_vendor_forbidden(self):
        # Register a fresh non-vendor user & try to POST /vendor/edit-requests
        suffix = uuid.uuid4().hex[:6]
        email = f"test_nonvend_{suffix}@test.com"
        r = requests.post(f"{API}/auth/register", json={
            "name": f"NV {suffix}", "email": email, "password": "Passw0rd!",
        }, timeout=15)
        assert r.status_code in (200, 201), r.text
        tok = r.json()["token"]
        r = requests.post(f"{API}/vendor/edit-requests", headers=_auth(tok), json={"shop_name": "X"}, timeout=15)
        assert r.status_code == 403, f"expected 403 got {r.status_code} {r.text}"


# ────────────────────────────────────────────────────────────
# 2. Geo endpoints
# ────────────────────────────────────────────────────────────
class TestGeo:
    def test_geo_search_place(self):
        # Nominatim is rate-limited; give it up to 15s
        r = requests.get(f"{API}/geo/search", params={"q": "Srikalahasti"}, timeout=20)
        # If Nominatim is down we accept 502 and skip
        if r.status_code == 502:
            pytest.skip("Nominatim unreachable from sandbox")
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        items = r.json()["items"]
        assert isinstance(items, list) and len(items) >= 1
        first = items[0]
        assert "pincode" in first and "state" in first and "area" in first
        # Loose pincode check — Srikalahasti PIN ranges ~517640s
        assert first.get("state", "").lower().find("andhra") != -1 or first.get("pincode", "").startswith("5176")

    def test_geo_search_pincode_shortcut(self):
        # Whether or not the local pincodes table has 517644, we should
        # get a valid response (either from Mongo or Nominatim)
        r = requests.get(f"{API}/geo/search", params={"q": "517644"}, timeout=20)
        if r.status_code == 502:
            pytest.skip("Nominatim unreachable and pincode not in local table")
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        assert isinstance(r.json()["items"], list)

    def test_geo_reverse(self):
        time.sleep(1.2)  # honour 1 rps politely
        r = requests.get(f"{API}/geo/reverse", params={"lat": 13.75, "lng": 79.70}, timeout=20)
        if r.status_code == 502:
            pytest.skip("Nominatim unreachable")
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        assert "pincode" in body and "state" in body

    def test_geo_pincode_lookup(self):
        r = requests.get(f"{API}/geo/pincode/517644", timeout=10)
        assert r.status_code in (200, 404), f"unexpected {r.status_code} {r.text}"
        if r.status_code == 200:
            body = r.json()
            assert body["pincode"] == "517644"

    def test_geo_pincode_invalid(self):
        r = requests.get(f"{API}/geo/pincode/abc12", timeout=10)
        assert r.status_code == 400


# ────────────────────────────────────────────────────────────
# 3. Product pincode filter
# ────────────────────────────────────────────────────────────
class TestProductPincodeFilter:
    def test_filter_returns_matching(self):
        r = requests.get(f"{API}/products", params={"pincode": VENDOR_PINCODE}, timeout=15)
        assert r.status_code == 200
        body = r.json()
        items = body["items"] if isinstance(body, dict) else body
        ids = [p["id"] for p in items]
        assert STATE["product_id"] in ids, f"product not in filter result. sample ids: {ids[:5]}"

    def test_filter_excludes_mismatch_but_keeps_legacy(self):
        # products with no store_pincode = legacy fallback → still returned
        r = requests.get(f"{API}/products", params={"pincode": CUSTOMER_BAD_PINCODE}, timeout=15)
        assert r.status_code == 200
        items = r.json()["items"]
        # Our test vendor product has store_pincode=500001 → should NOT be here
        ids = [p["id"] for p in items]
        assert STATE["product_id"] not in ids, "product with mismatched pincode still returned"
        # Any product returned must either match or have no store_pincode
        for p in items:
            sp = p.get("store_pincode")
            assert sp in (None, "", CUSTOMER_BAD_PINCODE), f"unexpected store_pincode leak: {sp}"


# ────────────────────────────────────────────────────────────
# 4. Checkout guard (out_of_delivery_zone)
# ────────────────────────────────────────────────────────────
class TestCheckoutGuard:
    @pytest.fixture(autouse=True)
    def _customer(self):
        # Register a customer with wallet funds so checkout can succeed
        suffix = uuid.uuid4().hex[:6]
        email = f"test_cust_{suffix}@test.com"
        r = requests.post(f"{API}/auth/register", json={
            "name": f"Cust {suffix}", "email": email, "password": "Passw0rd!",
        }, timeout=15)
        assert r.status_code in (200, 201), r.text
        self.cust_email = email
        self.cust_token = r.json()["token"]
        self.cust_id = r.json()["user"]["id"]

        # Approve + top up wallet as admin so wallet checkout works
        ah = _auth(STATE["admin_token"])
        requests.post(f"{API}/admin/approvals/{self.cust_id}/approve", headers=ah, timeout=15)
        requests.post(
            f"{API}/admin/users/{self.cust_id}/wallet",
            headers=ah,
            json={"amount": 5000.0, "type": "credit", "reason": "TEST topup"},
            timeout=15,
        )

        # Add the vendor product to cart
        ch = _auth(self.cust_token)
        r = requests.post(
            f"{API}/cart/add",
            headers=ch,
            json={"product_id": STATE["product_id"], "qty": 1},
            timeout=15,
        )
        assert r.status_code in (200, 201), f"add to cart failed: {r.status_code} {r.text}"
        self.ch = ch
        yield
        # cleanup
        try:
            requests.delete(f"{API}/admin/users/{self.cust_id}", headers=ah, timeout=10)
        except Exception:
            pass

    def test_out_of_zone_blocks(self):
        r = requests.post(
            f"{API}/orders/checkout",
            headers=self.ch,
            json={
                "payment_method": "wallet",
                "shipping_address": {
                    "name": "Test C", "phone": "9998887777",
                    "line1": "1 Main St", "city": "Chennai",
                    "state": "TN", "pincode": CUSTOMER_BAD_PINCODE,
                },
            },
            timeout=15,
        )
        assert r.status_code == 400, f"expected 400 got {r.status_code}: {r.text}"
        detail = r.json().get("detail")
        assert isinstance(detail, dict), f"expected structured detail, got {detail!r}"
        assert detail.get("code") == "out_of_delivery_zone"
        assert isinstance(detail.get("conflicts"), list) and len(detail["conflicts"]) >= 1

    def test_matching_pincode_succeeds(self):
        r = requests.post(
            f"{API}/orders/checkout",
            headers=self.ch,
            json={
                "payment_method": "wallet",
                "shipping_address": {
                    "name": "Test C", "phone": "9998887777",
                    "line1": "1 Main St", "city": "Hyderabad",
                    "state": "Telangana", "pincode": VENDOR_PINCODE,
                },
            },
            timeout=15,
        )
        assert r.status_code == 200, f"expected 200 got {r.status_code}: {r.text}"
        body = r.json()
        assert body.get("order_id") or body.get("id") or body.get("ok"), body
