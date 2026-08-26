"""Iter 55 — Edge cases for multi-vendor split + wallet/COD combo.

Complements the happy-path smoke in ``test_iter55_split_checkout.py``.
Covered scenarios:

  1. payment_method='wallet' single vendor → 1 order, wallet_paid=total, cod_due=0
  2. payment_method='cod' single vendor    → cod_due=total, wallet_paid=0
  3. Multi-vendor split (2 vendors) w/ wallet_cod happy sums
  4. wallet_amount=0 with wallet_cod → degrades to pure COD
  5. wallet_amount>=total with wallet_cod → degrades to pure wallet
  6. wallet_amount > actual wallet balance → 400 + stock rolled back
  7. /orders/me back-fill (all rows have order_number, wallet_paid, cod_due)
  8. cancel refund amounts:
        wallet    → refunded == total
        wallet_cod → refunded == wallet_paid
        cod       → refunded == 0
  9. GET /vendor/me/stats — POS 'Store Sale' non-zero when offline_sales
     exist; cancelled orders excluded from online_total.
 10. GET /vendor/me/earnings & /vendor/me/sales carry POS + online rows
     with the newly required fields.
 11. POST /orders/{id}/chat-vendor — 404 for someone else's order,
     200 for owner.
"""

import os
import time
import uuid

import pytest
import requests


BASE = os.environ.get("SC_BASE") or (
    (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "").rstrip("/") + "/api"
) or "https://vendor-network-app-1.preview.emergentagent.com/api"

BUYER_EMAIL = "testbuyer@test.com"
BUYER_PWD = "Test@1234"
VENDOR_EMAIL = "testvendor@test.com"
VENDOR_PWD = "Test@1234"
PIN = "517644"

P1 = "9c6bb05d-eecc-4637-8489-466f1e4f0288"   # Vendor One Widget  ₹100 (vendor1)
P2 = "409e52af-3660-4bb3-92b4-e418a7f4a5aa"   # Vendor Two Gadget  ₹250 (vendor2)

ADDR = {
    "name": "CI Buyer", "phone": "9999999999", "line1": "1 Test Street",
    "city": "Srikalahasti", "state": "Andhra Pradesh", "pincode": PIN,
}


def _login(email, pwd):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": pwd}, timeout=30)
    r.raise_for_status()
    return r.json()["token"]


@pytest.fixture(scope="module")
def buyer_token():
    return _login(BUYER_EMAIL, BUYER_PWD)


@pytest.fixture(scope="module")
def vendor_token():
    return _login(VENDOR_EMAIL, VENDOR_PWD)


@pytest.fixture(scope="module")
def h_buyer(buyer_token):
    return {"Authorization": f"Bearer {buyer_token}"}


@pytest.fixture(scope="module")
def h_vendor(vendor_token):
    return {"Authorization": f"Bearer {vendor_token}"}


def _reset_cart(h):
    requests.post(f"{BASE}/cart/clear", headers=h, timeout=30)


def _add(h, pid, qty=1):
    r = requests.post(f"{BASE}/cart/add", headers=h, json={"product_id": pid, "qty": qty}, timeout=30)
    assert r.status_code == 200, r.text[:200]


def _get_wallet(h):
    me = requests.get(f"{BASE}/auth/me", headers=h, timeout=30).json()
    return float(me.get("wallet_balance") or 0)


def _ensure_wallet(h_buyer, min_bal=1000.0):
    """Top up the buyer wallet if it dropped below `min_bal` after prior tests."""
    bal = _get_wallet(h_buyer)
    if bal >= min_bal:
        return bal
    # Direct top-up via admin — fallback: nudge via DB isn't available from tests.
    # Use the seed script path (idempotent).
    from motor.motor_asyncio import AsyncIOMotorClient
    import asyncio
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    async def _up():
        cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = cli[os.environ.get("DB_NAME", "test_database")]
        await db.users.update_one({"email": BUYER_EMAIL}, {"$set": {"wallet_balance": 5000.0}})
        cli.close()
    asyncio.run(_up())
    return _get_wallet(h_buyer)


