"""Iteration 81 — Phase-1 financial gaps testing.

Focus on flows the main verify_phase1_money.py could NOT cover:
  1. Role-based access on reconciliation endpoints (super_admin/finance allowed;
     manager/support/buyer blocked).
  2. Note-length guard (< 3 chars → 400) on resolve.
  3. Admin withdrawal REJECT returning money to vendor_earnings (not wallet_balance).
  4. Idempotency of admin reject (double-reject should not double-credit).
  5. Reconciliation open_total present + shape.

Runs against the public EXPO_BACKEND_URL.
"""
import os
import uuid

import pytest
import requests

BASE_URL = os.environ.get("EXPO_BACKEND_URL", "https://slangcart-tracking.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
UA = {"User-Agent": "curl/8.5.0"}

ADMIN = ("support@slangcart.com", "3)Ywxtic")
BUYER = ("testbuyer@test.com", "Test@1234")
VENDOR = ("testvendor@test.com", "Test@1234")

ADDR = {"name": "T", "phone": "9999999999", "line1": "1 Main St", "city": "Srikalahasti",
        "state": "AP", "pincode": "517644", "latitude": 13.7497, "longitude": 79.7036}


def _login(email, password):
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": password},
                      headers={**UA, "Content-Type": "application/json"},
                      timeout=30)
    r.raise_for_status()
    return r.json()["token"]


def _h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json", **UA}


@pytest.fixture(scope="module")
def admin_h():
    return _h(_login(*ADMIN))


@pytest.fixture(scope="module")
def buyer_h():
    return _h(_login(*BUYER))


@pytest.fixture(scope="module")
def vendor_h():
    return _h(_login(*VENDOR))


# ── Reconciliation endpoints ────────────────────────────────────────────

class TestReconciliationRBAC:
    def test_admin_can_list(self, admin_h):
        r = requests.get(f"{API}/admin/finance/reconciliations", headers=admin_h, timeout=30)
        assert r.status_code == 200, r.text[:200]
        data = r.json()
        assert "reconciliations" in data
        assert "open_total" in data
        assert isinstance(data["reconciliations"], list)

    def test_buyer_forbidden(self, buyer_h):
        r = requests.get(f"{API}/admin/finance/reconciliations", headers=buyer_h, timeout=30)
        assert r.status_code in (401, 403), f"expected 401/403 got {r.status_code}: {r.text[:200]}"

    def test_vendor_forbidden(self, vendor_h):
        r = requests.get(f"{API}/admin/finance/reconciliations", headers=vendor_h, timeout=30)
        assert r.status_code in (401, 403), f"expected 401/403 got {r.status_code}: {r.text[:200]}"

    def test_unauthenticated_forbidden(self):
        r = requests.get(f"{API}/admin/finance/reconciliations", headers=UA, timeout=30)
        assert r.status_code in (401, 403), r.status_code


class TestReconciliationResolveNote:
    def test_short_note_rejected(self, admin_h):
        # Any non-existent payment id — we just want the payload validation to fire before the 404.
        fake_pid = f"PAY_TEST_{uuid.uuid4().hex[:6]}"
        r = requests.post(f"{API}/admin/finance/reconciliations/{fake_pid}/resolve",
                          json={"action": "refund_to_wallet", "note": "hi"},
                          headers=admin_h, timeout=30)
        assert r.status_code == 400, f"expected 400 got {r.status_code}: {r.text[:200]}"
        assert "note" in r.text.lower(), r.text[:200]

    def test_empty_note_rejected(self, admin_h):
        fake_pid = f"PAY_TEST_{uuid.uuid4().hex[:6]}"
        r = requests.post(f"{API}/admin/finance/reconciliations/{fake_pid}/resolve",
                          json={"action": "close", "note": "  "},
                          headers=admin_h, timeout=30)
        assert r.status_code == 400, r.text[:200]

    def test_invalid_action_rejected(self, admin_h):
        fake_pid = f"PAY_TEST_{uuid.uuid4().hex[:6]}"
        r = requests.post(f"{API}/admin/finance/reconciliations/{fake_pid}/resolve",
                          json={"action": "steal_money", "note": "trying to break"},
                          headers=admin_h, timeout=30)
        assert r.status_code == 400, r.text[:200]

    def test_buyer_cannot_resolve(self, buyer_h):
        fake_pid = f"PAY_TEST_{uuid.uuid4().hex[:6]}"
        r = requests.post(f"{API}/admin/finance/reconciliations/{fake_pid}/resolve",
                          json={"action": "refund_to_wallet", "note": "a buyer trying"},
                          headers=buyer_h, timeout=30)
        assert r.status_code in (401, 403), r.status_code


# ── Vendor wallet visibility ────────────────────────────────────────────

class TestVendorWalletVisibility:
    def test_seller_sees_wallet_view(self, vendor_h):
        r = requests.get(f"{API}/vendor/me/wallet", headers=vendor_h, timeout=30)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        for k in ("available_balance", "ledger_credits", "ledger_debits",
                  "ledger_balance", "unledgered_difference", "in_sync",
                  "pending_withdrawals", "min_withdrawal", "can_withdraw"):
            assert k in d, f"vendor wallet missing key: {k}"
        assert d["min_withdrawal"] == 5000.0

    def test_buyer_denied(self, buyer_h):
        r = requests.get(f"{API}/vendor/me/wallet", headers=buyer_h, timeout=30)
        assert r.status_code == 403, f"expected 403 got {r.status_code}"


