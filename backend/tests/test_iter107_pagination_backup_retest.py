"""Iter107 — RETEST of defect #5: scalable pagination + complete backup/restore.

Uses the PUBLIC preview URL. A throw-away approved vendor (TEST_iter107_*) is
created directly in Mongo so the destructive `replace` restore and the 500-row
scale restore never touch testvendor@test.com's real catalogue. Everything this
suite creates is removed by id / by the throw-away vendor_id at teardown.
"""
import json
import os
import uuid

import bcrypt
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
T = 120
ADMIN = {"email": "support@slangcart.com", "password": "3)Ywxtic"}
VENDOR = {"email": "testvendor@test.com", "password": "Test@1234"}
MDB = MongoClient(_env("/app/backend/.env", "MONGO_URL"))[_env("/app/backend/.env", "DB_NAME")]

TAG = "TEST_iter107_" + uuid.uuid4().hex[:6]
TV_ID = str(uuid.uuid4())
TV_EMAIL = f"{TAG.lower()}@example.com"
TV_PW = "Test@1234"
REAL_VENDOR_PRODUCT_IDS: list = []   # products created on testvendor by this suite


def _login(c):
    r = requests.post(f"{BASE}/auth/login", json=c, timeout=T)
    assert r.status_code == 200, r.text[:300]
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _walk(url, headers, limit, params=None, items_key="items"):
    """Walk a skip/limit endpoint to the end; return (all_items, pages)."""
    out, pages, off = [], [], 0
    while True:
        p = {"limit": limit, "offset": off, **(params or {})}
        r = requests.get(url, headers=headers, params=p, timeout=T)
        assert r.status_code == 200, f"{url} off={off}: {r.status_code} {r.text[:200]}"
        d = r.json()
        pages.append(d)
        got = d[items_key]
        out.extend(got)
        if not d["has_more"]:
            break
        assert got, f"has_more=true but empty page at offset {off}"
        off += len(got)
        assert len(pages) < 500, "runaway pagination"
    return out, pages


@pytest.fixture(scope="module")
def ah():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def vh():
    return _login(VENDOR)


@pytest.fixture(scope="module")
def tvh():
    """Throw-away approved vendor, created + removed by this suite."""
    MDB.users.insert_one({
        "id": TV_ID, "name": TAG, "email": TV_EMAIL, "phone": "9" + uuid.uuid4().int.__str__()[:9],
        "password_hash": bcrypt.hashpw(TV_PW.encode(), bcrypt.gensalt()).decode(),
        "role": "user", "admin_role": None, "is_blocked": False, "approval_status": "approved",
        "registration_paid": True, "is_vendor": True, "vendor_status": "approved",
        "is_vendor_approved": True, "shop_name": TAG, "pincode": "517644",
        "referral_code": uuid.uuid4().hex[:6].upper(), "wallet_balance": 0.0,
        "created_at": "2026-01-01T00:00:00+00:00",
    })
    yield _login({"email": TV_EMAIL, "password": TV_PW})


@pytest.fixture(scope="module", autouse=True)
def _cleanup():
    yield
    MDB.products.delete_many({"vendor_id": TV_ID})
    if REAL_VENDOR_PRODUCT_IDS:
        MDB.products.delete_many({"id": {"$in": REAL_VENDOR_PRODUCT_IDS}})
    MDB.users.delete_many({"id": TV_ID})


def _rows(n, prefix):
    return [{"name": f"{prefix} {i:04d}", "price": 100 + i, "stock": 3,
             "category": "Electronics", "sub_category": "Audio",
             "description": "iter107 restore probe"} for i in range(n)]


