"""Iter106 — independent review of permanent images + catalogue pagination.

Runs against the PUBLIC preview URL (EXPO_PUBLIC_BACKEND_URL from frontend/.env).
"""
import os
import time
import uuid

import pytest
import requests
from pymongo import MongoClient


def _env(path, key):
    for ln in open(path):
        if ln.startswith(key + "="):
            return ln.split("=", 1)[1].strip().strip('"')
    raise KeyError(key)


ROOT = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or _env("/app/frontend/.env", "EXPO_PUBLIC_BACKEND_URL")).rstrip("/")
BASE = f"{ROOT}/api"
T = 90
ADMIN = {"email": "support@slangcart.com", "password": "3)Ywxtic"}
VENDOR = {"email": "testvendor@test.com", "password": "Test@1234"}
LIVE = "https://images.pexels.com/photos/5650016/pexels-photo-5650016.jpeg"
LIVE2 = "https://images.unsplash.com/photo-1523275335684-37898b6baf30"
LIVE3 = "https://images.pexels.com/photos/1229861/pexels-photo-1229861.jpeg"
DEAD = "https://cdn.shopify.com/s/files/1/0000/0000/definitely-gone-404.jpg"
PNG_1PX = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

MDB = MongoClient(_env("/app/backend/.env", "MONGO_URL"))[_env("/app/backend/.env", "DB_NAME")]
TAG = "TEST_iter106_" + uuid.uuid4().hex[:6]
CREATED: list = []


def _login(c):
    r = requests.post(f"{BASE}/auth/login", json=c, timeout=T)
    assert r.status_code == 200, r.text[:200]
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def ah():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def vh():
    return _login(VENDOR)


@pytest.fixture(scope="module", autouse=True)
def _cleanup():
    yield
    if CREATED:
        MDB.products.delete_many({"id": {"$in": list(CREATED)}})


def mk(ah, **extra):
    body = {"name": f"{TAG} {uuid.uuid4().hex[:4]}", "price": 321, "stock": 7,
            "category": "Electronics", "sub_category": "Audio", "gst_pct": 12,
            "description": "iter106 probe", **extra}
    r = requests.post(f"{BASE}/admin/products", json=body, headers=ah, timeout=T)
    assert r.status_code == 200, r.text[:300]
    d = r.json()
    CREATED.append(d["id"])
    return d


# --- Permanent image on create (Smart Search fix)
def test_external_cover_becomes_permanent(ah):
    d = mk(ah, image_url=LIVE)
    assert d["image_url"].startswith("/api/img/"), d["image_url"]
    assert d.get("image_import_status") == "ok"
    s = MDB.products.find_one({"id": d["id"]}, {"_id": 0, "image_url": 1})
    assert s["image_url"] == d["image_url"]


# --- /api/img serving contract
def test_img_endpoint_contract(ah):
    d = mk(ah, image_url=LIVE)
    full = requests.get(ROOT + d["image_url"], timeout=T)
    assert full.status_code == 200 and full.headers["content-type"].startswith("image/")
    # Cache-Control is asserted against the ORIGIN: the preview edge rewrites
    # it to `no-store`, which is an environment artefact, not app behaviour.
    origin = requests.get("http://localhost:8001" + d["image_url"], timeout=T)
    assert "immutable" in origin.headers.get("cache-control", ""), origin.headers.get("cache-control")
    th = requests.get(ROOT + d["image_url"] + "?w=360&q=72", timeout=T)
    assert th.status_code == 200 and th.headers["content-type"] == "image/jpeg"
    assert len(th.content) < len(full.content)
    assert requests.get(f"{BASE}/img/{'a'*40}.jpg", timeout=T).status_code == 404
    assert requests.get(f"{BASE}/img/not-a-key.jpg", timeout=T).status_code == 400
    assert requests.get(f"{BASE}/img/..%2F..%2Fetc.jpg", timeout=T).status_code in (400, 404)


