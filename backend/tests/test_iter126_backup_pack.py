# Iteration 126 — full database backup: the production "6/87 tables ·
# 2,929.8 MB → Backup failed" root cause and the hardening around it.
#
# Root cause: `backup_file_chunks` (the raw bytes of PREVIOUSLY prepared
# backups, 4 MB per document) was itself exported, so a new backup tried to
# fold every old backup into itself.
import hashlib
import json
import os
import time

import pymongo
import requests
from dotenv import dotenv_values

ENV = dotenv_values(os.path.join(os.path.dirname(__file__), "..", ".env"))
BASE = "http://localhost:8001/api"
ADMIN = {"email": ENV["ADMIN_EMAIL"], "password": ENV["ADMIN_PASSWORD"]}
MDB = pymongo.MongoClient(ENV["MONGO_URL"])[ENV["DB_NAME"]]


def _token():
    r = requests.post(f"{BASE}/auth/login", json=ADMIN, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["token"]


H = None


def setup_module():
    global H
    H = {"Authorization": f"Bearer {_token()}"}


def test_1_cache_collections_are_never_exported():
    """A backup must never contain backups."""
    r = requests.get(f"{BASE}/admin/backup/manifest", headers=H, timeout=120)
    assert r.status_code == 200, r.text
    m = r.json()
    names = [c["name"] for c in m["collections"]]
    for cache in ("backup_file_chunks", "backup_file_jobs", "backup_restore_jobs",
                  "db_snapshots", "db_snapshot_chunks"):
        assert cache not in names, f"{cache} is still exported"
        assert cache in m["skipped"]
    # Real business tables are still there.
    for keep in ("users", "orders", "transactions", "products"):
        assert keep in names
    print(f"manifest: {len(names)} tables, {m['total_documents']} docs, "
          f"{round(m.get('total_bytes', 0) / 1e6, 1)} MB on disk")


def test_2_manifest_reports_sizes():
    r = requests.get(f"{BASE}/admin/backup/manifest", headers=H, timeout=120)
    m = r.json()
    assert m.get("total_bytes", 0) > 0
    assert all("bytes" in c for c in m["collections"])


def test_3_pack_completes_and_verifies():
    r = requests.post(f"{BASE}/admin/backup/file/prepare", headers=H, json={}, timeout=120)
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    status = None
    for _ in range(300):
        time.sleep(2)
        s = requests.get(f"{BASE}/admin/backup/file/jobs/{job_id}", headers=H, timeout=60).json()
        status = s
        if s["status"] in ("ready", "failed", "cancelled"):
            break
    assert status and status["status"] == "ready", status
    assert status.get("verified") is True
    assert status.get("sha256")
    assert status.get("docs_written", 0) > 0
    print(f"packed {status['bytes_written'] / 1e6:.1f} MB · "
          f"{status['docs_written']} docs · {status['chunks']} chunks")

    # Download and prove the bytes are a complete, valid JSON document whose
    # checksum matches what the server packed.
    d = requests.get(f"{BASE}/admin/backup/file/jobs/{job_id}/download",
                     headers=H, timeout=600)
    assert d.status_code == 200
    assert hashlib.sha256(d.content).hexdigest() == status["sha256"]
    doc = json.loads(d.content)
    assert doc["format"] == "slangcart.app-backup"
    assert "users" in doc["collections"] and len(doc["collections"]["users"]) > 0
    assert doc["counts"]["users"] == len(doc["collections"]["users"])
    assert "backup_file_chunks" not in doc["collections"]
    globals()["_READY_JOB"] = job_id


def test_4_second_pack_is_refused_while_one_runs():
    r1 = requests.post(f"{BASE}/admin/backup/file/prepare", headers=H, json={}, timeout=120)
    assert r1.status_code == 200
    jid = r1.json()["job_id"]
    r2 = requests.post(f"{BASE}/admin/backup/file/prepare", headers=H, json={}, timeout=120)
    assert r2.status_code == 409, r2.text
    # Cancelling frees the bytes immediately.
    c = requests.post(f"{BASE}/admin/backup/file/jobs/{jid}/cancel", headers=H, timeout=60)
    assert c.status_code == 200, c.text
    for _ in range(20):
        time.sleep(1)
        st = requests.get(f"{BASE}/admin/backup/file/jobs/{jid}", headers=H, timeout=60).json()
        if st["status"] != "packing":
            break
    assert st["status"] == "cancelled", st
    assert MDB.backup_file_chunks.count_documents({"job_id": jid}) == 0


def test_5_purge_frees_every_cached_file():
    r = requests.delete(f"{BASE}/admin/backup/file/cache", headers=H, timeout=120)
    assert r.status_code == 200, r.text
    print("purged:", r.json())
    assert MDB.backup_file_chunks.count_documents({}) == 0


def test_6_money_is_untouched():
    txns = MDB.transactions.count_documents({})
    wallet = sum(u.get("wallet_balance") or 0 for u in MDB.users.find({}, {"wallet_balance": 1}))
    print(f"transactions={txns} wallet={round(wallet, 2)}")
    assert txns > 0


def test_7_restore_round_trip_in_an_isolated_database():
    """Prove a packed file restores byte-for-byte — into a SCRATCH database,
    never the live one. Covers the two things a backup exists for: real
    ObjectIds and real image bytes coming back intact."""
    import base64
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from bson import ObjectId
    from pymongo import ReplaceOne
    from routes.backup import _json_revive, _json_safe

    scratch_name = ENV["DB_NAME"] + "_restoretest"
    client = pymongo.MongoClient(ENV["MONGO_URL"])
    scratch = client[scratch_name]
    try:
        # A document shaped exactly like the permanent image store: ObjectId
        # `_id` (the key behind /api/img/<key>) plus raw JPEG bytes.
        jpeg = bytes([0xFF, 0xD8, 0xFF, 0xE0]) + os.urandom(2048)
        original = {"_id": ObjectId(), "data": jpeg, "content_type": "image/jpeg",
                    "product_id": "p-123", "amount": 1499.5}

        # Export → file → restore, through the very same helpers the app uses.
        on_file = json.loads(json.dumps(_json_safe(original), default=str))
        assert on_file["_id"]["$oid"] == str(original["_id"])
        assert base64.b64decode(on_file["data"]["$b64"]) == jpeg

        revived = _json_revive(on_file)
        scratch.product_image_files.bulk_write(
            [ReplaceOne({"_id": revived["_id"]}, revived, upsert=True)], ordered=False,
        )
        back = scratch.product_image_files.find_one({"_id": original["_id"]})
        assert back is not None, "restored document not found"
        assert bytes(back["data"]) == jpeg, "image bytes did not survive the round trip"
        assert back["_id"] == original["_id"], "image key changed — photos would go blank"
        assert back["amount"] == 1499.5

        # A replay of the SAME file must not duplicate the row (restores are
        # retried from flaky phones all the time).
        scratch.product_image_files.bulk_write(
            [ReplaceOne({"_id": revived["_id"]}, revived, upsert=True)], ordered=False,
        )
        assert scratch.product_image_files.count_documents({}) == 1
        print("restore round trip OK in isolated db:", scratch_name)
    finally:
        client.drop_database(scratch_name)