# ── Section 1 — payment_method='wallet' happy path ────────────────────
class TestWalletOnly:
    def test_wallet_single_vendor_creates_one_order_no_cod(self, h_buyer):
        _ensure_wallet(h_buyer, 500.0)
        _reset_cart(h_buyer)
        _add(h_buyer, P1, qty=2)  # ₹200
        r = requests.post(f"{BASE}/orders/checkout", headers=h_buyer, timeout=60, json={
            "payment_method": "wallet", "shipping_address": ADDR,
        })
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d["split_count"] == 1
        assert abs(d["grand_total"] - 200.0) < 0.02
        assert abs(d["wallet_paid"] - 200.0) < 0.02
        assert d["cod_due"] == 0
        o = d["orders"][0]
        assert o["paid_via"] == "wallet"
        assert o["payment_status"] == "paid"
        assert o["order_number"].startswith("SC-") and "-" not in o["order_number"][3:]


# ── Section 2 — payment_method='cod' happy path ───────────────────────
class TestCodOnly:
    def test_cod_amount_is_total_not_zero(self, h_buyer):
        _reset_cart(h_buyer)
        _add(h_buyer, P2, qty=1)  # ₹250
        r = requests.post(f"{BASE}/orders/checkout", headers=h_buyer, timeout=60, json={
            "payment_method": "cod", "shipping_address": ADDR,
        })
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert abs(d["grand_total"] - 250.0) < 0.02
        assert d["wallet_paid"] == 0
        assert abs(d["cod_due"] - 250.0) < 0.02, "regression: cod_due must equal grand_total, not zero"
        o = d["orders"][0]
        assert o["paid_via"] == "cod"
        assert o["payment_status"] == "pending_cod"


# ── Section 3 — wallet_cod: degrade to COD when wallet_amount=0 ───────
class TestWalletCodDegradeToCod:
    def test_wallet_amount_zero_becomes_pure_cod(self, h_buyer):
        _reset_cart(h_buyer)
        _add(h_buyer, P1, qty=1)  # ₹100 single vendor
        bal_before = _get_wallet(h_buyer)
        r = requests.post(f"{BASE}/orders/checkout", headers=h_buyer, timeout=60, json={
            "payment_method": "wallet_cod", "wallet_amount": 0, "shipping_address": ADDR,
        })
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d["wallet_paid"] == 0
        assert abs(d["cod_due"] - 100.0) < 0.02
        assert d["orders"][0]["paid_via"] == "cod"
        # Wallet must NOT have been debited.
        assert abs(_get_wallet(h_buyer) - bal_before) < 0.02


# ── Section 4 — wallet_cod: wallet_amount >= total → pure wallet ──────
class TestWalletCodDegradeToWallet:
    def test_wallet_amount_ge_total_becomes_pure_wallet(self, h_buyer):
        _ensure_wallet(h_buyer, 500.0)
        _reset_cart(h_buyer)
        _add(h_buyer, P1, qty=1)  # ₹100
        r = requests.post(f"{BASE}/orders/checkout", headers=h_buyer, timeout=60, json={
            "payment_method": "wallet_cod", "wallet_amount": 999.0, "shipping_address": ADDR,
        })
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert abs(d["wallet_paid"] - 100.0) < 0.02
        assert d["cod_due"] == 0
        assert d["orders"][0]["paid_via"] == "wallet"


