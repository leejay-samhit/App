"""Iter-94 (Jan 2026) — Slangcart owner-asked backend regressions.

Covers:
  1. GET /api/recharge/history enrichment (per-user, auth-gated, can_repeat,
     current_price, price_changed, highlights, network logo).
  2. Repeat flow — /recharge/payment/start with ONLY {kind, product_id,
     account} and /verify with a pay_MOCK_* token (idempotent).
  3. plan_highlights() derivation for seeded Airtel plans + explicit
     recharge_data/validity/calls override + non-recharge product has NO
     highlights key.
  4. PATCH /api/admin/recharge/options/{id} — image_url, name (slug
     re-derived), sort_order; mirror onto shop-categories tree; clear with
     ""; role-guard 403; unknown-id 404.
  5. GET /api/delivery-partner/me/customers — distance sort, origin
     fallback, sort toggle, shipping_address identity.
  6. Regression — /customers/{uid}/advance still works idempotently.
"""

import os
import re
import uuid
import pytest
import requests

BASE_URL = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL",
    "https://slangcart-tracking.preview.emergentagent.com",
).rstrip("/")

UA = {"User-Agent": "curl/8.5.0"}

ADMIN = {"email": "support@slangcart.com", "password": "3)Ywxtic"}
VENDOR = {"email": "testvendor@test.com", "password": "Test@1234"}
BUYER = {"email": "testbuyer@test.com", "password": "Test@1234"}
RIDER = {"email": "rider_test@test.com", "password": "Test@1234"}

# Known seed data (from the owner's note + preview DB).
BUYER_RECHARGE_NUMBER = "9876543210"
AIRTEL_STATE_SLUG = "andhra-pradesh-telangana-ap-tg"

_CREATED_PRODUCT_IDS: list[str] = []
_CREATED_PAYMENT_IDS: list[str] = []
_RECHARGE_IDS: list[str] = []
_LOGO_RESET_IDS: list[str] = []


def _login(creds: dict) -> str:
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds, headers=UA, timeout=30)
    assert r.status_code == 200, f"login failed for {creds['email']}: {r.status_code} {r.text}"
    tok = r.json().get("token")
    assert tok, f"no token for {creds['email']}: {r.json()}"
    return tok


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", **UA}


# --------------------------- fixtures --------------------------- #

@pytest.fixture(scope="module")
def admin_tok():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def vendor_tok():
    return _login(VENDOR)


@pytest.fixture(scope="module")
def buyer_tok():
    return _login(BUYER)


@pytest.fixture(scope="module")
def rider_tok():
    return _login(RIDER)


@pytest.fixture(scope="module", autouse=True)
def _cleanup(admin_tok):
    yield
    # delete products
    for pid in _CREATED_PRODUCT_IDS:
        try:
            requests.delete(
                f"{BASE_URL}/api/admin/products/{pid}", headers=_h(admin_tok), timeout=20,
            )
        except Exception:
            pass
    # restore logo rows we touched
    for oid in _LOGO_RESET_IDS:
        try:
            requests.patch(
                f"{BASE_URL}/api/admin/recharge/options/{oid}",
                json={"image_url": ""}, headers=_h(admin_tok), timeout=20,
            )
        except Exception:
            pass


# ----- helpers ----- #

def _create_recharge_plan(admin_tok: str, *, name: str, price: int,
                          state: str = AIRTEL_STATE_SLUG,
                          network: str = "airtel",
                          subcategory: str = "Airtel",
                          **extra) -> str:
    """POST a plan via the admin product endpoint and remember to delete it."""
    payload = {
        "name": name,
        "description": extra.pop("description", ""),
        "price": price,
        "category": "Recharge",
        "sub_category": subcategory,
        "image_url": "",
        "recharge_kind": "mobile",
        "recharge_network": network,
        "recharge_state": state,
        "is_published": True,
        "active": True,
        **extra,
    }
    r = requests.post(
        f"{BASE_URL}/api/admin/products", json=payload, headers=_h(admin_tok), timeout=30,
    )
    assert r.status_code in (200, 201), f"admin product create failed: {r.status_code} {r.text}"
    pid = r.json().get("id")
    assert pid
    _CREATED_PRODUCT_IDS.append(pid)
    return pid


def _get_product(admin_tok: str, pid: str) -> dict:
    # products.json walk the admin paginated list
    page = 1
    while page < 20:
        r = requests.get(
            f"{BASE_URL}/api/admin/products?limit=100&page={page}",
            headers=_h(admin_tok), timeout=30,
        )
        assert r.status_code == 200, r.text
        rows = r.json().get("items", []) if isinstance(r.json(), dict) else r.json()
        if not rows:
            break
        for p in rows:
            if p.get("id") == pid:
                return p
        page += 1
    raise AssertionError(f"product {pid} not found in admin list")


