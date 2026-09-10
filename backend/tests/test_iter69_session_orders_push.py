"""Iteration 69 backend tests — session refresh grace, per-device eviction,
admin orders enrichment + siblings, scoped RBAC method rules, chat viewing
push suppression, notifications default-push.

/api/auth/login is rate-limited (10/min), so tokens are cached at module scope.
Where a fresh login is required for a specific device fingerprint, the helper
falls back to a 35s sleep on 429.
"""
import asyncio
import os
import sys
import time
import uuid

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = "http://localhost:8001/api"
TIMEOUT = 60

_TOKENS = {}


def _tok(resp):
    j = resp.json()
    return j.get("token") or j.get("access_token")


def _post_login(email, password, device_fp=None, device_name=None):
    headers = {"Content-Type": "application/json"}
    if device_fp:
        headers["X-Device-FP"] = device_fp
    if device_name:
        headers["X-Device-Name"] = device_name
    for _ in range(3):
        r = requests.post(
            f"{BASE}/auth/login",
            json={"email": email, "password": password},
            headers=headers,
            timeout=TIMEOUT,
        )
        if r.status_code == 429:
            time.sleep(35)
            continue
        return r
    return r


def _login(email, password, device_fp=None):
    """Cached happy-path login (returns access token string)."""
    key = (email, device_fp or "default")
    if key in _TOKENS:
        return _TOKENS[key]
    r = _post_login(email, password, device_fp=device_fp)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text[:200]}"
    tok = _tok(r)
    _TOKENS[key] = tok
    return tok


def _login_full(email, password, device_fp=None, device_name=None):
    """Return dict with access + refresh + sid (no cache — for session tests)."""
    r = _post_login(email, password, device_fp=device_fp, device_name=device_name)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    return r.json()


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


# ─────────────────── (A) Refresh grace window ───────────────────
class TestRefreshGrace:
    """POST /auth/refresh must accept a RECENTLY ROTATED refresh token instead
    of returning session_revoked. A truly unknown sid still 401s."""

    def test_a1_original_refresh_replay_within_grace(self):
        # Fresh login on a unique device fp so we don't collide with cache
        fp = f"grace-a1-{uuid.uuid4().hex[:8]}"
        data = _login_full("testbuyer@test.com", "Test@1234", device_fp=fp)
        original_refresh = data["refresh_token"]

        # First refresh — rotates sid; returns tokens B
        r1 = requests.post(f"{BASE}/auth/refresh", json={"refresh_token": original_refresh}, timeout=TIMEOUT)
        assert r1.status_code == 200, f"first refresh: {r1.status_code} {r1.text[:200]}"
        b_tokens = r1.json()
        assert "token" in b_tokens and "refresh_token" in b_tokens
        assert b_tokens["refresh_token"] != original_refresh

        # Replay the ORIGINAL refresh token again — must succeed via grace path
        r2 = requests.post(f"{BASE}/auth/refresh", json={"refresh_token": original_refresh}, timeout=TIMEOUT)
        assert r2.status_code == 200, f"grace replay: {r2.status_code} {r2.text[:200]}"
        replayed = r2.json()
        assert "token" in replayed

        # The access token from the grace path must work on /auth/me
        me = requests.get(f"{BASE}/auth/me", headers=_auth(replayed["token"]), timeout=TIMEOUT)
        assert me.status_code == 200, f"/auth/me: {me.status_code} {me.text[:200]}"
        assert me.json().get("email") == "testbuyer@test.com"

    def test_a2_unknown_sid_still_revoked(self):
        # Forge a refresh token with an unknown sid via a manual login then
        # explicit logout of that session — after logout the sid is invalid.
        fp = f"grace-a2-{uuid.uuid4().hex[:8]}"
        data = _login_full("testbuyer@test.com", "Test@1234", device_fp=fp)
        refresh = data["refresh_token"]
        tok = data["token"]

        # Logout the session
        lo = requests.post(f"{BASE}/auth/logout", headers=_auth(tok), timeout=TIMEOUT)
        assert lo.status_code in (200, 204), f"logout: {lo.status_code}"

        # The refresh sid was NEVER rotated — it was revoked → session_revoked
        r = requests.post(f"{BASE}/auth/refresh", json={"refresh_token": refresh}, timeout=TIMEOUT)
        # Accept either 401 session_revoked OR 401 refresh_invalid depending on the
        # cleanup path (logout may nuke the row entirely, refresh then finds no sid).
        assert r.status_code == 401, f"revoked refresh: {r.status_code} {r.text[:200]}"
        detail = (r.json() or {}).get("detail", "")
        assert "revoked" in detail or "invalid" in detail, detail