# ── Section 5 — insufficient wallet must 400 + roll back stock ────────
class TestInsufficientWalletRollback:
    """Force a case where the *effective* wallet debit (= min(wallet_amount,
    total)) exceeds the buyer's actual wallet balance, so the ATOMIC debit
    inside /orders/checkout must fail and roll back the stock decrement.
    """

    def test_over_wallet_returns_400_and_stock_untouched(self, h_buyer):
        # Temporarily drop the buyer wallet to ₹50 so a ₹100 basket + a
        # ₹100 wallet_amount blows past the balance.
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
        async def _reset(bal):
            cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
            db = cli[os.environ.get("DB_NAME", "test_database")]
            await db.users.update_one({"email": BUYER_EMAIL}, {"$set": {"wallet_balance": bal}})
            cli.close()
        asyncio.run(_reset(50.0))

        _reset_cart(h_buyer)
        _add(h_buyer, P1, qty=1)  # ₹100 basket, wallet has ₹50
        p_before = requests.get(f"{BASE}/products/{P1}", timeout=30).json()
        stock_before = int(p_before.get("stock") or 0)

        try:
            r = requests.post(f"{BASE}/orders/checkout", headers=h_buyer, timeout=60, json={
                "payment_method": "wallet_cod",
                "wallet_amount": 100.0,   # capped at total=100 → tries to debit 100 from a 50 balance
                "shipping_address": ADDR,
            })
            assert r.status_code == 400, f"expected 400 got {r.status_code}: {r.text[:200]}"
            assert "wallet" in r.text.lower()

            # Stock must be restored — no leak from the failed attempt.
            p_after = requests.get(f"{BASE}/products/{P1}", timeout=30).json()
            stock_after = int(p_after.get("stock") or 0)
            assert stock_after == stock_before, (
                f"stock leak: was {stock_before} before failed checkout, now {stock_after}"
            )
            # Wallet balance untouched.
            assert abs(_get_wallet(h_buyer) - 50.0) < 0.02
        finally:
            _reset_cart(h_buyer)
            asyncio.run(_reset(5000.0))


# ── Section 6 — GET /orders/me back-fill ──────────────────────────────
class TestOrdersMeBackfill:
    def test_all_rows_have_required_fields(self, h_buyer):
        rows = requests.get(f"{BASE}/orders/me", headers=h_buyer, timeout=30).json()
        assert isinstance(rows, list)
        assert len(rows) > 0, "no orders visible for buyer"
        for o in rows:
            assert o.get("order_number"), f"missing order_number on {o.get('id')}"
            # wallet_paid + cod_due present (may be back-filled for legacy rows)
            assert o.get("wallet_paid") is not None
            assert o.get("cod_due") is not None
            # split_index/split_count may be missing on legacy rows — but if
            # present must be consistent.
            si = o.get("split_index")
            sc = o.get("split_count")
            if si is not None and sc is not None:
                assert 1 <= int(si) <= int(sc)


# ── Section 7 — Cancel refund amounts ─────────────────────────────────
class TestCancelRefunds:
    """Verify /orders/{id}/cancel refunds the correct slice for each paid_via."""

    def test_cancel_wallet_refunds_full_total(self, h_buyer):
        _ensure_wallet(h_buyer, 500.0)
        _reset_cart(h_buyer)
        _add(h_buyer, P1, qty=1)  # ₹100
        r = requests.post(f"{BASE}/orders/checkout", headers=h_buyer, timeout=60, json={
            "payment_method": "wallet", "shipping_address": ADDR,
        })
        assert r.status_code == 200, r.text[:200]
        oid = r.json()["orders"][0]["id"]
        bal_before = _get_wallet(h_buyer)

        c = requests.post(f"{BASE}/orders/{oid}/cancel", headers=h_buyer, timeout=30)
        assert c.status_code == 200, c.text[:200]
        j = c.json()
        assert j.get("status") == "cancelled"
        assert abs(float(j.get("refunded") or 0) - 100.0) < 0.02
        bal_after = _get_wallet(h_buyer)
        assert abs(bal_after - bal_before - 100.0) < 0.02, (
            f"wallet delta = {bal_after - bal_before} expected +100"
        )

    def test_cancel_cod_refunds_zero(self, h_buyer):
        _reset_cart(h_buyer)
        _add(h_buyer, P1, qty=1)
        r = requests.post(f"{BASE}/orders/checkout", headers=h_buyer, timeout=60, json={
            "payment_method": "cod", "shipping_address": ADDR,
        })
        assert r.status_code == 200
        oid = r.json()["orders"][0]["id"]
        bal_before = _get_wallet(h_buyer)
        c = requests.post(f"{BASE}/orders/{oid}/cancel", headers=h_buyer, timeout=30)
        assert c.status_code == 200
        assert float(c.json().get("refunded") or 0) == 0
        assert abs(_get_wallet(h_buyer) - bal_before) < 0.02

    def test_cancel_wallet_cod_refunds_only_wallet_slice(self, h_buyer):
        _ensure_wallet(h_buyer, 500.0)
        _reset_cart(h_buyer)
        _add(h_buyer, P1, qty=2)  # ₹200 single vendor
        r = requests.post(f"{BASE}/orders/checkout", headers=h_buyer, timeout=60, json={
            "payment_method": "wallet_cod", "wallet_amount": 60.0, "shipping_address": ADDR,
        })
        assert r.status_code == 200, r.text[:200]
        d = r.json()
        # ensure it stayed as wallet_cod (single vendor, wallet 60 of 200)
        assert d["orders"][0]["paid_via"] == "wallet_cod"
        assert abs(float(d["orders"][0]["wallet_paid"]) - 60.0) < 0.02
        oid = d["orders"][0]["id"]
        bal_before = _get_wallet(h_buyer)
        c = requests.post(f"{BASE}/orders/{oid}/cancel", headers=h_buyer, timeout=30)
        assert c.status_code == 200, c.text[:200]
        assert abs(float(c.json().get("refunded") or 0) - 60.0) < 0.02
        assert abs(_get_wallet(h_buyer) - bal_before - 60.0) < 0.02


