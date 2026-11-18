"""Iteration 36 — Shop Layout live-update backend verification.

Frontend change: ShopLayoutRenderer now accepts a `refreshTick` prop, auto-polls
every 30s while AppState is 'active', and parent shop screens bump the tick on
pull-to-refresh. The backend contract this depends on:

  1. GET /api/shop-layout             — returns active blocks (scope=home default)
  2. GET /api/shop-layout?scope=category&category=<name>
                                       — respects the category query param
  3. Fresh data (no server-side caching): POST/PATCH → next GET reflects change
     IMMEDIATELY (within same request cycle).
  4. PATCH active=false                — subsequent GET excludes the block
  5. GET /api/products                 — used by shop home + category fallback
  6. GET /api/products/by-source       — regression from iter 34/35
  7. Shop-layout CRUD/reorder          — regression
  8. Vendor product IMEI               — regression
  9. Products master search            — regression

NOTE: The review spec mentions `/api/shop-layout/blocks/active` but the actual
backend endpoint is `/api/shop-layout` (returns active blocks by default). The
frontend renderer calls `/shop-layout` via api client (see
frontend/src/shop-layout-renderer.tsx:732). We test the real endpoint.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
_fe = Path(__file__).resolve().parents[2] / "frontend" / ".env"
if _fe.exists():
    load_dotenv(_fe, override=False)

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "support@networkrupay.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", os.environ.get("ADMIN_PASSWORD", ""))

TINY_JPEG_DATA_URL = (
    "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsL"
    "DBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwh"
    "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIA"
    "AhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQID"
    "AAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpT"
    "VFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXG"
    "x8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD3+iiigD//2Q=="
)


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin_token(api):
    r = api.post(f"{BASE_URL}/api/auth/login",
                 json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}",
            "Content-Type": "application/json"}


# ────────────────────────────────────────────────────────────
# 1-2. Public GET /api/shop-layout endpoint
# ────────────────────────────────────────────────────────────

class TestShopLayoutPublicEndpoint:

    def test_get_active_home_returns_200(self, api):
        r = api.get(f"{BASE_URL}/api/shop-layout")
        assert r.status_code == 200, f"got {r.status_code}: {r.text}"
        body = r.json()
        assert "items" in body, f"missing 'items' key. keys={list(body.keys())}"
        assert isinstance(body["items"], list)
        assert body.get("scope") == "home"

    def test_get_active_home_only_returns_active(self, api):
        r = api.get(f"{BASE_URL}/api/shop-layout?scope=home")
        assert r.status_code == 200
        items = r.json().get("items", [])
        # Every item returned must have active=True
        for it in items:
            assert it.get("active") is True, (
                f"public endpoint returned inactive block {it.get('id')}"
            )

    def test_get_category_scope_respects_category_param(self, api, auth):
        """POST a category-scoped block for a unique category, then GET
        with ?scope=category&category=<name> must return it AND not return
        blocks scoped to other categories."""
        unique_cat = f"TEST_iter36_cat_{uuid.uuid4().hex[:6]}"
        other_cat = f"TEST_iter36_other_{uuid.uuid4().hex[:6]}"

        r1 = api.post(f"{BASE_URL}/api/admin/shop-layout", json={
            "block_type": "section_header",
            "scope": "category",
            "scope_category": unique_cat,
            "title": "TEST_iter36_cat_block",
            "sort_order": 8100,
            "active": True,
        }, headers=auth)
        assert r1.status_code == 200, f"create failed: {r1.status_code} {r1.text}"
        id1 = r1.json()["id"]

        r2 = api.post(f"{BASE_URL}/api/admin/shop-layout", json={
            "block_type": "section_header",
            "scope": "category",
            "scope_category": other_cat,
            "title": "TEST_iter36_other_block",
            "sort_order": 8101,
            "active": True,
        }, headers=auth)
        assert r2.status_code == 200
        id2 = r2.json()["id"]

        try:
            rg = api.get(
                f"{BASE_URL}/api/shop-layout",
                params={"scope": "category", "category": unique_cat},
            )
            assert rg.status_code == 200
            body = rg.json()
            assert body.get("scope") == "category"
            assert body.get("category") == unique_cat
            ids = {b["id"] for b in body.get("items", [])}
            assert id1 in ids, (
                f"category-scoped block {id1} not returned when filtering "
                f"category={unique_cat!r}. got ids={ids}"
            )
            assert id2 not in ids, (
                f"leak: block {id2} scoped to {other_cat!r} was returned "
                f"when filtering by {unique_cat!r}"
            )
        finally:
            api.delete(f"{BASE_URL}/api/admin/shop-layout/{id1}", headers=auth)
            api.delete(f"{BASE_URL}/api/admin/shop-layout/{id2}", headers=auth)


# ────────────────────────────────────────────────────────────
# 3-4. No server-side caching — fresh data after mutation
# ────────────────────────────────────────────────────────────

class TestShopLayoutLiveConsistency:
    """The critical contract for the frontend refreshTick / auto-poll fix:
    admin mutations must be visible on the very NEXT GET, with no server-side
    cache TTL. Simulates the 30-second auto-poll behaviour."""

    def test_new_block_appears_immediately_after_post(self, api, auth):
        marker = f"TEST_iter36_live_{uuid.uuid4().hex[:8]}"
        r = api.post(f"{BASE_URL}/api/admin/shop-layout", json={
            "block_type": "section_header",
            "title": marker,
            "sort_order": 8200,
            "active": True,
        }, headers=auth)
        assert r.status_code == 200, f"create failed: {r.status_code} {r.text}"
        bid = r.json()["id"]

        try:
            # NO sleep — immediate GET must reflect the write
            rg = api.get(f"{BASE_URL}/api/shop-layout?scope=home")
            assert rg.status_code == 200
            items = rg.json().get("items", [])
            found = next((b for b in items if b["id"] == bid), None)
            assert found is not None, (
                f"BUG: new block {bid} not visible on immediate GET after POST. "
                f"Server appears to have stale cache. total_items={len(items)}"
            )
            assert found["title"] == marker
        finally:
            api.delete(f"{BASE_URL}/api/admin/shop-layout/{bid}", headers=auth)

    def test_patch_toggle_active_false_excludes_immediately(self, api, auth):
        """PATCH active=false → next GET /api/shop-layout must exclude the block."""
        marker = f"TEST_iter36_toggle_{uuid.uuid4().hex[:8]}"
        r = api.post(f"{BASE_URL}/api/admin/shop-layout", json={
            "block_type": "section_header",
            "title": marker,
            "sort_order": 8300,
            "active": True,
        }, headers=auth)
        assert r.status_code == 200
        bid = r.json()["id"]

        try:
            # First confirm it is visible
            rg1 = api.get(f"{BASE_URL}/api/shop-layout?scope=home")
            assert rg1.status_code == 200
            ids_before = {b["id"] for b in rg1.json().get("items", [])}
            assert bid in ids_before, (
                f"prerequisite failed: block {bid} not visible while active=True"
            )

            # Toggle active=False
            rp = api.patch(
                f"{BASE_URL}/api/admin/shop-layout/{bid}",
                json={"active": False}, headers=auth,
            )
            assert rp.status_code == 200
            assert rp.json().get("active") is False, (
                f"PATCH did not persist active=false. got {rp.json().get('active')!r}"
            )

            # Immediate re-GET must exclude
            rg2 = api.get(f"{BASE_URL}/api/shop-layout?scope=home")
            assert rg2.status_code == 200
            ids_after = {b["id"] for b in rg2.json().get("items", [])}
            assert bid not in ids_after, (
                f"BUG: block {bid} still returned by public /shop-layout after "
                f"PATCH active=false. Stale cache suspected. "
                f"ids_after has {len(ids_after)} items."
            )

            # Toggle back active=True — must reappear immediately
            rp2 = api.patch(
                f"{BASE_URL}/api/admin/shop-layout/{bid}",
                json={"active": True}, headers=auth,
            )
            assert rp2.status_code == 200
            rg3 = api.get(f"{BASE_URL}/api/shop-layout?scope=home")
            ids_final = {b["id"] for b in rg3.json().get("items", [])}
            assert bid in ids_final, (
                f"BUG: toggle back to active=true did not reappear on next GET"
            )
        finally:
            api.delete(f"{BASE_URL}/api/admin/shop-layout/{bid}", headers=auth)

    def test_patch_title_reflects_immediately(self, api, auth):
        original = f"TEST_iter36_titleA_{uuid.uuid4().hex[:6]}"
        updated = f"TEST_iter36_titleB_{uuid.uuid4().hex[:6]}"
        r = api.post(f"{BASE_URL}/api/admin/shop-layout", json={
            "block_type": "section_header",
            "title": original,
            "sort_order": 8400,
            "active": True,
        }, headers=auth)
        assert r.status_code == 200
        bid = r.json()["id"]
        try:
            api.patch(f"{BASE_URL}/api/admin/shop-layout/{bid}",
                      json={"title": updated}, headers=auth)
            rg = api.get(f"{BASE_URL}/api/shop-layout?scope=home")
            found = next((b for b in rg.json().get("items", []) if b["id"] == bid), None)
            assert found is not None
            assert found["title"] == updated, (
                f"BUG: title update not reflected. got {found['title']!r}, "
                f"expected {updated!r}"
            )
        finally:
            api.delete(f"{BASE_URL}/api/admin/shop-layout/{bid}", headers=auth)


# ────────────────────────────────────────────────────────────
# 5-6. Products endpoints used by ShopHome + category fallback grid
# ────────────────────────────────────────────────────────────

class TestProductsEndpoints:

    def test_get_products_returns_200(self, api):
        r = api.get(f"{BASE_URL}/api/products")
        assert r.status_code == 200, f"got {r.status_code}: {r.text}"
        body = r.json()
        # /products returns a flat array
        assert isinstance(body, list), f"expected list, got {type(body).__name__}"
        # If any products, verify shape
        if body:
            p = body[0]
            assert "id" in p
            assert "_id" not in p, "MongoDB _id leaked in /api/products response"

    def test_products_by_source_all_limit_20(self, api):
        """The frontend calls with source=all&limit=20. Backend normalises
        unknown source to 'trending' — must still return 200."""
        r = api.get(f"{BASE_URL}/api/products/by-source",
                    params={"source": "all", "limit": 20})
        assert r.status_code == 200, f"got {r.status_code}: {r.text}"
        body = r.json()
        assert isinstance(body, list)
        assert len(body) <= 20, f"limit not respected, got {len(body)} items"

    def test_products_by_source_trending(self, api):
        r = api.get(f"{BASE_URL}/api/products/by-source",
                    params={"source": "trending", "limit": 10})
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ────────────────────────────────────────────────────────────
# 7. Regression: shop-layout CRUD/reorder still works
# ────────────────────────────────────────────────────────────

class TestShopLayoutCrudRegression:

    def test_create_patch_reorder_delete(self, api, auth):
        rA = api.post(f"{BASE_URL}/api/admin/shop-layout",
                      json={"block_type": "text",
                            "title": "TEST_iter36_regA",
                            "sort_order": 8500}, headers=auth)
        assert rA.status_code == 200
        idA = rA.json()["id"]
        rB = api.post(f"{BASE_URL}/api/admin/shop-layout",
                      json={"block_type": "text",
                            "title": "TEST_iter36_regB",
                            "sort_order": 8501}, headers=auth)
        assert rB.status_code == 200
        idB = rB.json()["id"]
        try:
            rp = api.patch(f"{BASE_URL}/api/admin/shop-layout/{idA}",
                           json={"title": "TEST_iter36_regA_patched"},
                           headers=auth)
            assert rp.status_code == 200
            assert rp.json()["title"] == "TEST_iter36_regA_patched"

            rr = api.post(f"{BASE_URL}/api/admin/shop-layout/reorder",
                          json={"items": [
                              {"id": idA, "sort_order": 8501},
                              {"id": idB, "sort_order": 8500},
                          ]}, headers=auth)
            assert rr.status_code == 200
            assert rr.json().get("updated") == 2

            rg = api.get(f"{BASE_URL}/api/admin/shop-layout", headers=auth)
            assert rg.status_code == 200
            items = {i["id"]: i for i in rg.json()["items"]}
            assert items[idA]["sort_order"] == 8501
            assert items[idB]["sort_order"] == 8500
        finally:
            api.delete(f"{BASE_URL}/api/admin/shop-layout/{idA}", headers=auth)
            api.delete(f"{BASE_URL}/api/admin/shop-layout/{idB}", headers=auth)

    def test_image_fit_still_persists(self, api, auth):
        """Guard against regression on iter 34/35 fix."""
        r = api.post(f"{BASE_URL}/api/admin/shop-layout", json={
            "block_type": "background",
            "title": "TEST_iter36_fit",
            "sort_order": 8600,
            "active": True,
            "image_data_url": TINY_JPEG_DATA_URL,
            "image_fit": "contain",
        }, headers=auth)
        assert r.status_code == 200
        bid = r.json()["id"]
        try:
            assert r.json()["image_fit"] == "contain"
            rg = api.get(f"{BASE_URL}/api/shop-layout?scope=home")
            found = next((b for b in rg.json().get("items", []) if b["id"] == bid), None)
            assert found is not None
            assert found.get("image_fit") == "contain"
        finally:
            api.delete(f"{BASE_URL}/api/admin/shop-layout/{bid}", headers=auth)


# ────────────────────────────────────────────────────────────
# 8. Regression: vendor product CRUD w/ IMEI (iter 33)
# ────────────────────────────────────────────────────────────

class TestVendorImeiRegression:

    def test_vendor_can_create_product_with_imei(self, api):
        r = api.post(f"{BASE_URL}/api/auth/login",
                     json={"email": "test_alice_73dc7f@test.com",
                           "password": "Passw0rd!"})
        if r.status_code != 200:
            pytest.skip(f"vendor login failed: {r.status_code}")
        token = r.json()["token"]
        hdr = {"Authorization": f"Bearer {token}",
               "Content-Type": "application/json"}
        payload = {
            "name": f"TEST_iter36_imei_{uuid.uuid4().hex[:6]}",
            "price": 999.0,
            "stock": 1,
            "image_url": "https://placehold.co/300x300",
            "serial_number": "SN-ITER36",
            "imei_1": "111111111111111",
            "imei_2": "222222222222222",
        }
        rc = api.post(f"{BASE_URL}/api/vendor/me/products",
                      json=payload, headers=hdr)
        if rc.status_code == 404:
            pytest.skip("vendor endpoint not present")
        assert rc.status_code in (200, 201), f"{rc.status_code} {rc.text}"
        pid = rc.json().get("id")
        try:
            rg = api.get(f"{BASE_URL}/api/vendor/me/products", headers=hdr)
            assert rg.status_code == 200
            body = rg.json()
            items = body if isinstance(body, list) else body.get("items", [])
            found = next((p for p in items if p.get("id") == pid), None)
            assert found is not None
            assert found.get("serial_number") == "SN-ITER36"
            assert found.get("imei_1") == "111111111111111"
            assert found.get("imei_2") == "222222222222222"
        finally:
            if pid:
                api.delete(f"{BASE_URL}/api/vendor/me/products/{pid}", headers=hdr)


# ────────────────────────────────────────────────────────────
# 9. Regression: products/master/search
# ────────────────────────────────────────────────────────────

class TestMasterSearchRegression:

    def test_master_search_returns_200(self, api, auth):
        r = api.get(f"{BASE_URL}/api/products/master/search",
                    params={"q": "iphone"}, headers=auth)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        for key in ("items", "count", "local_hits"):
            assert key in body, f"missing key {key!r}"
        assert "m91_hits" in body or "deodap_hits" in body
