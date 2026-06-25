"""Iteration 11 — Profile Picture Privacy (Group 8 + privacy module).

Tests:
  • GET    /api/users/me/privacy
  • PATCH  /api/users/me/privacy
  • POST   /api/users/me/profile-image (stamps profile_visibility)
  • routes.privacy.is_public_account / can_view_profile_image semantics

Service Providers and Vendors are HARD-LOCKED to "everyone" — the backend
must coerce any other value on write and on read.
"""
import os
import sys
import uuid
import asyncio
from pathlib import Path

import pytest
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

# Allow importing routes.privacy directly for unit-style checks
_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
load_dotenv(_BACKEND / ".env")

from routes import privacy as privacy_module  # noqa: E402

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

_mclient = MongoClient(MONGO_URL)
_mdb = _mclient[DB_NAME]


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────
def _h(token: str):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _register(email: str, name: str, password: str = "Test@1234", referral_code: str | None = None) -> str:
    """Register a user via the public API and return the new user_id."""
    body = {"email": email, "name": name, "password": password, "phone": f"+91{uuid.uuid4().int % 10**10:010d}"}
    if referral_code:
        body["referral_code"] = referral_code
    r = requests.post(f"{BASE_URL}/api/auth/register", json=body, timeout=30)
    assert r.status_code in (200, 201), f"register failed: {r.status_code} {r.text}"
    data = r.json()
    return data.get("user", {}).get("id") or data.get("id")


def _login(email: str, password: str = "Test@1234") -> str:
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["token"]


def _force_approved(user_id: str, **extra):
    """Flip a fresh user to approved so /users/me endpoints behave normally."""
    upd = {
        "approval_status": "approved",
        "registration_paid": True,
        "is_blocked": False,
    }
    upd.update(extra)
    _mdb.users.update_one({"id": user_id}, {"$set": upd})


def _get_user_doc(user_id: str) -> dict:
    return _mdb.users.find_one({"id": user_id}, {"_id": 0}) or {}


def _cleanup_email(email: str):
    _mdb.users.delete_many({"email": email})


# ──────────────────────────────────────────────────────────────────────
# Fixtures — build a downline chain A → B → C, plus an SP, a Vendor.
# ──────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def users():
    tag = uuid.uuid4().hex[:8]
    emails = {
        "A": f"test_priv_a_{tag}@example.com",
        "B": f"test_priv_b_{tag}@example.com",
        "C": f"test_priv_c_{tag}@example.com",
        "SP": f"test_priv_sp_{tag}@example.com",
        "V": f"test_priv_v_{tag}@example.com",
        "X": f"test_priv_x_{tag}@example.com",  # unrelated viewer
    }

    # Register A (no referral → admin sponsor)
    a_id = _register(emails["A"], "Privacy A")
    _force_approved(a_id)
    a_doc = _get_user_doc(a_id)
    a_ref = a_doc.get("referral_code")
    assert a_ref, "A should have referral_code"

    # Register B using A's referral_code (placement under A)
    b_id = _register(emails["B"], "Privacy B", referral_code=a_ref)
    _force_approved(b_id)
    # Force sponsor_id of B to A (spillover only fires when A has payouts_received >= 1, which it doesn't)
    _mdb.users.update_one({"id": b_id}, {"$set": {"sponsor_id": a_id}})
    b_doc = _get_user_doc(b_id)
    b_ref = b_doc.get("referral_code")

    # Register C under B
    c_id = _register(emails["C"], "Privacy C", referral_code=b_ref)
    _force_approved(c_id)
    _mdb.users.update_one({"id": c_id}, {"$set": {"sponsor_id": b_id}})

    # Register SP and flip to service provider approved
    sp_id = _register(emails["SP"], "Privacy SP")
    _force_approved(sp_id, is_service_provider=True, service_status="approved")

    # Register Vendor and flip to vendor approved
    v_id = _register(emails["V"], "Privacy V")
    _force_approved(v_id, is_vendor=True, vendor_status="approved")

    # Register unrelated viewer X
    x_id = _register(emails["X"], "Privacy X")
    _force_approved(x_id)
    # Spillover BFS may have placed X somewhere under A's chain. Force X to
    # have NO sponsor (outside A's downline) so downline checks against A
    # correctly return False.
    _mdb.users.update_one({"id": x_id}, {"$set": {"sponsor_id": None}})

    tokens = {
        "A":  _login(emails["A"]),
        "B":  _login(emails["B"]),
        "C":  _login(emails["C"]),
        "SP": _login(emails["SP"]),
        "V":  _login(emails["V"]),
        "X":  _login(emails["X"]),
    }
    ids = {"A": a_id, "B": b_id, "C": c_id, "SP": sp_id, "V": v_id, "X": x_id}

    yield {"emails": emails, "tokens": tokens, "ids": ids}

    # Teardown
    for em in emails.values():
        _cleanup_email(em)
    _mdb.chat_threads.delete_many({"participants": {"$all": [a_id]}})


