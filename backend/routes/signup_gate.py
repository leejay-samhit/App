"""Signup gate — mandatory, WhatsApp-verified mobile number.

Oct-2026 owner rule. A Google sign-in used to land straight on the
"Pay ₹118 / continue without subscription" screen, so an account could be
created with NO mobile number and NO sponsor. Both payment options are now
locked until this gate passes:

  * mobile number — MANDATORY, 10 digits, must not already belong to someone
  * invite code   — OPTIONAL; blank or unknown falls back to the admin code
                    ("EARN"), so every member always has a sponsor

If the mobile already exists we do NOT silently merge or overwrite: we return
the owning account's name + masked email so the app can tell the user to sign
in with that same email instead, or use a different mobile AND email. This is
the only safe answer — a phone number is the one field two real people are
most likely to collide on.

The same gate runs once for EXISTING users (including already-paid ones), who
just re-confirm their mobile and invite code.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from core.security import get_current_user
from core import otply
from core.db import db
from core.utils import now_utc, serialize_user
from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)
router = APIRouter()

# Nov-2026 — invite codes, sponsors and the ₹118 payment gate are gone. The
# gate now does ONE job: make sure the account has a mobile number that the
# person actually controls, proven by the WhatsApp OTP.

PHONE_TAKEN_MESSAGE = (
    "That mobile number is already registered to another account. "
    "Sign in with that account's email, or use a different number."
)


async def ensure_indexes() -> None:
    """Unique index on the normalised phone — the real race guard.

    Oct-2026: check-then-write let several accounts confirm the SAME number
    when they raced each other (6 parallel confirms → up to 5 owners). The
    duplicate check stays for the friendly conflict card; this index is what
    actually makes it impossible.

    Partial on purpose: accounts without a phone yet must not collide on null,
    and legacy rows with a non-10-digit phone are left alone.
    """
    try:
        await db.users.create_index(
            "phone",
            unique=True,
            name="uniq_user_phone",
            partialFilterExpression={"phone": {"$type": "string", "$gt": ""}},
        )
    except Exception as e:
        logger.warning(f"signup-gate phone index not applied ({e}) — duplicates stay possible")


class GateCheck(BaseModel):
    phone: str


class GateConfirm(BaseModel):
    phone: str
    otp: str


def normalise_phone(raw: str) -> str:
    """Keep the last 10 digits — users type +91, 0-prefixes and spaces."""
    digits = re.sub(r"\D+", "", raw or "")
    if len(digits) > 10:
        digits = digits[-10:]
    return digits


def mask_email(email: str) -> str:
    """j***n@gmail.com — enough to recognise your own account, not enough to
    enumerate someone else's."""
    email = (email or "").strip()
    if "@" not in email:
        return email
    local, _, domain = email.partition("@")
    if len(local) <= 2:
        shown = local[:1] + "*"
    else:
        shown = f"{local[0]}{'*' * max(1, len(local) - 2)}{local[-1]}"
    return f"{shown}@{domain}"