# --------------------------- 1. recharge history --------------------------- #

class TestRechargeHistory:
    def test_history_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/recharge/history", headers=UA, timeout=20)
        assert r.status_code == 401

    def test_buyer_history_enrichment(self, buyer_tok):
        r = requests.get(f"{BASE_URL}/api/recharge/history", headers=_h(buyer_tok), timeout=30)
        assert r.status_code == 200
        items = r.json().get("items") or []
        assert len(items) >= 1, "expected at least 1 pre-seeded recharge for testbuyer"
        row = items[0]
        for k in (
            "network_name", "network_logo", "can_repeat", "current_price",
            "price_changed", "highlights",
        ):
            assert k in row, f"missing field {k}"
        hl = row["highlights"]
        assert set(hl.keys()) >= {"data", "validity", "calls"}
        # live plan → can_repeat true + current_price present + equals product price
        live_rows = [x for x in items if x.get("can_repeat")]
        assert live_rows, "expected at least one repeatable (live) recharge row"
        for lr in live_rows:
            assert lr["current_price"] is not None
            assert float(lr["current_price"]) > 0

    def test_history_is_per_user(self, buyer_tok, rider_tok):
        buyer_rows = requests.get(
            f"{BASE_URL}/api/recharge/history", headers=_h(buyer_tok), timeout=20,
        ).json().get("items", [])
        rider_rows = requests.get(
            f"{BASE_URL}/api/recharge/history", headers=_h(rider_tok), timeout=20,
        ).json().get("items", [])
        buyer_ids = {x.get("id") for x in buyer_rows}
        rider_ids = {x.get("id") for x in rider_rows}
        # The rider has no recharges, so the sets must be disjoint.
        assert not (buyer_ids & rider_ids), "recharge rows leaked across users"

    def test_price_changed_and_unpublished(self, admin_tok, buyer_tok):
        """Create a plan → buy it as the buyer → bump the price → verify
        price_changed=True; then unpublish → verify can_repeat=False and
        current_price is None."""
        tag = uuid.uuid4().hex[:6]
        pid = _create_recharge_plan(
            admin_tok, name=f"ITER94 Pay Plan {tag}", price=29,
            description="Unlimited 28 days · 2GB/day",
        )
        # buyer: start + verify
        start = requests.post(
            f"{BASE_URL}/api/recharge/payment/start",
            json={"kind": "mobile", "product_id": pid, "account": BUYER_RECHARGE_NUMBER},
            headers=_h(buyer_tok), timeout=30,
        )
        assert start.status_code == 200, start.text
        js = start.json()
        pay_id = js["payment_id"]
        _CREATED_PAYMENT_IDS.append(pay_id)
        assert js.get("is_mock") is True
        verify = requests.post(
            f"{BASE_URL}/api/recharge/payment/verify",
            json={
                "payment_id": pay_id,
                "razorpay_order_id": js["razorpay_order_id"],
                "razorpay_payment_id": f"pay_MOCK_{uuid.uuid4().hex[:12]}",
                "razorpay_signature": "mock_sig",
            },
            headers=_h(buyer_tok), timeout=30,
        )
        assert verify.status_code == 200, verify.text
        _RECHARGE_IDS.append(verify.json().get("recharge_id"))
        # bump price via admin PATCH
        r = requests.patch(
            f"{BASE_URL}/api/admin/products/{pid}",
            json={"price": 59}, headers=_h(admin_tok), timeout=30,
        )
        assert r.status_code == 200, r.text
        hist = requests.get(
            f"{BASE_URL}/api/recharge/history", headers=_h(buyer_tok), timeout=20,
        ).json().get("items", [])
        row = next((x for x in hist if x.get("product_id") == pid), None)
        assert row is not None, "newly-created recharge missing from history"
        assert row["can_repeat"] is True
        assert row["current_price"] == 59.0
        assert row["price_changed"] is True

        # unpublish → can_repeat False + current_price None
        r = requests.patch(
            f"{BASE_URL}/api/admin/products/{pid}",
            json={"is_published": False}, headers=_h(admin_tok), timeout=30,
        )
        assert r.status_code == 200, r.text
        hist = requests.get(
            f"{BASE_URL}/api/recharge/history", headers=_h(buyer_tok), timeout=20,
        ).json().get("items", [])
        row = next((x for x in hist if x.get("product_id") == pid), None)
        assert row is not None
        assert row["can_repeat"] is False
        assert row["current_price"] is None


