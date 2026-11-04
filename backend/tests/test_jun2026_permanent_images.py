"""Jun-2026 — Permanent product images + catalogue pagination.

Covers the owner's four reports:
  A  Smart Search images go blank after some time
     → external URLs must be copied into permanent storage on save
  B  Shopify-restore images missing (primary + gallery)
     → `image_url` maps to the cover, `images[]` to the gallery, Shopify
       `Image Position` is honoured, duplicates removed, objects flattened
  C  Imported products crash the Android product screen
     → the API must never hand the client an object inside `images[]`
  D  Backup restore / product lists stop at 200
     → admin and vendor product lists are paged with a true total

Run:  python -m pytest tests/test_jun2026_permanent_images.py -q
"""
import os
import uuid

import pytest
import requests
from pymongo import MongoClient

BASE = os.environ.get("PROBE_BASE", "http://localhost:8001/api")
T = 60

ADMIN = {"email": "support@slangcart.com", "password": "3)Ywxtic"}
VENDOR = {"email": "testvendor@test.com", "password": "Test@1234"}

#: A real, stable, permissively-licensed photo we are allowed to fetch.
LIVE_IMAGE = "https://images.pexels.com/photos/5650016/pexels-photo-5650016.jpeg"
LIVE_IMAGE_2 = "https://images.unsplash.com/photo-1523275335684-37898b6baf30"
#: Guaranteed-dead reference — stands in for an expired CDN object.
DEAD_IMAGE = "https://cdn.shopify.com/s/files/1/0000/0000/definitely-gone-404.jpg"


def _env(path, key):
    for ln in open(path):
        if ln.startswith(key + "="):
            return ln.split("=", 1)[1].strip().strip('"')
    raise KeyError(key)


MDB = MongoClient(_env("/app/backend/.env", "MONGO_URL"))[_env("/app/backend/.env", "DB_NAME")]
TAG = uuid.uuid4().hex[:6]
_CREATED: list = []


def tok(creds):
    r = requests.post(f"{BASE}/auth/login", json=creds, timeout=T)
    assert r.status_code == 200, r.text[:200]
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {tok(ADMIN)}"}


@pytest.fixture(scope="module")
def vendor_h():
    return {"Authorization": f"Bearer {tok(VENDOR)}"}


@pytest.fixture(scope="module", autouse=True)
def _cleanup():
    yield
    if _CREATED:
        MDB.products.delete_many({"id": {"$in": _CREATED}})


def _mk_product(admin_h, **extra):
    body = {
        "name": f"PermImg {TAG} {uuid.uuid4().hex[:4]}",
        "price": 499, "stock": 5, "category": "Electronics",
        "description": "permanent-image probe",
        **extra,
    }
    r = requests.post(f"{BASE}/admin/products", json=body, headers=admin_h, timeout=T)
    assert r.status_code == 200, r.text[:300]
    doc = r.json()
    _CREATED.append(doc["id"])
    return doc


# ─────────────────────────── A — Smart Search ───────────────────────────

def test_a1_external_cover_is_copied_to_permanent_storage(admin_h):
    """The core fix: an outside URL never survives into the stored doc."""
    doc = _mk_product(admin_h, image_url=LIVE_IMAGE)
    assert doc["image_url"].startswith("/api/img/"), doc["image_url"]
    assert doc.get("image_import_status") == "ok"
    stored = MDB.products.find_one({"id": doc["id"]}, {"_id": 0, "image_url": 1})
    assert stored["image_url"] == doc["image_url"], "DB must hold the permanent ref, not the CDN URL"


def test_a2_permanent_ref_is_servable_and_cacheable(admin_h):
    doc = _mk_product(admin_h, image_url=LIVE_IMAGE)
    r = requests.get(f"{BASE.rsplit('/api', 1)[0]}{doc['image_url']}", timeout=T)
    assert r.status_code == 200, r.text[:200]
    assert r.headers["content-type"].startswith("image/")
    assert "immutable" in r.headers.get("cache-control", "")
    assert len(r.content) > 1000
    # Thumbnail variant used by the shop grid
    r2 = requests.get(f"{BASE.rsplit('/api', 1)[0]}{doc['image_url']}?w=360&q=72", timeout=T)
    assert r2.status_code == 200 and len(r2.content) < len(r.content)


