"""Multi-session auth tests (Phase 2 — 2026-06-27).

Covers the fix that lets a user be logged in on multiple devices concurrently
(mobile APK + web slangcart.com + tablet) without one device kicking out the
other. Previously a single `active_session_id` on the user doc was overwritten
on every login → older device's JWT failed get_current_user and returned 401
session_revoked.

Test scenarios (all backend, requires public EXPO_PUBLIC_BACKEND_URL):
  1. Concurrent login — two logins, both access tokens work on /api/auth/me.
  2. Register → login concurrent — register mints token1, then login mints
     token2; both must work.
  3. Single-device logout — token1 logged out → token1=401, token2=200.
  4. Refresh rotation — refresh once, old refresh dead, new access works,
     a second independent login's tokens stay alive.
  5. Slot cap (10) — 12 consecutive logins, oldest 2 evicted, newest 10 OK.
  6. Logout-then-third-login isolation — session1 dead, session2 + new
     session3 both alive.
"""
import os
import uuid
import time
import pytest
import requests
from pathlib import Path
from dotenv import load_dotenv

# Reuse conftest env loading conventions
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
_fe_env = Path(__file__).resolve().parents[2] / "frontend" / ".env"
if _fe_env.exists():
    load_dotenv(_fe_env, override=False)

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
ALICE_EMAIL = "test_alice_73dc7f@test.com"
ALICE_PASS = "Passw0rd!"


# ────────────────────────── helpers ─────────────────────────────
def _login(email: str, password: str):
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=20,
    )
    return r