# --- Shopify object gallery: order + dedupe + flatten
def test_shopify_object_gallery(ah):
    imgs = [{"src": LIVE3, "position": 3}, {"src": LIVE, "position": 1},
            {"src": LIVE2, "position": 2}, {"src": LIVE, "position": 4}, {"url": LIVE3}]
    d = mk(ah, image_url=LIVE, images=imgs)
    g = d["images"]
    assert all(isinstance(x, str) and x.startswith("/api/img/") for x in g), g
    assert len(g) == len(set(g)) == 3, g
    ref = {}
    for u in (LIVE, LIVE2, LIVE3):
        a = MDB.image_assets.find_one({"source_url": u, "ok": True}, {"_id": 0, "ref": 1})
        ref[u] = a["ref"]
    assert g == [ref[LIVE], ref[LIVE2], ref[LIVE3]], "position order not honoured"


# --- Dead URL -> failed + reason, URL kept for retry
def test_dead_url_reports_failure(ah):
    d = mk(ah, image_url=DEAD)
    assert d.get("image_import_status") == "failed"
    f = d["image_import_failures"][0]
    assert f["url"] == DEAD and len(f.get("reason", "")) > 5
    assert not d["image_url"].startswith("/api/img/")


# --- data: URIs untouched
def test_base64_passthrough(ah):
    d = mk(ah, image_url=PNG_1PX)
    s = MDB.products.find_one({"id": d["id"]}, {"_id": 0, "image_url": 1})
    assert s["image_url"] == PNG_1PX


# --- image-health (route ordering regression + auth)
def test_image_health(ah, vh):
    r = requests.get(f"{BASE}/admin/products/image-health", headers=ah, timeout=T)
    assert r.status_code == 200, r.text[:200]
    j = r.json()
    for k in ("total_products", "permanent", "external_pending", "needs_repair", "failed"):
        assert isinstance(j[k], int), k
    assert requests.get(f"{BASE}/admin/products/image-health", timeout=T).status_code in (401, 403)
    assert requests.get(f"{BASE}/admin/products/image-health", headers=vh, timeout=T).status_code in (401, 403)


# --- repair by id keeps business fields
def test_repair_by_id_preserves_fields(ah):
    d = mk(ah, image_url=PNG_1PX)
    MDB.products.update_one({"id": d["id"]}, {"$set": {"image_url": LIVE2, "images": [{"src": LIVE3, "position": 1}]}})
    before = MDB.products.find_one({"id": d["id"]}, {"_id": 0})
    r = requests.post(f"{BASE}/admin/products/repair-images", json={"product_ids": [d["id"]]}, headers=ah, timeout=T)
    assert r.status_code == 200, r.text[:200]
    after = MDB.products.find_one({"id": d["id"]}, {"_id": 0})
    assert after["image_url"].startswith("/api/img/")
    assert all(isinstance(x, str) and x.startswith("/api/img/") for x in after["images"])
    for k in ("price", "stock", "category", "sub_category", "gst_pct", "description", "name"):
        assert after.get(k) == before.get(k), k


# --- retry_failed summary shape
def test_repair_retry_failed_counts(ah):
    d = mk(ah, image_url=DEAD)
    r = requests.post(f"{BASE}/admin/products/repair-images",
                      json={"product_ids": [d["id"]], "retry_failed": True}, headers=ah, timeout=T)
    j = r.json()
    assert r.status_code == 200
    assert j["failed"] == 1 and j["images_failed"] == 1, j
    f = j["failures"][0]
    assert f["url"] == DEAD and f.get("reason") and f.get("product")
    r2 = requests.post(f"{BASE}/admin/products/repair-images", json={"limit": 2, "retry_failed": True},
                       headers=ah, timeout=T)
    j2 = r2.json()
    for k in ("scanned", "repaired", "failed", "images_failed", "failures", "remaining"):
        assert k in j2, k


