"""Snapshot engine v2 (chunked) — take + restore round trip.

The old engine crammed the whole DB into ONE Mongo document (16 MB cap) and
covered only 19 hardcoded collections, so on a real catalogue it silently
degraded to a metadata-only "backup". This checks the new chunked engine:
full coverage, chunks written, and a restore that leaves the data identical.

Restores the SAME snapshot it just took, so the database ends where it began.
"""
import asyncio
import os
import sys

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))


async def main():
    from core.db import db
    from server import _restore_snapshot, _snapshot_collections, _take_snapshot

    before = {}
    for c in await _snapshot_collections():
        before[c] = await db[c].count_documents({})
    print("collections covered:", len(before), "| docs:", sum(before.values()))
    assert len(before) > 40, "coverage regressed — the engine should snapshot the whole app"
    for must in ("users", "products", "orders", "chat_messages", "transactions", "offline_sales", "shop_layout_blocks"):
        assert must in before, f"{must} is missing from snapshot coverage"

    snap = await _take_snapshot(kind="manual", note="iter66 chunked-engine test")
    sid = snap["id"]
    print("snapshot", sid, "counts match:", snap["counts"] == before)
    assert snap["counts"] == before, (snap["counts"], before)

    parent = await db.db_snapshots.find_one({"id": sid}, {"_id": 0})
    assert parent["storage"] == "chunked" and parent["chunks"] > 0, parent
    assert "data" not in parent, "payload must live in chunks, not the parent doc"
    chunks = await db.db_snapshot_chunks.count_documents({"snapshot_id": sid})
    print("chunks written:", chunks)
    assert chunks == parent["chunks"], (chunks, parent["chunks"])

    res = await _restore_snapshot(sid)
    after = {c: await db[c].count_documents({}) for c in before}
    diffs = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
    print("restored collections:", len(res["restored"]), "| diffs:", diffs)
    assert not diffs, f"restore changed the data: {diffs}"

    # tidy up the test snapshot
    await db.db_snapshots.delete_one({"id": sid})
    await db.db_snapshot_chunks.delete_many({"snapshot_id": sid})
    print("PASS")


if __name__ == "__main__":
    asyncio.run(main())
