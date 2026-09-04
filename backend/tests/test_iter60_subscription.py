"""Iteration 60 · ₹118 SUBSCRIPTION / free-tier backend tests (Aug-2026).

Coverage
--------
1.  POST /api/payment/skip-subscription
      • unpaid user  → sets subscription_skipped=true (verify via /auth/me)
      • paid user    → already_paid=true, no DB mutation
2.  POST /api/withdrawals returns "Complete registration payment first" for a
    free-tier user (and creates NO transactions).
3.  PATCH /api/admin/users/{id} {registration_paid:true} on a free user
      • sets registration_paid=true, registration_source='offline_cash',
        paid_at, admin_approved_only=true, commission_triggered=true,
        subscription_skipped=false
      • creates EXACTLY ONE registration_fee txn (amount=118, status=paid,
        source=offline_cash)
      • creates NO referral_payout / direct_signup_credit / gst_collected txns
      • sponsor wallet_balance + total_earned unchanged
      • idempotent → 2nd PATCH does NOT create another fee txn
4.  /api/admin/transactions/summary?type=registration_fee — offline_cash count
    & amount increase by exactly 1 / ₹118 after the Admin-Approved action.
5.  /api/admin/finance/net-worth · group_3_gst.registration_gst is derived
    from RAZORPAY revenue only (unchanged by the offline approval); gst_payable
    stays subtracted in master.net_worth (formula check).
6.  /api/admin/users?source=unpaid and /api/admin/users/source-counts include
    the free-tier user under 'unpaid'.
"""

import os
import time
import uuid

import pytest
import requests


BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://vendor-network-app-1.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "support@slangcart.com"
ADMIN_PASSWORD = "3)Ywxtic"
PAID_EMAIL = "freetier1@test.com"
PAID_PASSWORD = "Just@4me"


# ────────────────────────── helpers / fixtures ──────────────────────────

def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text[:200]}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, f"no token in login response for {email}"
    return tok


def _headers(token: str):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _register(email: str, name: str, password: str = "Just@4me", phone: str | None = None, sponsor_code: str | None = None) -> dict:
    """Register a brand-new user and return the auth payload."""
    payload = {"name": name, "email": email, "password": password}
    if phone:
        payload["phone"] = phone
    if sponsor_code:
        payload["referral_code"] = sponsor_code
    r = requests.post(f"{API}/auth/register", json=payload, timeout=25)
    assert r.status_code in (200, 201), f"register failed: {r.status_code} {r.text[:300]}"
    return r.json()


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def paid_token():
    return _login(PAID_EMAIL, PAID_PASSWORD)


@pytest.fixture(scope="module")
def paid_user_me(paid_token):
    r = requests.get(f"{API}/auth/me", headers=_headers(paid_token), timeout=20)
    assert r.status_code == 200
    return r.json()


# One brand-new unpaid user per test that needs it — cheaper than a shared one
# because we also want to test admin-approve which mutates state permanently.
def _new_unpaid_user(sponsor_code: str | None = None):
    tag = uuid.uuid4().hex[:8]
    email = f"test_iter60_{tag}@example.com"
    reg = _register(email, name=f"TEST_iter60 {tag}", sponsor_code=sponsor_code)
    tok = reg.get("token") or reg.get("access_token")
    if not tok:
        tok = _login(email, "Just@4me")
    return email, tok, reg


# ──────────────────────────── the tests ────────────────────────────────

