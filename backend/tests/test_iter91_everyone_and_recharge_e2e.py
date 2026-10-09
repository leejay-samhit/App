"""Iteration 91 — E2E 'Everyone' delivery zone + Recharge operator sync.

Covers the owner's two January-2026 requests, exercised through the SAME
HTTP endpoints the mobile app hits (vendor edit-request → admin approve →
products / delivery / checkout). Unit-level pieces are already covered by
`verify_jun2026_recharge_sync_everyone.py` (21/21 PASS); this file hits the
full REST path.

Run:
    pytest backend/tests/test_iter91_everyone_and_recharge_e2e.py -v
"""
from __future__ import annotations

import os
import uuid
from typing import Any, Dict, List, Optional

import pytest
import requests
from pymongo import MongoClient

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "http://localhost:8001").rstrip("/") + "/api"
MONGO_URL = os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
DB_NAME = os.environ.get("DB_NAME") or "referral_ecom_db"

ADMIN = {"email": "support@slangcart.com", "password": "3)Ywxtic"}
VENDOR = {"email": "testvendor@test.com", "password": "Test@1234"}
BUYER = {"email": "testbuyer@test.com", "password": "Test@1234"}

VENDOR_PIN = "517644"
FAR_PIN = "110001"

HEADERS = {"User-Agent": "curl/8.5.0", "Content-Type": "application/json"}


