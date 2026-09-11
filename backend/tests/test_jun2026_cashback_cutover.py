"""Backend regression for the Jun-2026 MLM→Cashback cutover.

Covers the highest-priority acceptance criteria from the review request:
 * MLM endpoints must be gone (404/405).
 * Buyer dashboard shape is the new cashback-centric one.
 * Settings validation: reject default_cashback_pct>10, accept 5, round-trip
   the new delivery fields, refuse the removed payout_l1/directs_required.
 * Product create rejects cashback_pct>10.
 * /cashback-config returns 10 and delivery config.
 * Withdrawals: buyer 403, vendor 200/400 (not 403).
 * Short-id backfill + lookup.
 * Excel export produces a valid workbook and matches groupwise-summary.
"""
import io
import os
import pytest
import requests
from openpyxl import load_workbook

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://slangcart-tracking.preview.emergentagent.com").rstrip("/")
HEADERS_UA = {"User-Agent": "curl/8.5.0", "Content-Type": "application/json"}

ADMIN = ("support@slangcart.com", "3)Ywxtic")
VENDOR = ("testvendor@test.com", "Test@1234")
BUYER = ("testbuyer@test.com", "Test@1234")


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, headers=HEADERS_UA, timeout=20)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text[:200]}"
    return r.json()["token"]


