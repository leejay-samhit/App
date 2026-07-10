"""Iteration 46 — T&C acceptance gate on Vendor + Service-Provider onboarding.

Covers:
  * POST /api/vendor/apply with/without accepted_terms (happy path + legacy + invalid role)
  * GET  /api/vendor/me/status — persistence of accepted_terms
  * GET  /api/admin/vendor-applications — admin visibility
  * POST /api/service/apply with/without accepted_terms (happy path + legacy + role
    "vendor" allowed at endpoint level per spec)
  * GET  /api/service/me — persistence
  * GET  /api/admin/service-applications — admin visibility
  * GET  /api/admin/settings — 200 even without `onboarding_terms` key (fallback path)
  * PUT  /api/admin/settings — optional round-trip for onboarding_terms
"""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import pymongo
import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from conftest import auth_headers  # type: ignore  # noqa: E402

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

TEST_TAG = f"TEST_I46_{uuid.uuid4().hex[:8]}"

VENDOR_TITLE = "Vendor Declaration & GST Compliance Agreement"
SERVICE_TITLE = "Service Provider Declaration & Compliance Agreement"


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------------- fixtures

@pytest.fixture(scope="module")
def mongo_db():
    client = pymongo.MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    db = client[DB_NAME]
    yield db
    # Teardown — delete anything we created
    try:
        db.users.delete_many({"email": {"$regex": f"^{TEST_TAG.lower()}"}})
        db.vendor_applications.delete_many({"user_email": {"$regex": f"^{TEST_TAG.lower()}"}})
        db.service_applications.delete_many({"email": {"$regex": f"^{TEST_TAG.lower()}"}})
    except Exception:
        pass
    client.close()