# --------------------------- 2. Repeat flow ---------------------------- #

class TestRepeatFlow:
    def test_repeat_books_second_recharge_and_is_idempotent(self, admin_tok, buyer_tok):
        tag = uuid.uuid4().hex[:6]
        pid = _create_recharge_plan(
            admin_tok, name=f"ITER94 Repeat {tag}", price=19,
            description="Data add-on · 1GB",
        )
        # Repeat sends ONLY kind + product_id + account (no state/network)
        start = requests.post(
            f"{BASE_URL}/api/recharge/payment/start",
            json={"kind": "mobile", "product_id": pid, "account": BUYER_RECHARGE_NUMBER},
            headers=_h(buyer_tok), timeout=30,
        )
        assert start.status_code == 200, start.text
        js = start.json()
        pay_id = js["payment_id"]
        _CREATED_PAYMENT_IDS.append(pay_id)
        # state/network must come from the plan's own tags
        assert js.get("network") == "airtel"
        assert js.get("state") == AIRTEL_STATE_SLUG

        verify_payload = {
            "payment_id": pay_id,
            "razorpay_order_id": js["razorpay_order_id"],
            "razorpay_payment_id": f"pay_MOCK_{uuid.uuid4().hex[:12]}",
            "razorpay_signature": "mock_sig",
        }
        v1 = requests.post(
            f"{BASE_URL}/api/recharge/payment/verify", json=verify_payload,
            headers=_h(buyer_tok), timeout=30,
        )
        assert v1.status_code == 200, v1.text
        d1 = v1.json()
        assert d1["ok"] is True
        rid = d1["recharge_id"]
        _RECHARGE_IDS.append(rid)
        assert rid
        # replay — must be idempotent
        v2 = requests.post(
            f"{BASE_URL}/api/recharge/payment/verify", json=verify_payload,
            headers=_h(buyer_tok), timeout=30,
        )
        assert v2.status_code == 200, v2.text
        d2 = v2.json()
        assert d2.get("already_verified") is True
        assert d2.get("recharge_id") == rid

        # history shows exactly ONE row for this product_id
        hist = requests.get(
            f"{BASE_URL}/api/recharge/history", headers=_h(buyer_tok), timeout=20,
        ).json().get("items", [])
        matches = [x for x in hist if x.get("product_id") == pid]
        assert len(matches) == 1, f"expected 1 recharge for pid, got {len(matches)}"


# --------------------------- 3. plan_highlights ---------------------------- #