# ──────────────────────────────────────────────────────────────────────
# GET /users/me/privacy
# ──────────────────────────────────────────────────────────────────────
class TestGetPrivacy:
    def test_normal_user_not_locked(self, users):
        r = requests.get(f"{BASE_URL}/api/users/me/privacy", headers=_h(users["tokens"]["A"]))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["locked"] is False
        assert body["locked_reason"] is None
        assert body["profile_visibility"] in {"everyone", "downline", "accepted_requests"}
        assert isinstance(body["options"], list) and len(body["options"]) == 3
        vals = {o["value"] for o in body["options"]}
        assert vals == {"everyone", "downline", "accepted_requests"}

    def test_service_provider_locked_to_everyone(self, users):
        # Even if we tamper with the DB to set a non-public visibility, GET must coerce.
        _mdb.users.update_one({"id": users["ids"]["SP"]}, {"$set": {"profile_visibility": "downline"}})
        r = requests.get(f"{BASE_URL}/api/users/me/privacy", headers=_h(users["tokens"]["SP"]))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["locked"] is True
        assert isinstance(body["locked_reason"], str) and len(body["locked_reason"]) > 0
        assert body["profile_visibility"] == "everyone"

    def test_vendor_locked_to_everyone(self, users):
        _mdb.users.update_one({"id": users["ids"]["V"]}, {"$set": {"profile_visibility": "accepted_requests"}})
        r = requests.get(f"{BASE_URL}/api/users/me/privacy", headers=_h(users["tokens"]["V"]))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["locked"] is True
        assert body["locked_reason"]
        assert body["profile_visibility"] == "everyone"


