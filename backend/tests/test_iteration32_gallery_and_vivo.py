"""Iteration 32 — Backend tests for the enhanced 91mobiles-specs endpoint.

Focus:
  1. New `gallery` field in /api/products/master/91mobiles-specs response
  2. `_BRAND_PAGES` bump from 3 → 5 lets Vivo X100 resolve to 200
  3. hero_image still populated
  4. gallery capped at 12
  5. Unmatched query still returns 404
  6. No regression on popular phones (iPhone 15, Galaxy S24 Ultra, OnePlus 12R, Pixel 8)
  7. specs_filled >= 40 for iPhone 15
  8. Cache path still fast (< 1500ms — preview URL has network overhead)
  9. Vendor create/update still persists serial_number, imei_1, imei_2
"""
import os
import re
import time
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
_fe = Path(__file__).resolve().parents[2] / "frontend" / ".env"
if _fe.exists():
    load_dotenv(_fe, override=False)

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
SPECS_URL = f"{BASE_URL}/api/products/master/91mobiles-specs"


# ── Fixtures ────────────────────────────────────────────────────────
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


# ── 1. New `gallery` field on iPhone 15 ─────────────────────────────
class TestGalleryFieldIPhone15:
    @pytest.fixture(scope="class")
    def payload(self, auth):
        r = requests.get(
            SPECS_URL,
            params={"name": "iPhone 15", "brand": "Apple"},
            headers=auth,
            timeout=45,
        )
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:400]}"
        return r.json()

    def test_gallery_key_present(self, payload):
        assert "gallery" in payload, f"`gallery` missing from response. Keys: {list(payload.keys())}"
        assert isinstance(payload["gallery"], list), f"`gallery` should be a list, got {type(payload['gallery']).__name__}"

    def test_gallery_has_at_least_5_urls(self, payload):
        assert len(payload["gallery"]) >= 5, (
            f"expected >=5 gallery URLs for iPhone 15, got {len(payload['gallery'])}: {payload['gallery']}"
        )

    def test_gallery_urls_are_gsmarena_imgroot(self, payload):
        pat = re.compile(r"^https://fdn\.gsmarena\.com/imgroot/", re.I)
        bad = [u for u in payload["gallery"] if not pat.match(u)]
        assert not bad, f"gallery URLs not from fdn.gsmarena.com/imgroot/: {bad[:3]}"

    def test_gallery_capped_at_12(self, payload):
        assert len(payload["gallery"]) <= 12, (
            f"gallery exceeds 12-item cap: {len(payload['gallery'])}"
        )

    def test_hero_image_still_present(self, payload):
        assert payload.get("hero_image"), f"hero_image missing/empty: {payload.get('hero_image')!r}"

    def test_specs_filled_still_over_40(self, payload):
        assert payload["specs_filled"] >= 40, (
            f"regression: specs_filled dropped to {payload['specs_filled']} (need >=40)"
        )


# ── 2. Vivo X100 — previously 404, now 200 (verifies _BRAND_PAGES=5) ─
class TestVivoX100Matching:
    def test_vivo_x100_returns_200(self, auth):
        r = requests.get(
            SPECS_URL,
            params={"name": "Vivo X100", "brand": "Vivo"},
            headers=auth,
            timeout=60,  # cold brand cache can take ~5s (5 pages)
        )
        assert r.status_code == 200, (
            f"Vivo X100 should now resolve (BRAND_PAGES=5): "
            f"got {r.status_code}: {r.text[:400]}"
        )
        data = r.json()
        assert "x100" in data.get("matched_name", "").lower(), (
            f"unexpected matched_name for Vivo X100: {data.get('matched_name')!r}"
        )


# ── 3. Unmatchable query still 404 ──────────────────────────────────
class TestUnmatchableStill404:
    def test_zzz_test_query_still_404(self, auth):
        r = requests.get(
            SPECS_URL,
            params={"name": "ZZZTest99", "brand": "apple"},
            headers=auth,
            timeout=30,
        )
        assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text[:200]}"


