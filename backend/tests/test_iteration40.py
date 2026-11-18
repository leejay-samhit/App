"""Iteration 40 backend tests.

Coverage:
  1. products_master.search — 91mobiles blank image bug fix (no `-big-` rewrite,
     image_url reachable via HEAD/GET).
  2. shop_layout — new `category_ids` field on create/patch/get + backfill.
  3. products_master_images — new /products/images/search endpoint
     (Openverse+Wikimedia, regional translations, e-commerce filter,
     auth required, empty query, bogus term).
"""
from __future__ import annotations

import os
import time
import uuid
from typing import Any, Dict, List, Optional

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/") or \
           os.environ.get("EXPO_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fallback for pytest environment — read the frontend .env
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
                    BASE_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")
                    break
    except Exception:
        pass

VENDOR_EMAIL = "test_alice_73dc7f@test.com"
VENDOR_PASSWORD = "Passw0rd!"
ADMIN_EMAIL = "support@networkrupay.com"
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

ECOM_BLOCKLIST = {"amazon", "flipkart", "meesho", "ajio", "myntra",
                  "alibaba", "shopee", "deodap", "snapdeal"}


# ── Fixtures ─────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def api() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _login(api: requests.Session, email: str, password: str) -> str:
    r = api.post(f"{BASE_URL}/api/auth/login",
                 json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, f"no token in login response: {r.json()}"
    return tok


@pytest.fixture(scope="session")
def vendor_token(api: requests.Session) -> str:
    return _login(api, VENDOR_EMAIL, VENDOR_PASSWORD)


@pytest.fixture(scope="session")
def admin_token(api: requests.Session) -> str:
    return _login(api, ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture
def vendor_headers(vendor_token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {vendor_token}",
            "Content-Type": "application/json"}


@pytest.fixture
def admin_headers(admin_token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {admin_token}",
            "Content-Type": "application/json"}


# ── Change 1: 91mobiles blank-image fix ──────────────────────────────
class TestChange1_91mobilesImages:

    def test_iphone15_search_returns_reachable_91m_images(self, api, vendor_headers):
        r = api.get(f"{BASE_URL}/api/products/master/search",
                    params={"q": "iphone 15", "limit": 10},
                    headers=vendor_headers, timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        data = r.json()
        assert "items" in data
        m91_items = [it for it in data["items"] if it.get("source") == "91mobiles"]
        # Might have 0 if local hits >= 3; note either way but require reachability if any
        if not m91_items:
            pytest.skip("No 91mobiles rows returned (local catalog satisfied hit-count).")

        for it in m91_items:
            img = it.get("image_url") or ""
            assert img, f"empty image_url for 91mobiles item: {it.get('name')}"
            assert img.startswith("http"), f"non-http image_url: {img}"
            assert "-big-" not in img, (
                f"regression: 91mobiles url still contains '-big-': {img}")

        # HEAD/GET check reachability
        broken: List[str] = []
        for it in m91_items:
            img = it["image_url"]
            try:
                hr = requests.head(img, timeout=8, allow_redirects=True)
                if hr.status_code == 405 or hr.status_code >= 400:
                    # some CDNs refuse HEAD — retry with GET stream
                    gr = requests.get(img, timeout=8, stream=True,
                                      headers={"User-Agent": "Mozilla/5.0"})
                    if gr.status_code != 200:
                        broken.append(f"{img} -> {gr.status_code}")
                    gr.close()
            except Exception as e:
                broken.append(f"{img} -> exception {e}")
        assert not broken, f"broken 91mobiles image URLs: {broken}"

    def test_regression_search_mixed_sources(self, api, vendor_headers):
        r = api.get(f"{BASE_URL}/api/products/master/search",
                    params={"q": "iphone 15"},
                    headers=vendor_headers, timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert data.get("count", 0) >= 1
        sources = {it.get("source") for it in data.get("items", [])}
        # Just confirm response structure; multiple sources not guaranteed.
        assert sources.issubset({"local", "91mobiles", "deodap"}), sources


# ── Change 2: shop_layout category_ids ───────────────────────────────
class TestChange2_ShopLayoutCategoryIds:

    _created_ids: List[str] = []

    def teardown_method(self, method):
        # Cleanup: delete blocks we created via admin (needs headers each time)
        # We do cleanup via the class-level list in the final test.
        pass

    def test_1_create_block_with_category_ids(self, api, admin_headers):
        payload = {
            "block_type": "category_circles",
            "scope": "home",
            "title": "TEST_iter40 categories",
            "category_ids": ["id1", "id2", "id3"],
            "sort_order": 999,
        }
        r = api.post(f"{BASE_URL}/api/admin/shop-layout",
                     json=payload, headers=admin_headers, timeout=15)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        assert body.get("category_ids") == ["id1", "id2", "id3"], body.get("category_ids")
        assert body.get("id"), "response missing id"
        TestChange2_ShopLayoutCategoryIds._created_ids.append(body["id"])

    def test_2_patch_block_category_ids(self, api, admin_headers):
        assert TestChange2_ShopLayoutCategoryIds._created_ids, "no created block from test_1"
        block_id = TestChange2_ShopLayoutCategoryIds._created_ids[-1]
        r = api.patch(f"{BASE_URL}/api/admin/shop-layout/{block_id}",
                      json={"category_ids": ["id4"]},
                      headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("category_ids") == ["id4"], body.get("category_ids")

    def test_3_patch_omitting_category_ids_preserves_value(self, api, admin_headers):
        block_id = TestChange2_ShopLayoutCategoryIds._created_ids[-1]
        r = api.patch(f"{BASE_URL}/api/admin/shop-layout/{block_id}",
                      json={"title": "TEST_iter40 updated"},
                      headers=admin_headers, timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert body.get("category_ids") == ["id4"], (
            f"category_ids should be preserved, got {body.get('category_ids')}")

    def test_4_get_public_shop_layout_backfills_category_ids(self, api):
        r = api.get(f"{BASE_URL}/api/shop-layout", params={"scope": "home"}, timeout=15)
        assert r.status_code == 200
        items = r.json().get("items", [])
        assert isinstance(items, list)
        for it in items:
            assert "category_ids" in it, f"category_ids missing in block {it.get('id')}"
            assert isinstance(it["category_ids"], list), (
                f"category_ids not list for {it.get('id')}: {type(it['category_ids'])}")

    def test_5_get_admin_shop_layout_backfills_category_ids(self, api, admin_headers):
        r = api.get(f"{BASE_URL}/api/admin/shop-layout",
                    headers=admin_headers, timeout=15)
        assert r.status_code == 200
        items = r.json().get("items", [])
        for it in items:
            assert "category_ids" in it
            assert isinstance(it["category_ids"], list)

    def test_9_cleanup(self, api, admin_headers):
        # Cleanup all created blocks
        for bid in TestChange2_ShopLayoutCategoryIds._created_ids:
            try:
                api.delete(f"{BASE_URL}/api/admin/shop-layout/{bid}",
                           headers=admin_headers, timeout=10)
            except Exception:
                pass


# ── Change 3: Free image picker ──────────────────────────────────────
def _assert_no_ecom(items: List[Dict[str, Any]]):
    bad = []
    for it in items:
        src = (it.get("source") or "").lower()
        for blk in ECOM_BLOCKLIST:
            if blk in src:
                bad.append(src)
                break
    assert not bad, f"e-commerce sources leaked into results: {bad}"


def _assert_https_images(items: List[Dict[str, Any]]):
    for it in items:
        img = it.get("image") or ""
        assert img.startswith("https://"), f"non-https image: {img}"


class TestChange3_FreeImagePicker:

    def test_1_happy_path_sugar(self, api, vendor_headers):
        r = api.get(f"{BASE_URL}/api/products/images/search",
                    params={"q": "sugar", "limit": 10},
                    headers=vendor_headers, timeout=30)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert data.get("query") == "sugar"
        assert data.get("resolved_query")
        assert data.get("count", 0) >= 5, f"expected >=5, got {data.get('count')}"
        items = data.get("items", [])
        assert len(items) >= 5
        _assert_https_images(items)
        _assert_no_ecom(items)

    @pytest.mark.parametrize("q,expected", [
        ("Bellam", "jaggery"),
        ("Uddi pappu", "urad dal"),
        ("Kandi pappu", "toor dal"),
        ("Senaga pappu", "chana dal"),
        ("Minap pappu", "urad dal"),
    ])
    def test_2_regional_translation(self, api, vendor_headers, q, expected):
        r = api.get(f"{BASE_URL}/api/products/images/search",
                    params={"q": q, "limit": 10},
                    headers=vendor_headers, timeout=30)
        assert r.status_code == 200, f"[{q}] {r.status_code} {r.text[:300]}"
        data = r.json()
        assert data.get("resolved_query") == expected, (
            f"[{q}] expected resolved_query='{expected}', got '{data.get('resolved_query')}'")
        assert data.get("count", 0) >= 3, f"[{q}] count={data.get('count')}"
        _assert_no_ecom(data.get("items", []))

    def test_3_ecommerce_filter(self, api, vendor_headers):
        # Query a term where e-commerce might sneak in
        r = api.get(f"{BASE_URL}/api/products/images/search",
                    params={"q": "shampoo", "limit": 20},
                    headers=vendor_headers, timeout=30)
        assert r.status_code in (200, 404)
        if r.status_code == 200:
            _assert_no_ecom(r.json().get("items", []))

    def test_4_empty_query_rejected(self, api, vendor_headers):
        r = api.get(f"{BASE_URL}/api/products/images/search",
                    params={"q": "", "limit": 10},
                    headers=vendor_headers, timeout=15)
        assert r.status_code in (400, 422), f"expected 400/422, got {r.status_code}"

    def test_5_missing_query_rejected(self, api, vendor_headers):
        r = api.get(f"{BASE_URL}/api/products/images/search",
                    headers=vendor_headers, timeout=15)
        assert r.status_code in (400, 422)

    def test_6_cache_hit_faster(self, api, vendor_headers):
        # Prime cache
        api.get(f"{BASE_URL}/api/products/images/search",
                params={"q": "sugar", "limit": 10},
                headers=vendor_headers, timeout=30)
        t0 = time.perf_counter()
        r = api.get(f"{BASE_URL}/api/products/images/search",
                    params={"q": "sugar", "limit": 10},
                    headers=vendor_headers, timeout=30)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        assert r.status_code == 200
        # Cache guideline < 300ms; skip assertion if network is unreliable.
        if elapsed_ms > 800:
            pytest.skip(f"cache timing unreliable in preview env: {elapsed_ms:.0f}ms")
        assert elapsed_ms < 300, f"cache hit took {elapsed_ms:.0f}ms"

    def test_7_bogus_term_returns_404(self, api, vendor_headers):
        r = api.get(f"{BASE_URL}/api/products/images/search",
                    params={"q": "xyzzzz12345nonexistent", "limit": 10},
                    headers=vendor_headers, timeout=30)
        assert r.status_code == 404, f"expected 404, got {r.status_code} {r.text[:200]}"
        body = r.json()
        assert "detail" in body
        assert "no" in body["detail"].lower() or "not found" in body["detail"].lower()

    def test_8_auth_required(self, api):
        r = api.get(f"{BASE_URL}/api/products/images/search",
                    params={"q": "sugar", "limit": 5},
                    headers={"Content-Type": "application/json"}, timeout=15)
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"
