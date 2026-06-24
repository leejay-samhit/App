"""Admin Refund flow with multi-level claw-back (Group 8 — June 2026).

When admin initiates a refund for a user who no longer wants to participate:
  1. Every L1..L10 referral payout that was credited because of THIS user's
     signup is reversed from each recipient's wallet. Wallets may go
     negative — see policy below.
  2. Admin's funding debits for those payouts (lN_funding) are reversed too,
     restoring admin's buckets so the books stay zero-sum.
  3. The original registration-fee credit to admin (direct_signup / GST) is
     reversed for the requested amount. `gst_refund=true` includes the
     18% GST share; `false` keeps GST held on admin's books.
  4. A `refunds` ledger entry is created (Group 8).
  5. A `bank_ledger` debit is created so the System Wallet "bank balance"
     drops by the refunded amount — admin physically pays the user out of
     band (UPI / NEFT). The refund row carries the bank-ledger id.
  6. Final action:
        - soft_delete        : user.status="deleted_refund", hidden from app.
        - remove_referral    : user stays usable for shop / services, but is
                               detached from the upline tree and downline
                               re-parents to the user's grandparent (so the
                               matrix doesn't lose entire sub-trees).

Negative wallet policy (Option C from product):
  When clawback exceeds an upline's available wallet, the wallet goes
  NEGATIVE. We also persist `refund_debt` on the user so subsequent credit
  flows (referral_payout, manual adjust, etc.) can auto-deduct from the
  inflow until the debt is cleared. A red "you owe ₹X" banner can be shown
  on Dashboard reading from that field.

Idempotency:
  Each refund is keyed on `target_user_id` — a user can be refunded only
  once. Re-running returns the existing refund row.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core.db import db
from core.security import require_admin, require_admin_role
from core.utils import now_utc

router = APIRouter()


# ────────────────────────────────────────────────────────────────────
# Search users to refund
# ────────────────────────────────────────────────────────────────────
@router.get("/admin/refunds/search")
async def search_users_for_refund(
    q: str = Query(..., min_length=2, max_length=64),
    limit: int = 12,
    _admin: Dict[str, Any] = Depends(require_admin),
):
    """Find candidate users for refund by name / email / referral_id /
    phone. Excludes admins and users already refunded.
    """
    qn = q.strip().lower()
    rx = {"$regex": qn.replace("+", "\\+"), "$options": "i"}
    filt = {
        "$and": [
            {
                "$or": [
                    {"name": rx},
                    {"email": rx},
                    {"referral_id": rx},
                    {"my_referral_code": rx},
                    {"phone": rx},
                ]
            },
            {"role": {"$nin": ["admin", "super_admin"]}},
        ]
    }
    rows = await db.users.find(
        filt,
        {
            "_id": 0,
            "id": 1,
            "name": 1,
            "email": 1,
            "phone": 1,
            "referral_id": 1,
            "my_referral_code": 1,
            "wallet_balance": 1,
            "registration_paid": 1,
            "registration_amount": 1,
            "sponsor_id": 1,
            "status": 1,
            "refund_debt": 1,
        },
    ).limit(max(1, min(int(limit or 12), 50))).to_list(50)
    # Augment with "already_refunded" flag so the picker can dim them.
    ids = [r["id"] for r in rows if r.get("id")]
    if ids:
        existing = await db.refunds.find(
            {"target_user_id": {"$in": ids}}, {"_id": 0, "target_user_id": 1}
        ).to_list(len(ids))
        done = {e["target_user_id"] for e in existing}
        for r in rows:
            r["already_refunded"] = r.get("id") in done
    return {"items": rows}


# ────────────────────────────────────────────────────────────────────
# Preview the claw-back math (so admin sees impact before committing)
# ────────────────────────────────────────────────────────────────────
@router.get("/admin/refunds/preview/{user_id}")
async def preview_refund(
    user_id: str,
    gst_refund: bool = False,
    _admin: Dict[str, Any] = Depends(require_admin),
):
    user = await db.users.find_one({"id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.get("registration_paid"):
        raise HTTPException(status_code=400, detail="User has no paid registration to refund")
    existing = await db.refunds.find_one({"target_user_id": user_id})
    if existing:
        raise HTTPException(status_code=409, detail="User already refunded")

    # Pull the actual registration transaction to compute the company-share.
    reg_txn = await db.transactions.find_one(
        {
            "user_id": user_id,
            "type": "registration_inflow",
            "status": {"$in": ["paid", "success", "approved"]},
        },
        sort=[("created_at", -1)],
    )
    # Fall back to the user-level `registration_amount` if no inflow doc.
    gross_paid = float(
        (reg_txn or {}).get("amount")
        or user.get("registration_amount")
        or 0
    )
    # GST is 18% INCLUSIVE on Indian registration fees: net = gross / 1.18.
    gst = round(gross_paid - (gross_paid / 1.18), 2)
    net = round(gross_paid - gst, 2)
    refund_amount = round(gross_paid if gst_refund else net, 2)

    # Find every payout this signup triggered.
    payouts = await db.transactions.find(
        {
            "related_signup_id": user_id,
            "type": "referral_payout",
            "status": "success",
        }
    ).sort("level", 1).to_list(50)

    # Resolve recipient details for the preview table.
    rec_ids = list({p.get("user_id") for p in payouts if p.get("user_id")})
    rec_docs = await db.users.find(
        {"id": {"$in": rec_ids}},
        {"_id": 0, "id": 1, "name": 1, "email": 1, "wallet_balance": 1, "refund_debt": 1},
    ).to_list(len(rec_ids)) if rec_ids else []
    by_id = {r["id"]: r for r in rec_docs}

    claw_rows: List[Dict[str, Any]] = []
    total_clawback = 0.0
    total_going_negative = 0.0
    for p in payouts:
        rid = p.get("user_id")
        rec = by_id.get(rid) or {}
        # Net commission credited to the recipient's wallet — what we
        # actually claw back. `amount` field on referral_payout is the NET.
        amt = float(p.get("amount") or 0)
        cur_wallet = float(rec.get("wallet_balance") or 0)
        cur_debt = float(rec.get("refund_debt") or 0)
        after_wallet = round(cur_wallet - amt, 2)
        new_debt = cur_debt + (abs(after_wallet) if after_wallet < 0 else 0)
        claw_rows.append({
            "txn_id": p.get("id"),
            "recipient_id": rid,
            "recipient_name": rec.get("name"),
            "recipient_email": rec.get("email"),
            "level": int(p.get("level") or 0),
            "amount": amt,
            "current_wallet": cur_wallet,
            "wallet_after": after_wallet,
            "current_debt": cur_debt,
            "debt_after": round(new_debt, 2),
            "platform_fee_amount": float(p.get("platform_fee_amount") or 0),
        })
        total_clawback += amt
        if after_wallet < 0:
            total_going_negative += abs(after_wallet)

    return {
        "user": {
            "id": user["id"],
            "name": user.get("name"),
            "email": user.get("email"),
            "referral_id": user.get("referral_id") or user.get("my_referral_code"),
            "registration_paid": True,
            "gross_paid": gross_paid,
        },
        "gst_breakdown": {"gross": gross_paid, "net": net, "gst": gst},
        "gst_refund": bool(gst_refund),
        "refund_amount": refund_amount,
        "clawback": {
            "rows": claw_rows,
            "total": round(total_clawback, 2),
            "going_negative_total": round(total_going_negative, 2),
            "count": len(claw_rows),
        },
        "bank_debit": refund_amount,
        "generated_at": now_utc().isoformat(),
    }


# ────────────────────────────────────────────────────────────────────
# Initiate refund
# ────────────────────────────────────────────────────────────────────
class RefundRequest(BaseModel):
    target_user_id: str = Field(..., min_length=1)
    gst_refund: bool = False
    comments: Optional[str] = Field(default=None, max_length=500)
    final_action: str = Field(default="soft_delete")  # "soft_delete" | "remove_referral"


@router.post("/admin/refunds")
async def initiate_refund(
    payload: RefundRequest,
    admin: Dict[str, Any] = Depends(require_admin),
):
    if payload.final_action not in ("soft_delete", "remove_referral"):
        raise HTTPException(status_code=400, detail="final_action must be soft_delete or remove_referral")

    user = await db.users.find_one({"id": payload.target_user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.get("registration_paid"):
        raise HTTPException(status_code=400, detail="User has no paid registration to refund")
    if (user.get("email") or "").lower().endswith("@networkrupay.com") and user.get("role") in {"admin", "super_admin"}:
        raise HTTPException(status_code=400, detail="Cannot refund admin users")

    # Idempotency — single refund per user.
    if await db.refunds.find_one({"target_user_id": payload.target_user_id}):
        raise HTTPException(status_code=409, detail="User already refunded")

    ts = now_utc().isoformat()
    refund_id = str(uuid.uuid4())

    # ── 1. Compute refund amount from the original registration txn ──
    reg_txn = await db.transactions.find_one(
        {
            "user_id": payload.target_user_id,
            "type": "registration_inflow",
            "status": {"$in": ["paid", "success", "approved"]},
        },
        sort=[("created_at", -1)],
    )
    gross_paid = float((reg_txn or {}).get("amount") or user.get("registration_amount") or 0)
    if gross_paid <= 0:
        raise HTTPException(status_code=400, detail="Could not determine the joining-fee amount paid")
    gst = round(gross_paid - (gross_paid / 1.18), 2)
    net = round(gross_paid - gst, 2)
    refund_amount = round(gross_paid if payload.gst_refund else net, 2)

    # ── 2. Claw back every L1..L10 payout triggered by this signup ──
    payouts = await db.transactions.find(
        {
            "related_signup_id": payload.target_user_id,
            "type": "referral_payout",
            "status": "success",
        }
    ).to_list(50)

    clawback_rows: List[Dict[str, Any]] = []
    total_clawback_net = 0.0
    total_platform_fee_reversed = 0.0
    for p in payouts:
        rid = p.get("user_id")
        if not rid:
            continue
        net_paid = float(p.get("amount") or 0)              # what hit recipient wallet
        platform_fee = float(p.get("platform_fee_amount") or 0)
        level = int(p.get("level") or 0)

        # Debit recipient wallet by NET. Allow going negative — refund_debt
        # tracks the overdraft for future credits to absorb.
        rec = await db.users.find_one({"id": rid})
        if not rec:
            continue
        cur_wallet = float(rec.get("wallet_balance") or 0)
        cur_debt = float(rec.get("refund_debt") or 0)
        new_wallet = round(cur_wallet - net_paid, 2)
        new_debt = cur_debt + (abs(new_wallet) if new_wallet < 0 else 0)
        upd_set: Dict[str, Any] = {"wallet_balance": new_wallet}
        upd_set["refund_debt"] = round(new_debt, 2)
        # Roll back the legacy `total_earned` counter so dashboards stay sane.
        upd_inc: Dict[str, Any] = {"total_earned": -net_paid}
        await db.users.update_one({"id": rid}, {"$set": upd_set, "$inc": upd_inc})

        # Reversal txn (Group 8 visibility — type "refund_clawback").
        clawback_txn_id = str(uuid.uuid4())
        await db.transactions.insert_one({
            "id": clawback_txn_id,
            "user_id": rid,
            "type": "refund_clawback",
            "amount": -net_paid,
            "level": level,
            "status": "success",
            "description": (
                f"Claw-back of L{level} payout (refund of {user.get('name')})"
            ),
            "reverses": p.get("id"),
            "related_refund_id": refund_id,
            "related_signup_id": payload.target_user_id,
            "created_at": ts,
        })

        # If the original payout incurred a platform fee credited to admin,
        # reverse that too so Group 4 stays consistent.
        if platform_fee > 0:
            admin_doc = await db.users.find_one({"email": (await db.users.find_one({"role": "super_admin"}) or {}).get("email", "")})
            if not admin_doc:
                admin_doc = await db.users.find_one({"role": "super_admin"})
            if admin_doc:
                cur_pf = float((admin_doc.get("wallet_buckets") or {}).get("platform_fee_collected") or 0)
                await db.users.update_one(
                    {"id": admin_doc["id"]},
                    {"$set": {"wallet_buckets.platform_fee_collected": round(cur_pf - platform_fee, 2)}},
                )
                await db.transactions.insert_one({
                    "id": str(uuid.uuid4()),
                    "user_id": admin_doc["id"],
                    "type": "platform_fee_reversal",
                    "amount": -platform_fee,
                    "level": level,
                    "status": "success",
                    "description": f"Platform-fee reversal — refund of {user.get('name')}",
                    "related_refund_id": refund_id,
                    "reverses": p.get("id"),
                    "created_at": ts,
                })
                total_platform_fee_reversed += platform_fee

        # Mark the original payout as reversed (informational).
        await db.transactions.update_one(
            {"id": p.get("id")},
            {"$set": {"status": "reversed", "reversed_by": clawback_txn_id, "reversed_at": ts}},
        )

        clawback_rows.append({
            "recipient_id": rid,
            "level": level,
            "amount": net_paid,
            "wallet_before": cur_wallet,
            "wallet_after": new_wallet,
            "debt_added": round(abs(new_wallet) if new_wallet < 0 else 0, 2),
            "platform_fee_reversed": platform_fee,
            "clawback_txn_id": clawback_txn_id,
        })
        total_clawback_net += net_paid

    # ── 3. Reverse admin's lN_funding debits for this signup ──
    funding_txns = await db.transactions.find(
        {
            "related_signup_id": payload.target_user_id,
            "type": {"$regex": "^l[0-9]+_funding$"},
            "status": "success",
        }
    ).to_list(50)
    for f in funding_txns:
        # Original amount is negative (a debit). Add positive to undo.
        amt = float(f.get("amount") or 0)
        bucket = f.get("source_bucket") or "direct_signup"
        rid = f.get("user_id")
        if not rid:
            continue
        # Re-credit admin's bucket by abs(amt). amt is already negative so
        # we use the absolute value for the bucket increment.
        await db.users.update_one(
            {"id": rid},
            {"$inc": {f"wallet_buckets.{bucket}": abs(amt)}},
        )
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": rid,
            "type": "refund_funding_reversal",
            "amount": abs(amt),
            "status": "success",
            "description": f"Reversal of {f.get('type')} (refund of {user.get('name')})",
            "source_bucket": bucket,
            "related_refund_id": refund_id,
            "reverses": f.get("id"),
            "created_at": ts,
        })

    # ── 4. Reverse admin's direct_signup + (optional) gst_collected ──
    # The user's own registration credited admin direct_signup with `net`
    # and gst_collected with `gst`. Reverse those to zero the inflow.
    admin_doc = await db.users.find_one({"role": "super_admin"})
    if admin_doc:
        ds_bucket = float((admin_doc.get("wallet_buckets") or {}).get("direct_signup") or 0)
        await db.users.update_one(
            {"id": admin_doc["id"]},
            {"$set": {"wallet_buckets.direct_signup": round(ds_bucket - net, 2)}},
        )
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": admin_doc["id"],
            "type": "refund_revenue_reversal",
            "amount": -net,
            "status": "success",
            "description": f"Reversal of joining-fee net (refund of {user.get('name')})",
            "source_bucket": "direct_signup",
            "related_refund_id": refund_id,
            "created_at": ts,
        })
        if payload.gst_refund and gst > 0:
            gst_bucket = float((admin_doc.get("wallet_buckets") or {}).get("gst_collected") or 0)
            await db.users.update_one(
                {"id": admin_doc["id"]},
                {"$set": {"wallet_buckets.gst_collected": round(gst_bucket - gst, 2)}},
            )
            await db.transactions.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": admin_doc["id"],
                "type": "refund_gst_reversal",
                "amount": -gst,
                "status": "success",
                "description": f"GST reversal on refund of {user.get('name')}",
                "source_bucket": "gst_collected",
                "related_refund_id": refund_id,
                "created_at": ts,
            })

    # ── 5. Bank ledger debit (the money goes out to user's bank) ──
    bank_entry_id = str(uuid.uuid4())
    await db.bank_ledger.insert_one({
        "id": bank_entry_id,
        "kind": "debit",
        "amount": refund_amount,
        "purpose": "refund",
        "description": (
            f"Refund to {user.get('name')} ({user.get('referral_id') or user.get('email')})"
            + (" · GST included" if payload.gst_refund else "")
        ),
        "related_refund_id": refund_id,
        "related_user_id": payload.target_user_id,
        "created_by": admin["id"],
        "created_at": ts,
    })

    # Mark the original registration_inflow as refunded for visibility.
    if reg_txn:
        await db.transactions.update_one(
            {"id": reg_txn.get("id")},
            {"$set": {"refunded": True, "refunded_at": ts, "related_refund_id": refund_id}},
        )

    # ── 6. Final action on the target user ──
    final_set: Dict[str, Any] = {
        "refunded": True,
        "refunded_at": ts,
        "registration_paid": False,
        "refund_id": refund_id,
    }
    if payload.final_action == "soft_delete":
        final_set["status"] = "deleted_refund"
        final_set["is_blocked"] = True
        final_set["deleted_at"] = ts
    else:
        # Remove from referral scheme: detach from upline AND re-parent any
        # downline children to the user's sponsor (the grandparent).
        sponsor_id = user.get("sponsor_id")
        if sponsor_id:
            await db.users.update_many(
                {"sponsor_id": payload.target_user_id},
                {"$set": {"sponsor_id": sponsor_id}},
            )
            await db.users.update_one(
                {"id": sponsor_id},
                {"$inc": {"direct_referrals_count": -1}},
            )
        final_set["sponsor_id"] = None
        final_set["is_referral_active"] = False
        final_set["status"] = "referral_removed"

    await db.users.update_one({"id": payload.target_user_id}, {"$set": final_set})

    # ── 7. Persist the refund row (Group 8 ledger) ──
    refund_doc = {
        "id": refund_id,
        "target_user_id": payload.target_user_id,
        "target_name": user.get("name"),
        "target_email": user.get("email"),
        "target_referral_id": user.get("referral_id") or user.get("my_referral_code"),
        "gross_paid": gross_paid,
        "gst_refund": bool(payload.gst_refund),
        "gst_amount": gst,
        "net_amount": net,
        "refund_amount": refund_amount,
        "clawback_total": round(total_clawback_net, 2),
        "platform_fee_reversed": round(total_platform_fee_reversed, 2),
        "clawback_rows": clawback_rows,
        "comments": payload.comments,
        "final_action": payload.final_action,
        "bank_ledger_id": bank_entry_id,
        "status": "success",
        "created_by": admin["id"],
        "created_by_name": admin.get("name") or admin.get("email"),
        "created_at": ts,
    }
    await db.refunds.insert_one(refund_doc)

    # Strip _id for response
    refund_doc.pop("_id", None)
    return {"ok": True, "refund": refund_doc}


# ────────────────────────────────────────────────────────────────────
# List + drilldown
# ────────────────────────────────────────────────────────────────────
@router.get("/admin/refunds")
async def list_refunds(
    limit: int = 100,
    _admin: Dict[str, Any] = Depends(require_admin),
):
    rows = await db.refunds.find({}, {"_id": 0}).sort("created_at", -1).limit(max(1, min(int(limit or 100), 500))).to_list(500)
    total_amount = sum(float(r.get("refund_amount") or 0) for r in rows)
    return {"items": rows, "total_count": len(rows), "total_amount": round(total_amount, 2)}


@router.get("/admin/refunds/{refund_id}")
async def get_refund(
    refund_id: str,
    _admin: Dict[str, Any] = Depends(require_admin),
):
    row = await db.refunds.find_one({"id": refund_id}, {"_id": 0})
    if not row:
        raise HTTPException(status_code=404, detail="Refund not found")
    return row
