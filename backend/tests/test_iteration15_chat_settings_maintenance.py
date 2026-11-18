"""Iteration 15 — Chat Settings (wallpaper + chat lock) + Maintenance backfill.

Covers all new surfaces from the Slangcart follow-up sprint:
  • GET    /api/chat/settings
  • PATCH  /api/chat/settings/wallpaper      (default / clear_default / per-thread / preset validation)
  • POST   /api/chat/lock/setup              (once-only)
  • POST   /api/chat/lock/verify             (right / wrong PIN)
  • POST   /api/chat/lock/change             (rotate PIN; old becomes invalid)
  • PATCH  /api/chat/lock/tab                (PIN-gated tab lock toggle)
  • PATCH  /api/chat/lock/threads            (PIN-gated per-thread lock list)
  • POST   /api/chat/lock/disable            (PIN-gated wipe; then verify/change/disable → 400)
  • POST   /api/admin/maintenance/backfill-approval-status
                                             (super_admin gating + idempotency)
  • Regression: chat post/list/details still 200; /api/admin/broadcasts {audience:'all'} still 201.
"""
from __future__ import annotations

import os
import uuid
import pytest
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
_fe = Path(__file__).resolve().parents[2] / "frontend" / ".env"
if _fe.exists():
    load_dotenv(_fe, override=False)

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "support@networkrupay.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", os.environ.get("ADMIN_PASSWORD", ""))


def _h(t):
    return {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}


# ─────────────────────────── shared fixtures ──────────────────────────────

@pytest.fixture(scope="module")
def s():
    return requests.Session()


@pytest.fixture(scope="module")
def admin_token(s):
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def fresh_user(s, admin_token):
    """Freshly approved non-admin user with NO prior chat-lock state."""
    email = f"TEST_lock_{uuid.uuid4().hex[:8]}@test.com"
    body = {
        "email": email,
        "password": "Passw0rd!",
        "name": "LockTester",
        "phone": f"77777{uuid.uuid4().int % 100000:05d}",
        "referral_code": "EARN",
    }
    r = s.post(f"{BASE_URL}/api/auth/register", json=body)
    assert r.status_code in (200, 201), f"register: {r.status_code} {r.text}"
    data = r.json()
    uid = data["user"]["id"]
    ar = s.post(f"{BASE_URL}/api/admin/approvals/{uid}/approve", headers=_h(admin_token))
    assert ar.status_code == 200, f"approve: {ar.status_code} {ar.text}"
    lg = s.post(f"{BASE_URL}/api/auth/login",
                json={"email": email, "password": "Passw0rd!"})
    assert lg.status_code == 200, lg.text
    d2 = lg.json()
    return {"id": uid, "email": email, "token": d2["token"]}


@pytest.fixture(scope="module")
def second_user(s, admin_token):
    """A second approved user used as a non-admin caller for /maintenance."""
    email = f"TEST_nonadmin_{uuid.uuid4().hex[:8]}@test.com"
    body = {
        "email": email,
        "password": "Passw0rd!",
        "name": "NonAdmin",
        "phone": f"66666{uuid.uuid4().int % 100000:05d}",
        "referral_code": "EARN",
    }
    r = s.post(f"{BASE_URL}/api/auth/register", json=body)
    assert r.status_code in (200, 201), r.text
    data = r.json()
    uid = data["user"]["id"]
    ar = s.post(f"{BASE_URL}/api/admin/approvals/{uid}/approve", headers=_h(admin_token))
    assert ar.status_code == 200, ar.text
    # Re-login to get fresh sid token (admin approval doesn't rotate)
    lg = s.post(f"{BASE_URL}/api/auth/login",
                json={"email": email, "password": "Passw0rd!"})
    assert lg.status_code == 200
    return {"id": uid, "email": email, "token": lg.json()["token"]}


# ═══════════════════════════════════════════════════════════════════════════
# 1. GET /api/chat/settings — baseline shape
# ═══════════════════════════════════════════════════════════════════════════

