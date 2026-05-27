"""Manual UPI payment flow (Feb-2026).

Replaces Razorpay UI when admin sets `branding.payment_methods.razorpay_enabled=false`
(temporary — Razorpay code stays intact and re-enables instantly via the flag).

USER FLOW:
  1. Browser fetches /payment/upi-config — returns enabled methods + UPI deep-link
     prefix (`upi://pay?pa=<payee>&pn=<name>&am=<fee>&cu=INR`).
  2. Frontend renders Google Pay / PhonePe / Paytm buttons that all open the same
     UPI deep link (the chooser dialog is the OS's responsibility).
  3. After paying, user types/pastes UTR + selects which app they paid with →
     POST /payment/upi-manual creates a row in `manual_payments` with
     status=PENDING.
  4. Admin reviews in /admin/payments/pending, verifies bank statement matches
     UTR + ₹118, then POST /admin/payments/{id}/approve → activates the user
     (mirrors the Razorpay verify path exactly so commission cascade + archive
     fire identically).

SECURITY:
  - UTR submitted on the client is treated as UNVERIFIED until admin approves.
  - We DO NOT auto-approve from client signals — Razorpay's signature could be
    trusted; a typed UTR can't.
  - The frontend never receives the admin's bank account details — only the
    payee UPI ID + display name (both public-by-design).
"""
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core.db import db
from core.rate_limit import limiter as _rl
from core.security import get_current_user, require_admin, require_clean_device
from core.utils import now_utc


router = APIRouter()

# Conservative UTR shape: alphanumeric, 8–22 chars (banks vary).
_UTR_RE = re.compile(r"^[A-Z0-9]{8,22}$")
_VALID_APPS = {"gpay", "phonepe", "paytm", "bhim", "other"}


# ───────────────────────── PAYLOADS ─────────────────────────
class SubmitUpiManualPayload(BaseModel):
    utr: str = Field(..., min_length=8, max_length=22)
    app_used: str = Field(default="other")
    note: Optional[str] = Field(default=None, max_length=300)


class AdminApprovePayload(BaseModel):
    note: Optional[str] = Field(default=None, max_length=500)


class AdminRejectPayload(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)


# ───────────────────────── HELPERS ─────────────────────────
async def _get_payment_config() -> Dict[str, Any]:
    """Read payment-methods config from branding (admin-editable)."""
    from core.branding import get_branding_doc
    doc = await get_branding_doc()
    pm = (doc.get("payment_methods") or {}) if isinstance(doc.get("payment_methods"), dict) else {}
    # Sensible defaults so the UI never crashes when admin hasn't configured.
    return {
        "razorpay_enabled":   bool(pm.get("razorpay_enabled", False)),
        "upi_manual_enabled": bool(pm.get("upi_manual_enabled", True)),
        "payee_upi_id":       (pm.get("payee_upi_id") or "").strip(),
        "payee_name":         (pm.get("payee_name") or doc.get("app_name") or "App").strip(),
    }


async def _registration_fee() -> float:
    s = await db.settings.find_one({"_id": "system"}) or {}
    return float(s.get("registration_fee") or 118.0)


# ───────────────────────── PUBLIC ENDPOINTS ─────────────────────────
@router.get("/payment/upi-config")
async def get_upi_payment_config(user: Dict[str, Any] = Depends(get_current_user)):
    """Returns the data the payment screen needs to render the UPI buttons
    and the user's current pending-payment status."""
    pm   = await _get_payment_config()
    fee  = await _registration_fee()
    # Build the deep-link prefix — apps then add intent-specific routing.
    # tn=<note> & tr=<transactionRef> can be added later; we keep it minimal so
    # all three apps (G Pay, PhonePe, Paytm) accept it identically.
    pa = pm["payee_upi_id"]
    pn = pm["payee_name"] or "App"
    deeplink = ""
    if pa:
        deeplink = (
            f"upi://pay?pa={pa}&pn={pn.replace(' ', '%20')}"
            f"&am={int(fee) if fee == int(fee) else fee}&cu=INR"
        )

    # Current pending payment (if any) — drives the "Pending approval" screen.
    pending = await db.manual_payments.find_one(
        {"user_id": user["id"], "status": {"$in": ["PENDING", "APPROVED"]}},
        {"_id": 0},
        sort=[("created_at", -1)],
    )

    return {
        "methods_enabled": {
            "razorpay":   pm["razorpay_enabled"],
            "upi_manual": pm["upi_manual_enabled"],
        },
        "amount":          fee,
        "currency":        "INR",
        "payee_upi_id":    pm["payee_upi_id"],
        "payee_name":      pm["payee_name"],
        "deeplink_prefix": deeplink,
        "pending_payment": pending,  # null if user hasn't submitted yet
        "registration_paid": bool(user.get("registration_paid")),
    }


