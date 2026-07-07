"""Iteration 39 — Tests for the fast pre-fetch endpoint.

Endpoint: GET /api/products/master/91mobiles-detail?name=<name>&brand=<brand>

Returns only { source, matched_url, matched_name, hero_image, gallery } — a
lightweight companion to /91mobiles-specs used to populate product images
the instant a 91mobiles row is picked from Smart Search.
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
DETAIL_URL = f"{BASE_URL}/api/products/master/91mobiles-detail"
SPECS_URL = f"{BASE_URL}/api/products/master/91mobiles-specs"


# ── Auth fixture ────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def alice_token():
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


# ── 1. Happy path — Apple iPhone 15 ─────────────────────────────────
class TestHappyPath:
    def test_iphone_15_apple_returns_hero_and_gallery(self, auth):
        r = requests.get(
            DETAIL_URL,
            params={"name": "iPhone 15", "brand": "Apple"},
            headers=auth,
            timeout=30,
        )
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:400]}"
        p = r.json()
        assert p.get("source") == "gsmarena"
        assert "gsmarena.com" in p.get("matched_url", "")
        assert p.get("hero_image"), "hero_image must be non-empty"
        assert isinstance(p.get("gallery"), list) and len(p["gallery"]) > 0, (
            "gallery must be a non-empty list"
        )
        # matched_name should contain iPhone 15
        assert "iphone 15" in p.get("matched_name", "").lower()
        # spec_tabs should NOT be part of this fast endpoint
        assert "spec_tabs" not in p


# ── 2. Brand inference (no brand param) ─────────────────────────────
class TestBrandInference:
    def test_samsung_galaxy_s24_infers_brand(self, auth):
        r = requests.get(
            DETAIL_URL,
            params={"name": "Samsung Galaxy S24"},
            headers=auth,
            timeout=30,
        )
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:400]}"
        p = r.json()
        assert "galaxy s24" in p.get("matched_name", "").lower()
        assert p.get("hero_image"), "hero_image must be non-empty"
        assert isinstance(p.get("gallery"), list) and len(p["gallery"]) > 0


# ── 3. Cache hit is fast ────────────────────────────────────────────
class TestCache:
    def test_second_call_is_fast_and_identical(self, auth):
        # First call — may be cached already from earlier tests but that's fine.
        r1 = requests.get(
            DETAIL_URL,
            params={"name": "iPhone 15", "brand": "Apple"},
            headers=auth,
            timeout=30,
        )
        assert r1.status_code == 200
        p1 = r1.json()

        # Second call — should hit cache
        t0 = time.time()
        r2 = requests.get(
            DETAIL_URL,
            params={"name": "iPhone 15", "brand": "Apple"},
            headers=auth,
            timeout=30,
        )
        elapsed_ms = (time.time() - t0) * 1000
        assert r2.status_code == 200
        p2 = r2.json()

        assert elapsed_ms < 500, f"cache-hit should be <500ms, took {elapsed_ms:.0f}ms"
        assert p1 == p2, "payload should be identical between cache hits"


# ── 4. Unknown brand → 404 ──────────────────────────────────────────
class TestUnknownBrand:
    def test_unknown_brand_returns_404(self, auth):
        r = requests.get(
            DETAIL_URL,
            params={"name": "FakePhone 999", "brand": "nosuchbrand"},
            headers=auth,
            timeout=15,
        )
        assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text[:200]}"
        detail = (r.json().get("detail") or "").lower()
        assert "no gsmarena catalog" in detail, f"unexpected 404 detail: {detail}"


# ── 5. Unmatchable product on known brand → 404 ─────────────────────
class TestUnmatchable:
    def test_unmatchable_product_returns_404(self, auth):
        r = requests.get(
            DETAIL_URL,
            params={"name": "iPhone 9999 Ultra Fake", "brand": "Apple"},
            headers=auth,
            timeout=30,
        )
        assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text[:200]}"
        detail = (r.json().get("detail") or "").lower()
        assert "could not confidently match" in detail, f"unexpected 404 detail: {detail}"


# ── 6. Auth required ────────────────────────────────────────────────
class TestAuthRequired:
    def test_no_auth_returns_401_or_403(self):
        r = requests.get(
            DETAIL_URL,
            params={"name": "iPhone 15", "brand": "Apple"},
            timeout=15,
        )
        assert r.status_code in (401, 403), (
            f"expected 401/403 without auth, got {r.status_code}: {r.text[:200]}"
        )


# ── 7. Regression check — /91mobiles-specs still works ─────────────
class TestSpecsRegression:
    def test_specs_endpoint_still_returns_full_payload(self, auth):
        r = requests.get(
            SPECS_URL,
            params={"name": "iPhone 15", "brand": "Apple"},
            headers=auth,
            timeout=30,
        )
        assert r.status_code == 200, f"expected 200 on /91mobiles-specs, got {r.status_code}: {r.text[:400]}"
        p = r.json()
        assert p.get("source") == "gsmarena"
        assert p.get("hero_image"), "hero_image must be non-empty on specs endpoint"
        assert isinstance(p.get("gallery"), list) and len(p["gallery"]) > 0, (
            "gallery must be non-empty on specs endpoint"
        )
        assert isinstance(p.get("spec_tabs"), list) and len(p["spec_tabs"]) > 0, (
            "spec_tabs must be a non-empty list"
        )
        assert isinstance(p.get("specs_filled"), int)
        assert isinstance(p.get("specs_total"), int)
