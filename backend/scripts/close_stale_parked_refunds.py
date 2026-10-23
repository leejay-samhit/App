"""One-time cleanup — close `return_refund` parking rows whose return was
already refunded (the row should have been closed when the money moved, but
rows written before Jun 2026 were never upserted/closed).

Run once:  python3 scripts/close_stale_parked_refunds.py
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.db import db  # noqa: E402

DONE = {"refunded", "refund_paid", "completed", "closed", "company_funded"}


async def main() -> None:
    now = datetime.now(timezone.utc).isoformat()
    closed = 0
    skipped = 0
    async for row in db.vendor_outstanding.find(
        {"status": "open", "kind": "return_refund"}
    ):
        rid = row.get("return_id")
        ret = await db.returns.find_one({"id": rid}) if rid else None
        state = ((ret or {}).get("status") or "").lower()
        refunded = bool((ret or {}).get("refunded_at")) or state in DONE
        if ret and refunded:
            await db.vendor_outstanding.update_one(
                {"id": row["id"]},
                {"$set": {"status": "closed",
                          "closed_at": now,
                          "closed_reason": "stale_parked_refund_cleanup"}},
            )
            closed += 1
            print(f"closed  {row.get('id')}  ret={rid}  state={state or 'missing'}  "
                  f"amount={row.get('amount')}")
        else:
            skipped += 1
            print(f"kept    {row.get('id')}  ret={rid}  state={state or 'missing'}")
    print(f"\nclosed {closed}, kept {skipped}")


if __name__ == "__main__":
    asyncio.run(main())
