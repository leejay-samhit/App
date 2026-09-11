"""Iter 54 — Backend verification for the new /cart/adjust decrement path.

Scope (per review request):
  • POST /api/cart/adjust {delta:-1} on qty>=2 → returns {ok:true, qty:N-1}
  • POST /api/cart/adjust {delta:-1} on qty==1 → returns {ok:true, qty:0, removed:true}
  • POST /api/cart/adjust {delta:+1} on brand-new product → creates a row
  • POST /api/cart/adjust {delta:0} → returns HTTP 400

Uses the pre-existing testbuyer@test.com / Test@1234 pair from iteration 53.
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fall back to the frontend .env value expected by the environment
    BASE_URL = "https://slangcart-tracking.preview.emergentagent.com"

BUYER_EMAIL = "testbuyer@test.com"
BUYER_PASSWORD = "Test@1234"
ADMIN_EMAIL = "support@slangcart.com"
ADMIN_PASSWORD = "3)Ywxtic"


# ─── Shared fixtures ──────────────────────────────────────────────────
@pytest.fixture(scope="module")
def buyer_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": BUYER_EMAIL, "password": BUYER_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, f"buyer login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def buyer_headers(buyer_token):
    return {"Authorization": f"Bearer {buyer_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def any_product_id(admin_token):
    """Pick any published product id from the admin product list."""
    hdr = {"Authorization": f"Bearer {admin_token}"}
    r = requests.get(f"{BASE_URL}/api/admin/products?limit=5", headers=hdr, timeout=15)
    assert r.status_code == 200, f"admin/products failed: {r.status_code} {r.text}"
    body = r.json()
    items = body.get("items") if isinstance(body, dict) else body
    assert items, "no products found in admin catalog — cannot run cart tests"
    pid = items[0]["id"]
    return pid


@pytest.fixture(autouse=True)
def clean_cart(buyer_headers):
    """Reset cart before every test so behaviour is deterministic."""
    requests.post(f"{BASE_URL}/api/cart/clear", headers=buyer_headers, timeout=10)
    yield
    requests.post(f"{BASE_URL}/api/cart/clear", headers=buyer_headers, timeout=10)


# ─── /cart/adjust behavioural tests ───────────────────────────────────
class TestCartAdjust:
    """Iter 54 — validate the /cart/adjust decrement/increment contract."""

    def test_adjust_delta_zero_rejected(self, buyer_headers, any_product_id):
        r = requests.post(
            f"{BASE_URL}/api/cart/adjust",
            headers=buyer_headers,
            json={"product_id": any_product_id, "delta": 0},
            timeout=10,
        )
        assert r.status_code == 400, f"expected 400 for delta=0, got {r.status_code}: {r.text}"
        detail = (r.json().get("detail") or "").lower()
        assert "non-zero" in detail or "delta" in detail

    def test_adjust_positive_delta_creates_row(self, buyer_headers, any_product_id):
        r = requests.post(
            f"{BASE_URL}/api/cart/adjust",
            headers=buyer_headers,
            json={"product_id": any_product_id, "delta": 1},
            timeout=10,
        )
        assert r.status_code == 200, f"expected 200 for +1, got {r.status_code}: {r.text}"
        body = r.json()
        assert body.get("ok") is True
        assert body.get("qty") == 1
        # GET /cart must reflect the create.
        g = requests.get(f"{BASE_URL}/api/cart", headers=buyer_headers, timeout=10)
        assert g.status_code == 200
        assert g.json().get("count") == 1

    def test_adjust_decrement_from_multi_returns_new_qty(
        self, buyer_headers, any_product_id
    ):
        # Bring qty to 3.
        for _ in range(3):
            r = requests.post(
                f"{BASE_URL}/api/cart/adjust",
                headers=buyer_headers,
                json={"product_id": any_product_id, "delta": 1},
                timeout=10,
            )
            assert r.status_code == 200
        # Now decrement — expect qty 2, no removal flag.
        r = requests.post(
            f"{BASE_URL}/api/cart/adjust",
            headers=buyer_headers,
            json={"product_id": any_product_id, "delta": -1},
            timeout=10,
        )
        assert r.status_code == 200, f"decrement returned {r.status_code}: {r.text}"
        body = r.json()
        assert body.get("ok") is True
        assert body.get("qty") == 2, f"expected qty=2, got {body}"
        assert not body.get("removed"), "should not be removed when qty>0"
        # GET /cart double-check.
        g = requests.get(f"{BASE_URL}/api/cart", headers=buyer_headers, timeout=10)
        assert g.status_code == 200
        items = g.json().get("items") or []
        row = next((it for it in items if it["product_id"] == any_product_id), None)
        assert row is not None and row["qty"] == 2

    def test_adjust_decrement_from_one_removes_row(
        self, buyer_headers, any_product_id
    ):
        # qty=1
        r = requests.post(
            f"{BASE_URL}/api/cart/adjust",
            headers=buyer_headers,
            json={"product_id": any_product_id, "delta": 1},
            timeout=10,
        )
        assert r.status_code == 200
        # decrement → should remove
        r = requests.post(
            f"{BASE_URL}/api/cart/adjust",
            headers=buyer_headers,
            json={"product_id": any_product_id, "delta": -1},
            timeout=10,
        )
        assert r.status_code == 200, f"decrement→0 returned {r.status_code}: {r.text}"
        body = r.json()
        assert body.get("ok") is True
        assert body.get("qty") == 0
        assert body.get("removed") is True
        # GET /cart must be empty.
        g = requests.get(f"{BASE_URL}/api/cart", headers=buyer_headers, timeout=10)
        assert g.status_code == 200
        assert g.json().get("count") == 0

    def test_adjust_decrement_missing_row_rejected(
        self, buyer_headers, any_product_id
    ):
        """When no row exists, negative delta should NOT silently create."""
        r = requests.post(
            f"{BASE_URL}/api/cart/adjust",
            headers=buyer_headers,
            json={"product_id": any_product_id, "delta": -1},
            timeout=10,
        )
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
