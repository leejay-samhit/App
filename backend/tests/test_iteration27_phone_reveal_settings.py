"""
Iteration 27 — Phone-reveal fee settings tests.

Verifies:
  - GET /api/admin/settings includes phone_reveal_fee + phone_reveal_gst_pct (defaults)
  - PUT /api/admin/settings persists new values for both fields
  - Partial updates do not null other fields
  - Boundary validation (0, 100) succeeds
  - Out-of-range values rejected with 422
  - Empty body still returns 400
  - RBAC: regular user → 401/403; manager → 403; super_admin only
  - Existing fields (registration_fee, payout_l1, auto_approve_on_payment) still work
"""
import os
import time
import requests
import pytest
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
_fe = Path(__file__).resolve().parents[2] / "frontend" / ".env"
if _fe.exists():
    load_dotenv(_fe, override=False)

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "support@networkrupay.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", os.environ.get("ADMIN_PASSWORD", ""))

REGULAR_EMAIL = "test_alice_73dc7f@test.com"
REGULAR_PASSWORD = "Passw0rd!"


# --------------------------- helpers --------------------------- #
def _login(email: str, password: str):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=20)
    return r


def _admin_token():
    r = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json()["token"]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---------- module-level fixtures ---------- #
@pytest.fixture(scope="module")
def admin_token():
    return _admin_token()


@pytest.fixture(scope="module")
def regular_token():
    r = _login(REGULAR_EMAIL, REGULAR_PASSWORD)
    if r.status_code != 200:
        pytest.skip(f"regular user login unavailable: {r.status_code}")
    return r.json()["token"]


@pytest.fixture(scope="module")
def manager_token(admin_token):
    """Create an ephemeral manager admin for RBAC test; clean up at module teardown."""
    # Look for an existing manager first via /admin/admins
    r = requests.get(f"{BASE_URL}/api/admin/admins", headers=_hdr(admin_token), timeout=20)
    created_id = None
    email = None
    if r.status_code == 200:
        for a in r.json() or []:
            if a.get("admin_role") == "manager" and a.get("email"):
                email = a["email"]
                break
    if email is None:
        # Create a new manager via POST /api/admin/admins
        uniq = int(time.time())
        email = f"TEST_mgr_{uniq}@test.com"
        payload = {
            "name": "TEST Manager",
            "email": email,
            "password": "MgrPass123!",
            "admin_role": "manager",
        }
        c = requests.post(f"{BASE_URL}/api/admin/admins", headers=_hdr(admin_token), json=payload, timeout=20)
        if c.status_code not in (200, 201):
            pytest.skip(f"could not create manager: {c.status_code} {c.text}")
        created_id = c.json().get("id") or c.json().get("user", {}).get("id")
        # login as that manager
        lr = _login(email, "MgrPass123!")
        if lr.status_code != 200:
            pytest.skip(f"manager login failed: {lr.status_code} {lr.text}")
        tok = lr.json()["token"]
        yield tok
        # teardown — delete created manager
        if created_id:
            try:
                requests.delete(f"{BASE_URL}/api/admin/admins/{created_id}", headers=_hdr(admin_token), timeout=20)
            except Exception:
                pass
        return
    # Existing manager — but we don't know its password. Try a few obvious ones; else skip.
    for pw in ("MgrPass123!", "Manager@123", "Passw0rd!"):
        lr = _login(email, pw)
        if lr.status_code == 200:
            yield lr.json()["token"]
            return
    pytest.skip(f"could not authenticate existing manager {email}")


# Module-level teardown: restore defaults
@pytest.fixture(scope="module", autouse=True)
def _restore_defaults(admin_token):
    yield
    try:
        requests.put(
            f"{BASE_URL}/api/admin/settings",
            headers=_hdr(admin_token),
            json={"phone_reveal_fee": 1.0, "phone_reveal_gst_pct": 18.0},
            timeout=20,
        )
    except Exception:
        pass


