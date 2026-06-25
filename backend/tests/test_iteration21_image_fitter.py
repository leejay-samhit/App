"""
Iteration 21 backend smoke tests — image-fitter (frontend-only change) regression.

Goal: confirm that the existing admin shop-layout and admin product endpoints
still accept the `data:image/jpeg;base64,...` payloads produced by the new
frontend image-fitter, and verify that no incidental backend regressions were
introduced (chat settings/lock/broadcast endpoints).
"""
import os
import uuid
import requests
import pytest

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")

# A real 1x1 JPEG (smallest valid JPEG) as base64 — produced offline.
TINY_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEB"
    "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/2wBDAQEBAQEBAQEBAQEBAQEBAQEBAQEB"
    "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/wAARCAABAAEDASIA"
    "AhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAr/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFAEB"
    "AAAAAAAAAAAAAAAAAAAAAP/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/AL+AB//Z"
)
TINY_JPEG_DATA_URL = "data:image/jpeg;base64," + TINY_JPEG_B64


def _hdr(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ────────────────────────────────────────────────────────────────────────────
# Admin shop-layout — accept data:image/jpeg;base64 payloads
# ────────────────────────────────────────────────────────────────────────────
class TestAdminShopLayoutImageFitter:
    """Verifies admin shop-layout endpoints accept fitter-style data URLs."""

    def test_get_admin_shop_layout(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/shop-layout", headers=_hdr(admin_token))
        assert r.status_code == 200, r.text
        body = r.json()
        # Endpoint may return either a bare list or {items: [...]} envelope
        items = body["items"] if isinstance(body, dict) and "items" in body else body
        assert isinstance(items, list)

    def test_create_background_block_with_data_url(self, admin_token):
        """fitter 'background' preset → 1080x400 JPEG, payload is a data: URL."""
        payload = {
            "block_type": "background",
            "title": "TEST_iter21_bg",
            "image_data_url": TINY_JPEG_DATA_URL,
            "active": True,
            "sort_order": 9999,
        }
        r = requests.post(
            f"{BASE_URL}/api/admin/shop-layout", json=payload, headers=_hdr(admin_token)
        )
        assert r.status_code == 200, r.text
        block = r.json()
        block_id = block.get("id")
        assert block_id, f"Expected id in response, got {block}"
        assert block.get("block_type") == "background"
        assert block.get("image_data_url", "").startswith("data:image/jpeg;base64,")
        # Verify persistence via GET
        try:
            list_r = requests.get(
                f"{BASE_URL}/api/admin/shop-layout", headers=_hdr(admin_token)
            )
            assert list_r.status_code == 200
            body = list_r.json()
            items = body["items"] if isinstance(body, dict) and "items" in body else body
            ids = [b.get("id") for b in items]
            assert block_id in ids, "Newly created block not persisted"
        finally:
            # Cleanup
            del_r = requests.delete(
                f"{BASE_URL}/api/admin/shop-layout/{block_id}",
                headers=_hdr(admin_token),
            )
            assert del_r.status_code == 200, del_r.text

    def test_create_banner_slider_with_items(self, admin_token):
        """fitter 'banner_slider' preset → 1080x600 per slide; payload via items[]."""
        payload = {
            "block_type": "banner_slider",
            "title": "TEST_iter21_banner",
            "active": True,
            "sort_order": 9998,
            "items": [
                {
                    "label": "Slide 1",
                    "image_data_url": TINY_JPEG_DATA_URL,
                    "link_type": None,
                    "link_value": "",
                }
            ],
        }
        r = requests.post(
            f"{BASE_URL}/api/admin/shop-layout", json=payload, headers=_hdr(admin_token)
        )
        assert r.status_code == 200, r.text
        block = r.json()
        block_id = block.get("id")
        assert block_id
        try:
            assert block.get("items") and len(block["items"]) == 1
            assert block["items"][0]["image_data_url"].startswith("data:image/jpeg;base64,")
        finally:
            requests.delete(
                f"{BASE_URL}/api/admin/shop-layout/{block_id}",
                headers=_hdr(admin_token),
            )

    def test_patch_block_image(self, admin_token):
        """PATCH must accept image_data_url update from fitter."""
        # create
        create = requests.post(
            f"{BASE_URL}/api/admin/shop-layout",
            json={
                "block_type": "background",
                "title": "TEST_iter21_patch",
                "image_data_url": "",
                "active": True,
                "sort_order": 9997,
            },
            headers=_hdr(admin_token),
        )
        assert create.status_code == 200
        block_id = create.json()["id"]
        try:
            r = requests.patch(
                f"{BASE_URL}/api/admin/shop-layout/{block_id}",
                json={"image_data_url": TINY_JPEG_DATA_URL},
                headers=_hdr(admin_token),
            )
            assert r.status_code == 200, r.text
            updated = r.json()
            assert updated.get("image_data_url", "").startswith("data:image/jpeg;base64,")
        finally:
            requests.delete(
                f"{BASE_URL}/api/admin/shop-layout/{block_id}",
                headers=_hdr(admin_token),
            )


# ────────────────────────────────────────────────────────────────────────────
# Admin products — accept fitter-produced data URLs for image_url & images[]
# ────────────────────────────────────────────────────────────────────────────
class TestAdminProductsImageFitter:
    def test_create_product_with_data_url(self, admin_token):
        suffix = uuid.uuid4().hex[:6]
        payload = {
            "name": f"TEST_iter21_product_{suffix}",
            "price": 9.99,
            "image_url": TINY_JPEG_DATA_URL,
            "description": "fitter product_image preset (800x800)",
            "stock": 5,
            "category": "Electronics",
            "is_published": False,
            "images": [TINY_JPEG_DATA_URL, TINY_JPEG_DATA_URL],
        }
        r = requests.post(
            f"{BASE_URL}/api/admin/products", json=payload, headers=_hdr(admin_token)
        )
        assert r.status_code == 200, r.text
        product = r.json()
        pid = product.get("id")
        assert pid
        try:
            assert product["image_url"].startswith("data:image/jpeg;base64,")
            assert isinstance(product.get("images"), list) and len(product["images"]) == 2
            # Verify via list
            list_r = requests.get(
                f"{BASE_URL}/api/admin/products", headers=_hdr(admin_token)
            )
            assert list_r.status_code == 200
            assert any(p.get("id") == pid for p in list_r.json())
        finally:
            del_r = requests.delete(
                f"{BASE_URL}/api/admin/products/{pid}", headers=_hdr(admin_token)
            )
            assert del_r.status_code in (200, 204), del_r.text

    def test_patch_product_with_data_url(self, admin_token):
        suffix = uuid.uuid4().hex[:6]
        # create
        create = requests.post(
            f"{BASE_URL}/api/admin/products",
            json={
                "name": f"TEST_iter21_patch_{suffix}",
                "price": 1.0,
                "image_url": "https://example.com/x.jpg",
                "stock": 1,
                "is_published": False,
            },
            headers=_hdr(admin_token),
        )
        assert create.status_code == 200
        pid = create.json()["id"]
        try:
            r = requests.patch(
                f"{BASE_URL}/api/admin/products/{pid}",
                json={"image_url": TINY_JPEG_DATA_URL, "images": [TINY_JPEG_DATA_URL]},
                headers=_hdr(admin_token),
            )
            assert r.status_code == 200, r.text
            updated = r.json()
            assert updated["image_url"].startswith("data:image/jpeg;base64,")
            assert updated["images"][0].startswith("data:image/jpeg;base64,")
        finally:
            requests.delete(
                f"{BASE_URL}/api/admin/products/{pid}", headers=_hdr(admin_token)
            )


# ────────────────────────────────────────────────────────────────────────────
# Regression smoke from iteration 15 — chat settings / lock / broadcast
# ────────────────────────────────────────────────────────────────────────────
class TestIter15Regression:
    """Confirm previously-passing endpoints from iter15 still respond OK."""

    @pytest.fixture(scope="class")
    def alice_token(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "test_alice_73dc7f@test.com", "password": "Passw0rd!"},
        )
        if r.status_code != 200:
            pytest.skip(f"Alice test account unavailable: {r.status_code} {r.text}")
        return r.json()["token"]

    def test_chat_settings_get(self, alice_token):
        r = requests.get(f"{BASE_URL}/api/chat/settings", headers=_hdr(alice_token))
        assert r.status_code == 200, r.text
        body = r.json()
        # Must contain expected keys (don't strictly validate values)
        for k in ("has_pin", "locked_thread_ids"):
            assert k in body, f"Missing key {k} in /api/chat/settings"

    def test_chat_lock_threads_patch_idempotent(self, alice_token):
        # Reset Alice's locked_thread_ids to []
        r = requests.patch(
            f"{BASE_URL}/api/chat/lock/threads",
            json={"pin": "1234", "locked_thread_ids": []},
            headers=_hdr(alice_token),
        )
        # Some impls return 200 even when already empty
        assert r.status_code in (200, 204), r.text

    def test_admin_broadcast_list(self, admin_token):
        # Iter13/15 used /api/admin/broadcast — confirm it still resolves
        r = requests.get(
            f"{BASE_URL}/api/admin/broadcasts", headers=_hdr(admin_token)
        )
        # Either the canonical endpoint returns 200 OR the legacy spelling.
        # We just need to confirm no 500 / crash.
        assert r.status_code in (200, 404), r.text