def _import(h, rows, mode="merge", chunk=25):
    rep = {"created": 0, "updated": 0, "wiped": 0, "skipped": 0}
    for i in range(0, len(rows), chunk):
        r = requests.post(f"{BASE}/vendor/me/catalogue/import", headers=h, timeout=T, json={
            "products": rows[i:i + chunk], "mode": mode, "first_chunk": i == 0})
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        for k in ("created", "updated", "wiped", "images_imported", "images_failed",
                  "images_deferred", "image_failures", "skipped", "mode"):
            assert k in d, f"restore report missing {k}: {d}"
        rep["created"] += d["created"]; rep["updated"] += d["updated"]
        rep["wiped"] += d["wiped"]; rep["skipped"] += len(d["skipped"])
    return rep


# ── Admin product list: full walk ──────────────────────────────────────────
def test_admin_list_full_walk_no_dupes_no_missing(ah):
    items, pages = _walk(f"{BASE}/admin/products", ah, 60)
    ids = [p["id"] for p in items]
    total = pages[0]["total"]
    assert len(ids) == len(set(ids)), f"duplicates: {len(ids) - len(set(ids))}"
    assert len(ids) == total, f"walked {len(ids)} != total {total}"
    assert set(ids) == {p["id"] for p in MDB.products.find({}, {"id": 1})}
    assert pages[-1]["has_more"] is False


def test_admin_list_limit_clamped_300(ah):
    r = requests.get(f"{BASE}/admin/products", headers=ah, params={"limit": 5000}, timeout=T)
    assert r.status_code == 200 and r.json()["limit"] == 300


# ── Admin list: server-side search + paging ────────────────────────────────
def test_admin_search_total_is_filtered_and_paging_clean(ah):
    full = requests.get(f"{BASE}/admin/products", headers=ah, params={"limit": 1}, timeout=T).json()["total"]
    term = "Electronics"
    items, pages = _walk(f"{BASE}/admin/products", ah, 20, {"q": term})
    ids = [p["id"] for p in items]
    assert pages[0]["total"] < full, "q total equals full catalogue"
    assert len(ids) == len(set(ids)) == pages[0]["total"]
    rx = {"$regex": term, "$options": "i"}
    exp = MDB.products.count_documents({"$or": [{"name": rx}, {"brand": rx}, {"category": rx},
                                                {"sub_category": rx}, {"tags": rx}]})
    assert pages[0]["total"] == exp


def test_admin_vendor_filter_paging(ah, vh):
    vid = MDB.users.find_one({"email": VENDOR["email"]}, {"id": 1})["id"]
    items, pages = _walk(f"{BASE}/admin/products", ah, 20, {"vendor_id": vid})
    ids = [p["id"] for p in items]
    assert len(ids) == len(set(ids)) == pages[0]["total"] == MDB.products.count_documents({"vendor_id": vid})


# ── Vendor own list: full walk ─────────────────────────────────────────────
def test_vendor_list_full_walk(vh):
    vid = MDB.users.find_one({"email": VENDOR["email"]}, {"id": 1})["id"]
    items, pages = _walk(f"{BASE}/vendor/me/products", vh, 60)
    ids = [p["id"] for p in items]
    assert len(ids) == len(set(ids)) == pages[0]["total"] == MDB.products.count_documents({"vendor_id": vid})
    assert pages[-1]["has_more"] is False


def test_vendor_list_search_paging(vh):
    items, pages = _walk(f"{BASE}/vendor/me/products", vh, 20, {"q": "a"})
    ids = [p["id"] for p in items]
    assert len(ids) == len(set(ids)) == pages[0]["total"]


# ── Vendor export: complete ────────────────────────────────────────────────
def test_vendor_export_complete(vh):
    vid = MDB.users.find_one({"email": VENDOR["email"]}, {"id": 1})["id"]
    rows, pages = _walk(f"{BASE}/vendor/me/catalogue/export", vh, 25, items_key="products")
    names = [r["name"] for r in rows]
    assert len(rows) == pages[0]["total"] == MDB.products.count_documents({"vendor_id": vid})
    assert len(set(names)) == len(names)
    assert all("id" not in r and "vendor_id" not in r for r in rows)


