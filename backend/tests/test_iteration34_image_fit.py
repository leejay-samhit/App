"""Iteration 34 — Shop-layout `image_fit` field bug-fix tests.

The bug report: banner images were being double-cropped (client fitter did a
centre-crop + renderer used cover). Fix: add `image_fit` field ('cover' |
'contain') to both LayoutBlock and LayoutItem so admin can choose per block.

This suite verifies backend persistence of that field through POST/PATCH/GET
plus regression coverage for the existing CRUD/reorder flows and the two
unrelated features that share this codebase (products/master/search,
vendor product CRUD w/ IMEI).
"""
from __future__ import annotations

import os
import uuid
import time
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

# Load env
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
_fe = Path(__file__).resolve().parents[2] / "frontend" / ".env"
if _fe.exists():
    load_dotenv(_fe, override=False)

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "support@networkrupay.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Nlee@1115")

# 1x1 red pixel JPEG, valid data URL
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
# Bug-fix tests
# ────────────────────────────────────────────────────────────

class TestImageFitBlockLevel:
    """Block-level `image_fit` field on POST/PATCH/GET."""

    created_ids: list = []

    def test_post_default_cover_when_omitted(self, api, auth):
        """Old clients that omit image_fit must still succeed AND get default 'cover'."""
        payload = {
            "block_type": "background",
            "title": "TEST_iter34_default",
            "sort_order": 9001,
            "active": True,
            "image_data_url": TINY_JPEG_DATA_URL,
            # NOTE: no image_fit sent
        }
        r = api.post(f"{BASE_URL}/api/admin/shop-layout", json=payload, headers=auth)
        assert r.status_code == 200, f"create failed: {r.status_code} {r.text}"
        body = r.json()
        assert body["block_type"] == "background"
        assert body["title"] == "TEST_iter34_default"
        assert "image_fit" in body, (
            f"BUG: image_fit missing from POST response. keys={list(body.keys())}"
        )
        assert body["image_fit"] == "cover", (
            f"BUG: image_fit default should be 'cover', got {body.get('image_fit')!r}"
        )
        TestImageFitBlockLevel.created_ids.append(body["id"])

    def test_post_with_contain(self, api, auth):
        payload = {
            "block_type": "background",
            "title": "TEST_iter34_contain",
            "sort_order": 9002,
            "active": True,
            "image_data_url": TINY_JPEG_DATA_URL,
            "image_fit": "contain",
        }
        r = api.post(f"{BASE_URL}/api/admin/shop-layout", json=payload, headers=auth)
        assert r.status_code == 200, f"create failed: {r.status_code} {r.text}"
        body = r.json()
        assert body.get("image_fit") == "contain", (
            f"BUG: image_fit not persisted on POST. Sent 'contain', got {body.get('image_fit')!r}. "
            f"Full response keys: {list(body.keys())}"
        )
        TestImageFitBlockLevel.created_ids.append(body["id"])

    def test_get_admin_returns_image_fit(self, api, auth):
        """GET /api/admin/shop-layout must include image_fit on every block."""
        r = api.get(f"{BASE_URL}/api/admin/shop-layout", headers=auth)
        assert r.status_code == 200, f"admin list failed: {r.status_code} {r.text}"
        items = r.json().get("items", [])
        # Find at least our two created blocks
        ours = [b for b in items if b["id"] in TestImageFitBlockLevel.created_ids]
        assert len(ours) >= 2, f"created blocks not found in admin listing; got {len(ours)}"
        for b in ours:
            assert "image_fit" in b, (
                f"BUG: image_fit missing from admin listing for block id={b['id']}"
            )
        # Specifically verify the 'contain' one persisted
        contain_block = next(
            (b for b in ours if b["title"] == "TEST_iter34_contain"), None
        )
        assert contain_block is not None, "contain block not returned"
        assert contain_block["image_fit"] == "contain", (
            f"BUG: contain block returns image_fit={contain_block.get('image_fit')!r} "
            "after being POSTed as 'contain' — persistence broken"
        )

    def test_get_public_active_returns_image_fit(self, api):
        """GET /api/shop-layout returns image_fit on active blocks."""
        r = api.get(f"{BASE_URL}/api/shop-layout?scope=home")
        assert r.status_code == 200, f"public list failed: {r.status_code} {r.text}"
        items = r.json().get("items", [])
        ours = [b for b in items if b["id"] in TestImageFitBlockLevel.created_ids]
        assert len(ours) >= 2, (
            f"created blocks not returned by public endpoint; got {len(ours)}"
        )
        for b in ours:
            assert "image_fit" in b, (
                f"BUG: image_fit missing from public listing for block id={b['id']}"
            )

    def test_patch_cover_to_contain_and_back(self, api, auth):
        # Create a fresh block to mutate
        payload = {
            "block_type": "background",
            "title": "TEST_iter34_patch",
            "sort_order": 9003,
            "active": True,
            "image_data_url": TINY_JPEG_DATA_URL,
            "image_fit": "cover",
        }
        r = api.post(f"{BASE_URL}/api/admin/shop-layout", json=payload, headers=auth)
        assert r.status_code == 200
        block_id = r.json()["id"]
        TestImageFitBlockLevel.created_ids.append(block_id)

        # PATCH cover → contain
        r2 = api.patch(f"{BASE_URL}/api/admin/shop-layout/{block_id}",
                       json={"image_fit": "contain"}, headers=auth)
        assert r2.status_code == 200, f"patch failed: {r2.status_code} {r2.text}"
        assert r2.json().get("image_fit") == "contain", (
            f"BUG: PATCH image_fit->contain did not persist. Got {r2.json().get('image_fit')!r}"
        )

        # PATCH contain → cover
        r3 = api.patch(f"{BASE_URL}/api/admin/shop-layout/{block_id}",
                       json={"image_fit": "cover"}, headers=auth)
        assert r3.status_code == 200
        assert r3.json().get("image_fit") == "cover", (
            f"BUG: PATCH image_fit->cover did not persist. Got {r3.json().get('image_fit')!r}"
        )

    @classmethod
    def teardown_class(cls):
        """Clean up all created blocks."""
        try:
            token_r = requests.post(f"{BASE_URL}/api/auth/login",
                                    json={"email": ADMIN_EMAIL,
                                          "password": ADMIN_PASSWORD})
            if token_r.status_code != 200:
                return
            hdr = {"Authorization": f"Bearer {token_r.json()['token']}"}
            for bid in cls.created_ids:
                requests.delete(f"{BASE_URL}/api/admin/shop-layout/{bid}", headers=hdr)
        except Exception:
            pass


