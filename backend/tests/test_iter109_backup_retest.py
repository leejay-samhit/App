"""Iter109 — retest of the three iter108 issues.

ISSUE 1  vendor restore: restore_session stamping keeps same-name rows split
         across IMPORT_PAGE=5 chunks; replay is idempotent; older client OK.
ISSUE 2  admin merge restore: `id` match drops `_id` (no error 66); the real
         `settings` collection merges with a foreign `_id`; later collections
         in the walk still restore.
ISSUE 3  admin wipe restore: first_chunk=false chunks upsert on `_id` so a
         retry is a no-op; a normal multi-chunk wipe restores each row once.

Safety: settings is snapshotted (full Mongo docs) BEFORE the PIN swap and
re-written in teardown; the wipe tests run on a private throw-away collection
that is dropped at the end; vendor tests use a throw-away shop.
"""
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
TAG = "TEST_iter109_" + uuid.uuid4().hex[:6]
TV_ID = str(uuid.uuid4())
TV_EMAIL = f"{TAG.lower()}@example.com"
WIPE_COLL = f"test_iter109_wipe_{uuid.uuid4().hex[:6]}"
CREATED = {"products": [], "extra": []}   # extra: (collection, _id)


def _login(c):
    r = requests.post(f"{BASE}/auth/login", json=c, timeout=T)
    assert r.status_code == 200, r.text[:300]
    return {"Authorization": f"Bearer {r.json()['token']}"}


# ── fixtures ────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def settings_snap():
    snap = list(MDB.settings.find({}))
    yield snap
    keep = [d["_id"] for d in snap]
    MDB.settings.delete_many({"_id": {"$nin": keep}})
    for d in snap:
        MDB.settings.replace_one({"_id": d["_id"]}, d, upsert=True)


@pytest.fixture(scope="module")
def pin(settings_snap):
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
def ah():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def tvh():
    MDB.users.insert_one({
        "id": TV_ID, "name": TAG, "email": TV_EMAIL, "phone": "7" + str(uuid.uuid4().int)[:9],
        "password_hash": bcrypt.hashpw(b"Test@1234", bcrypt.gensalt()).decode(),
        "role": "user", "admin_role": None, "is_blocked": False, "approval_status": "approved",
        "registration_paid": True, "is_vendor": True, "vendor_status": "approved",
        "is_vendor_approved": True, "shop_name": TAG, "pincode": "517644",
        "referral_code": uuid.uuid4().hex[:6].upper(), "wallet_balance": 0.0,
        "created_at": "2026-01-01T00:00:00+00:00",
    })
    yield _login({"email": TV_EMAIL, "password": "Test@1234"})


@pytest.fixture(scope="module", autouse=True)
def _cleanup():
    yield
    MDB.products.delete_many({"vendor_id": TV_ID})
    if CREATED["products"]:
        MDB.products.delete_many({"id": {"$in": CREATED["products"]}})
    for coll, _id in CREATED["extra"]:
        MDB[coll].delete_one({"_id": _id})
    MDB.users.delete_many({"id": TV_ID})
    MDB.drop_collection(WIPE_COLL)


def _imp(h, rows, mode="merge", chunk=5, session="auto"):
    tot = {"created": 0, "updated": 0}
    sess = uuid.uuid4().hex if session == "auto" else session
    for i in range(0, len(rows), chunk):
        body = {"products": rows[i:i + chunk], "mode": mode, "first_chunk": i == 0}
        if sess is not None:
            body["restore_session"] = sess
        r = requests.post(f"{BASE}/vendor/me/catalogue/import", headers=h, timeout=T, json=body)
        assert r.status_code == 200, f"chunk {i}: {r.status_code} {r.text[:300]}"
        tot["created"] += r.json()["created"]; tot["updated"] += r.json()["updated"]
    return tot


def _mine(name):
    return list(MDB.products.find({"vendor_id": TV_ID, "name": name}, {"_id": 0}))


def _row(name, price):
    return {"name": name, "price": price, "stock": 1, "category": "Electronics"}


def _restore(ah, pin, coll, docs, mode="merge", first=True):
    return requests.post(f"{BASE}/admin/backup/restore", headers=ah, timeout=T, json={
        "collection": coll, "docs": docs, "mode": mode, "first_chunk": first, "danger_pin": pin})