# ── Admin dump / streamed file ─────────────────────────────────────────────
@pytest.mark.parametrize("coll,limit", [("products", 25), ("users", 200), ("orders", 200)])
def test_admin_dump_walk(ah, coll, limit):
    docs, pages = _walk(f"{BASE}/admin/backup/dump", ah, limit, {"collection": coll}, items_key="docs")
    # _id is stripped by _json_safe → key on `id` when present, else full content
    keys = [d.get("id") or json.dumps(d, sort_keys=True, default=str) for d in docs]
    assert len(keys) == len(set(keys)), "duplicate _id in dump"
    assert len(docs) == pages[0]["total"] == MDB[coll].count_documents({})
    for p in pages:
        assert {"total", "offset", "limit", "has_more"} <= set(p)


def test_admin_streamed_backup_complete(ah):
    r = requests.get(f"{BASE}/admin/backup/file", headers=ah, timeout=300)
    assert r.status_code == 200, r.text[:200]
    data = r.json()
    assert data["format"] == "slangcart.app-backup"
    c = data["collections"]
    for coll in ("products", "users", "orders"):
        assert len(c[coll]) == MDB[coll].count_documents({}), coll
    pids = [d.get("id") for d in c["products"]]
    assert len(pids) == len(set(pids))


# ── Restore idempotency (merge twice) on the REAL vendor, own TEST rows only ──
def test_restore_merge_idempotent_on_testvendor(vh):
    vid = MDB.users.find_one({"email": VENDOR["email"]}, {"id": 1})["id"]
    rows = _rows(6, f"{TAG}_idem")
    before = MDB.products.count_documents({"vendor_id": vid})
    r1 = _import(vh, rows)
    REAL_VENDOR_PRODUCT_IDS.extend(p["id"] for p in MDB.products.find(
        {"vendor_id": vid, "name": {"$in": [x["name"] for x in rows]}}, {"id": 1}))
    assert r1["created"] == 6 and r1["updated"] == 0
    mid = MDB.products.count_documents({"vendor_id": vid})
    assert mid == before + 6
    rows2 = [{**x, "price": x["price"] + 1} for x in rows]
    r2 = _import(vh, rows2)
    assert r2["created"] == 0 and r2["updated"] == 6, r2
    assert MDB.products.count_documents({"vendor_id": vid}) == mid
    p = MDB.products.find_one({"vendor_id": vid, "name": rows[0]["name"]})
    assert float(p["price"]) == float(rows2[0]["price"])


def test_restore_dupe_names_inside_one_chunk(tvh):
    """Two rows with the SAME name in one file are two real products.

    The owner's complaint was that a restore silently lost products, so a file
    listing "Red Saree" twice must restore BOTH rows — collapsing them would
    be the very data loss we are fixing. What must not happen is growth on a
    repeat restore: the second run has to claim each existing row once and
    report `updated`, leaving the count at 2.
    """
    rows = _rows(1, f"{TAG}_dupchunk") * 2
    r = _import(tvh, rows)
    n = MDB.products.count_documents({"vendor_id": TV_ID, "name": rows[0]["name"]})
    assert n == 2 and r["created"] == 2, f"a product was dropped: {n} ({r})"

    r2 = _import(tvh, rows)
    n2 = MDB.products.count_documents({"vendor_id": TV_ID, "name": rows[0]["name"]})
    MDB.products.delete_many({"vendor_id": TV_ID, "name": rows[0]["name"]})
    assert n2 == 2, f"repeat restore duplicated same-named rows: {n2} ({r2})"
    assert r2["updated"] == 2 and r2["created"] == 0, r2