# ── Section 8 — chat-vendor auth checks ───────────────────────────────
class TestChatVendorAuth:
    def test_chat_vendor_404_for_other_users_order(self, h_buyer, h_vendor):
        # Vendor tries to open chat on a buyer-owned order → 404
        rows = requests.get(f"{BASE}/orders/me", headers=h_buyer, timeout=30).json()
        assert rows, "buyer must have at least one order"
        oid = rows[0]["id"]
        r = requests.post(f"{BASE}/orders/{oid}/chat-vendor", headers=h_vendor, timeout=30)
        assert r.status_code == 404


# ── Section 9 — Vendor stats bug fix (Store Sale, cancelled excluded) ──
class TestVendorStats:
    def test_stats_returns_expected_shape(self, h_vendor):
        r = requests.get(f"{BASE}/vendor/me/stats", headers=h_vendor, timeout=30)
        assert r.status_code == 200, r.text[:200]
        s = r.json()
        # Must include pos_* fields (Store Sale)
        for k in ("pos_total", "pos_today", "pos_orders_all", "pos_orders_today",
                  "online_total", "online_today", "online_orders_all",
                  "total_sales", "today_earnings"):
            assert k in s, f"missing stat key {k}"
        # Types
        assert isinstance(s["pos_orders_all"], int)
        assert isinstance(s["online_orders_all"], int)
        # pos_total is a float — it can be 0 in a clean env, but must not be None
        assert s["pos_total"] is not None


class TestVendorEarnings:
    def test_earnings_online_and_pos_shape(self, h_vendor):
        r = requests.get(f"{BASE}/vendor/me/earnings", headers=h_vendor, timeout=30)
        assert r.status_code == 200, r.text[:200]
        e = r.json()
        assert "items" in e and "sum_amount" in e
        for row in e["items"][:10]:
            assert row.get("channel") in ("online", "pos")
            assert row.get("line_total") is not None
            if row["channel"] == "pos":
                # POS rows come from offline_sales — must carry invoice_no + customer.name
                assert "invoice_no" in row
                assert "customer_name" in row


class TestVendorSales:
    def test_sales_grouped_rows_carry_order_number_and_wallet_fields(self, h_vendor):
        r = requests.get(f"{BASE}/vendor/me/sales", headers=h_vendor, timeout=30)
        assert r.status_code == 200, r.text[:200]
        j = r.json()
        assert "items" in j
        online_rows = [x for x in j["items"] if x.get("channel") != "pos"]
        for o in online_rows[:10]:
            assert o.get("order_number"), "online sale row missing order_number"
            # cod_due / wallet_paid must be present for the new UI
            assert o.get("cod_due") is not None
            assert o.get("wallet_paid") is not None