# --- partial products must not be re-picked forever by the worker
def test_partial_product_not_requeued(ah):
    """A product with one good and one dead photo keeps the dead URL (so it
    can be retried), so it must be excluded from the AUTOMATIC sweep by its
    `partial` status — otherwise the worker re-downloads it forever."""
    from routes.product_images_repair import PENDING_FILTER
    d = mk(ah, image_url=LIVE, images=[LIVE, DEAD])
    assert d.get("image_import_status") == "partial", d.get("image_import_status")
    still_pending = MDB.products.count_documents({"$and": [{"id": d["id"]}, PENDING_FILTER]})
    assert still_pending == 0, ("partial product still matches the background-worker "
                                "'needs_repair' query -> worker re-downloads it forever")
    # …but the admin's "Retry failed photos" must still reach it.
    r = requests.post(f"{BASE}/admin/products/repair-images",
                      json={"product_ids": [d["id"]], "retry_failed": True},
                      headers=ah, timeout=T * 3)
    assert r.status_code == 200 and r.json()["scanned"] == 1


# --- detail never returns objects in images
def test_detail_never_returns_objects(ah):
    d = mk(ah, image_url=PNG_1PX)
    MDB.products.update_one({"id": d["id"]}, {"$set": {"images": [{"src": DEAD, "position": 2}, {"src": LIVE, "position": 1}, {"foo": 1}, None, 5]}})
    r = requests.get(f"{BASE}/products/{d['id']}", timeout=T)
    assert r.status_code == 200, r.text[:200]
    imgs = r.json().get("images") or []
    assert all(isinstance(x, str) for x in imgs), imgs


# --- admin pagination
def test_admin_pagination(ah):
    r = requests.get(f"{BASE}/admin/products", params={"limit": 5, "offset": 0}, headers=ah, timeout=T).json()
    for k in ("items", "total", "limit", "offset", "has_more"):
        assert k in r
    assert r["total"] == MDB.products.count_documents({})
    r2 = requests.get(f"{BASE}/admin/products", params={"limit": 5, "offset": 5}, headers=ah, timeout=T).json()
    a = {x["id"] for x in r["items"]}
    b = {x["id"] for x in r2["items"]}
    assert not (a & b)


def test_admin_full_walk_unique(ah):
    seen, off, total = [], 0, None
    while True:
        r = requests.get(f"{BASE}/admin/products", params={"limit": 300, "offset": off}, headers=ah, timeout=T).json()
        total = r["total"]
        seen += [x["id"] for x in r["items"]]
        if not r["has_more"]:
            break
        off += 300
    assert len(seen) == total
    assert len(set(seen)) == total, f"dupes across pages: {len(seen) - len(set(seen))}"


def test_vendor_pagination_walk(vh):
    seen, off = [], 0
    while True:
        r = requests.get(f"{BASE}/vendor/me/products", params={"limit": 3, "offset": off}, headers=vh, timeout=T).json()
        assert {"items", "total", "has_more"} <= set(r)
        seen += [x["id"] for x in r["items"]]
        if not r["has_more"]:
            break
        off += 3
    assert len(set(seen)) == r["total"] == len(seen)


# --- vendor restore: image counters + no duplicates on rerun
def test_vendor_import_counters_and_rerun(vh):
    name = f"{TAG} restore"
    prods = [{"name": name, "price": 99, "stock": 1, "category": "Electronics",
              "image_url": LIVE, "images": [{"src": LIVE2, "position": 2}, {"src": LIVE, "position": 1}, DEAD]}]
    try:
        r = requests.post(f"{BASE}/vendor/me/catalogue/import", json={"products": prods, "mode": "merge"}, headers=vh, timeout=T)
        assert r.status_code == 200, r.text[:300]
        j = r.json()
        for k in ("created", "skipped", "images_imported", "images_reused", "images_failed", "images_deferred", "image_failures"):
            assert k in j, k
        assert j["created"] == 1 and j["images_failed"] >= 1
        r2 = requests.post(f"{BASE}/vendor/me/catalogue/import", json={"products": prods, "mode": "merge"}, headers=vh, timeout=T)
        assert r2.status_code == 200
        n = MDB.products.count_documents({"name": name})
        assert n == 1, f"re-running the same restore duplicated the product ({n} copies)"
    finally:
        for p in MDB.products.find({"name": name}, {"_id": 0, "id": 1}):
            CREATED.append(p["id"])
