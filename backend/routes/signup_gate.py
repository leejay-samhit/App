"""Signup gate — mandatory mobile number + optional invite code.

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

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.security import get_current_user
from core.config import ADMIN_EMAIL
from core.db import db
from core.utils import now_utc, serialize_user
from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)
router = APIRouter()

FALLBACK_INVITE_CODE = "EARN"   # the super admin's own referral code

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
    referral_code: Optional[str] = None


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


async def resolve_sponsor(code: Optional[str]) -> Dict[str, Any]:
    """Blank or unknown invite code → the admin's code. Never fails."""
    typed = (code or "").strip().upper()
    sponsor = None
    if typed:
        sponsor = await db.users.find_one(
            {"referral_code": typed},
            {"_id": 0, "id": 1, "name": 1, "referral_code": 1},
        )
    used_fallback = sponsor is None
    if used_fallback:
        sponsor = await db.users.find_one(
            {"referral_code": FALLBACK_INVITE_CODE},
            {"_id": 0, "id": 1, "name": 1, "referral_code": 1},
        ) or await db.users.find_one(
            {"email": ADMIN_EMAIL.lower()},
            {"_id": 0, "id": 1, "name": 1, "referral_code": 1},
        )
    return {
        "sponsor": sponsor,
        "typed": typed,
        "used_fallback": used_fallback,
        "invalid_code": bool(typed) and used_fallback,
    }


@router.get("/auth/signup-gate/status")
async def gate_status(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Does this account still have to pass the gate?"""
    from core import truecaller as _tc

    phone_verified = bool(user.get("phone_verified"))
    paid = bool(user.get("registration_paid"))
    free_path = bool(user.get("subscription_skipped"))
    # Oct-2026 — a single, DERIVED status so there is never a second copy of
    # the truth to drift. Nothing new is stored: every value below is read
    # from the fields that already decide behaviour.
    if not (phone_verified or user.get("signup_gate_confirmed_at")):
        registration_status = "pending_verification"
    elif paid:
        registration_status = "payment_success"
    elif free_path:
        registration_status = "free_registration"
    else:
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
        "truecaller_available": _tc.is_enabled(),
        "fallback_code": FALLBACK_INVITE_CODE,
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

    resolved = await resolve_sponsor(payload.referral_code)
    sponsor = resolved["sponsor"]

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

    return {
        "ok": True,
        "phone": phone,
        "invite_code": (sponsor or {}).get("referral_code") or FALLBACK_INVITE_CODE,
        "invite_owner": (sponsor or {}).get("name") or "Slangcart",
        "used_fallback": resolved["used_fallback"],
        "invalid_code": resolved["invalid_code"],
        "notice": (
            f"That invite code wasn't found, so you'll join under the official "
            f"Slangcart code {FALLBACK_INVITE_CODE}."
            if resolved["invalid_code"] else
            (f"You'll join under the official Slangcart code {FALLBACK_INVITE_CODE}."
             if resolved["used_fallback"] else
             f"Invited by {(sponsor or {}).get('name') or 'a member'}.")
        ),
    }


@router.post("/auth/signup-gate/confirm")
async def gate_confirm(
    payload: GateCheck,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Save the mobile + sponsor and unlock the payment options.

    Re-runs the duplicate check so a race between two devices can't land the
    same number on two accounts.
    """
    verdict = await gate_check(payload, user)
    if not verdict.get("ok"):
        raise HTTPException(status_code=409, detail=verdict["conflict"]["message"])

    phone = verdict["phone"]
    resolved = await resolve_sponsor(payload.referral_code)
    sponsor = resolved["sponsor"]

    update: Dict[str, Any] = {
        "phone": phone,
        "signup_gate_confirmed_at": now_utc().isoformat(),
    }
    # A number CHANGE on an account whose number was verified by Truecaller is
    # refused outright: silently keeping `phone_verified: true` against a
    # brand-new number is exactly the takeover shape this gate exists to stop.
    current = normalise_phone(user.get("phone") or "")
    if user.get("phone_verified") and current and current != phone:
        raise HTTPException(
            status_code=409,
            detail="This account already has a verified mobile number. Contact support to change it.",
        )
    # Manual entry is the documented ALTERNATIVE to Truecaller, so it records
    # how the number was obtained without ever claiming it was verified by a
    # third party. A Truecaller pass later upgrades this to "truecaller".
    if not user.get("phone_verified"):
        update["phone_verified_method"] = "self_declared"
    # Never move an existing member off the sponsor who already earned on
    # them — the upline cascade is paid on `referred_by`, so rewriting it
    # after the fact would silently reassign someone else's commission.
    if sponsor and not user.get("referred_by"):
        update["referred_by"] = sponsor.get("referral_code")
        update["sponsor_id"] = sponsor.get("id")

    try:
        await db.users.update_one({"id": user["id"]}, {"$set": update})
    except DuplicateKeyError:
        # Lost the race against another account confirming the same number.
        raise HTTPException(status_code=409, detail=PHONE_TAKEN_MESSAGE)
    fresh = await db.users.find_one({"id": user["id"]}, {"_id": 0})
    return {
        "ok": True,
        "phone": phone,
        "invite_code": update.get("referred_by") or user.get("referred_by") or FALLBACK_INVITE_CODE,
        "used_fallback": resolved["used_fallback"],
        "user": serialize_user(fresh),
    }