def test_a3_image_survives_a_backend_restart(admin_h):
    """Bytes live in our own database, so nothing is lost on restart and the
    reference keeps resolving — this is what the old inline/temporary
    approaches could not guarantee."""
    doc = _mk_product(admin_h, image_url=LIVE_IMAGE)
    key = doc["image_url"].rsplit("/", 1)[-1]
    row = MDB.product_image_files.find_one({"_id": key})
    assert row and row.get("bytes", 0) > 1000
    assert row["content_type"].startswith("image/")


def test_a4_same_photo_twice_is_stored_once(admin_h):
    a = _mk_product(admin_h, image_url=LIVE_IMAGE)
    b = _mk_product(admin_h, image_url=LIVE_IMAGE)
    assert a["image_url"] == b["image_url"], "content-addressed storage must de-duplicate"


def test_a5_unfetchable_source_is_reported_not_stored(admin_h):
    """An image we can't legally/technically fetch must be recorded with a
    reason. The original URL is KEPT so the admin can retry it — but the
    product is flagged `failed`, which is what makes the shop show a
    placeholder instead of pretending the photo is fine."""
    doc = _mk_product(admin_h, image_url=DEAD_IMAGE)
    assert doc["image_import_status"] == "failed"
    assert not doc["image_url"].startswith("/api/img/"), "a dead URL is never passed off as stored"
    assert doc["image_url"] == DEAD_IMAGE, "the source URL must survive for a retry"
    fails = doc.get("image_import_failures") or []
    assert fails and fails[0]["url"] == DEAD_IMAGE
    assert fails[0]["reason"], "every failure carries a human-readable reason"


def test_a6_a_live_gallery_photo_is_promoted_when_the_cover_dies(admin_h):
    doc = _mk_product(admin_h, image_url=DEAD_IMAGE, images=[LIVE_IMAGE_2])
    assert doc["image_url"].startswith("/api/img/"), "gallery photo should become the thumbnail"
    assert doc["image_import_status"] == "partial"


def test_a8_recorded_failure_can_be_recovered_by_a_retry(admin_h):
    """The source URL survives a failed import, so 'Retry failed photos'
    has something to work with instead of an empty field."""
    doc = _mk_product(admin_h, image_url=DEAD_IMAGE)
    r = requests.post(
        f"{BASE}/admin/products/repair-images",
        json={"product_ids": [doc["id"]], "retry_failed": True},
        headers=admin_h, timeout=T * 3,
    )
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert body["scanned"] == 1
    assert body["images_failed"] >= 1, "photo-level failures are counted separately"
    assert body["failed"] == 1, "and the product itself is counted once"
    stored = MDB.products.find_one({"id": doc["id"]}, {"_id": 0, "image_import_failures": 1})
    assert stored["image_import_failures"][0]["url"] == DEAD_IMAGE


def test_a7_base64_covers_are_left_untouched(admin_h):
    """Existing vendor uploads keep working exactly as before."""
    tiny = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
            "AAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")
    doc = _mk_product(admin_h, image_url=tiny)
    assert doc["image_url"].startswith("data:image/"), "inline uploads must not be rewritten"


# ──────────────────── B — Shopify gallery mapping ───────────────────────

def test_b1_shopify_object_gallery_is_flattened_ordered_and_deduped(admin_h):
    """`images` arriving as Shopify objects with an `Image Position`."""
    from core.image_store import normalize_gallery
    out = normalize_gallery([
        {"src": "https://cdn.example.com/c.jpg", "position": 3},
        {"src": "https://cdn.example.com/a.jpg", "position": 1},
        {"src": "https://cdn.example.com/b.jpg", "position": 2},
        {"src": "https://cdn.example.com/a.jpg", "position": 4},   # duplicate
        "https://cdn.example.com/d.jpg",                            # no position
        {"url": "https://cdn.example.com/e.jpg"},                   # alt key
        {"nonsense": 1},                                            # unusable
    ])
    assert out == [
        "https://cdn.example.com/a.jpg",
        "https://cdn.example.com/b.jpg",
        "https://cdn.example.com/c.jpg",
        "https://cdn.example.com/d.jpg",
        "https://cdn.example.com/e.jpg",
    ]