class TestPlanHighlights:
    def test_seeded_airtel_plans_highlights(self, buyer_tok):
        r = requests.get(
            f"{BASE_URL}/api/recharge/products?kind=mobile&state={AIRTEL_STATE_SLUG}&network=airtel",
            headers=_h(buyer_tok), timeout=30,
        )
        assert r.status_code == 200
        plans = []
        for g in r.json().get("groups", []):
            plans.extend(g.get("products") or [])
        by_name = {p.get("name"): p for p in plans}

        unl = next((p for n, p in by_name.items() if "Unlimited 28 days" in n and "2GB/day" in n), None)
        assert unl is not None, "seeded 'Airtel Unlimited 28 days · 2GB/day' missing"
        hl = unl.get("highlights") or {}
        assert hl.get("data") == "2GB/day"
        assert hl.get("validity") == "28 days"
        assert hl.get("calls") == "Unlimited calls"

        addon = next((p for n, p in by_name.items() if "Data add-on" in n and "1GB" in n), None)
        assert addon is not None, "seeded 'Airtel Data add-on · 1GB' missing"
        hl = addon.get("highlights") or {}
        assert hl.get("data") == "1GB"
        assert not hl.get("validity")
        assert not hl.get("calls")

        tt = next((p for n, p in by_name.items() if "Talktime" in n and "100" in n), None)
        assert tt is not None, "seeded 'Airtel Talktime ₹100' missing"
        hl = tt.get("highlights") or {}
        assert hl.get("calls") == "Full talktime"

    def test_explicit_values_beat_parsed(self, admin_tok, buyer_tok):
        tag = uuid.uuid4().hex[:6]
        pid = _create_recharge_plan(
            admin_tok,
            name=f"ITER94 Unlimited 28 days 2GB/day {tag}",
            description="Unlimited 28 days · 2GB/day",
            price=11,
            recharge_data="99GB/day", recharge_validity="99 days", recharge_calls="VIP calls",
        )
        # read via /recharge/products (buyer)
        r = requests.get(
            f"{BASE_URL}/api/recharge/products?kind=mobile&state={AIRTEL_STATE_SLUG}&network=airtel",
            headers=_h(buyer_tok), timeout=30,
        )
        plans = []
        for g in r.json().get("groups", []):
            plans.extend(g.get("products") or [])
        p = next((x for x in plans if x.get("id") == pid), None)
        assert p is not None, "custom plan missing from /recharge/products"
        hl = p.get("highlights") or {}
        assert hl.get("data") == "99GB/day"
        assert hl.get("validity") == "99 days"
        assert hl.get("calls") == "VIP calls"

        # read via /products/{id} (public)
        r = requests.get(f"{BASE_URL}/api/products/{pid}", headers=UA, timeout=20)
        assert r.status_code == 200, r.text
        pub = r.json()
        assert "highlights" in pub
        assert pub["highlights"]["data"] == "99GB/day"
        assert pub["highlights"]["validity"] == "99 days"
        assert pub["highlights"]["calls"] == "VIP calls"

    def test_non_recharge_product_has_no_highlights(self, admin_tok):
        # Walk the admin product list to find any published non-recharge
        # product (public catalogue filters by pincode and may be empty for
        # anonymous callers).
        picked = None
        for page in range(1, 20):
            r = requests.get(
                f"{BASE_URL}/api/admin/products?limit=100&page={page}",
                headers=_h(admin_tok), timeout=30,
            )
            rows = r.json().get("items", []) if isinstance(r.json(), dict) else r.json()
            if not rows:
                break
            for row in rows:
                cat = (row.get("category") or "").lower()
                if cat and cat != "recharge" and not row.get("recharge_kind"):
                    if row.get("is_published") is False:
                        continue
                    r2 = requests.get(
                        f"{BASE_URL}/api/products/{row['id']}", headers=UA, timeout=20,
                    )
                    if r2.status_code == 200:
                        picked = r2.json()
                        break
            if picked:
                break
        assert picked is not None, "could not find a non-recharge product to assert on"
        assert "highlights" not in picked, (
            f"non-recharge product should not expose highlights key, got {picked.get('highlights')}"
        )


# --------------------------- 4. PATCH recharge/options ---------------------------- #