class TestSettingsShape:
    def test_unauth_rejected(self, s):
        r = s.get(f"{BASE_URL}/api/chat/settings")
        assert r.status_code in (401, 403)

    def test_default_shape(self, s, fresh_user):
        r = s.get(f"{BASE_URL}/api/chat/settings", headers=_h(fresh_user["token"]))
        assert r.status_code == 200, r.text
        body = r.json()
        for key in ("default_wallpaper", "thread_wallpapers", "has_pin",
                    "use_biometric", "lock_chat_tab", "locked_thread_ids", "presets"):
            assert key in body, f"missing {key} in {body}"
        # Defaults for a brand-new user
        assert body["default_wallpaper"] is None
        assert body["thread_wallpapers"] == {}
        assert body["has_pin"] is False
        assert body["use_biometric"] is False
        assert body["lock_chat_tab"] is False
        assert body["locked_thread_ids"] == []
        # Preset map must include the keys the front-end relies on.
        assert isinstance(body["presets"], dict)
        for k in ("default", "sky", "rose", "slate"):
            assert k in body["presets"], f"missing preset {k}"


# ═══════════════════════════════════════════════════════════════════════════
# 2. PATCH /api/chat/settings/wallpaper
# ═══════════════════════════════════════════════════════════════════════════

class TestWallpaper:
    def test_set_default_preset_sky(self, s, fresh_user):
        r = s.patch(
            f"{BASE_URL}/api/chat/settings/wallpaper",
            headers=_h(fresh_user["token"]),
            json={"default": {"kind": "preset", "value": "sky"}},
        )
        assert r.status_code == 200, r.text
        assert r.json()["default_wallpaper"] == {"kind": "preset", "value": "sky"}
        # GET reflects it
        g = s.get(f"{BASE_URL}/api/chat/settings", headers=_h(fresh_user["token"])).json()
        assert g["default_wallpaper"] == {"kind": "preset", "value": "sky"}

    def test_clear_default(self, s, fresh_user):
        r = s.patch(
            f"{BASE_URL}/api/chat/settings/wallpaper",
            headers=_h(fresh_user["token"]),
            json={"clear_default": True},
        )
        assert r.status_code == 200, r.text
        assert r.json()["default_wallpaper"] is None
        g = s.get(f"{BASE_URL}/api/chat/settings", headers=_h(fresh_user["token"])).json()
        assert g["default_wallpaper"] is None

    def test_set_thread_wallpaper_rose(self, s, fresh_user):
        tid = f"thread-{uuid.uuid4().hex[:8]}"
        r = s.patch(
            f"{BASE_URL}/api/chat/settings/wallpaper",
            headers=_h(fresh_user["token"]),
            json={"thread_wallpapers": {tid: {"kind": "preset", "value": "rose"}}},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["thread_wallpapers"].get(tid) == {"kind": "preset", "value": "rose"}
        # Persistence via GET
        g = s.get(f"{BASE_URL}/api/chat/settings", headers=_h(fresh_user["token"])).json()
        assert g["thread_wallpapers"].get(tid) == {"kind": "preset", "value": "rose"}

    def test_unknown_preset_rejected(self, s, fresh_user):
        r = s.patch(
            f"{BASE_URL}/api/chat/settings/wallpaper",
            headers=_h(fresh_user["token"]),
            json={"default": {"kind": "preset", "value": "banana"}},
        )
        assert r.status_code == 400, r.text
        assert "preset" in r.text.lower()

    def test_clear_per_thread_via_null(self, s, fresh_user):
        # Set then clear a per-thread override (extra-mile coverage for `wp is None`)
        tid = f"thread-clear-{uuid.uuid4().hex[:6]}"
        s.patch(f"{BASE_URL}/api/chat/settings/wallpaper",
                headers=_h(fresh_user["token"]),
                json={"thread_wallpapers": {tid: {"kind": "preset", "value": "sand"}}})
        r = s.patch(f"{BASE_URL}/api/chat/settings/wallpaper",
                    headers=_h(fresh_user["token"]),
                    json={"thread_wallpapers": {tid: None}})
        assert r.status_code == 200, r.text
        assert tid not in (r.json().get("thread_wallpapers") or {})


# ═══════════════════════════════════════════════════════════════════════════
# 3. Chat-lock lifecycle: setup → verify → change → tab → threads → disable
# ═══════════════════════════════════════════════════════════════════════════

class TestChatLockLifecycle:
    def test_01_setup_first_time(self, s, fresh_user):
        r = s.post(f"{BASE_URL}/api/chat/lock/setup",
                   headers=_h(fresh_user["token"]), json={"pin": "1234"})
        assert r.status_code == 200, r.text
        assert r.json()["has_pin"] is True

    def test_02_setup_second_time_rejected(self, s, fresh_user):
        r = s.post(f"{BASE_URL}/api/chat/lock/setup",
                   headers=_h(fresh_user["token"]), json={"pin": "5678"})
        assert r.status_code == 400, r.text
        assert "already" in r.text.lower()

    def test_03_verify_wrong_pin_403(self, s, fresh_user):
        r = s.post(f"{BASE_URL}/api/chat/lock/verify",
                   headers=_h(fresh_user["token"]), json={"pin": "9999"})
        assert r.status_code == 403, r.text

    def test_04_verify_right_pin_200(self, s, fresh_user):
        r = s.post(f"{BASE_URL}/api/chat/lock/verify",
                   headers=_h(fresh_user["token"]), json={"pin": "1234"})
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True}

    def test_05_change_pin(self, s, fresh_user):
        r = s.post(f"{BASE_URL}/api/chat/lock/change",
                   headers=_h(fresh_user["token"]),
                   json={"old_pin": "1234", "new_pin": "987654"})
        assert r.status_code == 200, r.text
        assert r.json()["has_pin"] is True

    def test_06_old_pin_now_invalid(self, s, fresh_user):
        r = s.post(f"{BASE_URL}/api/chat/lock/verify",
                   headers=_h(fresh_user["token"]), json={"pin": "1234"})
        assert r.status_code == 403, r.text

    def test_07_new_pin_works(self, s, fresh_user):
        r = s.post(f"{BASE_URL}/api/chat/lock/verify",
                   headers=_h(fresh_user["token"]), json={"pin": "987654"})
        assert r.status_code == 200, r.text

    def test_08_lock_tab_wrong_pin_403(self, s, fresh_user):
        r = s.patch(f"{BASE_URL}/api/chat/lock/tab",
                    headers=_h(fresh_user["token"]),
                    json={"pin": "000000", "lock_chat_tab": True})
        assert r.status_code == 403, r.text

    def test_09_lock_tab_right_pin_200(self, s, fresh_user):
        r = s.patch(f"{BASE_URL}/api/chat/lock/tab",
                    headers=_h(fresh_user["token"]),
                    json={"pin": "987654", "lock_chat_tab": True})
        assert r.status_code == 200, r.text
        assert r.json()["lock_chat_tab"] is True
        # GET reflects
        g = s.get(f"{BASE_URL}/api/chat/settings", headers=_h(fresh_user["token"])).json()
        assert g["lock_chat_tab"] is True

    def test_10_lock_threads_wrong_pin_403(self, s, fresh_user):
        r = s.patch(f"{BASE_URL}/api/chat/lock/threads",
                    headers=_h(fresh_user["token"]),
                    json={"pin": "111111", "locked_thread_ids": ["t1"]})
        assert r.status_code == 403, r.text

    def test_11_lock_threads_right_pin_200(self, s, fresh_user):
        r = s.patch(f"{BASE_URL}/api/chat/lock/threads",
                    headers=_h(fresh_user["token"]),
                    json={"pin": "987654", "locked_thread_ids": ["t1", "t2"]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["locked_thread_ids"] == ["t1", "t2"]
        g = s.get(f"{BASE_URL}/api/chat/settings", headers=_h(fresh_user["token"])).json()
        assert g["locked_thread_ids"] == ["t1", "t2"]

    def test_12_disable_lock(self, s, fresh_user):
        r = s.post(f"{BASE_URL}/api/chat/lock/disable",
                   headers=_h(fresh_user["token"]), json={"pin": "987654"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["has_pin"] is False
        # Disable also wipes lock_chat_tab + locked_thread_ids per code.
        assert body["lock_chat_tab"] is False
        assert body["locked_thread_ids"] == []

    def test_13_post_disable_verify_400(self, s, fresh_user):
        r = s.post(f"{BASE_URL}/api/chat/lock/verify",
                   headers=_h(fresh_user["token"]), json={"pin": "987654"})
        assert r.status_code == 400, r.text

    def test_14_post_disable_change_403(self, s, fresh_user):
        # No PIN configured → old_pin verify fails → 403 (per route impl).
        r = s.post(f"{BASE_URL}/api/chat/lock/change",
                   headers=_h(fresh_user["token"]),
                   json={"old_pin": "987654", "new_pin": "112233"})
        assert r.status_code == 403, r.text

    def test_15_post_disable_disable_400(self, s, fresh_user):
        r = s.post(f"{BASE_URL}/api/chat/lock/disable",
                   headers=_h(fresh_user["token"]), json={"pin": "987654"})
        assert r.status_code == 400, r.text


# ═══════════════════════════════════════════════════════════════════════════
# 4. /api/admin/maintenance/backfill-approval-status
# ═══════════════════════════════════════════════════════════════════════════

class TestMaintenanceBackfill:
    def test_non_admin_forbidden(self, s, second_user):
        r = s.post(f"{BASE_URL}/api/admin/maintenance/backfill-approval-status",
                   headers=_h(second_user["token"]))
        assert r.status_code == 403, r.text

    def test_super_admin_first_call(self, s, admin_token):
        r = s.post(f"{BASE_URL}/api/admin/maintenance/backfill-approval-status",
                   headers=_h(admin_token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert "copied_from_status" in body
        assert "admin_defaulted" in body
        assert isinstance(body["copied_from_status"], int)
        assert isinstance(body["admin_defaulted"], int)
        # cache for idempotency assert
        pytest.first_copied = body["copied_from_status"]
        pytest.first_admin = body["admin_defaulted"]

    def test_super_admin_second_call_idempotent(self, s, admin_token):
        r = s.post(f"{BASE_URL}/api/admin/maintenance/backfill-approval-status",
                   headers=_h(admin_token))
        assert r.status_code == 200, r.text
        body = r.json()
        # On the second call there must be nothing left to migrate.
        assert body["copied_from_status"] == 0, body
        assert body["admin_defaulted"] == 0, body


# ═══════════════════════════════════════════════════════════════════════════
# 5. Regression: original chat + broadcast still work after backfill
# ═══════════════════════════════════════════════════════════════════════════

class TestRegression:
    def test_chat_threads_list_still_200(self, s, fresh_user):
        r = s.get(f"{BASE_URL}/api/chat/threads", headers=_h(fresh_user["token"]))
        assert r.status_code == 200, r.text
        body = r.json()
        # Endpoint returns {"threads": [...]} (dict envelope, current shape)
        # or — older deployments — a bare list. Accept both for forward-compat.
        if isinstance(body, dict):
            assert "threads" in body and isinstance(body["threads"], list)
        else:
            assert isinstance(body, list)

    def test_broadcast_all_still_201(self, s, admin_token):
        # We don't need fresh recipients because earlier tests / prior runs have
        # left approved users in the DB. The backfill we just ran should ensure
        # any legacy `status` users now ALSO have `approval_status`.
        msg = f"TEST_iter15_regression_{uuid.uuid4().hex[:6]}"
        r = s.post(
            f"{BASE_URL}/api/admin/broadcasts",
            headers=_h(admin_token),
            json={"audience": "all", "title": "Iter15 regression", "message": msg},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body.get("recipient_count", 0) > 0, body