def test_b2_primary_maps_to_cover_and_array_to_gallery(admin_h):
    doc = _mk_product(admin_h, image_url=LIVE_IMAGE, images=[LIVE_IMAGE, LIVE_IMAGE_2])
    assert doc["image_url"].startswith("/api/img/")
    assert len(doc["images"]) == 2, "both unique gallery photos kept"
    assert all(u.startswith("/api/img/") for u in doc["images"])
    # The cover is the first gallery entry (same photo) — de-duped, not lost.
    assert doc["images"][0] == doc["image_url"]


@pytest.mark.parametrize("n", [1, 5, 10, 15])
def test_b3_many_images_per_product(admin_h, n):
    """1 / 5 / 10 / 15+ images, as the owner asked. Unique URLs are all
    preserved, the live ones become permanent references, the dead ones are
    reported and kept for a retry, and the THUMBNAIL is always one that
    actually works."""
    urls = [LIVE_IMAGE, LIVE_IMAGE_2] + [f"{DEAD_IMAGE}?i={i}" for i in range(n)]
    urls = urls[:max(2, n)]
    doc = _mk_product(admin_h, image_url=urls[0], images=urls)
    gallery = doc["images"]
    assert all(isinstance(u, str) for u in gallery), "never an object on the wire"
    assert len(set(gallery)) == len(gallery), "no duplicates"
    assert len(gallery) == len(urls), "every unique image is kept"
    assert doc["image_url"].startswith("/api/img/"), "thumbnail must be a working photo"
    assert sum(1 for u in gallery if u.startswith("/api/img/")) >= 2
    assert doc["image_import_status"] in ("ok", "partial")


# ─────────────── C — the Android product-screen crash ───────────────────

def test_c1_api_never_returns_an_object_inside_images(admin_h):
    """Reproduces the crash input: a raw Shopify doc written straight into
    Mongo. The public endpoints must still hand the app plain strings."""
    pid = str(uuid.uuid4())
    _CREATED.append(pid)
    MDB.products.insert_one({
        "id": pid, "name": f"Crasher {TAG}", "price": 199, "stock": 3,
        "is_published": True, "category": "Electronics",
        "image_url": {"src": LIVE_IMAGE},
        "images": [{"src": LIVE_IMAGE, "position": 1}, {"src": LIVE_IMAGE_2, "position": 2}],
    })
    r = requests.get(f"{BASE}/products/{pid}", timeout=T)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert isinstance(body["image_url"], str)
    assert all(isinstance(x, str) for x in body["images"]), body["images"]


def test_c2_lazy_repair_rewrites_an_opened_product(admin_h):
    """Opening a product with outside links schedules a permanent copy."""
    import time
    pid = str(uuid.uuid4())
    _CREATED.append(pid)
    MDB.products.insert_one({
        "id": pid, "name": f"LazyRepair {TAG}", "price": 299, "stock": 2,
        "is_published": True, "category": "Electronics",
        "image_url": LIVE_IMAGE, "images": [LIVE_IMAGE_2],
    })
    assert requests.get(f"{BASE}/products/{pid}", timeout=T).status_code == 200
    for _ in range(30):
        time.sleep(1)
        doc = MDB.products.find_one({"id": pid}, {"_id": 0, "image_url": 1})
        if str(doc.get("image_url") or "").startswith("/api/img/"):
            break
    assert str(doc["image_url"]).startswith("/api/img/"), "lazy repair never ran"


# ───────────────── D — repair tooling + pagination ──────────────────────