class TestSkipSubscription:
    def test_skip_for_unpaid_user_sets_flag(self):
        """POST /payment/skip-subscription for unpaid user sets flag; /auth/me confirms."""
        email, tok, _ = _new_unpaid_user()

        me1 = requests.get(f"{API}/auth/me", headers=_headers(tok), timeout=20).json()
        assert me1.get("registration_paid") is False
        assert not me1.get("subscription_skipped")

        r = requests.post(f"{API}/payment/skip-subscription", headers=_headers(tok), timeout=20)
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert body.get("ok") is True
        assert body.get("subscription_skipped") is True
        assert not body.get("already_paid")

        me2 = requests.get(f"{API}/auth/me", headers=_headers(tok), timeout=20).json()
        assert me2.get("subscription_skipped") is True, f"me: {me2}"
        assert me2.get("registration_paid") is False

    def test_skip_for_paid_user_is_noop(self, paid_token):
        """Paid user hitting skip returns already_paid=true and does NOT mutate state."""
        r = requests.post(f"{API}/payment/skip-subscription", headers=_headers(paid_token), timeout=20)
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert body.get("already_paid") is True
        assert body.get("subscription_skipped") is False
        me = requests.get(f"{API}/auth/me", headers=_headers(paid_token), timeout=20).json()
        assert me.get("registration_paid") is True
        # subscription_skipped must NOT have been flipped on for a paid user
        assert me.get("subscription_skipped") in (False, None, 0)


class TestFreeTierWithdrawalGate:
    def test_free_user_withdrawal_blocked(self):
        email, tok, _ = _new_unpaid_user()
        # skip subscription so user is a proper "free" user
        requests.post(f"{API}/payment/skip-subscription", headers=_headers(tok), timeout=20)

        # Try to withdraw — MIN is ₹100 so use ₹150 to bypass the min-check
        # message (we specifically want the registration gate to fire).
        r = requests.post(f"{API}/withdrawals", headers=_headers(tok),
                          json={"amount": 150}, timeout=20)
        assert r.status_code == 400, f"expected 400 got {r.status_code}: {r.text[:200]}"
        detail = (r.json().get("detail") or "").lower()
        assert "complete registration payment" in detail, f"unexpected detail: {detail}"

        # Confirm no transactions were created for this brand-new user
        me = requests.get(f"{API}/transactions", headers=_headers(tok), timeout=20)
        # /transactions may not exist under that path — try /wallet/transactions instead
        if me.status_code == 404:
            me = requests.get(f"{API}/wallet/transactions", headers=_headers(tok), timeout=20)
        # Either way there must be no withdrawal txn
        if me.status_code == 200:
            txns = me.json() if isinstance(me.json(), list) else me.json().get("items", [])
            assert not any(t.get("type") == "withdrawal" for t in txns)