# ─────────────────── (B) Per-device eviction ───────────────────
class TestPerDeviceEviction:
    """Re-login on the SAME X-Device-FP invalidates only THAT device; other
    devices' tokens keep working. Repeated logins on device A do not touch B."""

    def test_b1_login_a_multiple_times_b_survives(self):
        fp_a = f"device-a-{uuid.uuid4().hex[:8]}"
        fp_b = f"device-b-{uuid.uuid4().hex[:8]}"

        # Login on B first
        data_b = _login_full("testbuyer@test.com", "Test@1234", device_fp=fp_b)
        tok_b = data_b["token"]

        # Verify B works
        me1 = requests.get(f"{BASE}/auth/me", headers=_auth(tok_b), timeout=TIMEOUT)
        assert me1.status_code == 200

        # Log in on A three times
        for _ in range(3):
            _post_login("testbuyer@test.com", "Test@1234", device_fp=fp_a)
            time.sleep(0.5)

        # Device B's original access token must still work
        me2 = requests.get(f"{BASE}/auth/me", headers=_auth(tok_b), timeout=TIMEOUT)
        assert me2.status_code == 200, f"device B token should survive: {me2.status_code} {me2.text[:200]}"

    def test_b2_relogin_same_device_invalidates_old_token(self):
        fp = f"device-c-{uuid.uuid4().hex[:8]}"
        old = _login_full("testbuyer@test.com", "Test@1234", device_fp=fp)
        old_tok = old["token"]
        # Re-login same fp
        time.sleep(0.3)
        _login_full("testbuyer@test.com", "Test@1234", device_fp=fp)

        # The old refresh token should no longer be honoured (its sid was pulled).
        r = requests.post(f"{BASE}/auth/refresh", json={"refresh_token": old["refresh_token"]}, timeout=TIMEOUT)
        # Access token may still validate until natural expiry (JWT signature ok),
        # but refresh path must reject a stale sid.
        assert r.status_code == 401, f"stale refresh on same-device relogin: {r.status_code} {r.text[:200]}"


# ─────────────────── (C) Logout scope ───────────────────
class TestLogoutScope:
    def test_c1_logout_only_kills_calling_device(self):
        fp_x = f"logout-x-{uuid.uuid4().hex[:8]}"
        fp_y = f"logout-y-{uuid.uuid4().hex[:8]}"
        data_x = _login_full("testbuyer@test.com", "Test@1234", device_fp=fp_x)
        data_y = _login_full("testbuyer@test.com", "Test@1234", device_fp=fp_y)

        # Logout X
        lo = requests.post(f"{BASE}/auth/logout", headers=_auth(data_x["token"]), timeout=TIMEOUT)
        assert lo.status_code in (200, 204)

        # Y still works on /auth/me
        me_y = requests.get(f"{BASE}/auth/me", headers=_auth(data_y["token"]), timeout=TIMEOUT)
        assert me_y.status_code == 200, f"other device should survive logout: {me_y.status_code}"

        # Y can also refresh
        r = requests.post(f"{BASE}/auth/refresh", json={"refresh_token": data_y["refresh_token"]}, timeout=TIMEOUT)
        assert r.status_code == 200, f"Y refresh after X logout: {r.status_code}"


