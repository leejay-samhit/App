"""Iteration 4 backend tests — Phase 1 admin enhancements.

Coverage:
- Analytics dashboard endpoint
- KYC submit/list/approve/reject
- User block/unblock + login enforcement
- Wallet adjust (credit/debit/insufficient)
- Wallet freeze toggle (blocks withdrawal & checkout)
- Transactions filter / status update / refund
- Orders filter / status update / cancel-refund
- Audit logs
- CSV exports (users/transactions/withdrawals/orders)
- RBAC — super_admin vs manager on PUT /admin/settings
"""
import os
import uuid
import time
import pytest
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://slangcart-tracking.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"


def H(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _register_paid_user(prefix: str = "TEST_I4"):
    """Register + pay for a fresh user under ADMIN001; returns (token, user_dict)."""
    email = f"{prefix}_{uuid.uuid4().hex[:8]}@test.com"
    r = requests.post(f"{BASE_URL}/api/auth/register", json={
        "name": prefix, "email": email, "password": "Pass@1234", "referral_code": "ADMIN001",
    })
    assert r.status_code == 200, r.text
    tok = r.json()["token"]
    u = r.json()["user"]
    p = requests.post(f"{BASE_URL}/api/payment/register-fee", headers=H(tok))
    assert p.status_code == 200, p.text
    # refresh user
    me = requests.get(f"{BASE_URL}/api/auth/me", headers=H(tok)).json()
    return tok, me


# ---------- Analytics ----------
class TestAnalytics:
    def test_analytics_shape_7d(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/analytics?days=7", headers=H(admin_token))
        assert r.status_code == 200, r.text
        d = r.json()
        assert "kpis" in d and "daily_users" in d and "daily_revenue" in d and "daily_txns" in d
        for k in ["new_users_today", "new_users_month", "paid_users_today", "total_revenue",
                  "system_wallet", "total_payouts", "success_txns", "failed_txns",
                  "pending_txns", "refunded_txns", "orders_count", "orders_revenue"]:
            assert k in d["kpis"], f"missing kpi {k}"
        assert len(d["daily_users"]) == 7
        assert len(d["daily_revenue"]) == 7
        assert len(d["daily_txns"]) == 7
        assert all("date" in p and "value" in p for p in d["daily_users"])


# ---------- KYC ----------
class TestKYC:
    def test_kyc_submit_validation_and_approve(self, admin_token):
        tok, u = _register_paid_user("TEST_I4_KYC")
        # invalid aadhaar
        r = requests.post(f"{BASE_URL}/api/users/me/kyc", headers=H(tok),
                          json={"full_name": "Test User", "aadhaar": "1234", "pan": "ABCDE1234F"})
        assert r.status_code == 400
        # invalid PAN
        r = requests.post(f"{BASE_URL}/api/users/me/kyc", headers=H(tok),
                          json={"full_name": "Test User", "aadhaar": "123456789012", "pan": "SHORT"})
        assert r.status_code == 400
        # valid
        r = requests.post(f"{BASE_URL}/api/users/me/kyc", headers=H(tok),
                          json={"full_name": "Test User", "aadhaar": "123456789012", "pan": "ABCDE1234F"})
        assert r.status_code == 200, r.text
        # GET status
        g = requests.get(f"{BASE_URL}/api/users/me/kyc", headers=H(tok))
        assert g.status_code == 200
        body = g.json()
        assert body["status"] == "pending"
        assert body["aadhaar"] == "123456789012"
        assert body["pan"] == "ABCDE1234F"
        # admin list pending
        a = requests.get(f"{BASE_URL}/api/admin/kyc?status=pending", headers=H(admin_token))
        assert a.status_code == 200
        ids = [x["id"] for x in a.json()]
        assert u["id"] in ids
        # approve
        ap = requests.post(f"{BASE_URL}/api/admin/kyc/{u['id']}/approve", headers=H(admin_token))
        assert ap.status_code == 200
        g2 = requests.get(f"{BASE_URL}/api/users/me/kyc", headers=H(tok)).json()
        assert g2["status"] == "approved"

    def test_kyc_reject_with_reason(self, admin_token):
        tok, u = _register_paid_user("TEST_I4_REJ")
        requests.post(f"{BASE_URL}/api/users/me/kyc", headers=H(tok),
                      json={"full_name": "T", "aadhaar": "123456789012", "pan": "ABCDE1234F"})
        r = requests.post(f"{BASE_URL}/api/admin/kyc/{u['id']}/reject", headers=H(admin_token),
                          json={"reason": "bad doc"})
        assert r.status_code == 200
        g = requests.get(f"{BASE_URL}/api/users/me/kyc", headers=H(tok)).json()
        assert g["status"] == "rejected"
        assert g["reject_reason"] == "bad doc"


# ---------- Block / Unblock ----------
class TestBlock:
    def test_block_then_login_403_then_unblock(self, admin_token):
        email = f"TEST_I4_BLK_{uuid.uuid4().hex[:8]}@test.com"
        r = requests.post(f"{BASE_URL}/api/auth/register", json={
            "name": "B", "email": email, "password": "Pass@1234", "referral_code": "ADMIN001",
        })
        assert r.status_code == 200
        u = r.json()["user"]
        # block
        b = requests.post(f"{BASE_URL}/api/admin/users/{u['id']}/block",
                          headers=H(admin_token), json={"reason": "spam"})
        assert b.status_code == 200
        # login should 403
        lg = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": "Pass@1234"})
        assert lg.status_code == 403
        assert "spam" in lg.json().get("detail", "").lower() or "block" in lg.json().get("detail", "").lower()
        # unblock
        ub = requests.post(f"{BASE_URL}/api/admin/users/{u['id']}/unblock", headers=H(admin_token))
        assert ub.status_code == 200
        lg2 = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": "Pass@1234"})
        assert lg2.status_code == 200

    def test_block_self_400(self, admin_token):
        me = requests.get(f"{BASE_URL}/api/auth/me", headers=H(admin_token)).json()
        r = requests.post(f"{BASE_URL}/api/admin/users/{me['id']}/block",
                          headers=H(admin_token), json={"reason": "x"})
        assert r.status_code == 400


# ---------- Wallet adjust & freeze ----------
class TestWalletAdmin:
    def test_credit_then_debit_and_underflow(self, admin_token):
        tok, u = _register_paid_user("TEST_I4_W")
        # credit 500
        r = requests.post(f"{BASE_URL}/api/admin/users/{u['id']}/wallet", headers=H(admin_token),
                          json={"amount": 500, "type": "credit", "reason": "promo"})
        assert r.status_code == 200
        g = requests.get(f"{BASE_URL}/api/auth/me", headers=H(tok)).json()
        assert g["wallet_balance"] >= 500
        # debit 100
        r2 = requests.post(f"{BASE_URL}/api/admin/users/{u['id']}/wallet", headers=H(admin_token),
                           json={"amount": 100, "type": "debit", "reason": "fix"})
        assert r2.status_code == 200
        # debit huge -> 400
        r3 = requests.post(f"{BASE_URL}/api/admin/users/{u['id']}/wallet", headers=H(admin_token),
                           json={"amount": 999999, "type": "debit", "reason": "drain"})
        assert r3.status_code == 400
        # txn type=admin_adjust exists
        tf = requests.get(f"{BASE_URL}/api/admin/transactions/filter?type=admin_adjust&user_id=" + u["id"],
                          headers=H(admin_token))
        assert tf.status_code == 200 and len(tf.json()) >= 2

    def test_freeze_blocks_withdraw_and_checkout(self, admin_token):
        tok, u = _register_paid_user("TEST_I4_FRZ")
        # credit so withdrawal would otherwise be possible
        requests.post(f"{BASE_URL}/api/admin/users/{u['id']}/wallet", headers=H(admin_token),
                      json={"amount": 600, "type": "credit", "reason": "seed"})
        # set bank
        requests.post(f"{BASE_URL}/api/users/me/bank", headers=H(tok),
                      json={"upi_id": "x@upi"})
        # freeze
        fr = requests.post(f"{BASE_URL}/api/admin/users/{u['id']}/wallet/freeze", headers=H(admin_token))
        assert fr.status_code == 200 and fr.json()["frozen"] is True
        # withdrawal -> 403
        w = requests.post(f"{BASE_URL}/api/withdrawals", headers=H(tok), json={"amount": 500})
        assert w.status_code == 403
        # add cart item then checkout -> 403
        prods = requests.get(f"{BASE_URL}/api/products").json()
        if prods:
            requests.post(f"{BASE_URL}/api/cart/add", headers=H(tok),
                          json={"product_id": prods[0]["id"], "qty": 1})
            co = requests.post(f"{BASE_URL}/api/orders/checkout", headers=H(tok))
            assert co.status_code == 403
        # unfreeze
        fr2 = requests.post(f"{BASE_URL}/api/admin/users/{u['id']}/wallet/freeze", headers=H(admin_token))
        assert fr2.json()["frozen"] is False


# ---------- Transactions filter / refund ----------
class TestTransactionsAdmin:
    def test_filter_and_refund(self, admin_token):
        tok, u = _register_paid_user("TEST_I4_REF")
        # filter by user_id
        f = requests.get(f"{BASE_URL}/api/admin/transactions/filter?user_id=" + u["id"],
                         headers=H(admin_token))
        assert f.status_code == 200
        items = f.json()
        assert len(items) >= 1
        # sorted desc
        if len(items) >= 2:
            assert items[0]["created_at"] >= items[1]["created_at"]
        # find a registration_fee txn for admin (sponsor) — pick one credit txn for this user instead
        cred = [t for t in items if t.get("status") in ("paid", "credited")]
        assert cred, "no creditable txn found for user"
        # update status
        ps = requests.patch(f"{BASE_URL}/api/admin/transactions/{cred[0]['id']}",
                            headers=H(admin_token), json={"status": "pending"})
        assert ps.status_code == 200
        # refund the txn
        rf = requests.post(f"{BASE_URL}/api/admin/transactions/{cred[0]['id']}/refund",
                           headers=H(admin_token))
        assert rf.status_code == 200, rf.text
        # original now refunded
        f2 = requests.get(f"{BASE_URL}/api/admin/transactions/filter?user_id=" + u["id"],
                          headers=H(admin_token)).json()
        orig = next(t for t in f2 if t["id"] == cred[0]["id"])
        assert orig["status"] == "refunded"
        # refund txn exists
        refunds = [t for t in f2 if t.get("type") == "refund"]
        assert refunds


# ---------- Orders ----------
class TestOrdersAdmin:
    def test_order_status_and_cancel_refund(self, admin_token):
        tok, u = _register_paid_user("TEST_I4_ORD")
        # credit wallet so checkout works
        requests.post(f"{BASE_URL}/api/admin/users/{u['id']}/wallet", headers=H(admin_token),
                      json={"amount": 5000, "type": "credit", "reason": "seed"})
        prods = requests.get(f"{BASE_URL}/api/products").json()
        assert prods
        requests.post(f"{BASE_URL}/api/cart/add", headers=H(tok),
                      json={"product_id": prods[0]["id"], "qty": 1})
        co = requests.post(f"{BASE_URL}/api/orders/checkout", headers=H(tok))
        assert co.status_code == 200, co.text
        order_id = co.json()["id"]
        order_total = co.json()["total"]
        # admin list with filter
        lst = requests.get(f"{BASE_URL}/api/admin/orders?status=placed", headers=H(admin_token))
        assert lst.status_code == 200
        # invalid status
        bad = requests.patch(f"{BASE_URL}/api/admin/orders/{order_id}/status",
                             headers=H(admin_token), json={"status": "weird"})
        assert bad.status_code == 400
        # ship
        sh = requests.patch(f"{BASE_URL}/api/admin/orders/{order_id}/status",
                            headers=H(admin_token), json={"status": "shipped"})
        assert sh.status_code == 200
        # cancel & refund — get balance before
        bal_before = requests.get(f"{BASE_URL}/api/auth/me", headers=H(tok)).json()["wallet_balance"]
        cn = requests.patch(f"{BASE_URL}/api/admin/orders/{order_id}/status",
                            headers=H(admin_token), json={"status": "cancelled"})
        assert cn.status_code == 200
        bal_after = requests.get(f"{BASE_URL}/api/auth/me", headers=H(tok)).json()["wallet_balance"]
        assert round(bal_after - bal_before, 2) == round(order_total, 2)


# ---------- Audit logs ----------
class TestAudit:
    def test_audit_logs_recent(self, admin_token):
        # trigger something fresh
        tok, u = _register_paid_user("TEST_I4_AUD")
        requests.post(f"{BASE_URL}/api/admin/users/{u['id']}/block", headers=H(admin_token),
                      json={"reason": "audit-test"})
        r = requests.get(f"{BASE_URL}/api/admin/audit-logs?limit=50", headers=H(admin_token))
        assert r.status_code == 200
        items = r.json()
        assert any(x.get("action") == "user.block" and x.get("target_id") == u["id"] for x in items)
        # sorted desc
        if len(items) >= 2:
            assert items[0]["created_at"] >= items[1]["created_at"]


# ---------- CSV Exports ----------
class TestExports:
    @pytest.mark.parametrize("kind,header_field", [
        ("users", "email"),
        ("transactions", "amount"),
        ("withdrawals", "amount"),
        ("orders", "total"),
    ])
    def test_export_csv(self, admin_token, kind, header_field):
        r = requests.get(f"{BASE_URL}/api/admin/export/{kind}", headers=H(admin_token))
        assert r.status_code == 200, r.text
        ct = r.headers.get("content-type", "")
        assert "text/csv" in ct
        body = r.text
        first_line = body.splitlines()[0]
        assert header_field in first_line

    def test_export_invalid_kind(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/export/bogus", headers=H(admin_token))
        assert r.status_code == 400


# ---------- RBAC ----------
class TestRBAC:
    def test_super_admin_can_put_settings(self, admin_token):
        cur = requests.get(f"{BASE_URL}/api/admin/settings", headers=H(admin_token)).json()
        r = requests.put(f"{BASE_URL}/api/admin/settings", headers=H(admin_token),
                         json={"registration_fee": cur["registration_fee"]})
        assert r.status_code == 200

    def test_manager_blocked_from_settings(self, admin_token):
        # create a manager admin: register a user, then PATCH role=admin & admin_role=manager
        email = f"TEST_I4_MGR_{uuid.uuid4().hex[:8]}@test.com"
        password = "MgrPass@123"
        rr = requests.post(f"{BASE_URL}/api/auth/register", json={
            "name": "Mgr", "email": email, "password": password, "referral_code": "ADMIN001",
        })
        assert rr.status_code == 200
        uid = rr.json()["user"]["id"]
        # promote to manager
        pp = requests.patch(f"{BASE_URL}/api/admin/users/{uid}", headers=H(admin_token),
                            json={"role": "admin", "admin_role": "manager"})
        assert pp.status_code == 200, pp.text
        # login as manager
        lg = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
        assert lg.status_code == 200, lg.text
        mtok = lg.json()["token"]
        # manager: GET admin/users should work
        gu = requests.get(f"{BASE_URL}/api/admin/users", headers=H(mtok))
        assert gu.status_code == 200
        # manager: KYC list should work
        gk = requests.get(f"{BASE_URL}/api/admin/kyc", headers=H(mtok))
        assert gk.status_code == 200
        # manager: PUT settings should be FORBIDDEN
        sp = requests.put(f"{BASE_URL}/api/admin/settings", headers=H(mtok),
                          json={"registration_fee": 100})
        assert sp.status_code == 403, f"manager PUT settings expected 403 but got {sp.status_code}: {sp.text}"


# ---------- Regression smoke ----------
class TestRegressionSmoke:
    def test_login_admin(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert r.status_code == 200
        assert r.json()["user"]["role"] == "admin"

    def test_register_pay_chain(self, admin_token):
        # Register sponsor + 1 direct -> sponsor sees direct count incremented
        sp_email = f"TEST_I4_SP_{uuid.uuid4().hex[:8]}@test.com"
        rs = requests.post(f"{BASE_URL}/api/auth/register", json={
            "name": "SP", "email": sp_email, "password": "Pass@1234", "referral_code": "ADMIN001",
        }).json()
        sp_tok = rs["token"]
        sp_code = rs["user"]["referral_code"]
        requests.post(f"{BASE_URL}/api/payment/register-fee", headers=H(sp_tok))
        # direct
        rd = requests.post(f"{BASE_URL}/api/auth/register", json={
            "name": "D", "email": f"TEST_I4_D_{uuid.uuid4().hex[:8]}@test.com",
            "password": "Pass@1234", "referral_code": sp_code,
        }).json()
        requests.post(f"{BASE_URL}/api/payment/register-fee", headers=H(rd["token"]))
        dash = requests.get(f"{BASE_URL}/api/users/me/dashboard", headers=H(sp_tok)).json()
        assert dash["direct_referrals"] >= 1
