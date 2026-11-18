"""
UPDATE 2 — Smart Product-Master Autocomplete (Jan 2026)

Tests GET /api/products/master/search endpoint:
  1. Auth-gated (401 without token)
  2. Returns 200 + items[] for authenticated users
  3. Query min_length=1 works; missing query -> 422
  4. Empty result set returns count=0, items=[], no crash
  5. De-duplication by (name+brand) — identical rows collapsed to 1
  6. Ranking — prefix match ranks higher than substring match
  7. own_id filter — searching vendor should NOT see their own catalog rows
  8. external_available field present and False (Option A only)
  9. limit param respected (limit=3 returns at most 3)
 10. limit clamping/rejection — limit=100 or limit=0 should be rejected/clamped
"""

import os
import uuid
import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")

ALICE_EMAIL = "test_alice_73dc7f@test.com"
ALICE_PASSWORD = "Passw0rd!"
BOB_EMAIL = "test_bob_d96d89@test.com"
BOB_PASSWORD = "Passw0rd!"

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "support@networkrupay.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", os.environ.get("ADMIN_PASSWORD", ""))


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
def bob_token(http):
    return _login(http, BOB_EMAIL, BOB_PASSWORD)


@pytest.fixture(scope="module")
def admin_token(http):
    return _login(http, ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def alice_is_approved(http, alice_token):
    r = http.get(f"{BASE_URL}/api/vendor/me/status", headers=_bearer(alice_token))
    assert r.status_code == 200, r.text
    body = r.json()
    if not (body.get("is_vendor") and body.get("vendor_status") == "approved"):
        pytest.skip(
            f"Alice not approved vendor (is_vendor={body.get('is_vendor')}, "
            f"vendor_status={body.get('vendor_status')})."
        )
    return True


@pytest.fixture(scope="module")
def alice_products(http, alice_token, alice_is_approved):
    """Seed a unique product owned by Alice for own_id-filter test.
    Also seed a couple of extra products to test ranking/dedupe.
    """
    unique_tag = f"MasterTestZZZ_{uuid.uuid4().hex[:6]}"
    created = []

    # 1. Own product (should be filtered out when Alice searches)
    r = http.post(
        f"{BASE_URL}/api/vendor/me/products",
        json={
            "name": f"{unique_tag} Widget",
            "price": 999.0,
            "image_url": "https://example.com/widget.png",
            "brand": "WidgetBrand",
            "description": "TEST product for master search",
            "category": "Electronics",
        },
        headers=_bearer(alice_token),
        timeout=30,
    )
    assert r.status_code == 200, r.text
    own_id = r.json()["id"]
    created.append(own_id)

    yield {"unique_tag": unique_tag, "own_id": own_id}

    # teardown
    for pid in created:
        try:
            http.delete(
                f"{BASE_URL}/api/vendor/me/products/{pid}",
                headers=_bearer(alice_token),
                timeout=15,
            )
        except Exception:
            pass


@pytest.fixture(scope="module")
def bob_products(http, bob_token, alice_products):
    """Seed products owned by Bob so Alice can find them in master search.

    - One product whose name STARTS with the unique tag (prefix match, high rank).
    - One product where the tag is a middle-word (substring, lower rank).
    - Two identical duplicate rows to prove de-dupe collapses them.
    """
    tag = alice_products["unique_tag"]
    created = []

    def _mk(name: str, brand: str = "TestBrandX"):
        r = http.post(
            f"{BASE_URL}/api/vendor/me/products",
            json={
                "name": name,
                "price": 500.0,
                "image_url": "https://example.com/x.png",
                "brand": brand,
                "description": "TEST bob product for master search",
                "category": "Electronics",
            },
            headers=_bearer(bob_token),
            timeout=30,
        )
        assert r.status_code == 200, r.text
        return r.json()["id"]

    prefix_id = _mk(f"{tag} PrefixItem")           # prefix match on tag
    substring_id = _mk(f"Prefix {tag} Middle")     # tag in middle (substring)
    dup_name = f"{tag} DupProduct"
    dup_a = _mk(dup_name, brand="DupBrand")
    dup_b = _mk(dup_name, brand="DupBrand")        # exact duplicate

    created.extend([prefix_id, substring_id, dup_a, dup_b])

    yield {
        "tag": tag,
        "prefix_id": prefix_id,
        "substring_id": substring_id,
        "dup_ids": [dup_a, dup_b],
        "dup_name": dup_name,
    }

    for pid in created:
        try:
            http.delete(
                f"{BASE_URL}/api/vendor/me/products/{pid}",
                headers=_bearer(bob_token),
                timeout=15,
            )
        except Exception:
            pass


# ---------------- 1. Auth-gated ----------------

class TestAuthGating:

    def test_no_token_returns_401(self, http):
        r = http.get(f"{BASE_URL}/api/products/master/search?q=phone", timeout=30)
        assert r.status_code == 401, f"expected 401, got {r.status_code} {r.text}"

    def test_bad_token_returns_401(self, http):
        r = http.get(
            f"{BASE_URL}/api/products/master/search?q=phone",
            headers={"Authorization": "Bearer notarealtoken"},
            timeout=30,
        )
        assert r.status_code == 401, f"expected 401, got {r.status_code} {r.text}"


# ---------------- 2. Authenticated 200 + items[] ----------------

class TestAuthenticatedReturnsItems:

    def test_returns_200_with_items_array(self, http, alice_token):
        r = http.get(
            f"{BASE_URL}/api/products/master/search?q=phone",
            headers=_bearer(alice_token),
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "query" in body and body["query"] == "phone"
        assert "count" in body and isinstance(body["count"], int)
        assert "items" in body and isinstance(body["items"], list)
        assert body["count"] == len(body["items"])


# ---------------- 3. Query validation ----------------

class TestQueryValidation:

    def test_missing_q_returns_422(self, http, alice_token):
        r = http.get(
            f"{BASE_URL}/api/products/master/search",
            headers=_bearer(alice_token),
            timeout=30,
        )
        assert r.status_code in (400, 422), (
            f"missing q must be rejected, got {r.status_code} {r.text}"
        )

    def test_empty_q_returns_422(self, http, alice_token):
        r = http.get(
            f"{BASE_URL}/api/products/master/search?q=",
            headers=_bearer(alice_token),
            timeout=30,
        )
        # min_length=1 → FastAPI validation raises 422
        assert r.status_code in (400, 422), (
            f"empty q must be rejected, got {r.status_code} {r.text}"
        )

    def test_single_char_q_works(self, http, alice_token):
        r = http.get(
            f"{BASE_URL}/api/products/master/search?q=a",
            headers=_bearer(alice_token),
            timeout=30,
        )
        assert r.status_code == 200, r.text


# ---------------- 4. Empty result set ----------------

class TestEmptyResultSet:

    def test_unlikely_query_returns_zero(self, http, alice_token):
        random_q = f"XYZZ_{uuid.uuid4().hex}"
        r = http.get(
            f"{BASE_URL}/api/products/master/search?q={random_q}",
            headers=_bearer(alice_token),
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] == 0
        assert body["items"] == []
        assert body.get("external_available") is False


# ---------------- 5. external_available field ----------------

class TestExternalAvailableField:

    def test_field_present_and_false(self, http, alice_token):
        r = http.get(
            f"{BASE_URL}/api/products/master/search?q=phone",
            headers=_bearer(alice_token),
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "external_available" in body, "external_available must be in response"
        assert body["external_available"] is False, (
            f"external_available must be False (Option A), got {body['external_available']!r}"
        )


# ---------------- 6. own_id filter (main functional test) ----------------

class TestOwnProductsExcluded:

    def test_alice_does_not_see_own_products(
        self, http, alice_token, alice_products
    ):
        tag = alice_products["unique_tag"]
        r = http.get(
            f"{BASE_URL}/api/products/master/search?q={tag}",
            headers=_bearer(alice_token),
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Alice should NOT see her own product
        names = [it.get("name", "") for it in body["items"]]
        assert body["count"] == 0, (
            f"Alice must not see her own product '{tag} Widget' in master search, "
            f"got count={body['count']}, names={names}"
        )
        assert body["items"] == []

    def test_bob_sees_alices_product(
        self, http, bob_token, alice_products
    ):
        tag = alice_products["unique_tag"]
        r = http.get(
            f"{BASE_URL}/api/products/master/search?q={tag}",
            headers=_bearer(bob_token),
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Bob should see Alice's product (he isn't the owner)
        assert body["count"] >= 1, (
            f"Bob should see Alice's '{tag} Widget' product, got {body}"
        )
        names = [it.get("name", "") for it in body["items"]]
        assert any(tag in n for n in names), (
            f"Bob's result should include a name containing '{tag}', got {names}"
        )


# ---------------- 7. De-duplication ----------------

class TestDeduplication:

    def test_identical_name_brand_collapsed(
        self, http, alice_token, alice_products, bob_products
    ):
        """Bob created 2 identical rows with name f'{tag} DupProduct' + brand DupBrand.
        Alice searches — she should see exactly ONE of them (dedup by name+brand)."""
        dup_name = bob_products["dup_name"]
        r = http.get(
            f"{BASE_URL}/api/products/master/search?q={dup_name}&limit=25",
            headers=_bearer(alice_token),
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        matches = [
            it for it in body["items"]
            if it.get("name") == dup_name and (it.get("brand") == "DupBrand" or it.get("attrs_brand") == "DupBrand")
        ]
        assert len(matches) == 1, (
            f"Expected exactly 1 deduped row for '{dup_name}' + DupBrand, "
            f"got {len(matches)}: {matches}"
        )


# ---------------- 8. Ranking (prefix > substring) ----------------

class TestRanking:

    def test_prefix_match_ranks_above_substring(
        self, http, alice_token, alice_products, bob_products
    ):
        tag = bob_products["tag"]
        r = http.get(
            f"{BASE_URL}/api/products/master/search?q={tag}&limit=25",
            headers=_bearer(alice_token),
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        names = [it.get("name", "") for it in body["items"]]
        prefix_name = f"{tag} PrefixItem"
        substring_name = f"Prefix {tag} Middle"
        assert prefix_name in names, f"prefix product must appear: {names}"
        assert substring_name in names, f"substring product must appear: {names}"
        # prefix must rank above substring
        assert names.index(prefix_name) < names.index(substring_name), (
            f"'{prefix_name}' must rank above '{substring_name}', order={names}"
        )


# ---------------- 9. Limit param respected ----------------

class TestLimitParam:

    def test_limit_3_returns_at_most_3(
        self, http, alice_token, alice_products, bob_products
    ):
        tag = bob_products["tag"]
        r = http.get(
            f"{BASE_URL}/api/products/master/search?q={tag}&limit=3",
            headers=_bearer(alice_token),
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] <= 3, f"limit=3 not respected, got count={body['count']}"
        assert len(body["items"]) <= 3


# ---------------- 10. Limit clamp/reject ----------------

class TestLimitClamp:

    def test_limit_100_rejected_or_clamped(self, http, alice_token):
        r = http.get(
            f"{BASE_URL}/api/products/master/search?q=phone&limit=100",
            headers=_bearer(alice_token),
            timeout=30,
        )
        # Query() defines le=25 → FastAPI raises 422
        if r.status_code == 200:
            body = r.json()
            assert body["count"] <= 25, (
                f"limit=100 must be clamped to 25, got {body['count']}"
            )
        else:
            assert r.status_code in (400, 422), (
                f"limit=100 must be rejected or clamped, got {r.status_code} {r.text}"
            )

    def test_limit_0_rejected(self, http, alice_token):
        r = http.get(
            f"{BASE_URL}/api/products/master/search?q=phone&limit=0",
            headers=_bearer(alice_token),
            timeout=30,
        )
        # Query() defines ge=1 → FastAPI raises 422 (must not crash / not 500)
        assert r.status_code in (400, 422), (
            f"limit=0 must be rejected, got {r.status_code} {r.text}"
        )
        assert r.status_code != 500


# ---------------- 11. Payload shape sanity ----------------

class TestPayloadShape:

    def test_item_has_expected_fields(
        self, http, alice_token, alice_products, bob_products
    ):
        tag = bob_products["tag"]
        r = http.get(
            f"{BASE_URL}/api/products/master/search?q={tag}",
            headers=_bearer(alice_token),
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] >= 1
        item = body["items"][0]
        expected_keys = {
            "source", "id", "name", "brand", "image_url", "images",
            "price", "category", "description", "sub_features",
            "attrs_brand", "attrs_os", "attrs_ram", "attrs_cpu_model",
            "attrs_cpu_speed", "attrs_storage", "extra_attrs",
            "spec_tabs", "whats_in_box",
        }
        missing = expected_keys - set(item.keys())
        assert not missing, f"item missing expected fields: {missing}"
        assert item["source"] == "local"
