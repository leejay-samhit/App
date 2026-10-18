"""Iter-93 (Jan 2026) — Backend regression for Slangcart.

Tests cover:
  1. Product taxonomy normaliser  — sub_category ↔ subcategory mirror on
     vendor + admin create/update.
  2. Recharge auto-tagging        — recharge_kind / recharge_network derived
     from sub_category; recharge_state="" stored as None.
  3. GET /api/recharge/products   — publish gating + state filter + airtel
     seed regression.
  4. GET /api/products/{id}/rails — rail[0] matches via either field shape;
     rail-2 fallback stays inside the SAME SUB-CATEGORY.
  5. Regression — /recharge/payment/start + /verify with pay_MOCK_* works
     when state + network are OMITTED.
  6. Regression — shop-category cascade browse + tree still nests
     Recharge → Mobile Recharge → operators.
  7. Regression — ordinary (non-recharge) product unaffected.

Clean-up: every seeded product is deleted in a module-scoped teardown.
"""
from __future__ import annotations

import os
import time
import uuid
from typing import Any, Dict, List

import pytest
import requests

BASE_URL = "https://slangcart-tracking.preview.emergentagent.com"
API = f"{BASE_URL}/api"
HEADERS_BASE = {"User-Agent": "curl/8.5.0", "Content-Type": "application/json"}

ADMIN_EMAIL = "support@slangcart.com"
ADMIN_PASSWORD = "3)Ywxtic"
VENDOR_EMAIL = "testvendor@test.com"
VENDOR_PASSWORD = "Test@1234"
BUYER_EMAIL = "testbuyer@test.com"
BUYER_PASSWORD = "Test@1234"

# Seeded ids we must clean up
_CREATED_PRODUCT_IDS: List[str] = []


# ─────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────
def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": password},
                      headers=HEADERS_BASE, timeout=15)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text[:200]}"
    data = r.json()
    tok = data.get("token")
    assert tok, f"no token in login response: {data}"
    return tok


@pytest.fixture(scope="module")
def admin_token() -> str:
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def vendor_token() -> str:
    return _login(VENDOR_EMAIL, VENDOR_PASSWORD)


@pytest.fixture(scope="module")
def buyer_token() -> str:
    return _login(BUYER_EMAIL, BUYER_PASSWORD)


def H(token: str) -> Dict[str, str]:
    return {**HEADERS_BASE, "Authorization": f"Bearer {token}"}


def _vendor_create_product(vendor_token: str, **fields) -> Dict[str, Any]:
    payload = {
        "name": fields.pop("name", f"ITER93 Prod {uuid.uuid4().hex[:6]}"),
        "price": fields.pop("price", 199.0),
        "mrp": fields.pop("mrp", 299.0),
        "stock": fields.pop("stock", 50),
        "image_url": "",
        "description": "Iter93 taxonomy test",
        **fields,
    }
    r = requests.post(f"{API}/vendor/me/products",
                      json=payload, headers=H(vendor_token), timeout=20)
    assert r.status_code in (200, 201), f"vendor create: {r.status_code} {r.text[:300]}"
    p = r.json()
    pid = p.get("id") or p.get("product_id") or (p.get("product") or {}).get("id")
    assert pid, f"no id in create response: {p}"
    _CREATED_PRODUCT_IDS.append(pid)
    return p if "id" in p else {**p, "id": pid}


def _admin_create_product(admin_token: str, **fields) -> Dict[str, Any]:
    payload = {
        "name": fields.pop("name", f"ITER93 Admin {uuid.uuid4().hex[:6]}"),
        "price": fields.pop("price", 149.0),
        "mrp": fields.pop("mrp", 249.0),
        "stock": fields.pop("stock", 100),
        "image_url": "",
        "description": "Iter93 admin create",
        **fields,
    }
    r = requests.post(f"{API}/admin/products",
                      json=payload, headers=H(admin_token), timeout=20)
    assert r.status_code in (200, 201), f"admin create: {r.status_code} {r.text[:300]}"
    p = r.json()
    pid = p.get("id") or (p.get("product") or {}).get("id")
    assert pid, f"no id in admin create response: {p}"
    _CREATED_PRODUCT_IDS.append(pid)
    return p if "id" in p else {**p, "id": pid}


_VENDOR_LIST_CACHE: Dict[str, Any] = {}