def test_merge_does_not_unpublish_a_live_product(tvh):
    """Restoring over a running shop must not take matched products offline."""
    rows = _rows(1, f"{TAG}_live")
    _import(tvh, rows)
    pid = MDB.products.find_one({"vendor_id": TV_ID, "name": rows[0]["name"]})["id"]
    MDB.products.update_one({"id": pid}, {"$set": {"is_published": True}})
    rows[0]["price"] = 999
    _import(tvh, rows)
    p = MDB.products.find_one({"id": pid})
    MDB.products.delete_one({"id": pid})
    assert p["is_published"] is True, "a live product was unpublished by a restore"
    assert float(p["price"]) == 999.0, "the restore did not refresh the product"


# ── Restore at scale (500) + full paging on throw-away vendor ──────────────
def test_restore_500_then_page_everything(tvh, ah):
    rows = _rows(520, f"{TAG}_scale")
    rep = _import(tvh, rows)
    assert rep["created"] == 520 and rep["skipped"] == 0, rep
    assert MDB.products.count_documents({"vendor_id": TV_ID}) == 520
    items, pages = _walk(f"{BASE}/vendor/me/products", tvh, 60)
    assert len({p["id"] for p in items}) == len(items) == pages[0]["total"] == 520
    items, pages = _walk(f"{BASE}/admin/products", ah, 60, {"vendor_id": TV_ID})
    assert len({p["id"] for p in items}) == len(items) == pages[0]["total"] == 520
    exp, _ = _walk(f"{BASE}/vendor/me/catalogue/export", tvh, 25, items_key="products")
    assert len(exp) == len({e["name"] for e in exp}) == 520
    # second merge of the whole export: no growth
    rep2 = _import(tvh, exp)
    assert rep2["created"] == 0 and rep2["updated"] == 520, rep2
    assert MDB.products.count_documents({"vendor_id": TV_ID}) == 520


def test_restore_replace_wipes_and_restores(tvh):
    prior = MDB.products.count_documents({"vendor_id": TV_ID})
    assert prior > 0
    rows = _rows(40, f"{TAG}_replace")
    rep = _import(tvh, rows, mode="replace")
    assert rep["wiped"] == prior, rep
    assert rep["created"] == 40
    names = {p["name"] for p in MDB.products.find({"vendor_id": TV_ID}, {"name": 1})}
    assert names == {x["name"] for x in rows}


def test_restore_bad_mode_400(tvh):
    r = requests.post(f"{BASE}/vendor/me/catalogue/import", headers=tvh, timeout=T,
                      json={"products": [], "mode": "nuke"})
    assert r.status_code == 400


def test_restore_skips_invalid_rows(tvh):
    r = requests.post(f"{BASE}/vendor/me/catalogue/import", headers=tvh, timeout=T, json={
        "products": [{"name": "", "price": 10}, {"name": f"{TAG}_zero", "price": 0}, "x"], "mode": "merge"})
    assert r.status_code == 200
    d = r.json()
    assert d["created"] == 0 and len(d["skipped"]) == 3


# ── Regression guard ───────────────────────────────────────────────────────
def test_public_products_and_detail_cart_wishlist(vh):
    r = requests.get(f"{BASE}/products", timeout=T)
    assert r.status_code == 200
    d = r.json()
    lst = d if isinstance(d, list) else d.get("items", [])
    assert lst, "public list empty"
    pid = next(p["id"] for p in lst if not str(p.get("name", "")).startswith("TEST_"))
    r = requests.get(f"{BASE}/products/{pid}", timeout=T)
    assert r.status_code == 200 and r.json()["id"] == pid
    r = requests.get(f"{BASE}/products", params={"category": lst[0].get("category")}, timeout=T)
    assert r.status_code == 200
    buyer = _login({"email": "testbuyer@test.com", "password": "Test@1234"})
    was_saved = pid in json.dumps(requests.get(f"{BASE}/me/wishlist", headers=buyer, timeout=T).json())
    r = requests.post(f"{BASE}/products/{pid}/save", headers=buyer, timeout=T)
    assert r.status_code == 200, r.text[:200]
    if not r.json()["saved"]:
        r = requests.post(f"{BASE}/products/{pid}/save", headers=buyer, timeout=T)
    assert r.json()["saved"] is True
    wl = requests.get(f"{BASE}/me/wishlist", headers=buyer, timeout=T)
    assert wl.status_code == 200 and pid in json.dumps(wl.json())
    if not was_saved:
        requests.post(f"{BASE}/products/{pid}/save", headers=buyer, timeout=T)
    had = pid in json.dumps(requests.get(f"{BASE}/cart", headers=buyer, timeout=T).json())
    r = requests.post(f"{BASE}/cart/add", headers=buyer, timeout=T, json={"product_id": pid, "qty": 1})
    assert r.status_code == 200, r.text[:300]
    c = requests.get(f"{BASE}/cart", headers=buyer, timeout=T)
    assert c.status_code == 200 and pid in json.dumps(c.json())
    if not had:
        requests.post(f"{BASE}/cart/remove", headers=buyer, timeout=T, json={"product_id": pid})


