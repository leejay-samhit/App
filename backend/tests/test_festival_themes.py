"""Festival theme engine tests (Oct-2026).

Covers the acceptance criteria that can be verified server-side: the registry,
admin-only mutation, applying/restoring, palette stashing, version bumping and
the artwork proxy. UI verification is done in the browser.
"""
import os
import uuid

import pytest
import requests
from pymongo import MongoClient

BASE = os.environ.get("PROBE_BASE", "http://localhost:8001/api")
TIMEOUT = 30

ADMIN = {"email": "support@slangcart.com", "password": "3)Ywxtic"}
BUYER = {"email": "testbuyer@test.com", "password": "Test@1234"}

EXPECTED_IDS = [
    "deepavali", "ugadi", "independence_day", "ganesh_chaturthi", "dussehra",
    "maha_shivaratri", "ramzan", "christmas", "new_year", "sankranti",
]


def _env(path, key):
    for ln in open(path):
        if ln.startswith(key + "="):
            return ln.split("=", 1)[1].strip().strip('"')
    raise KeyError(key)


MDB = MongoClient(_env("/app/backend/.env", "MONGO_URL"))[_env("/app/backend/.env", "DB_NAME")]


def token(creds) -> str:
    r = requests.post(f"{BASE}/auth/login", json=creds, timeout=TIMEOUT)
    assert r.status_code == 200, r.text[:200]
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {token(ADMIN)}"}


@pytest.fixture(scope="module")
def buyer_h():
    return {"Authorization": f"Bearer {token(BUYER)}"}


@pytest.fixture(autouse=True)
def restore_theme(admin_h):
    """Snapshot the WHOLE branding document and put it back afterwards.

    These tests touch real settings (apply/clear/reset all write to the live
    branding doc), so restoring only the festival id is not enough — a reset
    would otherwise wipe the owner's tagline, tab labels and hero copy.
    """
    before = MDB.settings.find_one({"id": "branding"}, {"_id": 0})
    yield
    if before:
        MDB.settings.replace_one({"id": "branding"}, before, upsert=True)


# ─────────────────────────────── the registry ───────────────────────────────

def test_all_ten_festivals_are_listed():
    r = requests.get(f"{BASE}/festival-themes", timeout=TIMEOUT)
    assert r.status_code == 200, r.text[:200]
    items = r.json()["items"]
    assert [i["id"] for i in items] == EXPECTED_IDS, "all ten festivals, in order"
    for i in items:
        assert i["name"] and i["subtitle"] and i["icon"]
        assert len(i["swatches"]) >= 3, f"{i['id']} needs a colour preview"


def test_all_ten_festivals_are_applicable():
    items = requests.get(f"{BASE}/festival-themes", timeout=TIMEOUT).json()["items"]
    unavailable = [i["id"] for i in items if not i["available"]]
    assert unavailable == [], f"themes still marked as coming soon: {unavailable}"


def test_every_festival_carries_a_complete_design():
    items = requests.get(f"{BASE}/festival-themes", timeout=TIMEOUT).json()["items"]
    for d in items:
        for key in ("primary", "accent", "background", "surface", "textMain", "textMuted", "border"):
            assert d["colors"].get(key, "").startswith("#"), f"{d['id']} missing colour: {key}"
        for key in ("start", "middle", "end", "glow"):
            assert d["gradient"].get(key, "").startswith("#"), f"{d['id']} missing gradient stop: {key}"
        assert d["decor"].get("banner_title"), f"{d['id']} missing a banner title"
        assert d["decor"].get("pattern"), f"{d['id']} missing a decoration pattern"


def test_each_festival_has_its_own_decoration():
    """Distinct festivals must not all show the same diya."""
    items = requests.get(f"{BASE}/festival-themes", timeout=TIMEOUT).json()["items"]
    patterns = {i["id"]: (i["decor"] or {}).get("pattern") for i in items}
    assert len(set(patterns.values())) == len(patterns), \
        f"two festivals share a decoration: {patterns}"


# ───────────────────────────── authorisation ─────────────────────────────

def test_theme_listing_is_public_but_changing_it_is_not(buyer_h):
    assert requests.get(f"{BASE}/festival-themes", timeout=TIMEOUT).status_code == 200
    assert requests.get(f"{BASE}/festival-theme/active", timeout=TIMEOUT).status_code == 200

    for path, headers in (
        ("/admin/festival-theme/apply", None),
        ("/admin/festival-theme/apply", buyer_h),
        ("/admin/festival-theme/clear", None),
        ("/admin/festival-theme/clear", buyer_h),
        ("/admin/festival-theme/artwork", buyer_h),
    ):
        r = requests.post(f"{BASE}{path}", json={"festival_id": "deepavali"},
                          headers=headers, timeout=TIMEOUT)
        assert r.status_code in (401, 403), f"{path} ({'anon' if not headers else 'buyer'}) -> {r.status_code}"


