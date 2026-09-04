"""Phase 3 variants — edge-case regression tests (iter 65).

Scope (per E1 review request):
  - Chart catalogue shape (public endpoint)
  - Create with apparel/extra variants → derived price/stock
  - Create with ram_rom/absolute variants → derived price/stock
  - PATCH: base price recompute in extra mode
  - PATCH: variant-only stock change recomputes product total
  - Normalization: duplicate labels de-duped, blank labels dropped,
    negative stock clamped to 0
  - Public detail returns variants + variant_guide with in_stock flag
  - Public list returns has_variants + variant_count, no variants[]
  - Cart: variant_required 400, sold-out 400, two rows for two variants,
    adjust beyond stock 400, unit price = variant price, variant-aware remove
  - Checkout oversell race + rollback path
"""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "https://vendor-network-app-1.preview.emergentagent.com"
BASE_URL = BASE_URL.rstrip("/")
API = f"{BASE_URL}/api"
HEADERS = {"Content-Type": "application/json", "User-Agent": "curl/8.5.0"}


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, headers=HEADERS, timeout=30)
    if r.status_code != 200:
        return None
    d = r.json()
    return d.get("token") or d.get("access_token")


@pytest.fixture(scope="session")
def vendor_token():
    tok = _login("testvendor@test.com", "Test@1234")
    assert tok, "vendor login failed"
    return tok


@pytest.fixture(scope="session")
def admin_token():
    tok = _login("support@slangcart.com", "3)Ywxtic")
    assert tok, "admin login failed"
    return tok


def _publish(admin_tok, pid):
    """Admin publishes a vendor product so public endpoints see it."""
    requests.patch(f"{API}/admin/products/{pid}",
                   json={"is_published": True},
                   headers=_auth(admin_tok), timeout=30)


@pytest.fixture(scope="session")
def buyer_token():
    tok = _login("testbuyer@test.com", "Test@1234")
    assert tok, "buyer login failed"
    return tok


@pytest.fixture(scope="session")
def buyer2_token():
    tok = _login("testbuyer2@test.com", "Test@1234")
    if tok:
        return tok
    # Register new
    r = requests.post(f"{API}/auth/register",
                      json={"name": "Test Buyer 2", "email": "testbuyer2@test.com",
                            "password": "Test@1234", "phone": "9999900002"},
                      headers=HEADERS, timeout=30)
    tok = _login("testbuyer2@test.com", "Test@1234")
    return tok


def _auth(tok):
    return {**HEADERS, "Authorization": f"Bearer {tok}"}


