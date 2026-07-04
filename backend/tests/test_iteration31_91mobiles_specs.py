"""Tests for the new GSMArena-backed spec-template endpoint.

Endpoint: GET /api/products/master/91mobiles-specs?name=<name>&brand=<brand>
Introduced in iteration 31 to fix the "Load 91mobiles template" bug where
only labels were shown with empty values.
"""
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
SPECS_URL = f"{BASE_URL}/api/products/master/91mobiles-specs"


@pytest.fixture(scope="module")
def alice_token():
    """Approved vendor account from /app/memory/test_credentials.md."""
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "test_alice_73dc7f@test.com", "password": "Passw0rd!"},
        timeout=15,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def auth(alice_token):
    return {"Authorization": f"Bearer {alice_token}"}


# ── 1. Authentication required ──────────────────────────────────────
class TestAuth:
    def test_401_without_token(self):
        r = requests.get(SPECS_URL, params={"name": "iPhone 15", "brand": "Apple"}, timeout=15)
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}: {r.text[:200]}"

    def test_422_when_name_too_short(self, auth):
        r = requests.get(SPECS_URL, params={"name": "a", "brand": "Apple"}, headers=auth, timeout=15)
        assert r.status_code == 422, f"expected 422 for short name, got {r.status_code}: {r.text[:200]}"


# ── 2. iPhone 15 full-payload correctness ───────────────────────────
class TestIPhone15Payload:
    @pytest.fixture(scope="class")
    def payload(self, auth):
        r = requests.get(
            SPECS_URL,
            params={"name": "iPhone 15", "brand": "Apple"},
            headers=auth,
            timeout=30,
        )
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:400]}"
        return r.json()

    def test_shape(self, payload):
        for k in ("source", "matched_url", "matched_name", "hero_image", "spec_tabs", "specs_filled", "specs_total"):
            assert k in payload, f"missing key: {k}"
        assert payload["source"] == "gsmarena"
        assert isinstance(payload["spec_tabs"], list)
        assert isinstance(payload["specs_filled"], int)
        assert isinstance(payload["specs_total"], int)

    def test_all_11_categories(self, payload):
        expected = {
            "General", "Design", "Display", "Performance", "Storage",
            "Rear Camera", "Front Camera", "Battery", "Connectivity",
            "Sensors", "Multimedia",
        }
        got = {t["name"] for t in payload["spec_tabs"]}
        missing = expected - got
        assert not missing, f"missing tabs: {missing}"

    def test_specs_filled_threshold(self, payload):
        # Requirement: >= 50 out of 73
        assert payload["specs_total"] >= 60, f"specs_total too low: {payload['specs_total']}"
        assert payload["specs_filled"] >= 50, (
            f"specs_filled={payload['specs_filled']} out of {payload['specs_total']} "
            f"(need >=50). This suggests scraper isn't extracting real values."
        )

    def test_display_screen_size_contains_6_1(self, payload):
        display = next((t for t in payload["spec_tabs"] if t["name"] == "Display"), None)
        assert display, "Display tab missing"
        screen_row = next((r for r in display["rows"] if r["label"] == "Screen Size"), None)
        assert screen_row, "Screen Size row missing"
        assert "6.1" in (screen_row["value"] or ""), (
            f"expected '6.1' in Screen Size, got: {screen_row['value']!r}"
        )

    def test_general_launch_date_contains_2023(self, payload):
        general = next((t for t in payload["spec_tabs"] if t["name"] == "General"), None)
        assert general, "General tab missing"
        launch = next((r for r in general["rows"] if r["label"] == "Launch Date"), None)
        assert launch, "Launch Date row missing"
        assert "2023" in (launch["value"] or ""), (
            f"expected '2023' in Launch Date, got: {launch['value']!r}"
        )

    def test_matched_name_contains_iphone_15(self, payload):
        assert "iphone 15" in payload["matched_name"].lower(), (
            f"unexpected matched name: {payload['matched_name']}"
        )


# ── 3. Caching behaviour ────────────────────────────────────────────
class TestCache:
    def test_second_call_is_fast(self, auth):
        # First (warm or cold — irrelevant, we want the SECOND one to be cached)
        r1 = requests.get(
            SPECS_URL,
            params={"name": "iPhone 15", "brand": "Apple"},
            headers=auth,
            timeout=30,
        )
        assert r1.status_code == 200
        t0 = time.time()
        r2 = requests.get(
            SPECS_URL,
            params={"name": "iPhone 15", "brand": "Apple"},
            headers=auth,
            timeout=30,
        )
        elapsed_ms = (time.time() - t0) * 1000
        assert r2.status_code == 200
        # cached lookup goes through network + fastapi so allow generous 1500ms
        # (spec allows 100ms for the mongo lookup itself, but preview URL has
        # ~500ms network overhead)
        assert elapsed_ms < 1500, f"cached response too slow: {elapsed_ms:.0f}ms"
        assert r2.json()["spec_tabs"] == r1.json()["spec_tabs"], "cached payload differs"