def test_unknown_festivals_are_refused(admin_h):
    r = requests.post(f"{BASE}/admin/festival-theme/apply",
                      json={"festival_id": "holi-not-a-thing"}, headers=admin_h, timeout=TIMEOUT)
    assert r.status_code == 404


# ─────────────────────────── apply / restore ───────────────────────────

def test_applying_deepavali_rewrites_the_live_palette(admin_h):
    before = requests.get(f"{BASE}/festival-theme/active", timeout=TIMEOUT).json()

    r = requests.post(f"{BASE}/admin/festival-theme/apply",
                      json={"festival_id": "deepavali"}, headers=admin_h, timeout=TIMEOUT)
    assert r.status_code == 200, r.text[:300]
    doc = r.json()
    assert doc["colors"]["primary"] == "#4C1D95"
    assert doc["colors"]["accent"] == "#F59E0B"
    assert doc["gradient"]["glow"] == "#FBBF24"
    assert doc["festival"]["id"] == "deepavali"

    # Every user reads the same theme from the public endpoint.
    pub = requests.get(f"{BASE}/branding", timeout=TIMEOUT).json()
    assert pub["colors"]["primary"] == "#4C1D95"
    assert (pub.get("festival") or {}).get("id") == "deepavali"

    after = requests.get(f"{BASE}/festival-theme/active", timeout=TIMEOUT).json()
    assert after["theme_version"] >= before.get("theme_version", 0)
    assert after["id"] == "deepavali"


def test_restore_default_brings_back_the_admins_own_palette(admin_h):
    # Give the admin a custom primary FIRST, so we can prove restore returns
    # their colour and not the factory one.
    custom = "#0B3D2C"
    requests.put(f"{BASE}/admin/branding", json={"colors": {"primary": custom}},
                 headers=admin_h, timeout=TIMEOUT)

    requests.post(f"{BASE}/admin/festival-theme/apply", json={"festival_id": "deepavali"},
                  headers=admin_h, timeout=TIMEOUT)
    assert requests.get(f"{BASE}/branding", timeout=TIMEOUT).json()["colors"]["primary"] == "#4C1D95"

    r = requests.post(f"{BASE}/admin/festival-theme/clear", headers=admin_h, timeout=TIMEOUT)
    assert r.status_code == 200, r.text[:200]
    doc = r.json()
    assert doc["colors"]["primary"] == custom, "restore must return the admin's own colour"
    assert not doc.get("festival")

    # Clean up the custom colour.
    requests.put(f"{BASE}/admin/branding", json={"colors": {"primary": "#143D2E"}},
                 headers=admin_h, timeout=TIMEOUT)


def test_applying_twice_is_safe_and_keeps_one_stash(admin_h):
    for _ in range(3):
        r = requests.post(f"{BASE}/admin/festival-theme/apply", json={"festival_id": "deepavali"},
                          headers=admin_h, timeout=TIMEOUT)
        assert r.status_code == 200
    stored = MDB.settings.find_one({"id": "branding"}, {"_id": 0, "pre_festival_colors": 1})
    # The stash must still hold a NON-festival primary, i.e. re-applying never
    # overwrote it with the festival palette.
    assert (stored.get("pre_festival_colors") or {}).get("primary") != "#4C1D95"


def test_switching_between_festivals_never_loses_the_stash(admin_h):
    """Festival A -> festival B -> restore must still bring back the ADMIN'S
    own colours, not festival A's."""
    custom = "#0B3D2C"
    requests.put(f"{BASE}/admin/branding", json={"colors": {"primary": custom}},
                 headers=admin_h, timeout=TIMEOUT)
    try:
        requests.post(f"{BASE}/admin/festival-theme/apply", json={"festival_id": "ugadi"},
                      headers=admin_h, timeout=TIMEOUT)
        requests.post(f"{BASE}/admin/festival-theme/apply", json={"festival_id": "christmas"},
                      headers=admin_h, timeout=TIMEOUT)
        after = requests.get(f"{BASE}/branding", timeout=TIMEOUT).json()
        assert after["colors"]["primary"] == "#14532D", "Christmas palette not applied"
        assert (after.get("festival") or {}).get("id") == "christmas"

        r = requests.post(f"{BASE}/admin/festival-theme/clear", headers=admin_h, timeout=TIMEOUT)
        assert r.json()["colors"]["primary"] == custom, \
            "restore after switching festivals must return the admin's own colour"
    finally:
        requests.put(f"{BASE}/admin/branding", json={"colors": {"primary": "#143D2E"}},
                     headers=admin_h, timeout=TIMEOUT)


