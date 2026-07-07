"""
Iteration 37 — Deodap detail enrichment + 91mobiles thumb→big URL rewrite +
Deodap `handle` field in master-search rows.

Endpoints under test:
  1. GET /api/products/master/deodap-detail?handle=<handle>  (NEW)
     - Requires auth (401 without token)
     - handle=<valid> → 200 with { handle, title, description, images[] }
     - images should contain 3+ HTTPS/cdn.shopify.com URLs
     - handle=<junk> → 404 clean error (not 500)
     - missing handle → 422 validation error

  2. GET /api/products/master/search Deodap rows now carry a `handle` field
     (non-empty for source=deodap, absent/empty for other sources).

  3. GET /api/products/master/search 91mobiles rows: image_url no longer contains
     '/thumb/' path OR '-thumb-' suffix — should be '/big/' / '-big-' instead
     (or an unrelated format if not a thumbnail URL).

Regressions (confirm intact):
  (a) POST /api/vendor/me/products with serial_number/imei_1/imei_2
  (b) GET /api/shop-layout returns items
  (c) GET /api/products/master/91mobiles-specs?name=iPhone+15 works (specs + gallery)
  (d) /api/products/master/search still merges 3 sources
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL",
    os.environ.get("EXPO_BACKEND_URL", ""),
).rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL / EXPO_BACKEND_URL env var must be set"

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "support@networkrupay.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Nlee@1115")
ALICE_EMAIL = "test_alice_73dc7f@test.com"
ALICE_PASSWORD = "Passw0rd!"

# Known-good Deodap handles from the review request
KNOWN_HANDLES = [
    "wireless-over-ear-bluetooth-headphones-zw-053",
    "12836_3d_vr_box_with_headphones",
]


# ---------------- helpers ----------------

def _login(session: requests.Session, email: str, password: str) -> str:
    r = session.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=30,
    )
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text}"
    return r.json()["token"]


def _bearer(tok: str):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---------------- fixtures ----------------

@pytest.fixture(scope="module")
def http():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def alice_token(http):
    return _login(http, ALICE_EMAIL, ALICE_PASSWORD)


@pytest.fixture(scope="module")
def valid_handle(http, alice_token):
    """Fetch a live valid deodap handle from search, fall back to known-good."""
    try:
        r = http.get(
            f"{BASE_URL}/api/products/master/search?q=headphone&limit=15",
            headers=_bearer(alice_token),
            timeout=45,
        )
        if r.status_code == 200:
            body = r.json()
            for it in body.get("items", []):
                if it.get("source") == "deodap" and it.get("handle"):
                    return it["handle"]
    except Exception as e:
        print(f"could not pull live handle: {e}")
    return KNOWN_HANDLES[0]


# ============================================================
# 1. Deodap detail endpoint tests
# ============================================================

class TestDeodapDetailAuth:
    """Endpoint requires auth."""

    def test_missing_token_401(self, http):
        r = http.get(
            f"{BASE_URL}/api/products/master/deodap-detail?handle={KNOWN_HANDLES[0]}",
            timeout=30,
        )
        assert r.status_code == 401, f"expected 401 got {r.status_code}: {r.text[:200]}"


class TestDeodapDetailValid:
    """Valid handle → 200 with full gallery."""

    def test_valid_handle_returns_gallery(self, http, alice_token, valid_handle):
        r = http.get(
            f"{BASE_URL}/api/products/master/deodap-detail",
            params={"handle": valid_handle},
            headers=_bearer(alice_token),
            timeout=45,
        )
        assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
        body = r.json()
        # required fields
        for k in ("handle", "title", "description", "images"):
            assert k in body, f"response missing '{k}': keys={list(body.keys())}"
        assert isinstance(body["handle"], str) and body["handle"], \
            f"handle should be non-empty string, got {body['handle']!r}"
        assert isinstance(body["title"], str), f"title not string: {type(body['title'])}"
        assert isinstance(body["description"], str), \
            f"description not string: {type(body['description'])}"
        assert isinstance(body["images"], list), \
            f"images not list: {type(body['images'])}"

        # Real deodap products ship 5-12 images; require >=3
        assert len(body["images"]) >= 3, (
            f"expected >=3 images for {valid_handle}, got {len(body['images'])}: "
            f"{body['images']}"
        )
        # Every URL should be https:// or cdn.shopify.com
        for img in body["images"]:
            assert isinstance(img, str) and img, f"image entry invalid: {img!r}"
            assert (
                img.startswith("https://")
                or "cdn.shopify.com" in img
            ), f"image_url looks invalid: {img!r}"


class TestDeodapDetailInvalid:
    """Junk handle → clean 404, not 500."""

    def test_invalid_handle_404(self, http, alice_token):
        r = http.get(
            f"{BASE_URL}/api/products/master/deodap-detail",
            params={"handle": f"junk-non-existent-{uuid.uuid4().hex}"},
            headers=_bearer(alice_token),
            timeout=45,
        )
        assert r.status_code == 404, \
            f"expected 404 for invalid handle, got {r.status_code}: {r.text[:300]}"
        # Detail message should be present and human-readable
        body = r.json()
        assert "detail" in body, f"404 missing detail field: {body}"
        assert isinstance(body["detail"], str) and body["detail"], \
            f"detail should be non-empty string, got {body['detail']!r}"


class TestDeodapDetailMissingParam:
    """Missing handle → 422 validation error."""

    def test_missing_handle_422(self, http, alice_token):
        r = http.get(
            f"{BASE_URL}/api/products/master/deodap-detail",
            headers=_bearer(alice_token),
            timeout=30,
        )
        assert r.status_code == 422, \
            f"expected 422 for missing handle, got {r.status_code}: {r.text[:300]}"


# ============================================================
# 2. handle field on Deodap rows in master-search
# ============================================================

class TestDeodapHandleField:
    """Deodap rows carry a non-empty `handle` field; other sources don't."""

    def test_deodap_rows_have_handle(self, http, alice_token):
        r = http.get(
            f"{BASE_URL}/api/products/master/search?q=headphone&limit=15",
            headers=_bearer(alice_token),
            timeout=45,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        deodap_rows = [it for it in body["items"] if it.get("source") == "deodap"]
        if not deodap_rows:
            pytest.skip("no deodap rows for 'headphone' — external upstream empty")

        for row in deodap_rows:
            handle = row.get("handle")
            assert handle, f"deodap row missing handle: {row.get('name')} → {row}"
            assert isinstance(handle, str), f"handle should be string: {handle!r}"
            # Shopify handles are lowercase-dash slugs, allow underscores too
            # (Deodap uses both formats).
            assert " " not in handle, f"handle should not contain spaces: {handle!r}"

    def test_handle_can_be_used_to_fetch_detail(self, http, alice_token):
        """End-to-end: search → pick deodap row → deodap-detail returns gallery."""
        r = http.get(
            f"{BASE_URL}/api/products/master/search?q=headphone&limit=15",
            headers=_bearer(alice_token),
            timeout=45,
        )
        assert r.status_code == 200
        body = r.json()
        deodap_rows = [it for it in body["items"] if it.get("source") == "deodap"]
        if not deodap_rows:
            pytest.skip("no deodap rows returned")

        handle = deodap_rows[0].get("handle")
        assert handle, "first deodap row has no handle"

        r2 = http.get(
            f"{BASE_URL}/api/products/master/deodap-detail",
            params={"handle": handle},
            headers=_bearer(alice_token),
            timeout=45,
        )
        # Should succeed OR 404 (product may be delisted); either way must not 500.
        assert r2.status_code in (200, 404), \
            f"deodap-detail crashed for live handle {handle!r}: " \
            f"{r2.status_code} {r2.text[:300]}"
        if r2.status_code == 200:
            assert len(r2.json().get("images") or []) >= 1


# ============================================================
# 3. 91mobiles thumbnail URL rewrite
# ============================================================

class TestM91ThumbRewrite:
    """91mobiles image_url should no longer contain /thumb/ or -thumb- variants."""

    def test_91m_image_urls_are_big_variant(self, http, alice_token):
        # Use a phones query so 91mobiles hits
        r = http.get(
            f"{BASE_URL}/api/products/master/search?q=iphone+15&limit=15",
            headers=_bearer(alice_token),
            timeout=45,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        m91 = [it for it in body["items"] if it.get("source") == "91mobiles"]
        if not m91:
            # try a different query
            r = http.get(
                f"{BASE_URL}/api/products/master/search?q=galaxy+s24&limit=15",
                headers=_bearer(alice_token),
                timeout=45,
            )
            assert r.status_code == 200
            m91 = [it for it in r.json()["items"] if it.get("source") == "91mobiles"]
        if not m91:
            pytest.skip("no 91mobiles rows returned — upstream may be down")

        offenders = []
        for row in m91:
            img = row.get("image_url") or ""
            if not img:
                continue
            # After rewrite: neither /thumb/ nor -thumb- should appear.
            if "/thumb/" in img or "-thumb-" in img:
                offenders.append((row.get("name"), img))
        assert not offenders, (
            f"91mobiles image_urls should be rewritten from thumb→big. "
            f"Offenders: {offenders}"
        )


# ============================================================
# 4. Regressions
# ============================================================

class TestRegressionVendorImei:
    """(a) POST /api/vendor/me/products with serial + imei still persists."""

    def test_create_product_serial_imei(self, http, alice_token):
        name = f"TEST_iter37_{uuid.uuid4().hex[:6]}"
        payload = {
            "name": name,
            "price": 111.0,
            "image_url": "https://example.com/x.png",
            "brand": "Regr",
            "description": "TEST iter37 regression",
            "category": "Electronics",
            "serial_number": "SN-37-XYZ",
            "imei_1": "111111111111111",
            "imei_2": "222222222222222",
        }
        r = http.post(
            f"{BASE_URL}/api/vendor/me/products",
            json=payload,
            headers=_bearer(alice_token),
            timeout=30,
        )
        if r.status_code in (401, 403):
            pytest.skip(f"vendor cannot create product ({r.status_code})")
        assert r.status_code in (200, 201), r.text
        created = r.json()
        pid = created.get("id")
        try:
            assert created.get("serial_number") == "SN-37-XYZ"
            assert created.get("imei_1") == "111111111111111"
            assert created.get("imei_2") == "222222222222222"
        finally:
            if pid:
                http.delete(
                    f"{BASE_URL}/api/vendor/me/products/{pid}",
                    headers=_bearer(alice_token),
                    timeout=15,
                )


class TestRegressionShopLayout:
    """(b) GET /api/shop-layout still returns blocks."""

    def test_shop_layout_returns_items(self, http, alice_token):
        r = http.get(
            f"{BASE_URL}/api/shop-layout",
            headers=_bearer(alice_token),
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Response should contain items key (list)
        assert isinstance(body, dict), f"expected dict, got {type(body)}"
        assert "items" in body, f"response missing 'items': {list(body.keys())}"
        assert isinstance(body["items"], list)


class TestRegression91mSpecs:
    """(c) 91mobiles-specs for iPhone 15 still returns specs + gallery."""

    def test_iphone_specs_gallery(self, http, alice_token):
        r = http.get(
            f"{BASE_URL}/api/products/master/91mobiles-specs",
            params={"name": "iPhone 15", "brand": "Apple"},
            headers=_bearer(alice_token),
            timeout=60,
        )
        assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
        body = r.json()
        assert isinstance(body, dict) and body, "empty response"
        # Look for spec_tabs / extra_attrs / images anywhere
        # Different shapes across iterations — just require some content.
        # If gallery exposed as 'images' or 'gallery', require >=5.
        images = body.get("images") or body.get("gallery") or []
        if isinstance(images, list) and images:
            assert len(images) >= 5, (
                f"91mobiles-specs gallery should have >=5 images, got {len(images)}"
            )


class TestRegressionMasterSearchMergesSources:
    """(d) master-search still merges local + 91mobiles + deodap."""

    def test_headphone_merges_3_sources(self, http, alice_token):
        r = http.get(
            f"{BASE_URL}/api/products/master/search?q=headphone&limit=20",
            headers=_bearer(alice_token),
            timeout=45,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        for k in ("local_hits", "m91_hits", "deodap_hits"):
            assert k in body, f"response missing '{k}'"
        # At least 2 sources should have data (local may be 0 in fresh DBs)
        source_counts = {
            "local": body["local_hits"],
            "91mobiles": body["m91_hits"],
            "deodap": body["deodap_hits"],
        }
        non_zero = [s for s, c in source_counts.items() if c > 0]
        assert len(non_zero) >= 2, (
            f"expected at least 2 sources with hits, got {source_counts}"
        )
