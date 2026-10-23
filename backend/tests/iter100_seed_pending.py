"""Iter100 — seed/remove a TEST_ pending-approval product for the admin Products UI check.
Usage: python3 iter100_seed_pending.py seed|clean"""
import asyncio, os, sys
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.db import db  # noqa
PID = "TEST_i100_pending_ui"
async def main(cmd):
    await db.products.delete_one({"id": PID})
    if cmd == "seed":
        base = await db.products.find_one({"id": "401f3c2b-362a-4cfe-9d25-1e432f7ab97e"}, {"_id": 0})
        base.update({"id": PID, "name": "TEST_i100 Pending Widget", "is_published": False, "review_status": "pending",
                     "review_fields": ["price"], "created_at": datetime.now(timezone.utc).isoformat()})
        await db.products.insert_one(base)
    print(cmd, "ok")
asyncio.run(main(sys.argv[1]))
