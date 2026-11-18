"""Mobile-number sign-in with a WhatsApp OTP (OTPly).

Nov-2026 — replaces the Truecaller flow.

  POST /api/auth/otp/send    { mobile }            → sends the code
  POST /api/auth/otp/verify  { mobile, otp, name? } → signs in / signs up

The backend is the only thing that can declare a number verified: the app
sends the typed code here and gets a session back, or an error.

Account rules (owner decision, Nov-2026)
  * A verified number that already belongs to an account signs INTO that
    account — the OTP proves ownership, so no duplicate is created.
  * If that account is blocked, we do not sign in; we say which account it is
    (name + masked email) so the person can use the right sign-in.
  * A brand-new number creates a free customer account. No payment, no
    invite code, no sponsor.
"""
from __future__ import annotations

import logging
import uuid

from pymongo.errors import DuplicateKeyError
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core import otply
from core.db import db
from core.login_history import record_login
from core.security import (
    create_access_token,
    get_current_user,
    create_refresh_token,
    new_session_id,
    register_session,
)
from core.utils import gen_referral_code, now_utc, serialize_user

logger = logging.getLogger(__name__)
router = APIRouter()


class SendOtpRequest(BaseModel):
    mobile: str = Field(..., description="10-digit Indian mobile number")


class VerifyOtpRequest(BaseModel):
    mobile: str
    otp: str
    name: Optional[str] = None     # only used when creating a new account


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for") or ""
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


def _mask_email(email: str) -> str:
    email = (email or "").strip()
    if "@" not in email:
        return ""
    name, domain = email.split("@", 1)
    head = name[:2] if len(name) > 2 else name[:1]
    return f"{head}{'*' * max(3, len(name) - len(head))}@{domain}"


@router.post("/auth/otp/send")
async def send_login_otp(request: Request, payload: SendOtpRequest):
    try:
        return await otply.send_otp(payload.mobile, ip=_client_ip(request), purpose="login")
    except otply.OtpError as e:
        raise HTTPException(status_code=e.status, detail=e.message)


@router.post("/auth/otp/verify")
async def verify_login_otp(request: Request, payload: VerifyOtpRequest):
    try:
        mobile = await otply.verify_otp(payload.mobile, payload.otp)
    except otply.OtpError as e:
        raise HTTPException(status_code=e.status, detail=e.message)

    # Match on the exact number first, then on a stored number that merely
    # carries a country code / spacing (older rows were never normalised).
    user = await db.users.find_one({"phone": mobile})
    if not user:
        user = await db.users.find_one({"phone": {"$regex": f"{mobile}$"}})

    created = False
    if user:
        if user.get("is_blocked"):
            raise HTTPException(
                status_code=403,
                detail=(
                    f"This number belongs to {user.get('name') or 'an account'} "
                    f"({_mask_email(user.get('email', ''))}), which is currently blocked. "
                    "Please contact support."
                ),
            )
        # Nov-2026 phone ownership. A number typed at signup is NOT proof of
        # anything: anyone could have entered a stranger's number. So when the
        # matched account never verified it and has its own way in (password
        # or Google), the number is RELEASED from that account and whoever
        # just proved control of it continues with their own account. The
        # other account keeps its email/Google sign-in and all its data — it
        # only loses an unproven phone field.
        never_verified = not user.get("phone_verified")
        has_other_login = bool(user.get("password_hash") or user.get("password")) or bool(
            user.get("auth_provider") or user.get("google_id")
        )
        if never_verified and has_other_login:
            await db.users.update_one(
                {"id": user["id"]},
                {"$set": {
                    "phone": "",
                    "phone_released_at": now_utc().isoformat(),
                    "phone_released_reason": "claimed_by_whatsapp_otp",
                }},
            )
            user = None   # fall through to "sign in / create for this number"
    if user:
        # Keep the stored number in the normalised shape from now on.
        if user.get("phone") != mobile:
            await db.users.update_one({"id": user["id"]}, {"$set": {"phone": mobile}})
            user["phone"] = mobile
        await db.users.update_one(
            {"id": user["id"]},
            {"$set": {"phone_verified": True, "phone_verified_at": now_utc().isoformat()}},
        )
        user["phone_verified"] = True
    else:
        user_id = str(uuid.uuid4())
        # users.referral_code has a NON-sparse unique index: a missing code is
        # indexed as null and collides with any other code-less account (500).
        while True:
            ref_code = gen_referral_code()
            if not await db.users.find_one({"referral_code": ref_code}):
                break
        user = {
            "id": user_id,
            "name": (payload.name or "").strip() or f"Slangcart {mobile[-4:]}",
            # NO `email` key at all: a mobile-only account has no email, and an
            # empty string collides on the unique email index.
            "phone": mobile,
            "phone_verified": True,
            "phone_verified_at": now_utc().isoformat(),
            "auth_method": "mobile_otp",
            "role": "user",
            "admin_role": None,
            "referral_code": ref_code,
            "wallet_balance": 0.0,
            "is_blocked": False,
            "block_reason": None,
            "wallet_frozen": False,
            "kyc_status": "none",
            # Free from Nov-2026: no registration payment, no invite code.
            "registration_paid": False,
            "approval_status": "approved",
            "profile_complete": bool((payload.name or "").strip()),
            "created_at": now_utc().isoformat(),
        }
        try:
            await db.users.insert_one(dict(user))
        except DuplicateKeyError:
            # Another device finished the same signup a moment earlier.
            existing = await db.users.find_one({"phone": mobile}, {"_id": 0})
            if not existing:
                raise HTTPException(
                    status_code=409,
                    detail="Couldn't finish sign-in. Please request a new code.",
                )
            user = existing
        else:
            created = True

    sid = new_session_id()
    await register_session(user["id"], sid)
    token = create_access_token(user["id"], user.get("email", ""), user.get("role", "user"), sid=sid)
    refresh = create_refresh_token(user["id"], sid)
    try:
        await record_login(user, request, sid, method="mobile_otp")
    except Exception:
        pass
    return {
        "token": token,
        "refresh_token": refresh,
        "user": serialize_user(user),
        "created": created,
        "needs_profile": not bool((user.get("name") or "").strip()) or not user.get("profile_complete", True),
    }