# ──────────────────────────────────────────────────────────────────────
# PATCH /users/me/privacy
# ──────────────────────────────────────────────────────────────────────
class TestPatchPrivacy:
    def test_normal_user_set_downline(self, users):
        r = requests.patch(
            f"{BASE_URL}/api/users/me/privacy",
            json={"profile_visibility": "downline"},
            headers=_h(users["tokens"]["A"]),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["profile_visibility"] == "downline"
        assert body["locked"] is False
        # Persistence
        assert _get_user_doc(users["ids"]["A"])["profile_visibility"] == "downline"

    def test_normal_user_set_accepted_requests(self, users):
        r = requests.patch(
            f"{BASE_URL}/api/users/me/privacy",
            json={"profile_visibility": "accepted_requests"},
            headers=_h(users["tokens"]["A"]),
        )
        assert r.status_code == 200, r.text
        assert r.json()["profile_visibility"] == "accepted_requests"

    def test_normal_user_set_everyone(self, users):
        r = requests.patch(
            f"{BASE_URL}/api/users/me/privacy",
            json={"profile_visibility": "everyone"},
            headers=_h(users["tokens"]["A"]),
        )
        assert r.status_code == 200, r.text
        assert r.json()["profile_visibility"] == "everyone"

    def test_invalid_value_returns_400(self, users):
        r = requests.patch(
            f"{BASE_URL}/api/users/me/privacy",
            json={"profile_visibility": "nobody"},
            headers=_h(users["tokens"]["A"]),
        )
        assert r.status_code == 400, r.text

    def test_service_provider_override_to_everyone(self, users):
        # Client tries to hide SP's pic — backend must coerce to "everyone".
        r = requests.patch(
            f"{BASE_URL}/api/users/me/privacy",
            json={"profile_visibility": "downline"},
            headers=_h(users["tokens"]["SP"]),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["locked"] is True
        assert body["profile_visibility"] == "everyone"
        # DB must also show "everyone"
        assert _get_user_doc(users["ids"]["SP"])["profile_visibility"] == "everyone"

    def test_vendor_override_to_everyone(self, users):
        r = requests.patch(
            f"{BASE_URL}/api/users/me/privacy",
            json={"profile_visibility": "accepted_requests"},
            headers=_h(users["tokens"]["V"]),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["locked"] is True
        assert body["profile_visibility"] == "everyone"
        assert _get_user_doc(users["ids"]["V"])["profile_visibility"] == "everyone"


# ──────────────────────────────────────────────────────────────────────
# POST /users/me/profile-image — stamps profile_visibility
# ──────────────────────────────────────────────────────────────────────
# 1x1 transparent PNG data URI
_TINY_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


class TestProfileImageStampsVisibility:
    def test_normal_user_keeps_or_defaults_visibility(self, users):
        # Reset A's visibility
        _mdb.users.update_one({"id": users["ids"]["A"]}, {"$unset": {"profile_visibility": ""}})
        r = requests.post(
            f"{BASE_URL}/api/users/me/profile-image",
            json={"image_data_url": _TINY_PNG},
            headers=_h(users["tokens"]["A"]),
        )
        assert r.status_code == 200, r.text
        doc = _get_user_doc(users["ids"]["A"])
        assert doc.get("profile_visibility") in {"everyone", "downline", "accepted_requests"}
        assert doc.get("profile_image", "").startswith("data:image/")

    def test_service_provider_visibility_forced_to_everyone_on_upload(self, users):
        # Tamper: try to leave SP with a non-public value first
        _mdb.users.update_one({"id": users["ids"]["SP"]}, {"$set": {"profile_visibility": "downline"}})
        r = requests.post(
            f"{BASE_URL}/api/users/me/profile-image",
            json={"image_data_url": _TINY_PNG},
            headers=_h(users["tokens"]["SP"]),
        )
        assert r.status_code == 200, r.text
        doc = _get_user_doc(users["ids"]["SP"])
        assert doc.get("profile_visibility") == "everyone"
        assert doc.get("profile_image", "").startswith("data:image/")


# ──────────────────────────────────────────────────────────────────────
# Module-level semantics — is_public_account / can_view_profile_image
# ──────────────────────────────────────────────────────────────────────
class TestIsPublicAccount:
    def test_service_provider_flag_true(self):
        assert privacy_module.is_public_account({"is_service_provider": True}) is True

    def test_service_status_approved_true(self):
        assert privacy_module.is_public_account({"service_status": "approved"}) is True

    def test_vendor_requires_both_flag_and_approved(self):
        assert privacy_module.is_public_account({"is_vendor": True, "vendor_status": "approved"}) is True
        assert privacy_module.is_public_account({"is_vendor": True}) is False
        assert privacy_module.is_public_account({"vendor_status": "approved"}) is False

    def test_normal_user_false(self):
        assert privacy_module.is_public_account({"id": "u1"}) is False

    def test_empty_or_none(self):
        assert privacy_module.is_public_account({}) is False
        assert privacy_module.is_public_account(None) is False


class TestCanViewProfileImage:
    """Use a SHARED event loop because motor's AsyncIOMotorClient (db handle in
    core.db) is bound to whichever loop first touches it. Using asyncio.run()
    per-call would close that loop and the next call raises 'Event loop is
    closed'. Instead we keep one loop alive for the whole class."""

    @classmethod
    def setup_class(cls):
        cls._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(cls._loop)

    @classmethod
    def teardown_class(cls):
        cls._loop.close()

    def _run(self, coro):
        return self._loop.run_until_complete(coro)

    def test_own_profile_always_visible(self):
        target = {"id": "u1", "profile_visibility": "downline"}
        assert self._run(privacy_module.can_view_profile_image("u1", target)) is True

    def test_sp_target_always_visible(self):
        target = {"id": "sp1", "is_service_provider": True, "profile_visibility": "downline"}
        assert self._run(privacy_module.can_view_profile_image("anyone", target)) is True

    def test_vendor_target_always_visible(self):
        target = {"id": "v1", "is_vendor": True, "vendor_status": "approved", "profile_visibility": "downline"}
        assert self._run(privacy_module.can_view_profile_image("anyone", target)) is True

    def test_everyone_visible_to_all(self):
        target = {"id": "u1", "profile_visibility": "everyone"}
        assert self._run(privacy_module.can_view_profile_image("u2", target)) is True

    def test_missing_visibility_defaults_to_everyone(self):
        target = {"id": "u1"}
        assert self._run(privacy_module.can_view_profile_image("u2", target)) is True

    def test_downline_grants_descendant(self, users):
        # C is a descendant of A (A → B → C). Set A's visibility to downline.
        a_id, c_id = users["ids"]["A"], users["ids"]["C"]
        _mdb.users.update_one({"id": a_id}, {"$set": {"profile_visibility": "downline"}})
        target = _get_user_doc(a_id)
        target["id"] = a_id  # ensure id present
        assert self._run(privacy_module.can_view_profile_image(c_id, target)) is True

    def test_downline_denies_non_descendant(self, users):
        a_id, x_id = users["ids"]["A"], users["ids"]["X"]
        _mdb.users.update_one({"id": a_id}, {"$set": {"profile_visibility": "downline"}})
        target = _get_user_doc(a_id)
        target["id"] = a_id
        assert self._run(privacy_module.can_view_profile_image(x_id, target)) is False

    def test_downline_denies_anonymous(self, users):
        a_id = users["ids"]["A"]
        _mdb.users.update_one({"id": a_id}, {"$set": {"profile_visibility": "downline"}})
        target = _get_user_doc(a_id)
        target["id"] = a_id
        assert self._run(privacy_module.can_view_profile_image(None, target)) is False

    def test_accepted_requests_grants_with_thread(self, users):
        a_id, x_id = users["ids"]["A"], users["ids"]["X"]
        _mdb.users.update_one({"id": a_id}, {"$set": {"profile_visibility": "accepted_requests"}})
        parts = sorted([a_id, x_id])
        thread_id = f"thr_{uuid.uuid4().hex[:10]}"
        _mdb.chat_threads.insert_one({"id": thread_id, "participants": parts})
        try:
            target = _get_user_doc(a_id)
            target["id"] = a_id
            assert self._run(privacy_module.can_view_profile_image(x_id, target)) is True
        finally:
            _mdb.chat_threads.delete_one({"id": thread_id})

    def test_accepted_requests_denies_without_thread(self, users):
        a_id, x_id = users["ids"]["A"], users["ids"]["X"]
        _mdb.users.update_one({"id": a_id}, {"$set": {"profile_visibility": "accepted_requests"}})
        # Make sure no thread exists
        _mdb.chat_threads.delete_many({"participants": sorted([a_id, x_id])})
        target = _get_user_doc(a_id)
        target["id"] = a_id
        assert self._run(privacy_module.can_view_profile_image(x_id, target)) is False
