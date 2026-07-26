"""
Nov 2026 production hardening — end-to-end backend tests for Slangcart.

Covers:
  1. Pincode-scoped Shop Layout blocks (scope_pincode field)
  2. GST bucket in Admin System Wallet (system_wallet_deposits bucket:"gst")
  3. Delivery-radius mode "both" | "radius" | "pincode" | "none" product filter
  4. MongoDB indexes named ix_prod_store_pin, ix_prod_del_pins, ix_prod_vendor,
     ix_ver_user_status, ix_ver_status_created, ix_sl_scope_active,
     ix_sl_scope_pin, ix_swd_bucket

Run:  pytest backend/tests/test_nov2026_prod_hardening.py -v
"""
from __future__ import annotations

import os
import uuid
from typing import Any, Dict, List

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "http://localhost:8001").rstrip("/")
if not BASE_URL.endswith("/api") and "/api" not in BASE_URL:
    API = f"{BASE_URL}/api"
else:
    API = BASE_URL

ADMIN_EMAIL = "support@networkrupay.com"
ADMIN_PASSWORD = "Nlee@1115"
VENDOR_EMAIL = "raju@gmail.com"
VENDOR_PASSWORD = "Demo@2026"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "referral_ecom_db")


# ───────────────────────── Fixtures ─────────────────────────

@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin_token(api):
    r = api.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    tok = r.json().get("token")
    assert tok, "No token returned"
    return tok


@pytest.fixture(scope="module")
def vendor_token(api):
    r = api.post(f"{API}/auth/login", json={"email": VENDOR_EMAIL, "password": VENDOR_PASSWORD})
    assert r.status_code == 200, f"Vendor login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def vendor_id(api, vendor_token):
    r = api.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {vendor_token}"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.fixture(scope="module")
def db():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


def _auth(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ═════════════════════════ 1) Shop Layout — scope_pincode ═════════════════════════

TEST_PIN_A = "500001"
TEST_PIN_B = "999999"  # unlikely to have any block
TAG = uuid.uuid4().hex[:6]


class TestShopLayoutPincodeScope:
    created_ids: List[str] = []

    def test_create_pincode_scoped_block(self, api, admin_token):
        payload = {
            "block_type": "banner_slider",
            "scope": "home",
            "scope_pincode": TEST_PIN_A,
            "title": f"TEST_PINSCOPED_{TAG}",
            "active": True,
            "sort_order": 500,
        }
        r = api.post(f"{API}/admin/shop-layout", json=payload, headers=_auth(admin_token))
        assert r.status_code == 200, f"create failed: {r.status_code} {r.text}"
        body = r.json()
        assert body["block_type"] == "banner_slider"
        assert body["scope"] == "home"
        assert body["scope_pincode"] == TEST_PIN_A, f"scope_pincode not persisted: {body}"
        assert body["title"].startswith("TEST_PINSCOPED_")
        assert "id" in body
        TestShopLayoutPincodeScope.created_ids.append(body["id"])

    def test_create_global_block(self, api, admin_token):
        """Block with empty scope_pincode should render for ALL customers."""
        payload = {
            "block_type": "section_header",
            "scope": "home",
            "scope_pincode": "",
            "title": f"TEST_GLOBAL_{TAG}",
            "active": True,
            "sort_order": 501,
        }
        r = api.post(f"{API}/admin/shop-layout", json=payload, headers=_auth(admin_token))
        assert r.status_code == 200, r.text
        assert r.json()["scope_pincode"] == ""
        TestShopLayoutPincodeScope.created_ids.append(r.json()["id"])

    def test_get_with_matching_pincode_returns_both(self, api):
        """GET /shop-layout?pincode=500001 → returns pincode-scoped + global blocks."""
        r = api.get(f"{API}/shop-layout", params={"scope": "home", "pincode": TEST_PIN_A})
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        titles = [i.get("title", "") for i in items]
        assert f"TEST_PINSCOPED_{TAG}" in titles, "Pincode-scoped block missing for matching pin"
        assert f"TEST_GLOBAL_{TAG}" in titles, "Global block missing for matching pin"

    def test_get_with_nonmatching_pincode_excludes_scoped(self, api):
        """GET /shop-layout?pincode=999999 → returns ONLY global blocks."""
        r = api.get(f"{API}/shop-layout", params={"scope": "home", "pincode": TEST_PIN_B})
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        titles = [i.get("title", "") for i in items]
        assert f"TEST_PINSCOPED_{TAG}" not in titles, (
            f"Pincode-scoped block MUST NOT appear for non-matching pincode {TEST_PIN_B}"
        )
        assert f"TEST_GLOBAL_{TAG}" in titles, "Global block missing for non-matching pin"

    def test_get_without_pincode_returns_all(self, api):
        """Without ?pincode, all blocks (global + scoped) are returned."""
        r = api.get(f"{API}/shop-layout", params={"scope": "home"})
        assert r.status_code == 200
        titles = [i.get("title", "") for i in r.json()["items"]]
        assert f"TEST_PINSCOPED_{TAG}" in titles
        assert f"TEST_GLOBAL_{TAG}" in titles

    def test_cleanup_created_blocks(self, api, admin_token):
        for bid in TestShopLayoutPincodeScope.created_ids:
            r = api.delete(f"{API}/admin/shop-layout/{bid}", headers=_auth(admin_token))
            assert r.status_code in (200, 404), f"cleanup failed for {bid}: {r.text}"


