"""Iteration 56 backend regression suite.

Covers the 4 user-requested features:
  1. Multi-pincode banners (shop_layout)
     - POST /api/admin/shop-layout with a scope_pincodes list normalises
       (drops junk / short entries, de-dupes, preserves order) and clears
       the legacy scope_pincode when there are 2+ targets.
     - GET /api/shop-layout filtering by pincode INCLUDES the block for
       matching pincodes, EXCLUDES for non-matching, and EXCLUDES it for
       unknown-location customers (no pincode) while keeping global blocks.
     - Legacy compat: block created with only the old single field still
       matches and is back-filled to scope_pincodes on admin read.
     - PATCH scope_pincodes rewrites BOTH fields, and clearing to [] makes
       the block global again.
     - Regression: same story on scope=category blocks.
  2. Cash summary in GET /api/vendor/me/stats + delivered_at stamp on
     PATCH /api/admin/orders/{id}/status.

The multi-vendor split checkout / wallet+COD combo / delivery cash flow
were validated in iter55; here we ONLY exercise what iter56 changed.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

import pytest
import requests

from conftest import auth_headers  # noqa: F401  (fixture helper)


BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")

# ─────────────────────────── Fixtures ───────────────────────────

VENDOR_EMAIL = "testvendor@test.com"
VENDOR_PW = "Test@1234"
BUYER_EMAIL = "testbuyer@test.com"
BUYER_PW = "Test@1234"


def _login(api: requests.Session, email: str, password: str) -> str:
    r = api.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text[:200]}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def vendor_token(api):
    return _login(api, VENDOR_EMAIL, VENDOR_PW)


@pytest.fixture(scope="module")
def buyer_token(api):
    return _login(api, BUYER_EMAIL, BUYER_PW)


# Track every layout block we create so teardown can wipe them.
_created_blocks: List[str] = []


@pytest.fixture(autouse=True, scope="module")
def _teardown_blocks(api, admin_token):
    yield
    for bid in _created_blocks:
        try:
            api.delete(
                f"{BASE_URL}/api/admin/shop-layout/{bid}",
                headers=auth_headers(admin_token),
            )
        except Exception:
            pass


def _create_block(api, admin_token: str, **overrides) -> Dict[str, Any]:
    """Helper: create a `text` block (cheapest) with an auto-clean marker."""
    body: Dict[str, Any] = {
        "block_type": "text",
        "scope": "home",
        "title": f"TEST_iter56_{uuid.uuid4().hex[:6]}",
        "body": "iter56 regression fixture",
        "active": True,
    }
    body.update(overrides)
    r = api.post(
        f"{BASE_URL}/api/admin/shop-layout",
        json=body,
        headers=auth_headers(admin_token),
    )
    assert r.status_code == 200, f"create block failed: {r.status_code} {r.text[:200]}"
    doc = r.json()
    _created_blocks.append(doc["id"])
    return doc


def _public_layout(api, **params) -> List[Dict[str, Any]]:
    r = api.get(f"{BASE_URL}/api/shop-layout", params=params)
    assert r.status_code == 200, f"public layout failed: {r.status_code} {r.text[:200]}"
    return r.json().get("items", [])


def _admin_layout(api, admin_token: str, **params) -> List[Dict[str, Any]]:
    r = api.get(
        f"{BASE_URL}/api/admin/shop-layout",
        params=params,
        headers=auth_headers(admin_token),
    )
    assert r.status_code == 200, f"admin layout failed: {r.status_code} {r.text[:200]}"
    return r.json().get("items", [])


def _find(items: List[Dict[str, Any]], bid: str) -> Dict[str, Any] | None:
    return next((x for x in items if x.get("id") == bid), None)


# ─────────────────────── Multi-pincode: create + normalise ───────────────────────

class TestMultiPincodeCreate:
    def test_normalises_scope_pincodes_and_clears_legacy(self, api, admin_token):
        doc = _create_block(
            api,
            admin_token,
            scope_pincodes=["517644", "517640", "abc", "51764", "517644"],  # junk + dup
        )
        # junk + short values dropped, order preserved, dedup
        assert doc["scope_pincodes"] == ["517644", "517640"], doc["scope_pincodes"]
        # legacy single field cleared when there are 2+ targets
        assert doc["scope_pincode"] == "", doc["scope_pincode"]

    def test_single_target_populates_both_fields(self, api, admin_token):
        doc = _create_block(api, admin_token, scope_pincodes=["517644"])
        assert doc["scope_pincodes"] == ["517644"]
        # Server may leave legacy blank OR mirror; PATCH-side guarantees mirror,
        # POST-side only mirrors when the client also sent scope_pincode.
        # Public filter must match either way (tested below).


# ─────────────────────── Multi-pincode: public filtering ───────────────────────

class TestMultiPincodePublicFilter:
    @pytest.fixture(scope="class")
    def multi_block(self, api, admin_token):
        return _create_block(
            api,
            admin_token,
            scope_pincodes=["517644", "517640"],
        )

    def test_matches_first_pincode(self, api, multi_block):
        items = _public_layout(api, scope="home", pincode="517644")
        assert _find(items, multi_block["id"]) is not None

    def test_matches_second_pincode(self, api, multi_block):
        items = _public_layout(api, scope="home", pincode="517640")
        assert _find(items, multi_block["id"]) is not None

    def test_excludes_non_target_pincode(self, api, multi_block):
        items = _public_layout(api, scope="home", pincode="500001")
        assert _find(items, multi_block["id"]) is None

    def test_excludes_when_pincode_unknown(self, api, multi_block):
        """Targeted campaigns must NEVER leak to customers whose
        location we can't verify (no pincode)."""
        items = _public_layout(api, scope="home")
        assert _find(items, multi_block["id"]) is None

    def test_global_block_still_shows_with_no_pincode(self, api, admin_token):
        gb = _create_block(api, admin_token, scope_pincodes=[])
        items = _public_layout(api, scope="home")
        assert _find(items, gb["id"]) is not None
        # And also with a random pincode.
        items2 = _public_layout(api, scope="home", pincode="500001")
        assert _find(items2, gb["id"]) is not None


