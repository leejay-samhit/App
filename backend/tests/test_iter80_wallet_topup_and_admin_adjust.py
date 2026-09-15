"""Iteration 80 — wallet top-up (₹5,000 cap) + admin wallet adjust funded from
Company Net Worth. Two brand-new user-reported bugs.

Env:
  * EXPO_PUBLIC_BACKEND_URL   — public base URL (used as EXPO_BACKEND_URL fallback)
"""
import os
import time
import uuid
import requests
import pytest

BASE = (os.environ.get("EXPO_BACKEND_URL") or os.environ["EXPO_PUBLIC_BACKEND_URL"]).rstrip("/")

ADMIN = ("support@slangcart.com", "3)Ywxtic")
VENDOR = ("testvendor@test.com", "Test@1234")
BUYER = ("testbuyer@test.com", "Test@1234")


def _login(email: str, password: str) -> str:
    r = requests.post(f"{BASE}/api/auth/login", json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, f"no token in login response: {r.text[:200]}"
    return tok


def _me(token: str) -> dict:
    r = requests.get(f"{BASE}/api/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def buyer_token():
    return _login(*BUYER)


@pytest.fixture(scope="module")
def vendor_token():
    return _login(*VENDOR)


@pytest.fixture(scope="module")
def admin_token():
    return _login(*ADMIN)


# ─────────────────────── BUG 1a — /wallet/topup/* ───────────────────────

class TestWalletTopup:
    def test_config_shape(self, buyer_token):
        r = requests.get(f"{BASE}/api/wallet/topup/config", headers={"Authorization": f"Bearer {buyer_token}"}, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["min_amount"] == 10
        assert data["max_amount"] == 5000
        assert isinstance(data["presets"], list) and 500 in data["presets"]
        assert "balance" in data and "wallet_frozen" in data
        assert data["is_mock"] is True, "preview should be in mock mode"
        assert "key_id" in data

    def test_config_requires_auth(self):
        r = requests.get(f"{BASE}/api/wallet/topup/config", timeout=15)
        assert r.status_code in (401, 403), f"expected 401/403 got {r.status_code}"

    def test_start_over_limit(self, buyer_token):
        r = requests.post(f"{BASE}/api/wallet/topup/start", headers={"Authorization": f"Bearer {buyer_token}"},
                          json={"amount": 5001}, timeout=15)
        assert r.status_code == 400, r.text

    def test_start_under_limit(self, buyer_token):
        r = requests.post(f"{BASE}/api/wallet/topup/start", headers={"Authorization": f"Bearer {buyer_token}"},
                          json={"amount": 5}, timeout=15)
        assert r.status_code == 400, r.text

    def test_start_ok(self, buyer_token):
        r = requests.post(f"{BASE}/api/wallet/topup/start", headers={"Authorization": f"Bearer {buyer_token}"},
                          json={"amount": 500}, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["amount"] == 500 and d["amount_paise"] == 50000
        assert d["is_mock"] is True
        assert d["payment_id"] and d["razorpay_order_id"]
        assert "prefill" in d

    def test_verify_credits_once_and_not_twice(self, buyer_token):
        headers = {"Authorization": f"Bearer {buyer_token}"}
        bal_before = float(_me(buyer_token).get("wallet_balance") or 0)

        s = requests.post(f"{BASE}/api/wallet/topup/start", headers=headers, json={"amount": 250}, timeout=15).json()
        vpayload = {
            "payment_id": s["payment_id"],
            "razorpay_order_id": s["razorpay_order_id"],
            "razorpay_payment_id": f"pay_MOCK_{uuid.uuid4().hex[:12]}",
            "razorpay_signature": f"sig_MOCK_{uuid.uuid4().hex[:16]}",
        }
        v1 = requests.post(f"{BASE}/api/wallet/topup/verify", headers=headers, json=vpayload, timeout=20)
        assert v1.status_code == 200, v1.text
        d1 = v1.json()
        assert d1.get("ok") is True
        assert d1.get("reference", "").startswith("TXN"), f"reference short id missing: {d1}"

        bal_mid = float(_me(buyer_token).get("wallet_balance") or 0)
        assert round(bal_mid - bal_before, 2) == 250.0, f"expected +250; got {bal_before} → {bal_mid}"

        v2 = requests.post(f"{BASE}/api/wallet/topup/verify", headers=headers, json=vpayload, timeout=20)
        assert v2.status_code == 200, v2.text
        d2 = v2.json()
        assert d2.get("already_verified") is True, f"second verify must be idempotent: {d2}"

        bal_after = float(_me(buyer_token).get("wallet_balance") or 0)
        assert round(bal_after - bal_mid, 2) == 0.0, f"second verify must not credit; got {bal_mid} → {bal_after}"

        # Check a transaction row + bank ledger entry exist
        tx = requests.get(f"{BASE}/api/transactions/me", headers=headers, timeout=15).json()
        topup_txn = next((t for t in tx if t.get("type") == "wallet_topup" and abs(float(t.get("amount") or 0) - 250.0) < 0.01), None)
        assert topup_txn, "wallet_topup transaction not found for buyer"
        assert (topup_txn.get("short_id") or topup_txn.get("reference_number") or "").startswith("TXN")

    def test_verify_unauth(self):
        r = requests.post(f"{BASE}/api/wallet/topup/verify",
                          json={"payment_id": "x", "razorpay_payment_id": "y"}, timeout=10)
        assert r.status_code in (401, 403)

    def test_frozen_wallet_start_forbidden(self, admin_token, buyer_token):
        # Freeze buyer
        me = _me(buyer_token)
        uid = me["id"]
        ah = {"Authorization": f"Bearer {admin_token}"}
        f = requests.post(f"{BASE}/api/admin/users/{uid}/wallet/freeze",
                         headers=ah, json={"frozen": True}, timeout=15)
        assert f.status_code == 200, f.text
        try:
            r = requests.post(f"{BASE}/api/wallet/topup/start",
                              headers={"Authorization": f"Bearer {buyer_token}"},
                              json={"amount": 500}, timeout=15)
            assert r.status_code == 403, r.text
        finally:
            requests.post(f"{BASE}/api/admin/users/{uid}/wallet/freeze",
                          headers=ah, json={"frozen": False}, timeout=15)


# ─────────────────────── BUG 1c — Withdraw is vendor-only ───────────────────────

class TestWithdrawalsRoleGuard:
    def test_buyer_cannot_withdraw(self, buyer_token):
        r = requests.post(f"{BASE}/api/withdrawals",
                          headers={"Authorization": f"Bearer {buyer_token}"},
                          json={"amount": 100}, timeout=15)
        assert r.status_code in (400, 403), r.text


# ─────────────────────── BUG 2 — Admin wallet adjust funded from NET WORTH ───────────────────────

class TestAdminWalletAdjust:
    def _find_buyer(self, admin_token) -> str:
        r = requests.get(f"{BASE}/api/admin/users?email={BUYER[0]}",
                         headers={"Authorization": f"Bearer {admin_token}"}, timeout=15)
        assert r.status_code == 200, r.text
        items = r.json() if isinstance(r.json(), list) else r.json().get("users") or r.json().get("items") or []
        assert items, "buyer not found via admin users"
        u = next(x for x in items if x.get("email") == BUYER[0])
        return u["id"]

    def test_net_worth_endpoint(self, admin_token):
        r = requests.get(f"{BASE}/api/admin/finance/net-worth",
                         headers={"Authorization": f"Bearer {admin_token}"}, timeout=15)
        assert r.status_code == 200, r.text

    def test_credit_and_debit_from_networth(self, admin_token, buyer_token):
        ah = {"Authorization": f"Bearer {admin_token}"}
        uid = self._find_buyer(admin_token)
        bal0 = float(_me(buyer_token).get("wallet_balance") or 0)

        def _nw() -> float:
            j = requests.get(f"{BASE}/api/admin/finance/net-worth", headers=ah, timeout=15).json()
            return float((j.get("master") or {}).get("net_worth") or j.get("net_worth") or 0)

        nw0_val = _nw()

        # Credit ₹50 — MUST succeed now (previously 400 with "Insufficient Direct-Added funds")
        r = requests.post(f"{BASE}/api/admin/users/{uid}/wallet",
                          headers=ah,
                          json={"amount": 50, "type": "credit", "reason": "iter80 net-worth credit"}, timeout=15)
        assert r.status_code == 200, f"credit should succeed: {r.status_code} {r.text}"
        d = r.json()
        assert d.get("ok") is True
        assert d.get("funded_from") == "company_net_worth", f"funded_from should be company_net_worth: {d}"
        assert "user_balance" in d

        # User balance should have moved +50
        bal1 = float(_me(buyer_token).get("wallet_balance") or 0)
        assert round(bal1 - bal0, 2) == 50.0, f"expected +50 got {bal0} → {bal1}"

        # Net worth must have DECREASED by the credited amount (user liability rose)
        nw1_val = _nw()
        assert round(nw0_val - nw1_val, 2) == 50.0, f"net worth should drop by 50; {nw0_val} → {nw1_val}"

        # Debit ₹50 returns the money
        r2 = requests.post(f"{BASE}/api/admin/users/{uid}/wallet",
                           headers=ah,
                           json={"amount": 50, "type": "debit", "reason": "iter80 net-worth debit"}, timeout=15)
        assert r2.status_code == 200, r2.text
        assert r2.json().get("funded_from") == "company_net_worth"

        bal2 = float(_me(buyer_token).get("wallet_balance") or 0)
        assert round(bal2 - bal0, 2) == 0.0, f"balance should be back to {bal0}; got {bal2}"

        nw2_val = _nw()
        assert round(nw2_val - nw0_val, 2) == 0.0, f"net worth should return; {nw0_val} → {nw2_val}"

        # Confirm admin_credit txn row exists
        tx = requests.get(f"{BASE}/api/transactions/me", headers={"Authorization": f"Bearer {buyer_token}"}, timeout=15).json()
        assert any(t.get("type") == "admin_credit" for t in tx), "admin_credit txn not found for buyer"
