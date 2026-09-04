"""Iter 63 — Shop-Layout Spotlight block + product_count/product_ids caps + brief regressions.

Covers items 1, 2, and 3 from the review request.
"""
from __future__ import annotations
import os
import time
import pytest
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
_fe = Path(__file__).resolve().parents[2] / "frontend" / ".env"
if _fe.exists():
    load_dotenv(_fe, override=False)

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "support@slangcart.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "3)Ywxtic")
VENDOR_EMAIL = "testvendor@test.com"
VENDOR_PASSWORD = "Test@1234"

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) iter63-tests"}


# ── shared fixtures ─────────────────────────────────────────────
@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json", **UA})
    return sess


@pytest.fixture(scope="module")
def admin_token(s):
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def vendor_token(s):
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": VENDOR_EMAIL, "password": VENDOR_PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}", **UA}


# ══════════════════════════════════════════════════════════════
# 1) Spotlight block accepted + surfaced in public shop-layout
# ══════════════════════════════════════════════════════════════
class TestSpotlightBlock:
    """The newly-added `spotlight` block must be accepted by POST /admin/shop-layout,
    persist, and appear via GET /shop-layout for the matching pincode."""

    _created_id = None

    def test_spotlight_block_type_accepted(self, s, admin_token):
        payload = {
            "block_type": "spotlight",
            "scope": "home",
            "scope_pincode": "517644",
            "title": "iter63 spotlight",
            "cta_label": "View more",
            "data_source": "manual",
            "product_ids": [],
            "show_view_all": True,
            "active": True,
        }
        r = s.post(f"{BASE_URL}/api/admin/shop-layout", json=payload, headers=_auth(admin_token))
        assert r.status_code == 200, r.text
        doc = r.json()
        assert doc["block_type"] == "spotlight"
        assert doc["scope_pincode"] == "517644"
        assert doc["cta_label"] == "View more"
        assert doc.get("id")
        TestSpotlightBlock._created_id = doc["id"]

    def test_spotlight_visible_via_public_endpoint(self, s):
        assert TestSpotlightBlock._created_id, "prerequisite create must run first"
        r = s.get(f"{BASE_URL}/api/shop-layout", params={"scope": "home", "pincode": "517644"}, headers=UA)
        assert r.status_code == 200, r.text
        data = r.json()
        ids = [b["id"] for b in data["items"]]
        assert TestSpotlightBlock._created_id in ids, "spotlight block missing from public payload"
        blk = next(b for b in data["items"] if b["id"] == TestSpotlightBlock._created_id)
        assert blk["block_type"] == "spotlight"
        assert blk["title"] == "iter63 spotlight"

    def test_spotlight_cleanup(self, s, admin_token):
        if not TestSpotlightBlock._created_id:
            return
        r = s.delete(
            f"{BASE_URL}/api/admin/shop-layout/{TestSpotlightBlock._created_id}",
            headers=_auth(admin_token),
        )
        assert r.status_code in (200, 404)


