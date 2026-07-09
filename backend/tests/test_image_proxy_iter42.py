"""Iteration 42 — Backend tests for the free-image proxy + batch base64 fetch
endpoints added to fix the "blank thumbnails + can't download" bug in the
vendor Free Image Picker.

Endpoints under test:
  * GET  /api/products/images/proxy           (public)
  * POST /api/products/images/fetch-to-data   (auth)
  * GET  /api/products/images/search          (auth) — sanity chain
"""

from __future__ import annotations

import os
from urllib.parse import quote

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/") or \
           os.environ.get("EXPO_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL must be set"

# Direct-origin URL to bypass Cloudflare's edge for tests that inspect
# app-level response headers (CF rewrites Cache-Control) or app-level 5xx
# response bodies (CF swaps 502 body with its own HTML error page).
ORIGIN_URL = "http://localhost:8001"

VENDOR_EMAIL = "test_alice_73dc7f@test.com"
VENDOR_PASSWORD = "Passw0rd!"

WIKIMEDIA_THUMB = (
    "https://upload.wikimedia.org/wikipedia/commons/thumb/"
    "d/d7/Sour_rainbow_belts.jpg/500px-Sour_rainbow_belts.jpg"
)
EVIL_URL = "https://evil.example.com/x.jpg"
NON_IMAGE_URL = "https://commons.wikimedia.org/wiki/Main_Page"
FTP_URL = "ftp://foo/bar.jpg"


# ── Fixtures ─────────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def api() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def vendor_token(api: requests.Session) -> str:
    r = api.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": VENDOR_EMAIL, "password": VENDOR_PASSWORD},
    )
    assert r.status_code == 200, f"Vendor login failed: {r.status_code} {r.text}"
    j = r.json()
    tok = j.get("access_token") or j.get("token")
    assert tok, f"No token in login response: {j}"
    return tok


@pytest.fixture(scope="session")
def vendor_headers(vendor_token: str) -> dict:
    return {"Authorization": f"Bearer {vendor_token}"}


@pytest.fixture(scope="session")
def wm_thumbs(api: requests.Session, vendor_headers: dict) -> list:
    """Pull 5 fresh wikimedia/openverse thumbnails from the search endpoint."""
    r = api.get(
        f"{BASE_URL}/api/products/images/search",
        params={"q": "sugar", "limit": 5},
        headers=vendor_headers,
    )
    assert r.status_code == 200, f"Search failed: {r.status_code} {r.text}"
    items = r.json().get("items") or []
    return items


# ── PROXY endpoint ───────────────────────────────────────────────────────
class TestProxyEndpoint:
    """GET /api/products/images/proxy — public, allow-listed CDN streaming."""

    def test_01_happy_path_wikimedia_thumb(self, api):
        """Known-good Wikimedia thumbnail streams back as image/*."""
        url = f"{BASE_URL}/api/products/images/proxy?url={quote(WIKIMEDIA_THUMB, safe='')}"
        r = api.get(url)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:200]}"
        ct = r.headers.get("content-type", "")
        assert ct.startswith("image/"), f"Expected image/*, got {ct}"
        assert len(r.content) > 1000, f"Body too small: {len(r.content)} bytes"

    def test_02_non_allow_listed_host(self, api):
        r = api.get(f"{BASE_URL}/api/products/images/proxy",
                    params={"url": EVIL_URL})
        assert r.status_code == 400, r.text
        assert "not allow-listed" in r.json().get("detail", "").lower(), r.text

    def test_03_non_image_content(self, api):
        """Allow-listed host but returns HTML → 502."""
        r = api.get(f"{BASE_URL}/api/products/images/proxy",
                    params={"url": NON_IMAGE_URL})
        # Wikimedia may return 200 HTML → our code raises 502; if the
        # upstream sends a redirect that resolves to non-image, still 502.
        assert r.status_code == 502, f"Expected 502, got {r.status_code} {r.text[:200]}"

    def test_04_non_http_scheme(self, api):
        r = api.get(f"{BASE_URL}/api/products/images/proxy",
                    params={"url": FTP_URL})
        # ftp host isn't allow-listed either; whichever check trips first
        # must yield 400.
        assert r.status_code == 400, r.text

    def test_05_missing_url(self, api):
        r = api.get(f"{BASE_URL}/api/products/images/proxy")
        assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"

    def test_06_cache_control_header(self, api):
        # Hit origin directly — Cloudflare rewrites Cache-Control at the
        # preview edge (verified: `no-store, no-cache, must-revalidate`
        # from CF vs. `public, max-age=86400, immutable` from origin).
        # The APP correctly sets the intended header; the edge override
        # is an infra concern for the main agent, not a code bug.
        url = f"{ORIGIN_URL}/api/products/images/proxy?url={quote(WIKIMEDIA_THUMB, safe='')}"
        r = api.get(url)
        assert r.status_code == 200
        cc = r.headers.get("cache-control", "")
        assert cc == "public, max-age=86400, immutable", f"Got: {cc!r}"

    def test_07_cors_header(self, api):
        url = f"{BASE_URL}/api/products/images/proxy?url={quote(WIKIMEDIA_THUMB, safe='')}"
        r = api.get(url)
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") == "*", \
            f"Got: {r.headers.get('access-control-allow-origin')!r}"

    def test_08_no_auth_required(self, api):
        """Proxy MUST be public (RN <Image> can't send Bearer)."""
        # Fresh session with NO Authorization header.
        s = requests.Session()
        url = f"{BASE_URL}/api/products/images/proxy?url={quote(WIKIMEDIA_THUMB, safe='')}"
        r = s.get(url)
        assert r.status_code == 200, f"Public proxy blocked: {r.status_code} {r.text[:120]}"