def _register_and_promote(api, base_url, mongo_db, tag_suffix: str, extra_flags: Dict[str, Any]):
    email = f"{TEST_TAG.lower()}_{tag_suffix}@test.com"
    password = "P@ssw0rd1"
    r = None
    for attempt in range(8):
        r = api.post(f"{base_url}/api/auth/register", json={
            "name": f"{TEST_TAG} {tag_suffix}",
            "email": email,
            "password": password,
            "phone": f"9{int(time.time() * 1000) % 10000000000:010d}",
        })
        if r.status_code != 429:
            break
        time.sleep(15)
    assert r is not None and r.status_code in (200, 201), f"register failed: {r.status_code} {r.text}"
    user_id = r.json().get("user", {}).get("id") or r.json().get("id")
    assert user_id, f"no user id in register: {r.text}"

    base_flags = {"registration_paid": True, "approval_status": "approved"}
    base_flags.update(extra_flags)
    mongo_db.users.update_one({"id": user_id}, {"$set": base_flags})

    login = api.post(f"{base_url}/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, f"login failed: {login.status_code} {login.text}"
    return {"id": user_id, "email": email, "token": login.json()["token"]}


@pytest.fixture(scope="module")
def vendor_user(api, base_url, mongo_db):
    return _register_and_promote(api, base_url, mongo_db, "vendor", {})


@pytest.fixture(scope="module")
def vendor_legacy_user(api, base_url, mongo_db):
    return _register_and_promote(api, base_url, mongo_db, "vendorlegacy", {})


@pytest.fixture(scope="module")
def vendor_invalid_user(api, base_url, mongo_db):
    return _register_and_promote(api, base_url, mongo_db, "vendorinvalid", {})


@pytest.fixture(scope="module")
def service_user(api, base_url, mongo_db):
    return _register_and_promote(api, base_url, mongo_db, "svc", {})


@pytest.fixture(scope="module")
def service_legacy_user(api, base_url, mongo_db):
    return _register_and_promote(api, base_url, mongo_db, "svclegacy", {})


@pytest.fixture(scope="module")
def service_role_vendor_user(api, base_url, mongo_db):
    return _register_and_promote(api, base_url, mongo_db, "svcrolevendor", {})


# ============================================================ VENDOR TESTS

class TestVendorApplyTerms:
    """POST /api/vendor/apply with accepted_terms audit block."""

    def test_1_happy_path_with_accepted_terms(self, api, base_url, vendor_user):
        accepted_at = iso_now()
        payload = {
            "shop_name": f"{TEST_TAG} Vendor Shop",
            "gst_number": "22AAAAA0000A1Z5",
            "pan_number": "AAAAA1111A",
            "bank_name": "SBI",
            "bank_account": "000123456789",
            "bank_ifsc": "SBIN0000001",
            "description": "iteration 46 vendor test",
            "accepted_terms": {
                "role": "vendor",
                "version": "1.0.0",
                "accepted_at": accepted_at,
                "title": VENDOR_TITLE,
            },
        }
        r = api.post(f"{base_url}/api/vendor/apply", json=payload,
                     headers=auth_headers(vendor_user["token"]))
        assert r.status_code == 200, f"vendor apply failed: {r.status_code} {r.text}"
        body = r.json()
        assert body.get("ok") is True
        app_doc = body.get("application")
        assert app_doc is not None, "application missing from response"
        at = app_doc.get("accepted_terms")
        assert at is not None, "accepted_terms missing from returned application"
        assert at.get("role") == "vendor"
        assert at.get("version") == "1.0.0"
        assert at.get("accepted_at") == accepted_at
        assert at.get("title") == VENDOR_TITLE

    def test_2_legacy_no_accepted_terms(self, api, base_url, vendor_legacy_user):
        payload = {
            "shop_name": f"{TEST_TAG} Legacy Shop",
            "gst_number": "",
            "pan_number": "",
        }
        r = api.post(f"{base_url}/api/vendor/apply", json=payload,
                     headers=auth_headers(vendor_legacy_user["token"]))
        assert r.status_code == 200, f"legacy vendor apply failed: {r.status_code} {r.text}"
        body = r.json()
        assert body.get("application", {}).get("accepted_terms") is None, \
            "legacy client should get accepted_terms == null"

    def test_3_invalid_role_rejected(self, api, base_url, vendor_invalid_user):
        payload = {
            "shop_name": f"{TEST_TAG} Invalid Role Shop",
            "accepted_terms": {
                "role": "buyer",
                "version": "1.0.0",
                "accepted_at": iso_now(),
                "title": VENDOR_TITLE,
            },
        }
        r = api.post(f"{base_url}/api/vendor/apply", json=payload,
                     headers=auth_headers(vendor_invalid_user["token"]))
        assert r.status_code == 422, \
            f"invalid role should be 422, got {r.status_code}: {r.text}"

    def test_4_persistence_via_status(self, api, base_url, vendor_user):
        r = api.get(f"{base_url}/api/vendor/me/status",
                    headers=auth_headers(vendor_user["token"]))
        assert r.status_code == 200, f"vendor status failed: {r.status_code} {r.text}"
        app_doc = r.json().get("application")
        assert app_doc is not None, "application missing from status"
        at = app_doc.get("accepted_terms")
        assert at is not None, "accepted_terms missing from persisted app"
        assert at.get("role") == "vendor"
        assert at.get("version") == "1.0.0"
        assert at.get("title") == VENDOR_TITLE

    def test_5_admin_visibility(self, api, base_url, admin_token, vendor_user):
        # Fetch pending vendor apps as admin
        r = api.get(f"{base_url}/api/admin/vendor-applications?status=pending",
                    headers=auth_headers(admin_token))
        assert r.status_code == 200, f"admin list failed: {r.status_code} {r.text}"
        items = r.json().get("items") or []
        mine = next((a for a in items if a.get("user_id") == vendor_user["id"]), None)
        assert mine is not None, "vendor application not visible to admin"
        at = mine.get("accepted_terms")
        assert at is not None, "accepted_terms missing in admin listing"
        assert at.get("role") == "vendor"
        assert at.get("title") == VENDOR_TITLE


# ============================================================ SERVICE TESTS

class TestServiceApplyTerms:
    """POST /api/service/apply with accepted_terms."""

    def test_6_happy_path_with_accepted_terms(self, api, base_url, service_user):
        accepted_at = iso_now()
        payload = {
            "service_name": f"{TEST_TAG} Service Listing",
            "service_category": "Electrician",
            "pincode": "560001",
            "charge": 499,
            "description": "iteration 46 service test",
            "accepted_terms": {
                "role": "service_provider",
                "version": "1.0.0",
                "accepted_at": accepted_at,
                "title": SERVICE_TITLE,
            },
        }
        r = api.post(f"{base_url}/api/service/apply", json=payload,
                     headers=auth_headers(service_user["token"]))
        assert r.status_code == 200, f"service apply failed: {r.status_code} {r.text}"
        body = r.json()
        assert body.get("ok") is True
        app_doc = body.get("application")
        assert app_doc is not None, "application missing"
        at = app_doc.get("accepted_terms")
        assert at is not None
        assert at.get("role") == "service_provider"
        assert at.get("version") == "1.0.0"
        assert at.get("accepted_at") == accepted_at
        assert at.get("title") == SERVICE_TITLE

    def test_7_legacy_no_accepted_terms(self, api, base_url, service_legacy_user):
        payload = {
            "service_name": f"{TEST_TAG} Legacy Service",
            "service_category": "Plumber",
            "pincode": "560002",
            "charge": 299,
        }
        r = api.post(f"{base_url}/api/service/apply", json=payload,
                     headers=auth_headers(service_legacy_user["token"]))
        assert r.status_code == 200, f"legacy service apply failed: {r.status_code} {r.text}"
        assert r.json().get("application", {}).get("accepted_terms") is None

    def test_8_role_vendor_still_accepted_at_endpoint(self, api, base_url, service_role_vendor_user):
        """Spec: regex only enforces membership, so role='vendor' on /service/apply
        is intentionally allowed (title tells the story)."""
        payload = {
            "service_name": f"{TEST_TAG} Cross Role Service",
            "service_category": "Tutor",
            "pincode": "560003",
            "charge": 799,
            "accepted_terms": {
                "role": "vendor",  # cross-role allowed by AcceptedTermsBlock regex
                "version": "1.0.0",
                "accepted_at": iso_now(),
                "title": SERVICE_TITLE,
            },
        }
        r = api.post(f"{base_url}/api/service/apply", json=payload,
                     headers=auth_headers(service_role_vendor_user["token"]))
        assert r.status_code == 200, \
            f"role='vendor' on /service/apply should be accepted (200), got {r.status_code}: {r.text}"
        at = r.json().get("application", {}).get("accepted_terms")
        assert at is not None and at.get("role") == "vendor"

    def test_9a_service_persistence(self, api, base_url, service_user):
        r = api.get(f"{base_url}/api/service/me",
                    headers=auth_headers(service_user["token"]))
        assert r.status_code == 200, f"/service/me failed: {r.status_code} {r.text}"
        app_doc = r.json().get("application")
        assert app_doc is not None, "application missing from /service/me"
        at = app_doc.get("accepted_terms")
        assert at is not None, "accepted_terms missing from persisted service app"
        assert at.get("role") == "service_provider"
        assert at.get("title") == SERVICE_TITLE

    def test_9b_admin_visibility(self, api, base_url, admin_token, service_user):
        r = api.get(f"{base_url}/api/admin/service-applications?status=pending",
                    headers=auth_headers(admin_token))
        assert r.status_code == 200, f"admin list failed: {r.status_code} {r.text}"
        items = r.json().get("items") or []
        mine = next((a for a in items if a.get("user_id") == service_user["id"]), None)
        assert mine is not None, "service application not visible to admin"
        at = mine.get("accepted_terms")
        assert at is not None, "accepted_terms missing in admin listing"
        assert at.get("role") == "service_provider"
        assert at.get("title") == SERVICE_TITLE


# ============================================================ SETTINGS FALLBACK

class TestOnboardingSettingsFallback:
    """GET /api/admin/settings should return 200 even without onboarding_terms."""

    def test_10_settings_endpoint_returns_200(self, api, base_url, admin_token):
        r = api.get(f"{base_url}/api/admin/settings", headers=auth_headers(admin_token))
        assert r.status_code == 200, f"admin settings failed: {r.status_code} {r.text}"
        data = r.json()
        # The presence/absence of onboarding_terms is not required — the client
        # falls back silently. Just ensure the response is a dict.
        assert isinstance(data, dict), f"settings response is not an object: {type(data)}"

    def test_11_optional_onboarding_terms_roundtrip(self, api, base_url, admin_token):
        """Try to PUT an onboarding_terms override. If model rejects the extra
        field silently (drops it), we mark as 'CMS override not yet available'."""
        override = {
            "onboarding_terms": {
                "vendor": {"title": "TEST_I46 Override Title"},
            }
        }
        r = api.put(f"{base_url}/api/admin/settings", json=override,
                    headers=auth_headers(admin_token))
        # 200 → accepted; 400/422 → rejected because SettingsUpdate has no
        # `onboarding_terms` field (pydantic drops the extra key, handler
        # then sees "No fields provided"). Both are acceptable — the client
        # falls back to baked-in defaults.
        assert r.status_code in (200, 400, 422), \
            f"unexpected settings PUT status: {r.status_code}: {r.text}"

        # Now GET and see if it round-trips
        g = api.get(f"{base_url}/api/admin/settings", headers=auth_headers(admin_token))
        assert g.status_code == 200
        got = g.json().get("onboarding_terms")
        if got is None:
            # Expected behaviour today — SettingsUpdate model has no such field,
            # so it's dropped by pydantic. Client falls back to baked-in defaults.
            pytest.skip("CMS override not yet available on this backend — client uses defaults")
        else:
            assert got.get("vendor", {}).get("title") == "TEST_I46 Override Title"
