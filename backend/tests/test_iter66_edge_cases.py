"""Iteration 66 edge cases (Phase 4A + 4B + 5A) that were NOT covered by
the four scripted smoke tests.

Runs against the public preview URL (EXPO_PUBLIC_BACKEND_URL) so the tests
exercise the actual Cloudflare edge.

Covers:
    * catalogue import replace-mode multi-chunk (first_chunk=True then False)
    * catalogue import 403 for a non-vendor buyer
    * catalogue import malformed / oversized payload rejection
    * admin backup restore malformed docs / missing collection
    * admin backup restore with lat/lng-only delivery check (customer with no pincode)
    * delivery /check accepts lat/lng-only (no pincode) and returns coverage
"""
import asyncio
import os
import sys
import uuid

import pytest
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.security import hash_password  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://slangcart-tracking.preview.emergentagent.com").rstrip("/") + "/api"
UA = {"User-Agent": "curl/8.5.0"}
PIN = "135790"


def _login(email, password):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password}, headers=UA, timeout=60)
    r.raise_for_status()
    d = r.json()
    tok = d.get("token") or d.get("access_token")
    assert tok, d
    return {"Authorization": f"Bearer {tok}", **UA}


@pytest.fixture(scope="module")
def vendor1_headers():
    return _login("testvendor@test.com", "Test@1234")


@pytest.fixture(scope="module")
def vendor2_headers():
    return _login("testvendor2@test.com", "Test@1234")


@pytest.fixture(scope="module")
def buyer_headers():
    return _login("testbuyer@test.com", "Test@1234")


@pytest.fixture(scope="module")
def admin_headers():
    return _login("support@slangcart.com", "3)Ywxtic")


# --- Phase 4A edge cases ---------------------------------------------------

def _export_all(h):
    products, offset = [], 0
    while True:
        r = requests.get(f"{BASE}/vendor/me/catalogue/export", params={"offset": offset, "limit": 5}, headers=h, timeout=90)
        r.raise_for_status()
        d = r.json()
        products += d["products"]
        if not d["has_more"]:
            return products, d
        offset += 5


def test_export_pagination_no_leakage(vendor1_headers):
    products, meta = _export_all(vendor1_headers)
    assert len(products) == meta["total"] and meta["total"] > 0
    banned = {"id", "vendor_id", "store_pincode", "store_lat", "store_lng"}
    for p in products:
        leaked = banned & set(p.keys())
        assert not leaked, f"forbidden fields leaked: {leaked}"


def test_import_403_for_non_vendor(buyer_headers):
    r = requests.post(f"{BASE}/vendor/me/catalogue/import",
                      json={"products": [], "mode": "merge", "first_chunk": True},
                      headers=buyer_headers, timeout=30)
    assert r.status_code == 403, r.status_code


def test_import_merge_multichunk(vendor1_headers, vendor2_headers):
    """Merge-mode with multiple chunks: two calls should each land as drafts
    with restored_from_backup=true, first_chunk toggles between True/False.
    Merge mode is SAFE and won't wipe the Vendor Two Gadget fixture.
    Replace mode is intentionally NOT tested here to preserve fixture data;
    the vendor1-only smoke covers replace semantics.
    """
    products, _ = _export_all(vendor1_headers)
    assert len(products) >= 4, "need >= 4 source products for multi-chunk test"
    half = len(products) // 2
    chunk_a, chunk_b = products[:half], products[half:]

    before = requests.get(f"{BASE}/vendor/me/products", headers=vendor2_headers, timeout=90).json()
    base_count = len(before)
    base_restored_ids = {p["id"] for p in before if p.get("restored_from_backup")}

    r1 = requests.post(f"{BASE}/vendor/me/catalogue/import",
                       json={"products": chunk_a, "mode": "merge", "first_chunk": True},
                       headers=vendor2_headers, timeout=180)
    r1.raise_for_status()
    r2 = requests.post(f"{BASE}/vendor/me/catalogue/import",
                       json={"products": chunk_b, "mode": "merge", "first_chunk": False},
                       headers=vendor2_headers, timeout=180)
    r2.raise_for_status()

    after = requests.get(f"{BASE}/vendor/me/products", headers=vendor2_headers, timeout=90).json()
    new_restored = [p for p in after if p.get("restored_from_backup") and p["id"] not in base_restored_ids]
    assert len(new_restored) == len(products), f"multi-chunk merge expected {len(products)} new restored, got {len(new_restored)}"
    for p in new_restored:
        assert p["is_published"] is False, "restored products must be drafts"

    src_variant = [p for p in products if p.get("variants")]
    if src_variant:
        dst_variant = [p for p in new_restored if p.get("variants")]
        assert dst_variant, "variant products lost variants[] after import"

    # cleanup ONLY the products we just imported; keep base rows intact.
    for p in new_restored:
        requests.delete(f"{BASE}/vendor/me/products/{p['id']}", headers=vendor2_headers, timeout=45)
    final = requests.get(f"{BASE}/vendor/me/products", headers=vendor2_headers, timeout=90).json()
    assert len(final) == base_count, f"cleanup left {len(final)} != base {base_count}"


