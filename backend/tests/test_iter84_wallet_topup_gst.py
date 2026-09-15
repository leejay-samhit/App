"""Iteration 84 — extra checks for wallet-topup safety + GST-inclusive product pricing."""
import os
import uuid
import pytest
import requests

BASE = os.environ["EXPO_BACKEND_URL"].rstrip("/") + "/api"
UA = {"User-Agent": "curl/8.5.0", "Content-Type": "application/json"}
BUYER = ("testbuyer@test.com", "Test@1234")
VENDOR = ("testvendor@test.com", "Test@1234")


def _login(email, pw):
    r = requests.post(f"{BASE}/auth/login",
                      json={"email": email, "password": pw}, headers=UA, timeout=30)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['token']}", **UA}


@pytest.fixture(scope="module")
def buyer_h():
    return _login(*BUYER)


@pytest.fixture(scope="module")
def vendor_h():
    return _login(*VENDOR)


# --- BUG 1 · cross-user safety ---------------------------------------------
class TestTopupCrossUser:
    def test_body_amount_is_ignored_server_prices_it(self, buyer_h):
        s = requests.post(f"{BASE}/wallet/topup/start", json={"amount": 200},
                          headers=buyer_h, timeout=30).json()
        v = requests.post(f"{BASE}/wallet/topup/verify", json={
            "payment_id": s["payment_id"], "razorpay_order_id": s["razorpay_order_id"],
            "razorpay_payment_id": f"pay_MOCK_{uuid.uuid4().hex[:10]}",
            "razorpay_signature": "sig",
            # NOTE: no 'amount' key exists in the pydantic model — server takes
            # from OUR stored attempt. Verify that.
        }, headers=buyer_h, timeout=30)
        assert v.status_code == 200, v.text
        assert v.json()["amount"] == 200.0

    def test_other_user_cannot_verify_my_attempt(self, buyer_h, vendor_h):
        s = requests.post(f"{BASE}/wallet/topup/start", json={"amount": 111},
                          headers=buyer_h, timeout=30).json()
        v = requests.post(f"{BASE}/wallet/topup/verify", json={
            "payment_id": s["payment_id"], "razorpay_order_id": s["razorpay_order_id"],
            "razorpay_payment_id": f"pay_MOCK_{uuid.uuid4().hex[:10]}",
        }, headers=vendor_h, timeout=30)
        assert v.status_code == 404, v.text

    def test_other_user_cannot_recover_my_attempt(self, buyer_h, vendor_h):
        s = requests.post(f"{BASE}/wallet/topup/start", json={"amount": 123},
                          headers=buyer_h, timeout=30).json()
        r = requests.post(f"{BASE}/wallet/topup/recover",
                          json={"payment_id": s["payment_id"]},
                          headers=vendor_h, timeout=30)
        assert r.status_code == 404, r.text


# --- BUG 2 · GST compute defaults to inclusive -----------------------------
class TestGstCompute:
    def test_inclusive_default(self, vendor_h):
        r = requests.get(f"{BASE}/gst/compute?base=1180&pct=18",
                         headers=vendor_h, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["final_amount"] == 1180.0
        assert d["base_amount"] == 1000.0
        assert d["cgst_amount"] == 90.0
        assert d["sgst_amount"] == 90.0
        assert d["total_gst"] == 180.0

    def test_exclusive_still_available(self, vendor_h):
        r = requests.get(f"{BASE}/gst/compute?base=1180&pct=18&inclusive=false",
                         headers=vendor_h, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["base_amount"] == 1180.0
        assert d["final_amount"] == 1392.4

    def test_buyer_forbidden(self, buyer_h):
        # Sep-2026: gst/compute is vendor/admin-only — buyers never price.
        r = requests.get(f"{BASE}/gst/compute?base=1180&pct=18",
                         headers=buyer_h, timeout=30)
        assert r.status_code == 403


# --- BUG 2 · Public product hides vendor cost + inclusive breakdown --------
class TestPublicProductPricing:
    # NOTE: This case is comprehensively covered by
    # tests/verify_phase2_returns.py section [8] (public /products/{id}
    # excludes purchase_price + gst_breakdown.final_amount == 1180). Skipping
    # here so we don't re-create a published product just to re-check.
    @pytest.mark.skip("covered by verify_phase2_returns.py section [8]")
    def test_public_product_hides_cost_and_totals_include_gst(self, vendor_h):
        pass


# --- BUG 2 · Cashback modes: pct wins over flat, potential stock profit -----
class TestCashbackModes:
    def _create(self, vendor_h, **over):
        body = {"name": f"Iter84 cb {uuid.uuid4().hex[:6]}", "price": 500,
                "purchase_price": 400, "purchase_gst_pct": 0,
                "selling_gst_pct": 0, "image_url": "", "stock": 10,
                "category": "General", "is_published": True,
                "cashback_pct": 0, "free_delivery": False}
        body.update(over)
        return requests.post(f"{BASE}/vendor/me/products",
                             json=body, headers=vendor_h, timeout=30).json()

    def test_pct_cashback(self, vendor_h):
        p = self._create(vendor_h, cashback_pct=5)
        pr = requests.get(f"{BASE}/vendor/me/products/{p['id']}/pricing",
                          headers=vendor_h, timeout=30).json()
        assert pr["cashback"]["mode"] == "percent"
        assert pr["cashback"]["amount"] == 25.0
        assert pr["gross_profit_per_unit"] == 100.0
        assert pr["profit_per_unit"] == 75.0
        assert pr["potential_stock_profit"] == round(75.0 * pr["stock"], 2)

    def test_flat_cashback(self, vendor_h):
        p = self._create(vendor_h, cashback_pct=0, cashback_flat=25)
        pr = requests.get(f"{BASE}/vendor/me/products/{p['id']}/pricing",
                          headers=vendor_h, timeout=30).json()
        assert pr["cashback"]["mode"] == "flat"
        assert pr["cashback"]["amount"] == 25.0
        assert pr["profit_per_unit"] == 75.0

    def test_pct_wins_over_flat(self, vendor_h):
        p = self._create(vendor_h, cashback_pct=5, cashback_flat=25)
        pr = requests.get(f"{BASE}/vendor/me/products/{p['id']}/pricing",
                          headers=vendor_h, timeout=30).json()
        assert pr["cashback"]["mode"] == "percent"
        # Must NOT be 50 (percent wins, never stacks)
        assert pr["cashback"]["amount"] == 25.0
        assert pr["profit_per_unit"] == 75.0
