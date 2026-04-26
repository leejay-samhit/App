"""End-to-end backend tests for Referral & E-commerce API."""
import time
import uuid
import pytest
import requests
from conftest import BASE_URL, auth_headers


# ---------- Health & Auth ----------
class TestHealthAndAuth:
    def test_root(self, api):
        r = api.get(f"{BASE_URL}/api/")
        assert r.status_code == 200
        assert r.json().get("ok") is True

    def test_admin_login(self, api):
        r = api.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@app.com", "password": "Admin@123"})
        assert r.status_code == 200
        body = r.json()
        assert "token" in body and body["user"]["role"] == "admin"
        assert body["user"]["referral_code"] == "ADMIN001"
        assert "password_hash" not in body["user"]
        assert "_id" not in body["user"]

    def test_login_invalid_password(self, api):
        r = api.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@app.com", "password": "wrong"})
        assert r.status_code == 401

    def test_register_no_referral(self, api):
        email = f"TEST_user_{uuid.uuid4().hex[:8]}@test.com"
        r = api.post(f"{BASE_URL}/api/auth/register", json={
            "name": "Test User", "email": email, "password": "Test@1234"
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert "token" in body
        assert body["user"]["email"] == email.lower()
        assert body["user"]["referral_code"]
        assert body["user"]["registration_paid"] is False
        assert body["user"]["sponsor_id"] is None
        # /me works with the token
        me = api.get(f"{BASE_URL}/api/auth/me", headers=auth_headers(body["token"]))
        assert me.status_code == 200
        assert me.json()["email"] == email.lower()

    def test_register_duplicate_email(self, api):
        email = f"TEST_dup_{uuid.uuid4().hex[:8]}@test.com"
        api.post(f"{BASE_URL}/api/auth/register", json={
            "name": "Dup", "email": email, "password": "Test@1234"
        })
        r = api.post(f"{BASE_URL}/api/auth/register", json={
            "name": "Dup", "email": email, "password": "Test@1234"
        })
        assert r.status_code == 400

    def test_register_invalid_referral(self, api):
        email = f"TEST_invref_{uuid.uuid4().hex[:8]}@test.com"
        r = api.post(f"{BASE_URL}/api/auth/register", json={
            "name": "X", "email": email, "password": "Test@1234", "referral_code": "BAD123"
        })
        assert r.status_code == 400

    def test_me_no_token(self, api):
        r = api.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 401


# ---------- Payment & 1+4 Referral Payout ----------
def _register(api, ref=None):
    email = f"TEST_{uuid.uuid4().hex[:10]}@test.com"
    payload = {"name": "U", "email": email, "password": "Test@1234"}
    if ref:
        payload["referral_code"] = ref
    r = api.post(f"{BASE_URL}/api/auth/register", json=payload)
    assert r.status_code == 200, r.text
    return r.json()  # {token,user}


class TestPaymentAndPayout:
    def test_pay_registration_fee_idempotent(self, api):
        u = _register(api)
        token = u["token"]
        r1 = api.post(f"{BASE_URL}/api/payment/register-fee", headers=auth_headers(token))
        assert r1.status_code == 200
        assert r1.json()["amount"] == 100
        r2 = api.post(f"{BASE_URL}/api/payment/register-fee", headers=auth_headers(token))
        assert r2.status_code == 400

        # txns
        txns = api.get(f"{BASE_URL}/api/transactions/me", headers=auth_headers(token))
        assert txns.status_code == 200
        types = [t["type"] for t in txns.json()]
        assert "registration_fee" in types

    def test_one_plus_four_payout(self, api):
        # Sponsor: register & pay so they're active (sponsor doesn't need to pay to receive payout, but ok)
        sponsor = _register(api)
        s_token = sponsor["token"]
        sref = sponsor["user"]["referral_code"]
        api.post(f"{BASE_URL}/api/payment/register-fee", headers=auth_headers(s_token))

        # Register 4 directs and pay each
        for i in range(4):
            child = _register(api, ref=sref)
            r = api.post(f"{BASE_URL}/api/payment/register-fee", headers=auth_headers(child["token"]))
            assert r.status_code == 200

        # Sponsor's dashboard
        dash = api.get(f"{BASE_URL}/api/users/me/dashboard", headers=auth_headers(s_token))
        assert dash.status_code == 200
        d = dash.json()
        assert d["direct_referrals"] == 4, d
        assert d["wallet_balance"] == 400, d
        assert d["total_earned"] == 400, d
        assert d["payouts_received"] == 1, d
        assert d["next_payout_in"] == 4

        # Network endpoint shows children
        net = api.get(f"{BASE_URL}/api/users/me/network", headers=auth_headers(s_token))
        assert net.status_code == 200
        assert len(net.json()["children"]) == 4


# ---------- Bank / Withdrawals ----------
class TestBankAndWithdrawals:
    def test_bank_update_and_withdrawal_flow(self, api):
        # Build sponsor with payout balance
        sponsor = _register(api)
        s_token = sponsor["token"]
        sref = sponsor["user"]["referral_code"]
        api.post(f"{BASE_URL}/api/payment/register-fee", headers=auth_headers(s_token))
        for _ in range(4):
            c = _register(api, ref=sref)
            api.post(f"{BASE_URL}/api/payment/register-fee", headers=auth_headers(c["token"]))

        # Withdrawal without bank/upi -> 400
        r = api.post(f"{BASE_URL}/api/withdrawals", json={"amount": 100}, headers=auth_headers(s_token))
        assert r.status_code == 400

        # Update UPI
        r = api.post(f"{BASE_URL}/api/users/me/bank", json={"upi_id": "user@upi"}, headers=auth_headers(s_token))
        assert r.status_code == 200
        assert r.json()["upi_id"] == "user@upi"

        # Insufficient balance
        r = api.post(f"{BASE_URL}/api/withdrawals", json={"amount": 10000}, headers=auth_headers(s_token))
        assert r.status_code == 400

        # Successful withdrawal
        r = api.post(f"{BASE_URL}/api/withdrawals", json={"amount": 100}, headers=auth_headers(s_token))
        assert r.status_code == 200
        wid = r.json()["id"]
        assert r.json()["status"] == "pending"

        # Wallet locked
        d = api.get(f"{BASE_URL}/api/users/me/dashboard", headers=auth_headers(s_token)).json()
        assert d["wallet_balance"] == 300

        # GET own withdrawals
        my = api.get(f"{BASE_URL}/api/withdrawals/me", headers=auth_headers(s_token))
        assert my.status_code == 200 and any(w["id"] == wid for w in my.json())

    def test_withdrawal_rejection_refunds(self, api, admin_token):
        # Create a sponsor with balance + UPI + a withdrawal
        sponsor = _register(api)
        s_token = sponsor["token"]
        sref = sponsor["user"]["referral_code"]
        api.post(f"{BASE_URL}/api/payment/register-fee", headers=auth_headers(s_token))
        for _ in range(4):
            c = _register(api, ref=sref)
            api.post(f"{BASE_URL}/api/payment/register-fee", headers=auth_headers(c["token"]))
        api.post(f"{BASE_URL}/api/users/me/bank", json={"upi_id": "x@upi"}, headers=auth_headers(s_token))
        wr = api.post(f"{BASE_URL}/api/withdrawals", json={"amount": 200}, headers=auth_headers(s_token))
        wid = wr.json()["id"]

        # Reject as admin -> balance restored
        rj = api.post(f"{BASE_URL}/api/admin/withdrawals/{wid}/reject", headers=auth_headers(admin_token))
        assert rj.status_code == 200
        d = api.get(f"{BASE_URL}/api/users/me/dashboard", headers=auth_headers(s_token)).json()
        assert d["wallet_balance"] == 400

        # Approve flow on a fresh withdrawal
        wr2 = api.post(f"{BASE_URL}/api/withdrawals", json={"amount": 100}, headers=auth_headers(s_token))
        wid2 = wr2.json()["id"]
        ap = api.post(f"{BASE_URL}/api/admin/withdrawals/{wid2}/approve", headers=auth_headers(admin_token))
        assert ap.status_code == 200
        # Re-approve -> 400
        again = api.post(f"{BASE_URL}/api/admin/withdrawals/{wid2}/approve", headers=auth_headers(admin_token))
        assert again.status_code == 400


# ---------- Products / Admin ----------
class TestProductsAndAdmin:
    def test_products_seeded(self, api):
        r = api.get(f"{BASE_URL}/api/products")
        assert r.status_code == 200
        assert len(r.json()) >= 1
        for p in r.json():
            assert "name" in p and "price" in p and "image_url" in p
            assert "_id" not in p

    def test_admin_endpoints_require_admin(self, api):
        u = _register(api)
        for path in ["/api/admin/users", "/api/admin/withdrawals", "/api/admin/transactions", "/api/admin/stats"]:
            r = api.get(f"{BASE_URL}{path}", headers=auth_headers(u["token"]))
            assert r.status_code == 403, f"{path} expected 403 for non-admin, got {r.status_code}"

    def test_admin_users_list(self, api, admin_token):
        r = api.get(f"{BASE_URL}/api/admin/users", headers=auth_headers(admin_token))
        assert r.status_code == 200
        users = r.json()
        assert isinstance(users, list) and len(users) >= 1
        assert all("password_hash" not in u for u in users)

    def test_admin_stats(self, api, admin_token):
        r = api.get(f"{BASE_URL}/api/admin/stats", headers=auth_headers(admin_token))
        assert r.status_code == 200
        s = r.json()
        for k in ["total_users", "paid_users", "total_revenue", "total_referral_payouts"]:
            assert k in s

    def test_admin_transactions(self, api, admin_token):
        r = api.get(f"{BASE_URL}/api/admin/transactions", headers=auth_headers(admin_token))
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_admin_pending_withdrawals(self, api, admin_token):
        r = api.get(f"{BASE_URL}/api/admin/withdrawals?status=pending", headers=auth_headers(admin_token))
        assert r.status_code == 200
        for w in r.json():
            assert w["status"] == "pending"
