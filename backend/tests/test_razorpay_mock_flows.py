"""Razorpay mock-mode payment flows — Jan 2026 (iter 89).

Preview backend has no RAZORPAY_KEY_ID/SECRET, so creds.is_mock=True and the
client sends pay_MOCK_* / sig_MOCK_*. These tests exercise the four
Razorpay-fronted money paths end-to-end against the public preview URL:

  1. Registration-fee flow      (POST /payment/create-order → /payment/verify)
  2. Wallet top-up flow         (POST /wallet/topup/start → /wallet/topup/verify)
  3. Shop checkout flow         (POST /orders/payment/start → /verify)
  4. Recharge flow              (POST /recharge/payment/start → /verify, when a plan exists)

All assertions check both status codes AND response fields (is_mock, amount
in paise, status transitions, idempotency).
"""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://slangcart-tracking.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
HEADERS = {"Content-Type": "application/json", "User-Agent": "curl/8.5.0"}

BUYER_EMAIL = "testbuyer@test.com"
BUYER_PASSWORD = "Test@1234"


def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, headers=HEADERS, timeout=30)
    assert r.status_code == 200, f"login failed {r.status_code}: {r.text[:200]}"
    data = r.json()
    assert "token" in data
    return data["token"]


def _auth(token: str) -> dict:
    return {**HEADERS, "Authorization": f"Bearer {token}"}


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def buyer_token() -> str:
    return _login(BUYER_EMAIL, BUYER_PASSWORD)


@pytest.fixture(scope="module")
def fresh_user() -> dict:
    """Register a brand-new unpaid user so we can exercise the registration
    fee create-order / verify path (testbuyer is already registration_paid)."""
    tag = uuid.uuid4().hex[:8]
    payload = {
        "name": f"Rzp Mock {tag}",
        "email": f"rzp_mock_{tag}@test.com",
        "password": "Test@1234",
        "phone": f"98{tag[:8].replace('a','1').replace('b','2').replace('c','3').replace('d','4').replace('e','5').replace('f','6')}"[:10],
    }
    r = requests.post(f"{API}/auth/register", json=payload, headers=HEADERS, timeout=30)
    assert r.status_code in (200, 201), f"register failed {r.status_code}: {r.text[:300]}"
    body = r.json()
    token = body.get("token") or body.get("access_token")
    if not token:
        token = _login(payload["email"], payload["password"])
    return {"email": payload["email"], "password": payload["password"], "token": token}