class TestImageFitItemLevel:
    """LayoutItem-level `image_fit` on banner_slider items."""

    created_ids: list = []

    def test_post_banner_slider_with_item_image_fit(self, api, auth):
        payload = {
            "block_type": "banner_slider",
            "title": "TEST_iter34_slider",
            "sort_order": 9010,
            "active": True,
            "items": [
                {
                    "label": "Slide 1",
                    "image_data_url": TINY_JPEG_DATA_URL,
                    "image_fit": "contain",
                },
                {
                    "label": "Slide 2",
                    "image_data_url": TINY_JPEG_DATA_URL,
                    "image_fit": "cover",
                },
                {
                    "label": "Slide 3 no-fit",
                    "image_data_url": TINY_JPEG_DATA_URL,
                    # omit image_fit — should default to 'cover'
                },
            ],
        }
        r = api.post(f"{BASE_URL}/api/admin/shop-layout", json=payload, headers=auth)
        assert r.status_code == 200, f"slider create failed: {r.status_code} {r.text}"
        body = r.json()
        TestImageFitItemLevel.created_ids.append(body["id"])
        items = body.get("items", [])
        assert len(items) == 3, f"expected 3 items, got {len(items)}"
        assert items[0].get("image_fit") == "contain", (
            f"BUG: item[0].image_fit lost on POST. got {items[0].get('image_fit')!r}, "
            f"item keys={list(items[0].keys())}"
        )
        assert items[1].get("image_fit") == "cover", (
            f"BUG: item[1].image_fit lost on POST. got {items[1].get('image_fit')!r}"
        )
        assert items[2].get("image_fit") == "cover", (
            f"BUG: default image_fit on item[2] should be 'cover'. "
            f"got {items[2].get('image_fit')!r}"
        )

    def test_get_admin_returns_item_image_fit(self, api, auth):
        assert TestImageFitItemLevel.created_ids, "prerequisite create failed"
        block_id = TestImageFitItemLevel.created_ids[0]
        r = api.get(f"{BASE_URL}/api/admin/shop-layout", headers=auth)
        assert r.status_code == 200
        block = next((b for b in r.json().get("items", []) if b["id"] == block_id), None)
        assert block is not None, "slider not found in admin listing"
        items = block.get("items", [])
        assert len(items) == 3
        # Verify the persisted image_fit round-trips through the DB
        fits = [it.get("image_fit") for it in items]
        assert fits[0] == "contain", (
            f"BUG: item[0] image_fit not persisted through GET. fits={fits}"
        )
        assert fits[1] == "cover", (
            f"BUG: item[1] image_fit not persisted through GET. fits={fits}"
        )
        # Also verify image_data_url present alongside image_fit
        for it in items:
            assert it.get("image_data_url"), "image_data_url lost"

    def test_patch_items_preserves_image_fit(self, api, auth):
        """Regression: PATCH-ing items[] should preserve image_fit."""
        assert TestImageFitItemLevel.created_ids, "prerequisite create failed"
        block_id = TestImageFitItemLevel.created_ids[0]
        new_items = [
            {
                "label": "Slide A patched",
                "image_data_url": TINY_JPEG_DATA_URL,
                "image_fit": "contain",
            },
            {
                "label": "Slide B patched",
                "image_data_url": TINY_JPEG_DATA_URL,
                "image_fit": "cover",
            },
        ]
        r = api.patch(f"{BASE_URL}/api/admin/shop-layout/{block_id}",
                      json={"items": new_items}, headers=auth)
        assert r.status_code == 200, f"patch failed: {r.status_code} {r.text}"
        got_items = r.json().get("items", [])
        assert len(got_items) == 2
        assert got_items[0].get("image_fit") == "contain", (
            f"BUG: PATCH items[] dropped image_fit. Got {got_items[0].get('image_fit')!r}. "
            f"Full item: {got_items[0]}"
        )
        assert got_items[1].get("image_fit") == "cover", (
            f"BUG: PATCH items[] dropped image_fit for cover. Got {got_items[1]!r}"
        )

    @classmethod
    def teardown_class(cls):
        try:
            token_r = requests.post(f"{BASE_URL}/api/auth/login",
                                    json={"email": ADMIN_EMAIL,
                                          "password": ADMIN_PASSWORD})
            if token_r.status_code != 200:
                return
            hdr = {"Authorization": f"Bearer {token_r.json()['token']}"}
            for bid in cls.created_ids:
                requests.delete(f"{BASE_URL}/api/admin/shop-layout/{bid}", headers=hdr)
        except Exception:
            pass