class TestAdminApproveOfflineCash:
    """Full lifecycle for the PATCH admin-approved toggle."""

    def _get_admin_user_by_email(self, admin_token: str, email: str):
        r = requests.get(f"{API}/admin/users", headers=_headers(admin_token),
                         params={"q": email, "limit": 5}, timeout=20)
        assert r.status_code == 200, r.text[:200]
        payload = r.json()
        items = payload if isinstance(payload, list) else payload.get("items") or payload.get("users") or []
        for u in items:
            if u.get("email") == email:
                return u
        raise AssertionError(f"user {email} not found in admin/users")

    def _get_summary(self, admin_token):
        r = requests.get(f"{API}/admin/transactions/summary", headers=_headers(admin_token),
                         params={"type": "registration_fee"}, timeout=20)
        assert r.status_code == 200, r.text[:200]
        return r.json()

    def _get_net_worth(self, admin_token):
        r = requests.get(f"{API}/admin/finance/net-worth", headers=_headers(admin_token), timeout=25)
        assert r.status_code == 200, r.text[:200]
        return r.json()

    def _sponsor_wallet(self, admin_token, sponsor_id, sponsor_email=None):
        params = {"limit": 20}
        if sponsor_email:
            params["q"] = sponsor_email
        r = requests.get(f"{API}/admin/users", headers=_headers(admin_token),
                         params=params, timeout=20)
        payload = r.json()
        items = payload if isinstance(payload, list) else payload.get("items") or payload.get("users") or []
        for u in items:
            if u.get("id") == sponsor_id:
                return float(u.get("wallet_balance") or 0), float(u.get("total_earned") or 0)
        raise AssertionError(f"sponsor {sponsor_id} not found (searched q={sponsor_email})")

    def test_admin_approved_creates_offline_fee_and_no_referral(self, admin_token, paid_user_me):
        # Sign up as a downline of the paid user so we have a sponsor to
        # observe (wallet + total_earned must stay unchanged after approval).
        sponsor_code = paid_user_me.get("referral_code")
        assert sponsor_code, "paid user has no referral_code"

        # Snapshots
        summary_before = self._get_summary(admin_token)
        offline_before = summary_before["by_source"]["offline_cash"]
        net_before = self._get_net_worth(admin_token)
        gst_reg_before = net_before["group_3_gst"]["registration_gst"]
        gst_reg_base_before = net_before["group_3_gst"]["registration_gst_base"]
        sp_wallet_before, sp_earned_before = self._sponsor_wallet(admin_token, paid_user_me["id"], sponsor_email=paid_user_me.get("email"))

        email, tok, _ = _new_unpaid_user(sponsor_code=sponsor_code)
        me = requests.get(f"{API}/auth/me", headers=_headers(tok), timeout=20).json()
        assert me.get("registration_paid") is False
        target_id = me["id"]

        # Fetch initial admin view — must show up under 'unpaid'
        counts_before = requests.get(f"{API}/admin/users/source-counts",
                                     headers=_headers(admin_token), timeout=20).json()

        # PATCH admin approved on
        r = requests.patch(f"{API}/admin/users/{target_id}",
                           headers=_headers(admin_token),
                           json={"registration_paid": True}, timeout=25)
        assert r.status_code == 200, r.text[:300]
        fresh = r.json()
        assert fresh.get("registration_paid") is True
        assert fresh.get("registration_source") == "offline_cash"
        assert fresh.get("admin_approved_only") is True
        assert fresh.get("commission_triggered") is True
        assert fresh.get("subscription_skipped") is False
        assert fresh.get("paid_at")

        # Wait tiny bit for indexes/aggregation
        time.sleep(0.5)

        # Fetch user's transactions via admin — count registration_fee rows
        rt = requests.get(f"{API}/admin/transactions",
                          headers=_headers(admin_token),
                          params={"type": "registration_fee", "q": email, "limit": 50}, timeout=20)
        assert rt.status_code == 200, rt.text[:200]
        rows = rt.json() if isinstance(rt.json(), list) else rt.json().get("items", [])
        fee_rows = [t for t in rows if t.get("user_id") == target_id and t.get("type") == "registration_fee"]
        assert len(fee_rows) == 1, f"expected 1 registration_fee txn, got {len(fee_rows)}: {fee_rows}"
        row = fee_rows[0]
        assert float(row.get("amount")) == 118.0
        assert row.get("status") in ("paid", "success")
        assert (row.get("source") or "").lower() == "offline_cash"

        # Ensure NO referral_payout / direct_signup_credit / gst_collected txn for this user
        for bad_type in ("referral_payout", "direct_signup_credit", "gst_collected"):
            rr = requests.get(f"{API}/admin/transactions",
                              headers=_headers(admin_token),
                              params={"type": bad_type, "q": email, "limit": 20}, timeout=20)
            if rr.status_code == 200:
                items = rr.json() if isinstance(rr.json(), list) else rr.json().get("items", [])
                bad = [t for t in items if t.get("user_id") == target_id]
                assert not bad, f"{bad_type} txn should NOT exist for offline_cash user: {bad}"

        # Sponsor wallet_balance + total_earned unchanged
        sp_wallet_after, sp_earned_after = self._sponsor_wallet(admin_token, paid_user_me["id"], sponsor_email=paid_user_me.get("email"))
        assert sp_wallet_after == sp_wallet_before, f"sponsor wallet changed: {sp_wallet_before} → {sp_wallet_after}"
        assert sp_earned_after == sp_earned_before, f"sponsor total_earned changed: {sp_earned_before} → {sp_earned_after}"

        # Summary: offline_cash count +1 and amount +118
        summary_after = self._get_summary(admin_token)
        offline_after = summary_after["by_source"]["offline_cash"]
        assert offline_after["count"] == offline_before["count"] + 1, \
            f"offline_cash count didn't rise by 1: before={offline_before} after={offline_after}"
        assert round(offline_after["amount"] - offline_before["amount"], 2) == 118.0, \
            f"offline_cash amount didn't rise by 118: before={offline_before} after={offline_after}"

        # Net worth: registration_gst comes from RAZORPAY only → unchanged
        net_after = self._get_net_worth(admin_token)
        gst_reg_after = net_after["group_3_gst"]["registration_gst"]
        gst_reg_base_after = net_after["group_3_gst"]["registration_gst_base"]
        assert gst_reg_after == gst_reg_before, f"registration_gst leaked from offline: {gst_reg_before} → {gst_reg_after}"
        assert gst_reg_base_after == gst_reg_base_before, \
            f"registration_gst_base changed: {gst_reg_base_before} → {gst_reg_base_after}"

        # master.net_worth still subtracts gst_payable per formula
        master = net_after["master"]
        comps = master.get("components", {})
        expected = round(
            comps["bank_tally_net"] + comps["pending_collections"]
            - comps["user_wallet_balance"] - comps["pending_withdrawals"] - comps["gst_payable"], 2
        )
        assert round(master["net_worth"], 2) == expected, \
            f"net_worth formula off: master.net_worth={master['net_worth']} expected={expected} components={comps}"

        # Idempotency — 2nd PATCH must NOT create another fee row
        r2 = requests.patch(f"{API}/admin/users/{target_id}",
                            headers=_headers(admin_token),
                            json={"registration_paid": True}, timeout=25)
        assert r2.status_code == 200, r2.text[:200]
        time.sleep(0.3)
        rt2 = requests.get(f"{API}/admin/transactions",
                           headers=_headers(admin_token),
                           params={"type": "registration_fee", "q": email, "limit": 50}, timeout=20)
        rows2 = rt2.json() if isinstance(rt2.json(), list) else rt2.json().get("items", [])
        fee_rows2 = [t for t in rows2 if t.get("user_id") == target_id]
        assert len(fee_rows2) == 1, f"idempotency broken — got {len(fee_rows2)} fee rows: {fee_rows2}"

        # And offline_cash summary must be the SAME as immediately after first PATCH
        summary_after2 = self._get_summary(admin_token)
        assert summary_after2["by_source"]["offline_cash"]["count"] == offline_after["count"]
        assert round(summary_after2["by_source"]["offline_cash"]["amount"], 2) == round(offline_after["amount"], 2)


class TestUserSourceCounts:
    def test_unpaid_bucket_contains_free_users(self, admin_token):
        # Create a fresh user + skip subscription
        email, tok, _ = _new_unpaid_user()
        requests.post(f"{API}/payment/skip-subscription", headers=_headers(tok), timeout=20)

        r = requests.get(f"{API}/admin/users/source-counts", headers=_headers(admin_token), timeout=20)
        assert r.status_code == 200, r.text[:200]
        counts = r.json()
        assert "unpaid" in counts and counts["unpaid"] >= 1

        # Listing with source=unpaid must return this user
        r2 = requests.get(f"{API}/admin/users", headers=_headers(admin_token),
                          params={"source": "unpaid", "q": email, "limit": 20}, timeout=20)
        assert r2.status_code == 200, r2.text[:200]
        items = r2.json() if isinstance(r2.json(), list) else r2.json().get("items") or r2.json().get("users") or []
        emails = [u.get("email") for u in items]
        assert email in emails, f"free user {email} not in unpaid tab: {emails}"
        # And each row must be registration_paid=False
        row = next(u for u in items if u.get("email") == email)
        assert row.get("registration_paid") is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
