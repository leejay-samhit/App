"""One-shot cleanup: deduplicate l1_funding rows that were created
multiple times by the pre-fix backfill loop (no related_payout_txn_id
stamp meant every backend restart re-debited the same L1 payout).

Strategy:
  1. Get ALL l1_funding txns.
  2. Get ALL referral_payout L1 txns. For each, compute the LEGITIMATE
     debit total (= gross_amount, which is the L1 payout).
  3. Group l1_funding txns by related_payout_recipient. Compare actual
     sum vs legitimate sum → if actual exceeds legitimate, refund the
     surplus back to admin buckets and delete the extra rows.
  4. Stamp surviving l1_funding rows with the matching referral_payout's
     txn id (related_payout_txn_id) so the new idempotent backfill will
     skip them on next restart.

Safe to run multiple times — pure cleanup.
"""
import asyncio
import os
from collections import defaultdict

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")
client = AsyncIOMotorClient(os.environ["MONGO_URL"])
db = client[os.environ.get("DB_NAME", "test_database")]

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@app.com").lower()


async def main():
    admin = await db.users.find_one({"email": ADMIN_EMAIL})
    if not admin:
        print("[!] No admin user found — aborting.")
        return

    # Load all L1 referral_payout txns (the legitimate L1 events).
    legit_l1s = await db.transactions.find({
        "type": "referral_payout",
        "level": 1,
        "status": "success",
    }, {"_id": 0, "id": 1, "user_id": 1, "gross_amount": 1, "amount": 1,
        "related_signup_id": 1, "source_user_name": 1, "created_at": 1}).to_list(100000)

    # Map: recipient_id → legitimate total debit due
    legit_due = defaultdict(float)
    legit_txns_by_recipient = defaultdict(list)
    for tx in legit_l1s:
        recipient = tx["user_id"]
        # If recipient IS admin, that's the L1-cycle-to-admin path (no funding needed
        # because admin recipient is paid from referral_commission via _credit_payout's
        # admin branch, NOT from fee_residual). Skip these.
        rec_doc = await db.users.find_one({"id": recipient}, {"email": 1})
        if rec_doc and (rec_doc.get("email") or "").lower() == ADMIN_EMAIL:
            continue
        gross = float(tx.get("gross_amount") or tx.get("amount") or 0)
        if gross <= 0:
            continue
        legit_due[recipient] += gross
        legit_txns_by_recipient[recipient].append(tx)

    # Load all l1_funding txns
    fundings = await db.transactions.find({"type": "l1_funding"}, {
        "_id": 0, "id": 1, "amount": 1, "source_bucket": 1,
        "related_payout_recipient": 1, "related_signup_id": 1,
        "related_payout_txn_id": 1, "created_at": 1,
    }).to_list(100000)

    # Group by recipient
    by_recipient = defaultdict(list)
    for f in fundings:
        rid = f.get("related_payout_recipient")
        if not rid:
            continue
        by_recipient[rid].append(f)

    print(f"[i] Found {len(legit_l1s)} L1 payouts, {len(fundings)} l1_funding rows.")

    total_refunded = 0.0
    total_deleted = 0

    for recipient, funds in by_recipient.items():
        actual_debit = sum(abs(float(x["amount"])) for x in funds)  # amounts are negative
        legit = legit_due.get(recipient, 0.0)
        surplus = round(actual_debit - legit, 2)
        if surplus <= 0.01:
            continue
        print(f"[fix] recipient={recipient}: debited ₹{actual_debit}, due ₹{legit}, "
              f"surplus ₹{surplus} → cleaning up")
        # Sort by created_at descending — delete newest extras
        funds_sorted = sorted(funds, key=lambda x: x.get("created_at") or "", reverse=True)
        remaining_to_refund = surplus
        for f in funds_sorted:
            if remaining_to_refund <= 0.01:
                break
            amt = abs(float(f["amount"]))
            bucket = f.get("source_bucket")
            # Refund: credit back to admin bucket
            refund = round(min(amt, remaining_to_refund), 2)
            await db.users.update_one(
                {"id": admin["id"]},
                {"$inc": {f"wallet_buckets.{bucket}": refund, "wallet_balance": refund}},
            )
            # Delete this row if we refunded the whole thing; otherwise partial refund
            if refund == amt:
                await db.transactions.delete_one({"id": f["id"]})
                total_deleted += 1
            else:
                # Partial — adjust the txn amount (rare; only if surplus < single row)
                new_amt = round(-(amt - refund), 2)
                await db.transactions.update_one(
                    {"id": f["id"]},
                    {"$set": {"amount": new_amt,
                              "description": f.get("description", "") + " [cleanup-partial-refund]"}},
                )
            remaining_to_refund -= refund
            total_refunded += refund

    # Stamp surviving l1_funding rows with their matching referral_payout txn id,
    # so the new idempotent backfill check on (related_payout_txn_id) skips them.
    stamped = 0
    for recipient, l1_txns in legit_txns_by_recipient.items():
        # Re-query l1_funding for this recipient (post-delete state)
        remaining_funds = await db.transactions.find({
            "type": "l1_funding", "related_payout_recipient": recipient,
            "related_payout_txn_id": {"$in": [None, ""]},
        }).to_list(1000)
        # Round-robin map oldest L1 → oldest funding (1-to-1)
        l1_sorted = sorted(l1_txns, key=lambda x: x.get("created_at") or "")
        funds_sorted = sorted(remaining_funds, key=lambda x: x.get("created_at") or "")
        # Map by GROUPS — each L1 may have multiple funding rows (split across buckets).
        # Find consecutive funding rows summing to gross.
        f_idx = 0
        for l1 in l1_sorted:
            gross = float(l1.get("gross_amount") or l1.get("amount") or 0)
            acc = 0.0
            group = []
            while f_idx < len(funds_sorted) and acc < gross - 0.01:
                f = funds_sorted[f_idx]
                acc += abs(float(f["amount"]))
                group.append(f)
                f_idx += 1
            for f in group:
                await db.transactions.update_one(
                    {"id": f["id"]},
                    {"$set": {"related_payout_txn_id": l1["id"],
                              "related_signup_id": l1.get("related_signup_id") or f.get("related_signup_id")}},
                )
                stamped += 1

    print(f"[ok] Refunded ₹{total_refunded:.2f}, deleted {total_deleted} duplicate l1_funding rows, "
          f"stamped {stamped} survivors with related_payout_txn_id.")


asyncio.run(main())
