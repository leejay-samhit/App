"""Bank ledger — the company's real bank account, Group 7 (Sep-2026).

ONE rule: every rupee that lands in (or leaves) the company bank account
gets exactly one row here. Because of that:

    bank balance = Σ credits − Σ debits  ==  the bank statement

Nothing is "derived" from revenue tables any more, so the System Wallet's
Bank Balance Tally can be reconciled line-by-line against a real statement.

Money that arrives here is NOT automatically ours:
  * a wallet top-up is a **liability** (we owe the customer their balance)
  * a marketplace order receipt is a **liability** (we owe the vendor)
  * a registration fee / delivery charge IS **revenue** (ours, net of GST)

So `bank balance` is an ASSET figure and the liability groups are subtracted
from it in the net-worth formula — never netted off inside this ledger.

Idempotency is enforced by a unique index on `ref_key`, so a replayed
webhook or a double-tapped checkout can only ever write one row.
"""
import logging
import uuid
from typing import Any, Dict, Optional

from core.db import db
from core.utils import now_utc

logger = logging.getLogger(__name__)

# What the money IS, for the admin drill-down. `liability` categories mean
# the cash is in our bank but earmarked for someone else.
LIABILITY_CATEGORIES = {"wallet_topup", "shop_order_online", "cod_remittance"}
REVENUE_CATEGORIES = {"registration_fee", "delivery_charge", "service_fee", "platform_fee"}


async def ensure_indexes() -> None:
    try:
        await db.bank_ledger.create_index(
            "ref_key", unique=True, sparse=True, name="uniq_bank_ref_key",
        )
    except Exception as err:  # pragma: no cover
        logger.warning(f"bank ledger index setup: {str(err)[:200]}")


async def post_bank(
    *,
    kind: str,                       # "credit" (money in) | "debit" (money out)
    amount: float,
    category: str,
    description: str,
    ref_key: str,                    # idempotency key — one row per real event
    utr: Optional[str] = None,
    user_id: Optional[str] = None,
    vendor_id: Optional[str] = None,
    order_id: Optional[str] = None,
    payment_method: str = "razorpay",
    happened_at: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Write ONE bank row. Returns None when the row already existed."""
    amount = round(float(amount or 0), 2)
    if amount <= 0.009 or kind not in ("credit", "debit"):
        return None
    ts = happened_at or now_utc().isoformat()
    doc: Dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "ref_key": ref_key,
        "kind": kind,
        "amount": amount,
        "category": category,
        "money_nature": (
            "liability" if category in LIABILITY_CATEGORIES
            else "revenue" if category in REVENUE_CATEGORIES
            else "other"
        ),
        "description": description,
        "utr": utr,
        "user_id": user_id,
        "vendor_id": vendor_id,
        "order_id": order_id,
        "payment_method": payment_method,
        "happened_at": ts,
        "created_at": ts,
        **(extra or {}),
    }
    try:
        await db.bank_ledger.insert_one(doc)
    except Exception as err:
        if "duplicate" in str(err).lower() or "E11000" in str(err):
            return None
        raise
    doc.pop("_id", None)
    return doc


async def totals() -> Dict[str, float]:
    """Credits, debits and balance — this IS the bank statement."""
    rows = await db.bank_ledger.aggregate([
        {"$group": {"_id": "$kind", "sum": {"$sum": "$amount"}}},
    ]).to_list(10)
    by_kind = {r["_id"]: float(r["sum"] or 0) for r in rows}
    credits = round(by_kind.get("credit", 0.0), 2)
    debits = round(by_kind.get("debit", 0.0), 2)
    return {"credits": credits, "debits": debits, "balance": round(credits - debits, 2)}


async def by_category() -> Dict[str, Dict[str, float]]:
    """Per-category credit/debit split so admin can see where cash came from."""
    rows = await db.bank_ledger.aggregate([
        {"$group": {
            "_id": {"c": "$category", "k": "$kind"},
            "sum": {"$sum": "$amount"},
            "n": {"$sum": 1},
        }},
    ]).to_list(200)
    out: Dict[str, Dict[str, float]] = {}
    for r in rows:
        cat = r["_id"].get("c") or "other"
        kind = r["_id"].get("k") or "credit"
        slot = out.setdefault(cat, {"credit": 0.0, "debit": 0.0, "count": 0})
        slot[kind] = round(float(r["sum"] or 0), 2)
        slot["count"] += int(r["n"] or 0)
    return out