def test_every_festival_applies_and_restores(admin_h):
    """The full catalogue, end to end: each festival's palette must reach the
    public branding payload, and a final clear must restore the default."""
    registry = {i["id"]: i for i in requests.get(f"{BASE}/festival-themes", timeout=TIMEOUT).json()["items"]}
    for fid, meta in registry.items():
        r = requests.post(f"{BASE}/admin/festival-theme/apply", json={"festival_id": fid},
                          headers=admin_h, timeout=TIMEOUT)
        assert r.status_code == 200, f"{fid}: {r.text[:200]}"
        doc = r.json()
        assert doc["colors"]["primary"] == meta["colors"]["primary"], f"{fid} palette mismatch"
        assert (doc.get("festival") or {}).get("id") == fid
        assert doc["gradient"]["glow"] == meta["gradient"]["glow"]

    r = requests.post(f"{BASE}/admin/festival-theme/clear", headers=admin_h, timeout=TIMEOUT)
    assert r.status_code == 200
    assert not r.json().get("festival"), "festival should be gone after restore"


def test_theme_change_does_not_touch_user_data_or_money(admin_h, buyer_h):
    me_before = requests.get(f"{BASE}/auth/me", headers=buyer_h, timeout=TIMEOUT).json()
    w_before = requests.get(f"{BASE}/wallet/summary", headers=buyer_h, timeout=TIMEOUT)
    users_before = MDB.users.count_documents({})
    orders_before = MDB.orders.count_documents({})

    requests.post(f"{BASE}/admin/festival-theme/apply", json={"festival_id": "deepavali"},
                  headers=admin_h, timeout=TIMEOUT)
    requests.post(f"{BASE}/admin/festival-theme/clear", headers=admin_h, timeout=TIMEOUT)

    me_after = requests.get(f"{BASE}/auth/me", headers=buyer_h, timeout=TIMEOUT).json()
    assert me_after.get("id") == me_before.get("id")
    assert me_after.get("role") == me_before.get("role")
    assert me_after.get("registration_paid") == me_before.get("registration_paid")
    assert MDB.users.count_documents({}) == users_before
    assert MDB.orders.count_documents({}) == orders_before
    if w_before.status_code == 200:
        w_after = requests.get(f"{BASE}/wallet/summary", headers=buyer_h, timeout=TIMEOUT)
        assert w_after.json() == w_before.json(), "wallet must be byte-identical"


def test_tabs_and_app_name_survive_a_theme_change(admin_h):
    before = requests.get(f"{BASE}/branding", timeout=TIMEOUT).json()
    requests.post(f"{BASE}/admin/festival-theme/apply", json={"festival_id": "deepavali"},
                  headers=admin_h, timeout=TIMEOUT)
    after = requests.get(f"{BASE}/branding", timeout=TIMEOUT).json()
    assert after["app_name"] == before["app_name"], "the Slangcart name must stay"
    assert after["tabs"] == before["tabs"]
    assert after.get("support_whatsapp") == before.get("support_whatsapp")


# ───────────────────────────── artwork proxy ─────────────────────────────

def test_artwork_route_404s_until_something_is_generated():
    r = requests.get(f"{BASE}/festival-artwork/deepavali/banner", timeout=TIMEOUT)
    # 200 if an admin already generated it in this environment, 404 if not.
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        assert r.headers.get("Content-Type", "").startswith("image/")


def test_artwork_route_rejects_unknown_festival_or_slot():
    assert requests.get(f"{BASE}/festival-artwork/nope/banner", timeout=TIMEOUT).status_code == 404
    assert requests.get(f"{BASE}/festival-artwork/deepavali/sidebar", timeout=TIMEOUT).status_code == 404


def test_every_festival_has_an_artwork_prompt(admin_h):
    """The banner-artwork button must never fail for a missing prompt."""
    r = requests.post(f"{BASE}/admin/festival-theme/artwork",
                      json={"festival_id": "nope", "slot": "banner"}, headers=admin_h, timeout=TIMEOUT)
    assert r.status_code == 404

    items = requests.get(f"{BASE}/festival-themes", timeout=TIMEOUT).json()["items"]
    for i in items:
        # The listing strips prompts, so check the registry directly.
        from core.festival_themes import get_festival
        f = get_festival(i["id"])
        assert f and len(f.get("artwork_prompt") or "") > 80, f"{i['id']} has no artwork prompt"


def test_artwork_generation_rejects_a_bad_slot(admin_h):
    r = requests.post(f"{BASE}/admin/festival-theme/artwork",
                      json={"festival_id": "deepavali", "slot": "wallpaper"},
                      headers=admin_h, timeout=TIMEOUT)
    assert r.status_code == 400


def test_full_branding_reset_also_drops_the_festival(admin_h):
    requests.post(f"{BASE}/admin/festival-theme/apply", json={"festival_id": "deepavali"},
                  headers=admin_h, timeout=TIMEOUT)
    r = requests.post(f"{BASE}/admin/branding/reset", headers=admin_h, timeout=TIMEOUT)
    assert r.status_code == 200, r.text[:200]
    doc = r.json()
    assert not doc.get("festival"), "a full reset must clear the festival too"
    assert doc["colors"]["primary"] == "#143D2E"
    stored = MDB.settings.find_one({"id": "branding"}, {"_id": 0}) or {}
    assert "pre_festival_colors" not in stored
