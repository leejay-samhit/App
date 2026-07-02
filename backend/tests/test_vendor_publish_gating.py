"""
UPDATE 1 — Vendor Shop scoping + publish gating (Jan 2026)

Tests:
  1. POST /api/vendor/me/products always forces is_published=False even if the
     vendor payload sends is_published=True.
  2. PATCH /api/vendor/me/products/{id} silently drops is_published from the
     vendor payload (admin decision must be respected).
  3. GET  /api/products (public) still returns only published products (no
     regression).
  4. GET  /api/admin/products still sees all products (published + hidden).
  5. PATCH /api/admin/products/{id} can still toggle is_published (no
     regression on the admin publish path).
  6. GET  /api/vendor/me/products returns the vendor's own products including
     unpublished ones.
  7. End-to-end vendor CRUD: create → list → PATCH non-publish field → delete.
"""

import os
import uuid
import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")

ALICE_EMAIL = "test_alice_73dc7f@test.com"
ALICE_PASSWORD = "Passw0rd!"

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "support@networkrupay.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Nlee@1115")


# ---------------- helpers ----------------

def _login(session: requests.Session, email: str, password: str) -> str:
    r = session.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=30,
    )
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text}"
    return r.json()["token"]


def _bearer(tok: str):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---------------- fixtures ----------------

@pytest.fixture(scope="module")
def http():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def vendor_token(http):
    return _login(http, ALICE_EMAIL, ALICE_PASSWORD)


