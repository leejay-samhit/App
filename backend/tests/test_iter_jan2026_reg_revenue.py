"""Jan-2026 iteration — Registration-fee revenue + Users source tabs +
GST maths + Admin Approved toggle safety tests.

Covers the review request in `iteration_N.json`:
  * GET /api/admin/transactions (server-side type + source + q filters)
  * GET /api/admin/transactions/summary (per-source totals)
  * GET /api/admin/users?source=... + /admin/users/source-counts
  * GET /api/admin/export/registration-fees (+ users export)
  * GET /api/admin/finance/net-worth (registration_gst = razorpay×18/118)
  * GET /api/admin/finance/groups/group_3_gst/transactions
  * PATCH /api/admin/users/{id} — Admin Approved must NOT credit uplines
"""
import os
import csv
import io
import time
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL missing from env"
BASE_URL = BASE_URL.rstrip("/")

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "support@slangcart.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "3)Ywxtic")


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                      timeout=20)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text[:200]}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, "no token in admin login response"
    return tok


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


# ---------- Registration-fee revenue: server-side filter ----------
class TestAdminTransactionsRegistrationFee:
    def test_type_filter_returns_only_registration_fee_rows(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/admin/transactions",
                         params={"type": "registration_fee", "limit": 20, "offset": 0},
                         headers=admin_headers, timeout=20)
        assert r.status_code == 200, r.text[:400]
        rows = r.json()
        assert isinstance(rows, list)
        assert len(rows) > 0, "no registration_fee rows returned"
        for t in rows:
            assert t.get("type") == "registration_fee", f"non-reg row leaked: {t.get('type')}"
            # enriched fields expected
            assert "short_ref" in t
            assert t.get("short_ref", "").startswith("REG-"), t.get("short_ref")
            assert "registration_source" in t
        # collect ids to check pagination
        ids_page1 = [t.get("id") for t in rows]
        # verify offset works
        r2 = requests.get(f"{BASE_URL}/api/admin/transactions",
                          params={"type": "registration_fee", "limit": 5, "offset": 5},
                          headers=admin_headers, timeout=20)
        assert r2.status_code == 200
        rows2 = r2.json()
        if len(ids_page1) > 5:
            # page 2 should not contain first 5 ids
            page2_ids = {t.get("id") for t in rows2}
            first5 = set(ids_page1[:5])
            assert not (first5 & page2_ids), "pagination overlap detected"

    def test_source_razorpay_filter(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/admin/transactions",
                         params={"type": "registration_fee", "source": "razorpay", "limit": 50},
                         headers=admin_headers, timeout=20)
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) >= 3, f"expected >=3 razorpay reg rows, got {len(rows)}"
        for t in rows:
            assert t.get("registration_source") == "razorpay", t.get("registration_source")

    def test_source_upi_manual_filter(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/admin/transactions",
                         params={"type": "registration_fee", "source": "upi_manual", "limit": 50},
                         headers=admin_headers, timeout=20)
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) >= 2
        for t in rows:
            assert t.get("registration_source") == "upi_manual"

    def test_source_offline_cash_filter(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/admin/transactions",
                         params={"type": "registration_fee", "source": "offline_cash", "limit": 50},
                         headers=admin_headers, timeout=20)
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) >= 2
        for t in rows:
            assert t.get("registration_source") == "offline_cash"

    def test_search_q_by_name(self, admin_headers):
        # Seed users start with "Seed razorpay 1"
        r = requests.get(f"{BASE_URL}/api/admin/transactions",
                         params={"type": "registration_fee", "q": "Seed razorpay 1", "limit": 50},
                         headers=admin_headers, timeout=20)
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) >= 1
        assert any("Seed razorpay 1" in (t.get("user_name") or "") for t in rows)