# ── ISSUE 1: vendor restore_session ──────────────────────────────────────
def test_1a_1b_same_name_row1_and_row6_two_chunks(tvh):
    name = f"{TAG} Split"
    rows = [_row(name, 301)] + [_row(f"{TAG} fA{i}", 50 + i) for i in range(4)] + [_row(name, 302)]
    rep = _imp(tvh, rows)
    assert rep == {"created": 6, "updated": 0}, rep
    got = _mine(name)
    assert sorted(p["price"] for p in got) == [301, 302], [p["price"] for p in got]
    before = {p["id"]: p["price"] for p in got}
    rep2 = _imp(tvh, rows)
    assert rep2 == {"created": 0, "updated": 6}, rep2
    again = _mine(name)
    assert sorted(p["price"] for p in again) == [301, 302]
    after = {p["id"]: p["price"] for p in again}
    assert set(after) == set(before), "replay replaced product ids"
    # informational: does each product id keep its own price on replay?
    print(f"ID->price stable on replay: {after == before} before={before} after={after}")


def test_1c_three_occurrences_three_chunks(tvh):
    name = f"{TAG} Triple"
    rows = []
    for c, price in enumerate((401, 402, 403)):
        rows.append(_row(name, price))
        rows += [_row(f"{TAG} fB{c}{i}", 60 + i) for i in range(4)]
    assert len(rows) == 15
    rep = _imp(tvh, rows)
    assert rep["created"] == 15, rep
    assert sorted(p["price"] for p in _mine(name)) == [401, 402, 403]
    for _ in range(2):
        rep2 = _imp(tvh, rows)
        assert rep2 == {"created": 0, "updated": 15}, rep2
        assert sorted(p["price"] for p in _mine(name)) == [401, 402, 403]


def test_1d_older_client_without_session(tvh):
    name = f"{TAG} Old"
    rows = [_row(name, 501), _row(f"{TAG} oldfill", 9)]
    rep = _imp(tvh, rows, session=None)
    assert rep == {"created": 2, "updated": 0}, rep
    rep2 = _imp(tvh, rows, session=None)
    assert rep2 == {"created": 0, "updated": 2}, rep2
    assert [p["price"] for p in _mine(name)] == [501]
    # empty-string session must behave like no session, not a 500
    r = requests.post(f"{BASE}/vendor/me/catalogue/import", headers=tvh, timeout=T, json={
        "products": rows, "mode": "merge", "first_chunk": True, "restore_session": ""})
    assert r.status_code == 200 and r.json()["created"] == 0, r.text[:300]


def test_1d_older_client_split_name_behaviour(tvh):
    """Informational: older client (no session) + name split across chunks."""
    name = f"{TAG} OldSplit"
    rows = [_row(name, 601)] + [_row(f"{TAG} fC{i}", 70 + i) for i in range(4)] + [_row(name, 602)]
    _imp(tvh, rows, session=None)
    print(f"older-client split rows: {sorted(p['price'] for p in _mine(name))}")


def test_1e_same_session_chunk_retry(tvh):
    """Informational: a chunk retried with the SAME session (lost response)."""
    name = f"{TAG} Retry"
    sess = uuid.uuid4().hex
    rows = [_row(name, 701)]
    _imp(tvh, rows, session=sess)
    _imp(tvh, rows, session=sess)
    print(f"same-session retry -> rows: {len(_mine(name))}")


def test_1f_export_leaks_restore_session(tvh):
    r = requests.get(f"{BASE}/vendor/me/catalogue/export", headers=tvh, timeout=T)
    assert r.status_code == 200
    d = r.json()
    items = d.get("products") or d.get("items") or []
    assert items
    leaked = sum(1 for p in items if "restore_session" in p)
    print(f"export rows carrying restore_session: {leaked}/{len(items)}")


# ── ISSUE 2: admin merge, `_id` clash ────────────────────────────────────
def test_2a_merge_id_match_different_objectid(ah, pin):
    pid = f"{TAG}-oidclash"
    CREATED["products"].append(pid)
    orig_oid = ObjectId()
    MDB.products.insert_one({"_id": orig_oid, "id": pid, "name": f"{TAG} clash", "price": 10,
                             "vendor_id": TV_ID, "is_published": False})
    file_doc = {"_id": {"$oid": str(ObjectId())}, "id": pid, "name": f"{TAG} clash v2", "price": 11,
                "vendor_id": TV_ID, "is_published": False}
    r = _restore(ah, pin, "products", [file_doc])
    assert r.status_code == 200, r.text[:300]
    assert r.json()["upserted"] == 1 and r.json()["inserted"] == 0, r.json()
    rows = list(MDB.products.find({"id": pid}))
    assert len(rows) == 1 and rows[0]["price"] == 11 and rows[0]["_id"] == orig_oid


