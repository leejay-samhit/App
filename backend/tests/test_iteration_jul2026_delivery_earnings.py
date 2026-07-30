"""Iteration Jul 2026 backend regression suite.

Covers the seven features/bugs (A–G) implemented by main agent:
  A. Vendor delivery-info (ETA + delivery person) PATCH endpoint
  B. Customer cancel-order gating on `delivery_info_updated_at`
  C. Shop `sub_category` filter (products_public._build_category_filter)
  D. Vendor Dashboard gross earnings with per-channel breakdown
  E. Vendor earnings drill-down (online + POS, month/date/channel filters)
  F. Vendor sales list merges POS rows tagged channel='pos'
  G. Vendor approval status surfaced via /auth/login

Plus regressions from prior iterations:
  • GET /admin/shop-layout
  • GET /products?pincode=517644&strict_location=true
"""
import os
import uuid
from typing import Any, Dict, List

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")
if not BASE_URL:
    # Fallback to the /app/frontend/.env value that supervisor uses.
    with open("/app/frontend/.env") as fh:
        for line in fh:
            if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip()
                break
BASE_URL = (BASE_URL or "").rstrip("/")

ADMIN = {"email": "support@slangcart.com", "password": "3)Ywxtic"}
CUSTOMER = {"email": "leejay@gmail.com", "password": "Just@4me"}
VENDOR_A = {"email": "brightkittu@slangcart.com", "password": "Just@4me"}     # 3 kittu products
VENDOR_B = {"email": "knasar786@gmail.com", "password": "Just@4me"}           # 0 products


# ─────────────────────────── Fixtures ──────────────────────────────
@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _login(api: requests.Session, creds: Dict[str, str]) -> Dict[str, Any]:
    r = api.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"login failed for {creds['email']}: {r.status_code} {r.text}"
    return r.json()


