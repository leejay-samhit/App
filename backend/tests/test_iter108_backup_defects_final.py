"""Iter108 — FINAL verification of the 5 backup defects reported in iter107.

Destructive pieces are guarded:
  * Danger PIN is swapped to a known hash and restored in a finally/teardown.
  * product_image_files wipe+restore keeps a full Mongo-side snapshot and
    re-upserts every original row in teardown, whatever happens.
  * Everything else is TEST_iter108_* rows / a throw-away vendor, removed by id.
"""
import base64
import json
import os
import sys
import uuid

import bcrypt
import pytest
import requests
from bson import ObjectId
from pymongo import MongoClient

sys.path.insert(0, "/app/backend")


def _env(path, key):
    for ln in open(path):
        if ln.startswith(key + "="):
            return ln.split("=", 1)[1].strip().strip('"')
    raise KeyError(key)


ROOT = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or _env("/app/frontend/.env", "EXPO_PUBLIC_BACKEND_URL")).rstrip("/")
BASE = f"{ROOT}/api"
T = 180
ADMIN = {"email": "support@slangcart.com", "password": "3)Ywxtic"}
MDB = MongoClient(_env("/app/backend/.env", "MONGO_URL"))[_env("/app/backend/.env", "DB_NAME")]
PIN = "135790"

TAG = "TEST_iter108_" + uuid.uuid4().hex[:6]
TV_ID = str(uuid.uuid4())
TV_EMAIL = f"{TAG.lower()}@example.com"
TV_PW = "Test@1234"
CREATED = {"short_ids": [], "image_assets": [], "payout_keys": [], "products": []}


def _login(c):
    r = requests.post(f"{BASE}/auth/login", json=c, timeout=T)
    assert r.status_code == 200, r.text[:300]
    return {"Authorization": f"Bearer {r.json()['token']}"}


# ── fixtures ────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def ah():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def pin():
    from core.security import hash_password
    doc = MDB.settings.find_one({"id": "global"}, {"_id": 0, "danger_pin_hash": 1})
    old = (doc or {}).get("danger_pin_hash")
    MDB.settings.update_one({"id": "global"}, {"$set": {"danger_pin_hash": hash_password(PIN)}})
    try:
        yield PIN
    finally:
        if old is None:
            MDB.settings.update_one({"id": "global"}, {"$unset": {"danger_pin_hash": ""}})
        else:
            MDB.settings.update_one({"id": "global"}, {"$set": {"danger_pin_hash": old}})