# ── Withdrawal flow — REJECT returns money to vendor_earnings ───────────

class TestAdminWithdrawalReject:
    """End-to-end: seed vendor_earnings via login → request withdrawal →
    reject → verify money returned to vendor_earnings (not wallet_balance)."""

    def _wallet_state(self, admin_h, email):
        # Use admin GET user endpoint if available; otherwise resort to vendor summary.
        r = requests.get(f"{API}/vendor/me/wallet", headers=self._vendor_h, timeout=30)
        return r.json()

    def test_reject_flow(self, admin_h, vendor_h):
        self._vendor_h = vendor_h
        # baseline
        r0 = requests.get(f"{API}/vendor/me/wallet", headers=vendor_h, timeout=30)
        assert r0.status_code == 200
        v0 = r0.json()
        available_before = float(v0["available_balance"])
        if available_before < 5000:
            pytest.skip(f"Vendor available balance {available_before} < 5000, cannot exercise flow")

        # request a valid withdrawal
        wr = requests.post(f"{API}/withdrawals",
                           json={"amount": 5000},
                           headers=vendor_h, timeout=30)
        if wr.status_code == 400 and "already have a settlement" in wr.text:
            pytest.skip("A withdrawal is already in progress; cannot cleanly exercise reject flow")
        assert wr.status_code == 200, wr.text[:300]
        wid = wr.json()["id"]

        # after request: money should be held (available drops by ~5000)
        r1 = requests.get(f"{API}/vendor/me/wallet", headers=vendor_h, timeout=30)
        v1 = r1.json()
        held_delta = round(available_before - float(v1["available_balance"]), 2)
        assert abs(held_delta - 5000.0) < 0.01, f"expected -5000 held; got delta={held_delta}"
        # wallet_field must be vendor_earnings for a seller
        # (peek via the admin approve list not exposed here, so rely on RETURN behaviour)

        # admin rejects
        rej = requests.post(f"{API}/admin/withdrawals/{wid}/reject",
                            json={"reason": "iter81 gap test reject"},
                            headers=admin_h, timeout=30)
        assert rej.status_code == 200, rej.text[:300]

        # money must be back in vendor_earnings (available_balance restored)
        r2 = requests.get(f"{API}/vendor/me/wallet", headers=vendor_h, timeout=30)
        v2 = r2.json()
        restored = round(float(v2["available_balance"]) - float(v1["available_balance"]), 2)
        assert abs(restored - 5000.0) < 0.01, (
            f"expected +5000 restored to vendor_earnings; got delta={restored}"
        )
        # exact idempotency — a second reject on an already-rejected withdrawal must fail
        rej2 = requests.post(f"{API}/admin/withdrawals/{wid}/reject",
                             json={"reason": "double-tap"},
                             headers=admin_h, timeout=30)
        assert rej2.status_code == 400, f"double reject should 400; got {rej2.status_code}"

        # balance must be identical (no second credit)
        r3 = requests.get(f"{API}/vendor/me/wallet", headers=vendor_h, timeout=30)
        v3 = r3.json()
        assert v3["available_balance"] == v2["available_balance"], (
            f"double-reject should not credit again: {v2['available_balance']} -> {v3['available_balance']}"
        )


# ── Withdrawal RBAC / limits ────────────────────────────────────────────

class TestWithdrawalRules:
    def test_below_minimum_rejected(self, vendor_h):
        r = requests.post(f"{API}/withdrawals", json={"amount": 1000},
                          headers=vendor_h, timeout=30)
        assert r.status_code == 400
        assert "5000" in r.text

    def test_buyer_role_blocked(self, buyer_h):
        r = requests.post(f"{API}/withdrawals", json={"amount": 5000},
                          headers=buyer_h, timeout=30)
        assert r.status_code in (400, 403), r.status_code


# ── Frontend must be able to fetch backend-driven payment total ─────────

class TestPaymentStartShape:
    def test_start_returns_amount_shape(self, buyer_h):
        # clear cart, add a product from the vendor, hit /payment/start
        requests.post(f"{API}/cart/clear", headers=buyer_h, timeout=15)
        prods = requests.get(f"{API}/products?limit=5", headers=buyer_h, timeout=15).json()
        items = prods.get("products") or prods.get("items") or prods
        if not items:
            pytest.skip("No products visible to buyer to exercise /payment/start")
        pid = items[0]["id"]
        requests.post(f"{API}/cart/add",
                      json={"product_id": pid, "qty": 1},
                      headers=buyer_h, timeout=15)
        r = requests.post(f"{API}/orders/payment/start",
                          json={"wallet_amount": 0},
                          headers=buyer_h, timeout=30)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        for k in ("amount", "goods_total", "delivery_total", "payment_id", "razorpay_order_id"):
            assert k in d, f"payment/start missing {k}: {list(d.keys())}"
        assert d["amount"] == round(float(d["goods_total"]) + float(d["delivery_total"]), 2)