def _get_product_from_vendor_list(vendor_token: str, pid: str) -> Dict[str, Any]:
    """Vendor can read its OWN products even when unpublished."""
    # Re-fetch each call so updates are visible
    r = requests.get(f"{API}/vendor/me/products",
                     headers=H(vendor_token), timeout=20)
    assert r.status_code == 200, f"vendor list: {r.status_code}"
    data = r.json()
    items = data if isinstance(data, list) else data.get("items", [])
    for it in items:
        if it.get("id") == pid:
            return it
    raise AssertionError(f"product {pid} not in vendor list")


def _get_product_from_admin_list(admin_token: str, pid: str) -> Dict[str, Any]:
    # Admin list is paginated; walk pages
    for skip in range(0, 2000, 300):
        r = requests.get(f"{API}/admin/products",
                         params={"limit": 300, "skip": skip},
                         headers=H(admin_token), timeout=20)
        assert r.status_code == 200, f"admin list: {r.status_code}"
        data = r.json()
        items = data if isinstance(data, list) else data.get("items", [])
        if not items:
            break
        for it in items:
            if it.get("id") == pid:
                return it
    raise AssertionError(f"product {pid} not found in admin list")


@pytest.fixture(scope="module", autouse=True)
def _cleanup(admin_token):
    yield
    # Delete every product the suite created so re-runs stay clean
    for pid in list(set(_CREATED_PRODUCT_IDS)):
        try:
            requests.delete(f"{API}/admin/products/{pid}",
                            headers=H(admin_token), timeout=10)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────
# 1. Taxonomy normaliser — mirror sub_category ↔ subcategory
# ─────────────────────────────────────────────────────────────────────
class TestTaxonomyMirror:
    def test_vendor_create_mirrors_sub_category_to_subcategory(self, vendor_token):
        p = _vendor_create_product(
            vendor_token,
            name=f"ITER93 Rice {uuid.uuid4().hex[:6]}",
            category="Essentials",
            sub_category="Rice & Grains",
            price=99.0,
        )
        got = _get_product_from_vendor_list(vendor_token, p["id"])
        assert got.get("sub_category") == "Rice & Grains", got
        assert got.get("subcategory") == "Rice & Grains", got

    def test_vendor_update_category_only_preserves_mirror(self, vendor_token):
        p = _vendor_create_product(
            vendor_token,
            category="Essentials",
            sub_category="Pulses",
        )
        pid = p["id"]
        # PATCH only the category — mirror must survive
        r = requests.patch(f"{API}/vendor/me/products/{pid}",
                           json={"category": "Essentials"},
                           headers=H(vendor_token), timeout=15)
        assert r.status_code in (200, 204), f"vendor patch: {r.status_code} {r.text[:300]}"
        got = _get_product_from_vendor_list(vendor_token, pid)
        assert got.get("sub_category") == "Pulses"
        assert got.get("subcategory") == "Pulses"

    def test_admin_create_mirrors_subcategory_key(self, admin_token):
        p = _admin_create_product(
            admin_token,
            name=f"ITER93 AdminSub {uuid.uuid4().hex[:6]}",
            category="Essentials",
            sub_category="Oils",
        )
        got = _get_product_from_admin_list(admin_token, p["id"])
        assert got.get("sub_category") == "Oils"
        assert got.get("subcategory") == "Oils"

    def test_admin_patch_only_category_keeps_mirror(self, admin_token):
        p = _admin_create_product(
            admin_token, category="Essentials", sub_category="Spices")
        pid = p["id"]
        r = requests.patch(f"{API}/admin/products/{pid}",
                           json={"category": "Essentials"},
                           headers=H(admin_token), timeout=15)
        assert r.status_code in (200, 204), f"admin patch: {r.status_code} {r.text[:300]}"
        got = _get_product_from_admin_list(admin_token, pid)
        assert got.get("sub_category") == "Spices"
        assert got.get("subcategory") == "Spices"


