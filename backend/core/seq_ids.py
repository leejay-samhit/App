"""Permanent, human-readable sequential IDs (TXNA1, ORD1, CUS1 …).

Admin reports must never show a 20-character database id. This module hands
out short codes that are:

* **sequential** — TXNA1, TXNA2, TXNA3 … TXNA100 … TXNA100000
* **permanent** — assigned once, stored, and returned unchanged forever
* **never reused** — a cancelled ORD5 keeps its code; the next order is ORD6
* **non-destructive** — the real `id` on the document is untouched. The
  mapping lives in its own `short_ids` collection keyed by the long id, so
  nothing in the existing schema has to change.

Downloading the same Excel twice therefore produces identical IDs, and an
admin can paste `TXNA125` into search to open the original record.
"""
import logging
from typing import Any, Dict, Iterable, List, Optional

from core.db import db
from core.utils import now_utc

logger = logging.getLogger(__name__)

# kind → prefix. Adding a kind is safe; its counter starts at 1.
PREFIXES: Dict[str, str] = {
    "txn":        "TXNA",
    "order":      "ORD",
    "payment":    "PAY",
    "customer":   "CUS",
    "vendor":     "VEN",
    "shop":       "SHP",
    "cashback":   "CBK",
    "settlement": "SET",
    "delivery":   "DEL",
    "refund":     "REF",
    "wallet":     "WLT",
}


def prefix_for(kind: str) -> str:
    try:
        return PREFIXES[kind]
    except KeyError:
        raise ValueError(f"Unknown short-id kind: {kind}")


async def _next_seq(kind: str) -> int:
    """Atomically claim the next number for this kind."""
    doc = await db.counters.find_one_and_update(
        {"_id": f"shortid:{kind}"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,  # type: ignore[arg-type]
    )
    return int((doc or {}).get("seq") or 1)


async def get_or_create(kind: str, ref_id: str) -> str:
    """Return the permanent short code for `ref_id`, minting it on first use.

    Safe under concurrency: the mapping row's `_id` is the (kind, ref_id)
    pair, so a racing writer's insert fails and we read back the winner's
    code instead of issuing a second one.
    """
    pref = prefix_for(kind)
    if not ref_id:
        return ""
    key = f"{kind}:{ref_id}"
    existing = await db.short_ids.find_one({"_id": key}, {"_id": 0, "code": 1})
    if existing and existing.get("code"):
        return str(existing["code"])

    seq = await _next_seq(kind)
    code = f"{pref}{seq}"
    try:
        await db.short_ids.insert_one({
            "_id": key,
            "kind": kind,
            "ref_id": ref_id,
            "code": code,
            "seq": seq,
            "created_at": now_utc().isoformat(),
        })
        return code
    except Exception:
        # Lost the race — the number we claimed is simply skipped (IDs are
        # never reused, and gaps are harmless). Return the winner's code.
        winner = await db.short_ids.find_one({"_id": key}, {"_id": 0, "code": 1})
        return str((winner or {}).get("code") or code)


async def get_many(kind: str, ref_ids: Iterable[str]) -> Dict[str, str]:
    """Bulk resolve — one query for the ones we already know, then mint the
    rest. Used by the Excel exporter so a 50 000-row report is not 50 000
    round trips."""
    ids = [r for r in dict.fromkeys(ref_ids) if r]
    if not ids:
        return {}
    keys = [f"{kind}:{r}" for r in ids]
    out: Dict[str, str] = {}
    async for row in db.short_ids.find({"_id": {"$in": keys}}, {"_id": 0, "ref_id": 1, "code": 1}):
        out[str(row["ref_id"])] = str(row["code"])
    for ref in ids:
        if ref not in out:
            out[ref] = await get_or_create(kind, ref)
    return out


async def resolve(code: str) -> Optional[Dict[str, Any]]:
    """Reverse lookup so admin search accepts `TXNA125` and opens the
    original record."""
    code = (code or "").strip().upper()
    if not code:
        return None
    row = await db.short_ids.find_one({"code": code}, {"_id": 0})
    return row


_BACKFILL_SPECS: List[Dict[str, Any]] = [
    {"kind": "txn",      "collection": "transactions"},
    {"kind": "order",    "collection": "orders"},
    {"kind": "customer", "collection": "users",    "query": {"role": {"$ne": "admin"}}},
    {"kind": "vendor",   "collection": "users",    "query": {"is_vendor": True}},
    {"kind": "cashback", "collection": "cashback_ledger", "id_field": "_id"},
    {"kind": "refund",   "collection": "refund_requests"},
    {"kind": "delivery", "collection": "withdrawals"},
]


async def backfill(limit_per_kind: int = 100_000) -> Dict[str, int]:
    """Assign codes to everything that predates this feature, in CREATION
    order so the numbering reads chronologically. Idempotent — rows that
    already have a mapping are skipped by `get_or_create`."""
    stats: Dict[str, int] = {}
    for spec in _BACKFILL_SPECS:
        kind = spec["kind"]
        coll = getattr(db, spec["collection"])
        id_field = spec.get("id_field", "id")
        query = dict(spec.get("query") or {})
        minted = 0
        cursor = coll.find(query, {"_id": 1, id_field: 1, "created_at": 1}).sort("created_at", 1).limit(limit_per_kind)
        async for doc in cursor:
            ref = doc.get(id_field) if id_field != "_id" else doc.get("_id")
            if not ref:
                continue
            key = f"{kind}:{ref}"
            if await db.short_ids.find_one({"_id": key}, {"_id": 1}):
                continue
            await get_or_create(kind, str(ref))
            minted += 1
        stats[kind] = minted
    return stats


async def ensure_indexes() -> None:
    try:
        await db.short_ids.create_index("code", unique=True)
        await db.short_ids.create_index([("kind", 1), ("seq", 1)])
    except Exception as err:  # pragma: no cover
        logger.warning(f"short_ids index setup: {str(err)[:200]}")