def test_restore_same_name_two_products_second_merge(tvh):
    """Shop legitimately has 2 products with the SAME name (e.g. sizes).
    Re-merging the export must not collapse both rows onto one product."""
    nm = f"{TAG}_samename"
    rows = [{"name": nm, "price": 111, "stock": 1, "category": "Electronics"},
            {"name": nm, "price": 222, "stock": 1, "category": "Electronics"}]
    _import(tvh, rows)
    r2 = _import(tvh, rows)
    prices = sorted(float(p["price"]) for p in MDB.products.find({"vendor_id": TV_ID, "name": nm}))
    MDB.products.delete_many({"vendor_id": TV_ID, "name": nm})
    assert prices == [111.0, 222.0], f"after 2nd merge prices={prices} report={r2}"


def test_admin_restore_requires_valid_pin(ah):
    r = requests.post(f"{BASE}/admin/backup/restore", headers=ah, timeout=T, json={
        "collection": "products", "docs": [], "mode": "merge", "danger_pin": "000000"})
    assert r.status_code in (400, 401), r.text[:200]
    print("admin restore without pin ->", r.status_code, r.json().get("detail"))


# ── Permanent image store must survive a full backup ───────────────────────
def test_admin_dump_product_image_files_ok(ah):
    """Paged dump of the permanent image store (BSON Binary bytes)."""
    if not MDB.product_image_files.count_documents({}):
        pytest.skip("no permanent images stored")
    r = requests.get(f"{BASE}/admin/backup/dump", headers=ah, timeout=T,
                     params={"collection": "product_image_files", "limit": 5})
    assert r.status_code == 200, f"{r.status_code} {r.text[:120]}"


def test_streamed_backup_keeps_image_keys_and_bytes(ah):
    """`_id` IS the /api/img/<key> key — stripping it makes images unrestorable."""
    one = MDB.product_image_files.find_one({}, {"_id": 1})
    if not one:
        pytest.skip("no permanent images stored")
    r = requests.get(f"{BASE}/admin/backup/file", headers=ah, timeout=300)
    files = r.json()["collections"].get("product_image_files", [])
    blob = json.dumps(files)
    assert one["_id"] in blob, "image key (_id) missing from backup → /api/img refs 404 after restore"
    assert not any(str(f.get("data", "")).startswith("b'") for f in files), "bytes exported as python repr"


def test_streamed_backup_keeps_counter_names(ah):
    one = MDB.counters.find_one({}, {"_id": 1})
    if not one:
        pytest.skip("no counters")
    r = requests.get(f"{BASE}/admin/backup/file", headers=ah, timeout=300)
    assert str(one["_id"]) in json.dumps(r.json()["collections"].get("counters", [])), \
        "counter names (_id) stripped → sequences cannot be restored"