# ═════════════════════════ 2) System Wallet GST bucket ═════════════════════════

class TestSystemWalletGstBucket:

    def test_system_wallet_returns_gst_bucket(self, api, admin_token):
        r = api.get(f"{API}/admin/system-wallet", headers=_auth(admin_token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert "gst_bucket" in body, f"gst_bucket missing from system-wallet response: {list(body.keys())}"
        gb = body["gst_bucket"]
        assert "total" in gb and "invoice_count" in gb, f"gst_bucket keys wrong: {gb}"
        assert isinstance(gb["total"], (int, float))
        assert isinstance(gb["invoice_count"], int)

    def test_pos_sale_writes_gst_deposit_and_increases_bucket(
        self, api, admin_token, vendor_token, vendor_id, db
    ):
        # a) snapshot bucket before
        r0 = api.get(f"{API}/admin/system-wallet", headers=_auth(admin_token))
        assert r0.status_code == 200
        gb0 = r0.json()["gst_bucket"]
        before_total = float(gb0["total"])
        before_count = int(gb0["invoice_count"])

        # b) create a vendor product with sufficient stock so POS can bill it
        prod_id = f"TEST_gst_prod_{TAG}"
        db.products.insert_one({
            "id": prod_id,
            "name": f"TEST_GST_Product_{TAG}",
            "price": 100.0,
            "image_url": "",
            "stock": 100,
            "cost_price": 50.0,
            "vendor_id": vendor_id,
            "vendor_email": VENDOR_EMAIL,
            "is_published": True,
            "created_at": "2026-01-01T00:00:00+00:00",
        })

        try:
            # c) Create a POS sale with GST 18% on a ₹100 unit → gst_total = ₹18
            sale_payload = {
                "customer": {"kind": "named", "name": "Test Customer", "phone": "9999999999"},
                "items": [{
                    "product_id": prod_id,
                    "name": f"TEST_GST_Product_{TAG}",
                    "qty": 1,
                    "price": 100.0,
                    "gst_pct": 18.0,
                    "discount": None,
                }],
                "payments": [{"mode": "cash", "amount": 118.0}],
                "gst_inclusive": False,
                "round_off": False,
                "bill_discount": None,
                "notes": "test",
                "client_id": str(uuid.uuid4()),
            }
            r_sale = api.post(
                f"{API}/vendor/me/pos/sales",
                json=sale_payload,
                headers=_auth(vendor_token),
            )
            assert r_sale.status_code == 200, f"POS sale failed: {r_sale.status_code} {r_sale.text}"
            sale = r_sale.json()
            assert sale["totals"]["gst_total"] == 18.0, f"unexpected gst_total: {sale['totals']}"
            invoice_no = sale["invoice_no"]
            sale_id = sale["id"]

            # d) Verify a system_wallet_deposits row with bucket="gst" was written
            deposit = db.system_wallet_deposits.find_one(
                {"bucket": "gst", "sale_id": sale_id}
            )
            assert deposit is not None, (
                "No system_wallet_deposits row with bucket='gst' for the POS sale"
            )
            assert deposit["source"] == "gst_pos"
            assert deposit["amount"] == 18.0, f"deposit amount wrong: {deposit['amount']}"
            assert deposit["vendor_id"] == vendor_id
            assert deposit["invoice_no"] == invoice_no

            # e) Re-fetch system-wallet — gst_bucket total & count must have grown
            r1 = api.get(f"{API}/admin/system-wallet", headers=_auth(admin_token))
            assert r1.status_code == 200
            gb1 = r1.json()["gst_bucket"]
            assert float(gb1["total"]) == pytest.approx(before_total + 18.0, abs=0.01), (
                f"gst_bucket.total did not increase by 18: before={before_total} after={gb1['total']}"
            )
            assert int(gb1["invoice_count"]) == before_count + 1, (
                f"invoice_count did not increment: before={before_count} after={gb1['invoice_count']}"
            )
        finally:
            # Cleanup: delete the sale, product & deposit
            db.offline_sales.delete_many({"items.product_id": prod_id})
            db.system_wallet_deposits.delete_many({"invoice_no": {"$exists": True},
                                                    "vendor_id": vendor_id,
                                                    "amount": 18.0,
                                                    "bucket": "gst",
                                                    "source": "gst_pos"})
            db.products.delete_one({"id": prod_id})


# ═════════════════════════ 3) Delivery-radius mode product filter ═════════════════════════

RADIUS_PIN = "560001"
OTHER_PIN = "110001"


class TestDeliveryRadiusModeFilter:
    """POST products directly to DB with each mode, then hit GET /products?pincode=X."""

    prod_ids: List[str] = []

    def _mk_prod(self, db, vendor_id: str, mode: str, extra: Dict[str, Any] = None) -> str:
        pid = f"TEST_radmode_{mode}_{TAG}"
        doc = {
            "id": pid,
            "name": f"TEST_RadMode_{mode}_{TAG}",
            "price": 199.0,
            "image_url": "",
            "stock": 10,
            "vendor_id": vendor_id,
            "is_published": True,
            "store_pincode": RADIUS_PIN,
            "delivery_radius_mode": mode,
            "delivery_pincodes": [],
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        if extra:
            doc.update(extra)
        db.products.insert_one(doc)
        TestDeliveryRadiusModeFilter.prod_ids.append(pid)
        return pid

    def test_setup_and_verify_modes(self, db, vendor_id):
        # cleanup any leftovers
        db.products.delete_many({"id": {"$regex": f"^TEST_radmode_.*_{TAG}$"}})
        TestDeliveryRadiusModeFilter.prod_ids.clear()

        self._mk_prod(db, vendor_id, "both")
        self._mk_prod(db, vendor_id, "pincode")
        self._mk_prod(db, vendor_id, "radius")
        self._mk_prod(db, vendor_id, "none")

        # And one with mode="radius" but explicit delivery_pincodes containing RADIUS_PIN
        # → this SHOULD be returned even under radius mode (delivery_pincodes match wins).
        self._mk_prod(
            db, vendor_id, "radius",
            extra={
                "id": f"TEST_radmode_radius_explicit_{TAG}",
                "delivery_pincodes": [RADIUS_PIN],
            },
        )
        # Since _mk_prod pushed the same suffix twice, correct the list:
        TestDeliveryRadiusModeFilter.prod_ids[-1] = f"TEST_radmode_radius_explicit_{TAG}"

    def _fetch_products_for_pin(self, api, pincode: str) -> List[Dict[str, Any]]:
        r = api.get(f"{API}/products", params={"pincode": pincode, "limit": 100})
        assert r.status_code == 200, r.text
        body = r.json()
        # endpoint returns either a bare array (back-compat) or envelope
        if isinstance(body, dict):
            return body.get("items") or []
        return body

    def test_mode_both_returned_for_matching_pincode(self, api):
        items = self._fetch_products_for_pin(api, RADIUS_PIN)
        ids = {p["id"] for p in items}
        assert f"TEST_radmode_both_{TAG}" in ids, "mode='both' should be returned when store_pincode matches"

    def test_mode_pincode_returned_for_matching_pincode(self, api):
        items = self._fetch_products_for_pin(api, RADIUS_PIN)
        ids = {p["id"] for p in items}
        assert f"TEST_radmode_pincode_{TAG}" in ids, "mode='pincode' should be returned when store_pincode matches"

    def test_mode_radius_NOT_returned_for_matching_store_pincode(self, api):
        """mode='radius' means km-only delivery — store_pincode is NOT auto-deliverable."""
        items = self._fetch_products_for_pin(api, RADIUS_PIN)
        ids = {p["id"] for p in items}
        assert f"TEST_radmode_radius_{TAG}" not in ids, (
            "mode='radius' (with no delivery_pincodes match) must NOT be returned"
        )

    def test_mode_none_NOT_returned(self, api):
        items = self._fetch_products_for_pin(api, RADIUS_PIN)
        ids = {p["id"] for p in items}
        assert f"TEST_radmode_none_{TAG}" not in ids, "mode='none' must NOT be returned"

    def test_mode_radius_with_explicit_pincode_IS_returned(self, api):
        """Even under mode='radius', if delivery_pincodes contains the pin, it matches."""
        items = self._fetch_products_for_pin(api, RADIUS_PIN)
        ids = {p["id"] for p in items}
        assert f"TEST_radmode_radius_explicit_{TAG}" in ids, (
            "mode='radius' WITH matching delivery_pincodes entry should still be returned"
        )

    def test_nonmatching_pincode_returns_none_of_them(self, api):
        items = self._fetch_products_for_pin(api, OTHER_PIN)
        ids = {p["id"] for p in items}
        for pid in TestDeliveryRadiusModeFilter.prod_ids:
            assert pid not in ids, f"product {pid} leaked for non-matching pincode {OTHER_PIN}"

    def test_cleanup(self, db):
        db.products.delete_many({"id": {"$regex": f"^TEST_radmode_.*_{TAG}$"}})


# ═════════════════════════ 4) MongoDB indexes ═════════════════════════

EXPECTED_INDEXES = {
    "products": {"ix_prod_store_pin", "ix_prod_del_pins", "ix_prod_vendor"},
    "vendor_edit_requests": {"ix_ver_user_status", "ix_ver_status_created"},
    "shop_layout_blocks": {"ix_sl_scope_active", "ix_sl_scope_pin"},
    "system_wallet_deposits": {"ix_swd_bucket"},
}


class TestNamedIndexes:

    def test_products_indexes_exist(self, db):
        names = set(db.products.index_information().keys())
        missing = EXPECTED_INDEXES["products"] - names
        assert not missing, f"products missing indexes: {missing}. Present: {names}"

    def test_vendor_edit_requests_indexes_exist(self, db):
        names = set(db.vendor_edit_requests.index_information().keys())
        missing = EXPECTED_INDEXES["vendor_edit_requests"] - names
        assert not missing, f"vendor_edit_requests missing: {missing}. Present: {names}"

    def test_shop_layout_blocks_indexes_exist(self, db):
        names = set(db.shop_layout_blocks.index_information().keys())
        missing = EXPECTED_INDEXES["shop_layout_blocks"] - names
        assert not missing, f"shop_layout_blocks missing: {missing}. Present: {names}"

    def test_system_wallet_deposits_index_exists(self, db):
        names = set(db.system_wallet_deposits.index_information().keys())
        missing = EXPECTED_INDEXES["system_wallet_deposits"] - names
        assert not missing, f"system_wallet_deposits missing: {missing}. Present: {names}"