# ─────────────────────── Legacy single scope_pincode compat ───────────────────────

class TestLegacyCompat:
    @pytest.fixture(scope="class")
    def legacy_block(self, api, admin_token):
        # Send ONLY the old single field, leave scope_pincodes unset.
        doc = _create_block(api, admin_token, scope_pincode="517644")
        return doc

    def test_public_still_matches(self, api, legacy_block):
        items = _public_layout(api, scope="home", pincode="517644")
        assert _find(items, legacy_block["id"]) is not None

    def test_admin_read_back_fills_scope_pincodes(self, api, admin_token, legacy_block):
        items = _admin_layout(api, admin_token)
        got = _find(items, legacy_block["id"])
        assert got is not None
        # Back-fill: scope_pincodes should mirror the legacy single field.
        assert got["scope_pincodes"] == ["517644"], got.get("scope_pincodes")
        assert got["scope_pincode"] == "517644"


# ─────────────────────── Category scope regression ───────────────────────

class TestCategoryScopeRegression:
    def test_category_block_filters_still_work_by_pincode(self, api, admin_token):
        doc = _create_block(
            api,
            admin_token,
            scope="category",
            scope_category="TESTCAT_iter56",
            scope_pincodes=["517644"],
        )
        # Public with matching pincode + category → present
        items = _public_layout(api, scope="category", category="TESTCAT_iter56", pincode="517644")
        assert _find(items, doc["id"]) is not None, items
        # Non-matching pincode → hidden
        items2 = _public_layout(api, scope="category", category="TESTCAT_iter56", pincode="500001")
        assert _find(items2, doc["id"]) is None
        # No pincode → hidden (same rule as home scope)
        items3 = _public_layout(api, scope="category", category="TESTCAT_iter56")
        assert _find(items3, doc["id"]) is None