# ---------- Registration-fee summary ----------
class TestAdminTransactionsSummary:
    def test_summary_totals(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/admin/transactions/summary",
                         params={"type": "registration_fee"},
                         headers=admin_headers, timeout=20)
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        assert data.get("type") == "registration_fee"
        total = data.get("total") or {}
        by_source = data.get("by_source") or {}
        # Seed contribution: raz=3×118=354, upi=2×118=236, offline=2×118=236
        assert by_source["razorpay"]["count"] >= 3
        assert by_source["upi_manual"]["count"] >= 2
        assert by_source["offline_cash"]["count"] >= 2
        # amounts consistent
        assert by_source["razorpay"]["amount"] >= 354.0
        assert by_source["upi_manual"]["amount"] >= 236.0
        assert by_source["offline_cash"]["amount"] >= 236.0
        # totals must equal sum of buckets
        summed_count = sum(v["count"] for v in by_source.values())
        summed_amt = round(sum(v["amount"] for v in by_source.values()), 2)
        assert total["count"] == summed_count
        assert round(total["amount"], 2) == summed_amt


# ---------- Users source filter + counts ----------
class TestAdminUsersSourceFilter:
    def test_users_source_counts(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/admin/users/source-counts",
                         headers=admin_headers, timeout=20)
        assert r.status_code == 200
        c = r.json()
        for k in ("all", "razorpay", "upi_manual", "offline_cash", "unpaid"):
            assert k in c
            assert isinstance(c[k], int)
        assert c["razorpay"] >= 3
        assert c["upi_manual"] >= 2
        assert c["offline_cash"] >= 2
        assert c["all"] >= c["razorpay"] + c["upi_manual"] + c["offline_cash"]

    def test_users_source_razorpay(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/admin/users",
                         params={"source": "razorpay", "limit": 50},
                         headers=admin_headers, timeout=20)
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) >= 3
        for u in rows:
            assert u.get("registration_paid") is True
            assert u.get("registration_source") == "razorpay"

    def test_users_source_upi_manual(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/admin/users",
                         params={"source": "upi_manual", "limit": 50},
                         headers=admin_headers, timeout=20)
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) >= 2
        for u in rows:
            assert u.get("registration_source") == "upi_manual"

    def test_users_source_unpaid(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/admin/users",
                         params={"source": "unpaid", "limit": 50},
                         headers=admin_headers, timeout=20)
        assert r.status_code == 200
        rows = r.json()
        for u in rows:
            assert u.get("registration_paid") is not True


# ---------- CSV Exports ----------
class TestExports:
    def _parse_csv(self, text):
        return list(csv.reader(io.StringIO(text)))

    def test_export_registration_fees_all(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/admin/export/registration-fees",
                         headers=admin_headers, timeout=30)
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")
        rows = self._parse_csv(r.text)
        assert len(rows) >= 2  # header + at least 1 row
        header = rows[0]
        expected = ["reference", "paid_on", "name", "member_id", "email", "phone",
                    "join_source", "amount", "gst_18_inclusive", "net_excl_gst",
                    "status", "razorpay_payment_id", "razorpay_order_id",
                    "utr_bank_ref", "sponsor_code", "description"]
        assert header == expected, f"header mismatch: {header}"
        # find a razorpay row and check GST math (118 -> 18)
        idx = {h: i for i, h in enumerate(header)}
        raz_rows = [r for r in rows[1:] if r[idx["join_source"]] == "Razorpay gateway"]
        assert len(raz_rows) >= 3
        for row in raz_rows:
            amt = float(row[idx["amount"]])
            gst = float(row[idx["gst_18_inclusive"]])
            net = float(row[idx["net_excl_gst"]])
            expected_gst = round(amt * 18 / 118, 2)
            assert gst == expected_gst, f"gst math wrong: amt={amt} gst={gst} expected={expected_gst}"
            assert round(amt - gst, 2) == net
            # razorpay rows should have payment id
            assert row[idx["razorpay_payment_id"]], "razorpay_payment_id missing"

    def test_export_registration_fees_source_filter(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/admin/export/registration-fees",
                         params={"source": "razorpay"},
                         headers=admin_headers, timeout=30)
        assert r.status_code == 200
        rows = self._parse_csv(r.text)
        header = rows[0]
        idx = {h: i for i, h in enumerate(header)}
        for row in rows[1:]:
            assert row[idx["join_source"]] == "Razorpay gateway", row

    def test_export_users_no_literal_none(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/admin/export/users",
                         params={"source": "upi_manual"},
                         headers=admin_headers, timeout=30)
        assert r.status_code == 200
        rows = self._parse_csv(r.text)
        header = rows[0]
        assert "join_source" in header
        assert "admin_approved" in header
        # check no literal "None" (Python's None stringified)
        for row in rows[1:]:
            for cell in row:
                assert cell != "None", f"literal 'None' found in row: {row}"
            # join_source for upi_manual should say 'UPI manual transfer'
            js_idx = header.index("join_source")
            aa_idx = header.index("admin_approved")
            assert row[js_idx] == "UPI manual transfer"
            assert row[aa_idx] == "Yes"


