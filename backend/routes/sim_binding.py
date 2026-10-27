"""SIM-binding API.

    POST /api/sim-binding/challenge     — server nonce, single-use, 120 s
    POST /api/sim-binding/verify        — submit a device SIM check + nonce
    POST /api/sim-binding/number-proof  — submit a Truecaller auth code
    GET  /api/sim-binding/status        — server truth for this user
    POST /api/sim-binding/revalidate    — force a re-check (SIM swap, support)
    POST /api/sim-binding/device-link/start  — verified phone mints a QR code
    POST /api/sim-binding/device-link/claim  — browser redeems it
    GET  /api/admin/sim-binding/overview     — admin dashboard + audit tail
    PATCH /api/admin/sim-binding/policy      — admin flips enforcement

Design rule enforced throughout: the client never decides its own level. It
reports observations; this module decides. A request that merely claims
"verified" is rejected — the nonce must match an unused, unexpired, own-user
challenge, and number ownership must come back from Truecaller's servers.
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core import sim_binding as sb
from core import truecaller
from core.db import db
from core.rate_limit import limiter
from core.security import get_current_user, require_admin

logger = logging.getLogger(__name__)
router = APIRouter()


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for") or ""
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else ""))[:64]


def _ua(request: Request) -> str:
    return (request.headers.get("user-agent") or "")[:160]


# ── Challenge ────────────────────────────────────────────────────────────
class ChallengeBody(BaseModel):
    purpose: str = Field(default="sim_check", max_length=32)
    device_fp: str = Field(default="", max_length=64)


@router.post("/sim-binding/challenge")
@limiter.limit("20/minute")
async def sim_challenge(
    request: Request,
    body: ChallengeBody,
    user: Dict[str, Any] = Depends(get_current_user),
):
    ch = await sb.create_challenge(user["id"], body.purpose, body.device_fp)
    await sb.audit(user["id"], "challenge_issued", "ok", detail=body.purpose, ip=_client_ip(request), ua=_ua(request))
    return {
        "challenge_id": ch["id"],
        "nonce": ch["nonce"],
        "expires_at": ch["expires_at"],
        "ttl_seconds": sb.CHALLENGE_TTL_SECONDS,
    }


# ── Device SIM check ─────────────────────────────────────────────────────
class VerifyBody(BaseModel):
    challenge_id: str = Field(..., max_length=64)
    nonce: str = Field(..., max_length=128)
    sim_state: str = Field(..., max_length=32)
    slot_count: int = Field(default=0, ge=0, le=8)
    has_esim: bool = False
    # Carrier identity is sent as MCC/MNC only (public network codes, not
    # subscriber identifiers) and is immediately fingerprinted server-side.
    mcc: str = Field(default="", max_length=8)
    mnc: str = Field(default="", max_length=8)
    platform: str = Field(default="", max_length=16)
    os_version: str = Field(default="", max_length=32)
    app_version: str = Field(default="", max_length=32)
    is_device: bool = True
    # Optional hardware attestation. Once Play Integrity is configured (see
    # core/play_integrity.py) it becomes MANDATORY here, which is what stops a
    # modified client from simply asserting "SIM present".
    play_integrity_token: Optional[str] = Field(default=None, max_length=8192)


@router.post("/sim-binding/verify")
@limiter.limit("20/minute")
async def sim_verify(
    request: Request,
    body: VerifyBody,
    user: Dict[str, Any] = Depends(get_current_user),
):
    ip, ua = _client_ip(request), _ua(request)

    if body.sim_state not in sb.DEVICE_STATES:
        await sb.audit(user["id"], "device_check", "rejected", detail="unknown_state", ip=ip, ua=ua)
        raise HTTPException(status_code=400, detail="Unknown SIM state.")

    ch = await sb.consume_challenge(body.challenge_id, body.nonce, user["id"])
    if not ch["ok"]:
        await sb.audit(user["id"], "device_check", "rejected", detail=ch["reason"], ip=ip, ua=ua)
        raise HTTPException(status_code=400, detail="This verification attempt is no longer valid. Please try again.")

    # A browser can never produce a genuine SIM reading.
    if (body.platform or "").lower() == "web":
        await sb.audit(user["id"], "device_check", "rejected", detail="web_platform", ip=ip, ua=ua)
        raise HTTPException(
            status_code=400,
            detail="A browser can't check a SIM. Link your verified phone instead.",
        )

    # Hardware attestation, when it is available. Until the Play Integrity
    # service account is configured this is recorded but cannot be checked —
    # the honest position, rather than pretending the reading is attested.
    attested = "unavailable"
    try:
        from core.play_integrity import is_enabled as _pi_enabled, verify_integrity_token, evaluate_verdicts

        if _pi_enabled():
            if not body.play_integrity_token:
                await sb.audit(user["id"], "device_check", "rejected", detail="attestation_missing", ip=ip, ua=ua)
                raise HTTPException(status_code=400, detail="This device could not be verified. Please try again.")
            decoded = await verify_integrity_token(body.play_integrity_token)
            verdicts = evaluate_verdicts(decoded or {})
            if not verdicts.get("passed"):
                await sb.audit(user["id"], "device_check", "rejected", detail="attestation_failed", ip=ip, ua=ua)
                raise HTTPException(status_code=403, detail="This device could not be verified.")
            attested = "play_integrity"
    except HTTPException:
        raise
    except Exception as e:  # never let attestation plumbing break the check
        logger.warning(f"sim verify: attestation check skipped ({type(e).__name__})")

    fp = sb.carrier_fingerprint(body.mcc, body.mnc, body.slot_count, body.has_esim)
    res = await sb.record_device_check(
        user["id"],
        sim_state=body.sim_state,
        slot_count=body.slot_count,
        has_esim=body.has_esim,
        carrier_fp=fp,
        platform=body.platform,
        os_version=body.os_version,
        app_version=body.app_version,
        is_device=body.is_device,
    )
    await sb.audit(
        user["id"],
        "device_check",
        "ok",
        detail=(
            f"{body.sim_state} slots={body.slot_count} esim={int(body.has_esim)} "
            f"changed={int(res['sim_changed'])} attested={attested}"
        ),
        ip=ip,
        ua=ua,
    )
    status = await sb.status_for(user["id"])
    status["sim_changed"] = res["sim_changed"]
    return status


# ── Number ownership proof (external verifier only) ──────────────────────
class NumberProofBody(BaseModel):
    challenge_id: str = Field(..., max_length=64)
    nonce: str = Field(..., max_length=128)
    provider: str = Field(default="truecaller", max_length=24)
    code: str = Field(..., max_length=2048)
    code_verifier: str = Field(..., max_length=256)


@router.post("/sim-binding/number-proof")
@limiter.limit("10/minute")
async def sim_number_proof(
    request: Request,
    body: NumberProofBody,
    user: Dict[str, Any] = Depends(get_current_user),
):
    ip, ua = _client_ip(request), _ua(request)

    if body.provider != "truecaller" or not truecaller.is_enabled():
        await sb.audit(user["id"], "number_proof", "rejected", detail="provider_not_configured", ip=ip, ua=ua)
        raise HTTPException(status_code=503, detail="Number verification isn't switched on yet.")

    ch = await sb.consume_challenge(body.challenge_id, body.nonce, user["id"])
    if not ch["ok"]:
        await sb.audit(user["id"], "number_proof", "rejected", detail=ch["reason"], ip=ip, ua=ua)
        raise HTTPException(status_code=400, detail="This verification attempt is no longer valid. Please try again.")

    result = await truecaller.verify_authorization_code(body.code, body.code_verifier)
    if not result["ok"]:
        await sb.audit(user["id"], "number_proof", "rejected", detail=result["reason"], ip=ip, ua=ua)
        raise HTTPException(status_code=401, detail="We couldn't confirm that number. Please try again.")

    # The number must match the one on the Slangcart account; otherwise a user
    # could "verify" with any Truecaller account they happen to be signed into.
    account_phone = "".join(ch_ for ch_ in str(user.get("phone") or "") if ch_.isdigit())
    proven_phone = "".join(ch_ for ch_ in result["phone"] if ch_.isdigit())
    if account_phone and proven_phone and account_phone[-10:] != proven_phone[-10:]:
        await sb.audit(user["id"], "number_proof", "rejected", detail="phone_mismatch", ip=ip, ua=ua)
        raise HTTPException(
            status_code=409,
            detail="That number doesn't match the mobile number on this account.",
        )

    await sb.record_number_proof(
        user["id"], method="truecaller", phone_last4=proven_phone, subject=result["subject"]
    )
    if not account_phone and proven_phone:
        await db.users.update_one({"id": user["id"]}, {"$set": {"phone": proven_phone[-10:]}})
    await sb.audit(user["id"], "number_proof", "ok", detail="truecaller", ip=ip, ua=ua)
    return await sb.status_for(user["id"])


# ── Status / revalidate ──────────────────────────────────────────────────
@router.get("/sim-binding/status")
async def sim_status(user: Dict[str, Any] = Depends(get_current_user)):
    return await sb.status_for(user["id"])


class RevalidateBody(BaseModel):
    reason: str = Field(default="user_requested", max_length=120)


@router.post("/sim-binding/revalidate")
@limiter.limit("10/minute")
async def sim_revalidate(
    request: Request,
    body: RevalidateBody,
    user: Dict[str, Any] = Depends(get_current_user),
):
    await sb.require_revalidation(user["id"], body.reason)
    await sb.audit(user["id"], "revalidate", "ok", detail=body.reason, ip=_client_ip(request), ua=_ua(request))
    return await sb.status_for(user["id"])


# ── Web device linking (QR) ──────────────────────────────────────────────
# A browser cannot read a SIM, so it borrows a phone's level: the VERIFIED
# PHONE mints a short-lived code, the browser redeems it. The code is single
# use, expires in 3 minutes, and the link itself expires in 24 hours.
@router.post("/sim-binding/device-link/start")
@limiter.limit("10/minute")
async def device_link_start(
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Called by the BROWSER. Mints a pending code to render as a QR."""
    now = datetime.now(timezone.utc)
    code = secrets.token_urlsafe(18)
    doc = {
        "id": secrets.token_hex(8),
        "code": code,
        "user_id": user["id"],
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=sb.DEVICE_LINK_TTL_SECONDS)).isoformat(),
        "claimed_at": None,
        "status": "pending",
    }
    await db.device_links.insert_one(dict(doc))
    await sb.audit(user["id"], "device_link_started", "ok", ip=_client_ip(request), ua=_ua(request))
    return {
        "code": code,
        "expires_at": doc["expires_at"],
        "ttl_seconds": sb.DEVICE_LINK_TTL_SECONDS,
    }


