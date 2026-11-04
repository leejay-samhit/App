"""Nov 2026 — backup reliability fixes regression tests.

Covers the production failures the owner reported:
1. Full-backup file packing hung forever / "Packing on the server…" — now a
   server-side background job (prepare → poll → download).
2. Snapshot restore returned "500" on big Atlas data — now a background job
   with live progress and per-collection fault tolerance.
3. A snapshot restore REVOKED the acting admin's session mid-job (the users
   collection was wiped and re-inserted without their active_session_ids).
4. Snapshots stripped `_id`, so a restore destroyed the named `counters`
   (shortid:order …) — short IDs would have restarted at 1 and collided.
"""
import json
import os
import time
import uuid

import pytest
import requests

BASE = "http://localhost:8001/api"
T = 60
PIN = "135790"


def _login():
    r = requests.post(f"{BASE}/auth/login",
                      json={"email": "support@slangcart.com", "password": "3)Ywxtic"}, timeout=T)
    assert r.status_code == 200, r.text[:200]
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def ah():
    return _login()


@pytest.fixture(scope="module")
def pin():
    """Temporarily set a known Danger PIN for the restore calls (sync driver —
    no event-loop churn in the test process)."""
    from dotenv import dotenv_values
    from pymongo import MongoClient
    from core.security import hash_password
    env = dotenv_values(os.path.join(os.path.dirname(__file__), "..", ".env"))
    db = MongoClient(env["MONGO_URL"])[env["DB_NAME"]]
    doc = db.settings.find_one({"id": "global"}, {"_id": 0, "danger_pin_hash": 1})
    old = (doc or {}).get("danger_pin_hash")
    db.settings.update_one({"id": "global"}, {"$set": {"danger_pin_hash": hash_password(PIN)}})
    yield PIN
    if old:
        db.settings.update_one({"id": "global"}, {"$set": {"danger_pin_hash": old}})


def _new_snapshot(ah):
    r = requests.post(f"{BASE}/admin/backups", json={"note": f"pytest {uuid.uuid4().hex[:6]}"},
                      headers=ah, timeout=300)
    assert r.status_code == 200, r.text[:300]
    return r.json()["id"]


def _wait_restore(ah, job_id, timeout_s=240):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = requests.get(f"{BASE}/admin/backups/restore-jobs/{job_id}", headers=ah, timeout=T)
        # 401 here means the restore kicked the acting admin out — the exact
        # regression this suite guards against.
        assert r.status_code == 200, f"session lost mid-restore: {r.status_code} {r.text[:200]}"
        job = r.json()
        if job.get("status") in ("done", "failed"):
            return job
        time.sleep(2)
    raise AssertionError("restore job never finished")


def test_prepared_file_backup_packs_and_downloads(ah):
    """prepare → poll → download yields one complete, valid backup JSON."""
    r = requests.post(f"{BASE}/admin/backup/file/prepare", json={"scope": "app"},
                      headers=ah, timeout=T)
    assert r.status_code == 200, r.text[:300]
    job_id = r.json()["job_id"]
    total = r.json()["collections_total"]
    assert total > 10

    deadline = time.time() + 300
    job = None
    while time.time() < deadline:
        job = requests.get(f"{BASE}/admin/backup/file/jobs/{job_id}", headers=ah, timeout=T).json()
        if job["status"] in ("ready", "failed"):
            break
        time.sleep(2)
    assert job and job["status"] == "ready", job
    assert job["collections_done"] == total
    assert job["bytes_written"] > 0

    d = requests.get(f"{BASE}/admin/backup/file/jobs/{job_id}/download", headers=ah, timeout=300)
    assert d.status_code == 200, d.text[:200]
    doc = json.loads(d.content)
    assert doc["format"] == "slangcart.app-backup"
    assert len(doc["collections"]) == total
    assert isinstance(doc["collections"].get("products"), list)


