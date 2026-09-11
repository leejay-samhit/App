"""MLM cutover (Jun-2026) — one-time data migration.

Business decision: the Level 1-10 / referral-income model is gone. Slangcart
is a marketplace with purchase cashback. This module performs the one-time
cutover on the data that the old engine left behind.

What it does
------------
1. **Zeroes out MLM-earned wallet money.** For every non-admin member we
   total the referral income they were ever credited
   (`referral_payout` rows still in `success`) and debit that amount from
   their wallet — capped at whatever they actually still hold, so a wallet
   can never be pushed negative by the cutover.
2. **Keeps the books balanced.** Every debit is mirrored by a credit into
   the platform's `referral_commission` bucket (the payouts were funded out
   of platform revenue in the first place), and an offsetting
   `mlm_cutover_reclaim` transaction is written on the admin account. Total
   debit == total credit, so Company Net Worth does not move.
3. **Never deletes history.** The original `referral_payout` rows are
   preserved untouched and only stamped `mlm_cutover=True` so reports can
   tell that the money was reclaimed at cutover.
4. **Clears the dead counters** (`pending_directs`, `pending_l2..l10`,
   `true_direct_count`, `pending_true_directs`, `payouts_received`,
   `total_earned`, `referral_enabled`) so no stale progress bar or gate can
   resurrect the old behaviour.

Idempotent: guarded by an `app_state` marker, and each user is stamped
`mlm_cutover_at` so a re-run can never double-debit.
"""
import logging
import uuid
from typing import Any, Dict

from core.db import db
from core.utils import now_utc

logger = logging.getLogger(__name__)

MIGRATION_KEY = "mlm_cutover_2026_06"

_DEAD_FIELDS = [
    "pending_directs",
    "pending_true_directs",
    "true_direct_count",
    "payouts_received",
    "referral_enabled",
    "referral_switch_note",
    "referral_switch_at",
    "referral_switch_by",
] + [f"pending_l{i}" for i in range(2, 11)]


async def _referral_income(user_id: str) -> float:
    agg = await db.transactions.aggregate([
        {"$match": {"user_id": user_id, "type": "referral_payout", "status": "success"}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
    ]).to_list(1)
    return round(float(agg[0]["total"]), 2) if agg else 0.0


async def run_mlm_cutover(admin_email: str, credit_admin_bucket) -> Dict[str, Any]:
    """Execute the cutover once. `credit_admin_bucket` is injected to avoid
    a circular import back into server.py."""
    if await db.app_state.find_one({"_id": MIGRATION_KEY}):
        return {"skipped": True}

    ts = now_utc().isoformat()
    admin = await db.users.find_one({"email": admin_email.lower()}, {"_id": 0, "id": 1})
    admin_id = (admin or {}).get("id")

    users = db.users.find(
        {"role": {"$ne": "admin"}, "mlm_cutover_at": {"$exists": False}},
        {"_id": 0, "id": 1, "name": 1, "wallet_balance": 1, "email": 1},
    )
    touched = 0
    total_reclaimed = 0.0
    total_written_off = 0.0

    async for u in users:
        uid = u["id"]
        earned = await _referral_income(uid)
        held = round(float(u.get("wallet_balance") or 0), 2)
        reclaim = round(min(max(earned, 0.0), max(held, 0.0)), 2)
        written_off = round(max(earned - reclaim, 0.0), 2)

        upd: Dict[str, Any] = {
            "$set": {
                "mlm_cutover_at": ts,
                "mlm_cutover_reclaimed": reclaim,
                "mlm_cutover_written_off": written_off,
                "total_earned": 0.0,
            },
            "$unset": {f: "" for f in _DEAD_FIELDS},
        }
        if reclaim > 0:
            upd["$inc"] = {"wallet_balance": -reclaim}
        await db.users.update_one({"id": uid}, upd)

        if reclaim > 0:
            await db.transactions.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": uid,
                "type": "mlm_cutover_reversal",
                "amount": -reclaim,
                "status": "success",
                "description": (
                    f"Referral-income reversal \u2014 \u20b9{reclaim:g} reclaimed at the "
                    f"Slangcart cashback cutover. Referral earnings are discontinued; "
                    f"cashback is now earned on delivered orders."
                ),
                "mlm_cutover": True,
                "created_at": ts,
            })
        if earned > 0:
            await db.transactions.update_many(
                {"user_id": uid, "type": "referral_payout", "status": "success"},
                {"$set": {"mlm_cutover": True, "mlm_cutover_at": ts}},
            )
        total_reclaimed += reclaim
        total_written_off += written_off
        touched += 1

    total_reclaimed = round(total_reclaimed, 2)
    if total_reclaimed > 0 and admin_id:
        # Mirror entry so Total Debit == Total Credit across the ledger.
        await credit_admin_bucket("referral_commission", total_reclaimed, also_total_earned=False)
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": admin_id,
            "type": "mlm_cutover_reclaim",
            "amount": total_reclaimed,
            "status": "success",
            "description": (
                f"Referral-income reclaim at cashback cutover \u2014 \u20b9{total_reclaimed:g} "
                f"recovered from {touched} member wallets"
            ),
            "mlm_cutover": True,
            "created_at": ts,
        })

    result = {
        "users_touched": touched,
        "reclaimed": total_reclaimed,
        "written_off": round(total_written_off, 2),
        "at": ts,
    }
    await db.app_state.insert_one({"_id": MIGRATION_KEY, **result})
    logger.info(
        f"MLM cutover: {touched} members, \u20b9{total_reclaimed} reclaimed, "
        f"\u20b9{result['written_off']} written off"
    )
    return result