# ────────────────────────────────────────────────────────────
# Regression coverage
# ────────────────────────────────────────────────────────────

class TestShopLayoutRegression:
    """Existing CRUD + reorder flows still work."""

    def test_create_patch_reorder_delete(self, api, auth):
        # Create A
        rA = api.post(f"{BASE_URL}/api/admin/shop-layout",
                      json={"block_type": "text",
                            "title": "TEST_iter34_regA",
                            "sort_order": 9500},
                      headers=auth)
        assert rA.status_code == 200
        idA = rA.json()["id"]

        # Create B
        rB = api.post(f"{BASE_URL}/api/admin/shop-layout",
                      json={"block_type": "text",
                            "title": "TEST_iter34_regB",
                            "sort_order": 9501},
                      headers=auth)
        assert rB.status_code == 200
        idB = rB.json()["id"]

        try:
            # Patch title on A
            rp = api.patch(f"{BASE_URL}/api/admin/shop-layout/{idA}",
                           json={"title": "TEST_iter34_regA_patched"},
                           headers=auth)
            assert rp.status_code == 200
            assert rp.json()["title"] == "TEST_iter34_regA_patched"

            # Reorder — swap
            rr = api.post(f"{BASE_URL}/api/admin/shop-layout/reorder",
                          json={"items": [
                              {"id": idA, "sort_order": 9501},
                              {"id": idB, "sort_order": 9500},
                          ]}, headers=auth)
            assert rr.status_code == 200
            assert rr.json().get("updated") == 2

            # Verify GET reflects new order
            rg = api.get(f"{BASE_URL}/api/admin/shop-layout", headers=auth)
            assert rg.status_code == 200
            items = {i["id"]: i for i in rg.json()["items"]}
            assert items[idA]["sort_order"] == 9501
            assert items[idB]["sort_order"] == 9500
        finally:
            api.delete(f"{BASE_URL}/api/admin/shop-layout/{idA}", headers=auth)
            api.delete(f"{BASE_URL}/api/admin/shop-layout/{idB}", headers=auth)

    def test_delete_returns_404_after(self, api, auth):
        r = api.post(f"{BASE_URL}/api/admin/shop-layout",
                     json={"block_type": "text",
                           "title": "TEST_iter34_delme",
                           "sort_order": 9600},
                     headers=auth)
        assert r.status_code == 200
        bid = r.json()["id"]
        rd = api.delete(f"{BASE_URL}/api/admin/shop-layout/{bid}", headers=auth)
        assert rd.status_code == 200
        rd2 = api.delete(f"{BASE_URL}/api/admin/shop-layout/{bid}", headers=auth)
        assert rd2.status_code == 404