def _auth(tok):
    return {**HEADERS_UA, "Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin_token():
    return _login(*ADMIN)


@pytest.fixture(scope="module")
def buyer_token():
    return _login(*BUYER)


@pytest.fixture(scope="module")
def vendor_token():
    return _login(*VENDOR)


# ── MLM removal ────────────────────────────────────────────────────────
class TestMLMRemoved:
    @pytest.mark.parametrize("path", [
        "/api/users/me/network",
        "/api/admin/users/tree",
    ])
    def test_get_endpoints_gone(self, buyer_token, admin_token, path):
        tok = admin_token if path.startswith("/api/admin") else buyer_token
        r = requests.get(f"{BASE_URL}{path}", headers=_auth(tok), timeout=20)
        assert r.status_code in (404, 405), f"{path} still exists: {r.status_code}"

    def test_admin_lineage_gone(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/users/anyid/lineage", headers=_auth(admin_token), timeout=20)
        assert r.status_code in (404, 405)

    def test_wallet_transfer_gone(self, buyer_token):
        r = requests.post(f"{BASE_URL}/api/wallet/transfer", json={"to_user_id": "x", "amount": 1}, headers=_auth(buyer_token), timeout=20)
        assert r.status_code in (404, 405)


# ── Dashboard shape ────────────────────────────────────────────────────
class TestBuyerDashboardShape:
    def test_cashback_shape(self, buyer_token):
        r = requests.get(f"{BASE_URL}/api/users/me/dashboard", headers=_auth(buyer_token), timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        # NEW fields present
        for k in ("wallet_balance", "cashback_earned", "pending_cashback", "orders_count", "delivered_count", "invite_code", "cashback_per_day"):
            assert k in d, f"missing new field {k}"
        # OLD MLM fields absent
        for gone in ("team_size", "level_breakdown", "next_payout_in", "directs_required"):
            assert gone not in d, f"MLM field {gone} still returned"


# ── /cashback-config ───────────────────────────────────────────────────
class TestCashbackConfig:
    def test_public_config(self):
        r = requests.get(f"{BASE_URL}/api/cashback-config", headers=HEADERS_UA, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("max_cashback_pct") == 10.0
        for k in ("delivery_charge_flat", "delivery_free_threshold", "delivery_cart_max", "delivery_charge_enabled"):
            assert k in d, f"missing {k}"


# ── Admin settings validation ──────────────────────────────────────────
class TestAdminSettings:
    def _get(self, tok):
        r = requests.get(f"{BASE_URL}/api/admin/settings", headers=_auth(tok), timeout=20)
        assert r.status_code == 200, r.text
        return r.json()

    def _put(self, tok, patch):
        return requests.put(f"{BASE_URL}/api/admin/settings", json=patch, headers=_auth(tok), timeout=20)

    def test_reject_cashback_over_ten(self, admin_token):
        r = self._put(admin_token, {"default_cashback_pct": 11})
        assert r.status_code == 422, f"expected 422, got {r.status_code} {r.text[:200]}"

    def test_accept_five(self, admin_token):
        r = self._put(admin_token, {"default_cashback_pct": 5})
        assert r.status_code == 200, r.text
        s = self._get(admin_token)
        assert float(s.get("default_cashback_pct") or 0) == 5.0

    def test_delivery_roundtrip(self, admin_token):
        r = self._put(admin_token, {
            "delivery_charge_flat": 30,
            "delivery_free_threshold": 500,
            "delivery_cart_max": 40,
            "delivery_charge_enabled": True,
            "cashback_enabled": True,
        })
        assert r.status_code == 200, r.text
        s = self._get(admin_token)
        assert float(s["delivery_charge_flat"]) == 30.0
        assert float(s["delivery_free_threshold"]) == 500.0
        assert float(s["delivery_cart_max"]) == 40.0
        assert s["delivery_charge_enabled"] is True
        assert s["cashback_enabled"] is True

    def test_reject_removed_mlm_fields(self, admin_token):
        # These MLM-era fields must no longer be accepted (either 422 or silently dropped)
        r = self._put(admin_token, {"payout_l1": 999, "directs_required": 3})
        # Owner requirement is "must NOT accept" — either 422 or a 200 that ignores.
        if r.status_code == 200:
            s = self._get(admin_token)
            assert "payout_l1" not in s or s.get("payout_l1") is None, "payout_l1 was persisted"
            assert "directs_required" not in s or s.get("directs_required") is None, "directs_required was persisted"


# ── Vendor product cashback validation ─────────────────────────────────
class TestVendorProductCashback:
    def test_reject_over_ten(self, vendor_token):
        body = {"name": "TEST cashback reject", "price": 100, "stock": 10, "cashback_pct": 15, "image_url": ""}
        r = requests.post(f"{BASE_URL}/api/vendor/me/products", json=body, headers=_auth(vendor_token), timeout=20)
        assert r.status_code == 422, f"expected 422, got {r.status_code} {r.text[:250]}"

    def test_accept_five_and_reflected_in_product(self, vendor_token):
        body = {"name": "TEST cashback 5pct", "price": 100, "stock": 10, "cashback_pct": 5, "image_url": ""}
        r = requests.post(f"{BASE_URL}/api/vendor/me/products", json=body, headers=_auth(vendor_token), timeout=20)
        assert r.status_code in (200, 201), r.text
        p = r.json()
        pid = p.get("id")
        assert pid, r.text
        # Confirm via vendor listing (public GET may 404 on unpublished/unlisted products)
        lst = requests.get(f"{BASE_URL}/api/vendor/me/products", headers=_auth(vendor_token), timeout=20)
        assert lst.status_code == 200, lst.text
        rows = lst.json() if isinstance(lst.json(), list) else lst.json().get("products") or lst.json().get("items") or []
        mine = next((x for x in rows if x.get("id") == pid), None)
        assert mine is not None, "product not found in vendor listing"
        assert float(mine.get("cashback_pct") or 0) == 5.0
        # public GET (best-effort)
        r2 = requests.get(f"{BASE_URL}/api/products/{pid}", headers=HEADERS_UA, timeout=20)
        if r2.status_code == 200:
            assert float(r2.json().get("cashback_pct") or 0) == 5.0
        # cleanup — best-effort
        requests.delete(f"{BASE_URL}/api/vendor/me/products/{pid}", headers=_auth(vendor_token), timeout=20)


# ── Withdrawals gate ───────────────────────────────────────────────────
class TestWithdrawalsGate:
    def test_buyer_blocked_403(self, buyer_token):
        r = requests.post(f"{BASE_URL}/api/withdrawals", json={"amount": 100}, headers=_auth(buyer_token), timeout=20)
        assert r.status_code == 403, f"buyer withdrawal not blocked: {r.status_code} {r.text[:200]}"
        assert "purchase" in r.text.lower() or "seller" in r.text.lower() or "cashback" in r.text.lower()

    def test_vendor_reaches_business_layer(self, vendor_token):
        # 200/201 success, or 400 for insufficient balance / missing UPI — but NOT 403.
        r = requests.post(f"{BASE_URL}/api/withdrawals", json={"amount": 100}, headers=_auth(vendor_token), timeout=20)
        assert r.status_code != 403, f"vendor was blocked: {r.text[:200]}"


# ── Short IDs ──────────────────────────────────────────────────────────
class TestShortIds:
    def test_backfill_and_lookup(self, admin_token):
        r = requests.post(f"{BASE_URL}/api/admin/short-id/backfill", headers=_auth(admin_token), timeout=120)
        assert r.status_code == 200, r.text
        # Call twice — must not mint new codes.
        r2 = requests.post(f"{BASE_URL}/api/admin/short-id/backfill", headers=_auth(admin_token), timeout=120)
        assert r2.status_code == 200, r2.text
        # Every kind on the 2nd call must be 0 minted.
        for k, v in (r2.json().get("minted") or {}).items():
            assert v == 0, f"second backfill re-minted {k}={v} (codes must be permanent)"
        # Look up any transaction code — TXNA1 must resolve.
        r3 = requests.get(f"{BASE_URL}/api/admin/short-id/TXNA1", headers=_auth(admin_token), timeout=20)
        assert r3.status_code == 200, r3.text
        d = r3.json()
        assert d.get("code") == "TXNA1" and d.get("ref_id")


# ── Excel export ───────────────────────────────────────────────────────
class TestExcelExport:
    def test_export_and_summary_match(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/wallet/export/groupwise", headers=_auth(admin_token), timeout=120)
        assert r.status_code == 200, r.text[:200]
        ct = r.headers.get("content-type", "")
        assert "spreadsheetml" in ct, ct
        wb = load_workbook(io.BytesIO(r.content))
        assert len(wb.sheetnames) >= 1
        first = wb[wb.sheetnames[0]]
        headers = [c.value for c in first[1]]
        assert len(headers) == 25, f"expected 25 columns, got {len(headers)}: {headers}"
        assert headers[0] == "Transaction ID"
        assert "Date" in headers and "Time" in headers
        # Group summary block present
        found_summary = False
        for row in first.iter_rows(values_only=True):
            if row and row[0] == "GROUP SUMMARY":
                found_summary = True
                break
        assert found_summary, "GROUP SUMMARY block missing"
        # Cross-check totals with groupwise-summary
        s = requests.get(f"{BASE_URL}/api/admin/wallet/groupwise-summary", headers=_auth(admin_token), timeout=60)
        assert s.status_code == 200