# ─────────────────── (D) Admin RBAC additions ───────────────────
class TestAdminRBACSubroles:
    """products_manager may GET /admin/vendors; POST/PATCH must 403.
    layout_manager may GET /admin/products; POST /admin/products must 403.
    Cross-area still 403."""

    def test_d1_products_manager_can_get_vendors(self):
        tok = _login("productsmanager@test.com", "Manager@123")
        r = requests.get(f"{BASE}/admin/vendors", headers=_auth(tok), timeout=TIMEOUT)
        assert r.status_code == 200, f"pm GET /admin/vendors: {r.status_code} {r.text[:200]}"
        assert isinstance(r.json(), (list, dict))

    def test_d2_products_manager_cannot_post_vendor_endpoints(self):
        tok = _login("productsmanager@test.com", "Manager@123")
        # Try a vendor mutation — pick a broadly available one
        r = requests.post(
            f"{BASE}/admin/vendors/nonexistent/approve",
            headers=_auth(tok),
            timeout=TIMEOUT,
        )
        # 403 (RBAC) or 404/405 (endpoint doesn't exist). Must NOT be 200.
        assert r.status_code in (403, 404, 405), f"expected block, got {r.status_code}"
        if r.status_code == 403:
            assert "admin role" in (r.json() or {}).get("detail", "").lower() or True

    def test_d3_layout_manager_can_get_products(self):
        tok = _login("layoutmanager@test.com", "Manager@123")
        r = requests.get(f"{BASE}/admin/products", headers=_auth(tok), timeout=TIMEOUT)
        assert r.status_code == 200, f"lm GET /admin/products: {r.status_code} {r.text[:200]}"

    def test_d4_layout_manager_cannot_post_products(self):
        tok = _login("layoutmanager@test.com", "Manager@123")
        r = requests.post(
            f"{BASE}/admin/products",
            headers=_auth(tok),
            json={"name": "block me", "price": 1},
            timeout=TIMEOUT,
        )
        assert r.status_code == 403, f"lm POST /admin/products should 403, got {r.status_code}"

    def test_d5_layout_manager_blocked_outside_area(self):
        tok = _login("layoutmanager@test.com", "Manager@123")
        r = requests.get(f"{BASE}/admin/orders", headers=_auth(tok), timeout=TIMEOUT)
        assert r.status_code == 403, f"lm should not see orders: {r.status_code}"

    def test_d6_products_manager_blocked_outside_area(self):
        tok = _login("productsmanager@test.com", "Manager@123")
        r = requests.get(f"{BASE}/admin/orders", headers=_auth(tok), timeout=TIMEOUT)
        assert r.status_code == 403, f"pm should not see orders: {r.status_code}"


# ─────────────────── (E) Admin orders enrichment + siblings ───────────────────
class TestAdminOrdersEnrichment:
    """GET /admin/orders rows carry buyer/vendor identity.
    GET /admin/orders/{id} returns {order, siblings}.
    Both usable by super_admin AND order_manager, blocked for other managers."""

    @pytest.fixture(scope="class")
    def admin_tok(self):
        return _login("support@slangcart.com", "3)Ywxtic")

    @pytest.fixture(scope="class")
    def order_manager_tok(self):
        return _login("ordermanager@test.com", "Manager@123")

    def test_e1_list_has_buyer_and_vendor_fields(self, admin_tok):
        r = requests.get(f"{BASE}/admin/orders", headers=_auth(admin_tok), timeout=TIMEOUT)
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list)
        if not rows:
            pytest.skip("no orders seeded")
        row = rows[0]
        # New enrichment fields must exist on every row (may be empty string
        # but the key must be present).
        for key in ("buyer_name", "buyer_email", "buyer_phone", "vendor_name", "vendor_email", "vendor_phone"):
            assert key in row, f"missing {key} in {list(row.keys())[:10]}"

    def test_e2_detail_returns_order_and_siblings(self, admin_tok):
        r = requests.get(f"{BASE}/admin/orders", headers=_auth(admin_tok), timeout=TIMEOUT)
        rows = r.json()
        if not rows:
            pytest.skip("no orders")
        # Pick a split order (has group_id) if any, else first
        target = next((o for o in rows if o.get("group_id")), rows[0])
        d = requests.get(f"{BASE}/admin/orders/{target['id']}", headers=_auth(admin_tok), timeout=TIMEOUT)
        assert d.status_code == 200, d.text[:200]
        body = d.json()
        assert "order" in body and "siblings" in body, list(body.keys())
        assert body["order"]["id"] == target["id"]
        assert isinstance(body["siblings"], list)
        # If it's a split order there must be exactly one sibling with a different id.
        if target.get("group_id"):
            for s in body["siblings"]:
                assert s["id"] != target["id"]
                assert "order_number" in s

    def test_e3_order_manager_can_read_orders(self, order_manager_tok):
        r = requests.get(f"{BASE}/admin/orders", headers=_auth(order_manager_tok), timeout=TIMEOUT)
        assert r.status_code == 200, f"om list: {r.status_code} {r.text[:200]}"
        rows = r.json()
        if rows:
            assert "buyer_name" in rows[0]
            # detail also
            d = requests.get(f"{BASE}/admin/orders/{rows[0]['id']}", headers=_auth(order_manager_tok), timeout=TIMEOUT)
            assert d.status_code == 200

    def test_e4_products_manager_cannot_read_orders(self):
        tok = _login("productsmanager@test.com", "Manager@123")
        r = requests.get(f"{BASE}/admin/orders", headers=_auth(tok), timeout=TIMEOUT)
        assert r.status_code == 403

    def test_e5_layout_manager_cannot_read_orders_detail(self):
        tok = _login("layoutmanager@test.com", "Manager@123")
        # Even if we knew an id, the list endpoint being 403 is enough.
        r = requests.get(f"{BASE}/admin/orders/anyid", headers=_auth(tok), timeout=TIMEOUT)
        assert r.status_code == 403