# ── 4. No regression on previously-working popular phones ───────────
@pytest.mark.parametrize("name,brand", [
    ("iPhone 15", "Apple"),
    ("Galaxy S24 Ultra", "Samsung"),
    ("OnePlus 12R", "OnePlus"),
    ("Pixel 8", "Google"),
])
def test_popular_phones_no_regression(auth, name, brand):
    r = requests.get(
        SPECS_URL,
        params={"name": name, "brand": brand},
        headers=auth,
        timeout=60,
    )
    assert r.status_code == 200, (
        f"{name}/{brand}: expected 200, got {r.status_code}: {r.text[:400]}"
    )
    body = r.json()
    assert body.get("specs_filled", 0) >= 40, (
        f"{name}/{brand}: specs_filled dropped to {body.get('specs_filled')} (need >=40)"
    )
    # New key must be present on every 200 response
    assert "gallery" in body and isinstance(body["gallery"], list), (
        f"{name}/{brand}: missing `gallery` list in response"
    )
    assert len(body["gallery"]) <= 12, (
        f"{name}/{brand}: gallery exceeds 12-item cap ({len(body['gallery'])})"
    )


# ── 5. Cache path still fast ────────────────────────────────────────
class TestCacheFast:
    def test_second_call_is_fast(self, auth):
        # Warm
        r1 = requests.get(
            SPECS_URL,
            params={"name": "iPhone 15", "brand": "Apple"},
            headers=auth,
            timeout=45,
        )
        assert r1.status_code == 200
        # Cached
        t0 = time.time()
        r2 = requests.get(
            SPECS_URL,
            params={"name": "iPhone 15", "brand": "Apple"},
            headers=auth,
            timeout=30,
        )
        elapsed_ms = (time.time() - t0) * 1000
        assert r2.status_code == 200
        # 100ms is the DB-lookup budget but the preview URL adds ~500ms
        # of network+ingress overhead. Allow 1500ms wall-clock.
        assert elapsed_ms < 1500, f"cached response too slow: {elapsed_ms:.0f}ms"
        # Cached payload must still contain the new gallery field
        assert "gallery" in r2.json(), "cached payload missing `gallery` field"


# ── 6. Vendor create/update still persists serial + IMEI fields ─────
class TestVendorSerialImeiPersistence:
    def test_create_and_update_preserves_imei_serial(self, auth):
        create_payload = {
            "name": "TEST_iter32_serial_imei",
            "description": "iter32 backend regression",
            "price": 4999,
            "category_id": "phones",
            "image_url": "https://example.com/x.jpg",
            "images": [],
            "specs": {"brand": "TestBrand"},
            "serial_number": "SN-ITER32-AAA",
            "imei_1": "300000000000001",
            "imei_2": "300000000000002",
        }
        r = requests.post(
            f"{BASE_URL}/api/vendor/me/products",
            json=create_payload,
            headers={**auth, "Content-Type": "application/json"},
            timeout=20,
        )
        assert r.status_code in (200, 201), f"create failed: {r.status_code} {r.text[:400]}"
        prod = r.json()
        pid = prod.get("id") or prod.get("_id")
        assert pid, f"no id returned: {prod}"
        try:
            # Verify via GET list
            g = requests.get(
                f"{BASE_URL}/api/vendor/me/products",
                headers=auth,
                timeout=15,
            )
            assert g.status_code == 200
            body = g.json()
            items = body if isinstance(body, list) else (
                body.get("items") or body.get("products") or []
            )
            found = next((it for it in items if (it.get("id") or it.get("_id")) == pid), None)
            assert found, "created product not returned by GET"
            assert found.get("serial_number") == "SN-ITER32-AAA"
            assert found.get("imei_1") == "300000000000001"
            assert found.get("imei_2") == "300000000000002"

            # Update — change IMEI-2 via PATCH and confirm persistence
            upd = requests.patch(
                f"{BASE_URL}/api/vendor/me/products/{pid}",
                json={"imei_2": "300000000000099"},
                headers={**auth, "Content-Type": "application/json"},
                timeout=20,
            )
            assert upd.status_code in (200, 204), f"update failed: {upd.status_code} {upd.text[:300]}"
            g2 = requests.get(
                f"{BASE_URL}/api/vendor/me/products",
                headers=auth,
                timeout=15,
            )
            body2 = g2.json()
            items2 = body2 if isinstance(body2, list) else (
                body2.get("items") or body2.get("products") or []
            )
            found2 = next((it for it in items2 if (it.get("id") or it.get("_id")) == pid), None)
            assert found2 and found2.get("imei_2") == "300000000000099", (
                f"update did not persist imei_2: {found2}"
            )
        finally:
            if pid:
                requests.delete(
                    f"{BASE_URL}/api/vendor/me/products/{pid}",
                    headers=auth,
                    timeout=15,
                )
