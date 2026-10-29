"""Truecaller one-tap mobile verification (Oct 2026).

FLOW — the client never holds anything that decides the outcome:

  1. `POST /api/auth/truecaller/start`
     The SERVER mints the OAuth `state` and the PKCE `code_verifier`, stores
     them against this user with a short TTL, and hands the app only the
     `state` + `code_challenge`. The verifier never leaves the backend.
  2. The app passes those to the Truecaller SDK, which shows Truecaller's own
     consent sheet and returns a one-time authorization code.
  3. `POST /api/auth/truecaller/verify`
     The server consumes the state (single use), exchanges the code WITH its
     own verifier at Truecaller's token endpoint, reads the number back from
     Truecaller's `userinfo`, and only then marks the phone verified.

So a tapped button proves nothing: without a live server-issued state and a
code that Truecaller itself honours, verification simply does not happen.

Duplicate protection reuses the existing signup-gate rules, so a number that
already belongs to another account is refused with the same wording rather
than being merged or taken over.
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core import truecaller
from core.db import db
from core.pkce import code_challenge_for
from core.rate_limit import limiter
from core.security import get_current_user
from core.utils import now_utc, serialize_user
from routes.signup_gate import (
    normalise_phone,
    resolve_sponsor,
    FALLBACK_INVITE_CODE,
    PHONE_TAKEN_MESSAGE,
)
from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)
router = APIRouter()

STATE_TTL_SECONDS = 300


class StartBody(BaseModel):
    purpose: str = Field(default="registration", max_length=32)


@router.get("/auth/truecaller/availability")
async def truecaller_availability(user: Dict[str, Any] = Depends(get_current_user)):
    """Is one-tap verification configured, and is this account already done?"""
    return {
        "configured": truecaller.is_enabled(),
        "phone_verified": bool(user.get("phone_verified")),
        "phone": user.get("phone") or "",
        "method": user.get("phone_verified_method"),
        # The manual mobile-number form stays available as the documented
        # alternative when Truecaller is missing, cancelled or unusable.
        "fallback": "manual_entry",
    }


@router.post("/auth/truecaller/start")
@limiter.limit("10/minute")
async def truecaller_start(
    request: Request,
    body: StartBody,
    user: Dict[str, Any] = Depends(get_current_user),
):
    if not truecaller.is_enabled():
        raise HTTPException(status_code=503, detail="One-tap verification isn't switched on yet.")

    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)[:96]
    now = datetime.now(timezone.utc)
    await db.truecaller_states.insert_one({
        "state": state,
        "user_id": user["id"],
        "code_verifier": verifier,
        "purpose": body.purpose,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=STATE_TTL_SECONDS)).isoformat(),
        "used_at": None,
    })
    return {
        "state": state,
        "code_challenge": code_challenge_for(verifier),
        "scopes": ["openid", "profile", "phone"],
        "ttl_seconds": STATE_TTL_SECONDS,
    }


class VerifyBody(BaseModel):
    state: str = Field(..., max_length=128)
    authorization_code: str = Field(..., max_length=4096)
    referral_code: Optional[str] = Field(default=None, max_length=32)


@router.post("/auth/truecaller/verify")
@limiter.limit("10/minute")
async def truecaller_verify(
    request: Request,
    body: VerifyBody,
    user: Dict[str, Any] = Depends(get_current_user),
):
    if not truecaller.is_enabled():
        raise HTTPException(status_code=503, detail="One-tap verification isn't switched on yet.")

    # ── Consume the state: single use, unexpired, and owned by this account.
    row = await db.truecaller_states.find_one({"state": body.state}, {"_id": 0})
    if not row or row.get("user_id") != user["id"]:
        raise HTTPException(status_code=400, detail="This verification attempt is no longer valid. Please try again.")
    if row.get("used_at"):
        raise HTTPException(status_code=400, detail="This verification attempt was already used.")
    if datetime.now(timezone.utc) > datetime.fromisoformat(row["expires_at"]):
        raise HTTPException(status_code=400, detail="Verification timed out. Please try again.")
    claimed = await db.truecaller_states.update_one(
        {"state": body.state, "used_at": None},
        {"$set": {"used_at": now_utc().isoformat()}},
    )
    if claimed.modified_count != 1:
        raise HTTPException(status_code=400, detail="This verification attempt was already used.")

    result = await truecaller.verify_authorization_code(body.authorization_code, row["code_verifier"])
    if not result["ok"]:
        logger.warning(f"truecaller verify rejected: {result['reason']}")
        raise HTTPException(status_code=401, detail="We couldn't confirm that number. Please try again.")

    phone = normalise_phone(result["phone"])
    if len(phone) != 10:
        raise HTTPException(status_code=400, detail="Truecaller returned an unsupported number for India.")

    # ── Same duplicate rules as the manual gate: never merge, never take over.
    owner = await db.users.find_one(
        {"$or": [{"phone": phone}, {"phone": {"$regex": f"{phone}$"}}], "id": {"$ne": user["id"]}},
        {"_id": 0, "id": 1, "name": 1, "email": 1},
    )
    if owner:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{phone[:2]}****{phone[-2:]} is already registered to "
                f"{owner.get('name') or 'another member'}. Sign in with that account's email, "
                "or verify a different mobile number."
            ),
        )
    # If this account already verified a DIFFERENT number, refuse silently
    # swapping it — that is an account-takeover shape, not a correction.
    existing = normalise_phone(user.get("phone") or "")
    if user.get("phone_verified") and existing and existing != phone:
        raise HTTPException(
            status_code=409,
            detail="This account already has a verified mobile number. Contact support to change it.",
        )

    resolved = await resolve_sponsor(body.referral_code)
    sponsor = resolved["sponsor"]
    update: Dict[str, Any] = {
        "phone": phone,
        "phone_verified": True,
        "phone_verified_method": "truecaller",
        "phone_verified_at": now_utc().isoformat(),
        "truecaller_sub": result["subject"],
        # The manual gate and this path unlock the very same screen.
        "signup_gate_confirmed_at": user.get("signup_gate_confirmed_at") or now_utc().isoformat(),
    }
    if sponsor and not user.get("referred_by"):
        update["referred_by"] = sponsor.get("referral_code")
        update["sponsor_id"] = sponsor.get("id")

    try:
        await db.users.update_one({"id": user["id"]}, {"$set": update})
    except DuplicateKeyError:
        # Another account claimed this number first; never merge or overwrite.
        raise HTTPException(status_code=409, detail=PHONE_TAKEN_MESSAGE)
    fresh = await db.users.find_one({"id": user["id"]}, {"_id": 0})
    return {
        "ok": True,
        "phone": phone,
        "phone_verified": True,
        "method": "truecaller",
        "invite_code": update.get("referred_by") or user.get("referred_by") or FALLBACK_INVITE_CODE,
        "user": serialize_user(fresh),
    }


async def ensure_indexes() -> None:
    try:
        await db.truecaller_states.create_index("state", unique=True, name="uniq_tc_state")
        # Short-lived by nature: drop rows an hour after they are minted.
        await db.truecaller_states.create_index("created_at", expireAfterSeconds=3600, name="tc_state_ttl")
    except Exception as e:
        logger.warning(f"truecaller index setup: {e}")