@router.get("/auth/signup-gate/status")
async def gate_status(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Does this account still have to pass the gate?"""
    phone_verified = bool(user.get("phone_verified"))
    paid = bool(user.get("registration_paid"))
    free_path = bool(user.get("subscription_skipped"))
    # Oct-2026 — a single, DERIVED status so there is never a second copy of
    # the truth to drift. Nothing new is stored: every value below is read
    # from the fields that already decide behaviour.
    if not (phone_verified or user.get("signup_gate_confirmed_at")):
        registration_status = "pending_verification"
    else:
        # Nov-2026 — registration is free for everyone. `paid` only survives
        # so historical ₹118 receipts still render in the account history.
        registration_status = "verified"
    return {
        "required": not bool(user.get("signup_gate_confirmed_at")),
        "phone": user.get("phone") or "",
        "phone_verified": phone_verified,
        "phone_verified_method": user.get("phone_verified_method"),
        "referral_code_used": user.get("referred_by") or "",
        "registration_paid": paid,
        "registration_status": registration_status,
        "registration_path": "paid" if paid else ("free" if free_path else "undecided"),
        "auth_provider": user.get("auth_provider") or "password",
    }


@router.post("/auth/signup-gate/check")
async def gate_check(
    payload: GateCheck,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Validate the mobile + invite code WITHOUT saving anything.

    Returns `ok: false` with a `conflict` block when the number already
    belongs to a different account, so the app can show the exact wording the
    owner asked for (registered name + email + "sign in with that email").
    """
    phone = normalise_phone(payload.phone)
    if len(phone) != 10:
        raise HTTPException(status_code=400, detail="Enter a valid 10-digit mobile number.")
    if phone[0] not in "6789":
        raise HTTPException(status_code=400, detail="Indian mobile numbers start with 6, 7, 8 or 9.")

    # ── Duplicate check — twice, exactly as asked. Once on the normalised
    # 10-digit form and once on anything that merely ENDS with those digits,
    # so a legacy "+919154735888" row can never slip through.
    owner = await db.users.find_one(
        {"phone": phone, "id": {"$ne": user["id"]}},
        {"_id": 0, "id": 1, "name": 1, "email": 1, "auth_provider": 1},
    )
    if not owner:
        owner = await db.users.find_one(
            {"phone": {"$regex": f"{phone}$"}, "id": {"$ne": user["id"]}},
            {"_id": 0, "id": 1, "name": 1, "email": 1, "auth_provider": 1},
        )

    if owner:
        return {
            "ok": False,
            "conflict": {
                "reason": "phone_taken",
                "name": owner.get("name") or "an existing member",
                "email": owner.get("email") or "",
                "email_masked": mask_email(owner.get("email") or ""),
                "signed_in_with_google": (owner.get("auth_provider") == "google"),
                "message": (
                    f"This mobile number is already registered as "
                    f"{owner.get('name') or 'an existing member'} "
                    f"({mask_email(owner.get('email') or '')}). Please sign in by tapping "
                    f"\u201cContinue\u201d with that same email id, or use a different mobile "
                    f"number and a different email id. Need help? Raise a ticket using Contact."
                ),
            },
        }

    return {"ok": True, "phone": phone}


@router.post("/auth/signup-gate/confirm")
async def gate_confirm(
    payload: GateConfirm,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Verify the WhatsApp code and attach the number to this account.

    Nov-2026 — the number is now PROVEN, not self-declared: the same OTPly
    code the mobile sign-in uses is verified here before the number is saved.
    There is no invite code and no payment step after this.
    """
    verdict = await gate_check(GateCheck(phone=payload.phone), user)
    if not verdict.get("ok"):
        raise HTTPException(status_code=409, detail=verdict["conflict"]["message"])
    phone = verdict["phone"]

    # A number CHANGE on an already-verified account is refused outright:
    # silently moving a verified flag onto a brand-new number is exactly the
    # takeover shape this gate exists to stop.
    current = normalise_phone(user.get("phone") or "")
    if user.get("phone_verified") and current and current != phone:
        raise HTTPException(
            status_code=409,
            detail="This account already has a verified mobile number. Contact support to change it.",
        )

    try:
        await otply.verify_otp(phone, payload.otp)
    except otply.OtpError as e:
        raise HTTPException(status_code=e.status, detail=e.message)

    update: Dict[str, Any] = {
        "phone": phone,
        "phone_verified": True,
        "phone_verified_method": "whatsapp_otp",
        "phone_verified_at": now_utc().isoformat(),
        "signup_gate_confirmed_at": now_utc().isoformat(),
    }
    try:
        await db.users.update_one({"id": user["id"]}, {"$set": update})
    except DuplicateKeyError:
        # Lost the race against another account confirming the same number.
        raise HTTPException(status_code=409, detail=PHONE_TAKEN_MESSAGE)
    fresh = await db.users.find_one({"id": user["id"]}, {"_id": 0})
    return {"ok": True, "phone": phone, "user": serialize_user(fresh)}


@router.post("/auth/signup-gate/send-otp")
async def gate_send_otp(
    payload: GateCheck,
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Send the WhatsApp code for the number this account wants to attach."""
    verdict = await gate_check(payload, user)
    if not verdict.get("ok"):
        raise HTTPException(status_code=409, detail=verdict["conflict"]["message"])
    fwd = request.headers.get("x-forwarded-for") or ""
    ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "")
    try:
        return await otply.send_otp(verdict["phone"], ip=ip, purpose="signup_gate")
    except otply.OtpError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