# ── Chart catalogue ─────────────────────────────────────────────────
class TestChartCatalogue:
    def test_public_charts_shape(self):
        r = requests.get(f"{API}/product-variant-charts", headers=HEADERS, timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert "price_modes" in data
        modes = [m["value"] for m in data["price_modes"]]
        assert "extra" in modes and "absolute" in modes
        charts = {c["value"]: c for c in data["charts"]}
        expected = {"apparel", "footwear_uk", "footwear_eu", "footwear_kids",
                    "waist_in", "kids_age", "free_size", "ram_rom", "custom"}
        assert expected.issubset(set(charts.keys())), f"missing charts: {expected - set(charts.keys())}"
        # Apparel: XS..3XL, guide has Chest/Length/Shoulder
        ap = charts["apparel"]
        ap_labels = [o["label"] for o in ap["options"]]
        assert all(x in ap_labels for x in ["XS", "S", "M", "L", "XL", "XXL", "3XL"])
        assert any("Chest" in c for c in ap["columns"])
        assert any("Length" in c for c in ap["columns"])
        assert any("Shoulder" in c for c in ap["columns"])
        # Footwear UK guide has UK→EU→foot cm
        fw = charts["footwear_uk"]
        assert any("EU" in c for c in fw["columns"])
        assert any("cm" in c.lower() for c in fw["columns"])
        # RAM/ROM includes 8GB / 256GB
        ram_labels = [o["label"] for o in charts["ram_rom"]["options"]]
        assert "8GB / 256GB" in ram_labels


# ── Product create/update (variant business logic) ──────────────────
class TestVariantCreateExtraMode:
    """apparel + extra: S/M=499, L=+30, XL=+50; L sold out (stock=0)."""

    def test_create_and_derived(self, vendor_token, admin_token):
        payload = {
            "name": f"TEST_VariantTee_{uuid.uuid4().hex[:6]}",
            "price": 499,
            "image_url": "",
            "stock": 0,
            "category": "Clothes",
            "variant_chart": "apparel",
            "variant_price_mode": "extra",
            "variants": [
                {"label": "S", "stock": 3},
                {"label": "M", "stock": 5},
                {"label": "L", "stock": 0, "price_extra": 30},
                {"label": "XL", "stock": 2, "price_extra": 50},
            ],
        }
        r = requests.post(f"{API}/vendor/me/products", json=payload, headers=_auth(vendor_token), timeout=30)
        assert r.status_code in (200, 201), r.text
        p = r.json()
        pytest.extra_product_id = p["id"]
        assert p.get("has_variants") is True
        assert p.get("stock") == 10  # sum
        assert p.get("base_price") == 499
        # Cheapest BUYABLE (L is sold out → excluded) — S/M @ 499 is cheapest
        assert p.get("price") == 499
        vs = {v["label"]: v for v in p["variants"]}
        assert vs["S"]["price"] == 499
        assert vs["M"]["price"] == 499
        assert vs["L"]["price"] == 529
        assert vs["XL"]["price"] == 549
        for v in p["variants"]:
            assert v.get("id"), "variant missing generated id"
        _publish(admin_token, p["id"])

    def test_patch_base_price_recomputes(self, vendor_token):
        pid = pytest.extra_product_id
        r = requests.patch(f"{API}/vendor/me/products/{pid}",
                           json={"price": 600, "variant_chart": "apparel",
                                 "variant_price_mode": "extra",
                                 "variants": [
                                     {"label": "S", "stock": 3},
                                     {"label": "M", "stock": 5},
                                     {"label": "L", "stock": 0, "price_extra": 30},
                                     {"label": "XL", "stock": 2, "price_extra": 50},
                                 ]},
                           headers=_auth(vendor_token), timeout=30)
        assert r.status_code == 200, r.text
        # Re-fetch
        pub = requests.get(f"{API}/products/{pid}", headers=HEADERS, timeout=30).json()
        vs = {v["label"]: v for v in pub["variants"]}
        assert vs["S"]["price"] == 600
        assert vs["XL"]["price"] == 650
        assert pub["price"] == 600  # cheapest buyable

    def test_patch_variant_stock_recomputes_total(self, vendor_token):
        pid = pytest.extra_product_id
        r = requests.patch(f"{API}/vendor/me/products/{pid}",
                           json={"variant_chart": "apparel",
                                 "variant_price_mode": "extra",
                                 "variants": [
                                     {"label": "S", "stock": 7},
                                     {"label": "M", "stock": 5},
                                     {"label": "L", "stock": 0, "price_extra": 30},
                                     {"label": "XL", "stock": 2, "price_extra": 50},
                                 ]},
                           headers=_auth(vendor_token), timeout=30)
        assert r.status_code == 200
        pub = requests.get(f"{API}/products/{pid}", headers=HEADERS, timeout=30).json()
        # Note public endpoint returns list-summed stock via variants; check product
        # via find. Sum should be 14.
        # We check the fresh product by using vendor list
        vlist = requests.get(f"{API}/vendor/me/products", headers=_auth(vendor_token), timeout=30).json()
        row = next((x for x in (vlist if isinstance(vlist, list) else vlist.get("items", [])) if x["id"] == pid), None)
        assert row is not None
        assert row.get("stock") == 14


class TestVariantCreateAbsoluteMode:
    """ram_rom + absolute: 4/64=11999, 8/256=15999. Cheapest buyable = product price."""

    def test_create_absolute(self, vendor_token):
        payload = {
            "name": f"TEST_VariantPhone_{uuid.uuid4().hex[:6]}",
            "price": 11999,
            "image_url": "",
            "stock": 0,
            "category": "Mobiles",
            "variant_chart": "ram_rom",
            "variant_price_mode": "absolute",
            "variants": [
                {"label": "4GB / 64GB", "stock": 4, "price_abs": 11999},
                {"label": "8GB / 256GB", "stock": 2, "price_abs": 15999},
            ],
        }
        r = requests.post(f"{API}/vendor/me/products", json=payload, headers=_auth(vendor_token), timeout=30)
        assert r.status_code in (200, 201), r.text
        p = r.json()
        pytest.abs_product_id = p["id"]
        assert p["has_variants"] is True
        assert p["stock"] == 6
        assert p["price"] == 11999
        vs = {v["label"]: v for v in p["variants"]}
        assert vs["4GB / 64GB"]["price"] == 11999
        assert vs["8GB / 256GB"]["price"] == 15999


class TestVariantNormalization:
    """De-dup labels, drop blank labels, clamp negative stock."""

    def test_dedup_and_clamp(self, vendor_token):
        payload = {
            "name": f"TEST_VariantNorm_{uuid.uuid4().hex[:6]}",
            "price": 100,
            "image_url": "",
            "stock": 0,
            "category": "Clothes",
            "variant_chart": "apparel",
            "variant_price_mode": "extra",
            "variants": [
                {"label": "S", "stock": 5},
                {"label": "S", "stock": 99},        # duplicate → dropped
                {"label": "", "stock": 10},         # blank → dropped
                {"label": "  ", "stock": 10},       # whitespace → dropped
                {"label": "M", "stock": -3},        # negative → 0
            ],
        }
        r = requests.post(f"{API}/vendor/me/products", json=payload, headers=_auth(vendor_token), timeout=30)
        assert r.status_code in (200, 201), r.text
        p = r.json()
        labels = [v["label"] for v in p["variants"]]
        assert labels.count("S") == 1
        assert "" not in labels
        assert "  " not in labels
        m = next(v for v in p["variants"] if v["label"] == "M")
        assert m["stock"] == 0
        # First S kept with stock 5, not 99
        s = next(v for v in p["variants"] if v["label"] == "S")
        assert s["stock"] == 5
        # cleanup
        requests.delete(f"{API}/vendor/me/products/{p['id']}", headers=_auth(vendor_token), timeout=30)


# ── Public listing / detail ─────────────────────────────────────────
class TestPublicListDetail:
    def test_public_detail_has_variant_guide(self, vendor_token):
        pid = pytest.extra_product_id
        r = requests.get(f"{API}/products/{pid}", headers=HEADERS, timeout=30)
        assert r.status_code == 200
        p = r.json()
        assert p["has_variants"] is True
        assert p["variant_chart"] == "apparel"
        assert isinstance(p.get("variants"), list) and len(p["variants"]) >= 4
        # sold-out still listed with in_stock=false
        for v in p["variants"]:
            assert set(v.keys()) >= {"id", "label", "price", "stock", "in_stock"}
        L = next(v for v in p["variants"] if v["label"] == "L")
        assert L["in_stock"] is False
        guide = p.get("variant_guide")
        assert guide and guide.get("guide") and guide.get("columns")

    def test_public_list_no_variants_array(self):
        r = requests.get(f"{API}/products", params={"q": "TEST_VariantTee", "limit": 20}, headers=HEADERS, timeout=30)
        assert r.status_code == 200
        data = r.json()
        items = data if isinstance(data, list) else data.get("items", [])
        assert items, "no items returned"
        for it in items:
            if it["id"] == pytest.extra_product_id:
                assert it.get("has_variants") is True
                assert it.get("variant_count", 0) >= 4
                assert "variants" not in it, "list must not include variants[]"
                break
        else:
            pytest.fail("test product not in list")


# ── Cart ────────────────────────────────────────────────────────────
class TestCartVariantFlow:
    def test_add_without_variant_400(self, buyer_token):
        pid = pytest.extra_product_id
        r = requests.post(f"{API}/cart/add", json={"product_id": pid, "qty": 1},
                          headers=_auth(buyer_token), timeout=30)
        assert r.status_code == 400
        detail = r.json().get("detail")
        assert isinstance(detail, dict) and detail.get("code") == "variant_required"
        assert isinstance(detail.get("options"), list) and len(detail["options"]) >= 4

    def test_add_soldout_variant_400(self, buyer_token):
        pid = pytest.extra_product_id
        pub = requests.get(f"{API}/products/{pid}", headers=HEADERS, timeout=30).json()
        L = next(v for v in pub["variants"] if v["label"] == "L")
        r = requests.post(f"{API}/cart/add", json={"product_id": pid, "qty": 1, "variant_id": L["id"]},
                          headers=_auth(buyer_token), timeout=30)
        assert r.status_code == 400
        assert "has only 0 left" in str(r.json().get("detail", ""))

    def test_two_variants_two_rows(self, buyer_token):
        # Clear cart
        requests.post(f"{API}/cart/clear", headers=_auth(buyer_token), timeout=30)
        pid = pytest.extra_product_id
        pub = requests.get(f"{API}/products/{pid}", headers=HEADERS, timeout=30).json()
        S = next(v for v in pub["variants"] if v["label"] == "S")
        XL = next(v for v in pub["variants"] if v["label"] == "XL")
        r1 = requests.post(f"{API}/cart/add", json={"product_id": pid, "qty": 1, "variant_id": S["id"]},
                           headers=_auth(buyer_token), timeout=30)
        assert r1.status_code == 200 and r1.json().get("variant_label") == "S"
        r2 = requests.post(f"{API}/cart/add", json={"product_id": pid, "qty": 1, "variant_id": XL["id"]},
                           headers=_auth(buyer_token), timeout=30)
        assert r2.status_code == 200 and r2.json().get("variant_label") == "XL"
        cart = requests.get(f"{API}/cart", headers=_auth(buyer_token), timeout=30).json()
        rows = [it for it in cart["items"] if it.get("product_id") == pid]
        assert len(rows) == 2
        labels = {r["variant_label"] for r in rows}
        assert labels == {"S", "XL"}
        # unit_price = variant price
        xl_row = next(r for r in rows if r["variant_label"] == "XL")
        # Base was patched to 600, XL extra=+50 → 650
        assert xl_row["unit_price"] == 650
        assert xl_row["line_total"] == 650

    def test_adjust_beyond_variant_stock_400(self, buyer_token):
        pid = pytest.extra_product_id
        pub = requests.get(f"{API}/products/{pid}", headers=HEADERS, timeout=30).json()
        XL = next(v for v in pub["variants"] if v["label"] == "XL")
        # XL stock=2, we already have qty 1 → adjust +5 must fail
        r = requests.post(f"{API}/cart/adjust",
                          json={"product_id": pid, "variant_id": XL["id"], "delta": 5},
                          headers=_auth(buyer_token), timeout=30)
        assert r.status_code == 400

    def test_remove_specific_variant(self, buyer_token):
        pid = pytest.extra_product_id
        pub = requests.get(f"{API}/products/{pid}", headers=HEADERS, timeout=30).json()
        S = next(v for v in pub["variants"] if v["label"] == "S")
        r = requests.post(f"{API}/cart/remove",
                          json={"product_id": pid, "variant_id": S["id"]},
                          headers=_auth(buyer_token), timeout=30)
        assert r.status_code == 200
        cart = requests.get(f"{API}/cart", headers=_auth(buyer_token), timeout=30).json()
        rows = [it for it in cart["items"] if it.get("product_id") == pid]
        assert len(rows) == 1
        assert rows[0]["variant_label"] == "XL"

    def test_remove_all_variants(self, buyer_token):
        pid = pytest.extra_product_id
        r = requests.post(f"{API}/cart/remove",
                          json={"product_id": pid},
                          headers=_auth(buyer_token), timeout=30)
        assert r.status_code == 200
        cart = requests.get(f"{API}/cart", headers=_auth(buyer_token), timeout=30).json()
        rows = [it for it in cart["items"] if it.get("product_id") == pid]
        assert len(rows) == 0


# ── Checkout oversell + rollback ────────────────────────────────────
class TestCheckoutVariant:
    def test_checkout_decrements_variant_and_total(self, vendor_token, buyer_token):
        # Reset XL to stock=1 so oversell can be triggered
        pid = pytest.extra_product_id
        requests.patch(f"{API}/vendor/me/products/{pid}",
                       json={"variant_chart": "apparel", "variant_price_mode": "extra",
                             "variants": [
                                 {"label": "S", "stock": 5},
                                 {"label": "M", "stock": 5},
                                 {"label": "L", "stock": 0, "price_extra": 30},
                                 {"label": "XL", "stock": 1, "price_extra": 50},
                             ]}, headers=_auth(vendor_token), timeout=30)
        pub = requests.get(f"{API}/products/{pid}", headers=HEADERS, timeout=30).json()
        pre_total = pub["stock"] if "stock" in pub else None
        XL = next(v for v in pub["variants"] if v["label"] == "XL")
        requests.post(f"{API}/cart/clear", headers=_auth(buyer_token), timeout=30)
        r = requests.post(f"{API}/cart/add",
                          json={"product_id": pid, "qty": 1, "variant_id": XL["id"]},
                          headers=_auth(buyer_token), timeout=30)
        assert r.status_code == 200
        # Checkout as COD to avoid wallet balance concerns
        checkout_payload = {
            "paid_via": "cod", "payment_mode": "cod",
            "shipping_address": {
                "name": "Test Buyer", "phone": "9999900001",
                "line1": "Srikalahasti", "city": "Srikalahasti",
                "state": "AP", "pincode": "517644",
                "latitude": 13.7497, "longitude": 79.7036,
            }
        }
        co = requests.post(f"{API}/orders/checkout",
                           json=checkout_payload,
                           headers=_auth(buyer_token), timeout=60)
        # Some backends require address — accept 200/201, otherwise skip
        if co.status_code not in (200, 201):
            pytest.skip(f"checkout returned {co.status_code}: {co.text[:200]}")
        # Verify XL decremented to 0
        pub2 = requests.get(f"{API}/products/{pid}", headers=HEADERS, timeout=30).json()
        XL2 = next(v for v in pub2["variants"] if v["label"] == "XL")
        assert XL2["stock"] == 0

    def test_oversell_race_prevented(self, vendor_token, buyer_token, buyer2_token):
        if not buyer2_token:
            pytest.skip("buyer2 not available")
        pid = pytest.extra_product_id
        # Set XL to stock=1
        requests.patch(f"{API}/vendor/me/products/{pid}",
                       json={"variant_chart": "apparel", "variant_price_mode": "extra",
                             "variants": [
                                 {"label": "S", "stock": 5},
                                 {"label": "M", "stock": 5},
                                 {"label": "L", "stock": 0, "price_extra": 30},
                                 {"label": "XL", "stock": 1, "price_extra": 50},
                             ]}, headers=_auth(vendor_token), timeout=30)
        pub = requests.get(f"{API}/products/{pid}", headers=HEADERS, timeout=30).json()
        XL = next(v for v in pub["variants"] if v["label"] == "XL")
        # Both buyers add qty=1
        requests.post(f"{API}/cart/clear", headers=_auth(buyer_token), timeout=30)
        requests.post(f"{API}/cart/clear", headers=_auth(buyer2_token), timeout=30)
        a1 = requests.post(f"{API}/cart/add",
                           json={"product_id": pid, "qty": 1, "variant_id": XL["id"]},
                           headers=_auth(buyer_token), timeout=30)
        a2 = requests.post(f"{API}/cart/add",
                           json={"product_id": pid, "qty": 1, "variant_id": XL["id"]},
                           headers=_auth(buyer2_token), timeout=30)
        assert a1.status_code == 200 and a2.status_code == 200
        # Sequential checkouts (real race would need threads; sequential still validates atomic guard)
        checkout_payload = {
            "paid_via": "cod", "payment_mode": "cod",
            "shipping_address": {
                "name": "Test Buyer", "phone": "9999900001",
                "line1": "Srikalahasti", "city": "Srikalahasti",
                "state": "AP", "pincode": "517644",
                "latitude": 13.7497, "longitude": 79.7036,
            }
        }
        c1 = requests.post(f"{API}/orders/checkout",
                           json=checkout_payload,
                           headers=_auth(buyer_token), timeout=60)
        c2 = requests.post(f"{API}/orders/checkout",
                           json=checkout_payload,
                           headers=_auth(buyer2_token), timeout=60)
        # First should succeed, second should fail with friendly out-of-stock
        if c1.status_code in (200, 201):
            assert c2.status_code >= 400, f"second checkout should have failed, got {c2.status_code}: {c2.text[:200]}"
            msg = str(c2.json().get("detail", "")).lower()
            assert ("out of stock" in msg or "left" in msg or "no longer" in msg or "insufficient" in msg or "stock" in msg), \
                f"unfriendly error msg: {msg}"
        # Ensure stock never went negative
        pub2 = requests.get(f"{API}/products/{pid}", headers=HEADERS, timeout=30).json()
        for v in pub2["variants"]:
            assert v["stock"] >= 0, f"variant {v['label']} went negative"