def _me(token: str):
    return requests.get(
        f"{BASE_URL}/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )


def _logout(token: str):
    return requests.post(
        f"{BASE_URL}/api/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )


def _refresh(refresh_token: str):
    return requests.post(
        f"{BASE_URL}/api/auth/refresh",
        json={"refresh_token": refresh_token},
        timeout=20,
    )


def _register(email: str, password: str, name: str = "Test User"):
    return requests.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": email, "password": password, "name": name},
        timeout=30,
    )


# ─────────────────────── tests ──────────────────────────────────

class TestConcurrentLogin:
    """PRIMARY: two simultaneous logins on the same account must both stay valid."""

    def test_two_logins_both_tokens_work(self):
        r1 = _login(ALICE_EMAIL, ALICE_PASS)
        assert r1.status_code == 200, f"login1: {r1.status_code} {r1.text}"
        token1 = r1.json()["token"]

        r2 = _login(ALICE_EMAIL, ALICE_PASS)
        assert r2.status_code == 200, f"login2: {r2.status_code} {r2.text}"
        token2 = r2.json()["token"]

        # Both tokens MUST work — this was broken before fix.
        m1 = _me(token1)
        m2 = _me(token2)
        assert m1.status_code == 200, (
            f"REGRESSION: first login token returned {m1.status_code} after "
            f"second login. Response: {m1.text}"
        )
        assert m2.status_code == 200, f"second login token failed: {m2.text}"
        assert m1.json()["email"] == ALICE_EMAIL
        assert m2.json()["email"] == ALICE_EMAIL


class TestRegisterThenLogin:
    """PRIMARY: register flow's token must coexist with a subsequent login."""

    def test_register_then_login_both_work(self):
        # Unique throwaway account
        email = f"test_multisession_{uuid.uuid4().hex[:8]}@test.com"
        password = "Passw0rd!"
        reg = _register(email, password)
        assert reg.status_code == 200, f"register: {reg.status_code} {reg.text}"
        token_reg = reg.json()["token"]

        login = _login(email, password)
        assert login.status_code == 200, f"login: {login.status_code} {login.text}"
        token_login = login.json()["token"]

        # Both must be alive
        m_reg = _me(token_reg)
        m_login = _me(token_login)
        assert m_reg.status_code == 200, (
            f"REGRESSION: register-time token returned {m_reg.status_code} "
            f"after a subsequent login. Response: {m_reg.text}"
        )
        assert m_login.status_code == 200, f"login token failed: {m_login.text}"


class TestSingleDeviceLogout:
    """Logging out one device must not kick the other."""

    def test_logout_token1_only_kills_token1(self):
        t1 = _login(ALICE_EMAIL, ALICE_PASS).json()["token"]
        t2 = _login(ALICE_EMAIL, ALICE_PASS).json()["token"]

        # Confirm both live
        assert _me(t1).status_code == 200
        assert _me(t2).status_code == 200

        # Logout device 1
        lo = _logout(t1)
        assert lo.status_code == 200, f"logout: {lo.status_code} {lo.text}"

        # device 1 dead, device 2 alive
        r1 = _me(t1)
        r2 = _me(t2)
        assert r1.status_code == 401, f"expected 401, got {r1.status_code} {r1.text}"
        assert r1.json().get("detail") == "session_revoked"
        assert r2.status_code == 200, (
            f"REGRESSION: device-2 token died after device-1 logout. "
            f"{r2.status_code} {r2.text}"
        )


class TestRefreshRotation:
    """Refresh: old refresh dies, new access works, second session unaffected."""

    def test_refresh_rotates_only_caller_slot(self):
        r1 = _login(ALICE_EMAIL, ALICE_PASS).json()
        r2 = _login(ALICE_EMAIL, ALICE_PASS).json()
        access1, refresh1 = r1["token"], r1["refresh_token"]
        access2, refresh2 = r2["token"], r2["refresh_token"]

        # Rotate session 1
        rot = _refresh(refresh1)
        assert rot.status_code == 200, f"refresh: {rot.status_code} {rot.text}"
        new_access1 = rot.json()["token"]
        new_refresh1 = rot.json()["refresh_token"]
        assert new_access1 != access1
        assert new_refresh1 != refresh1

        # Old refresh1 must now be revoked (sid no longer in active set).
        old_again = _refresh(refresh1)
        assert old_again.status_code == 401, (
            f"old refresh should be dead; got {old_again.status_code} {old_again.text}"
        )

        # New access1 works
        m = _me(new_access1)
        assert m.status_code == 200, f"new access failed: {m.status_code} {m.text}"

        # Session 2 (independent) MUST still work
        m2 = _me(access2)
        assert m2.status_code == 200, (
            f"REGRESSION: independent session died during another session's "
            f"refresh. {m2.status_code} {m2.text}"
        )
        # And session 2's refresh still works
        rot2 = _refresh(refresh2)
        assert rot2.status_code == 200, f"session-2 refresh failed: {rot2.text}"


class TestSlotCap:
    """Spawn 12 logins → oldest 2 evicted, newest 10 alive."""

    def test_oldest_evicted_after_cap(self):
        tokens = []
        # /auth/login is rate-limited to 10/minute (slowapi, per-IP). To do 12
        # consecutive logins in one test we must space them out > 6 s apart so
        # any 60-second rolling window holds < 10 calls. 7 s buffer is safe.
        for i in range(12):
            r = _login(ALICE_EMAIL, ALICE_PASS)
            assert r.status_code == 200, (
                f"login[{i}] failed: {r.status_code} {r.text} "
                f"(rate-limit hit? check 10/minute on /auth/login)"
            )
            tokens.append(r.json()["token"])
            if i < 11:
                time.sleep(7)

        # Oldest 2 should be evicted
        for i, t in enumerate(tokens[:2]):
            res = _me(t)
            assert res.status_code == 401, (
                f"slot[{i}] expected 401 (evicted), got {res.status_code} {res.text}"
            )
            assert res.json().get("detail") == "session_revoked"

        # Newest 10 should be alive
        for i, t in enumerate(tokens[2:]):
            res = _me(t)
            assert res.status_code == 200, (
                f"slot[{i+2}] expected 200, got {res.status_code} {res.text}"
            )


class TestLogoutThirdLoginIsolation:
    """After logout(s1) + new login(s3), s1 dead while s2 + s3 alive."""

    def test_revoked_session_stays_dead_after_new_login(self):
        s1 = _login(ALICE_EMAIL, ALICE_PASS).json()["token"]
        s2 = _login(ALICE_EMAIL, ALICE_PASS).json()["token"]
        assert _logout(s1).status_code == 200
        s3 = _login(ALICE_EMAIL, ALICE_PASS).json()["token"]

        r1 = _me(s1)
        r2 = _me(s2)
        r3 = _me(s3)
        assert r1.status_code == 401, f"s1 should stay dead: {r1.status_code} {r1.text}"
        assert r2.status_code == 200, f"s2 must be alive: {r2.status_code} {r2.text}"
        assert r3.status_code == 200, f"s3 must be alive: {r3.status_code} {r3.text}"


class TestLegacyTokenBackwardCompat:
    """A token with NO sid claim should be accepted ONLY when the user has no
    session model populated. We can't easily mint such a token without the JWT
    secret, but we can confirm a real logged-in user with an sid token rejects
    tampered no-sid behaviour — covered indirectly by the multi-session tests.

    This test verifies the documented behaviour: when a user has active sids
    AND a token without sid is presented, it must be 401. We forge such a
    request by stripping the sid claim from a real token via the JWT_SECRET.
    """

    def test_no_sid_token_rejected_when_user_has_active_sessions(self):
        # Try to read JWT_SECRET from backend env (best-effort; skip if absent).
        secret = os.environ.get("JWT_SECRET")
        algo = os.environ.get("JWT_ALGORITHM", "HS256")
        if not secret:
            pytest.skip("JWT_SECRET not available to test runner; skipping legacy-token forgery test")

        import jwt
        from datetime import datetime, timezone, timedelta

        # Login to create an active session
        r = _login(ALICE_EMAIL, ALICE_PASS)
        assert r.status_code == 200
        user = r.json()["user"]
        # Forge a no-sid access token
        now = datetime.now(timezone.utc)
        legacy_payload = {
            "sub": user["id"],
            "email": user["email"],
            "role": user.get("role", "user"),
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "type": "access",
        }
        legacy_token = jwt.encode(legacy_payload, secret, algorithm=algo)
        res = _me(legacy_token)
        assert res.status_code == 401, (
            f"legacy no-sid token should be rejected once user has active sids; "
            f"got {res.status_code} {res.text}"
        )
        assert res.json().get("detail") == "session_revoked"
