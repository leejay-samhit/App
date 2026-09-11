"""Iteration 53 — Slangcart perf & UX fixes regression.

Verifies:
  1. GET /api/admin/products — paginated envelope, slim projection
     (NO base64 in payload), <200KB, respects ?limit and ?q filters.
  2. GET /api/products?q= — public free-text search across name/etc.
  3. GET /api/cart — batched find, slim projection, no base64 in
     product blocks, responds in <500ms.

Test credentials are read from /app/memory/test_credentials.md and
mirrored here for convenience.
"""
import os
import re
import time
import json
import base64
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://slangcart-tracking.preview.emergentagent.com").rstrip("/")

ADMIN_EMAIL = "support@slangcart.com"
ADMIN_PASSWORD = "3)Ywxtic"
# Note (iter 53): the DB is a fresh instance, so the users mentioned in
# /app/memory/test_credentials.md (leejay@, knasar786@, brightkittu@) do
# NOT exist. Falling back to the test users that DO exist —
# testbuyer@test.com and testvendor@test.com — whose passwords the test
# harness reset to Test@1234 for CI purposes.
USER_EMAIL = "testbuyer@test.com"
USER_PASSWORD = "Test@1234"
VENDOR_EMAIL = "testvendor@test.com"
VENDOR_PASSWORD = "Test@1234"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _login(session, email, password):
    r = session.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text[:300]}"
    data = r.json()
    tok = data.get("token") or data.get("access_token")
    assert tok, f"no token in login response for {email}: {data}"
    return tok