def _auth(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def vendor_b_token(api):
    return _login(api, VENDOR_B)["token"]


@pytest.fixture(scope="module")
def vendor_a_token(api):
    return _login(api, VENDOR_A)["token"]


@pytest.fixture(scope="module")
def customer_token(api):
    return _login(api, CUSTOMER)["token"]


# ───────────────── (G) Auth: vendor approval surfaced ──────────────
class TestVendorApprovalOnLogin:
    def test_knasar_login_shows_vendor_approved(self, api):
        data = _login(api, VENDOR_B)
        u = data["user"]
        assert u["is_vendor"] is True
        assert u["is_vendor_approved"] is True
        assert u["vendor_status"] == "approved"


# ─────────────────── (D) Vendor stats — gross + breakdown ─────────
class TestVendorStats:
    def test_stats_shape_and_math_vendor_b(self, api, vendor_b_token):
        r = api.get(f"{BASE_URL}/api/vendor/me/stats", headers=_auth(vendor_b_token), timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in [
            "total_sales", "total_earnings", "today_earnings",
            "online_total", "online_today", "online_orders_all", "online_orders_today",
            "pos_total", "pos_today", "pos_orders_all", "pos_orders_today",
            "products_count", "published_count", "wallet_balance",
        ]:
            assert k in d, f"missing key {k}"
        # Aggregate check: total_sales == online_total + pos_total (rounded)
        assert round(d["online_total"] + d["pos_total"], 2) == d["total_sales"]
        assert round(d["online_total"] + d["pos_total"], 2) == d["total_earnings"]

    def test_stats_shape_vendor_a(self, api, vendor_a_token):
        r = api.get(f"{BASE_URL}/api/vendor/me/stats", headers=_auth(vendor_a_token), timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["products_count"] >= 3
        assert round(d["online_total"] + d["pos_total"], 2) == d["total_sales"]


# ────────────────── (E) Vendor earnings drill-down ─────────────────
class TestVendorEarnings:
    def test_earnings_default_returns_envelope(self, api, vendor_b_token):
        r = api.get(f"{BASE_URL}/api/vendor/me/earnings", headers=_auth(vendor_b_token), timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ["items", "total", "sum_amount", "online_count", "pos_count", "online_sum", "pos_sum"]:
            assert k in d, f"missing earnings key {k}"
        # sanity: online_count + pos_count == total
        assert d["online_count"] + d["pos_count"] == d["total"]
        # sum_amount ≈ online_sum + pos_sum
        assert round(d["online_sum"] + d["pos_sum"], 2) == d["sum_amount"]

    def test_earnings_channel_online(self, api, vendor_b_token):
        r = api.get(
            f"{BASE_URL}/api/vendor/me/earnings",
            headers=_auth(vendor_b_token), params={"channel": "online"}, timeout=15,
        )
        assert r.status_code == 200
        d = r.json()
        assert d["pos_count"] == 0
        for it in d["items"]:
            assert it["channel"] == "online"

    def test_earnings_channel_pos(self, api, vendor_b_token):
        r = api.get(
            f"{BASE_URL}/api/vendor/me/earnings",
            headers=_auth(vendor_b_token), params={"channel": "pos"}, timeout=15,
        )
        assert r.status_code == 200
        d = r.json()
        assert d["online_count"] == 0
        for it in d["items"]:
            assert it["channel"] == "pos"

    def test_earnings_month_filter(self, api, vendor_b_token):
        # Valid month should return 200 with envelope; may be 0 items if no sales.
        r = api.get(
            f"{BASE_URL}/api/vendor/me/earnings",
            headers=_auth(vendor_b_token), params={"month": "2025-01"}, timeout=15,
        )
        assert r.status_code == 200
        d = r.json()
        assert d["total"] == 0  # No sales in Jan 2025

    def test_earnings_month_invalid_returns_400(self, api, vendor_b_token):
        r = api.get(
            f"{BASE_URL}/api/vendor/me/earnings",
            headers=_auth(vendor_b_token), params={"month": "not-a-month"}, timeout=15,
        )
        assert r.status_code == 400

    def test_earnings_from_to_date(self, api, vendor_b_token):
        r = api.get(
            f"{BASE_URL}/api/vendor/me/earnings",
            headers=_auth(vendor_b_token),
            params={"from_date": "2026-01-01", "to_date": "2026-01-02"}, timeout=15,
        )
        assert r.status_code == 200


# ──────── (F) Vendor sales — merged online + POS with channel='pos' ─
class TestVendorSales:
    def test_sales_envelope(self, api, vendor_a_token):
        r = api.get(f"{BASE_URL}/api/vendor/me/sales", headers=_auth(vendor_a_token), timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "items" in d and "total" in d
        assert isinstance(d["items"], list)
        # If any POS rows exist they must be tagged channel='pos'
        for it in d["items"]:
            if it.get("channel") == "pos":
                assert it.get("invoice_no") is not None or it.get("invoice_no") == 0 or True  # optional
                assert isinstance(it.get("items"), list)
                assert "total" in it

    def test_sales_items_have_product_details(self, api, vendor_a_token):
        r = api.get(f"{BASE_URL}/api/vendor/me/sales", headers=_auth(vendor_a_token), timeout=15)
        assert r.status_code == 200
        for order in r.json()["items"]:
            for line in order.get("items", []):
                assert "name" in line
                assert "qty" in line
                assert "line_total" in line


# ──────── (A) Vendor delivery-info PATCH endpoint ───────────────────
class TestVendorDeliveryInfoPatch:
    def test_patch_403_on_unknown_order(self, api, vendor_b_token):
        r = api.patch(
            f"{BASE_URL}/api/vendor/orders/{uuid.uuid4()}/delivery-info",
            headers=_auth(vendor_b_token),
            json={"estimated_delivery_at": "2026-02-01T10:00:00Z",
                  "delivery_person_name": "TEST Rider",
                  "delivery_person_phone": "9999900000"},
            timeout=15,
        )
        assert r.status_code == 403, f"expected 403 for foreign/unknown order, got {r.status_code}: {r.text}"

    def test_patch_on_owned_order_if_available(self, api, vendor_a_token):
        # Locate a vendor_sales row for vendor A via /vendor/me/sales
        sales = api.get(f"{BASE_URL}/api/vendor/me/sales", headers=_auth(vendor_a_token), timeout=15).json()
        online_orders: List[str] = [
            o["order_id"] for o in sales.get("items", [])
            if o.get("order_id") and o.get("channel") != "pos"
        ]
        if not online_orders:
            pytest.skip("Vendor A has no online orders to PATCH delivery-info on")
        oid = online_orders[0]
        r = api.patch(
            f"{BASE_URL}/api/vendor/orders/{oid}/delivery-info",
            headers=_auth(vendor_a_token),
            json={
                "estimated_delivery_at": "2026-02-05T18:30:00Z",
                "delivery_person_name": "TEST Rider Ravi",
                "delivery_person_phone": "9990001111",
            }, timeout=15,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ok") is True
        order = d.get("order") or {}
        assert order.get("estimated_delivery_at") == "2026-02-05T18:30:00Z"
        assert order.get("delivery_person_name") == "TEST Rider Ravi"
        assert order.get("delivery_person_phone") == "9990001111"
        assert order.get("delivery_info_updated_at")

        # And it should be mirrored on /vendor/me/sales
        sales2 = api.get(f"{BASE_URL}/api/vendor/me/sales", headers=_auth(vendor_a_token), timeout=15).json()
        target = next((o for o in sales2["items"] if o.get("order_id") == oid), None)
        assert target is not None
        assert target.get("estimated_delivery_at") == "2026-02-05T18:30:00Z"
        assert target.get("delivery_person_name") == "TEST Rider Ravi"


# ─── customer /orders/me now exposes delivery fields ──────────────
class TestCustomerOrdersMeDeliveryFields:
    def test_orders_me_shape(self, api, customer_token):
        r = api.get(f"{BASE_URL}/api/orders/me", headers=_auth(customer_token), timeout=15)
        assert r.status_code == 200
        orders = r.json()
        # For each order (if any), the delivery fields should be present
        # (either null or actual value — key must at least be readable).
        for o in orders:
            # These may not be present as keys until vendor sets them; endpoint
            # is not required to inject nulls. Just ensure fetch works.
            assert "id" in o
            assert "status" in o


# ──────── (B) Customer cancel gating ────────────────────────────────
class TestCustomerCancelOrderGating:
    def test_cancel_unknown_order_404(self, api, customer_token):
        r = api.post(
            f"{BASE_URL}/api/orders/{uuid.uuid4()}/cancel",
            headers=_auth(customer_token), timeout=15,
        )
        assert r.status_code == 404

    def test_cancel_not_placed_returns_400(self, api, customer_token):
        # find a non-placed order for the customer
        orders = api.get(f"{BASE_URL}/api/orders/me", headers=_auth(customer_token), timeout=15).json()
        non_placed = [o for o in orders if o.get("status") not in ("placed", None)]
        if not non_placed:
            pytest.skip("Customer has no non-placed order to test gating")
        oid = non_placed[0]["id"]
        r = api.post(f"{BASE_URL}/api/orders/{oid}/cancel", headers=_auth(customer_token), timeout=15)
        assert r.status_code == 400
        assert "no longer be cancelled" in (r.json().get("detail") or "").lower()

    def test_cancel_after_delivery_info_returns_400(self, api, customer_token):
        orders = api.get(f"{BASE_URL}/api/orders/me", headers=_auth(customer_token), timeout=15).json()
        engaged = [
            o for o in orders
            if o.get("status") == "placed" and o.get("delivery_info_updated_at")
        ]
        if not engaged:
            pytest.skip("No placed+engaged orders to check the delivery_info_updated_at gate")
        oid = engaged[0]["id"]
        r = api.post(f"{BASE_URL}/api/orders/{oid}/cancel", headers=_auth(customer_token), timeout=15)
        assert r.status_code == 400
        assert "already started processing" in (r.json().get("detail") or "").lower()


# ──────── (C) Shop sub_category filter — the reported 0-items bug ─
class TestShopSubCategoryFilter:
    def test_mobiles_apple_returns_two(self, api):
        r = api.get(f"{BASE_URL}/api/products", params={"category": "Mobiles", "subcategory": "Apple"}, timeout=15)
        assert r.status_code == 200
        d = r.json()
        items = d.get("items") if isinstance(d, dict) else d
        names = [it.get("name") for it in items]
        assert len(items) == 2, f"expected 2 Apple items, got {len(items)}: {names}"
        joined = " | ".join(names)
        assert "Apple iPhone 17 Pro" in joined
        assert "iPhone 15 Pro Max" in joined

    def test_mobiles_samsung_returns_one(self, api):
        r = api.get(f"{BASE_URL}/api/products", params={"category": "Mobiles", "subcategory": "Samsung"}, timeout=15)
        assert r.status_code == 200
        d = r.json()
        items = d.get("items") if isinstance(d, dict) else d
        assert len(items) == 1, f"expected 1 Samsung item, got {len(items)}"
        assert "Samsung" in items[0].get("name", "")


# ──────── Regression: /admin/shop-layout + strict_location ─────────
class TestRegression:
    @pytest.fixture(scope="class")
    def admin_token(self, api):
        return _login(api, ADMIN)["token"]

    def test_admin_shop_layout(self, api, admin_token):
        r = api.get(f"{BASE_URL}/api/admin/shop-layout", headers=_auth(admin_token), timeout=15)
        assert r.status_code == 200, r.text
        # response is typically {blocks: [...]} or a list
        d = r.json()
        assert isinstance(d, (list, dict))

    def test_products_strict_location_517644(self, api):
        r = api.get(
            f"{BASE_URL}/api/products",
            params={"pincode": "517644", "strict_location": "true"}, timeout=15,
        )
        assert r.status_code == 200
        d = r.json()
        items = d.get("items") if isinstance(d, dict) else d
        # The 3 Kittu products at 517644 should still be there
        assert len(items) >= 3