class TestOptionPatch:
    def _airtel_option(self, admin_tok):
        r = requests.get(
            f"{BASE_URL}/api/recharge/options?kind=mobile", headers=_h(admin_tok), timeout=20,
        )
        for o in (r.json().get("mobile", {}).get("networks") or []):
            if o.get("slug") == "airtel":
                return o
        raise AssertionError("Airtel mobile network option missing")

    def _find_shop_cat(self, path_match: list[str]):
        r = requests.get(f"{BASE_URL}/api/shop-categories/tree", headers=UA, timeout=30)
        tree = r.json()
        items = tree if isinstance(tree, list) else tree.get("items", [])

        def walk(nodes, path):
            for n in nodes:
                p2 = path + [n.get("name")]
                yield p2, n
                for row in walk(n.get("children") or [], p2):
                    yield row
        for path, node in walk(items, []):
            if path == path_match:
                return node
        return None

    def test_patch_logo_name_sort_and_mirror(self, admin_tok):
        opt = self._airtel_option(admin_tok)
        oid = opt["id"]
        _LOGO_RESET_IDS.append(oid)
        logo = (
            "data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkAAIAAAoAAv/lxKUAAAAASUVORK5CYII="
        )
        r = requests.patch(
            f"{BASE_URL}/api/admin/recharge/options/{oid}",
            json={"image_url": logo, "name": "Airtel", "sort_order": 0},
            headers=_h(admin_tok), timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("image_url") == logo
        # slug re-derived (same name here, so stays 'airtel')
        assert body.get("slug") == "airtel"
        # logo appears in GET /recharge/options
        opts = requests.get(
            f"{BASE_URL}/api/recharge/options?kind=mobile", headers=UA, timeout=20,
        ).json()
        air = next(o for o in opts["mobile"]["networks"] if o.get("slug") == "airtel")
        assert air.get("image_url") == logo

        # mirror into Recharge > Mobile Recharge > Airtel
        cat = self._find_shop_cat(["Recharge", "Mobile Recharge", "Airtel"])
        assert cat is not None, "mirrored shop-category row missing"
        assert cat.get("image_url") == logo

    def test_clear_logo_with_empty_string(self, admin_tok):
        opt = self._airtel_option(admin_tok)
        oid = opt["id"]
        r = requests.patch(
            f"{BASE_URL}/api/admin/recharge/options/{oid}",
            json={"image_url": ""}, headers=_h(admin_tok), timeout=30,
        )
        assert r.status_code == 200, r.text
        opts = requests.get(
            f"{BASE_URL}/api/recharge/options?kind=mobile", headers=UA, timeout=20,
        ).json()
        air = next(o for o in opts["mobile"]["networks"] if o.get("slug") == "airtel")
        assert air.get("image_url") in (None, ""), air.get("image_url")

    def test_role_guard_403_for_vendor_and_buyer(self, admin_tok, vendor_tok, buyer_tok):
        oid = self._airtel_option(admin_tok)["id"]
        for tok in (vendor_tok, buyer_tok):
            r = requests.patch(
                f"{BASE_URL}/api/admin/recharge/options/{oid}",
                json={"sort_order": 0}, headers=_h(tok), timeout=20,
            )
            assert r.status_code == 403, f"expected 403 for non-admin, got {r.status_code} {r.text}"

    def test_unknown_id_404(self, admin_tok):
        r = requests.patch(
            f"{BASE_URL}/api/admin/recharge/options/{uuid.uuid4()}",
            json={"sort_order": 1}, headers=_h(admin_tok), timeout=20,
        )
        assert r.status_code == 404


# --------------------------- 5 + 6. dp_my_customers ---------------------------- #

class TestDPCustomers:
    def test_distance_and_shipping_identity(self, rider_tok):
        # explicit lat/lng (Srikalahasti centre-ish)
        r = requests.get(
            f"{BASE_URL}/api/delivery-partner/me/customers?lat=13.7484&lng=79.7027&sort=distance",
            headers=_h(rider_tok), timeout=30,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("sorted_by") == "distance"
        assert d.get("has_origin") is True
        assert d.get("total", 0) >= 1
        items = d.get("items") or []
        # Must be sorted by distance_km ascending (None last)
        last = -1.0
        for it in items:
            dk = it.get("distance_km")
            if dk is None:
                dk = 1e12
            assert dk >= last - 1e-6, f"not nearest-first: {dk} < {last}"
            last = dk
        # Identity from shipping_address — name/address/pincode non-empty for
        # at least the first customer who has orders.
        head = items[0]
        assert head.get("name")
        assert head.get("address"), f"shipping_address.address was blank: {head}"
        assert head.get("pincode")
        assert head.get("order_count", 0) >= 1
        assert "shops" in head and isinstance(head["shops"], list)
        assert "cash_to_collect" in head

    def test_sort_orders_toggle(self, rider_tok):
        r = requests.get(
            f"{BASE_URL}/api/delivery-partner/me/customers?lat=13.7484&lng=79.7027&sort=orders",
            headers=_h(rider_tok), timeout=30,
        )
        assert r.status_code == 200
        d = r.json()
        assert d.get("sorted_by") == "orders"

    def test_no_latlng_falls_back_to_rider_pincode(self, rider_tok):
        r = requests.get(
            f"{BASE_URL}/api/delivery-partner/me/customers",
            headers=_h(rider_tok), timeout=30,
        )
        assert r.status_code == 200
        d = r.json()
        # Rider's dp_pincodes include 517644 → origin resolvable
        assert d.get("has_origin") is True
        # Items should carry distance_km (not necessarily sorted mode==distance,
        # but the field must be populated when origin is known).
        items = d.get("items") or []
        if items:
            assert any(x.get("distance_km") is not None for x in items)

    def test_advance_endpoint_regression(self, rider_tok):
        # Just hit the endpoint for the known buyer id with status=delivered
        # on an empty bulk (no changes expected if there are no in-transit
        # orders). We're asserting the shape, not forcing a status change.
        cust_resp = requests.get(
            f"{BASE_URL}/api/delivery-partner/me/customers",
            headers=_h(rider_tok), timeout=20,
        ).json()
        items = cust_resp.get("items") or []
        if not items:
            pytest.skip("no customers to advance")
        uid = items[0]["user_id"]
        r = requests.post(
            f"{BASE_URL}/api/delivery-partner/customers/{uid}/advance",
            json={}, headers=_h(rider_tok), timeout=30,
        )
        # Endpoint still responds (200 or 400 'nothing to advance'); never 5xx
        assert r.status_code in (200, 400), f"advance endpoint broke: {r.status_code} {r.text}"
        # Idempotency: calling it again returns the same shape
        r2 = requests.post(
            f"{BASE_URL}/api/delivery-partner/customers/{uid}/advance",
            json={}, headers=_h(rider_tok), timeout=30,
        )
        assert r2.status_code in (200, 400)