@router.get("/sim-binding/device-link/{code}")
async def device_link_status(code: str, user: Dict[str, Any] = Depends(get_current_user)):
    """Browser polls its OWN code. Account status is not an answer here: the
    question is "has my phone approved THIS code?"."""
    link = await db.device_links.find_one({"code": code, "user_id": user["id"]}, {"_id": 0})
    if not link:
        raise HTTPException(status_code=404, detail="That link code isn't valid.")
    expired = datetime.now(timezone.utc) > datetime.fromisoformat(link["expires_at"])
    return {
        "claimed": bool(link.get("claimed_at")),
        "expired": expired and not link.get("claimed_at"),
        "expires_at": link["expires_at"],
    }


class LinkClaimBody(BaseModel):
    code: str = Field(..., max_length=64)


@router.post("/sim-binding/device-link/claim")
@limiter.limit("20/minute")
async def device_link_claim(
    request: Request,
    body: LinkClaimBody,
    user: Dict[str, Any] = Depends(get_current_user),
):
    ip, ua = _client_ip(request), _ua(request)
    # Called by the VERIFIED PHONE after scanning the browser's QR.
    #
    # A browser must never approve its OWN code: it would mint a code and
    # claim it in the same session, and the phone would never be involved.
    # The whole point of linking is that a device which CAN read a SIM
    # vouches for one that cannot.
    if sb.is_browser_caller(request.headers.get("x-client-platform") or "", ua):
        await sb.audit(user["id"], "device_link_claim", "rejected", detail="browser_self_claim", ip=ip, ua=ua)
        raise HTTPException(
            status_code=403,
            detail="Approve this code from the Slangcart app on your verified phone.",
        )
    phone_status = await sb.status_for(user["id"])
    if not phone_status["meets_requirement"] or phone_status["level"] == sb.LEVEL_LINKED:
        await sb.audit(user["id"], "device_link_claim", "rejected", detail="phone_not_verified", ip=ip, ua=ua)
        raise HTTPException(
            status_code=403,
            detail="Verify this phone's SIM first, then scan the code on your computer.",
        )
    link = await db.device_links.find_one({"code": body.code}, {"_id": 0})
    if not link:
        await sb.audit(user["id"], "device_link_claim", "rejected", detail="not_found", ip=ip, ua=ua)
        raise HTTPException(status_code=400, detail="That link code isn't valid.")
    if link.get("claimed_at"):
        await sb.audit(user["id"], "device_link_claim", "rejected", detail="replayed", ip=ip, ua=ua)
        raise HTTPException(status_code=400, detail="That link code was already used.")
    if datetime.now(timezone.utc) > datetime.fromisoformat(link["expires_at"]):
        await sb.audit(user["id"], "device_link_claim", "rejected", detail="expired", ip=ip, ua=ua)
        raise HTTPException(status_code=400, detail="That link code has expired. Generate a new one.")
    if link["user_id"] != user["id"]:
        # Linking is same-account only: a code must never hand one person's
        # verification to another account.
        await sb.audit(user["id"], "device_link_claim", "rejected", detail="account_mismatch", ip=ip, ua=ua)
        raise HTTPException(status_code=403, detail="That code belongs to a different account.")

    claimed = await db.device_links.update_one(
        {"code": body.code, "claimed_at": None},
        {"$set": {"claimed_at": datetime.now(timezone.utc).isoformat(), "status": "claimed", "claim_ua": ua}},
    )
    if claimed.modified_count != 1:
        raise HTTPException(status_code=400, detail="That link code was already used.")

    now = datetime.now(timezone.utc)
    await db.sim_bindings.update_one(
        {"user_id": user["id"]},
        {
            "$set": {
                "web_link_expires_at": (now + timedelta(hours=sb.DEVICE_LINK_SESSION_HOURS)).isoformat(),
                "web_link_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }
        },
        upsert=True,
    )
    await sb.audit(user["id"], "device_link_claim", "ok", ip=ip, ua=ua)
    return {
        "linked": True,
        "expires_at": (now + timedelta(hours=sb.DEVICE_LINK_SESSION_HOURS)).isoformat(),
        "hours": sb.DEVICE_LINK_SESSION_HOURS,
    }


# ── Admin ────────────────────────────────────────────────────────────────
@router.get("/admin/sim-binding/overview")
async def admin_overview(admin: Dict[str, Any] = Depends(require_admin)):
    policy = await sb.effective_policy()
    by_state: List[Dict[str, Any]] = await db.sim_bindings.aggregate(
        [{"$group": {"_id": "$sim_state", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}]
    ).to_list(20)
    total_users = await db.users.count_documents({})
    verified_numbers = await db.sim_bindings.count_documents({"number_verified": True})
    revalidate = await db.sim_bindings.count_documents({"revalidate_required": True})
    recent = await db.sim_audit.find({}, {"_id": 0}).sort("created_at", -1).to_list(40)
    rejected = await db.sim_audit.count_documents({"result": "rejected"})
    return {
        "policy": policy,
        "totals": {
            "users": total_users,
            "bindings": await db.sim_bindings.count_documents({}),
            "number_verified": verified_numbers,
            "needs_revalidation": revalidate,
            "rejected_attempts": rejected,
            "by_sim_state": {str(r["_id"]): r["n"] for r in by_state},
        },
        "recent_events": recent,
        "notes": [
            "A local SIM check proves only that a SIM is present in the handset.",
            "Number ownership is proven by Truecaller's servers, never by the app.",
            "Shopping, checkout, payments, wallet, recharge and vendor tools are never gated.",
        ],
    }


class PolicyBody(BaseModel):
    enforce_chat: Optional[bool] = None
    required_level: Optional[str] = Field(default=None, max_length=24)
    allow_web_without_link: Optional[bool] = None


@router.patch("/admin/sim-binding/policy")
async def admin_set_policy(body: PolicyBody, admin: Dict[str, Any] = Depends(require_admin)):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if "required_level" in patch and patch["required_level"] not in (
        sb.LEVEL_NONE,
        sb.LEVEL_SIM,
        sb.LEVEL_NUMBER,
    ):
        raise HTTPException(status_code=400, detail="Unknown verification level.")
    return await sb.set_policy(patch, admin["id"])


@router.post("/admin/sim-binding/revalidate/{user_id}")
async def admin_force_revalidate(user_id: str, admin: Dict[str, Any] = Depends(require_admin)):
    await sb.require_revalidation(user_id, f"admin:{admin['id']}")
    await sb.audit(user_id, "revalidate", "ok", detail=f"forced_by_admin:{admin['id']}")
    return {"ok": True, "user_id": user_id}