# ── BATCH fetch endpoint ─────────────────────────────────────────────────
class TestBatchFetchToData:
    """POST /api/products/images/fetch-to-data — vendor-authenticated."""

    def test_09_happy_single(self, api, vendor_headers):
        r = api.post(
            f"{BASE_URL}/api/products/images/fetch-to-data",
            json={"urls": [WIKIMEDIA_THUMB]},
            headers=vendor_headers,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        j = r.json()
        assert j.get("count") == 1, j
        assert j.get("ok_count") == 1, j
        item = j["items"][0]
        assert item["ok"] is True, item
        assert item["data_url"].startswith("data:image/"), item["data_url"][:80]
        assert ";base64," in item["data_url"]

    def test_10_happy_multi(self, api, vendor_headers, wm_thumbs):
        # Prefer wikimedia thumbs; if fewer than 3 are wikimedia, pad with the known one.
        wm_only = [i["thumbnail"] for i in wm_thumbs
                   if "wikimedia.org" in (i.get("thumbnail") or "")][:3]
        while len(wm_only) < 3:
            wm_only.append(WIKIMEDIA_THUMB)
        urls = list(dict.fromkeys(wm_only))[:3]
        # Ensure exactly 3 unique-ish URLs; if dedupe collapsed, retry with search image field.
        if len(urls) < 3:
            for i in wm_thumbs:
                cand = i.get("image")
                if cand and cand not in urls and "wikimedia.org" in cand:
                    urls.append(cand)
                if len(urls) >= 3:
                    break
        # Fallback: force to 3 via slight query-string variations that all resolve to real thumbs.
        while len(urls) < 3:
            urls.append(WIKIMEDIA_THUMB + f"?v={len(urls)}")
        r = api.post(
            f"{BASE_URL}/api/products/images/fetch-to-data",
            json={"urls": urls},
            headers=vendor_headers,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        j = r.json()
        assert j.get("count") == len(urls), j
        # Allow 1 failure tolerance for the padded/query-string variants.
        assert j.get("ok_count") >= max(1, len(urls) - 1), j

    def test_11_mixed_valid_invalid(self, api, vendor_headers):
        r = api.post(
            f"{BASE_URL}/api/products/images/fetch-to-data",
            json={"urls": [WIKIMEDIA_THUMB, EVIL_URL]},
            headers=vendor_headers,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        j = r.json()
        assert j["count"] == 2, j
        assert j["ok_count"] == 1, j
        ok_flags = {it["url"]: it["ok"] for it in j["items"]}
        assert ok_flags[WIKIMEDIA_THUMB] is True
        assert ok_flags[EVIL_URL] is False

    def test_12_all_invalid_hosts(self, api, vendor_headers):
        # Hit origin directly — Cloudflare swaps the JSON body of any 5xx
        # from origin with its own "Bad gateway" HTML page (status code
        # is preserved). Through the public URL only the 502 status can
        # be asserted; the JSON body assertion has to run against origin.
        r = api.post(
            f"{ORIGIN_URL}/api/products/images/fetch-to-data",
            json={"urls": [EVIL_URL, "https://another.bad/x.png"]},
            headers=vendor_headers,
        )
        assert r.status_code == 502, f"{r.status_code} {r.text[:200]}"
        assert "every upstream" in r.json().get("detail", "").lower()

    def test_12b_all_invalid_hosts_public_status_only(self, api, vendor_headers):
        # Through the public preview URL: only status code is reliable.
        r = api.post(
            f"{BASE_URL}/api/products/images/fetch-to-data",
            json={"urls": [EVIL_URL, "https://another.bad/x.png"]},
            headers=vendor_headers,
        )
        assert r.status_code == 502, f"{r.status_code} {r.text[:200]}"

    def test_13_empty_urls(self, api, vendor_headers):
        r = api.post(
            f"{BASE_URL}/api/products/images/fetch-to-data",
            json={"urls": []},
            headers=vendor_headers,
        )
        assert r.status_code == 400, r.text

    def test_14_too_many_urls(self, api, vendor_headers):
        urls = [WIKIMEDIA_THUMB] * 21
        r = api.post(
            f"{BASE_URL}/api/products/images/fetch-to-data",
            json={"urls": urls},
            headers=vendor_headers,
        )
        assert r.status_code == 400, r.text

    def test_15_missing_auth(self, api):
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        r = s.post(
            f"{BASE_URL}/api/products/images/fetch-to-data",
            json={"urls": [WIKIMEDIA_THUMB]},
        )
        assert r.status_code in (401, 403), f"Expected 401/403, got {r.status_code}: {r.text[:120]}"


# ── Integration chain ────────────────────────────────────────────────────
class TestSearchChain:
    """search → proxy first thumbnail, search → fetch-to-data first image."""

    def test_16_search_then_proxy_first_thumb(self, api, vendor_headers, wm_thumbs):
        assert wm_thumbs, "search returned no items"
        thumb = wm_thumbs[0]["thumbnail"]
        r = api.get(f"{BASE_URL}/api/products/images/proxy",
                    params={"url": thumb})
        assert r.status_code == 200, f"{r.status_code} thumb={thumb} body={r.text[:120]}"
        assert r.headers.get("content-type", "").startswith("image/")
        assert len(r.content) > 500

    def test_17_search_then_fetch_first_image(self, api, vendor_headers, wm_thumbs):
        assert wm_thumbs, "search returned no items"
        img = wm_thumbs[0]["image"]
        r = api.post(
            f"{BASE_URL}/api/products/images/fetch-to-data",
            json={"urls": [img]},
            headers=vendor_headers,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        j = r.json()
        assert j["ok_count"] == 1, j
        assert j["items"][0]["data_url"].startswith("data:image/")