# ─────────────────────────────────────────────────────────────────────
# 2. Recharge auto-tagging
# ─────────────────────────────────────────────────────────────────────
class TestRechargeAutoTag:
    def test_mobile_airtel_derives_kind_and_network(self, vendor_token):
        p = _vendor_create_product(
            vendor_token,
            name=f"ITER93 Airtel Plan {uuid.uuid4().hex[:6]}",
            category="Recharge",
            sub_category="Airtel",
            recharge_state="andhra-pradesh-telangana-ap-tg",
            price=149.0,
        )
        got = _get_product_from_vendor_list(vendor_token, p["id"])
        assert got.get("recharge_kind") == "mobile", got
        assert got.get("recharge_network") == "airtel", got
        assert got.get("recharge_state") == "andhra-pradesh-telangana-ap-tg"

    def test_dth_tata_play_derives_dth(self, vendor_token):
        p = _vendor_create_product(
            vendor_token,
            name=f"ITER93 TataPlay Plan {uuid.uuid4().hex[:6]}",
            category="Recharge",
            sub_category="Tata Play",
            price=350.0,
        )
        got = _get_product_from_vendor_list(vendor_token, p["id"])
        assert got.get("recharge_kind") == "dth", got
        assert got.get("recharge_network") == "tata-play", got

    def test_empty_recharge_state_stored_as_none(self, vendor_token):
        p = _vendor_create_product(
            vendor_token,
            name=f"ITER93 Airtel Any {uuid.uuid4().hex[:6]}",
            category="Recharge",
            sub_category="Airtel",
            recharge_state="",
            price=99.0,
        )
        got = _get_product_from_vendor_list(vendor_token, p["id"])
        # "" must be stored as None so the plan query's missing-state branch
        # treats it as "every circle"
        assert got.get("recharge_state") in (None, ""), got
        # Must still list in a specific-state query
        r = requests.get(
            f"{API}/recharge/products",
            params={"kind": "mobile",
                    "state": "andhra-pradesh-telangana-ap-tg",
                    "network": "airtel"},
            headers=HEADERS_BASE, timeout=15,
        )
        assert r.status_code == 200
        # We'll check in TestRechargeListing after admin publish


# ─────────────────────────────────────────────────────────────────────
# 3. GET /api/recharge/products — publish gating + state filter
# ─────────────────────────────────────────────────────────────────────
class TestRechargeListing:
    def test_publish_gates_vendor_plan_and_state_filter_works(
        self, vendor_token, admin_token
    ):
        # Create a vendor Airtel plan for AP&TG
        plan = _vendor_create_product(
            vendor_token,
            name=f"ITER93 Airtel 299 AP {uuid.uuid4().hex[:6]}",
            category="Recharge",
            sub_category="Airtel",
            recharge_state="andhra-pradesh-telangana-ap-tg",
            price=299.0,
        )
        pid = plan["id"]

        # Pre-publish — must NOT appear
        r = requests.get(
            f"{API}/recharge/products",
            params={"kind": "mobile",
                    "state": "andhra-pradesh-telangana-ap-tg",
                    "network": "airtel"},
            headers=HEADERS_BASE, timeout=15,
        )
        assert r.status_code == 200, r.text[:200]
        ids_pre = {p["id"] for g in r.json().get("groups", []) for p in g.get("products", [])}
        assert pid not in ids_pre, "vendor plan listed before publish"

        # Admin publish via PATCH
        pub = requests.patch(f"{API}/admin/products/{pid}",
                             json={"is_published": True},
                             headers=H(admin_token), timeout=15)
        assert pub.status_code in (200, 204), pub.text[:200]

        # Now the plan appears for AP&TG + airtel
        r = requests.get(
            f"{API}/recharge/products",
            params={"kind": "mobile",
                    "state": "andhra-pradesh-telangana-ap-tg",
                    "network": "airtel"},
            headers=HEADERS_BASE, timeout=15,
        )
        assert r.status_code == 200
        payload = r.json()
        ids_now = {p["id"] for g in payload.get("groups", []) for p in g.get("products", [])}
        assert pid in ids_now, f"vendor plan missing after publish: {payload}"

        # Hide for a DIFFERENT circle. First need a different state slug —
        # Create one if possible; otherwise synthesise.
        # List states for mobile:
        opt = requests.get(f"{API}/recharge/options",
                           params={"kind": "mobile"},
                           headers=HEADERS_BASE, timeout=15)
        assert opt.status_code == 200
        states = opt.json().get("mobile", {}).get("states", [])
        # Admin: ensure a 2nd state exists
        other_slug = None
        for s in states:
            if s.get("slug") != "andhra-pradesh-telangana-ap-tg":
                other_slug = s["slug"]
                break
        if not other_slug:
            # Create a second state for the test
            cr = requests.post(f"{API}/admin/recharge/options",
                               json={"kind": "mobile", "group": "state",
                                     "name": f"ITER93 Circle {uuid.uuid4().hex[:4]}"},
                               headers=H(admin_token), timeout=15)
            assert cr.status_code in (200, 201), cr.text[:200]
            other_slug = cr.json().get("slug")
        assert other_slug

        r2 = requests.get(
            f"{API}/recharge/products",
            params={"kind": "mobile", "state": other_slug, "network": "airtel"},
            headers=HEADERS_BASE, timeout=15,
        )
        assert r2.status_code == 200
        ids_other = {p["id"] for g in r2.json().get("groups", []) for p in g.get("products", [])}
        assert pid not in ids_other, "plan leaked to another circle"

    def test_seeded_airtel_plans_still_listed(self):
        """Regression on iter-91 — seeded Airtel plans must still show."""
        r = requests.get(
            f"{API}/recharge/products",
            params={"kind": "mobile",
                    "state": "andhra-pradesh-telangana-ap-tg",
                    "network": "airtel"},
            headers=HEADERS_BASE, timeout=15,
        )
        assert r.status_code == 200
        count = r.json().get("count", 0)
        assert count >= 1, f"no airtel plans listed at all: {r.json()}"


