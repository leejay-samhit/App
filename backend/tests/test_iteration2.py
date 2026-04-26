"""Iteration 2 tests — multi-level payouts, notifications, cart, orders, dashboard new fields."""
import uuid
import pytest
from conftest import BASE_URL, auth_headers


def _register(api, ref=None):
    email = f"TEST_{uuid.uuid4().hex[:10]}@test.com"
    payload = {"name": "U", "email": email, "password": "Test@1234"}
    if ref:
        payload["referral_code"] = ref
    r = api.post(f"{BASE_URL}/api/auth/register", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _pay(api, token):
    r = api.post(f"{BASE_URL}/api/payment/register-fee", headers=auth_headers(token))
    assert r.status_code == 200, r.text


# ---------- Dashboard new fields ----------
class TestDashboardNewFields:
    def test_dashboard_includes_new_fields(self, api):
        u = _register(api)
        r = api.get(f"{BASE_URL}/api/users/me/dashboard", headers=auth_headers(u["token"]))
        assert r.status_code == 200
        d = r.json()
        # New fields
        assert "unread_notifications" in d
        assert isinstance(d["unread_notifications"], int)
        assert "tier" in d
        assert {"name", "min", "color", "icon"}.issubset(d["tier"].keys())
        assert d["tier"]["name"] == "Bronze"  # team_size 0
        assert "level_payouts" in d
        assert d["level_payouts"] == {"l1": 400, "l2": 100, "l3": 50}


# ---------- Multi-level payouts ----------
class TestMultiLevelPayouts:
    def test_l1_l2_l3_chain(self, api):
        # S -> A -> 4 directs of A. After all 4 paid:
        #   A: ₹400 (L1 4-cycle)
        #   S: 4×₹100 = ₹400 (L2)
        # Then add E under one of A's directs (D1 -> E), pay E:
        #   D1 gets L1 increment (1/4, no payout yet)
        #   A gets ₹100 L2
        #   S gets ₹50 L3
        S = _register(api); _pay(api, S["token"])
        A = _register(api, ref=S["user"]["referral_code"]); _pay(api, A["token"])
        # After A pays: S gets direct +1 (no L1 cycle yet, only 1)
        directs = []
        for _ in range(4):
            d = _register(api, ref=A["user"]["referral_code"])
            _pay(api, d["token"])
            directs.append(d)

        # Verify A's wallet
        a_dash = api.get(f"{BASE_URL}/api/users/me/dashboard", headers=auth_headers(A["token"])).json()
        assert a_dash["direct_referrals"] == 4, a_dash
        assert a_dash["wallet_balance"] == 400, f"A should have ₹400 L1 payout, got {a_dash['wallet_balance']}"
        assert a_dash["payouts_received"] == 1

        # Verify S's wallet: 4 × L2 ₹100 = ₹400 (S has only 1 direct = A; no L1 cycle)
        s_dash = api.get(f"{BASE_URL}/api/users/me/dashboard", headers=auth_headers(S["token"])).json()
        assert s_dash["direct_referrals"] == 1
        assert s_dash["wallet_balance"] == 400, f"S L2 expected ₹400, got {s_dash['wallet_balance']}"
        assert s_dash["payouts_received"] == 0  # no L1 cycle yet
        assert s_dash["team_size"] >= 5  # A + 4 directs

        # Add E under D1 -> S should get L3 ₹50
        D1 = directs[0]
        E = _register(api, ref=D1["user"]["referral_code"]); _pay(api, E["token"])

        s_dash2 = api.get(f"{BASE_URL}/api/users/me/dashboard", headers=auth_headers(S["token"])).json()
        # S wallet was 400, +50 L3 = 450
        assert s_dash2["wallet_balance"] == 450, f"S L3 +50 expected 450, got {s_dash2['wallet_balance']}"

        # A wallet was 400, + L2 ₹100 = 500
        a_dash2 = api.get(f"{BASE_URL}/api/users/me/dashboard", headers=auth_headers(A["token"])).json()
        assert a_dash2["wallet_balance"] == 500

        # Transactions for S should include L2 and L3 payouts
        txns = api.get(f"{BASE_URL}/api/transactions/me", headers=auth_headers(S["token"])).json()
        levels = [t.get("level") for t in txns if t.get("type") == "referral_payout"]
        assert 2 in levels and 3 in levels


# ---------- Notifications ----------
class TestNotifications:
    def test_welcome_notification_on_payment(self, api):
        u = _register(api); _pay(api, u["token"])
        r = api.get(f"{BASE_URL}/api/notifications/me", headers=auth_headers(u["token"]))
        assert r.status_code == 200
        notifs = r.json()
        kinds = [n["kind"] for n in notifs]
        assert "welcome" in kinds

    def test_referral_notification_to_sponsor(self, api):
        S = _register(api); _pay(api, S["token"])
        D = _register(api, ref=S["user"]["referral_code"]); _pay(api, D["token"])
        r = api.get(f"{BASE_URL}/api/notifications/me", headers=auth_headers(S["token"])).json()
        kinds = [n["kind"] for n in r]
        assert "referral" in kinds

    def test_unread_only_and_read_all(self, api):
        u = _register(api); _pay(api, u["token"])
        all_n = api.get(f"{BASE_URL}/api/notifications/me", headers=auth_headers(u["token"])).json()
        assert len(all_n) >= 1
        unread = api.get(f"{BASE_URL}/api/notifications/me?unread_only=true",
                         headers=auth_headers(u["token"])).json()
        assert all(n["read"] is False for n in unread)
        assert len(unread) >= 1
        # mark all read
        m = api.post(f"{BASE_URL}/api/notifications/me/read-all", headers=auth_headers(u["token"]))
        assert m.status_code == 200
        unread2 = api.get(f"{BASE_URL}/api/notifications/me?unread_only=true",
                          headers=auth_headers(u["token"])).json()
        assert unread2 == []
        # dashboard count = 0
        d = api.get(f"{BASE_URL}/api/users/me/dashboard", headers=auth_headers(u["token"])).json()
        assert d["unread_notifications"] == 0


# ---------- Cart & Orders ----------
class TestCartAndOrders:
    def _build_funded_user(self, api):
        # build a user with wallet via two 4-direct cycles → ₹800 (covers cheapest ₹499 product)
        S = _register(api); _pay(api, S["token"])
        for _ in range(8):
            c = _register(api, ref=S["user"]["referral_code"]); _pay(api, c["token"])
        return S

    def test_cart_add_get_remove_clear(self, api):
        u = _register(api)
        products = api.get(f"{BASE_URL}/api/products").json()
        assert products
        p1 = products[0]
        # add
        r = api.post(f"{BASE_URL}/api/cart/add", json={"product_id": p1["id"], "qty": 2},
                     headers=auth_headers(u["token"]))
        assert r.status_code == 200
        # get enriched
        c = api.get(f"{BASE_URL}/api/cart", headers=auth_headers(u["token"])).json()
        assert c["count"] == 2
        assert len(c["items"]) == 1
        item = c["items"][0]
        assert item["line_total"] == p1["price"] * 2
        assert item["product"]["id"] == p1["id"]
        assert c["total"] == p1["price"] * 2
        # add same again increments
        api.post(f"{BASE_URL}/api/cart/add", json={"product_id": p1["id"], "qty": 1},
                 headers=auth_headers(u["token"]))
        c2 = api.get(f"{BASE_URL}/api/cart", headers=auth_headers(u["token"])).json()
        assert c2["count"] == 3
        # remove
        api.post(f"{BASE_URL}/api/cart/remove", json={"product_id": p1["id"]},
                 headers=auth_headers(u["token"]))
        c3 = api.get(f"{BASE_URL}/api/cart", headers=auth_headers(u["token"])).json()
        assert c3["count"] == 0
        # clear (idempotent)
        api.post(f"{BASE_URL}/api/cart/clear", headers=auth_headers(u["token"]))

    def test_cart_add_invalid_product(self, api):
        u = _register(api)
        r = api.post(f"{BASE_URL}/api/cart/add", json={"product_id": "nope", "qty": 1},
                     headers=auth_headers(u["token"]))
        assert r.status_code == 404

    def test_checkout_empty_cart(self, api):
        u = _register(api)
        r = api.post(f"{BASE_URL}/api/orders/checkout", headers=auth_headers(u["token"]))
        assert r.status_code == 400

    def test_checkout_insufficient_wallet(self, api):
        u = _register(api)  # wallet 0
        products = api.get(f"{BASE_URL}/api/products").json()
        p = products[0]
        api.post(f"{BASE_URL}/api/cart/add", json={"product_id": p["id"], "qty": 1},
                 headers=auth_headers(u["token"]))
        r = api.post(f"{BASE_URL}/api/orders/checkout", headers=auth_headers(u["token"]))
        assert r.status_code == 400
        assert "Insufficient" in r.json().get("detail", "")

    def test_checkout_success_deducts_and_creates_order(self, api):
        S = self._build_funded_user(api)
        token = S["token"]
        # Verify wallet 800 (2 cycles)
        d = api.get(f"{BASE_URL}/api/users/me/dashboard", headers=auth_headers(token)).json()
        assert d["wallet_balance"] == 800
        starting = d["wallet_balance"]
        products = api.get(f"{BASE_URL}/api/products").json()
        # Pick a cheap product
        cheap = sorted(products, key=lambda x: x["price"])[0]
        api.post(f"{BASE_URL}/api/cart/add", json={"product_id": cheap["id"], "qty": 1},
                 headers=auth_headers(token))
        r = api.post(f"{BASE_URL}/api/orders/checkout", headers=auth_headers(token))
        assert r.status_code == 200, r.text
        order = r.json()
        assert order["status"] == "placed"
        assert order["paid_via"] == "wallet"
        assert isinstance(order["items"], list) and len(order["items"]) == 1
        assert order["items"][0]["product_id"] == cheap["id"]
        assert order["total"] == cheap["price"]

        # Wallet deducted
        d2 = api.get(f"{BASE_URL}/api/users/me/dashboard", headers=auth_headers(token)).json()
        assert d2["wallet_balance"] == starting - cheap["price"]
        # Cart cleared
        c = api.get(f"{BASE_URL}/api/cart", headers=auth_headers(token)).json()
        assert c["count"] == 0
        # Orders/me has order
        my = api.get(f"{BASE_URL}/api/orders/me", headers=auth_headers(token)).json()
        assert any(o["id"] == order["id"] for o in my)
        # Order notification created
        notifs = api.get(f"{BASE_URL}/api/notifications/me", headers=auth_headers(token)).json()
        assert any(n["kind"] == "order" for n in notifs)