class CompleteProfileRequest(BaseModel):
    name: str
    email: Optional[str] = None


@router.post("/auth/otp/complete-profile")
async def complete_profile(
    payload: CompleteProfileRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Finish a brand-new mobile account: name (required) + email (optional)."""
    name = (payload.name or "").strip()
    if len(name) < 2:
        raise HTTPException(status_code=400, detail="Please enter your full name.")
    update: Dict[str, Any] = {"name": name, "profile_complete": True}
    email = (payload.email or "").strip().lower()
    if email:
        clash = await db.users.find_one({"email": email, "id": {"$ne": user["id"]}})
        if clash:
            raise HTTPException(
                status_code=409,
                detail="That email is already used by another Slangcart account.",
            )
        update["email"] = email
    await db.users.update_one({"id": user["id"]}, {"$set": update})
    fresh = await db.users.find_one({"id": user["id"]}, {"_id": 0})
    return {"user": serialize_user(fresh)}


# ──────────────────────────────────────────────────────────────────────
# Changing the mobile number on an existing account (Nov-2026, req 8).
# The new number must be proven by a WhatsApp code before it replaces the
# old one, so nobody can take over a number they do not control. Wallet,
# orders and transactions stay on the same account id throughout.
# ──────────────────────────────────────────────────────────────────────

class ChangeMobileSendRequest(BaseModel):
    mobile: str = Field(..., min_length=10, max_length=15)


class ChangeMobileVerifyRequest(BaseModel):
    mobile: str = Field(..., min_length=10, max_length=15)
    otp: str = Field(..., min_length=4, max_length=8)


@router.post("/me/mobile/change/send-otp")
async def change_mobile_send(
    request: Request,
    payload: ChangeMobileSendRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    try:
        mobile = otply.normalise_mobile(payload.mobile)
    except otply.OtpError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    if mobile == (user.get("phone") or ""):
        raise HTTPException(
            status_code=400, detail="That is already your registered number.",
        )
    clash = await db.users.find_one(
        {"phone": mobile, "id": {"$ne": user["id"]}}, {"_id": 0, "name": 1, "email": 1},
    )
    if clash:
        raise HTTPException(
            status_code=409,
            detail=(
                "This number is already on another Slangcart account"
                f"{(' (' + _mask_email(clash.get('email', '')) + ')') if clash.get('email') else ''}. "
                "Sign in to that account instead."
            ),
        )
    try:
        return await otply.send_otp(mobile, ip=_client_ip(request), purpose="change")
    except otply.OtpError as e:
        raise HTTPException(status_code=e.status, detail=e.message)


@router.post("/me/mobile/change/verify")
async def change_mobile_verify(
    payload: ChangeMobileVerifyRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    try:
        mobile = await otply.verify_otp(payload.mobile, payload.otp)
    except otply.OtpError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    try:
        await db.users.update_one(
            {"id": user["id"]},
            {"$set": {
                "phone": mobile,
                "phone_verified": True,
                "phone_verified_at": now_utc().isoformat(),
                "phone_changed_at": now_utc().isoformat(),
            }},
        )
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="This number was just taken by another account. Try a different one.",
        )
    fresh = await db.users.find_one({"id": user["id"]}, {"_id": 0})
    return {"ok": True, "user": serialize_user(fresh)}