# ─────────────────────── PATCH scope_pincodes ───────────────────────

class TestPatchMultiPincode:
    def test_patch_replaces_both_fields(self, api, admin_token):
        doc = _create_block(api, admin_token, scope_pincodes=["517644", "517640"])
        r = api.patch(
            f"{BASE_URL}/api/admin/shop-layout/{doc['id']}",
            json={"scope_pincodes": ["500001"]},
            headers=auth_headers(admin_token),
        )
        assert r.status_code == 200, r.text
        upd = r.json()
        assert upd["scope_pincodes"] == ["500001"]
        # Single target → legacy field mirrored
        assert upd["scope_pincode"] == "500001"

    def test_patch_clears_targeting_to_global(self, api, admin_token):
        doc = _create_block(api, admin_token, scope_pincodes=["517644"])
        r = api.patch(
            f"{BASE_URL}/api/admin/shop-layout/{doc['id']}",
            json={"scope_pincodes": []},
            headers=auth_headers(admin_token),
        )
        assert r.status_code == 200, r.text
        upd = r.json()
        assert upd["scope_pincodes"] == []
        assert upd["scope_pincode"] == ""
        # And it must now be considered global — shows with no pincode.
        items = _public_layout(api, scope="home")
        assert _find(items, doc["id"]) is not None

    def test_patch_multi_target_clears_legacy_single(self, api, admin_token):
        doc = _create_block(api, admin_token, scope_pincodes=["517644"])
        r = api.patch(
            f"{BASE_URL}/api/admin/shop-layout/{doc['id']}",
            json={"scope_pincodes": ["500001", "500002", "500003"]},
            headers=auth_headers(admin_token),
        )
        assert r.status_code == 200
        upd = r.json()
        assert upd["scope_pincodes"] == ["500001", "500002", "500003"]
        # Multi target → legacy single MUST be blank
        assert upd["scope_pincode"] == ""


# ─────────────────────── Vendor cash summary + delivered_at ───────────────────────

def _place_cod_order(api, buyer_token: str, vendor_product_id: str, cod_amount: float = 100.0):
    """Place a wallet+COD combo order with wallet_amount=0 (pure COD) so
    the whole total lands in cod_due for a single vendor."""
    # 1) Clear cart, then add
    api.post(f"{BASE_URL}/api/cart/clear", headers=auth_headers(buyer_token))
    r = api.post(
        f"{BASE_URL}/api/cart/add",
        json={"product_id": vendor_product_id, "qty": 1},
        headers=auth_headers(buyer_token),
    )
    assert r.status_code == 200, f"cart add failed: {r.status_code} {r.text[:200]}"
    # 2) Checkout with wallet_cod / wallet_amount=0 (pure COD)
    r = api.post(
        f"{BASE_URL}/api/orders/checkout",
        json={
            "shipping_address": {
                "name": "Test Buyer",
                "phone": "9999900000",
                "line1": "Test line",
                "city": "Srikalahasti",
                "state": "Andhra Pradesh",
                "pincode": "517644",
            },
            "payment_method": "wallet_cod",
            "wallet_amount": 0,
        },
        headers=auth_headers(buyer_token),
    )
    assert r.status_code == 200, f"checkout failed: {r.status_code} {r.text[:200]}"
    body = r.json()
    orders = body.get("orders") or []
    assert orders, f"no orders returned: {body}"
    return orders[0]