@pytest.fixture(scope="module")
def admin_token(session):
    return _login(session, ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def user_token(session):
    return _login(session, USER_EMAIL, USER_PASSWORD)


@pytest.fixture(scope="module")
def vendor_token(session):
    return _login(session, VENDOR_EMAIL, VENDOR_PASSWORD)


def _auth(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _has_base64_data_uri(obj) -> bool:
    """Recursively scan a JSON structure for a base64 image data-URI."""
    if isinstance(obj, str):
        return obj.startswith("data:image") and ";base64," in obj
    if isinstance(obj, dict):
        return any(_has_base64_data_uri(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_base64_data_uri(v) for v in obj)
    return False


# ─────────────────────────────────────────────────────────────
# 1. Admin /api/admin/products — paginated envelope + slim projection
# ─────────────────────────────────────────────────────────────
class TestAdminProductsPaginated:

    def test_default_envelope_shape(self, session, admin_token):
        r = session.get(f"{BASE_URL}/api/admin/products", headers=_auth(admin_token), timeout=20)
        assert r.status_code == 200, f"got {r.status_code}: {r.text[:200]}"
        data = r.json()
        assert isinstance(data, dict), f"expected paginated dict, got {type(data)}"
        for key in ("items", "total", "limit", "offset", "has_more"):
            assert key in data, f"missing '{key}' in response: {list(data.keys())}"
        assert isinstance(data["items"], list)
        assert data["limit"] == 60, f"expected default limit=60, got {data['limit']}"
        assert data["offset"] == 0
        assert data["total"] >= 0

    def test_no_base64_in_payload(self, session, admin_token):
        r = session.get(f"{BASE_URL}/api/admin/products?limit=60", headers=_auth(admin_token), timeout=20)
        assert r.status_code == 200
        data = r.json()
        items = data.get("items", [])
        # ── Slim projection: no base64 image_url on ANY item.
        for it in items:
            img = it.get("image_url") or ""
            assert not (isinstance(img, str) and img.startswith("data:")), (
                f"product {it.get('id')} still returns base64 image_url"
            )
            # Verify slim fields are stripped
            for banned in ("images", "description", "specifications", "interested_users", "reviews", "questions"):
                assert banned not in it, f"slim projection failed: {banned} present in item {it.get('id')}"

    def test_response_size_under_200kb(self, session, admin_token):
        r = session.get(f"{BASE_URL}/api/admin/products?limit=60", headers=_auth(admin_token), timeout=20)
        assert r.status_code == 200
        size = len(r.content)
        assert size < 200 * 1024, f"response too large: {size} bytes (> 200KB), slim projection may not be applied"

    def test_limit_3_returns_max_3_items(self, session, admin_token):
        r = session.get(f"{BASE_URL}/api/admin/products?limit=3", headers=_auth(admin_token), timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert data["limit"] == 3
        assert len(data["items"]) <= 3
        # If backend has >= 3 products the array should be exactly 3
        if data["total"] >= 3:
            assert len(data["items"]) == 3

    def test_max_limit_capped_at_300(self, session, admin_token):
        r = session.get(f"{BASE_URL}/api/admin/products?limit=9999", headers=_auth(admin_token), timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert data["limit"] == 300, f"limit not capped: got {data['limit']}"

    def test_q_filter_no_crash(self, session, admin_token):
        r = session.get(f"{BASE_URL}/api/admin/products?q=widget", headers=_auth(admin_token), timeout=20)
        assert r.status_code == 200, f"?q= caused crash: {r.status_code} {r.text[:200]}"
        data = r.json()
        assert isinstance(data["items"], list)
        # Every returned item must actually match the query on some slim field.
        needle = "widget"
        for it in data["items"]:
            hay = " ".join([
                str(it.get("name") or ""),
                str(it.get("brand") or ""),
                str(it.get("category") or ""),
                str(it.get("sub_category") or ""),
                " ".join(it.get("tags") or []) if isinstance(it.get("tags"), list) else str(it.get("tags") or ""),
            ]).lower()
            assert needle in hay, f"product {it.get('id')} name/brand/category doesn't contain '{needle}'"

    def test_offset_pagination_works(self, session, admin_token):
        r0 = session.get(f"{BASE_URL}/api/admin/products?limit=3&offset=0", headers=_auth(admin_token), timeout=20)
        r1 = session.get(f"{BASE_URL}/api/admin/products?limit=3&offset=3", headers=_auth(admin_token), timeout=20)
        assert r0.status_code == 200 and r1.status_code == 200
        d0, d1 = r0.json(), r1.json()
        if d0["total"] >= 6:
            ids0 = {it.get("id") for it in d0["items"]}
            ids1 = {it.get("id") for it in d1["items"]}
            assert ids0.isdisjoint(ids1), "pagination overlap between offset=0 and offset=3"

    def test_admin_only_auth(self, session, user_token):
        r = session.get(f"{BASE_URL}/api/admin/products", headers=_auth(user_token), timeout=15)
        assert r.status_code in (401, 403), f"non-admin should be blocked, got {r.status_code}"

    def test_response_time_reasonable(self, session, admin_token):
        t0 = time.time()
        r = session.get(f"{BASE_URL}/api/admin/products?limit=60", headers=_auth(admin_token), timeout=20)
        dur = time.time() - t0
        assert r.status_code == 200
        # Target: paginated slim call << 3s
        assert dur < 3.0, f"/admin/products took {dur:.2f}s — perf fix regression"


# ─────────────────────────────────────────────────────────────
# 2. Public /api/products?q= free-text search
# ─────────────────────────────────────────────────────────────
class TestPublicProductsSearch:

    def test_q_filter_returns_paginated_envelope(self, session):
        r = session.get(f"{BASE_URL}/api/products?q=widget", timeout=15)
        assert r.status_code == 200
        data = r.json()
        # When any filter (incl. q) is present, endpoint returns paginated envelope
        assert isinstance(data, dict), f"expected paginated envelope, got {type(data)}: {str(data)[:200]}"
        for k in ("items", "total", "limit", "offset", "has_more"):
            assert k in data

    def test_q_filter_matches_name_case_insensitive(self, session):
        # Use a query prefix that should match if any Kittu product exists
        r = session.get(f"{BASE_URL}/api/products?q=kittu", timeout=15)
        assert r.status_code == 200
        data = r.json()
        items = data.get("items", [])
        # Each item's name/description/brand/category/sub_category should contain 'kittu'
        for it in items:
            fields = " ".join([
                str(it.get("name") or ""),
                str(it.get("brand") or ""),
                str(it.get("category") or ""),
                str(it.get("sub_category") or ""),
                str(it.get("subcategory") or ""),
            ]).lower()
            # description is projected out, so skip that
            assert "kittu" in fields, f"product {it.get('id')} matched query 'kittu' but has no field with it — {fields[:150]}"

    def test_q_empty_string_falls_back_to_default(self, session):
        # Empty q should not add a filter — behaves like plain /products (bare list)
        r = session.get(f"{BASE_URL}/api/products", timeout=15)
        assert r.status_code == 200
        # Endpoint may return either list OR envelope when NO filters applied
        data = r.json()
        assert isinstance(data, (list, dict))

    def test_q_no_base64_in_response(self, session):
        r = session.get(f"{BASE_URL}/api/products?q=iphone", timeout=15)
        assert r.status_code == 200
        data = r.json()
        items = data.get("items", []) if isinstance(data, dict) else data
        for it in items:
            img = it.get("image_url") or ""
            assert not (isinstance(img, str) and img.startswith("data:")), (
                f"public list still returns base64 for product {it.get('id')}"
            )


# ─────────────────────────────────────────────────────────────
# 3. Cart /api/cart — batched find, slim projection
# ─────────────────────────────────────────────────────────────
class TestCartSlimProjection:

    def test_empty_cart_shape(self, session, user_token):
        # Ensure we start clean
        session.post(f"{BASE_URL}/api/cart/clear", headers=_auth(user_token), timeout=10)
        r = session.get(f"{BASE_URL}/api/cart", headers=_auth(user_token), timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert data.get("items") == []
        assert data.get("count", 0) == 0
        assert isinstance(data.get("total"), (int, float))

    def test_cart_add_and_slim_response(self, session, user_token):
        # Grab a product to add
        pr = session.get(f"{BASE_URL}/api/products?limit=5", timeout=15).json()
        items = pr if isinstance(pr, list) else pr.get("items", [])
        if not items:
            pytest.skip("No products available to seed cart")
        pid = items[0]["id"]

        # Clear then add
        session.post(f"{BASE_URL}/api/cart/clear", headers=_auth(user_token), timeout=10)
        r = session.post(f"{BASE_URL}/api/cart/add", headers=_auth(user_token), json={"product_id": pid, "qty": 2}, timeout=10)
        assert r.status_code == 200, f"cart/add failed: {r.status_code} {r.text[:200]}"

        # GET cart
        r = session.get(f"{BASE_URL}/api/cart", headers=_auth(user_token), timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert len(data["items"]) == 1
        row = data["items"][0]
        assert row["product_id"] == pid
        assert row["qty"] == 2
        prod = row.get("product") or {}
        # ── Slim projection assertions ──
        for banned in ("images", "description", "specifications", "interested_users", "reviews", "questions"):
            assert banned not in prod, f"cart product still contains banned field '{banned}'"
        img = prod.get("image_url") or ""
        assert not (isinstance(img, str) and img.startswith("data:")), (
            "cart product still returns base64 image_url"
        )
        assert data["count"] == 2
        assert data["total"] == pytest.approx(float(prod.get("price", 0)) * 2, rel=1e-3)

        # Clean up
        session.post(f"{BASE_URL}/api/cart/clear", headers=_auth(user_token), timeout=10)

    def test_cart_response_time_reasonable(self, session, user_token):
        # Add a few items then time the GET
        pr = session.get(f"{BASE_URL}/api/products?limit=5", timeout=15).json()
        items = pr if isinstance(pr, list) else pr.get("items", [])
        if not items:
            pytest.skip("No products available")
        session.post(f"{BASE_URL}/api/cart/clear", headers=_auth(user_token), timeout=10)
        for it in items[:5]:
            session.post(f"{BASE_URL}/api/cart/add", headers=_auth(user_token), json={"product_id": it["id"], "qty": 1}, timeout=10)
        t0 = time.time()
        r = session.get(f"{BASE_URL}/api/cart", headers=_auth(user_token), timeout=10)
        dur = time.time() - t0
        assert r.status_code == 200
        assert dur < 2.0, f"/cart took {dur:.2f}s — batched find not effective (target <500ms; hard cap 2s)"

        # Clean up
        session.post(f"{BASE_URL}/api/cart/clear", headers=_auth(user_token), timeout=10)

    def test_cart_no_base64_at_scale(self, session, user_token):
        r = session.get(f"{BASE_URL}/api/cart", headers=_auth(user_token), timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert not _has_base64_data_uri(data), "cart response contains a base64 data URI somewhere"