def test_2b_settings_merge_from_other_deployment_then_walk_continues(ah, pin, settings_snap):
    dump = requests.get(f"{BASE}/admin/backup/dump", headers=ah, timeout=T,
                        params={"collection": "settings", "limit": 500}).json()
    docs = dump["docs"]
    assert any(d.get("id") == "global" for d in docs)
    db_ids = {d["_id"] for d in MDB.settings.find({}, {"_id": 1})}
    # simulate a file from another deployment: same `id`, different `_id`
    foreign = []
    for d in docs:
        d = dict(d)
        if d.get("id"):
            d["_id"] = {"$oid": str(ObjectId())}
        foreign.append(d)
    g = next(d for d in foreign if d.get("id") == "global")
    g["TEST_iter109_marker"] = TAG
    before = MDB.settings.count_documents({})
    r = _restore(ah, pin, "settings", foreign)
    assert r.status_code == 200, f"settings merge aborted: {r.status_code} {r.text[:300]}"
    assert MDB.settings.count_documents({}) == before, "settings rows duplicated"
    gdb = MDB.settings.find_one({"id": "global"})
    assert gdb.get("TEST_iter109_marker") == TAG, "global settings row not updated"
    assert {d["_id"] for d in MDB.settings.find({}, {"_id": 1})} == db_ids, "_id changed"
    # PIN in the file == current test PIN, so the walk can continue
    MDB.settings.update_one({"id": "global"}, {"$unset": {"TEST_iter109_marker": ""}})

    # collections after `settings` in the manifest walk must still restore
    man = requests.get(f"{BASE}/admin/backup/manifest", headers=ah, timeout=T).json()
    names = [c.get("name") if isinstance(c, dict) else c for c in
             (man.get("collections") or man.get("counts") or [])]
    if isinstance(man.get("collections"), dict):
        names = list(man["collections"].keys())
    print(f"manifest walk: {names}")
    later = names[names.index("settings") + 1:] if "settings" in names else []
    later = [n for n in later if n not in ("product_image_files",)][:3] or ["audit_logs"]
    for coll in later:
        oid = ObjectId()
        CREATED["extra"].append((coll, oid))
        rr = _restore(ah, pin, coll, [{"_id": {"$oid": str(oid)}, "id": f"{TAG}-{coll}", "note": TAG}])
        assert rr.status_code == 200, f"{coll} after settings: {rr.status_code} {rr.text[:200]}"
        assert MDB[coll].find_one({"id": f"{TAG}-{coll}"}) is not None
        MDB[coll].delete_many({"id": f"{TAG}-{coll}"})


def test_2c_merge_upsert_new_id_keeps_file_objectid(ah, pin):
    """Informational: a NEW `id` doc — is the file `_id` kept on insert?"""
    pid = f"{TAG}-newid"
    CREATED["products"].append(pid)
    oid = ObjectId()
    r = _restore(ah, pin, "products", [{"_id": {"$oid": str(oid)}, "id": pid, "name": pid,
                                        "price": 3, "vendor_id": TV_ID, "is_published": False}])
    assert r.status_code == 200, r.text[:300]
    row = MDB.products.find_one({"id": pid})
    assert row is not None
    print(f"new-id merge keeps file _id: {row['_id'] == oid}")


# ── ISSUE 3: wipe-mode chunks upsert on `_id` ────────────────────────────
def test_3a_wipe_chunk_retry_is_noop(ah, pin):
    pid = f"{TAG}-retry"
    CREATED["products"].append(pid)
    d = {"_id": {"$oid": str(ObjectId())}, "id": pid, "name": pid, "price": 5,
         "vendor_id": TV_ID, "is_published": False}
    r1 = _restore(ah, pin, "products", [d], mode="wipe", first=False)
    r2 = _restore(ah, pin, "products", [d], mode="wipe", first=False)
    assert r1.status_code == 200 and r2.status_code == 200, (r1.text[:200], r2.text[:200])
    assert MDB.products.count_documents({"id": pid}) == 1
    print(f"retry report: r1={r1.json()['inserted']} r2={r2.json()['inserted']} wiped={r1.json()['wiped']},{r2.json()['wiped']}")