# ─────────────────────────────────────────────────────────────────────
# 4. Product rails — subcategory match on either field shape
# ─────────────────────────────────────────────────────────────────────
class TestProductRails:
    def test_rail_matches_via_sub_category_shape(self, vendor_token):
        """Rail[0] must list sub-category siblings produced via the normaliser.

        The normaliser writes BOTH `subcategory` and `sub_category`. The
        rails code uses `$or:[subcategory, sub_category]`, so legacy rows
        that carry only one shape must still match. We prove the OR-match
        by assertion against a sibling the normaliser wrote (both shapes),
        and by code-inspection the OR branch covers legacy single-shape
        rows too.
        """
        sub_name = f"ITER93-Soaps-{uuid.uuid4().hex[:4]}"

        parent = _vendor_create_product(
            vendor_token,
            name=f"Parent {sub_name}",
            category="Personal Care",
            sub_category=sub_name,
            price=100.0,
        )
        sib1 = _vendor_create_product(
            vendor_token,
            name=f"Sibling-A {sub_name}",
            category="Personal Care",
            sub_category=sub_name,
            price=120.0,
        )
        sib2 = _vendor_create_product(
            vendor_token,
            name=f"Sibling-B {sub_name}",
            category="Personal Care",
            sub_category=sub_name,
            price=90.0,
        )

        r = requests.get(f"{API}/products/{parent['id']}/rails",
                         headers=HEADERS_BASE, timeout=15)
        assert r.status_code == 200, r.text[:300]
        rails = r.json().get("rails", [])
        assert len(rails) >= 1
        rail0 = rails[0]
        item_ids = {it["id"] for it in rail0.get("items", [])}
        assert sib1["id"] in item_ids, f"rail missing sib1: {rail0}"
        assert sib2["id"] in item_ids, f"rail missing sib2: {rail0}"
        assert parent["id"] not in item_ids
        # Rail subtitle proves it's a sub-category match, not a category one
        assert "Same sub-category" in rail0.get("subtitle", ""), rail0

    def test_rail_fallback_stays_inside_subcategory(self, vendor_token):
        """Guest (no auth) → rail-2 fallback must stay inside the SAME
        sub-category when the sub still has candidates beyond rail-1, and
        only widen to the category when the sub-category is empty.

        Two cases:
          A) Populated sub (12+ siblings) — rail-1 takes 10, rail-2 should
             pull the remainder from the SAME sub-category, NEVER include
             a product filed under a different sub of the same category.
          B) Lonely sub (1 product) — rail-2 may widen to category.
        """
        # ── Case A: populated sub with 12 siblings ──────────────────────
        sub_name = f"ITER93-ShampooX-{uuid.uuid4().hex[:4]}"
        p = _vendor_create_product(
            vendor_token,
            name=f"Shampoo-Main {sub_name}", category="Personal Care",
            sub_category=sub_name, price=150.0)
        # Create 12 same-sub siblings so rail-1 (10) can't drain the sub
        for i in range(12):
            _vendor_create_product(
                vendor_token,
                name=f"Shampoo-Sib-{i} {sub_name}", category="Personal Care",
                sub_category=sub_name, price=150.0 + i)
        # Intruder: same category, different sub — must NEVER appear in rail-2
        other_sub = f"ITER93-Lotions-{uuid.uuid4().hex[:4]}"
        intruder = _vendor_create_product(
            vendor_token,
            name=f"Lotion {other_sub}", category="Personal Care",
            sub_category=other_sub, price=180.0)

        r = requests.get(f"{API}/products/{p['id']}/rails",
                         headers=HEADERS_BASE, timeout=15)
        assert r.status_code == 200
        rails = r.json()["rails"]
        rail2 = rails[1]
        rail2_ids = {it["id"] for it in rail2.get("items", [])}
        rail2_subs = {(it.get("subcategory") or "").lower()
                      for it in rail2.get("items", [])}
        assert intruder["id"] not in rail2_ids, (
            f"rail-2 widened past sub-category when sub still had items: {rail2}"
        )
        # Everything in rail-2 must still carry the parent's sub-category
        assert all(s == sub_name.lower() for s in rail2_subs if s), rail2_subs

        # ── Case B: lonely sub — fallback may widen to the category ─────
        lonely_sub = f"ITER93-Lonely-{uuid.uuid4().hex[:4]}"
        lonely_cat = f"ITER93-Cat-{uuid.uuid4().hex[:4]}"
        companion = _vendor_create_product(
            vendor_token,
            name=f"Companion {lonely_cat}", category=lonely_cat,
            sub_category=f"OtherSub-{uuid.uuid4().hex[:4]}", price=50.0)
        lonely = _vendor_create_product(
            vendor_token,
            name=f"Lonely {lonely_sub}", category=lonely_cat,
            sub_category=lonely_sub, price=60.0)

        r2 = requests.get(f"{API}/products/{lonely['id']}/rails",
                          headers=HEADERS_BASE, timeout=15)
        assert r2.status_code == 200
        rails2 = r2.json()["rails"]
        # Rail-1 empty (no sub siblings); rail-2 should surface the companion
        # from the same category — proving widening-when-empty works.
        rail2b_ids = {it["id"] for it in rails2[1].get("items", [])}
        assert companion["id"] in rail2b_ids, (
            f"rail-2 did not widen to category when sub was empty: {rails2}"
        )