def test_d1_image_health_reports_counts(admin_h):
    r = requests.get(f"{BASE}/admin/products/image-health", headers=admin_h, timeout=T)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    for key in ("total_products", "permanent", "external_pending", "needs_repair", "failed"):
        assert key in body, key
    assert body["total_products"] >= 1


def test_d2_repair_endpoint_fixes_broken_references(admin_h):
    pid = str(uuid.uuid4())
    _CREATED.append(pid)
    MDB.products.insert_one({
        "id": pid, "name": f"Repairable {TAG}", "price": 149, "stock": 1,
        "is_published": True, "category": "Electronics",
        "image_url": LIVE_IMAGE, "images": [],
    })
    r = requests.post(
        f"{BASE}/admin/products/repair-images",
        json={"limit": 50, "product_ids": [pid]}, headers=admin_h, timeout=T * 3,
    )
    assert r.status_code == 200, r.text[:300]
    assert r.json()["scanned"] >= 1
    doc = MDB.products.find_one({"id": pid}, {"_id": 0, "image_url": 1})
    assert doc["image_url"].startswith("/api/img/")


def test_d3_repair_never_touches_price_stock_or_category(admin_h):
    pid = str(uuid.uuid4())
    _CREATED.append(pid)
    MDB.products.insert_one({
        "id": pid, "name": f"Untouched {TAG}", "price": 777, "stock": 9,
        "is_published": True, "category": "Electronics", "sub_category": "Audio",
        "gst_pct": 18, "description": "keep me", "image_url": LIVE_IMAGE_2,
    })
    requests.post(f"{BASE}/admin/products/repair-images",
                  json={"product_ids": [pid]}, headers=admin_h, timeout=T * 3)
    doc = MDB.products.find_one({"id": pid}, {"_id": 0})
    assert doc["price"] == 777 and doc["stock"] == 9
    assert doc["category"] == "Electronics" and doc["sub_category"] == "Audio"
    assert doc["gst_pct"] == 18 and doc["description"] == "keep me"


def test_d4_admin_product_list_is_paged_with_a_true_total(admin_h):
    r = requests.get(f"{BASE}/admin/products", params={"limit": 5, "offset": 0},
                     headers=admin_h, timeout=T)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert set(["items", "total", "has_more", "limit", "offset"]).issubset(body)
    assert len(body["items"]) <= 5
    assert body["total"] == MDB.products.count_documents({})
    if body["total"] > 5:
        assert body["has_more"] is True
        page2 = requests.get(f"{BASE}/admin/products", params={"limit": 5, "offset": 5},
                             headers=admin_h, timeout=T).json()
        ids1 = {x["id"] for x in body["items"]}
        ids2 = {x["id"] for x in page2["items"]}
        assert not (ids1 & ids2), "pages must not overlap"


def test_d5_vendor_product_list_is_paged(vendor_h):
    r = requests.get(f"{BASE}/vendor/me/products", params={"limit": 3, "offset": 0},
                     headers=vendor_h, timeout=T)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert set(["items", "total", "has_more"]).issubset(body)
    assert len(body["items"]) <= 3
    assert isinstance(body["total"], int)


def test_d6_whole_vendor_catalogue_is_reachable_by_paging(vendor_h):
    """The 200/1000-row cliff is gone: paging reaches every product."""
    seen, offset = set(), 0
    total = None
    while True:
        body = requests.get(f"{BASE}/vendor/me/products",
                            params={"limit": 50, "offset": offset},
                            headers=vendor_h, timeout=T).json()
        total = body["total"]
        seen.update(x["id"] for x in body["items"])
        if not body["has_more"] or not body["items"]:
            break
        offset += 50
    assert len(seen) == total, f"paged {len(seen)} of {total}"


# ──────────── E — fixes for the iteration-106 code review ────────────────