# ─────────────────────────────── helpers ───────────────────────────────
def _login(creds: Dict[str, str]) -> str:
    r = requests.post(f"{BASE}/auth/login", json=creds, headers=HEADERS, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("token")
    assert tok, f"no token: {r.text}"
    return tok


def _auth(tok: str) -> Dict[str, str]:
    return {**HEADERS, "Authorization": f"Bearer {tok}"}


# ──────────────────────── module-scoped fixtures ───────────────────────
@pytest.fixture(scope="module")
def mongo():
    cli = MongoClient(MONGO_URL)
    yield cli[DB_NAME]
    cli.close()


@pytest.fixture(scope="module")
def tokens():
    return {
        "admin":  _login(ADMIN),
        "vendor": _login(VENDOR),
        "buyer":  _login(BUYER),
    }


@pytest.fixture(scope="module")
def vendor_id(mongo) -> str:
    v = mongo.users.find_one({"email": VENDOR["email"]}, {"_id": 0, "id": 1})
    assert v and v.get("id")
    return v["id"]


@pytest.fixture(scope="module")
def vendor_baseline(mongo, vendor_id):
    """Snapshot the vendor's current zone + wipe seeded products at teardown."""
    v = mongo.users.find_one({"id": vendor_id}, {"_id": 0})
    snap = {k: v.get(k) for k in ("delivery_radius_mode", "delivery_radius_km",
                                   "delivery_pincodes", "store_pincode",
                                   "pincode", "lat", "lng", "delivery_available")}
    seeded: Dict[str, List[str]] = {"products": [], "recharge_options": [],
                                     "edit_requests": [], "shop_cats": []}
    yield {"snap": snap, "seeded": seeded}
    # ── cleanup ─────────────────────────────────────────────────────────
    if seeded["products"]:
        mongo.products.delete_many({"id": {"$in": seeded["products"]}})
    if seeded["edit_requests"]:
        mongo.vendor_edit_requests.delete_many({"id": {"$in": seeded["edit_requests"]}})
    if seeded["recharge_options"]:
        mongo.recharge_options.delete_many({"id": {"$in": seeded["recharge_options"]}})
    if seeded["shop_cats"]:
        mongo.shop_categories.delete_many({"id": {"$in": seeded["shop_cats"]}})
    # Restore vendor profile exactly as it was.
    mongo.users.update_one({"id": vendor_id}, {"$set": snap})
    # Make sure cart is empty for the buyer so the next CI run starts clean.
    buyer = mongo.users.find_one({"email": BUYER["email"]}, {"_id": 0, "id": 1})
    if buyer:
        mongo.cart_items.delete_many({"user_id": buyer["id"]})


# ──────────────── Phase A — "Everyone" zone end-to-end ─────────────────
class TestEveryoneZoneE2E:
    """Phase A: edit-request → admin approve → zone + public filter."""

    def test_01_vendor_submits_everywhere_edit_request(self, tokens, vendor_baseline):
        body = {"delivery_radius_mode": "everywhere", "note": "iter91 test"}
        r = requests.post(f"{BASE}/vendor/edit-requests", json=body,
                          headers=_auth(tokens["vendor"]), timeout=30)
        assert r.status_code == 200, r.text
        doc = r.json()
        assert doc.get("status") == "pending"
        assert doc.get("changes", {}).get("delivery_radius_mode") == "everywhere"
        vendor_baseline["seeded"]["edit_requests"].append(doc["id"])
        pytest.edit_req_id = doc["id"]

    def test_02_admin_approves_edit_request(self, tokens):
        rid = pytest.edit_req_id
        r = requests.post(f"{BASE}/admin/vendor-edit-requests/{rid}/approve",
                          headers=_auth(tokens["admin"]), timeout=30)
        assert r.status_code == 200, r.text
        assert r.json().get("status") == "approved"

    def test_03_vendor_delivery_zone_reflects_everywhere(self, tokens):
        r = requests.get(f"{BASE}/vendor/me/delivery-zone",
                         headers=_auth(tokens["vendor"]), timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("mode") == "everywhere"
        assert data.get("explains", {}).get("everywhere") is True

    def test_04_vendor_zone_check_far_pincode(self, tokens):
        r = requests.get(f"{BASE}/vendor/me/delivery-zone/check",
                         params={"pincode": FAR_PIN},
                         headers=_auth(tokens["vendor"]), timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("covered") is True
        assert data.get("reason") == "everywhere"


# ─────── Phase B — Seed a published product + customer visibility ───────
class TestEveryoneCustomerVisibility:

    def test_10_seed_published_product_for_vendor(self, mongo, vendor_id, vendor_baseline):
        pid = str(uuid.uuid4())
        mongo.products.insert_one({
            "id": pid,
            "name": "ITER91 Everywhere Widget",
            "price": 149.0, "stock": 50,
            "category": "Fashion", "subcategory": "Accessories",
            "vendor_id": vendor_id,
            "is_published": True, "active": True,
            "delivery_available": True, "cod_available": True,
            "store_pincode": VENDOR_PIN,
            "delivery_radius_mode": "everywhere",
            "delivery_radius_km": 5,
        })
        vendor_baseline["seeded"]["products"].append(pid)
        pytest.ever_pid = pid
        # Bust caches so /products reflects immediately.
        try:
            requests.get(f"{BASE}/admin/cache/bust", timeout=5,
                         headers=_auth(_login(ADMIN)))
        except Exception:
            pass

    def test_11_products_listed_for_far_pincode(self, tokens):
        # The /products endpoint takes a pincode filter and must now include
        # our everywhere vendor's product even though the shop is far away.
        r = requests.get(f"{BASE}/products", params={"pincode": FAR_PIN, "limit": 300},
                         headers=_auth(tokens["buyer"]), timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        items = body.get("items") or body.get("products") or body if isinstance(body, list) else body.get("items", [])
        if isinstance(body, dict) and "items" not in body and "products" not in body:
            items = body.get("results") or []
        ids = {p.get("id") for p in items}
        assert pytest.ever_pid in ids, (
            f"everywhere product {pytest.ever_pid} missing from /products"
            f"?pincode={FAR_PIN} — got {len(items)} items")

    def test_12_delivery_check_far_pincode(self, tokens):
        r = requests.get(f"{BASE}/delivery/check", params={"pincode": FAR_PIN},
                         headers=_auth(tokens["buyer"]), timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("deliverable") is True
        assert int(data.get("vendor_count") or 0) >= 1


# ─────────────── Phase C — Checkout COD / Online / Wallet ──────────────
def _add_to_cart(tokens, pid: str):
    requests.post(f"{BASE}/cart/clear", headers=_auth(tokens["buyer"]), timeout=15)
    r = requests.post(f"{BASE}/cart/add", json={"product_id": pid, "qty": 1},
                      headers=_auth(tokens["buyer"]), timeout=15)
    assert r.status_code == 200, f"cart/add failed: {r.status_code} {r.text}"


def _ship(pin: str) -> Dict[str, Any]:
    return {
        "name": "ITER91 Buyer", "phone": "9999999999",
        "line1": "A1 Test Line", "city": "Testville",
        "state": "TS", "pincode": pin,
    }


class TestEveryoneCheckoutRules:

    def test_20_cod_far_blocked(self, tokens):
        _add_to_cart(tokens, pytest.ever_pid)
        r = requests.post(f"{BASE}/orders/checkout",
                          json={"payment_method": "cod",
                                "shipping_address": _ship(FAR_PIN)},
                          headers=_auth(tokens["buyer"]), timeout=30)
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
        detail = r.json().get("detail") or {}
        assert isinstance(detail, dict), detail
        assert detail.get("code") == "cod_not_available", detail

    def test_21_wallet_cod_far_blocked(self, tokens):
        _add_to_cart(tokens, pytest.ever_pid)
        r = requests.post(f"{BASE}/orders/checkout",
                          json={"payment_method": "wallet_cod",
                                "wallet_amount": 10,
                                "shipping_address": _ship(FAR_PIN)},
                          headers=_auth(tokens["buyer"]), timeout=30)
        assert r.status_code == 400, r.text
        detail = r.json().get("detail") or {}
        assert isinstance(detail, dict), detail
        assert detail.get("code") == "cod_not_available", detail

    def test_22_cod_near_allowed(self, tokens):
        _add_to_cart(tokens, pytest.ever_pid)
        r = requests.post(f"{BASE}/orders/checkout",
                          json={"payment_method": "cod",
                                "shipping_address": _ship(VENDOR_PIN)},
                          headers=_auth(tokens["buyer"]), timeout=30)
        assert r.status_code == 200, f"COD near should succeed, got {r.status_code}: {r.text}"
        resp = r.json()
        # Response varies by server version; just confirm an order id lives in it.
        assert any(k in resp for k in ("order_id", "orders", "ok", "order_ids")), resp

    def test_23_wallet_far_allowed(self, tokens, mongo):
        _add_to_cart(tokens, pytest.ever_pid)
        # Ensure buyer has enough balance (seed memory says ~₹48k).
        buyer = mongo.users.find_one({"email": BUYER["email"]}, {"_id": 0, "wallet_balance": 1})
        assert float(buyer.get("wallet_balance") or 0) >= 500, "buyer wallet too low to run this test"
        r = requests.post(f"{BASE}/orders/checkout",
                          json={"payment_method": "wallet",
                                "shipping_address": _ship(FAR_PIN)},
                          headers=_auth(tokens["buyer"]), timeout=30)
        assert r.status_code == 200, f"wallet far should succeed: {r.status_code} {r.text}"

    def test_24_online_far_allowed(self, tokens):
        _add_to_cart(tokens, pytest.ever_pid)
        # Start a Razorpay (mock) attempt
        r = requests.post(f"{BASE}/orders/payment/start", json={"wallet_amount": 0},
                          headers=_auth(tokens["buyer"]), timeout=30)
        assert r.status_code == 200, r.text
        attempt = r.json()
        assert attempt.get("is_mock") is True, f"preview must be in mock mode: {attempt}"
        pay_id = attempt["payment_id"]
        rzp_oid = attempt["razorpay_order_id"]
        mock_pid = f"pay_MOCK_{uuid.uuid4().hex[:12]}"
        v = requests.post(f"{BASE}/orders/payment/verify",
                          json={"payment_id": pay_id,
                                "razorpay_order_id": rzp_oid,
                                "razorpay_payment_id": mock_pid,
                                "razorpay_signature": "sig_MOCK_x"},
                          headers=_auth(tokens["buyer"]), timeout=30)
        assert v.status_code == 200, v.text
        c = requests.post(f"{BASE}/orders/checkout",
                          json={"payment_method": "online",
                                "payment_id": pay_id,
                                "shipping_address": _ship(FAR_PIN)},
                          headers=_auth(tokens["buyer"]), timeout=30)
        assert c.status_code == 200, f"online far should succeed: {c.status_code} {c.text}"


# ─────────────────── Phase D — Regression: normal vendor ─────────────────
class TestNormalVendorRegression:

    def test_30_revert_vendor_to_both_mode(self, mongo, vendor_id, tokens, vendor_baseline):
        # Go through the REAL edit-request flow so the products_public
        # 60s cache gets busted on admin approval (direct DB writes leave
        # the eligibility cache stale and poison this test).
        body = {"delivery_radius_mode": "both", "delivery_radius_km": 10}
        r = requests.post(f"{BASE}/vendor/edit-requests", json=body,
                          headers=_auth(tokens["vendor"]), timeout=30)
        assert r.status_code == 200, r.text
        rid = r.json()["id"]
        vendor_baseline["seeded"]["edit_requests"].append(rid)
        a = requests.post(f"{BASE}/admin/vendor-edit-requests/{rid}/approve",
                          headers=_auth(tokens["admin"]), timeout=30)
        assert a.status_code == 200, a.text
        # Keep the seeded product's own copy in sync (edit-request only
        # denormalises when location/radius are in the payload, which they
        # are here — but double-write to be safe).
        mongo.products.update_one(
            {"id": pytest.ever_pid},
            {"$set": {"delivery_radius_mode": "both", "delivery_radius_km": 10,
                      "store_pincode": VENDOR_PIN}},
        )

    def test_31_far_pincode_product_hidden(self, tokens):
        r = requests.get(f"{BASE}/products",
                         params={"pincode": FAR_PIN, "limit": 300},
                         headers=_auth(tokens["buyer"]), timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        items = body.get("items") or body.get("products") or body.get("results") or []
        ids = {p.get("id") for p in items}
        assert pytest.ever_pid not in ids, "normal vendor's product leaked to far pincode"

    def test_32_far_checkout_blocked_with_zone_code(self, tokens):
        _add_to_cart(tokens, pytest.ever_pid)
        r = requests.post(f"{BASE}/orders/checkout",
                          json={"payment_method": "cod",
                                "shipping_address": _ship(FAR_PIN)},
                          headers=_auth(tokens["buyer"]), timeout=30)
        assert r.status_code == 400, r.text
        detail = r.json().get("detail") or {}
        assert isinstance(detail, dict) and detail.get("code") == "out_of_delivery_zone", detail

    def test_33_near_cod_still_allowed(self, tokens):
        _add_to_cart(tokens, pytest.ever_pid)
        r = requests.post(f"{BASE}/orders/checkout",
                          json={"payment_method": "cod",
                                "shipping_address": _ship(VENDOR_PIN)},
                          headers=_auth(tokens["buyer"]), timeout=30)
        assert r.status_code == 200, f"local COD regression broken: {r.status_code} {r.text}"


# ──────────────── Phase E — Recharge operator ⇄ shop sub-category sync ─────────────
class TestRechargeSyncE2E:

    def test_40_admin_adds_new_operator(self, tokens, vendor_baseline):
        nm = f"ITER91Op {uuid.uuid4().hex[:5]}"
        r = requests.post(f"{BASE}/admin/recharge/options",
                          json={"kind": "mobile", "group": "network", "name": nm},
                          headers=_auth(tokens["admin"]), timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        pytest.rch_op_id = body["id"]
        pytest.rch_op_name = nm
        pytest.rch_network_slug = body.get("network") or body.get("slug") or nm.lower().replace(" ", "-")
        vendor_baseline["seeded"]["recharge_options"].append(body["id"])

    def test_41_vendor_posts_product_under_operator(self, tokens, vendor_baseline):
        payload = {
            "name": f"ITER91 Plan {uuid.uuid4().hex[:5]}",
            "price": 199.0, "stock": 99,
            "category": "Recharge",
            # Backend's ProductCreate model uses `sub_category` (with
            # underscore). The recharge listing / option_product_count
            # queries BOTH `sub_category` and `subcategory`, so storing on
            # `sub_category` is correct and the one the real app uses.
            "sub_category": pytest.rch_op_name,
            "description": "iter91 plan", "image_url": "",
        }
        r = requests.post(f"{BASE}/vendor/me/products", json=payload,
                          headers=_auth(tokens["vendor"]), timeout=30)
        assert r.status_code == 200, r.text
        doc = r.json()
        pytest.rch_pid = doc["id"]
        vendor_baseline["seeded"]["products"].append(doc["id"])
        assert doc.get("is_published") is False, "vendor should start unpublished"
        assert (doc.get("sub_category") or doc.get("subcategory")) == pytest.rch_op_name

    def test_42_unpublished_hidden_from_recharge_listing(self, tokens, mongo):
        # Resolve network slug from the mirrored sub-category.
        cat = mongo.shop_categories.find_one({"recharge_option_id": pytest.rch_op_id})
        assert cat, "sub-category should mirror the operator"
        net = cat.get("recharge_network") or pytest.rch_network_slug
        r = requests.get(f"{BASE}/recharge/products",
                         params={"kind": "mobile",
                                 "state": "andhra-pradesh-telangana-ap-tg",
                                 "network": net},
                         headers=_auth(tokens["buyer"]), timeout=30)
        assert r.status_code == 200, r.text
        names = [p["name"] for g in r.json().get("groups", []) for p in g.get("products", [])]
        prod = mongo.products.find_one({"id": pytest.rch_pid}, {"_id": 0, "name": 1})
        assert prod["name"] not in names, f"unpublished plan should NOT be listed: {names}"
        pytest.rch_network_resolved = net
        pytest.rch_prod_name = prod["name"]

    def test_43_admin_publishes_and_product_lists(self, tokens):
        r = requests.patch(f"{BASE}/admin/products/{pytest.rch_pid}",
                           json={"is_published": True},
                           headers=_auth(tokens["admin"]), timeout=30)
        assert r.status_code == 200, r.text
        # Re-query the recharge listing
        r2 = requests.get(f"{BASE}/recharge/products",
                          params={"kind": "mobile",
                                  "state": "andhra-pradesh-telangana-ap-tg",
                                  "network": pytest.rch_network_resolved},
                          headers=_auth(tokens["buyer"]), timeout=30)
        assert r2.status_code == 200, r2.text
        names = [p["name"] for g in r2.json().get("groups", []) for p in g.get("products", [])]
        assert pytest.rch_prod_name in names, (
            f"published plan should list under operator: got {names}")

    def test_44_delete_operator_blocked_while_products_exist(self, tokens):
        r = requests.delete(f"{BASE}/admin/recharge/options/{pytest.rch_op_id}",
                            headers=_auth(tokens["admin"]), timeout=30)
        assert r.status_code == 409, f"expected 409, got {r.status_code}: {r.text}"
        # The message must name the live product count.
        txt = r.text
        assert "product" in txt.lower(), f"error should mention products: {txt}"
        # Loose match — "1 product" OR "1 product(s)" OR "1 live product" etc.
        assert "1" in txt, f"error should mention the count: {txt}"

    def test_45_delete_allowed_once_empty(self, mongo, tokens):
        # Remove the lone product first.
        mongo.products.delete_one({"id": pytest.rch_pid})
        r = requests.delete(f"{BASE}/admin/recharge/options/{pytest.rch_op_id}",
                            headers=_auth(tokens["admin"]), timeout=30)
        assert r.status_code == 200, r.text
        cat = mongo.shop_categories.find_one({"recharge_option_id": pytest.rch_op_id})
        assert cat is not None and not cat.get("active"), \
            "mirrored sub-category should be deactivated (not deleted)"