# ============================================================== #
# 1. GET defaults
# ============================================================== #
class TestGetSettings:
    def test_get_includes_phone_reveal_fields(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/settings", headers=_hdr(admin_token), timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "phone_reveal_fee" in data, f"missing phone_reveal_fee: keys={list(data)}"
        assert "phone_reveal_gst_pct" in data, f"missing phone_reveal_gst_pct: keys={list(data)}"
        # Type checks
        assert isinstance(data["phone_reveal_fee"], (int, float))
        assert isinstance(data["phone_reveal_gst_pct"], (int, float))


# ============================================================== #
# 2. PUT happy path — set both fields
# ============================================================== #
class TestPutBothFields:
    def test_put_both_fields_then_get_reflects(self, admin_token):
        body = {"phone_reveal_fee": 5.0, "phone_reveal_gst_pct": 22.5}
        r = requests.put(f"{BASE_URL}/api/admin/settings", headers=_hdr(admin_token), json=body, timeout=20)
        assert r.status_code == 200, r.text
        echoed = r.json()
        assert echoed["phone_reveal_fee"] == 5.0
        assert echoed["phone_reveal_gst_pct"] == 22.5

        # confirm with GET
        g = requests.get(f"{BASE_URL}/api/admin/settings", headers=_hdr(admin_token), timeout=20)
        assert g.status_code == 200
        gd = g.json()
        assert gd["phone_reveal_fee"] == 5.0
        assert gd["phone_reveal_gst_pct"] == 22.5


# ============================================================== #
# 3. Partial update — only one field, the other preserved
# ============================================================== #
class TestPartialUpdate:
    def test_only_fee_then_pct_preserved(self, admin_token):
        # Seed both
        requests.put(
            f"{BASE_URL}/api/admin/settings",
            headers=_hdr(admin_token),
            json={"phone_reveal_fee": 7.0, "phone_reveal_gst_pct": 12.0},
            timeout=20,
        )
        # Update only fee
        r = requests.put(
            f"{BASE_URL}/api/admin/settings",
            headers=_hdr(admin_token),
            json={"phone_reveal_fee": 10.0},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["phone_reveal_fee"] == 10.0
        assert data["phone_reveal_gst_pct"] == 12.0, f"gst_pct got mutated: {data['phone_reveal_gst_pct']}"

    def test_only_pct_then_fee_preserved(self, admin_token):
        # current state: fee=10.0, pct=12.0 from prior test
        r = requests.put(
            f"{BASE_URL}/api/admin/settings",
            headers=_hdr(admin_token),
            json={"phone_reveal_gst_pct": 9.5},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["phone_reveal_gst_pct"] == 9.5
        assert data["phone_reveal_fee"] == 10.0, f"fee got mutated: {data['phone_reveal_fee']}"


# ============================================================== #
# 4. Boundary values
# ============================================================== #
class TestBoundaryValues:
    def test_fee_zero_ok(self, admin_token):
        r = requests.put(
            f"{BASE_URL}/api/admin/settings",
            headers=_hdr(admin_token),
            json={"phone_reveal_fee": 0},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        assert r.json()["phone_reveal_fee"] == 0

    def test_pct_hundred_ok(self, admin_token):
        r = requests.put(
            f"{BASE_URL}/api/admin/settings",
            headers=_hdr(admin_token),
            json={"phone_reveal_gst_pct": 100},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        assert r.json()["phone_reveal_gst_pct"] == 100


# ============================================================== #
# 5. Negative validation (must return 422)
# ============================================================== #
class TestValidationErrors:
    def test_fee_negative_422(self, admin_token):
        r = requests.put(
            f"{BASE_URL}/api/admin/settings",
            headers=_hdr(admin_token),
            json={"phone_reveal_fee": -1},
            timeout=20,
        )
        assert r.status_code == 422, f"expected 422, got {r.status_code}: {r.text}"

    def test_pct_above_100_422(self, admin_token):
        r = requests.put(
            f"{BASE_URL}/api/admin/settings",
            headers=_hdr(admin_token),
            json={"phone_reveal_gst_pct": 150},
            timeout=20,
        )
        assert r.status_code == 422, f"expected 422, got {r.status_code}: {r.text}"

    def test_pct_negative_422(self, admin_token):
        r = requests.put(
            f"{BASE_URL}/api/admin/settings",
            headers=_hdr(admin_token),
            json={"phone_reveal_gst_pct": -0.5},
            timeout=20,
        )
        assert r.status_code == 422, f"expected 422, got {r.status_code}: {r.text}"

    def test_empty_body_400(self, admin_token):
        r = requests.put(
            f"{BASE_URL}/api/admin/settings",
            headers=_hdr(admin_token),
            json={},
            timeout=20,
        )
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
        assert "No fields provided" in r.text or "no fields" in r.text.lower()


# ============================================================== #
# 6. RBAC
# ============================================================== #
class TestRBAC:
    def test_regular_user_get_blocked(self, regular_token):
        r = requests.get(f"{BASE_URL}/api/admin/settings", headers=_hdr(regular_token), timeout=20)
        assert r.status_code in (401, 403), f"got {r.status_code}: {r.text}"

    def test_regular_user_put_blocked(self, regular_token):
        r = requests.put(
            f"{BASE_URL}/api/admin/settings",
            headers=_hdr(regular_token),
            json={"phone_reveal_fee": 99},
            timeout=20,
        )
        assert r.status_code in (401, 403), f"got {r.status_code}: {r.text}"

    def test_unauth_blocked(self):
        r = requests.put(
            f"{BASE_URL}/api/admin/settings",
            json={"phone_reveal_fee": 99},
            timeout=20,
        )
        assert r.status_code in (401, 403)

    def test_manager_put_blocked(self, manager_token):
        r = requests.put(
            f"{BASE_URL}/api/admin/settings",
            headers=_hdr(manager_token),
            json={"phone_reveal_fee": 99},
            timeout=20,
        )
        assert r.status_code == 403, f"manager should be 403, got {r.status_code}: {r.text}"


# ============================================================== #
# 7. Cross-field isolation: existing fields still work and don't trash phone_reveal_*
# ============================================================== #
class TestCrossFieldIsolation:
    def test_existing_field_update_preserves_phone_reveal(self, admin_token):
        # Seed phone_reveal_* with known values
        requests.put(
            f"{BASE_URL}/api/admin/settings",
            headers=_hdr(admin_token),
            json={"phone_reveal_fee": 3.0, "phone_reveal_gst_pct": 7.0},
            timeout=20,
        )
        # Read current registration_fee so we can restore it later
        g0 = requests.get(f"{BASE_URL}/api/admin/settings", headers=_hdr(admin_token), timeout=20)
        original_reg_fee = g0.json().get("registration_fee", 118)

        # Update an unrelated field
        r = requests.put(
            f"{BASE_URL}/api/admin/settings",
            headers=_hdr(admin_token),
            json={"payout_l1": 401.0},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["payout_l1"] == 401.0
        assert data["phone_reveal_fee"] == 3.0
        assert data["phone_reveal_gst_pct"] == 7.0

        # Update auto_approve_on_payment toggle
        r2 = requests.put(
            f"{BASE_URL}/api/admin/settings",
            headers=_hdr(admin_token),
            json={"auto_approve_on_payment": False},
            timeout=20,
        )
        assert r2.status_code == 200, r2.text
        d2 = r2.json()
        assert d2["auto_approve_on_payment"] is False
        assert d2["phone_reveal_fee"] == 3.0
        assert d2["phone_reveal_gst_pct"] == 7.0

        # restore
        requests.put(
            f"{BASE_URL}/api/admin/settings",
            headers=_hdr(admin_token),
            json={"payout_l1": 400.0, "auto_approve_on_payment": True, "registration_fee": float(original_reg_fee)},
            timeout=20,
        )


# ============================================================== #
# 8. Restore defaults (explicit final test for documentation)
# ============================================================== #
class TestRestoreDefaults:
    def test_restore_defaults(self, admin_token):
        r = requests.put(
            f"{BASE_URL}/api/admin/settings",
            headers=_hdr(admin_token),
            json={"phone_reveal_fee": 1.0, "phone_reveal_gst_pct": 18.0},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["phone_reveal_fee"] == 1.0
        assert data["phone_reveal_gst_pct"] == 18.0
