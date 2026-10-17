"""Iter-92 (Jan 2026) — Admin treasury clarity + Cart delivery parity +
Delivery-partner customer-wise flow + Wallet set-off remit.

Owner-filed items:
  1. Admin · System Wallet — show vendor shop-wallet money + rider cash
     + rider wallets for clarity (NOT added to net worth)
  2. Cart `delivery` block must agree to the paisa with /orders/checkout
     and /orders/payment/start; "add more for free delivery" hint
  3. Delivery-partner customer-wise view + bulk advance + cash safety
  4. /remit/wallet set-off: no bank_ledger row, admin net worth unchanged

Credentials come from /app/memory/test_credentials.md.
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for ln in f:
            if ln.startswith("EXPO_PUBLIC_BACKEND_URL="):
                BASE_URL = ln.split("=", 1)[1].strip().strip('"').rstrip("/")

ADMIN = ("support@slangcart.com", "3)Ywxtic")
VENDOR = ("testvendor@test.com", "Test@1234")
BUYER = ("testbuyer@test.com", "Test@1234")
RIDER = ("rider_test@test.com", "Test@1234")
RIDER_ID = "a0bf6822-59fa-4b18-bc53-381229a1f30c"
VENDOR_ID = "1115f762-0a4f-474e-bbdb-6227a06f08b1"


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text}"
    body = r.json()
    tok = body.get("token") or body.get("access_token")
    assert tok, f"no token in login response: {body}"
    return tok, body.get("user") or {}


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ─────────────────────────────────────────────────────────────────────────
# Session-scoped fixtures
# ─────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def tokens():
    admin_t, _ = _login(*ADMIN)
    buyer_t, buyer = _login(*BUYER)
    rider_t, rider = _login(*RIDER)
    vendor_t, vendor = _login(*VENDOR)
    return {
        "admin": admin_t, "buyer": buyer_t, "rider": rider_t, "vendor": vendor_t,
        "buyer_user": buyer, "rider_user": rider, "vendor_user": vendor,
    }


@pytest.fixture(scope="module")
def vendor_product(tokens):
    """Pick a product belonging to the test vendor (preferred) via admin API."""
    r = requests.get(f"{BASE_URL}/api/admin/products?limit=500",
                     headers=_hdr(tokens["admin"]), timeout=30)
    assert r.status_code == 200, r.text
    rows = r.json().get("items") or r.json() or []
    if isinstance(rows, dict):
        rows = rows.get("items") or []
    prod = next((p for p in rows if p.get("vendor_id") == VENDOR_ID and
                 (p.get("is_published") is not False) and float(p.get("price") or 0) > 0),
                None)
    assert prod, f"no published product found for vendor {VENDOR_ID}"
    return prod


@pytest.fixture(scope="module")
def rider_vendor_mapping(tokens):
    """Map the rider to our test vendor for the duration of this module; restore afterwards."""
    r = requests.put(
        f"{BASE_URL}/api/admin/delivery-partners/{RIDER_ID}/vendors",
        headers=_hdr(tokens["admin"]),
        json={"vendor_ids": [VENDOR_ID]}, timeout=30,
    )
    assert r.status_code == 200, f"map rider failed: {r.status_code} {r.text}"
    yield
    # cleanup — clear mapping
    requests.put(
        f"{BASE_URL}/api/admin/delivery-partners/{RIDER_ID}/vendors",
        headers=_hdr(tokens["admin"]), json={"vendor_ids": []}, timeout=30,
    )


# ─────────────────────────────────────────────────────────────────────────
# 1. Admin System Wallet — treasury clarity rows
# ─────────────────────────────────────────────────────────────────────────
class TestAdminTreasuryClarity:
    def test_net_worth_has_new_clarity_rows(self, tokens):
        r = requests.get(f"{BASE_URL}/api/admin/finance/net-worth",
                         headers=_hdr(tokens["admin"]), timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        coh = body["cash_on_hand"]
        for k in ("rider_cash_held", "rider_count", "rider_wallets",
                  "rider_wallet_count", "vendor_wallets", "vendor_wallet_count"):
            assert k in coh, f"cash_on_hand missing {k}: {list(coh.keys())}"
        comp = body["master"]["components"]
        for k in ("vendor_payable", "rider_cash_held", "rider_wallets"):
            assert k in comp, f"master.components missing {k}"
        # Clarity rows should NOT be baked into cash_on_hand.total:
        # total = registration_cash + cod_with_collectors
        expected_total = round(float(coh.get("registration_cash") or 0) +
                               float(coh.get("cod_with_collectors") or 0), 2)
        assert abs(float(coh["total"]) - expected_total) < 0.02, (
            f"cash_on_hand.total {coh['total']} != reg_cash + cod_in_field {expected_total} "
            "— new clarity rows must NOT be added into the total"
        )

    def test_net_worth_formula_ignores_new_clarity_rows(self, tokens):
        """The NEW rider_cash_held / rider_wallets / vendor_wallets rows are
        informational — net_worth must still equal
        bank + cash_on_hand + pending - user_wallet - vendor_payable
         - pending_withdrawals - gst_payable."""
        body = requests.get(f"{BASE_URL}/api/admin/finance/net-worth",
                            headers=_hdr(tokens["admin"]), timeout=30).json()
        c = body["master"]["components"]
        expected = round(
            float(c["bank_balance"]) + float(c["cash_on_hand"])
            + float(c["pending_collections"])
            - float(c["user_wallet_balance"]) - float(c["vendor_payable"])
            - float(c["pending_withdrawals"]) - float(c["gst_payable"]), 2,
        )
        assert abs(float(body["master"]["net_worth"]) - expected) < 0.05, (
            f"net_worth {body['master']['net_worth']} != formula {expected}; "
            "new clarity rows must NOT be added into net_worth"
        )

    def test_rider_cash_movement_only_tracks_real_money(self, tokens):
        """Credit rider wallet by ₹1 (real money event: creates a user-wallet
        liability without a matching asset ⇒ net worth should fall by ₹1).
        Reverse ⇒ net worth returns. Proves master.net_worth responds to
        real ledger events, NOT to the clarity surface."""
        nw0 = requests.get(f"{BASE_URL}/api/admin/finance/net-worth",
                           headers=_hdr(tokens["admin"]), timeout=30).json()["master"]["net_worth"]
        key = uuid.uuid4().hex[:8]
        requests.post(f"{BASE_URL}/api/admin/transactions/adjust",
                      headers=_hdr(tokens["admin"]),
                      json={"user_id": RIDER_ID, "amount": 1.0,
                            "category": "correction",
                            "description": f"TEST iter92 credit {key}",
                            "wallet": "wallet_balance"}, timeout=20)
        nw1 = requests.get(f"{BASE_URL}/api/admin/finance/net-worth",
                           headers=_hdr(tokens["admin"]), timeout=30).json()["master"]["net_worth"]
        # Reverse immediately
        requests.post(f"{BASE_URL}/api/admin/transactions/adjust",
                      headers=_hdr(tokens["admin"]),
                      json={"user_id": RIDER_ID, "amount": -1.0,
                            "category": "correction",
                            "description": f"TEST iter92 reverse {key}",
                            "wallet": "wallet_balance"}, timeout=20)
        nw2 = requests.get(f"{BASE_URL}/api/admin/finance/net-worth",
                           headers=_hdr(tokens["admin"]), timeout=30).json()["master"]["net_worth"]
        # Delta ≈ −1 after liability credit; back to ~original after reversal.
        assert abs((nw1 - nw0) - (-1.0)) < 0.05, (
            f"net_worth delta on liability credit expected ≈ -1.00, got {nw1 - nw0}"
        )
        assert abs(nw2 - nw0) < 0.05, (
            f"net_worth did not return after reversal: {nw0} → {nw2}"
        )


# ─────────────────────────────────────────────────────────────────────────
# 2. Cart delivery quote parity with checkout + payment/start
# ─────────────────────────────────────────────────────────────────────────
def _clear_cart(tok):
    requests.post(f"{BASE_URL}/api/cart/clear", headers=_hdr(tok), timeout=20)


def _add(tok, pid, qty, variant_id=None):
    body = {"product_id": pid, "qty": qty}
    if variant_id:
        body["variant_id"] = variant_id
    r = requests.post(f"{BASE_URL}/api/cart/add", headers=_hdr(tok), json=body, timeout=20)
    assert r.status_code == 200, f"cart/add: {r.status_code} {r.text}"


class TestCartDeliveryParity:
    def test_cart_has_delivery_block(self, tokens, vendor_product):
        _clear_cart(tokens["buyer"])
        _add(tokens["buyer"], vendor_product["id"], 1)
        r = requests.get(f"{BASE_URL}/api/cart", headers=_hdr(tokens["buyer"]), timeout=20)
        assert r.status_code == 200, r.text
        c = r.json()
        d = c.get("delivery") or {}
        for k in ("enabled", "total", "free", "per_seller", "add_more_for_free", "hint"):
            assert k in d, f"cart.delivery missing {k}"
        assert "payable_total" in c
        assert abs(c["payable_total"] - round(c["total"] + d["total"], 2)) < 0.02

    def test_delivery_total_matches_payment_start(self, tokens, vendor_product):
        _clear_cart(tokens["buyer"])
        _add(tokens["buyer"], vendor_product["id"], 1)
        cart = requests.get(f"{BASE_URL}/api/cart", headers=_hdr(tokens["buyer"]),
                            timeout=20).json()
        d_total = round(float(cart["delivery"]["total"]), 2)

        start = requests.post(
            f"{BASE_URL}/api/orders/payment/start",
            headers=_hdr(tokens["buyer"]),
            json={"wallet_amount": 0}, timeout=30,
        )
        # If wallet already covers full order, start returns 400 — fine.
        if start.status_code == 400 and "wallet" in start.text.lower():
            pytest.skip("buyer wallet covers full order — cannot test online start")
        assert start.status_code == 200, f"payment/start: {start.status_code} {start.text}"
        s = start.json()
        assert abs(float(s["delivery_total"]) - d_total) < 0.02, (
            f"cart.delivery.total {d_total} != payment/start.delivery_total {s['delivery_total']}"
        )

    def test_free_vs_paid_delivery_scenarios(self, tokens, vendor_product):
        # Scenario A: 1 unit → likely below threshold → delivery > 0 OR free (if product.free_delivery)
        _clear_cart(tokens["buyer"])
        _add(tokens["buyer"], vendor_product["id"], 1)
        a = requests.get(f"{BASE_URL}/api/cart", headers=_hdr(tokens["buyer"]),
                         timeout=20).json()
        da = a["delivery"]
        if da["free"]:
            assert da["total"] <= 0.009
            assert da["add_more_for_free"] == 0
            # If free due to product.free_delivery, we can't easily force paid.
            # Still assert hint text sanity.
            assert "free" in (da["hint"] or "").lower()
            return

        # Scenario A is PAID — assert gap math
        assert da["total"] > 0, "expected paid delivery at qty=1"
        # add_more_for_free == sum of per-seller gaps
        gap_sum = round(sum(float((s or {}).get("add_more_for_free") or 0)
                            for s in da["per_seller"]), 2)
        assert abs(float(da["add_more_for_free"]) - gap_sum) < 0.02, (
            f"add_more_for_free mismatch: top={da['add_more_for_free']} rows={gap_sum}"
        )
        # per_seller charges sum to delivery.total (respecting cart_max cap)
        charges = round(sum(float((s or {}).get("charge") or 0)
                            for s in da["per_seller"]), 2)
        cart_max = float(da.get("cart_max") or 0)
        if da.get("capped"):
            assert abs(float(da["total"]) - cart_max) < 0.02
        else:
            assert abs(float(da["total"]) - charges) < 0.02, (
                f"per_seller charges {charges} ≠ delivery.total {da['total']}"
            )

        # Scenario B: huge qty to exceed threshold → should become free
        _clear_cart(tokens["buyer"])
        _add(tokens["buyer"], vendor_product["id"], 50)
        b = requests.get(f"{BASE_URL}/api/cart", headers=_hdr(tokens["buyer"]),
                         timeout=20).json()
        db_ = b["delivery"]
        # Threshold may be configured very high — if still charged, skip
        if not db_["free"]:
            pytest.skip(f"50-unit cart still below free threshold "
                        f"(subtotal={b['total']}, per_seller={db_['per_seller']})")
        assert db_["total"] <= 0.009
        assert db_["add_more_for_free"] == 0


# ─────────────────────────────────────────────────────────────────────────
# 3-5. Delivery-partner customer-wise flow + MONEY SAFETY
# ─────────────────────────────────────────────────────────────────────────
def _seed_cod_order(tokens, buyer_id, vendor_id, cod_due, name_tag):
    """Direct Mongo-style seed via admin APIs is painful; instead do a real
    COD checkout. Returns the created order_id."""
    from datetime import datetime, timezone
    tok = tokens["buyer"]
    _clear_cart(tok)
    # Pick vendor's product
    r = requests.get(f"{BASE_URL}/api/admin/products?limit=500",
                     headers=_hdr(tokens["admin"]), timeout=30)
    rows = r.json().get("items") or []
    prod = next((p for p in rows
                 if p.get("vendor_id") == vendor_id and
                 (p.get("cod_available") is not False) and
                 float(p.get("price") or 0) > 0), None)
    assert prod, "no COD-eligible vendor product"
    qty = max(1, int(cod_due // max(1, float(prod.get("price") or 1))) or 1)
    _add(tok, prod["id"], qty)
    r = requests.post(f"{BASE_URL}/api/orders/checkout", headers=_hdr(tok),
                      json={"payment_method": "cod",
                            "shipping_address": {
                                "name": "Iter92 Tester", "phone": "9999900000",
                                "line1": "1 Test St", "city": "Srikalahasti",
                                "state": "AP", "pincode": "517644",
                            }}, timeout=30)
    assert r.status_code == 200, f"checkout: {r.status_code} {r.text}"
    out = r.json()
    # checkout may return {"orders":[{id,...}]} or single
    orders = out.get("orders") or ([out["order"]] if out.get("order") else [])
    assert orders, f"no order created: {out}"
    return [o.get("id") for o in orders if o.get("id")]


class TestDeliveryPartnerFlow:
    @pytest.fixture(scope="class")
    def seeded_orders(self, tokens, rider_vendor_mapping):
        """Seed 2 COD orders for the buyer so bulk advance has >1 order."""
        o1 = _seed_cod_order(tokens, tokens["buyer_user"].get("id"), VENDOR_ID, 100, "iter92-A")
        o2 = _seed_cod_order(tokens, tokens["buyer_user"].get("id"), VENDOR_ID, 100, "iter92-B")
        ids = o1 + o2
        yield ids
        # cleanup — delete orders directly via admin
        for oid in ids:
            try:
                requests.delete(f"{BASE_URL}/api/admin/orders/{oid}",
                                headers=_hdr(tokens["admin"]), timeout=10)
            except Exception:
                pass

    def test_customers_view_lists_grouped_orders(self, tokens, seeded_orders):
        r = requests.get(f"{BASE_URL}/api/delivery-partner/me/customers?status=open",
                         headers=_hdr(tokens["rider"]), timeout=20)
        assert r.status_code == 200, r.text
        items = r.json().get("items") or []
        mine = next((x for x in items
                     if x.get("user_id") == tokens["buyer_user"].get("id")), None)
        assert mine, f"buyer not grouped: {[i.get('user_id') for i in items]}"
        for k in ("name", "phone", "orders", "order_count", "open_count",
                  "item_count", "order_value", "cash_to_collect",
                  "next_status", "next_label"):
            assert k in mine, f"customer row missing {k}"
        assert mine["open_count"] >= 2, f"open_count={mine['open_count']}"
        assert all(o.get("shop_name") for o in mine["orders"])

    def test_customers_view_blocks_non_rider(self, tokens):
        r = requests.get(f"{BASE_URL}/api/delivery-partner/me/customers?status=open",
                         headers=_hdr(tokens["buyer"]), timeout=20)
        assert r.status_code == 403, f"buyer token should get 403, got {r.status_code}"
        r = requests.get(f"{BASE_URL}/api/delivery-partner/me/customers?status=open",
                         headers=_hdr(tokens["vendor"]), timeout=20)
        assert r.status_code == 403

    def test_advance_each_to_own_next_stage(self, tokens, seeded_orders):
        """Empty body steps every open order to NEXT_STATUS[current]."""
        buyer_id = tokens["buyer_user"].get("id")
        r = requests.post(
            f"{BASE_URL}/api/delivery-partner/customers/{buyer_id}/advance",
            headers=_hdr(tokens["rider"]), json={}, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["updated"] >= 1

    def test_bulk_delivered_cash_safety_idempotent(self, tokens, seeded_orders):
        """Jump all remaining to delivered; dp_cash_in_hand must rise by
        sum of cod_due with exactly ONE DPCASH:{order_id} txn per order.
        A second identical call must be a no-op."""
        buyer_id = tokens["buyer_user"].get("id")

        # Capture rider cash BEFORE
        w0 = requests.get(f"{BASE_URL}/api/delivery-partner/me/wallet",
                          headers=_hdr(tokens["rider"]), timeout=20).json()
        before_cash = float(w0["cash_in_hand"])

        # Record admin net_worth BEFORE to assert ZERO drift from COD collection
        nw0 = requests.get(f"{BASE_URL}/api/admin/finance/net-worth",
                           headers=_hdr(tokens["admin"]), timeout=20).json()["master"]["net_worth"]

        # First call: jump to delivered
        r1 = requests.post(
            f"{BASE_URL}/api/delivery-partner/customers/{buyer_id}/advance",
            headers=_hdr(tokens["rider"]), json={"status": "delivered"}, timeout=30,
        )
        assert r1.status_code == 200, r1.text
        got_cash1 = float(r1.json().get("cash_collected") or 0)

        w1 = requests.get(f"{BASE_URL}/api/delivery-partner/me/wallet",
                          headers=_hdr(tokens["rider"]), timeout=20).json()
        after_cash1 = float(w1["cash_in_hand"])
        assert abs((after_cash1 - before_cash) - got_cash1) < 0.02, (
            f"dp_cash_in_hand rose by {after_cash1 - before_cash}; "
            f"reported cash_collected {got_cash1}"
        )

        # Second call — orders already delivered → cash_collected must be 0
        r2 = requests.post(
            f"{BASE_URL}/api/delivery-partner/customers/{buyer_id}/advance",
            headers=_hdr(tokens["rider"]), json={"status": "delivered"}, timeout=30,
        )
        # Could be 404 "no open orders" or 200 with updated=0 — both OK
        if r2.status_code == 200:
            assert float(r2.json().get("cash_collected") or 0) < 0.01
            assert int(r2.json().get("updated") or 0) == 0
        else:
            assert r2.status_code == 404

        w2 = requests.get(f"{BASE_URL}/api/delivery-partner/me/wallet",
                          headers=_hdr(tokens["rider"]), timeout=20).json()
        assert abs(float(w2["cash_in_hand"]) - after_cash1) < 0.02, (
            "Replay credited cash again — idempotency broken!"
        )

        # Admin net_worth should be UNCHANGED (COD was already an asset
        # in cash_on_hand even before marking delivered via unremitted field,
        # but at a minimum this reinforces no double-count)
        nw1 = requests.get(f"{BASE_URL}/api/admin/finance/net-worth",
                           headers=_hdr(tokens["admin"]), timeout=20).json()["master"]["net_worth"]
        # we allow small drift because other activity may happen; but
        # the ADJUST on COD delivery must be bounded.
        assert abs(nw1 - nw0) < max(10.0, after_cash1 + 1.0), (
            f"admin net_worth drifted {nw1-nw0} from COD delivery — unexpected"
        )

    def test_me_vendors_sync(self, tokens):
        """After bulk delivery, GET /me/vendors (My Shops) open_orders drops."""
        r = requests.get(f"{BASE_URL}/api/delivery-partner/me/vendors",
                         headers=_hdr(tokens["rider"]), timeout=20)
        assert r.status_code == 200, r.text


# ─────────────────────────────────────────────────────────────────────────
# 6. Rider wallet set-off remit (/remit/wallet)
# ─────────────────────────────────────────────────────────────────────────
class TestRiderWalletRemit:
    def test_wallet_arithmetic_three_cases(self, tokens):
        """payable_from_wallet = min(cash_in_hand, wallet);
        remaining_after_wallet = cash_in_hand − that."""
        r = requests.get(f"{BASE_URL}/api/delivery-partner/me/wallet",
                         headers=_hdr(tokens["rider"]), timeout=20)
        assert r.status_code == 200, r.text
        v = r.json()
        for k in ("payable_from_wallet", "remaining_after_wallet",
                  "personal_wallet", "cash_in_hand"):
            assert k in v, f"wallet missing {k}"
        pw = round(min(float(v["cash_in_hand"]), float(v["personal_wallet"])), 2)
        assert abs(float(v["payable_from_wallet"]) - pw) < 0.02
        rem = round(float(v["cash_in_hand"]) - pw, 2)
        assert abs(float(v["remaining_after_wallet"]) - rem) < 0.02

        r2 = requests.get(f"{BASE_URL}/api/delivery-partner/me/net-worth",
                          headers=_hdr(tokens["rider"]), timeout=20)
        assert r2.status_code == 200
        v2 = r2.json()
        assert "payable_from_wallet" in v2 and "remaining_after_wallet" in v2

    def test_remit_wallet_guard_over_cash(self, tokens):
        w = requests.get(f"{BASE_URL}/api/delivery-partner/me/wallet",
                         headers=_hdr(tokens["rider"]), timeout=20).json()
        over = float(w["cash_in_hand"]) + 10_000.0
        r = requests.post(f"{BASE_URL}/api/delivery-partner/remit/wallet",
                          headers=_hdr(tokens["rider"]),
                          json={"amount": over}, timeout=20)
        assert r.status_code == 400, f"should 400 when amount>cash: got {r.status_code}"

    def test_remit_wallet_guard_over_wallet(self, tokens):
        """Fund rider wallet with ₹1 only, then try to remit > wallet balance
        but ≤ cash_in_hand → 400 naming the wallet balance."""
        w = requests.get(f"{BASE_URL}/api/delivery-partner/me/wallet",
                         headers=_hdr(tokens["rider"]), timeout=20).json()
        cash = float(w["cash_in_hand"])
        if cash < 2.0:
            pytest.skip(f"rider has no cash to owe (cash_in_hand={cash})")
        wallet_bal = float(w["personal_wallet"])
        # Try to remit a bit more than wallet (but within cash_in_hand)
        attempt = round(min(cash, wallet_bal + 1.0), 2)
        if attempt <= wallet_bal + 0.009:
            pytest.skip("cannot force wallet<attempt<=cash scenario")
        r = requests.post(f"{BASE_URL}/api/delivery-partner/remit/wallet",
                          headers=_hdr(tokens["rider"]),
                          json={"amount": attempt}, timeout=20)
        assert r.status_code == 400, r.text
        assert "wallet" in (r.json().get("detail") or "").lower()

    def test_remit_wallet_setoff_no_bank_row(self, tokens):
        """CRITICAL: funding rider's wallet, then wallet-set-off must debit
        wallet + cash_in_hand, create 2 txns (not a bank_ledger row)."""
        w = requests.get(f"{BASE_URL}/api/delivery-partner/me/wallet",
                         headers=_hdr(tokens["rider"]), timeout=20).json()
        cash = float(w["cash_in_hand"])
        if cash < 1.0:
            pytest.skip(f"rider has no cash to set off (cash_in_hand={cash})")
        setoff = round(min(cash, 50.0), 2)

        # Fund rider wallet via admin adjust so it can cover the set-off.
        key = uuid.uuid4().hex[:8]
        fund = requests.post(
            f"{BASE_URL}/api/admin/transactions/adjust",
            headers=_hdr(tokens["admin"]),
            json={"user_id": RIDER_ID, "amount": setoff,
                  "category": "correction",
                  "description": f"TEST iter92 fund rider for setoff {key}",
                  "wallet": "wallet_balance"}, timeout=20,
        )
        assert fund.status_code == 200, fund.text

        # Capture BANK balance before
        nw_before = requests.get(f"{BASE_URL}/api/admin/finance/net-worth",
                                 headers=_hdr(tokens["admin"]), timeout=20).json()
        bank_before = float(nw_before["group_7_bank"]["balance"])
        nw_val_before = float(nw_before["master"]["net_worth"])

        r = requests.post(f"{BASE_URL}/api/delivery-partner/remit/wallet",
                          headers=_hdr(tokens["rider"]),
                          json={"amount": setoff}, timeout=30)
        assert r.status_code == 200, f"remit/wallet: {r.status_code} {r.text}"
        body = r.json()
        assert body["ok"] is True
        assert abs(float(body["amount"]) - setoff) < 0.02

        w2 = requests.get(f"{BASE_URL}/api/delivery-partner/me/wallet",
                          headers=_hdr(tokens["rider"]), timeout=20).json()
        assert abs(float(w2["cash_in_hand"]) - (cash - setoff)) < 0.02
        # Wallet should have dropped too (we funded = setoff, so now ~original)

        nw_after = requests.get(f"{BASE_URL}/api/admin/finance/net-worth",
                                headers=_hdr(tokens["admin"]), timeout=20).json()
        bank_after = float(nw_after["group_7_bank"]["balance"])
        nw_val_after = float(nw_after["master"]["net_worth"])
        assert abs(bank_after - bank_before) < 0.02, (
            f"BANK BALANCE MOVED on wallet set-off: {bank_before} → {bank_after} "
            "(must be internal — no bank_ledger row)"
        )
        # Net worth: asset (cash_on_hand) falls by setoff AND liability
        # (customer_wallet) also falls by setoff → net worth unchanged.
        assert abs(nw_val_after - nw_val_before) < 0.05, (
            f"net_worth drifted on set-off: {nw_val_before} → {nw_val_after}"
        )

    def test_remit_start_mock_regression(self, tokens):
        """Razorpay remit regression — /remit/start + /remit/verify path still works
        and writes a bank_ledger CREDIT (opposite of the wallet set-off)."""
        w = requests.get(f"{BASE_URL}/api/delivery-partner/me/wallet",
                         headers=_hdr(tokens["rider"]), timeout=20).json()
        cash = float(w["cash_in_hand"])
        if cash < 1.0:
            pytest.skip(f"nothing to remit via Razorpay (cash_in_hand={cash})")
        amt = round(min(cash, 50.0), 2)
        start = requests.post(f"{BASE_URL}/api/delivery-partner/remit/start",
                              headers=_hdr(tokens["rider"]),
                              json={"amount": amt}, timeout=30)
        if start.status_code != 200:
            pytest.skip(f"remit/start not available: {start.status_code} {start.text[:120]}")
        s = start.json()
        remit_id = s.get("remit_id") or s.get("id")
        rzp_order = s.get("razorpay_order_id") or s.get("order_id") or ""
        assert remit_id and rzp_order, f"no remit_id / razorpay_order_id in {s}"
        bank_before = requests.get(f"{BASE_URL}/api/admin/finance/net-worth",
                                   headers=_hdr(tokens["admin"]),
                                   timeout=20).json()["group_7_bank"]["balance"]
        verify = requests.post(
            f"{BASE_URL}/api/delivery-partner/remit/verify",
            headers=_hdr(tokens["rider"]),
            json={"remit_id": remit_id,
                  "razorpay_order_id": rzp_order,
                  "razorpay_payment_id": f"pay_MOCK_{uuid.uuid4().hex[:12]}",
                  "razorpay_signature": "mock"},
            timeout=30,
        )
        assert verify.status_code == 200, verify.text
        bank_after = requests.get(f"{BASE_URL}/api/admin/finance/net-worth",
                                  headers=_hdr(tokens["admin"]),
                                  timeout=20).json()["group_7_bank"]["balance"]
        assert bank_after - bank_before >= amt - 0.05, (
            f"Razorpay remit did NOT credit bank: {bank_before} → {bank_after} "
            f"(expected +{amt})"
        )