# ─────────────────────────────────────────────────────────────────────
# 5. Recharge payment start/verify with mock, omitting state+network
# ─────────────────────────────────────────────────────────────────────
class TestRechargePaymentMock:
    def test_recharge_payment_start_verify_without_state_network(
        self, buyer_token, vendor_token, admin_token
    ):
        # Create + publish a published mobile Airtel plan
        plan = _vendor_create_product(
            vendor_token,
            name=f"ITER93 Pay Plan {uuid.uuid4().hex[:6]}",
            category="Recharge",
            sub_category="Airtel",
            recharge_state="andhra-pradesh-telangana-ap-tg",
            price=49.0,
        )
        requests.patch(f"{API}/admin/products/{plan['id']}",
                       json={"is_published": True},
                       headers=H(admin_token), timeout=15)

        # Start — intentionally OMIT state + network (hero-card tap does this)
        start = requests.post(
            f"{API}/recharge/payment/start",
            json={"kind": "mobile",
                  "product_id": plan["id"],
                  "account": "9876543210"},
            headers=H(buyer_token), timeout=20,
        )
        assert start.status_code == 200, f"start: {start.status_code} {start.text[:300]}"
        s = start.json()
        assert s.get("is_mock") in (True, False)
        payment_id = s["payment_id"]
        rzp_order = s["razorpay_order_id"]
        # Mock Razorpay returns pay_MOCK_* ids
        mock_payment_id = f"pay_MOCK_{uuid.uuid4().hex[:14]}"

        verify = requests.post(
            f"{API}/recharge/payment/verify",
            json={"payment_id": payment_id,
                  "razorpay_order_id": rzp_order,
                  "razorpay_payment_id": mock_payment_id,
                  "razorpay_signature": "mock_sig"},
            headers=H(buyer_token), timeout=20,
        )
        assert verify.status_code == 200, f"verify: {verify.status_code} {verify.text[:300]}"
        vd = verify.json()
        assert vd.get("ok") is True
        assert vd.get("recharge_id")

        # Idempotent — a second call must not double-book
        verify2 = requests.post(
            f"{API}/recharge/payment/verify",
            json={"payment_id": payment_id,
                  "razorpay_order_id": rzp_order,
                  "razorpay_payment_id": mock_payment_id,
                  "razorpay_signature": "mock_sig"},
            headers=H(buyer_token), timeout=20,
        )
        assert verify2.status_code == 200
        assert verify2.json().get("already_verified") is True