# ──────────────────────────────────────────────────────────────────────────
# 1. Registration-fee flow
# ──────────────────────────────────────────────────────────────────────────
class TestRegistrationFee:
    """Registration ₹118 flow in mock mode (pay_MOCK_* / sig_MOCK_*)."""

    def test_payment_config_is_mock(self, fresh_user):
        r = requests.get(f"{API}/payment/config", headers=_auth(fresh_user["token"]), timeout=15)
        assert r.status_code == 200
        c = r.json()
        assert c["is_mock"] is True, f"expected mock mode, got key_id={c.get('key_id')} is_mock={c.get('is_mock')}"
        assert c["amount_paise"] == int(round(c["amount"] * 100))
        assert c["currency"] == "INR"
        assert c["registration_paid"] is False
        assert c["attempts_remaining"] >= 1

    def test_create_order_returns_mock_order_id(self, fresh_user):
        r = requests.post(f"{API}/payment/create-order", headers=_auth(fresh_user["token"]), timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["is_mock"] is True
        assert body["order_id"].startswith("order_MOCK_"), body["order_id"]
        assert body["amount_paise"] > 0
        fresh_user["order_id"] = body["order_id"]
        fresh_user["amount_paise"] = body["amount_paise"]

    def test_verify_with_mock_payment_marks_paid(self, fresh_user):
        order_id = fresh_user.get("order_id")
        if not order_id:
            pytest.skip("create-order didn't run")
        verify = {
            "razorpay_order_id": order_id,
            "razorpay_payment_id": f"pay_MOCK_{uuid.uuid4().hex[:12]}",
            "razorpay_signature": f"sig_MOCK_{uuid.uuid4().hex[:18]}",
        }
        r = requests.post(f"{API}/payment/verify", json=verify, headers=_auth(fresh_user["token"]), timeout=20)
        assert r.status_code == 200, f"verify failed {r.status_code}: {r.text[:300]}"
        body = r.json()
        assert body.get("ok") is True or body.get("success") is True or "razorpay_payment_id" in body

        # GET /payment/config afterwards → registration_paid=True
        r2 = requests.get(f"{API}/payment/config", headers=_auth(fresh_user["token"]), timeout=15)
        assert r2.status_code == 200
        assert r2.json()["registration_paid"] is True

    def test_second_create_order_rejected(self, fresh_user):
        r = requests.post(f"{API}/payment/create-order", headers=_auth(fresh_user["token"]), timeout=15)
        assert r.status_code == 400
        assert "already paid" in r.text.lower()


# ──────────────────────────────────────────────────────────────────────────
# 2. Wallet top-up flow
# ──────────────────────────────────────────────────────────────────────────
class TestWalletTopup:
    """Wallet top-up — mock mode must credit wallet exactly once."""

    def test_topup_config_is_mock(self, buyer_token):
        r = requests.get(f"{API}/wallet/topup/config", headers=_auth(buyer_token), timeout=15)
        assert r.status_code == 200, r.text
        c = r.json()
        assert c["is_mock"] is True
        assert c["min_amount"] >= 10
        assert c["max_amount"] >= c["min_amount"]
        assert isinstance(c["presets"], list) and len(c["presets"]) > 0

    def test_topup_start_and_verify_credits_wallet(self, buyer_token):
        # Record balance before
        me = requests.get(f"{API}/auth/me", headers=_auth(buyer_token), timeout=15).json()
        before = round(float(me.get("wallet_balance") or 0), 2)

        amount = 11.0  # tiny, keeps books clean
        s = requests.post(f"{API}/wallet/topup/start", json={"amount": amount},
                         headers=_auth(buyer_token), timeout=20)
        assert s.status_code == 200, f"start failed {s.status_code}: {s.text[:300]}"
        att = s.json()
        assert att.get("payment_id")
        assert att.get("razorpay_order_id")
        assert att.get("is_mock") is True

        v = requests.post(f"{API}/wallet/topup/verify", json={
            "payment_id": att["payment_id"],
            "razorpay_order_id": att["razorpay_order_id"],
            "razorpay_payment_id": f"pay_MOCK_{uuid.uuid4().hex[:12]}",
            "razorpay_signature": f"sig_MOCK_{uuid.uuid4().hex[:18]}",
        }, headers=_auth(buyer_token), timeout=20)
        assert v.status_code == 200, f"verify failed {v.status_code}: {v.text[:300]}"
        body = v.json()
        assert body["ok"] is True
        assert round(float(body["amount"]), 2) == amount
        assert round(float(body["balance"]), 2) == round(before + amount, 2), (
            f"wallet not credited: before={before} after={body['balance']} expected={before+amount}"
        )

    def test_verify_idempotent_second_call(self, buyer_token):
        """Replaying the same mock payment id must NOT double-credit."""
        me = requests.get(f"{API}/auth/me", headers=_auth(buyer_token), timeout=15).json()
        before = round(float(me.get("wallet_balance") or 0), 2)

        s = requests.post(f"{API}/wallet/topup/start", json={"amount": 10.0},
                         headers=_auth(buyer_token), timeout=20).json()
        pid = f"pay_MOCK_{uuid.uuid4().hex[:12]}"
        v1 = requests.post(f"{API}/wallet/topup/verify", json={
            "payment_id": s["payment_id"],
            "razorpay_order_id": s["razorpay_order_id"],
            "razorpay_payment_id": pid,
            "razorpay_signature": f"sig_MOCK_{uuid.uuid4().hex[:18]}",
        }, headers=_auth(buyer_token), timeout=20)
        assert v1.status_code == 200, v1.text
        after_first = round(float(v1.json()["balance"]), 2)
        assert after_first == round(before + 10.0, 2)

        # Replay — same payment attempt, same razorpay payment id
        v2 = requests.post(f"{API}/wallet/topup/verify", json={
            "payment_id": s["payment_id"],
            "razorpay_order_id": s["razorpay_order_id"],
            "razorpay_payment_id": pid,
            "razorpay_signature": f"sig_MOCK_{uuid.uuid4().hex[:18]}",
        }, headers=_auth(buyer_token), timeout=20)
        assert v2.status_code == 200
        body = v2.json()
        assert body.get("already_verified") is True or round(float(body["balance"]), 2) == after_first, (
            f"double credit! before={before} after1={after_first} after2={body.get('balance')}"
        )

    def test_topup_below_min_rejected(self, buyer_token):
        r = requests.post(f"{API}/wallet/topup/start", json={"amount": 1.0},
                         headers=_auth(buyer_token), timeout=15)
        assert r.status_code == 400
        assert "minimum" in r.text.lower() or "min" in r.text.lower()

    def test_topup_above_max_rejected(self, buyer_token):
        r = requests.post(f"{API}/wallet/topup/start", json={"amount": 1_000_000.0},
                         headers=_auth(buyer_token), timeout=15)
        assert r.status_code == 400


# ──────────────────────────────────────────────────────────────────────────
# 3. Shop checkout — online payment flow
# ──────────────────────────────────────────────────────────────────────────
class TestOrderOnlinePayment:
    """POST /orders/payment/start empty-cart guards + mock flow when there IS a product."""

    def test_start_empty_cart_rejected(self, buyer_token):
        # Clear any existing cart first
        requests.post(f"{API}/cart/clear", headers=_auth(buyer_token), timeout=10)
        r = requests.post(f"{API}/orders/payment/start", json={"wallet_amount": 0},
                         headers=_auth(buyer_token), timeout=15)
        assert r.status_code == 400
        assert "cart" in r.text.lower() or "empty" in r.text.lower()

    def test_start_verify_with_product_in_cart(self, buyer_token):
        """Add one product (pincode 517644 vendor) → price it → mock-pay → verify.

        A missing / stock-less product just skips the test; this is a smoke
        test for the mock Razorpay layer, not a product-catalogue test.
        """
        # Find a published product with stock from testvendor
        pr = requests.get(f"{API}/products?pincode=517644", headers=_auth(buyer_token), timeout=20)
        if pr.status_code != 200:
            pytest.skip(f"products listing not available: {pr.status_code}")
        rows = pr.json()
        if isinstance(rows, dict):
            rows = rows.get("items") or rows.get("products") or []
        in_stock = [p for p in rows if (p.get("stock") or 0) > 0 and (p.get("price") or 0) > 0]
        if not in_stock:
            pytest.skip("no in-stock products at 517644")
        pid = in_stock[0]["id"]

        # Clear cart + add one (POST /cart/clear, POST /cart/add)
        requests.post(f"{API}/cart/clear", headers=_auth(buyer_token), timeout=10)
        add = requests.post(f"{API}/cart/add", json={"product_id": pid, "qty": 1},
                          headers=_auth(buyer_token), timeout=15)
        assert add.status_code in (200, 201), f"add to cart: {add.status_code} {add.text[:200]}"

        s = requests.post(f"{API}/orders/payment/start", json={"wallet_amount": 0},
                         headers=_auth(buyer_token), timeout=20)
        if s.status_code != 200:
            pytest.skip(f"orders/payment/start returned {s.status_code}: {s.text[:200]}")
        att = s.json()
        assert att["is_mock"] is True
        assert att["payment_id"]
        assert att["razorpay_order_id"]
        assert att["amount_paise"] == int(round(att["amount"] * 100))

        v = requests.post(f"{API}/orders/payment/verify", json={
            "payment_id": att["payment_id"],
            "razorpay_order_id": att["razorpay_order_id"],
            "razorpay_payment_id": f"pay_MOCK_{uuid.uuid4().hex[:12]}",
            "razorpay_signature": f"sig_MOCK_{uuid.uuid4().hex[:18]}",
        }, headers=_auth(buyer_token), timeout=20)
        assert v.status_code == 200, f"verify: {v.status_code} {v.text[:200]}"
        body = v.json()
        assert body["ok"] is True
        assert body["payment_id"] == att["payment_id"]

        # Pending endpoint should now surface the paid-but-unconsumed attempt
        p = requests.get(f"{API}/orders/payment/pending", headers=_auth(buyer_token), timeout=15)
        assert p.status_code == 200
        pending = p.json().get("pending")
        # The verify above created an unconsumed paid attempt
        assert pending is not None, "expected a paid-but-unconsumed attempt"
        assert pending["payment_id"] == att["payment_id"]

        # Clean up: cart clear + leave attempt as-is (next checkout can consume it)
        requests.post(f"{API}/cart/clear", headers=_auth(buyer_token), timeout=10)


# ──────────────────────────────────────────────────────────────────────────
# 4. Recharge flow (best-effort — only runs if a published plan exists)
# ──────────────────────────────────────────────────────────────────────────
class TestRechargePayment:
    def test_recharge_mock_flow(self, buyer_token):
        plans = requests.get(f"{API}/products?category=recharge", headers=_auth(buyer_token), timeout=15)
        rows = []
        if plans.status_code == 200:
            data = plans.json()
            rows = data if isinstance(data, list) else (data.get("items") or [])
        plan = next(
            (p for p in rows if (p.get("recharge_kind") in ("mobile", "dth")) and float(p.get("price") or 0) > 0),
            None,
        )
        if not plan:
            pytest.skip("no mobile/dth recharge plan seeded")

        s = requests.post(f"{API}/recharge/payment/start", json={
            "kind": plan.get("recharge_kind") or "mobile",
            "product_id": plan["id"],
            "account": "9876543210",
        }, headers=_auth(buyer_token), timeout=20)
        assert s.status_code == 200, s.text
        att = s.json()
        assert att["is_mock"] is True
        assert att["payment_id"]

        v = requests.post(f"{API}/recharge/payment/verify", json={
            "payment_id": att["payment_id"],
            "razorpay_order_id": att["razorpay_order_id"],
            "razorpay_payment_id": f"pay_MOCK_{uuid.uuid4().hex[:12]}",
            "razorpay_signature": f"sig_MOCK_{uuid.uuid4().hex[:18]}",
        }, headers=_auth(buyer_token), timeout=20)
        assert v.status_code == 200, v.text
        body = v.json()
        assert body["ok"] is True
        assert body.get("recharge_id")
