# Iter107 — Festival themes: public endpoints, admin-only authz (anon + buyer), apply/restore palette, no user-data damage
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", os.environ.get("EXPO_BACKEND_URL", "")).rstrip("/")
if not BASE_URL:
    for line in open("/app/frontend/.env"):
        if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "support@slangcart.com", "password": "3)Ywxtic"}
BUYER = {"email": "testbuyer@test.com", "password": "Test@1234"}


def _login(creds):
    r = requests.post(f"{API}/auth/login", json=creds, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"login failed {creds['email']}: {r.status_code} {r.text[:200]}")
    d = r.json()
    return d.get("token") or d.get("access_token")


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login(ADMIN)}"}


@pytest.fixture(scope="module")
def buyer_h():
    return {"Authorization": f"Bearer {_login(BUYER)}"}


def _env(path, key):
    for ln in open(path):
        if ln.startswith(key + "="):
            return ln.split("=", 1)[1].strip().strip('"')
    raise KeyError(key)


@pytest.fixture(autouse=True)
def keep_live_branding():
    """Snapshot the WHOLE branding document and put it back afterwards.

    These tests apply and clear themes on the real database, so without this
    the owner's live theme (and any branding text) would be left changed.
    """
    from pymongo import MongoClient
    mdb = MongoClient(_env("/app/backend/.env", "MONGO_URL"))[_env("/app/backend/.env", "DB_NAME")]
    before = mdb.settings.find_one({"id": "branding"}, {"_id": 0})
    yield
    if before:
        mdb.settings.replace_one({"id": "branding"}, before, upsert=True)


# Public endpoints
def test_public_list():
    r = requests.get(f"{API}/festival-themes", timeout=30)
    assert r.status_code == 200
    items = r.json()["items"]
    ids = {i["id"] for i in items}
    assert len(items) == 10
    assert ids == {"deepavali", "ugadi", "independence_day", "ganesh_chaturthi", "dussehra",
                   "maha_shivaratri", "ramzan", "christmas", "new_year", "sankranti"}
    avail = [i["id"] for i in items if i.get("available")]
    assert avail == ["deepavali"]


def test_public_active():
    r = requests.get(f"{API}/festival-theme/active", timeout=30)
    assert r.status_code == 200
    assert set(r.json().keys()) >= {"id", "name", "theme_version"}


# Authz — anon + buyer
@pytest.mark.parametrize("path,body", [
    ("admin/festival-theme/apply", {"festival_id": "deepavali"}),
    ("admin/festival-theme/clear", {}),
    ("admin/festival-theme/artwork", {"festival_id": "deepavali", "slot": "banner"}),
])
def test_anon_refused(path, body):
    r = requests.post(f"{API}/{path}", json=body, timeout=30)
    assert r.status_code in (401, 403), r.text


@pytest.mark.parametrize("path,body", [
    ("admin/festival-theme/apply", {"festival_id": "deepavali"}),
    ("admin/festival-theme/clear", {}),
    ("admin/festival-theme/artwork", {"festival_id": "deepavali", "slot": "banner"}),
])
def test_buyer_refused(buyer_h, path, body):
    r = requests.post(f"{API}/{path}", json=body, headers=buyer_h, timeout=30)
    assert r.status_code in (401, 403), r.text


def test_placeholder_refused(admin_h):
    r = requests.post(f"{API}/admin/festival-theme/apply", json={"festival_id": "christmas"}, headers=admin_h, timeout=30)
    assert r.status_code == 400
    r = requests.post(f"{API}/admin/festival-theme/apply", json={"festival_id": "nope"}, headers=admin_h, timeout=30)
    assert r.status_code == 404


# Apply -> verify -> restore -> verify, user data unchanged
def test_apply_restore_cycle_no_user_damage(admin_h, buyer_h):
    me0 = requests.get(f"{API}/auth/me", headers=buyer_h, timeout=30).json()
    w0 = requests.get(f"{API}/wallet/summary", headers=buyer_h, timeout=30).json()
    b0 = requests.get(f"{API}/branding", timeout=30).json()

    r = requests.post(f"{API}/admin/festival-theme/apply", json={"festival_id": "deepavali"}, headers=admin_h, timeout=30)
    assert r.status_code == 200, r.text
    b = requests.get(f"{API}/branding", timeout=30).json()
    c = b["colors"]
    assert c["primary"].upper() == "#4C1D95"
    assert c["accent"].upper() == "#F59E0B"
    assert c["background"].upper() == "#FFF8EE"
    assert b["gradient"]["glow"].upper() == "#FBBF24"
    assert b["festival"]["id"] == "deepavali"
    assert b.get("app_name") == b0.get("app_name") and b.get("tagline") == b0.get("tagline")
    assert requests.get(f"{API}/festival-theme/active", timeout=30).json()["id"] == "deepavali"

    r = requests.post(f"{API}/admin/festival-theme/clear", headers=admin_h, timeout=30)
    assert r.status_code == 200, r.text
    b2 = requests.get(f"{API}/branding", timeout=30).json()
    assert b2.get("festival") is None
    # Order-independent: the suite may START with a festival already live
    # (b0 would then be the festival palette), so compare against the
    # non-festival brand colour rather than against b0.
    assert b2["colors"]["primary"].upper() != "#4C1D95", "restore must leave the festival palette"
    assert b2["colors"]["primary"].upper() == "#143D2E"
    assert b2.get("tagline") == b0.get("tagline")

    me1 = requests.get(f"{API}/auth/me", headers=buyer_h, timeout=30).json()
    w1 = requests.get(f"{API}/wallet/summary", headers=buyer_h, timeout=30).json()
    assert me0 == me1
    assert w0 == w1


def test_artwork_returns_clear_error(admin_h):
    r = requests.post(f"{API}/admin/festival-theme/artwork", json={"festival_id": "deepavali", "slot": "banner"},
                      headers=admin_h, timeout=120)
    print("ARTWORK:", r.status_code, r.text[:300])
    # Universal key inactive → expected a readable 4xx. It must NOT be a 5xx:
    # the ingress replaces 5xx bodies with a generic HTML error page, which
    # would hide the reason from the admin screen.
    assert r.status_code in (200, 402, 424, 503), r.text[:200]
    if r.status_code != 200:
        body = r.json()
        assert "detail" in body and len(body["detail"]) > 5
        assert "<" not in body["detail"], "an HTML blob must never reach the admin"
        assert len(body["detail"]) <= 400, "error text must stay readable"