def test_download_before_ready_is_409_not_a_hang(ah):
    r = requests.post(f"{BASE}/admin/backup/file/prepare", json={"scope": "app"},
                      headers=ah, timeout=T)
    job_id = r.json()["job_id"]
    early = requests.get(f"{BASE}/admin/backup/file/jobs/{job_id}/download", headers=ah, timeout=T)
    # Either already ready (tiny db) or a clean "still packing" — never a hang.
    assert early.status_code in (200, 409)
    if early.status_code == 409:
        assert "packing" in early.text


def test_snapshot_keeps_counter_names(ah):
    """A snapshot must capture `_id` — the counter name LIVES in `_id`."""
    snap_id = _new_snapshot(ah)
    from dotenv import dotenv_values
    from pymongo import MongoClient
    env = dotenv_values(os.path.join(os.path.dirname(__file__), "..", ".env"))
    mdb = MongoClient(env["MONGO_URL"])[env["DB_NAME"]]
    rows = []
    for ch in mdb.db_snapshot_chunks.find(
            {"snapshot_id": snap_id, "collection": "counters"}, {"rows": 1}):
        rows.extend(ch.get("rows") or [])
    assert rows, "counters were not captured at all"
    named = [r for r in rows if isinstance(r.get("_id"), str)]
    assert named, f"counter names stripped: {rows[:2]}"
    assert any(r["_id"].startswith("shortid:") for r in named)


def test_snapshot_restore_job_keeps_admin_session_and_counters(ah, pin):
    """Full round-trip: restore as a job, admin session survives, named
    counters survive, and new short IDs do not collide."""
    from dotenv import dotenv_values
    from pymongo import MongoClient
    env = dotenv_values(os.path.join(os.path.dirname(__file__), "..", ".env"))
    mdb = MongoClient(env["MONGO_URL"])[env["DB_NAME"]]

    named_before = {c["_id"]: c.get("seq") for c in mdb.counters.find({"_id": {"$type": "string"}})}
    assert any(k.startswith("shortid:") for k in named_before), "no named counters to verify"

    snap_id = _new_snapshot(ah)
    r = requests.post(f"{BASE}/admin/backups/{snap_id}/restore",
                      json={"danger_pin": PIN}, headers=ah, timeout=T)
    assert r.status_code == 200, r.text[:300]
    job = _wait_restore(ah, r.json()["job_id"])
    assert job["status"] == "done", job
    assert job.get("ok") is True, f"collections failed: {job.get('failed')}"

    # Session survived the restore (the admin can still call the API).
    still = requests.get(f"{BASE}/auth/me", headers=ah, timeout=T)
    assert still.status_code == 200, "the acting admin was logged out by the restore"

    # Counters are still NAMED and at-or-above their previous values.
    named_after = {c["_id"]: c.get("seq") for c in mdb.counters.find({"_id": {"$type": "string"}})}
    for k, v in named_before.items():
        assert k in named_after, f"counter {k} lost its name in the restore"
        assert named_after[k] >= v, f"counter {k} went BACKWARDS ({v} -> {named_after[k]})"

    # A freshly minted short ID must continue the sequence, not restart at 1.
    # `find_one_and_update` is exactly what core.seq_ids._next_seq does, so
    # this proves the named counter keeps counting instead of colliding.
    nxt = mdb.counters.find_one_and_update(
        {"_id": "shortid:order"}, {"$inc": {"seq": 1}},
        return_document=True,
    )
    assert nxt and nxt["seq"] > named_before.get("shortid:order", 0), \
        "order short-ID counter did not continue the sequence"
    # roll the claimed number back so the test leaves no gap in numbering
    mdb.counters.update_one({"_id": "shortid:order"}, {"$inc": {"seq": -1}})


def test_restore_unknown_job_is_404(ah):
    r = requests.get(f"{BASE}/admin/backups/restore-jobs/{uuid.uuid4()}", headers=ah, timeout=T)
    assert r.status_code == 404