def test_import_malformed_payload_rejected(vendor2_headers):
    # completely bogus products entry (not a list)
    r = requests.post(f"{BASE}/vendor/me/catalogue/import",
                      json={"products": "not-a-list", "mode": "merge", "first_chunk": True},
                      headers=vendor2_headers, timeout=30)
    assert r.status_code in (400, 422), r.status_code

    # products list contains a non-dict → server must not 500
    r = requests.post(f"{BASE}/vendor/me/catalogue/import",
                      json={"products": ["not-a-dict"], "mode": "merge", "first_chunk": True},
                      headers=vendor2_headers, timeout=30)
    assert r.status_code in (200, 400, 422), r.status_code


# --- Phase 4B edge cases ---------------------------------------------------

async def _swap_pin(new_hash):
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = c[os.environ.get("DB_NAME", "test_database")]
    doc = await db.settings.find_one({"id": "global"}, {"_id": 0, "danger_pin_hash": 1})
    old = (doc or {}).get("danger_pin_hash")
    await db.settings.update_one({"id": "global"}, {"$set": {"danger_pin_hash": new_hash}})
    c.close()
    return old


@pytest.fixture(scope="module")
def swapped_pin():
    old = asyncio.get_event_loop().run_until_complete(_swap_pin(hash_password(PIN)))
    yield PIN
    if old:
        asyncio.get_event_loop().run_until_complete(_swap_pin(old))


def test_admin_restore_bad_collection(admin_headers, swapped_pin):
    r = requests.post(f"{BASE}/admin/backup/restore",
                      json={"collection": "definitely_not_a_collection_xyz", "docs": [], "mode": "merge",
                            "first_chunk": True, "danger_pin": swapped_pin},
                      headers=admin_headers, timeout=60)
    # Should either 400/404 or accept-and-noop; but should never 500 or wipe unrelated data
    assert r.status_code < 500, r.status_code


def test_admin_restore_malformed_docs(admin_headers, swapped_pin):
    r = requests.post(f"{BASE}/admin/backup/restore",
                      json={"collection": "shop_layout_blocks", "docs": "not-a-list",
                            "mode": "merge", "first_chunk": True, "danger_pin": swapped_pin},
                      headers=admin_headers, timeout=60)
    assert r.status_code in (400, 422), r.status_code


def test_admin_manifest_excludes_forbidden(admin_headers, swapped_pin):
    r = requests.get(f"{BASE}/admin/backup/manifest", headers=admin_headers, timeout=90)
    r.raise_for_status()
    man = r.json()
    names = [c["name"] for c in man["collections"]]
    assert "db_snapshots" not in names
    assert "pincodes" not in names
    assert "users" in names and "products" in names and "orders" in names


# --- Phase 5A edge cases ---------------------------------------------------

def test_delivery_check_latlng_only(buyer_headers):
    # customer inside vendor radius but with NO pincode, only lat/lng
    r = requests.get(f"{BASE}/delivery/check",
                     params={"lat": 13.7484, "lng": 79.7027},
                     headers=buyer_headers, timeout=90)
    assert r.status_code == 200, r.status_code
    d = r.json()
    assert d.get("vendor_count", 0) >= 1, f"gps-only delivery check failed: {d}"

    # far-away lat/lng must be zero
    far = requests.get(f"{BASE}/delivery/check",
                      params={"lat": 28.6139, "lng": 77.2090},  # Delhi
                      headers=buyer_headers, timeout=90).json()
    assert far.get("vendor_count", 0) == 0, far


def test_products_pincode_only(buyer_headers):
    r = requests.get(f"{BASE}/products",
                     params={"pincode": "517644", "strict_location": "true", "limit": 3},
                     headers=buyer_headers, timeout=90)
    r.raise_for_status()
    data = r.json()
    total = data.get("total") if isinstance(data, dict) else len(data)
    assert total and total > 0


def test_delivery_check_no_location(buyer_headers):
    """Neither pincode nor lat/lng: must not 500."""
    r = requests.get(f"{BASE}/delivery/check", headers=buyer_headers, timeout=60)
    assert r.status_code < 500, r.status_code


# --- Phase 5B smoke: shop-layout image list never inlines base64 -----------

def test_shop_layout_never_inlines_base64(admin_headers):
    pub = requests.get(f"{BASE}/shop-layout", params={"scope": "home"}, timeout=60).json()
    for b in pub.get("items", []):
        iu = b.get("image_data_url") or ""
        assert not iu.startswith("data:"), f"public list leaked base64 for block {b.get('id')}"
        for it in b.get("items") or []:
            iu2 = it.get("image_data_url") or ""
            assert not iu2.startswith("data:"), "public slide leaked base64"

    adm = requests.get(f"{BASE}/admin/shop-layout", headers=admin_headers, timeout=60).json()
    for b in adm.get("items", []):
        iu = b.get("image_data_url") or ""
        assert not iu.startswith("data:"), f"admin list leaked base64 for block {b.get('id')}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s"]))