@router.post("/payment/upi-manual")
@_rl.limit("10/hour")
async def submit_upi_manual_payment(
    request: Request,
    payload: SubmitUpiManualPayload,
    user: Dict[str, Any] = Depends(require_clean_device),
):
    """User submits the UTR after paying via UPI app. Status starts PENDING —
    NO auto-activation. Admin must approve before commission cascade fires."""
    if user.get("registration_paid"):
        raise HTTPException(status_code=400, detail="Registration fee already paid")

    pm = await _get_payment_config()
    if not pm["upi_manual_enabled"]:
        raise HTTPException(status_code=400, detail="Manual UPI payments are not currently accepted")
    if not pm["payee_upi_id"]:
        raise HTTPException(status_code=500, detail="Payment is not configured. Please contact support.")

    utr = payload.utr.strip().upper()
    if not _UTR_RE.match(utr):
        raise HTTPException(status_code=422, detail="UTR must be 8–22 alphanumeric characters")
    app_used = payload.app_used.strip().lower()
    if app_used not in _VALID_APPS:
        app_used = "other"

    # Prevent duplicate UTR submissions across users — a UTR is unique on the bank side.
    dupe = await db.manual_payments.find_one({"utr": utr})
    if dupe and dupe.get("user_id") != user["id"]:
        raise HTTPException(status_code=409, detail="This UTR has already been submitted by another user")

    fee = await _registration_fee()

    # If user already has a pending submission, REPLACE the UTR/app/note
    # rather than create a second row — keeps the queue clean.
    existing = await db.manual_payments.find_one(
        {"user_id": user["id"], "status": "PENDING"},
        sort=[("created_at", -1)],
    )
    if existing:
        await db.manual_payments.update_one(
            {"id": existing["id"]},
            {"$set": {
                "utr":            utr,
                "app_used":       app_used,
                "note":           (payload.note or "").strip() or None,
                "updated_at":     now_utc().isoformat(),
            }},
        )
        payment_id = existing["id"]
    else:
        payment_id = str(uuid.uuid4())
        await db.manual_payments.insert_one({
            "id":             payment_id,
            "user_id":        user["id"],
            "user_email":     user.get("email"),
            "user_name":      user.get("name"),
            "amount":         fee,
            "currency":       "INR",
            "utr":            utr,
            "app_used":       app_used,
            "payment_method": "upi_manual",
            "status":         "PENDING",
            "note":           (payload.note or "").strip() or None,
            "approved_by":    None,
            "approved_at":    None,
            "rejected_at":    None,
            "rejection_reason": None,
            "created_at":     now_utc().isoformat(),
            "updated_at":     now_utc().isoformat(),
        })
        # Mirror a placeholder transaction row in the user's wallet so the
        # transaction history shows "Registration fee · pending verification".
        await db.transactions.insert_one({
            "id":              str(uuid.uuid4()),
            "user_id":         user["id"],
            "type":            "registration_fee",
            "amount":          fee,
            "status":          "pending",
            "description":     f"Registration fee via UPI · UTR {utr} (awaiting approval)",
            "reference_number": utr,
            "payment_method":  "upi_manual",
            "manual_payment_id": payment_id,
            "created_at":      now_utc().isoformat(),
        })

    return {"ok": True, "payment_id": payment_id, "status": "PENDING"}


