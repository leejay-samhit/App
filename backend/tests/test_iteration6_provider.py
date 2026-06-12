"""Iteration 6 — Service Provider Availability + Profile-Image backend tests.

Covers:
  * POST/DELETE /api/users/me/profile-image  (base64 upload + clear)
  * GET  /api/auth/me                        (must surface profile_image)
  * PATCH /api/services/me/availability      (provider-only; 400 / 403 paths)
  * GET  /api/services                       (default hides 'offline', explicit filters)
  * GET  /api/services/{provider_id}/profile (returns availability_status + profile_image)
  * GET  /api/admin/service-analytics        (availability buckets sum == total providers)

The pre-existing conftest.py fixtures (base_url, api, admin_token, auth_headers)
are reused. Test providers are inserted directly into Mongo with TEST_* prefix
and cleaned up at the end of the session.
"""
from __future__ import annotations

import base64
import os
import time
import uuid
from typing import Any, Dict, List

import pymongo
import pytest
import requests
from dotenv import load_dotenv
from pathlib import Path

# Load backend .env so MONGO_URL / DB_NAME are available regardless of where pytest is run from.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from conftest import auth_headers  # type: ignore  # noqa: E402

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

TINY_JPEG_B64 = (
    # 1x1 white JPEG (~700 bytes binary) — adequate to pass "data:image/" check
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEB"
    "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/2wBDAQEBAQEBAQEBAQEBAQE"
    "BAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/wA"
    "ARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAr/xAAUEAEAAAAAAAAAAA"
    "AAAAAAAAAA/8QAFAEBAAAAAAAAAAAAAAAAAAAAAP/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2g"
    "AMAwEAAhEDEQA/AL+AB//Z"
)
SMALL_DATA_URI = f"data:image/jpeg;base64,{TINY_JPEG_B64}"
# Generate an oversized base64 string (>1.5 MB) for the 413 path
_OVERSIZED_BYTES = b"A" * 1_600_000
OVERSIZED_DATA_URI = "data:image/jpeg;base64," + base64.b64encode(_OVERSIZED_BYTES).decode()

# Test sentinel — used both as prefix on inserted docs and to identify test data on teardown.
TEST_TAG = f"TEST_I6_{uuid.uuid4().hex[:8]}"


# ------------------------------------------------------------------ fixtures

@pytest.fixture(scope="module")
def mongo_db():
    client = pymongo.MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    db = client[DB_NAME]
    yield db
    client.close()