# ---------- Net Worth / GST maths ----------
class TestNetWorthAndGST:
    def test_net_worth_gst_registration_from_razorpay_only(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/admin/finance/net-worth",
                         headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        g3 = d["group_3_gst"]
        by_src = d["group_1_revenue"]["by_source"]
        raz_amt = float(by_src["razorpay"]["amount"])
        expected_gst = round(raz_amt * 18 / 118, 2)
        assert g3["registration_gst"] == expected_gst, \
            f"registration_gst {g3['registration_gst']} != {expected_gst}"
        # collected == registration_gst + other_gst
        assert round(g3["registration_gst"] + g3["other_gst"], 2) == g3["collected"]
        # payable == collected - paid
        assert round(g3["collected"] - g3["paid"], 2) == g3["payable"]
        # master.net_worth formula check
        m = d["master"]
        comp = m["components"]
        expected_nw = round(
            comp["bank_tally_net"] + comp["pending_collections"]
            - comp["user_wallet_balance"] - comp["pending_withdrawals"]
            - comp["gst_payable"], 2,
        )
        assert m["net_worth"] == expected_nw

    def test_group3_gst_drilldown_razorpay_only(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/admin/finance/groups/group_3_gst/transactions",
                         params={"limit": 200},
                         headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        items = data["items"]
        # There should be at least 3 razorpay entry-gst lines
        entry_lines = [i for i in items if i.get("type") == "gst_collected · registration"]
        assert len(entry_lines) >= 3, f"expected >=3 razorpay entry GST lines, got {len(entry_lines)}"
        for line in entry_lines:
            assert line.get("source") == "razorpay"
            # 118 -> 18
            assert abs(line["amount"] - 18.0) < 0.02, f"expected 18.00 gst, got {line['amount']}"
            assert "Entry GST 18% on" in (line.get("description") or "")


# ---------- Admin Approved toggle safety ----------
class TestAdminApprovedToggle:
    def test_toggle_registration_paid_no_referral_side_effects(self, admin_headers):
        """Create an unpaid user with a sponsor, flip registration_paid=true
        via PATCH, verify NO referral_payout / direct_signup_credit / registration_fee
        transactions were created and sponsor wallet balance did not move."""
        # Create sponsor first via admin
        sponsor_email = f"test_sponsor_{int(time.time())}@example.com"
        s = requests.post(f"{BASE_URL}/api/admin/create-user",
                          headers=admin_headers, timeout=20,
                          json={"name": "T Sponsor", "email": sponsor_email,
                                "password": "Passw0rd!", "registration_paid": True})
        if s.status_code == 404:
            # fallback path — /api/auth/register + admin approve
            s = requests.post(f"{BASE_URL}/api/auth/register",
                              json={"name": "T Sponsor", "email": sponsor_email,
                                    "password": "Passw0rd!"}, timeout=20)
        assert s.status_code in (200, 201), s.text[:300]
        # fetch sponsor
        u_list = requests.get(f"{BASE_URL}/api/admin/users",
                              params={"q": sponsor_email, "limit": 5},
                              headers=admin_headers, timeout=20).json()
        assert u_list, "sponsor not created"
        sponsor = u_list[0]
        sponsor_id = sponsor["id"]
        sponsor_ref = sponsor.get("referral_code")
        sponsor_wallet_before = float(sponsor.get("wallet_balance") or 0)
        sponsor_earned_before = float(sponsor.get("total_earned") or 0)

        # Approve sponsor if not already
        if not sponsor.get("registration_paid"):
            requests.patch(f"{BASE_URL}/api/admin/users/{sponsor_id}",
                           headers=admin_headers, timeout=20,
                           json={"registration_paid": True})

        # Register a downline unpaid user referencing sponsor
        downline_email = f"test_dnl_{int(time.time())}@example.com"
        d = requests.post(f"{BASE_URL}/api/auth/register",
                          json={"name": "T Downline", "email": downline_email,
                                "password": "Passw0rd!", "referral_code": sponsor_ref},
                          timeout=20)
        assert d.status_code in (200, 201), d.text[:300]

        dnl_list = requests.get(f"{BASE_URL}/api/admin/users",
                                params={"q": downline_email, "limit": 5},
                                headers=admin_headers, timeout=20).json()
        assert dnl_list, "downline not created"
        downline = dnl_list[0]
        downline_id = downline["id"]
        assert downline.get("registration_paid") is not True

        # Count txns for sponsor+downline BEFORE
        def _txns_for(uid):
            r = requests.get(f"{BASE_URL}/api/admin/transactions",
                             params={"limit": 200}, headers=admin_headers, timeout=20).json()
            return [t for t in r if t.get("user_id") == uid]

        txns_sp_before = _txns_for(sponsor_id)
        txns_dl_before = _txns_for(downline_id)

        # Flip Admin Approved (registration_paid=true) on downline
        patch = requests.patch(f"{BASE_URL}/api/admin/users/{downline_id}",
                               headers=admin_headers, timeout=20,
                               json={"registration_paid": True})
        assert patch.status_code == 200, patch.text[:300]
        fresh = patch.json()
        assert fresh.get("registration_paid") is True
        assert fresh.get("admin_approved_only") is True
        assert fresh.get("commission_triggered") is True

        # Compare sponsor wallet + txns AFTER
        sponsor_after = requests.get(f"{BASE_URL}/api/admin/users",
                                     params={"q": sponsor_email, "limit": 5},
                                     headers=admin_headers, timeout=20).json()[0]
        assert float(sponsor_after.get("wallet_balance") or 0) == sponsor_wallet_before, \
            "sponsor wallet_balance changed after Admin Approved toggle"
        assert float(sponsor_after.get("total_earned") or 0) == sponsor_earned_before, \
            "sponsor total_earned changed after Admin Approved toggle"

        txns_sp_after = _txns_for(sponsor_id)
        txns_dl_after = _txns_for(downline_id)

        forbidden_types = {"referral_payout", "direct_signup_credit", "registration_fee"}
        new_sp = [t for t in txns_sp_after if t not in txns_sp_before]
        new_dl = [t for t in txns_dl_after if t not in txns_dl_before]
        for t in new_sp:
            assert t.get("type") not in forbidden_types, f"sponsor got {t.get('type')} txn from Admin Approved!"
        for t in new_dl:
            assert t.get("type") not in forbidden_types, f"downline got {t.get('type')} txn from Admin Approved!"

        # Cleanup — best effort
        try:
            requests.delete(f"{BASE_URL}/api/admin/users/{downline_id}",
                            headers=admin_headers, timeout=10)
            requests.delete(f"{BASE_URL}/api/admin/users/{sponsor_id}",
                            headers=admin_headers, timeout=10)
        except Exception:
            pass