# ── Jun 2026 — a full backup must be able to bring the IMAGE STORE back ────
# The export used to strip `_id` from every document and str() raw bytes into
# "b'\xff\xd8...'". In `product_image_files` the `_id` IS the key behind every
# /api/img/<key> link, so a backup restored into a fork came back with every
# product photo blank. These five tests pin the round-trip.
def test_dump_of_the_image_store_does_not_500(ah):
    """Raw image bytes used to raise UnicodeDecodeError and return a 500."""
    r = requests.get(f"{BASE}/admin/backup/dump",
                     params={"collection": "product_image_files", "limit": 3, "offset": 0},
                     headers=ah, timeout=T)
    assert r.status_code == 200, r.text[:300]
    assert r.json()["total"] >= 1, "no permanent images to verify against"


def test_image_store_export_keeps_its_key_and_real_bytes(ah):
    import base64
    d = requests.get(f"{BASE}/admin/backup/dump",
                     params={"collection": "product_image_files", "limit": 3, "offset": 0},
                     headers=ah, timeout=T).json()["docs"]
    assert d, "no image files exported"
    doc = d[0]
    assert isinstance(doc.get("_id"), str) and doc["_id"], \
        "`_id` is missing — the /api/img/<key> link cannot be rebuilt"
    blob = doc.get("data")
    assert isinstance(blob, dict) and "$b64" in blob, \
        f"image bytes were not base64-encoded: {str(blob)[:80]}"
    raw = base64.b64decode(blob["$b64"])
    assert raw[:2] in (b"\xff\xd8", b"\x89P", b"RI", b"GI"), "decoded bytes are not an image"
    assert len(raw) == int(doc.get("bytes") or len(raw))


def test_restored_image_actually_serves_again(ah):
    """Delete one stored image, replay the exported document, re-fetch it."""
    from routes.backup import _json_revive
    d = requests.get(f"{BASE}/admin/backup/dump",
                     params={"collection": "product_image_files", "limit": 5, "offset": 0},
                     headers=ah, timeout=T).json()["docs"]
    doc = d[0]
    key = doc["_id"]
    before = MDB.product_image_files.find_one({"_id": key})
    assert before is not None
    MDB.product_image_files.delete_one({"_id": key})
    try:
        revived = _json_revive(doc)
        assert isinstance(revived["data"], bytes), "image bytes did not survive the export"
        MDB.product_image_files.replace_one({"_id": key}, revived, upsert=True)
        assert len(MDB.product_image_files.find_one({"_id": key})["data"]) == len(before["data"]), \
            "restored bytes differ from the original"
        # A unique width bypasses the in-process render cache, so this really
        # is served from the row we just restored.
        w = 137 + (hash(key) % 29)
        r = requests.get(f"{ROOT}/api/img/{key}", params={"w": w, "q": 71}, timeout=T)
        assert r.status_code == 200 and r.headers.get("content-type", "").startswith("image/")
        assert len(r.content) > 100
    finally:
        MDB.product_image_files.replace_one({"_id": key}, before, upsert=True)


def test_counters_keep_their_names(ah):
    """Counters are keyed by `_id`; without it they restored as bare {seq: N}
    and new short IDs collided with the unique short_ids.code index."""
    d = requests.get(f"{BASE}/admin/backup/dump",
                     params={"collection": "counters", "limit": 20, "offset": 0},
                     headers=ah, timeout=T).json()["docs"]
    assert d, "no counters exported"
    bad = [c for c in d if not c.get("_id")]
    assert not bad, f"counter names lost: {bad[:3]}"
    named = [c for c in d if isinstance(c.get("_id"), str)]
    assert named, f"no counter kept a readable name: {d[:3]}"


def test_idless_documents_are_upsertable_not_blind_inserted():
    """short_ids / image_assets / payout_keys have no `id` field. The restore
    now keys them on `_id`, so replaying the same file twice is a no-op."""
    import inspect
    from routes import backup as bk
    src = inspect.getsource(bk.admin_backup_restore)
    assert 'ReplaceOne({"_id": d["_id"]}' in src, \
        "id-less documents are still inserted blindly on every restore"
    assert "matched_count" in src, "`upserted` still reports 0 for identical documents"
