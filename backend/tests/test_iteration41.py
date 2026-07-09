"""Iteration 41 targeted retest — Bellam→jaggery translation gate.

Retests the 7 cases from the review request after main-agent fix to
`/app/backend/routes/products_master_images.py` where KNOWN vernacular terms in
`_TRANSLATIONS` always search the English translation first, with raw fallback
only if translation returns 0 hits.
"""
from __future__ import annotations

import os
from typing import Dict

import pytest
import requests


def _load_base_url() -> str:
    url = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
           or os.environ.get("EXPO_BACKEND_URL")
           or "").rstrip("/")
    if url:
        return url
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
                return line.split("=", 1)[1].strip().strip('"').rstrip("/")
    raise RuntimeError("EXPO_PUBLIC_BACKEND_URL not found")


BASE_URL = _load_base_url()

VENDOR_EMAIL = "test_alice_73dc7f@test.com"
VENDOR_PASSWORD = "Passw0rd!"


@pytest.fixture(scope="module")
def api() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def vendor_headers(api: requests.Session) -> Dict[str, str]:
    r = api.post(f"{BASE_URL}/api/auth/login",
                 json={"email": VENDOR_EMAIL, "password": VENDOR_PASSWORD},
                 timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, f"no token in login body: {r.json()}"
    return {"Authorization": f"Bearer {tok}",
            "Content-Type": "application/json"}


def _search(api: requests.Session, headers: Dict[str, str], q: str,
            limit: int = 10) -> requests.Response:
    return api.get(f"{BASE_URL}/api/products/images/search",
                   params={"q": q, "limit": limit},
                   headers=headers, timeout=45)


class TestTranslationGate:
    """Retests for the vernacular→English translation gate."""

    # ── Vernacular terms: MUST translate ─────────────────────────────
    @pytest.mark.parametrize("q,expected", [
        ("Bellam", "jaggery"),
        ("Uddi pappu", "urad dal"),
        ("Kandi pappu", "toor dal"),
        ("Senaga pappu", "chana dal"),
        ("Minap pappu", "urad dal"),
    ])
    def test_vernacular_translates(self, api, vendor_headers, q, expected):
        r = _search(api, vendor_headers, q)
        assert r.status_code == 200, f"[{q}] {r.status_code} {r.text[:300]}"
        data = r.json()
        assert data.get("resolved_query") == expected, (
            f"[{q}] expected resolved_query='{expected}', got "
            f"'{data.get('resolved_query')}'")
        # Spec: Bellam must have count >=3 (others should also have hits since
        # they map to well-known English terms).
        assert data.get("count", 0) >= 3, (
            f"[{q}] count={data.get('count')} (expected >=3)")

    # ── Non-vernacular term: MUST NOT translate ──────────────────────
    def test_sugar_no_translation(self, api, vendor_headers):
        r = _search(api, vendor_headers, "Sugar")
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        data = r.json()
        # resolved_query should be unchanged (case-insensitive compare — server
        # may normalize case).
        assert (data.get("resolved_query") or "").lower() == "sugar", (
            f"expected resolved_query='Sugar' (unchanged), got "
            f"'{data.get('resolved_query')}'")
        assert data.get("count", 0) >= 5, (
            f"expected count >=5, got {data.get('count')}")

    # ── Non-vernacular gibberish: 404 or 0 hits ──────────────────────
    def test_gibberish_no_hits(self, api, vendor_headers):
        r = _search(api, vendor_headers, "nonexistgibberish123")
        assert r.status_code in (200, 404), (
            f"expected 200 or 404, got {r.status_code} {r.text[:200]}")
        if r.status_code == 200:
            data = r.json()
            assert data.get("count", 0) == 0, (
                f"expected count=0 for gibberish, got {data.get('count')}")