def test_3b_multi_chunk_wipe_restores_every_row_once(ah, pin):
    MDB[WIPE_COLL].insert_many([{"_id": ObjectId(), "stale": True} for _ in range(4)])
    rows = [{"_id": {"$oid": str(ObjectId())}, "id": f"{TAG}-w{i}", "n": i} for i in range(12)]
    rows.append({"id": f"{TAG}-noid", "n": 99})       # row without `_id` (plain insert)
    total_ins, wiped = 0, 0
    for i in range(0, len(rows), 5):
        r = _restore(ah, pin, WIPE_COLL, rows[i:i + 5], mode="wipe", first=(i == 0))
        assert r.status_code == 200, r.text[:300]
        total_ins += r.json()["inserted"]; wiped += r.json()["wiped"]
    assert wiped == 4
    assert total_ins == len(rows), total_ins
    assert MDB[WIPE_COLL].count_documents({}) == len(rows)
    assert MDB[WIPE_COLL].count_documents({"stale": True}) == 0
    ns = sorted(d["n"] for d in MDB[WIPE_COLL].find({}))
    assert ns == sorted(r["n"] for r in rows), "row duplicated or lost"
    assert all(isinstance(d["_id"], ObjectId) for d in MDB[WIPE_COLL].find({}))
    # retry the middle chunk — still exactly once
    r = _restore(ah, pin, WIPE_COLL, rows[5:10], mode="wipe", first=False)
    assert r.status_code == 200
    assert MDB[WIPE_COLL].count_documents({}) == len(rows)


def test_2d_settings_from_other_deployment_with_different_pin(ah, pin):
    """Realistic cross-deployment file: its settings{id:'global'} carries the
    SOURCE deployment's danger_pin_hash. The client re-sends the same PIN on
    every chunk, so the walk must keep working for collections after it."""
    from core.security import hash_password
    dump = requests.get(f"{BASE}/admin/backup/dump", headers=ah, timeout=T,
                        params={"collection": "settings", "limit": 500}).json()["docs"]
    g = dict(next(d for d in dump if d.get("id") == "global"))
    g["_id"] = {"$oid": str(ObjectId())}
    g["danger_pin_hash"] = hash_password("246802")      # source deployment's PIN
    try:
        r = _restore(ah, pin, "settings", [g])
        assert r.status_code == 200, r.text[:300]
        oid = ObjectId()
        CREATED["extra"].append(("shop_categories", oid))
        rr = _restore(ah, pin, "shop_categories", [{"_id": {"$oid": str(oid)}, "id": f"{TAG}-pin", "note": TAG}])
        MDB.shop_categories.delete_many({"id": f"{TAG}-pin"})
        assert rr.status_code == 200, (
            f"walk aborts after settings: next collection with the same PIN -> {rr.status_code} {rr.text[:200]}")
    finally:
        MDB.settings.update_one({"id": "global"}, {"$set": {"danger_pin_hash": hash_password(PIN)}})


def test_2e_wipe_settings_keeps_the_live_pin(ah, pin):
    """A `wipe` restore of `settings` from a file with no global row used to
    delete the Danger PIN outright, so every later collection failed with
    "Danger PIN not set". The admin's own PIN is now always kept."""
    from core.security import hash_password, verify_password
    snapshot = list(MDB.settings.find({}))
    try:
        # A file whose settings page carries only an unrelated row.
        r = _restore(ah, pin, "settings", [{"id": f"{TAG}-stray", "note": TAG}],
                     mode="wipe", first=True)
        assert r.status_code == 200, r.text[:300]
        g = MDB.settings.find_one({"id": "global"}, {"_id": 0, "danger_pin_hash": 1})
        assert g and g.get("danger_pin_hash"), "the Danger PIN was wiped by a restore"
        assert verify_password(PIN, g["danger_pin_hash"]), "the PIN was replaced by the file's"
        # …and the next collection in the walk still authenticates.
        rr = _restore(ah, pin, "shop_categories", [{"id": f"{TAG}-afterwipe", "note": TAG}])
        MDB.shop_categories.delete_many({"id": f"{TAG}-afterwipe"})
        assert rr.status_code == 200, f"walk aborts after a wiped settings: {rr.text[:200]}"
    finally:
        MDB.settings.delete_many({})
        if snapshot:
            MDB.settings.insert_many(snapshot)
        MDB.settings.update_one({"id": "global"}, {"$set": {"danger_pin_hash": hash_password(PIN)}})


def test_2f_restore_session_is_not_exported(tvh):
    """`restore_session` / `restored_at` are bookkeeping from a PREVIOUS
    restore and must not travel inside a fresh export file."""
    _imp(tvh, [{"name": f"{TAG} ExportLeak", "price": 77, "stock": 1, "category": "Electronics"}])
    d = requests.get(f"{BASE}/vendor/me/catalogue/export", headers=tvh, timeout=T,
                     params={"limit": 25, "offset": 0}).json()
    rows = d.get("products") or d.get("items") or []
    assert rows, d
    for row in rows:
        assert "restore_session" not in row, "restore_session leaked into the export"
        assert "restored_at" not in row, "restored_at leaked into the export"
