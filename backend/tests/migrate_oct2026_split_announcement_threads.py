"""One-off migration — un-hijack DM threads that admin broadcast flipped
into read-only announcement channels.

Background
----------
`routes/broadcast._get_or_create_announcement_thread` used to reuse (and
promote) whatever chat thread already existed between the super admin and
the user. `routes/chat.post_message` rejects sends from non-admins on
announcement threads, so after the very first broadcast every user and
vendor lost the ability to message the admin.

The code is fixed (broadcast threads are now separate documents). This
script repairs the existing data:

  For every thread with is_announcement=True that ALSO holds real
  (non-broadcast) conversation:
    1. create / reuse a dedicated announcement thread for the same pair
    2. move the broadcast messages across
    3. clear is_announcement on the original DM thread

Idempotent — safe to re-run.

Run:  python -m tests.migrate_oct2026_split_announcement_threads
"""
import asyncio
import uuid
from datetime import datetime, timezone

from core.db import db


async def main() -> None:
    threads = await db.chat_threads.find({"is_announcement": True}).to_list(100000)
    print(f"announcement threads: {len(threads)}")
    repaired = 0
    moved_total = 0
    for t in threads:
        tid = t["id"]
        real = await db.chat_messages.count_documents(
            {"thread_id": tid, "is_broadcast": {"$ne": True}},
        )
        if real == 0:
            continue  # pure broadcast channel — nothing to repair
        parts = sorted(t.get("participants") or [])
        admin_id = t.get("announcement_by") or (parts[0] if parts else "")
        # Dedicated channel for the broadcast messages.
        channel = await db.chat_threads.find_one(
            {"participants": parts, "is_announcement": True, "id": {"$ne": tid}},
        )
        if not channel:
            channel = {
                "id": str(uuid.uuid4()),
                "participants": parts,
                "is_announcement": True,
                "announcement_by": admin_id,
                "created_at": datetime.now(timezone.utc),
                "last_message_at": t.get("last_message_at") or datetime.now(timezone.utc),
            }
            await db.chat_threads.insert_one(dict(channel))
        res = await db.chat_messages.update_many(
            {"thread_id": tid, "is_broadcast": True},
            {"$set": {"thread_id": channel["id"]}},
        )
        moved_total += res.modified_count
        await db.chat_threads.update_one(
            {"id": tid},
            {"$set": {"is_announcement": False}, "$unset": {"announcement_by": ""}},
        )
        repaired += 1
        print(f"  repaired {tid} → channel {channel['id']} ({res.modified_count} broadcasts moved)")

    # Backfill the explicit flag so future $ne:True queries stay index-friendly.
    await db.chat_threads.update_many(
        {"is_announcement": {"$exists": False}},
        {"$set": {"is_announcement": False}},
    )
    print(f"done. repaired={repaired} broadcasts_moved={moved_total}")


if __name__ == "__main__":
    asyncio.run(main())
