"""Iteration 51 — Location-first Shop + Admin vendor filters + pincode-scoped shop layout.

Covers the review_request:
  1. GET /products?strict_location=true (with/without pincode / lat-lng)
  2. GET /products/by-source with location filter
  3. GET /admin/products — vendor_name enrichment + vendor_id/vendor_q filters
  4. GET /admin/vendors + ?q=kittu narrowing (returns {items:[{id,name,email,store_pincode}...]})
  5. GET /shop-layout — pincode-scoped block visibility
  6. Regression: /api/auth/login for admin + user + vendor
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL missing"
BASE_URL = BASE_URL.rstrip("/")

ADMIN_EMAIL = "support@slangcart.com"
ADMIN_PASS = "3)Ywxtic"
USER_EMAIL = "leejay@gmail.com"
USER_PASS = "Just@4me"
VENDOR_EMAIL = "brightkittu@slangcart.com"
VENDOR_PASS = "Just@4me"
KITTU_VENDOR_ID = "283753d8-0838-4a94-9158-ddfe464acdba"

KITTU_PRODUCT_NAMES = {"Kittu Handmade Saree", "Kittu Silk Kurta", "Kittu Village Ghee 500g"}


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def s():
    return requests.Session()


def _login(s, email, password):
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=20)
    return r


@pytest.fixture(scope="module")
def admin_token(s):
    r = _login(s, ADMIN_EMAIL, ADMIN_PASS)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text[:200]}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ---------- Regression: Auth ----------
class TestAuthRegression:
    def test_admin_login(self, s):
        r = _login(s, ADMIN_EMAIL, ADMIN_PASS)
        assert r.status_code == 200
        data = r.json()
        assert "token" in data and "user" in data
        assert data["user"].get("email") == ADMIN_EMAIL

    def test_user_login(self, s):
        r = _login(s, USER_EMAIL, USER_PASS)
        assert r.status_code == 200, r.text[:200]
        assert "token" in r.json() and "user" in r.json()

    def test_vendor_login(self, s):
        r = _login(s, VENDOR_EMAIL, VENDOR_PASS)
        assert r.status_code == 200, r.text[:200]
        assert "token" in r.json() and "user" in r.json()


# ---------- Products — strict_location behaviour ----------
class TestProductsLocationFirst:
    def test_strict_no_location_returns_empty(self, s):
        r = s.get(f"{BASE_URL}/api/products?strict_location=true", timeout=20)
        assert r.status_code == 200
        data = r.json()
        # Endpoint returns dict when strict_location paginated shape is triggered
        assert isinstance(data, dict), f"Expected dict envelope, got {type(data)}"
        assert data.get("items") == []
        assert data.get("total") == 0

    def test_pincode_517644_returns_only_kittu(self, s):
        r = s.get(f"{BASE_URL}/api/products?pincode=517644&strict_location=true", timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)
        items = data.get("items", [])
        assert data.get("total") == 3, f"expected 3, got {data.get('total')}: {[p.get('name') for p in items]}"
        names = {p.get("name") for p in items}
        assert names == KITTU_PRODUCT_NAMES, f"unexpected products: {names}"
        # ALL products must belong to kittu vendor
        for p in items:
            assert p.get("vendor_id") == KITTU_VENDOR_ID, f"leaked product: {p.get('name')} vendor={p.get('vendor_id')}"

    def test_pincode_516002_returns_empty(self, s):
        r = s.get(f"{BASE_URL}/api/products?pincode=516002&strict_location=true", timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert data.get("total") == 0, f"Cuddapah should have 0 products, got {data.get('total')}"
        assert data.get("items") == []

    def test_latlng_within_radius_returns_kittu(self, s):
        # Kittu store lat/lng — customer standing right at the store
        r = s.get(
            f"{BASE_URL}/api/products?lat=13.7484&lng=79.7027&strict_location=true",
            timeout=20,
        )
        assert r.status_code == 200
        data = r.json()
        items = data.get("items", [])
        assert data.get("total") == 3, f"expected 3 kittu products, got {data.get('total')}"
        names = {p.get("name") for p in items}
        assert names == KITTU_PRODUCT_NAMES

    def test_latlng_out_of_radius_returns_empty(self, s):
        # Kadapa ≈ 120 km from Srikalahasti
        r = s.get(
            f"{BASE_URL}/api/products?lat=14.4674&lng=78.8241&strict_location=true",
            timeout=20,
        )
        assert r.status_code == 200
        data = r.json()
        assert data.get("total") == 0, f"expected 0, got {data.get('total')}"


# ---------- Products by-source ----------
class TestProductsBySource:
    def test_by_source_trending_pincode_scoped(self, s):
        r = s.get(
            f"{BASE_URL}/api/products/by-source?source=trending&pincode=517644&strict_location=true",
            timeout=20,
        )
        assert r.status_code == 200
        items = r.json()
        assert isinstance(items, list)
        # All items must be kittu vendor's
        for p in items:
            assert p.get("vendor_id") == KITTU_VENDOR_ID
        names = {p.get("name") for p in items}
        assert names.issubset(KITTU_PRODUCT_NAMES)

    def test_by_source_no_location_backcompat(self, s):
        r = s.get(f"{BASE_URL}/api/products/by-source?source=trending", timeout=20)
        assert r.status_code == 200
        items = r.json()
        assert isinstance(items, list)  # global catalogue works

    def test_by_source_kadapa_empty(self, s):
        r = s.get(
            f"{BASE_URL}/api/products/by-source?source=trending&pincode=516002&strict_location=true",
            timeout=20,
        )
        assert r.status_code == 200
        assert r.json() == []


# ---------- Admin products enrichment + filters ----------
class TestAdminProducts:
    def test_admin_products_have_vendor_name(self, s, admin_headers):
        r = s.get(f"{BASE_URL}/api/admin/products", headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text[:200]
        data = r.json()
        assert isinstance(data, list)
        # find kittu products
        kittu_ps = [p for p in data if p.get("vendor_id") == KITTU_VENDOR_ID]
        assert len(kittu_ps) == 3, f"kittu products count in admin list = {len(kittu_ps)}"
        for p in kittu_ps:
            assert p.get("vendor_name"), f"vendor_name missing on {p.get('name')}"
            # Business name may vary — accept anything Kittu / Bright Kittu
            vn = (p.get("vendor_name") or "").lower()
            assert "kittu" in vn or "bright" in vn, f"unexpected vendor_name: {p.get('vendor_name')}"
        # legacy products (no vendor_id) should say "Admin catalog"
        legacy = [p for p in data if not p.get("vendor_id")]
        for p in legacy:
            assert p.get("vendor_name") == "Admin catalog"

    def test_admin_products_filter_by_vendor_id(self, s, admin_headers):
        r = s.get(
            f"{BASE_URL}/api/admin/products?vendor_id={KITTU_VENDOR_ID}",
            headers=admin_headers, timeout=20,
        )
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) == 3
        names = {p.get("name") for p in data}
        assert names == KITTU_PRODUCT_NAMES

    def test_admin_products_filter_by_vendor_q(self, s, admin_headers):
        r = s.get(f"{BASE_URL}/api/admin/products?vendor_q=kittu", headers=admin_headers, timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) == 3
        names = {p.get("name") for p in data}
        assert names == KITTU_PRODUCT_NAMES


# ---------- Admin vendors picker ----------
class TestAdminVendors:
    def test_admin_vendors_shape(self, s, admin_headers):
        r = s.get(f"{BASE_URL}/api/admin/vendors", headers=admin_headers, timeout=20)
        assert r.status_code == 200, r.text[:200]
        data = r.json()
        assert isinstance(data, dict), f"Expected dict envelope, got {type(data)}: {str(data)[:200]}"
        assert "items" in data
        items = data["items"]
        assert isinstance(items, list)
        # locate kittu
        kittu = next((v for v in items if v.get("email") == VENDOR_EMAIL), None)
        assert kittu is not None, f"kittu vendor missing. sample: {items[:2]}"
        assert "id" in kittu and "name" in kittu and "email" in kittu and "store_pincode" in kittu, kittu
        assert kittu.get("store_pincode") == "517644"

    def test_admin_vendors_query_narrow(self, s, admin_headers):
        r = s.get(f"{BASE_URL}/api/admin/vendors?q=kittu", headers=admin_headers, timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict) and "items" in data
        items = data["items"]
        assert len(items) >= 1
        for v in items:
            hay = ((v.get("name") or "") + " " + (v.get("email") or "")).lower()
            assert "kittu" in hay


# ---------- Shop Layout pincode scope ----------
@pytest.fixture(scope="module")
def scoped_block_id(s, admin_headers):
    """Create a scope_pincode=517644 test block. Cleaned up in test_zzz_cleanup."""
    body = {
        "block_type": "section_header",
        "scope": "home",
        "scope_pincode": "517644",
        "title": "TEST_ITER51_SCOPED_517644",
        "sort_order": 999,
        "active": True,
    }
    r = s.post(f"{BASE_URL}/api/admin/shop-layout", json=body, headers=admin_headers, timeout=20)
    assert r.status_code == 200, r.text[:200]
    doc = r.json()
    yield doc["id"]
    # teardown
    s.delete(f"{BASE_URL}/api/admin/shop-layout/{doc['id']}", headers=admin_headers, timeout=20)


class TestShopLayoutPincodeScope:
    def test_public_layout_no_pincode_excludes_scoped(self, s, scoped_block_id):
        r = s.get(f"{BASE_URL}/api/shop-layout", timeout=20)
        assert r.status_code == 200
        items = r.json().get("items", [])
        ids = {b["id"] for b in items}
        assert scoped_block_id not in ids, "scope_pincode=517644 block leaked to no-pincode request"

    def test_public_layout_mismatched_pincode_excludes_scoped(self, s, scoped_block_id):
        r = s.get(f"{BASE_URL}/api/shop-layout?pincode=516002", timeout=20)
        assert r.status_code == 200
        items = r.json().get("items", [])
        ids = {b["id"] for b in items}
        assert scoped_block_id not in ids, "scope_pincode=517644 block leaked to 516002 request"

    def test_public_layout_matching_pincode_includes_scoped(self, s, scoped_block_id):
        r = s.get(f"{BASE_URL}/api/shop-layout?pincode=517644", timeout=20)
        assert r.status_code == 200
        items = r.json().get("items", [])
        ids = {b["id"] for b in items}
        assert scoped_block_id in ids, "matching-pincode request MUST include scope_pincode=517644 block"
        # also verify globals still visible (any block whose scope_pincode is empty)
        has_global = any((b.get("scope_pincode") or "") == "" for b in items)
        assert has_global, "expected at least one global block alongside scoped"

    def test_admin_layout_sees_everything(self, s, admin_headers, scoped_block_id):
        r = s.get(f"{BASE_URL}/api/admin/shop-layout", headers=admin_headers, timeout=20)
        assert r.status_code == 200
        items = r.json().get("items", [])
        ids = {b["id"] for b in items}
        assert scoped_block_id in ids, "admin_view=True should list scope_pincode blocks"