@pytest.fixture(scope="module")
def admin_token(http):
    return _login(http, ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def vendor_is_approved(http, vendor_token):
    """Sanity: Alice must be an approved vendor for this test file to run."""
    r = http.get(f"{BASE_URL}/api/vendor/me/status", headers=_bearer(vendor_token))
    assert r.status_code == 200, f"vendor/me/status failed: {r.status_code} {r.text}"
    body = r.json()
    if not (body.get("is_vendor") and body.get("vendor_status") == "approved"):
        pytest.skip(
            f"Alice is not an approved vendor (is_vendor={body.get('is_vendor')}, "
            f"vendor_status={body.get('vendor_status')}). Approve first."
        )
    return True


@pytest.fixture(scope="module")
def created_ids():
    """Track ids created so we can clean up at teardown."""
    return []


@pytest.fixture(scope="module", autouse=True)
def _cleanup(request, http, vendor_token, created_ids):
    yield
    # best-effort teardown
    for pid in created_ids:
        try:
            http.delete(
                f"{BASE_URL}/api/vendor/me/products/{pid}",
                headers=_bearer(vendor_token),
                timeout=15,
            )
        except Exception:
            pass


# ---------------- 1. create forces is_published=False ----------------

class TestVendorCreateForcesUnpublished:

    def test_create_ignores_vendor_is_published_true(
        self, http, vendor_token, vendor_is_approved, created_ids
    ):
        payload = {
            "name": f"TEST_pub_gate_{uuid.uuid4().hex[:6]}",
            "price": 199.0,
            "image_url": "https://example.com/x.png",
            "description": "publish gating test",
            "stock": 10,
            "category": "Electronics",
            "is_published": True,   # vendor tries to publish itself
        }
        r = http.post(
            f"{BASE_URL}/api/vendor/me/products",
            json=payload,
            headers=_bearer(vendor_token),
            timeout=30,
        )
        assert r.status_code == 200, f"create failed: {r.status_code} {r.text}"
        body = r.json()
        assert body.get("is_published") is False, (
            f"Expected is_published=False, got {body.get('is_published')!r}"
        )
        assert body.get("name") == payload["name"]
        assert body.get("price") == payload["price"]
        assert body.get("vendor_id"), "vendor_id must be stamped by backend"
        created_ids.append(body["id"])

    def test_create_without_is_published_still_false(
        self, http, vendor_token, vendor_is_approved, created_ids
    ):
        payload = {
            "name": f"TEST_pub_gate_{uuid.uuid4().hex[:6]}",
            "price": 250.0,
            "image_url": "https://example.com/y.png",
        }
        r = http.post(
            f"{BASE_URL}/api/vendor/me/products",
            json=payload,
            headers=_bearer(vendor_token),
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("is_published") is False
        created_ids.append(body["id"])


# ---------------- 2. GET /api/vendor/me/products lists own products (including unpublished) ----------------

class TestVendorListsOwnProducts:

    def test_vendor_sees_unpublished_own_product(
        self, http, vendor_token, vendor_is_approved, created_ids
    ):
        assert created_ids, "prior create test must have produced ids"
        r = http.get(
            f"{BASE_URL}/api/vendor/me/products",
            headers=_bearer(vendor_token),
            timeout=30,
        )
        assert r.status_code == 200, r.text
        items = r.json()
        assert isinstance(items, list)
        ids = {it["id"] for it in items}
        for pid in created_ids:
            assert pid in ids, f"vendor should see own unpublished product {pid}"
        # And these are unpublished
        for it in items:
            if it["id"] in created_ids:
                assert it.get("is_published") is False


# ---------------- 3. GET /api/products (public) hides unpublished ----------------

class TestPublicProductsHidesUnpublished:

    def test_public_endpoint_excludes_unpublished(
        self, http, vendor_is_approved, created_ids
    ):
        assert created_ids
        r = http.get(f"{BASE_URL}/api/products", timeout=30)
        assert r.status_code == 200, r.text
        items = r.json()
        assert isinstance(items, list)
        ids = {it.get("id") for it in items}
        for pid in created_ids:
            assert pid not in ids, (
                f"Public /api/products must NOT include unpublished product {pid}"
            )


# ---------------- 4. Admin can PATCH is_published (regression) ----------------

class TestAdminCanPublish:

    def test_admin_publishes_vendor_product(
        self, http, admin_token, vendor_is_approved, created_ids
    ):
        assert created_ids
        pid = created_ids[0]
        r = http.patch(
            f"{BASE_URL}/api/admin/products/{pid}",
            json={"is_published": True},
            headers=_bearer(admin_token),
            timeout=30,
        )
        assert r.status_code == 200, f"admin patch failed: {r.status_code} {r.text}"
        body = r.json()
        assert body.get("is_published") is True

        # GET public must now include it
        pub = http.get(f"{BASE_URL}/api/products", timeout=30)
        assert pub.status_code == 200
        assert pid in {it.get("id") for it in pub.json()}


# ---------------- 5. Vendor PATCH with is_published=False must NOT unpublish ----------------

class TestVendorPatchStripsIsPublished:

    def test_vendor_patch_cannot_unpublish(
        self, http, vendor_token, vendor_is_approved, created_ids
    ):
        assert created_ids
        pid = created_ids[0]  # was published by admin in previous test class
        # vendor tries to un-publish AND update description
        new_desc = f"updated by vendor {uuid.uuid4().hex[:4]}"
        r = http.patch(
            f"{BASE_URL}/api/vendor/me/products/{pid}",
            json={"is_published": False, "description": new_desc},
            headers=_bearer(vendor_token),
            timeout=30,
        )
        assert r.status_code == 200, f"vendor patch failed: {r.status_code} {r.text}"
        body = r.json()
        assert body.get("is_published") is True, (
            "vendor PATCH must NOT be able to unpublish an admin-published product"
        )
        assert body.get("description") == new_desc, "non-publish fields must still update"

    def test_vendor_patch_only_is_published_returns_400(
        self, http, vendor_token, vendor_is_approved, created_ids
    ):
        """If vendor sends only is_published, after stripping the update dict
        is empty and endpoint should raise 400 (no fields provided)."""
        assert created_ids
        pid = created_ids[0]
        r = http.patch(
            f"{BASE_URL}/api/vendor/me/products/{pid}",
            json={"is_published": False},
            headers=_bearer(vendor_token),
            timeout=30,
        )
        assert r.status_code == 400, (
            f"expected 400 when only is_published is sent (backend strips it), "
            f"got {r.status_code} {r.text}"
        )


# ---------------- 6. Admin sees all products (regression) ----------------

class TestAdminListsAllProducts:

    def test_admin_sees_published_and_unpublished(
        self, http, admin_token, vendor_is_approved, created_ids
    ):
        r = http.get(
            f"{BASE_URL}/api/admin/products",
            headers=_bearer(admin_token),
            timeout=30,
        )
        assert r.status_code == 200, r.text
        items = r.json()
        ids = {it.get("id") for it in items}
        # created_ids[0] is published now, created_ids[1] is still unpublished
        for pid in created_ids:
            assert pid in ids, f"admin should see product {pid}"

        # check that at least one of the created products is is_published=False
        by_id = {it["id"]: it for it in items if it.get("id") in created_ids}
        if len(created_ids) >= 2:
            assert by_id[created_ids[1]].get("is_published") is False


# ---------------- 7. End-to-end vendor CRUD ----------------

class TestVendorCrudEndToEnd:

    def test_vendor_create_list_patch_delete(
        self, http, vendor_token, vendor_is_approved
    ):
        # create
        payload = {
            "name": f"TEST_crud_{uuid.uuid4().hex[:6]}",
            "price": 55.0,
            "image_url": "https://example.com/crud.png",
            "stock": 5,
        }
        r = http.post(
            f"{BASE_URL}/api/vendor/me/products",
            json=payload,
            headers=_bearer(vendor_token),
            timeout=30,
        )
        assert r.status_code == 200, r.text
        pid = r.json()["id"]
        assert r.json().get("is_published") is False

        # list
        r = http.get(
            f"{BASE_URL}/api/vendor/me/products",
            headers=_bearer(vendor_token),
            timeout=30,
        )
        assert r.status_code == 200
        assert pid in {it["id"] for it in r.json()}

        # patch non-publish field (price)
        r = http.patch(
            f"{BASE_URL}/api/vendor/me/products/{pid}",
            json={"price": 77.0, "stock": 9},
            headers=_bearer(vendor_token),
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("price") == 77.0
        assert body.get("stock") == 9
        assert body.get("is_published") is False  # unchanged

        # delete
        r = http.delete(
            f"{BASE_URL}/api/vendor/me/products/{pid}",
            headers=_bearer(vendor_token),
            timeout=30,
        )
        assert r.status_code == 200
        assert r.json().get("ok") is True

        # verify gone
        r = http.get(
            f"{BASE_URL}/api/vendor/me/products",
            headers=_bearer(vendor_token),
            timeout=30,
        )
        assert pid not in {it["id"] for it in r.json()}