@pytest.fixture(scope="module")
def provider_user(api, base_url, mongo_db):
    """Create a fresh user via the public register endpoint, then directly
    promote them to an approved service provider in Mongo. Returns
    {id, email, token, password}."""
    email = f"{TEST_TAG}_prov@test.com".lower()
    password = "P@ssw0rd1"
    # Register — backoff on 429 (auth/register is rate-limited to 5/min in prod)
    r = None
    for attempt in range(8):
        r = api.post(f"{base_url}/api/auth/register", json={
            "name": f"{TEST_TAG} Provider",
            "email": email,
            "password": password,
            "phone": f"9{int(time.time())%10000000000:010d}",
        })
        if r.status_code != 429:
            break
        time.sleep(15)
    assert r is not None and r.status_code in (200, 201), f"register failed: {r.status_code} {r.text}"
    body = r.json()
    user_id = body.get("user", {}).get("id") or body.get("id")
    assert user_id, f"no user id in register response: {body}"

    # Promote directly via Mongo so we don't need to drive the full payment + admin-approval flow.
    res = mongo_db.users.update_one(
        {"id": user_id},
        {"$set": {
            "registration_paid": True,
            "is_service_provider": True,
            "service_status": "approved",
            "service_name": f"{TEST_TAG} Services",
            "service_category": "Electrician",
            "service_pincode": "560001",
            "service_charge": 499,
            "service_description": "Test provider for iteration 6",
            "service_approved_at": "2026-01-01T00:00:00",
        }},
    )
    assert res.matched_count == 1, "failed to flip user into service provider"

    # Login to get a token reflecting the new flags
    login = api.post(f"{base_url}/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, f"provider login failed: {login.status_code} {login.text}"
    token = login.json()["token"]
    yield {"id": user_id, "email": email, "password": password, "token": token}

    # Teardown — remove provider
    mongo_db.users.delete_one({"id": user_id})


@pytest.fixture(scope="module")
def regular_user(api, base_url, mongo_db):
    """A non-provider user — used to verify 403 on availability."""
    email = f"{TEST_TAG}_user@test.com".lower()
    password = "P@ssw0rd1"
    r = None
    for attempt in range(8):
        r = api.post(f"{base_url}/api/auth/register", json={
            "name": f"{TEST_TAG} User",
            "email": email,
            "password": password,
            "phone": f"8{int(time.time())%10000000000:010d}",
        })
        if r.status_code != 429:
            break
        time.sleep(15)
    assert r is not None and r.status_code in (200, 201), f"register failed: {r.status_code} {r.text}"
    user_id = r.json().get("user", {}).get("id")
    login = api.post(f"{base_url}/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    token = login.json()["token"]
    yield {"id": user_id, "email": email, "token": token}
    mongo_db.users.delete_one({"id": user_id})


@pytest.fixture(scope="module")
def extra_providers(mongo_db):
    """Seed three additional approved providers with distinct availability statuses
    so the listing-filter tests have predictable data even if the DB has nothing else."""
    docs = []
    statuses = ["available", "busy", "offline"]
    for st in statuses:
        uid = str(uuid.uuid4())
        docs.append({
            "id": uid,
            "name": f"{TEST_TAG} {st.title()} Provider",
            "email": f"{TEST_TAG}_{st}@test.com".lower(),
            "phone": f"7{int(time.time())%10000000000:010d}",
            "password_hash": "x",
            "referral_code": f"T{uid[:5]}",
            "is_service_provider": True,
            "registration_paid": True,
            "service_status": "approved",
            "service_name": f"{TEST_TAG} {st} svc",
            "service_category": "Plumber",
            "service_pincode": "560002",
            "service_charge": 299,
            "service_description": f"Test {st} provider",
            "availability_status": st,
            "service_approved_at": "2026-01-01T00:00:00",
            "created_at": "2026-01-01T00:00:00",
        })
    mongo_db.users.insert_many(docs)
    yield {d["availability_status"]: d for d in docs}
    mongo_db.users.delete_many({"id": {"$in": [d["id"] for d in docs]}})


# ============================================================
# 1) Profile-image upload / delete
# ============================================================
class TestProfileImage:
    def test_upload_small_image_succeeds_and_persists(self, api, base_url, provider_user, mongo_db):
        r = api.post(
            f"{base_url}/api/users/me/profile-image",
            json={"image_data_url": SMALL_DATA_URI},
            headers=auth_headers(provider_user["token"]),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("profile_image") == SMALL_DATA_URI
        assert body.get("profile_image_updated_at"), "missing profile_image_updated_at on response"
        # Verify persisted
        doc = mongo_db.users.find_one({"id": provider_user["id"]}, {"_id": 0, "profile_image": 1})
        assert doc and doc.get("profile_image") == SMALL_DATA_URI

    def test_auth_me_returns_profile_image(self, api, base_url, provider_user):
        r = api.get(f"{base_url}/api/auth/me", headers=auth_headers(provider_user["token"]))
        assert r.status_code == 200, r.text
        assert r.json().get("profile_image") == SMALL_DATA_URI

    def test_upload_rejects_empty_data_uri(self, api, base_url, provider_user):
        r = api.post(
            f"{base_url}/api/users/me/profile-image",
            json={"image_data_url": ""},
            headers=auth_headers(provider_user["token"]),
        )
        assert r.status_code == 400, r.text

    def test_upload_rejects_non_image_data_uri(self, api, base_url, provider_user):
        r = api.post(
            f"{base_url}/api/users/me/profile-image",
            json={"image_data_url": "data:text/plain;base64,SGVsbG8="},
            headers=auth_headers(provider_user["token"]),
        )
        assert r.status_code == 400, r.text

    def test_upload_rejects_oversized_image(self, api, base_url, provider_user):
        r = api.post(
            f"{base_url}/api/users/me/profile-image",
            json={"image_data_url": OVERSIZED_DATA_URI},
            headers=auth_headers(provider_user["token"]),
        )
        assert r.status_code == 413, r.text

    def test_delete_clears_profile_image(self, api, base_url, provider_user, mongo_db):
        r = api.delete(
            f"{base_url}/api/users/me/profile-image",
            headers=auth_headers(provider_user["token"]),
        )
        assert r.status_code == 200, r.text
        # Mongo doc should no longer have profile_image
        doc = mongo_db.users.find_one({"id": provider_user["id"]}, {"_id": 0, "profile_image": 1})
        assert doc is not None
        assert "profile_image" not in doc, f"profile_image still present: {doc}"
        # And /auth/me must not expose it
        me = api.get(f"{base_url}/api/auth/me", headers=auth_headers(provider_user["token"]))
        assert me.status_code == 200
        assert "profile_image" not in me.json() or me.json().get("profile_image") in (None, "")


# ============================================================
# 2) Provider availability PATCH
# ============================================================
class TestAvailabilityPatch:
    def test_non_provider_forbidden(self, api, base_url, regular_user):
        r = api.patch(
            f"{base_url}/api/services/me/availability",
            json={"status": "available"},
            headers=auth_headers(regular_user["token"]),
        )
        assert r.status_code == 403, r.text

    def test_invalid_status_rejected(self, api, base_url, provider_user):
        r = api.patch(
            f"{base_url}/api/services/me/availability",
            json={"status": "vacationing"},
            headers=auth_headers(provider_user["token"]),
        )
        assert r.status_code == 400, r.text

    @pytest.mark.parametrize("status_val", ["available", "busy", "offline"])
    def test_valid_statuses_persist(self, api, base_url, provider_user, mongo_db, status_val):
        r = api.patch(
            f"{base_url}/api/services/me/availability",
            json={"status": status_val},
            headers=auth_headers(provider_user["token"]),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert body.get("availability_status") == status_val
        assert body.get("availability_updated_at")
        # Verify Mongo
        doc = mongo_db.users.find_one(
            {"id": provider_user["id"]},
            {"_id": 0, "availability_status": 1, "availability_updated_at": 1},
        )
        assert doc and doc.get("availability_status") == status_val


# ============================================================
# 3) GET /services availability filter
# ============================================================
def _ids(items: List[Dict[str, Any]]) -> set:
    return {it.get("id") for it in items if it.get("id")}


def _fetch_services(api, base_url, **params) -> List[Dict[str, Any]]:
    r = api.get(f"{base_url}/api/services", params=params)
    assert r.status_code == 200, f"/services failed: {r.status_code} {r.text}"
    data = r.json()
    # Endpoint may return either a list or a dict with `items` — be flexible.
    if isinstance(data, dict):
        return data.get("items") or data.get("results") or []
    return data


class TestListServicesAvailabilityFilter:
    def test_default_hides_offline(self, api, base_url, extra_providers):
        items = _fetch_services(api, base_url)
        ids = _ids(items)
        assert extra_providers["available"]["id"] in ids, "available provider should be visible by default"
        assert extra_providers["busy"]["id"] in ids, "busy provider should be visible by default"
        assert extra_providers["offline"]["id"] not in ids, "offline provider must be HIDDEN by default"

    def test_explicit_offline_filter(self, api, base_url, extra_providers):
        items = _fetch_services(api, base_url, availability="offline")
        ids = _ids(items)
        assert extra_providers["offline"]["id"] in ids
        assert extra_providers["available"]["id"] not in ids
        assert extra_providers["busy"]["id"] not in ids
        # Every returned item must be tagged offline
        for it in items:
            assert it.get("availability_status") == "offline"

    def test_explicit_busy_filter(self, api, base_url, extra_providers):
        items = _fetch_services(api, base_url, availability="busy")
        ids = _ids(items)
        assert extra_providers["busy"]["id"] in ids
        assert extra_providers["available"]["id"] not in ids
        assert extra_providers["offline"]["id"] not in ids
        for it in items:
            assert it.get("availability_status") == "busy"

    def test_explicit_available_filter(self, api, base_url, extra_providers):
        items = _fetch_services(api, base_url, availability="available")
        ids = _ids(items)
        assert extra_providers["available"]["id"] in ids
        assert extra_providers["busy"]["id"] not in ids
        assert extra_providers["offline"]["id"] not in ids
        for it in items:
            assert it.get("availability_status") == "available"


# ============================================================
# 4) GET /services/{id}/profile
# ============================================================
class TestServiceProviderProfile:
    def test_profile_returns_availability_and_profile_image(self, api, base_url, mongo_db, extra_providers, provider_user):
        # Re-upload a profile image on the busy provider directly via Mongo so
        # we can verify both fields surface on /profile in one shot.
        busy_id = extra_providers["busy"]["id"]
        mongo_db.users.update_one(
            {"id": busy_id},
            {"$set": {"profile_image": SMALL_DATA_URI, "profile_image_updated_at": "2026-01-01T00:00:00"}},
        )
        r = api.get(f"{base_url}/api/services/{busy_id}/profile")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("id") == busy_id
        assert body.get("availability_status") == "busy"
        assert body.get("profile_image") == SMALL_DATA_URI

    def test_profile_404_for_unknown(self, api, base_url):
        r = api.get(f"{base_url}/api/services/{uuid.uuid4()}/profile")
        assert r.status_code == 404


# ============================================================
# 5) Admin service-analytics availability sum
# ============================================================
class TestAdminAvailabilityAnalytics:
    def test_buckets_sum_to_total_providers(self, api, base_url, admin_token, mongo_db, extra_providers, provider_user):
        r = api.get(
            f"{base_url}/api/admin/service-analytics",
            headers=auth_headers(admin_token),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        avail = body.get("availability") or {}
        bucket_sum = sum(int(avail.get(k, 0)) for k in ("available", "busy", "offline", "unset"))
        total_providers = mongo_db.users.count_documents({"is_service_provider": True})
        assert bucket_sum == total_providers, (
            f"availability buckets {avail} sum={bucket_sum} != total providers {total_providers}"
        )