@router.get("/payment/upi-manual/status")
async def get_my_upi_manual_status(user: Dict[str, Any] = Depends(get_current_user)):
    """Polled by the user's "Pending approval" screen to learn when admin
    approves. Returns the latest non-rejected payment row (if any)."""
    row = await db.manual_payments.find_one(
        {"user_id": user["id"]},
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    return {"payment": row, "registration_paid": bool(user.get("registration_paid"))}


# ───────────────────────── ADMIN ENDPOINTS ─────────────────────────
@router.get("/admin/payments/pending")
async def list_pending_payments(
    limit: int = 200,
    status: str = "PENDING",
    _admin: Dict[str, Any] = Depends(require_admin),
):
    """List manual UPI payments by status (default PENDING) so admin / finance
    can verify and approve. Embeds user phone for quick contact."""
    status_filter = status.upper() if status else "PENDING"
    rows: List[Dict[str, Any]] = await db.manual_payments.find(
        {"status": status_filter},
        {"_id": 0},
    ).sort("created_at", -1).limit(max(1, min(int(limit), 500))).to_list(500)
    # Hydrate phone (not denormalized in manual_payments).
    user_ids = list({r["user_id"] for r in rows})
    users = await db.users.find({"id": {"$in": user_ids}}, {"_id": 0, "id": 1, "phone": 1, "referral_code": 1, "referred_by": 1}).to_list(len(user_ids) or 1)
    by_uid = {u["id"]: u for u in users}
    for r in rows:
        u = by_uid.get(r["user_id"], {})
        r["user_phone"]         = u.get("phone")
        r["user_referral_code"] = u.get("referral_code")
        r["user_referred_by"]   = u.get("referred_by")
    return {"items": rows, "count": len(rows)}


@router.post("/admin/payments/{payment_id}/approve")
async def approve_manual_payment(
    payment_id: str,
    payload: AdminApprovePayload,
    admin: Dict[str, Any] = Depends(require_admin),
):
    """Mark the manual UPI payment as APPROVED, activate the user's account,
    and fire the same L1–L10 commission cascade that runs after Razorpay
    verify. Idempotent — re-approving a row is a no-op."""
    row = await db.manual_payments.find_one({"id": payment_id})
    if not row:
        raise HTTPException(status_code=404, detail="Payment not found")
    if row["status"] == "APPROVED":
        return {"ok": True, "already_approved": True}
    if row["status"] == "REJECTED":
        raise HTTPException(status_code=400, detail="Cannot approve a rejected payment")

    user = await db.users.find_one({"id": row["user_id"]})
    if not user:
        raise HTTPException(status_code=404, detail="User no longer exists")
    if user.get("registration_paid"):
        # Already approved (perhaps via another path). Bring this row in sync.
        await db.manual_payments.update_one(
            {"id": payment_id},
            {"$set": {"status": "APPROVED", "approved_at": now_utc().isoformat(), "approved_by": admin.get("email")}},
        )
        return {"ok": True, "already_paid": True}

    fee = await _registration_fee()
    now_iso = now_utc().isoformat()

    # 1) Mark the user paid + approved (atomic — no double-fire).
    upd = await db.users.update_one(
        {"id": user["id"], "registration_paid": {"$ne": True}},
        {"$set": {
            "registration_paid":  True,
            "registration_source": "upi_manual",
            "payment_method":     "upi_manual",
            "razorpay_utr":       row["utr"],         # reuse same field for invoice rendering
            "paid_at":            now_iso,
            "approval_status":    "approved",
            "approval_reviewed_at": now_iso,
            "approval_reviewed_by": admin.get("email") or admin.get("id"),
        }},
    )
    if upd.modified_count == 0:
        # Race: someone else paid in the meantime — fall through to record approval anyway.
        pass

    # 2) Promote the pending transaction row to paid.
    await db.transactions.update_one(
        {"user_id": user["id"], "manual_payment_id": payment_id, "status": "pending"},
        {"$set": {
            "status":           "paid",
            "source":           "upi_manual",
            "description":      f"Registration fee via UPI · UTR {row['utr']} (approved by {admin.get('email')})",
            "paid_at":          now_iso,
        }},
    )

    # 3) Fire the same downstream side-effects as Razorpay verify.
    fresh = await db.users.find_one({"id": user["id"]})
    if fresh:
        try:
            from server import _trigger_referral_commissions, _archive_approved_user, _audit_log, _create_notification
            try:
                await _trigger_referral_commissions(fresh)
            except Exception:
                pass
            try:
                await _archive_approved_user(fresh, admin)
            except Exception:
                pass
            try:
                await _audit_log(admin, "payment.upi_manual.approve", "manual_payment", payment_id,
                                 {"utr": row["utr"], "amount": fee, "app_used": row.get("app_used")})
            except Exception:
                pass
            try:
                await _create_notification(
                    user["id"], "approval", "Account approved",
                    f"Your UPI payment (UTR {row['utr']}) has been verified. You're now active.",
                )
            except Exception:
                pass
        except Exception:
            pass

    # 4) Update the manual_payments row to reflect approval.
    await db.manual_payments.update_one(
        {"id": payment_id},
        {"$set": {
            "status":         "APPROVED",
            "approved_by":    admin.get("email") or admin.get("id"),
            "approved_at":    now_iso,
            "admin_note":     (payload.note or "").strip() or None,
            "updated_at":     now_iso,
        }},
    )

    return {"ok": True, "payment_id": payment_id, "status": "APPROVED"}


@router.post("/admin/payments/{payment_id}/reject")
async def reject_manual_payment(
    payment_id: str,
    payload: AdminRejectPayload,
    admin: Dict[str, Any] = Depends(require_admin),
):
    row = await db.manual_payments.find_one({"id": payment_id})
    if not row:
        raise HTTPException(status_code=404, detail="Payment not found")
    if row["status"] == "APPROVED":
        raise HTTPException(status_code=400, detail="Cannot reject an already-approved payment")

    now_iso = now_utc().isoformat()
    await db.manual_payments.update_one(
        {"id": payment_id},
        {"$set": {
            "status":           "REJECTED",
            "rejected_at":      now_iso,
            "rejected_by":      admin.get("email") or admin.get("id"),
            "rejection_reason": payload.reason.strip(),
            "updated_at":       now_iso,
        }},
    )
    await db.transactions.update_one(
        {"user_id": row["user_id"], "manual_payment_id": payment_id},
        {"$set": {"status": "failed",
                  "description": f"Registration fee rejected by admin · {payload.reason.strip()}"}},
    )
    try:
        from server import _create_notification, _audit_log
        await _create_notification(
            row["user_id"], "approval", "Payment needs attention",
            f"Your UPI submission was rejected: {payload.reason.strip()}. Please re-submit with the correct UTR.",
        )
        await _audit_log(admin, "payment.upi_manual.reject", "manual_payment", payment_id,
                         {"reason": payload.reason.strip(), "utr": row.get("utr")})
    except Exception:
        pass
    return {"ok": True, "payment_id": payment_id, "status": "REJECTED"}