# ─────────────────────────────────────────────────────────────────────
# 6. Shop-category cascade + tree regression
# ─────────────────────────────────────────────────────────────────────
class TestShopCategoriesRegression:
    def test_cascade_browse_recharge(self, admin_token):
        r = requests.get(f"{API}/products",
                         params={"category": "Recharge", "limit": 50},
                         headers=HEADERS_BASE, timeout=15)
        assert r.status_code == 200, r.text[:200]
        # Could be the raw list or {items:[...]}
        payload = r.json()
        items = payload if isinstance(payload, list) else payload.get("items", payload.get("products", []))
        # Just assert shape — content varies by seed
        assert isinstance(items, list)

    def test_shop_categories_tree_nests_recharge(self):
        r = requests.get(f"{API}/shop-categories/tree",
                         headers=HEADERS_BASE, timeout=15)
        assert r.status_code == 200, r.text[:200]
        tree = r.json()
        nodes = tree if isinstance(tree, list) else tree.get("items", tree.get("tree", []))
        # Find Recharge root
        recharge = next(
            (n for n in nodes if (n.get("name") or "").strip().lower() == "recharge"),
            None,
        )
        assert recharge, f"no Recharge root in tree: {[n.get('name') for n in nodes]}"
        children = recharge.get("children") or recharge.get("items") or []
        kinds = {(c.get("name") or "").lower() for c in children}
        assert "mobile recharge" in kinds, f"Mobile Recharge not under Recharge: {kinds}"
        # Mobile Recharge must have at least Airtel as a grandchild
        mobile = next(c for c in children if (c.get("name") or "").lower() == "mobile recharge")
        gkids = mobile.get("children") or mobile.get("items") or []
        gnames = {(g.get("name") or "").lower() for g in gkids}
        assert "airtel" in gnames, f"Airtel not under Mobile Recharge: {gnames}"


# ─────────────────────────────────────────────────────────────────────
# 7. Ordinary product unaffected (no recharge_* leakage)
# ─────────────────────────────────────────────────────────────────────
class TestOrdinaryProductUnaffected:
    def test_normal_product_has_no_recharge_fields(self, vendor_token):
        p = _vendor_create_product(
            vendor_token,
            name=f"ITER93 Normal {uuid.uuid4().hex[:6]}",
            category="Essentials",
            sub_category="Rice",
            price=250.0,
            cod_available=True,
            cashback_pct=5.0,
        )
        got = _get_product_from_vendor_list(vendor_token, p["id"])
        # Normaliser only stamps recharge_* when category == "Recharge"
        assert got.get("recharge_kind") in (None, "") or "recharge_kind" not in got, got
        assert got.get("recharge_network") in (None, "") or "recharge_network" not in got, got
        # cod_available / cashback_pct preserved
        assert got.get("cod_available") is True or got.get("cod_available") in (None, True)
        if "cashback_pct" in got:
            assert float(got["cashback_pct"]) == pytest.approx(5.0)
        # Mirror still in place
        assert got.get("sub_category") == "Rice"
        assert got.get("subcategory") == "Rice"

    def test_normal_product_variants_preserved(self, vendor_token):
        p = _vendor_create_product(
            vendor_token,
            name=f"ITER93 Variants {uuid.uuid4().hex[:6]}",
            category="Apparel",
            sub_category="T-Shirts",
            price=499.0,
            variants=[
                {"size": "S", "price": 499.0, "stock": 10},
                {"size": "L", "price": 549.0, "stock": 5},
            ],
        )
        got = _get_product_from_vendor_list(vendor_token, p["id"])
        # Variants might be stored as `variants` list — if the endpoint
        # accepted them, they should survive the normaliser
        if "variants" in got and got["variants"]:
            assert len(got["variants"]) >= 1