@pytest.fixture(scope="module")
def tvh():
    MDB.users.insert_one({
        "id": TV_ID, "name": TAG, "email": TV_EMAIL, "phone": "8" + str(uuid.uuid4().int)[:9],
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
    if CREATED["products"]:
        MDB.products.delete_many({"id": {"$in": CREATED["products"]}})
    for coll in ("short_ids", "image_assets", "payout_keys"):
        if CREATED[coll]:
            MDB[coll].delete_many({"_id": {"$in": CREATED[coll]}})
    MDB.users.delete_many({"id": TV_ID})


def _restore(ah, pin, coll, docs, mode="merge", first=True):
    return requests.post(f"{BASE}/admin/backup/restore", headers=ah, timeout=T, json={
        "collection": coll, "docs": docs, "mode": mode, "first_chunk": first, "danger_pin": pin})


def _walk_dump(ah, coll, limit):
    out, off = [], 0
    while True:
        r = requests.get(f"{BASE}/admin/backup/dump", headers=ah, timeout=T,
                         params={"collection": coll, "limit": limit, "offset": off})
        assert r.status_code == 200, f"{coll} off={off}: {r.status_code} {r.text[:200]}"
        d = r.json()
        out.extend(d["docs"])
        if not d["has_more"]:
            return out, d["total"]
        off += len(d["docs"])


# ── DEFECT 1 + 2: image store export / streamed file / HTTP wipe+restore ─
def test_dump_image_store_pages_and_encodes_bytes(ah):
    docs, total = _walk_dump(ah, "product_image_files", 2)
    assert len(docs) == total and total > 0
    keys = [d["_id"] for d in docs]
    assert len(set(keys)) == len(keys), "duplicate rows across pages"
    for d in docs:
        assert isinstance(d["_id"], str) and len(d["_id"].split(".")[0]) == 40
        assert isinstance(d.get("data"), dict) and set(d["data"]) == {"$b64"}
        raw = base64.b64decode(d["data"]["$b64"])
        assert len(raw) == int(d["bytes"]), f"{d['_id']} decoded size mismatch"
        db_raw = MDB.product_image_files.find_one({"_id": d["_id"]})["data"]
        assert bytes(db_raw) == raw, f"{d['_id']} decoded bytes != stored bytes"


def test_streamed_full_backup_carries_ids_and_b64(ah, tmp_path):
    p = tmp_path / "full.json"
    with requests.get(f"{BASE}/admin/backup/file", headers=ah, timeout=280, stream=True) as r:
        assert r.status_code == 200, r.text[:200]
        with open(p, "wb") as f:
            for ch in r.iter_content(1 << 20):
                f.write(ch)
    blob = json.loads(p.read_text())
    cols = blob["collections"]
    pif = cols["product_image_files"]
    assert len(pif) == MDB.product_image_files.count_documents({})
    for d in pif:
        assert isinstance(d["_id"], str) and "$b64" in d["data"]
        assert not str(d["data"]).startswith("b'"), "bytes str()'d"
        assert len(base64.b64decode(d["data"]["$b64"])) == int(d["bytes"])
    # one legacy bare counter {_id: ObjectId, seq: 12} exists (residue of the old
    # name-stripping restore) — it must export as {"$oid"}, never vanish.
    assert all(isinstance(c.get("_id"), str) or set(c["_id"]) == {"$oid"} for c in cols["counters"])
    assert any(c["_id"].startswith("shortid:") for c in cols["counters"])
    assert "b'\\\\x" not in p.read_text()[:50_000_000]


def test_wipe_and_restore_image_store_via_http(ah, pin):
    snapshot = list(MDB.product_image_files.find({}))
    assert snapshot
    docs, total = _walk_dump(ah, "product_image_files", 3)
    assert total == len(snapshot)
    try:
        # chunk 1 wipes, later chunks append — exactly what the app does
        for i in range(0, len(docs), 3):
            r = _restore(ah, pin, "product_image_files", docs[i:i + 3], mode="wipe", first=(i == 0))
            assert r.status_code == 200, r.text[:300]
        assert MDB.product_image_files.count_documents({}) == len(snapshot)
        for orig in snapshot:
            now = MDB.product_image_files.find_one({"_id": orig["_id"]})
            assert now is not None, f"{orig['_id']} missing after restore"
            assert isinstance(now["data"], bytes), f"{orig['_id']} data type {type(now['data'])}"
            assert now["data"] == orig["data"], f"{orig['_id']} bytes differ"
            assert now.get("content_type") == orig.get("content_type")
            # unique width -> bypasses the in-process cache, forces a DB read
            r = requests.get(f"{ROOT}/api/img/{orig['_id']}", params={"w": 333, "q": 41}, timeout=T)
            assert r.status_code == 200 and r.headers["content-type"].startswith("image/"), orig["_id"]
        # a second MERGE of the same file must not duplicate and must report matches
        r = _restore(ah, pin, "product_image_files", docs, mode="merge")
        assert r.status_code == 200, r.text[:300]
        assert r.json()["upserted"] == len(docs) and r.json()["inserted"] == 0
        assert MDB.product_image_files.count_documents({}) == len(snapshot)
    finally:
        for orig in snapshot:
            MDB.product_image_files.replace_one({"_id": orig["_id"]}, orig, upsert=True)


# ── DEFECT 3: id-less collections are idempotent on re-restore ───────────
@pytest.mark.parametrize("coll", ["short_ids", "image_assets", "payout_keys"])
def test_idless_collection_restore_twice_no_dupes(ah, pin, coll):
    if coll == "short_ids":
        _id = f"TEST:{TAG}:{coll}"
        doc = {"_id": _id, "kind": "TEST", "ref_id": TAG, "code": f"T{uuid.uuid4().hex[:8].upper()}", "seq": 1}
        jdoc = dict(doc)
    else:
        oid = ObjectId()
        _id = oid
        doc = {"_id": oid, "note": TAG}
        jdoc = {"_id": {"$oid": str(oid)}, "note": TAG}
    CREATED[coll].append(_id)
    before = MDB[coll].count_documents({})
    r1 = _restore(ah, pin, coll, [jdoc])
    assert r1.status_code == 200, r1.text[:300]
    r2 = _restore(ah, pin, coll, [jdoc])
    assert r2.status_code == 200, f"second restore failed (unique index?): {r2.text[:300]}"
    assert MDB[coll].count_documents({}) == before + 1, "id-less row duplicated on merge"
    got = MDB[coll].find_one({"_id": _id})
    assert got is not None and type(got["_id"]) is type(doc["_id"]), "_id type not revived"
    assert r2.json()["upserted"] == 1, f"upserted under-reported: {r2.json()}"


def test_real_short_ids_page_rerestore_is_noop(ah, pin):
    docs, _ = _walk_dump(ah, "short_ids", 1000) if False else (requests.get(
        f"{BASE}/admin/backup/dump", headers=ah, timeout=T,
        params={"collection": "short_ids", "limit": 50, "offset": 0}).json()["docs"], None)
    before = MDB.short_ids.count_documents({})
    r = _restore(ah, pin, "short_ids", docs)
    assert r.status_code == 200, r.text[:300]
    assert r.json()["upserted"] == len(docs)
    assert MDB.short_ids.count_documents({}) == before


def test_counters_export_names(ah):
    docs = requests.get(f"{BASE}/admin/backup/dump", headers=ah, timeout=T,
                        params={"collection": "counters", "limit": 50}).json()["docs"]
    assert docs
    # `_id` is either the counter's name or a tagged ObjectId — never missing.
    for c in docs:
        assert isinstance(c["_id"], str) or set(c["_id"]) == {"$oid"}, c
    names = [c["_id"] for c in docs if isinstance(c["_id"], str)]
    assert any(n.startswith("shortid:") for n in names), names


# ── Probe: same `id`, different `_id` (target populated by an OLD-format
#    restore, which stripped `_id` and minted fresh ObjectIds) ──────────
def test_merge_when_target_row_has_different_objectid(ah, pin):
    pid = f"{TAG}-oidclash"
    CREATED["products"].append(pid)
    MDB.products.insert_one({"_id": ObjectId(), "id": pid, "name": f"{TAG} oid clash",
                             "price": 10, "vendor_id": TV_ID, "is_published": False})
    file_doc = {"_id": {"$oid": str(ObjectId())}, "id": pid, "name": f"{TAG} oid clash v2",
                "price": 11, "vendor_id": TV_ID, "is_published": False}
    r = _restore(ah, pin, "products", [file_doc])
    assert r.status_code == 200, f"merge over an id-matched row with another _id fails: {r.status_code} {r.text[:300]}"
    assert MDB.products.find_one({"id": pid})["price"] == 11


def test_wipe_mode_chunk_retry_duplicate_id(ah, pin):
    """mode=wipe, first_chunk=false is a plain insert; a retried chunk now
    carries the same `_id` twice (old format minted new ones)."""
    pid = f"{TAG}-retry"
    CREATED["products"].append(pid)
    d = {"_id": {"$oid": str(ObjectId())}, "id": pid, "name": f"{TAG} retry", "price": 5,
         "vendor_id": TV_ID, "is_published": False}
    r1 = _restore(ah, pin, "products", [d], mode="wipe", first=False)
    assert r1.status_code == 200, r1.text[:300]
    r2 = _restore(ah, pin, "products", [d], mode="wipe", first=False)
    assert r2.status_code == 200, f"retried wipe chunk errors: {r2.status_code} {r2.text[:200]}"


# ── DEFECT 4: vendor restore name matching ───────────────────────────────
def _imp(h, rows, mode="merge", chunk=5, session=None):
    """Mirrors the app: one `restore_session` for the whole file (see
    frontend/app/vendor/catalogue-backup.tsx), sent on every chunk."""
    tot = {"created": 0, "updated": 0}
    session = session or uuid.uuid4().hex
    for i in range(0, len(rows), chunk):
        r = requests.post(f"{BASE}/vendor/me/catalogue/import", headers=h, timeout=T, json={
            "products": rows[i:i + chunk], "mode": mode, "first_chunk": i == 0,
            "restore_session": session})
        assert r.status_code == 200, r.text[:300]
        tot["created"] += r.json()["created"]; tot["updated"] += r.json()["updated"]
    return tot


def _mine(name):
    return list(MDB.products.find({"vendor_id": TV_ID, "name": name}, {"_id": 0}))


def test_two_existing_same_name_rows_stay_distinct(tvh):
    name = f"{TAG} Twin"
    rep = _imp(tvh, [{"name": name, "price": 111, "stock": 1, "category": "Electronics"},
                     {"name": name, "price": 222, "stock": 1, "category": "Electronics"}])
    assert rep["created"] == 2
    rep2 = _imp(tvh, [{"name": name, "price": 111, "stock": 1, "category": "Electronics"},
                      {"name": name, "price": 222, "stock": 1, "category": "Electronics"}])
    assert rep2 == {"created": 0, "updated": 2}, rep2
    assert sorted(p["price"] for p in _mine(name)) == [111, 222]


def test_same_name_split_across_chunks_keeps_both(tvh):
    """The app restores IMPORT_PAGE=5 rows per request, so a name repeated in
    the file can land in two different requests. Chunk 2 used to re-read the
    shop, find the row chunk 1 had just created and overwrite it — losing a
    product. Rows stamped with this restore_session are now never re-matched."""
    name = f"{TAG} Split"
    rows = [{"name": name, "price": 301, "stock": 1, "category": "Electronics"}]
    rows += [{"name": f"{TAG} filler {i}", "price": 50 + i, "stock": 1, "category": "Electronics"} for i in range(4)]
    rows += [{"name": name, "price": 302, "stock": 1, "category": "Electronics"}]
    _imp(tvh, rows, chunk=5)
    got = _mine(name)
    assert len(got) == 2, f"fresh restore lost a same-named product across chunks: {[(p['price']) for p in got]}"
    assert sorted(p["price"] for p in got) == [301, 302]

    # …and replaying the same file is still idempotent: 2 rows in, 2 rows out.
    rep = _imp(tvh, rows, chunk=5)
    again = _mine(name)
    assert len(again) == 2, f"repeat restore duplicated the split rows: {len(again)} ({rep})"
    assert sorted(p["price"] for p in again) == [301, 302]
    assert rep["created"] == 0, rep


def test_live_product_stays_published_on_merge(tvh):
    name = f"{TAG} Live"
    _imp(tvh, [{"name": name, "price": 400, "stock": 1, "category": "Electronics"}])
    MDB.products.update_one({"vendor_id": TV_ID, "name": name}, {"$set": {"is_published": True}})
    rep = _imp(tvh, [{"name": name, "price": 405, "stock": 7, "category": "Electronics", "is_published": False}])
    assert rep == {"created": 0, "updated": 1}
    p = _mine(name)[0]
    assert p["is_published"] is True and p["price"] == 405 and p["stock"] == 7


# ── DEFECT 5: legacy array vs paged object ───────────────────────────────
def test_vendor_me_products_legacy_and_paged(tvh):
    r = requests.get(f"{BASE}/vendor/me/products", headers=tvh, timeout=T)
    assert r.status_code == 200 and isinstance(r.json(), list), type(r.json())
    legacy = {p["id"] for p in r.json()}
    paged, off = set(), 0
    while True:
        d = requests.get(f"{BASE}/vendor/me/products", headers=tvh, timeout=T,
                         params={"limit": 3, "offset": off}).json()
        assert isinstance(d, dict) and {"items", "total", "limit", "offset", "has_more"} <= set(d)
        paged |= {p["id"] for p in d["items"]}
        if not d["has_more"]:
            break
        off += len(d["items"])
    assert legacy == paged and len(legacy) == d["total"] == MDB.products.count_documents({"vendor_id": TV_ID})
    only_limit = requests.get(f"{BASE}/vendor/me/products", headers=tvh, timeout=T, params={"limit": 2}).json()
    assert isinstance(only_limit, dict) and len(only_limit["items"]) == 2


def test_admin_products_partial_stat_labels():
    src = open("/app/frontend/app/admin/products.tsx").read()
    for label in ("No stock so far", "Interest so far", "Approvals so far"):
        assert label in src, label