class TestProductsMasterSearchRegression:
    """Cross-source search still returns 200 with local + 91mobiles + deodap."""

    def test_master_search_returns_200(self, api, auth):
        r = api.get(
            f"{BASE_URL}/api/products/master/search",
            params={"q": "headphone"},
            headers=auth,
        )
        assert r.status_code == 200, f"master search failed: {r.status_code} {r.text}"
        body = r.json()
        # Required fields still present
        for key in ("items", "count", "local_hits"):
            assert key in body, f"master search response missing key {key!r}"
        # Sources may vary but iteration 33 baseline had m91_hits & deodap_hits
        assert "m91_hits" in body or "deodap_hits" in body, (
            "master search should still expose external hit counts"
        )


class TestVendorProductImeiRegression:
    """Vendor product CRUD with serial_number/imei_1/imei_2 still works."""

    def test_vendor_can_create_product_with_imei(self, api):
        # Login as Alice (from test_credentials.md)
        r = api.post(f"{BASE_URL}/api/auth/login",
                     json={"email": "test_alice_73dc7f@test.com",
                           "password": "Passw0rd!"})
        if r.status_code != 200:
            pytest.skip(f"vendor login failed: {r.status_code} {r.text}")
        token = r.json()["token"]
        hdr = {"Authorization": f"Bearer {token}",
               "Content-Type": "application/json"}
        payload = {
            "name": f"TEST_iter34_imei_{uuid.uuid4().hex[:6]}",
            "price": 999.0,
            "stock": 1,
            "serial_number": "SN-ITER34",
            "imei_1": "111111111111111",
            "imei_2": "222222222222222",
        }
        rc = api.post(f"{BASE_URL}/api/vendor/me/products",
                      json=payload, headers=hdr)
        if rc.status_code == 404:
            pytest.skip("vendor product create endpoint not present in this build")
        assert rc.status_code in (200, 201), f"create failed: {rc.status_code} {rc.text}"
        pid = rc.json().get("id")
        try:
            # Verify via GET
            rg = api.get(f"{BASE_URL}/api/vendor/me/products", headers=hdr)
            assert rg.status_code == 200
            items = rg.json().get("items") or rg.json()
            if isinstance(items, dict):
                items = items.get("items", [])
            found = next((p for p in items if p.get("id") == pid), None)
            assert found is not None, "created product not found in vendor list"
            assert found.get("serial_number") == "SN-ITER34"
            assert found.get("imei_1") == "111111111111111"
            assert found.get("imei_2") == "222222222222222"
        finally:
            if pid:
                api.delete(f"{BASE_URL}/api/vendor/me/products/{pid}", headers=hdr)