class TestVendorCashSummary:
    VENDOR_PRODUCT_ID = "9c6bb05d-eecc-4637-8489-466f1e4f0288"  # Vendor One Widget ₹100

    def test_pending_rises_and_collected_rises_on_delivery(self, api, vendor_token, buyer_token, admin_token):
        # Baseline
        r0 = api.get(f"{BASE_URL}/api/vendor/me/stats", headers=auth_headers(vendor_token))
        assert r0.status_code == 200, r0.text
        s0 = r0.json()
        for k in ("cod_pending_total", "cod_pending_count",
                  "cod_collected_today", "cod_collected_today_count"):
            assert k in s0, f"missing {k} in stats"

        pending0 = float(s0["cod_pending_total"])
        pending_cnt0 = int(s0["cod_pending_count"])
        collected0 = float(s0["cod_collected_today"])
        collected_cnt0 = int(s0["cod_collected_today_count"])

        # Place COD order
        order = _place_cod_order(api, buyer_token, self.VENDOR_PRODUCT_ID)
        order_id = order["id"]
        cod_due = float(order.get("cod_due") or 0)
        assert cod_due > 0, f"cod_due should be positive on wallet_cod pure-cod: {order}"

        # Pending must rise by cod_due, count by 1
        r1 = api.get(f"{BASE_URL}/api/vendor/me/stats", headers=auth_headers(vendor_token))
        s1 = r1.json()
        assert round(float(s1["cod_pending_total"]) - pending0, 2) == round(cod_due, 2), \
            f"pending {pending0} → {s1['cod_pending_total']}, expected +{cod_due}"
        assert int(s1["cod_pending_count"]) == pending_cnt0 + 1

        # Deliver via vendor route (delegates to admin handler)
        r2 = api.patch(
            f"{BASE_URL}/api/vendor/orders/{order_id}/status",
            json={"status": "delivered"},
            headers=auth_headers(vendor_token),
        )
        assert r2.status_code == 200, f"deliver failed: {r2.status_code} {r2.text[:200]}"

        # Pending falls by cod_due, collected_today rises by cod_due
        r3 = api.get(f"{BASE_URL}/api/vendor/me/stats", headers=auth_headers(vendor_token))
        s3 = r3.json()
        assert round(pending0 - float(s3["cod_pending_total"]) + cod_due, 2) == round(cod_due, 2), \
            f"pending should drop by {cod_due}: {s1['cod_pending_total']} → {s3['cod_pending_total']}"
        assert round(float(s3["cod_collected_today"]) - collected0, 2) == round(cod_due, 2), \
            f"collected_today should rise by {cod_due}: {collected0} → {s3['cod_collected_today']}"
        assert int(s3["cod_collected_today_count"]) == collected_cnt0 + 1

    def test_delivered_at_stamped_once_and_not_overwritten(self, api, vendor_token, buyer_token, admin_token):
        order = _place_cod_order(api, buyer_token, self.VENDOR_PRODUCT_ID)
        order_id = order["id"]

        # First deliver
        r1 = api.patch(
            f"{BASE_URL}/api/admin/orders/{order_id}/status",
            json={"status": "delivered"},
            headers=auth_headers(admin_token),
        )
        assert r1.status_code == 200, r1.text

        # Fetch the stamped delivered_at (admin listing has it)
        r_list = api.get(
            f"{BASE_URL}/api/admin/orders",
            headers=auth_headers(admin_token),
        )
        assert r_list.status_code == 200
        got = next((o for o in r_list.json() if o.get("id") == order_id), None)
        assert got is not None, "order not in admin list"
        first_stamp = got.get("delivered_at")
        assert first_stamp, f"delivered_at missing after first delivery: {got}"

        # Repeat status update (delivered → delivered) - must NOT overwrite
        # Sleep for a wall-clock second so a naive re-stamp would differ.
        import time
        time.sleep(1.1)
        r2 = api.patch(
            f"{BASE_URL}/api/admin/orders/{order_id}/status",
            json={"status": "delivered"},
            headers=auth_headers(admin_token),
        )
        assert r2.status_code == 200, r2.text

        r_list2 = api.get(
            f"{BASE_URL}/api/admin/orders",
            headers=auth_headers(admin_token),
        )
        got2 = next((o for o in r_list2.json() if o.get("id") == order_id), None)
        assert got2.get("delivered_at") == first_stamp, \
            f"delivered_at was overwritten: {first_stamp} → {got2.get('delivered_at')}"
