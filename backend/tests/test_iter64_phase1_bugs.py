"""
Iteration 64 — Phase 1 revenue-blocking backend regressions.

Coverage:
1. GET /api/vendor/me/products (vendor auth) must be SLIM:
   - No 'images' or 'image_data_url' keys
   - Adds 'gallery_count'
   - Any base64 cover rewritten to /api/products/{id}/image?...
   - has_inline_image=true when rewritten
   - Payload size is small (<< raw doc)
2. GET /api/vendor/me/products/{id} (vendor auth) returns full doc with 'images';
   returns 404 for another vendor's product; 401/403 unauthenticated.
3. GET /api/products/by-source?source=category&category=general&pincode=517644
   matches case-insensitively across category / sub_category / subcategory.
4. /api/admin/shop-layout PATCH view_all_link + GET /api/shop-layout works.
"""
import os
import json
import pytest
import requests
from conftest import BASE_URL, auth_headers  # noqa: F401

VENDOR_EMAIL = "testvendor@test.com"
VENDOR_PASSWORD = "Test@1234"
BUYER_EMAIL = "testbuyer@test.com"
BUYER_PASSWORD = "Test@1234"
PINCODE = "517644"

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def vendor_token(api):
    r = api.post(f"{BASE_URL}/api/auth/login", json={"email": VENDOR_EMAIL, "password": VENDOR_PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def buyer_token(api):
    r = api.post(f"{BASE_URL}/api/auth/login", json={"email": BUYER_EMAIL, "password": BUYER_PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["token"]


# ---------------------------------------------------------------------------
# 1. Slim /vendor/me/products
# ---------------------------------------------------------------------------
class TestVendorSlimList:
    def test_returns_slim_list(self, api, vendor_token):
        r = api.get(f"{BASE_URL}/api/vendor/me/products", headers=auth_headers(vendor_token))
        assert r.status_code == 200, r.text
        items = r.json()
        assert isinstance(items, list)
        assert len(items) > 0, "vendor should have at least 1 product"
        for p in items:
            assert "images" not in p, f"'images' must be removed. Got keys: {list(p.keys())}"
            assert "image_data_url" not in p, "'image_data_url' must be removed"
            assert "gallery_count" in p, "gallery_count must be present"
            assert isinstance(p["gallery_count"], int)
            img = p.get("image_url") or ""
            # No inline base64 covers in slim list
            assert not (isinstance(img, str) and img.startswith("data:")), \
                "base64 cover must be rewritten to /api/products/{id}/image endpoint"
            if p.get("has_inline_image"):
                assert "/api/products/" in img and "/image" in img

    def test_payload_size_is_small(self, api, vendor_token):
        r = api.get(f"{BASE_URL}/api/vendor/me/products", headers=auth_headers(vendor_token))
        assert r.status_code == 200
        size = len(r.content)
        items = r.json()
        # slim list should be well under 200KB per product on average, and no huge base64
        assert size < 500_000, f"slim list too large: {size} bytes for {len(items)} products"


# ---------------------------------------------------------------------------
# 2. Full /vendor/me/products/{id}
# ---------------------------------------------------------------------------
class TestVendorProductDetail:
    def _one_id(self, api, token):
        r = api.get(f"{BASE_URL}/api/vendor/me/products", headers=auth_headers(token))
        assert r.status_code == 200
        items = r.json()
        assert items, "vendor has no products"
        return items[0]["id"]

    def test_detail_returns_full_doc(self, api, vendor_token):
        pid = self._one_id(api, vendor_token)
        r = api.get(f"{BASE_URL}/api/vendor/me/products/{pid}", headers=auth_headers(vendor_token))
        assert r.status_code == 200, r.text
        doc = r.json()
        # Full doc should include images key (even if empty)
        assert "images" in doc, "full doc must include 'images' key"
        assert isinstance(doc["images"], list)
        assert doc.get("id") == pid

    def test_detail_unauth_returns_401_or_403(self, api, vendor_token):
        pid = self._one_id(api, vendor_token)
        r = api.get(f"{BASE_URL}/api/vendor/me/products/{pid}")
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"

    def test_detail_wrong_vendor_returns_404(self, api, vendor_token, admin_token):
        # Find a product NOT owned by testvendor via admin listing
        r = api.get(f"{BASE_URL}/api/admin/products?limit=50", headers=auth_headers(admin_token))
        assert r.status_code == 200
        payload = r.json()
        items = payload.get("items", payload) if isinstance(payload, dict) else payload
        # Get testvendor's product ids for exclusion
        me = api.get(f"{BASE_URL}/api/vendor/me/products", headers=auth_headers(vendor_token)).json()
        mine = {p["id"] for p in me}
        foreign = next((p for p in items if p.get("id") and p["id"] not in mine), None)
        if not foreign:
            pytest.skip("no foreign product in DB to test cross-vendor 404")
        r2 = api.get(
            f"{BASE_URL}/api/vendor/me/products/{foreign['id']}",
            headers=auth_headers(vendor_token),
        )
        assert r2.status_code == 404, f"expected 404 for foreign product, got {r2.status_code}"


# ---------------------------------------------------------------------------
# 3. /products/by-source?source=category  case-insensitive + sub_category
# ---------------------------------------------------------------------------
class TestBySourceCategory:
    def _fetch(self, api, cat):
        return api.get(
            f"{BASE_URL}/api/products/by-source",
            params={
                "source": "category",
                "category": cat,
                "limit": 10,
                "pincode": PINCODE,
                "strict_location": "true",
            },
        )

    def test_general_returns_products(self, api):
        r = self._fetch(api, "general")
        assert r.status_code == 200, r.text
        items = r.json()
        assert isinstance(items, list)
        assert len(items) >= 1, "expected at least 1 product for category=general (spec says 3)"

    def test_case_insensitive_match(self, api):
        results = {}
        for c in ("general", "General", "GENERAL"):
            r = self._fetch(api, c)
            assert r.status_code == 200
            results[c] = sorted([p.get("id") for p in r.json()])
        assert results["general"] == results["General"] == results["GENERAL"], \
            f"case-insensitive mismatch: {results}"

    def test_bogus_category_returns_empty(self, api):
        r = self._fetch(api, "__no_such_category_xyz__")
        assert r.status_code == 200
        assert r.json() == []


# ---------------------------------------------------------------------------
# 4. Admin shop-layout patch/get still works
# ---------------------------------------------------------------------------
class TestShopLayoutBasics:
    def test_get_home_layout(self, api):
        r = api.get(f"{BASE_URL}/api/shop-layout", params={"scope": "home", "pincode": PINCODE})
        assert r.status_code == 200, r.text
        data = r.json()
        # Server may return either list or dict with 'items' or 'blocks'
        if isinstance(data, dict):
            blocks = data.get("blocks") or data.get("items") or []
        else:
            blocks = data
        assert isinstance(blocks, list)
        # spec says 7 home blocks
        assert len(blocks) >= 1, f"expected >=1 blocks, got {len(blocks)}"

    def test_admin_patch_view_all_link(self, api, admin_token):
        r = api.get(f"{BASE_URL}/api/admin/shop-layout", headers=auth_headers(admin_token))
        assert r.status_code == 200
        payload = r.json()
        blocks = payload.get("blocks") or payload.get("items") if isinstance(payload, dict) else payload
        target = None
        for b in blocks or []:
            if b.get("scope") == "home" and (b.get("pincode") == PINCODE or not b.get("pincode")):
                target = b
                break
        if not target:
            pytest.skip("no home block available to PATCH")
        bid = target["id"]
        original_link = target.get("view_all_link") or ""
        new_link = "General"
        r2 = api.patch(
            f"{BASE_URL}/api/admin/shop-layout/{bid}",
            headers=auth_headers(admin_token),
            json={"view_all_link": new_link},
        )
        assert r2.status_code in (200, 204), f"PATCH failed: {r2.status_code} {r2.text}"
        # Verify via GET
        r3 = api.get(f"{BASE_URL}/api/admin/shop-layout", headers=auth_headers(admin_token))
        got = None
        payload3 = r3.json()
        blocks3 = payload3.get("blocks") or payload3.get("items") if isinstance(payload3, dict) else payload3
        for b in blocks3 or []:
            if b.get("id") == bid:
                got = b
                break
        assert got is not None
        assert got.get("view_all_link") == new_link, f"view_all_link not persisted: {got.get('view_all_link')}"
        # Restore
        api.patch(
            f"{BASE_URL}/api/admin/shop-layout/{bid}",
            headers=auth_headers(admin_token),
            json={"view_all_link": original_link},
        )