# ── 4. Multiple popular phones ──────────────────────────────────────
@pytest.mark.parametrize("name,brand,min_filled", [
    ("iPhone 15", "Apple", 40),
    ("Galaxy S24 Ultra", "Samsung", 40),
    ("OnePlus 12R", "OnePlus", 40),
    ("POCO X6 Pro", "POCO", 40),
    ("Pixel 8", "Google", 40),
])
def test_popular_phones(auth, name, brand, min_filled):
    r = requests.get(
        SPECS_URL,
        params={"name": name, "brand": brand},
        headers=auth,
        timeout=45,
    )
    assert r.status_code == 200, (
        f"{name}/{brand}: expected 200, got {r.status_code}: {r.text[:400]}"
    )
    data = r.json()
    assert data["specs_filled"] >= min_filled, (
        f"{name}/{brand}: only {data['specs_filled']} filled (need {min_filled})"
    )
    assert len(data["spec_tabs"]) == 11, (
        f"{name}/{brand}: expected 11 spec tabs, got {len(data['spec_tabs'])}"
    )


# ── 5. Graceful 404s ────────────────────────────────────────────────
class TestNotFound:
    def test_unknown_brand_returns_404(self, auth):
        r = requests.get(
            SPECS_URL,
            params={"name": "SomeModel 12", "brand": "FakeBrand"},
            headers=auth,
            timeout=15,
        )
        assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text[:200]}"

    def test_unmatchable_name_returns_404(self, auth):
        r = requests.get(
            SPECS_URL,
            params={"name": "nonexistent-widget-xyz", "brand": "apple"},
            headers=auth,
            timeout=30,
        )
        assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text[:200]}"


# ── 6. Existing endpoints not broken ────────────────────────────────
class TestNoRegressions:
    def test_products_master_search_still_works(self, auth):
        r = requests.get(
            f"{BASE_URL}/api/products/master/search",
            params={"q": "iphone"},
            headers=auth,
            timeout=15,
        )
        assert r.status_code == 200, f"master/search broken: {r.status_code} {r.text[:200]}"
        # response can be either a list or {results: [...]}
        body = r.json()
        assert isinstance(body, (list, dict)), "unexpected shape"

    def test_products_public_list_still_works(self):
        r = requests.get(f"{BASE_URL}/api/products", timeout=15)
        assert r.status_code == 200, f"/api/products broken: {r.status_code} {r.text[:200]}"
        body = r.json()
        # accept either list or paginated shape
        assert isinstance(body, (list, dict))


# ── 7. Vendor create still stores IMEI / serial fields ──────────────
class TestVendorCreateStillWorks:
    def test_create_product_with_imei_and_serial(self, auth):
        payload = {
            "name": "TEST_91spec_dev_product",
            "description": "regression check for iteration31",
            "price": 1234,
            "category_id": "phones",
            "image_url": "https://example.com/test.jpg",
            "images": [],
            "specs": {"brand": "TestBrand"},
            "serial_number": "SN-TEST-91SPEC-001",
            "imei_1": "111111111111111",
            "imei_2": "222222222222222",
        }
        r = requests.post(
            f"{BASE_URL}/api/vendor/me/products",
            json=payload,
            headers={**auth, "Content-Type": "application/json"},
            timeout=20,
        )
        assert r.status_code in (200, 201), f"create failed: {r.status_code} {r.text[:400]}"
        prod = r.json()
        pid = prod.get("id") or prod.get("_id")
        try:
            # verify persistence via GET
            g = requests.get(
                f"{BASE_URL}/api/vendor/me/products",
                headers=auth,
                timeout=15,
            )
            assert g.status_code == 200
            items = g.json() if isinstance(g.json(), list) else g.json().get("items") or g.json().get("products") or []
            found = next((it for it in items if (it.get("id") or it.get("_id")) == pid), None)
            assert found, "created product not returned by GET /api/vendor/me/products"
            assert found.get("serial_number") == "SN-TEST-91SPEC-001"
            assert found.get("imei_1") == "111111111111111"
            assert found.get("imei_2") == "222222222222222"
        finally:
            if pid:
                requests.delete(
                    f"{BASE_URL}/api/vendor/me/products/{pid}",
                    headers=auth,
                    timeout=15,
                )