def test_e1_paging_is_stable_when_timestamps_collide(admin_h, vendor_h):
    """Bulk imports write hundreds of products in the same second. Sorting on
    `created_at` alone gave Mongo an unstable order, so skip/limit paging
    overlapped and silently dropped products from the admin list, the vendor
    list and the vendor backup FILE."""
    def page_all(url, headers, step):
        ids, offset, total = [], 0, None
        while True:
            body = requests.get(url, params={"limit": step, "offset": offset},
                                headers=headers, timeout=T).json()
            total = body["total"]
            ids += [x["id"] for x in body["items"]]
            if not body["has_more"] or not body["items"]:
                break
            offset += step
        return ids, total

    for url, headers, step in (
        (f"{BASE}/admin/products", admin_h, 17),
        (f"{BASE}/vendor/me/products", vendor_h, 7),
    ):
        ids, total = page_all(url, headers, step)
        assert len(ids) == len(set(ids)), f"{url}: pages overlap"
        assert len(set(ids)) == total, f"{url}: paged {len(set(ids))} of {total}"


def test_e2_vendor_export_file_has_no_gaps_or_duplicates(vendor_h):
    names, offset, total = [], 0, 0
    while True:
        body = requests.get(f"{BASE}/vendor/me/catalogue/export",
                            params={"offset": offset, "limit": 10},
                            headers=vendor_h, timeout=T).json()
        total = body["total"]
        names += [p.get("name") for p in body["products"]]
        if not body["has_more"]:
            break
        offset += 10
    assert len(names) == total
    assert len(set(names)) == len(names), "the exported file repeats products"


def test_e3_restoring_the_same_file_twice_does_not_duplicate(vendor_h):
    """'Allow administrators to retry failed image imports without
    duplicating products' — a merge restore is keyed on the shop's own
    product name, so a re-run updates instead of inserting."""
    tag = uuid.uuid4().hex[:6]
    products = [{"name": f"IDEM_{tag}_{i}", "price": 100 + i, "stock": 4,
                 "category": "Electronics", "image_url": ""} for i in range(3)]
    first = requests.post(f"{BASE}/vendor/me/catalogue/import",
                          json={"products": products, "mode": "merge", "first_chunk": True},
                          headers=vendor_h, timeout=T * 3).json()
    second = requests.post(f"{BASE}/vendor/me/catalogue/import",
                           json={"products": products, "mode": "merge"},
                           headers=vendor_h, timeout=T * 3).json()
    assert first["created"] == 3 and first.get("updated", 0) == 0
    assert second["created"] == 0 and second["updated"] == 3
    found = requests.get(f"{BASE}/vendor/me/products",
                         params={"limit": 300, "q": f"IDEM_{tag}"},
                         headers=vendor_h, timeout=T).json()
    assert found["total"] == 3, "a second restore created duplicates"
    for row in found["items"]:
        requests.delete(f"{BASE}/vendor/me/products/{row['id']}", headers=vendor_h, timeout=T)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:27017/x.jpg",
    "http://localhost/x.jpg",
    "http://169.254.169.254/latest/meta-data/",
    "http://10.0.0.5/x.jpg",
    "http://192.168.1.1/x.jpg",
    "http://[::1]/x.jpg",
    "https://example.com:2375/x.jpg",
])
def test_e4_image_fetcher_refuses_internal_targets(url):
    """A vendor controls these URLs, so the downloader must never become a
    port scanner for the cluster — and the refusal must not leak which
    internal ports are open."""
    from urllib.parse import urlparse
    from core.image_store import _blocked_target
    reason = _blocked_target(urlparse(url))
    assert reason, f"{url} was not refused"
    assert "public web address" in reason or "resolved" in reason
    assert "27017" not in reason and "refused" not in reason.lower()


def test_e5_partial_products_leave_the_automatic_queue(admin_h):
    """One good + one dead photo = `partial`. The product keeps the dead URL
    for a retry, so it must be excluded from the automatic sweep by status or
    the worker loops on it forever and starves every other product."""
    from routes.product_images_repair import PENDING_FILTER
    doc = _mk_product(admin_h, image_url=LIVE_IMAGE, images=[LIVE_IMAGE, DEAD_IMAGE])
    assert doc["image_import_status"] == "partial"
    assert MDB.products.count_documents({"$and": [{"id": doc["id"]}, PENDING_FILTER]}) == 0
