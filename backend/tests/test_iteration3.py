"""Iteration 3 backend tests: admin user mgmt + dynamic settings."""
import os
import uuid
import pytest
import requests
from conftest import auth_headers

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://network-pay-1.preview.emergentagent.com").rstrip("/")


def _register(email_prefix="u", referral=None):
    email = f"TEST_{email_prefix}_{uuid.uuid4().hex[:6]}@test.com"
    body = {"name": email_prefix, "email": email, "password": "Pass@123", "phone": "9999999999"}
    if referral:
        body["referral_code"] = referral
    r = requests.post(f"{BASE}/api/auth/register", json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ---------- Settings endpoints ----------
class TestAdminSettings:
    def test_get_settings_shape(self, admin_token):
        r = requests.get(f"{BASE}/api/admin/settings", headers=auth_headers(admin_token))
        assert r.status_code == 200
        d = r.json()
        for k in ["registration_fee", "payout_l1", "payout_l2", "payout_l3", "directs_required"]:
            assert k in d
        # restore defaults at start of suite
        requests.put(f"{BASE}/api/admin/settings", headers=auth_headers(admin_token),
                     json={"registration_fee": 100, "payout_l1": 400, "payout_l2": 100,
                           "payout_l3": 50, "directs_required": 4})

    def test_put_settings_partial_update(self, admin_token):
        r = requests.put(f"{BASE}/api/admin/settings", headers=auth_headers(admin_token),
                         json={"payout_l1": 250})
        assert r.status_code == 200
        assert r.json()["payout_l1"] == 250
        # other fields preserved
        assert r.json()["registration_fee"] == 100
        # restore
        requests.put(f"{BASE}/api/admin/settings", headers=auth_headers(admin_token),
                     json={"payout_l1": 400})

    def test_put_settings_non_admin_403(self, admin_token):
        u = _register("nonadmin")
        r = requests.put(f"{BASE}/api/admin/settings", headers=auth_headers(u["token"]),
                         json={"payout_l1": 999})
        assert r.status_code == 403

    def test_settings_drives_payment_flow(self, admin_token):
        # Set new structure: directs_required=2, l1=200
        r = requests.put(f"{BASE}/api/admin/settings", headers=auth_headers(admin_token),
                         json={"directs_required": 2, "payout_l1": 200, "payout_l2": 50,
                               "payout_l3": 25, "registration_fee": 100})
        assert r.status_code == 200

        # Sponsor signs up under admin and pays
        sponsor = _register("sp", referral="ADMIN001")
        rp = requests.post(f"{BASE}/api/payment/register-fee", headers=auth_headers(sponsor["token"]))
        assert rp.status_code == 200
        sponsor_code = sponsor["user"]["referral_code"]

        # Two directs under sponsor pay -> sponsor should get L1 payout (₹200) on 2nd
        d1 = _register("d1", referral=sponsor_code)
        requests.post(f"{BASE}/api/payment/register-fee", headers=auth_headers(d1["token"]))
        # After 1 direct: sponsor has no L1 yet (count=1, needs 2)
        dash1 = requests.get(f"{BASE}/api/users/me/dashboard", headers=auth_headers(sponsor["token"])).json()
        assert dash1["wallet_balance"] == 0
        assert dash1["direct_referrals"] == 1

        d2 = _register("d2", referral=sponsor_code)
        requests.post(f"{BASE}/api/payment/register-fee", headers=auth_headers(d2["token"]))
        dash2 = requests.get(f"{BASE}/api/users/me/dashboard", headers=auth_headers(sponsor["token"])).json()
        # After 2 directs, sponsor gets L1 payout = ₹200
        assert dash2["wallet_balance"] == 200, f"expected 200 got {dash2}"
        assert dash2["directs_required"] == 2
        assert dash2["level_payouts"]["l1"] == 200
        assert dash2["level_payouts"]["l2"] == 50

        # restore defaults
        requests.put(f"{BASE}/api/admin/settings", headers=auth_headers(admin_token),
                     json={"registration_fee": 100, "payout_l1": 400, "payout_l2": 100,
                           "payout_l3": 50, "directs_required": 4})


# ---------- Admin user mgmt ----------
class TestAdminUserMgmt:
    def test_patch_user_basic_fields(self, admin_token):
        u = _register("patchme")
        uid = u["user"]["id"]
        r = requests.patch(f"{BASE}/api/admin/users/{uid}", headers=auth_headers(admin_token),
                           json={"name": "Renamed", "phone": "8888888888", "wallet_balance": 555.0,
                                 "registration_paid": True, "upi_id": "test@upi"})
        assert r.status_code == 200
        d = r.json()
        assert d["name"] == "Renamed"
        assert d["phone"] == "8888888888"
        assert d["wallet_balance"] == 555.0
        assert d["registration_paid"] is True
        assert d["upi_id"] == "test@upi"
        # notification created
        notifs = requests.get(f"{BASE}/api/notifications/me", headers=auth_headers(u["token"])).json()
        assert any(n["kind"] == "account" for n in notifs)

    def test_patch_email_uniqueness(self, admin_token):
        u1 = _register("u1")
        u2 = _register("u2")
        r = requests.patch(f"{BASE}/api/admin/users/{u2['user']['id']}",
                           headers=auth_headers(admin_token),
                           json={"email": u1["user"]["email"]})
        assert r.status_code == 400
        assert "already" in r.json()["detail"].lower()

    def test_patch_demote_last_admin_blocked(self, admin_token):
        # find admin id
        users = requests.get(f"{BASE}/api/admin/users", headers=auth_headers(admin_token)).json()
        admins = [x for x in users if x["role"] == "admin"]
        if len(admins) == 1:
            r = requests.patch(f"{BASE}/api/admin/users/{admins[0]['id']}",
                               headers=auth_headers(admin_token), json={"role": "user"})
            assert r.status_code == 400
            assert "last admin" in r.json()["detail"].lower()
        else:
            pytest.skip("multiple admins exist")

    def test_reset_password(self, admin_token):
        u = _register("pwreset")
        new_pw = "NewPass@456"
        r = requests.post(f"{BASE}/api/admin/users/{u['user']['id']}/reset-password",
                          headers=auth_headers(admin_token), json={"new_password": new_pw})
        assert r.status_code == 200
        # login with new password
        login = requests.post(f"{BASE}/api/auth/login",
                              json={"email": u["user"]["email"], "password": new_pw})
        assert login.status_code == 200

    def test_reset_password_min_length(self, admin_token):
        u = _register("pwshort")
        r = requests.post(f"{BASE}/api/admin/users/{u['user']['id']}/reset-password",
                          headers=auth_headers(admin_token), json={"new_password": "abc"})
        assert r.status_code == 422  # pydantic min_length

    def test_delete_user(self, admin_token):
        u = _register("delme")
        uid = u["user"]["id"]
        r = requests.delete(f"{BASE}/api/admin/users/{uid}", headers=auth_headers(admin_token))
        assert r.status_code == 200
        # verify gone
        users = requests.get(f"{BASE}/api/admin/users", headers=auth_headers(admin_token)).json()
        assert not any(x["id"] == uid for x in users)

    def test_delete_self_blocked(self, admin_token):
        # admin id
        me = requests.get(f"{BASE}/api/auth/me", headers=auth_headers(admin_token)).json()
        r = requests.delete(f"{BASE}/api/admin/users/{me['id']}", headers=auth_headers(admin_token))
        assert r.status_code == 400
        assert "yourself" in r.json()["detail"].lower()

    def test_non_admin_forbidden(self, admin_token):
        u = _register("regular")
        # PATCH
        r = requests.patch(f"{BASE}/api/admin/users/{u['user']['id']}",
                           headers=auth_headers(u["token"]), json={"name": "x"})
        assert r.status_code == 403
        # DELETE
        r = requests.delete(f"{BASE}/api/admin/users/{u['user']['id']}", headers=auth_headers(u["token"]))
        assert r.status_code == 403
        # reset-password
        r = requests.post(f"{BASE}/api/admin/users/{u['user']['id']}/reset-password",
                          headers=auth_headers(u["token"]), json={"new_password": "abcdef"})
        assert r.status_code == 403
        # settings GET
        r = requests.get(f"{BASE}/api/admin/settings", headers=auth_headers(u["token"]))
        assert r.status_code == 403

    def test_dashboard_reflects_settings(self, admin_token):
        # Update settings
        requests.put(f"{BASE}/api/admin/settings", headers=auth_headers(admin_token),
                     json={"directs_required": 3, "payout_l1": 333, "payout_l2": 33, "payout_l3": 3})
        u = _register("dash")
        d = requests.get(f"{BASE}/api/users/me/dashboard", headers=auth_headers(u["token"])).json()
        assert d["directs_required"] == 3
        assert d["level_payouts"]["l1"] == 333
        assert d["level_payouts"]["l2"] == 33
        assert d["level_payouts"]["l3"] == 3
        # restore
        requests.put(f"{BASE}/api/admin/settings", headers=auth_headers(admin_token),
                     json={"registration_fee": 100, "payout_l1": 400, "payout_l2": 100,
                           "payout_l3": 50, "directs_required": 4})