# ══════════════════════════════════════════════════════════════
# 2) product_count / product_ids caps raised from 50 → 500
# ══════════════════════════════════════════════════════════════
class TestLayoutCaps:
    _created_id = None

    def test_post_product_count_400_persists(self, s, admin_token):
        payload = {
            "block_type": "product_grid",
            "scope": "home",
            "title": "iter63 caps",
            "data_source": "manual",
            "product_count": 400,
            "product_ids": [f"pid-{i}" for i in range(120)],
            "active": True,
        }
        r = s.post(f"{BASE_URL}/api/admin/shop-layout", json=payload, headers=_auth(admin_token))
        assert r.status_code == 200, r.text
        doc = r.json()
        assert doc["product_count"] == 400, f"expected 400, got {doc['product_count']}"
        assert len(doc["product_ids"]) == 120, f"expected 120 ids, got {len(doc['product_ids'])}"
        TestLayoutCaps._created_id = doc["id"]

    def test_post_product_count_9999_clamps_to_500(self, s, admin_token):
        payload = {
            "block_type": "product_grid",
            "scope": "home",
            "title": "iter63 caps clamp",
            "data_source": "manual",
            "product_count": 9999,
            "active": True,
        }
        r = s.post(f"{BASE_URL}/api/admin/shop-layout", json=payload, headers=_auth(admin_token))
        assert r.status_code == 200, r.text
        doc = r.json()
        assert doc["product_count"] == 500, f"expected clamp to 500, got {doc['product_count']}"
        # cleanup
        s.delete(f"{BASE_URL}/api/admin/shop-layout/{doc['id']}", headers=_auth(admin_token))

    def test_patch_product_count_400_persists(self, s, admin_token):
        assert TestLayoutCaps._created_id
        r = s.patch(
            f"{BASE_URL}/api/admin/shop-layout/{TestLayoutCaps._created_id}",
            json={"product_count": 400},
            headers=_auth(admin_token),
        )
        assert r.status_code == 200, r.text
        assert r.json()["product_count"] == 400

    def test_patch_product_count_9999_clamps_to_500(self, s, admin_token):
        assert TestLayoutCaps._created_id
        r = s.patch(
            f"{BASE_URL}/api/admin/shop-layout/{TestLayoutCaps._created_id}",
            json={"product_count": 9999},
            headers=_auth(admin_token),
        )
        assert r.status_code == 200, r.text
        assert r.json()["product_count"] == 500

    def test_patch_product_ids_over_500_capped(self, s, admin_token):
        assert TestLayoutCaps._created_id
        big_ids = [f"px-{i}" for i in range(650)]
        r = s.patch(
            f"{BASE_URL}/api/admin/shop-layout/{TestLayoutCaps._created_id}",
            json={"product_ids": big_ids},
            headers=_auth(admin_token),
        )
        assert r.status_code == 200, r.text
        assert len(r.json()["product_ids"]) == 500, f"got {len(r.json()['product_ids'])}"

    def test_caps_cleanup(self, s, admin_token):
        if TestLayoutCaps._created_id:
            s.delete(
                f"{BASE_URL}/api/admin/shop-layout/{TestLayoutCaps._created_id}",
                headers=_auth(admin_token),
            )


# ══════════════════════════════════════════════════════════════
# 3) Brief regressions from batch-1 (iter 62)
# ══════════════════════════════════════════════════════════════
class TestRegressions:
    def test_search_suggest_widget_grouped_by_name(self, s):
        r = s.get(
            f"{BASE_URL}/api/products/search-suggest",
            params={"q": "widget", "pincode": "517644"},
            headers=UA,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "items" in data
        names = [it["name"].lower() for it in data["items"]]
        # each name must be unique (grouped)
        assert len(names) == len(set(names)), f"duplicates in suggestions: {names}"
        assert any("widget" in n for n in names), f"widget missing: {names}"

    def test_publish_all_endpoint_reachable(self, s, admin_token, vendor_token):
        # Only verifying endpoint routes / auth remain — do NOT actually flip data
        # 401/403 unauthenticated
        r_unauth = s.post(f"{BASE_URL}/api/admin/products/publish-all", json={"publish": True}, headers=UA)
        assert r_unauth.status_code in (401, 403), f"expected 401/403, got {r_unauth.status_code}"
        # 401/403 as vendor
        r_vendor = s.post(
            f"{BASE_URL}/api/admin/products/publish-all",
            json={"publish": True},
            headers=_auth(vendor_token),
        )
        assert r_vendor.status_code in (401, 403), f"expected 401/403 as vendor, got {r_vendor.status_code}"

    def test_product_image_endpoint_unpublished_ok(self, s, admin_token):
        # Find an unpublished product; if none, skip.
        r = s.get(f"{BASE_URL}/api/admin/products", params={"limit": 100}, headers=_auth(admin_token))
        assert r.status_code == 200, r.text
        items = r.json().get("items", [])
        unpub = [p for p in items if p.get("is_published") is False]
        if not unpub:
            pytest.skip("no unpublished product to sample")
        pid = unpub[0]["id"]
        # Public image endpoint should return 200 even for unpublished
        img = s.get(f"{BASE_URL}/api/products/{pid}/image", params={"w": 360, "q": 72}, headers=UA)
        assert img.status_code == 200, f"got {img.status_code} — expected 200 for unpublished"
        assert img.headers.get("content-type", "").startswith("image/")

    def test_vendor_cash_summary_iter62_regression(self, s, vendor_token):
        r = s.get(
            f"{BASE_URL}/api/vendor/me/pos/cash-summary",
            params={"date": "2026-08-26"},
            headers=_auth(vendor_token),
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("date") == "2026-08-26"
        assert data.get("total_collected") == 300, f"got {data.get('total_collected')}"
        assert data.get("bills") == 1, f"got {data.get('bills')}"