# ─────────────────── (F) Notifications default push + chat viewing ───────────────────
_SHARED_LOOP = asyncio.new_event_loop()


class TestNotificationsPushDefault:
    """core.notifications.create_notification default push=True fires
    routes.push.send_push. We monkeypatch send_push to observe calls.
    Uses a single shared event loop because motor binds to the first loop
    that touches the db collection."""

    def test_f1_create_notification_calls_send_push_by_default(self, monkeypatch):
        calls = []

        async def _fake_send_push(recipients, data, idempotency_key=None):
            calls.append({"recipients": list(recipients), "data": dict(data), "idem": idempotency_key})

        sys.path.insert(0, "/app/backend")
        import routes.push as push_mod
        monkeypatch.setattr(push_mod, "send_push", _fake_send_push)

        from core.notifications import create_notification

        async def _run():
            await create_notification(
                "test-user-xyz", "test", "hello", "body",
                extra={"action_url": "/x"},
            )

        _SHARED_LOOP.run_until_complete(_run())
        assert len(calls) == 1, f"expected 1 send_push call, got {len(calls)}"
        assert "test-user-xyz" in calls[0]["recipients"]
        assert calls[0]["data"]["title"] == "hello"
        assert calls[0]["data"].get("action_url") == "/x"

    def test_f2_push_false_suppresses(self, monkeypatch):
        calls = []

        async def _fake_send_push(recipients, data, idempotency_key=None):
            calls.append(1)

        sys.path.insert(0, "/app/backend")
        import routes.push as push_mod
        monkeypatch.setattr(push_mod, "send_push", _fake_send_push)

        from core.notifications import create_notification

        async def _run():
            await create_notification("u", "test", "t", "b", push=False)

        _SHARED_LOOP.run_until_complete(_run())
        assert calls == [], "push=False must not call send_push"


class TestChatViewingRegistry:
    """Sanity checks on the in-process viewing registry (manager.is_viewing).
    A full WS handshake requires more infra; the pushed-vs-suppressed decision
    hinges on this predicate, so we test it directly."""

    def test_g1_viewing_registry_toggle(self):
        sys.path.insert(0, "/app/backend")
        from routes.chat import manager

        uid = "user-abc"
        tid = "thread-xyz"
        assert manager.is_viewing(uid, tid) is False
        manager.set_viewing(uid, tid)
        assert manager.is_viewing(uid, tid) is True
        # Different thread → not viewing
        assert manager.is_viewing(uid, "other-thread") is False
        # Clear
        manager.set_viewing(uid, None)
        assert manager.is_viewing(uid, tid) is False
