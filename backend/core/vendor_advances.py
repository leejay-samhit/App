"""Seller advances — money Slangcart paid OUT on a seller's behalf that is
not cashback (a return refund the company funded because the shop wallet was
short, a delivery fee the seller owes us, …).

Cashback has its own counter on the user document (`cashback_outstanding`);
these debts live only as `vendor_outstanding` rows, so this module is the ONE
place they are totalled and recovered. Recovery is the same single process the
owner asked for — straight out of the seller's shop-earnings wallet:

    vendor wallet (Group 2 liability) ──► treasury

Nothing can be double-booked: the rows are CLAIMED with optimistic
`$inc`-on-exact-value updates before the wallet is touched, the wallet debit is
idempotent, and the claims are handed straight back if the debit fails.
"""
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from core.db import db
from core.utils import now_utc

logger = logging.getLogger(__name__)

# Debts the company actually paid out and expects back from the seller.
RECOVERABLE_KINDS = ("return_refund_company_funded", "delivery_fee",
                     "delivery_fee_company_funded")


async def open_total(vendor_id: str) -> float:
    """What this seller still owes us, excluding cashback."""
    agg = await db.vendor_outstanding.aggregate([
        {"$match": {"vendor_id": vendor_id, "status": "open",
                    "kind": {"$in": list(RECOVERABLE_KINDS)}}},
        {"$group": {"_id": None, "sum": {"$sum": {
            "$subtract": ["$amount", {"$ifNull": ["$recovered", 0]}],
        }}}},
    ]).to_list(1)
    return round(float((agg or [{}])[0].get("sum") or 0), 2)


async def _claim(vendor_id: str, amount: float) -> Tuple[float, List[Dict[str, Any]]]:
    """Reserve `amount` against the open rows, oldest first.

    Each row is claimed with a filter on its CURRENT `recovered` value, so two
    parallel recoveries cannot both claim the same rupees. Returns what was
    actually claimed and enough detail to undo it.
    """
    remaining = round(max(0.0, float(amount or 0)), 2)
    ts = now_utc().isoformat()
    claimed: List[Dict[str, Any]] = []
    total = 0.0
    cursor = db.vendor_outstanding.find(
        {"vendor_id": vendor_id, "status": "open",
         "kind": {"$in": list(RECOVERABLE_KINDS)}},
    ).sort("created_at", 1)
    async for row in cursor:
        if remaining <= 0.009:
            break
        had = round(float(row.get("recovered") or 0), 2)
        owed = round(float(row.get("amount") or 0) - had, 2)
        if owed <= 0.009:
            continue
        take = round(min(owed, remaining), 2)
        fully = take >= owed - 0.009
        res = await db.vendor_outstanding.update_one(
            {"id": row["id"], "status": "open", "recovered": row.get("recovered") or 0},
            {"$set": {"recovered": round(had + take, 2),
                      "status": "settled" if fully else "open",
                      "updated_at": ts,
                      **({"settled_at": ts} if fully else {})}},
        )
        if res.modified_count != 1:
            continue  # somebody else got there first
        claimed.append({"id": row["id"], "take": take, "was": had,
                        "was_status": "open", "kind": row.get("kind")})
        total = round(total + take, 2)
        remaining = round(remaining - take, 2)
    return total, claimed


async def _unclaim(claimed: List[Dict[str, Any]]) -> None:
    """Hand a claim back — but ONLY if nobody has claimed on top of it, so a
    rollback can never wipe out a parallel recovery that did go through."""
    for c in claimed:
        await db.vendor_outstanding.update_one(
            {"id": c["id"], "recovered": round(c["was"] + c["take"], 2)},
            {"$set": {"recovered": c["was"], "status": c["was_status"]},
             "$unset": {"settled_at": ""}},
        )


async def recover_from_wallet(
    vendor_id: str,
    amount: float,
    *,
    credit_admin_bucket,
    note: str = "Recovered from seller's shop-earnings wallet",
    recorded_by: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Take up to `amount` of the seller's non-cashback debt out of his wallet."""
    from core import shop_money

    want = round(max(0.0, float(amount or 0)), 2)
    if want <= 0.009:
        return {"applied": 0.0, "rows": 0}

    v = await db.users.find_one(
        {"id": vendor_id},
        {"_id": 0, "vendor_earnings": 1, "vendor_business_name": 1,
         "shop_name": 1, "name": 1},
    )
    if not v:
        raise ValueError("Seller not found")
    owed = await open_total(vendor_id)
    available = round(float(v.get("vendor_earnings") or 0), 2)
    cap = round(min(want, owed, max(0.0, available)), 2)
    if cap <= 0.009:
        return {"applied": 0.0, "rows": 0, "outstanding_before": owed,
                "outstanding_after": owed, "wallet_before": available,
                "reason": "nothing_to_recover" if owed <= 0.009 else "wallet_empty"}

    take, claimed = await _claim(vendor_id, cap)
    if take <= 0.009:
        await _unclaim(claimed)
        return {"applied": 0.0, "rows": 0, "reason": "already_recovered",
                "outstanding_before": owed, "outstanding_after": owed}

    shop = v.get("vendor_business_name") or v.get("shop_name") or v.get("name") or "Seller"
    key = idempotency_key or f"ADVRECOVER-WALLET:{uuid.uuid4().hex[:10]}"
    try:
        row = await shop_money.debit(
            vendor_id, shop_money.VENDOR_WALLET, take,
            idempotency_key=key,
            group="vendor_payable",
            txn_type="advance_recovery",
            vendor_id=vendor_id,
            shop_name=shop,
            settlement_status="recovered",
            description=(
                f"{note} — ₹{take:g} of ₹{owed:g} the company advanced for this shop "
                f"(return refunds / fees) taken from {shop}'s shop earnings wallet "
                f"into the System Wallet treasury"
            ),
            extra={"wallet_impact": "vendor_earnings_only", "manual_recovery": True,
                   "recovery_method": "wallet", "recorded_by": recorded_by,
                   "recovery_ref": key,
                   "kinds": sorted({c["kind"] for c in claimed if c.get("kind")})},
        )
    except shop_money.InsufficientFunds:
        await _unclaim(claimed)
        return {"applied": 0.0, "rows": 0, "reason": "wallet_empty",
                "outstanding_before": owed, "outstanding_after": owed}
    except Exception:
        await _unclaim(claimed)
        raise
    if row is None:
        await _unclaim(claimed)
        return {"applied": 0.0, "rows": 0, "reason": "replay",
                "outstanding_before": owed, "outstanding_after": owed}

    # Mirror of the funding entry in core.returns (which booked the advance as
    # a margin loss), so the two net to zero once the money is back.
    await credit_admin_bucket("shopping_margin", take, also_total_earned=False)
    return {
        "applied": take,
        "rows": len(claimed),
        "outstanding_before": owed,
        "outstanding_after": round(owed - take, 2),
        "wallet_before": available,
        "wallet_after": round(available - take, 2),
        "reference": key,
    }
