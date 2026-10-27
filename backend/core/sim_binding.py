"""SIM-binding readiness — server-owned verification state (Oct 2026).

WHAT THIS IS, PRECISELY
-----------------------
Two *different* facts are tracked here and are never conflated:

  1. `sim_state`      — what the Android device reported about SIM presence
                        (SubscriptionManager / TelephonyManager). This is a
                        LOCAL, FREE signal. It proves a SIM/eSIM subscription
                        exists in the handset. It proves NOTHING about whose
                        number it is.
  2. `number_verified` — proof that the user's registered mobile number is
                        actually theirs. This can ONLY come from an external
                        verifier (Truecaller OAuth today; an SMS/missed-call
                        provider if the owner adds one). The device can never
                        assert it.

`level` is the single server-computed answer the rest of the app consumes:

    none            → nothing established
    sim_presence    → a SIM/eSIM is present on a real, attested-enough device
    number_verified → sim_presence AND external proof of number ownership
    linked_device   → a browser session inheriting a phone's level via QR

The enforcement gate compares `level` against the policy's `required_level`,
and the policy can never demand `number_verified` while no number-proof
provider is configured — otherwise switching enforcement on would lock every
user out of chat. That clamp lives in `effective_policy()`.

PRIVACY / DoT POSTURE
---------------------
Deliberately NOT collected or stored: IMEI, IMSI, ICCID, SIM serial,
subscription id, MSISDN read off the SIM, phone number from the client.
What is stored is a keyed fingerprint `carrier_fp` = HMAC-SHA256(server
secret, "mcc|mnc|slots|esim") — enough to notice "the SIM situation changed,
re-check", useless as an identifier, and not reversible to a subscriber.
See /app/memory/SIM_BINDING.md for the compliance checklist.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from core.config import JWT_SECRET
from core.db import db

logger = logging.getLogger(__name__)

# ── Device-reported SIM states (mirrors modules/sim-binding Kotlin enum) ──
SIM_PRESENT = "SIM_PRESENT"
SIM_ABSENT = "SIM_ABSENT"
SIM_STATE_UNKNOWN = "SIM_STATE_UNKNOWN"
PERMISSION_DENIED = "PERMISSION_DENIED"
DEVICE_UNSUPPORTED = "DEVICE_UNSUPPORTED"
REVALIDATION_REQUIRED = "REVALIDATION_REQUIRED"

DEVICE_STATES = {
    SIM_PRESENT,
    SIM_ABSENT,
    SIM_STATE_UNKNOWN,
    PERMISSION_DENIED,
    DEVICE_UNSUPPORTED,
    REVALIDATION_REQUIRED,
}

# ── Server-computed levels ───────────────────────────────────────────────
LEVEL_NONE = "none"
LEVEL_SIM = "sim_presence"
LEVEL_NUMBER = "number_verified"
LEVEL_LINKED = "linked_device"

LEVEL_RANK = {LEVEL_NONE: 0, LEVEL_SIM: 1, LEVEL_LINKED: 1, LEVEL_NUMBER: 2}

CHALLENGE_TTL_SECONDS = 120
# A pass is not forever: SIMs get swapped, phones get resold. After this the
# client must run the check again (cheap — it is a local read, no SMS).
BINDING_TTL_HOURS = 72
DEVICE_LINK_TTL_SECONDS = 180
DEVICE_LINK_SESSION_HOURS = 24

POLICY_DOC_ID = "sim_binding_policy"
DEFAULT_POLICY: Dict[str, Any] = {
    # Owner decision (Oct 2026): "Enforce straight away", "All customer-vendor
    # and support chats". Shopping, checkout, payments, wallet, recharge and
    # vendor operations are deliberately NOT gated.
    "enforce_chat": True,
    "required_level": LEVEL_SIM,
    # Web/desktop sessions cannot read a SIM. They either link a verified
    # phone by QR or stay unverified; `allow_web_without_link` is the escape
    # hatch the owner can flip if browser users start complaining.
    "allow_web_without_link": False,
    "updated_at": None,
    "updated_by": None,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def carrier_fingerprint(mcc: str, mnc: str, slots: int, has_esim: bool) -> str:
    """Keyed, non-reversible fingerprint of the SIM *situation* (never an id).

    HMAC (not a bare hash) so the tiny input space — a few hundred Indian
    MCC/MNC pairs — cannot be brute-forced back out of a stolen database dump.
    """
    msg = f"{(mcc or '').strip()}|{(mnc or '').strip()}|{int(slots)}|{int(bool(has_esim))}"
    return hmac.new(JWT_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()[:32]


def number_proof_available() -> bool:
    """Is any external number-ownership verifier wired up right now?"""
    import os

    return bool((os.environ.get("TRUECALLER_CLIENT_ID") or "").strip())


# ── Policy ───────────────────────────────────────────────────────────────
async def get_policy() -> Dict[str, Any]:
    doc = await db.app_settings.find_one({"_id": POLICY_DOC_ID}) or {}
    policy = {**DEFAULT_POLICY}
    for k in DEFAULT_POLICY:
        if k in doc:
            policy[k] = doc[k]
    return policy


async def effective_policy() -> Dict[str, Any]:
    """Policy with the safety clamps applied.

    Clamp: `required_level` can never exceed what the platform can actually
    deliver. Demanding `number_verified` with no verifier configured would be
    a 100% lockout, so it degrades to `sim_presence` and says so.
    """
    policy = await get_policy()
    clamped = False
    if policy["required_level"] == LEVEL_NUMBER and not number_proof_available():
        policy["required_level"] = LEVEL_SIM
        clamped = True
    policy["clamped_to_sim_presence"] = clamped
    policy["number_proof_available"] = number_proof_available()
    return policy


async def set_policy(patch: Dict[str, Any], admin_id: str) -> Dict[str, Any]:
    allowed = {k: v for k, v in patch.items() if k in DEFAULT_POLICY and k not in ("updated_at", "updated_by")}
    allowed["updated_at"] = _now().isoformat()
    allowed["updated_by"] = admin_id
    await db.app_settings.update_one({"_id": POLICY_DOC_ID}, {"$set": allowed}, upsert=True)
    await audit(admin_id, "policy_updated", "ok", detail=str(sorted(allowed.keys())))
    return await effective_policy()


# ── Audit ────────────────────────────────────────────────────────────────
async def audit(
    user_id: Optional[str],
    event: str,
    result: str,
    detail: str = "",
    ip: str = "",
    ua: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Security-relevant event log.

    NEVER pass a challenge nonce, an OAuth code, an access token, a password
    or a phone number into `detail` — the whole point of this log is that it
    stays safe to read.
    """
    try:
        row = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "event": event,
            "result": result,
            "detail": detail[:300],
            "ip": (ip or "")[:64],
            "ua": (ua or "")[:160],
            "created_at": _now().isoformat(),
        }
        if extra:
            row.update({k: v for k, v in extra.items() if k not in ("nonce", "code", "token", "phone")})
        await db.sim_audit.insert_one(row)
    except Exception as e:  # audit must never break a request
        logger.warning(f"sim audit failed: {e}")


# ── Challenges ───────────────────────────────────────────────────────────
async def create_challenge(user_id: str, purpose: str, device_fp: str = "") -> Dict[str, Any]:
    now = _now()
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "purpose": purpose,
        "nonce": secrets.token_urlsafe(32),
        "device_fp": (device_fp or "")[:64],
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=CHALLENGE_TTL_SECONDS)).isoformat(),
        "used_at": None,
    }
    await db.sim_challenges.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


async def consume_challenge(challenge_id: str, nonce: str, user_id: str) -> Dict[str, Any]:
    """Single-use + expiry + owner check. Returns {ok, reason}."""
    ch = await db.sim_challenges.find_one({"id": challenge_id}, {"_id": 0})
    if not ch:
        return {"ok": False, "reason": "challenge_not_found"}
    if ch["user_id"] != user_id:
        return {"ok": False, "reason": "challenge_owner_mismatch"}
    if ch.get("used_at"):
        return {"ok": False, "reason": "challenge_replayed"}
    if not hmac.compare_digest(str(ch.get("nonce") or ""), str(nonce or "")):
        return {"ok": False, "reason": "nonce_mismatch"}
    if _now() > datetime.fromisoformat(ch["expires_at"]):
        return {"ok": False, "reason": "challenge_expired"}
    res = await db.sim_challenges.update_one(
        {"id": challenge_id, "used_at": None}, {"$set": {"used_at": _now().isoformat()}}
    )
    if res.modified_count != 1:
        # Lost the race against a concurrent replay.
        return {"ok": False, "reason": "challenge_replayed"}
    return {"ok": True, "reason": "", "challenge": ch}


# ── Binding state ────────────────────────────────────────────────────────
def compute_level(binding: Optional[Dict[str, Any]]) -> str:
    if not binding:
        return LEVEL_NONE
    if binding.get("linked_from_user_id"):
        return LEVEL_LINKED
    if binding.get("sim_state") != SIM_PRESENT:
        return LEVEL_NONE
    if binding.get("revalidate_required"):
        return LEVEL_NONE
    checked = binding.get("last_check_at")
    if checked:
        try:
            if _now() - datetime.fromisoformat(checked) > timedelta(hours=BINDING_TTL_HOURS):
                return LEVEL_NONE
        except ValueError:
            return LEVEL_NONE
    if binding.get("number_verified"):
        return LEVEL_NUMBER
    return LEVEL_SIM


async def get_binding(user_id: str) -> Optional[Dict[str, Any]]:
    return await db.sim_bindings.find_one({"user_id": user_id}, {"_id": 0})


async def status_for(user_id: str) -> Dict[str, Any]:
    binding = await get_binding(user_id)
    policy = await effective_policy()
    level = compute_level(binding)
    ok = LEVEL_RANK.get(level, 0) >= LEVEL_RANK.get(policy["required_level"], 1)
    return {
        "level": level,
        "meets_requirement": ok,
        "required_level": policy["required_level"],
        "enforce_chat": bool(policy["enforce_chat"]),
        "number_proof_available": policy["number_proof_available"],
        "sim_state": (binding or {}).get("sim_state") or SIM_STATE_UNKNOWN,
        "slot_count": (binding or {}).get("slot_count", 0),
        "has_esim": bool((binding or {}).get("has_esim")),
        "number_verified": bool((binding or {}).get("number_verified")),
        "number_proof_method": (binding or {}).get("number_proof_method"),
        "phone_last4": (binding or {}).get("phone_last4"),
        "revalidate_required": bool((binding or {}).get("revalidate_required")),
        "last_check_at": (binding or {}).get("last_check_at"),
        "verified_at": (binding or {}).get("verified_at"),
        "linked_from_device": bool((binding or {}).get("linked_from_user_id")),
        "binding_ttl_hours": BINDING_TTL_HOURS,
        # Said out loud so no screen can imply more than was proven.
        "disclaimer": (
            "A local SIM check only shows that a SIM is present in the phone. "
            "It is not proof that the number belongs to this account."
        ),
    }


async def record_device_check(
    user_id: str,
    *,
    sim_state: str,
    slot_count: int,
    has_esim: bool,
    carrier_fp: str,
    platform: str,
    os_version: str,
    app_version: str,
    is_device: bool,
) -> Dict[str, Any]:
    """Persist a device-reported SIM check. Never touches `number_verified`."""
    prev = await get_binding(user_id)
    now_iso = _now().isoformat()
    # Only compare fingerprints between two PRESENT readings. Otherwise
    # pulling a SIM out and putting the SAME one back would look like a swap,
    # because an absent reading has no carrier codes to fingerprint.
    changed = bool(
        prev
        and prev.get("sim_state") == SIM_PRESENT
        and sim_state == SIM_PRESENT
        and prev.get("carrier_fp")
        and carrier_fp
        and prev["carrier_fp"] != carrier_fp
    )

    update: Dict[str, Any] = {
        "user_id": user_id,
        "sim_state": sim_state,
        "slot_count": int(slot_count),
        "has_esim": bool(has_esim),
        "carrier_fp": carrier_fp,
        "platform": platform[:16],
        "os_version": os_version[:32],
        "app_version": app_version[:32],
        "is_device": bool(is_device),
        "last_check_at": now_iso,
        "updated_at": now_iso,
        "revalidate_required": False,
    }
    if not prev:
        update["created_at"] = now_iso

    if changed:
        # The SIM situation moved (swap, removal, new eSIM). Any number proof
        # we held was for the old situation — drop it and ask again.
        update["revalidate_required"] = True
        update["number_verified"] = False
        update["number_proof_method"] = None
        update["phone_last4"] = None
        update["sim_changed_at"] = now_iso
    if sim_state != SIM_PRESENT:
        update["number_verified"] = False

    unset: Dict[str, str] = {}
    if changed or sim_state != SIM_PRESENT:
        # A linked browser inherits this phone's standing — the moment the
        # phone stops passing, the browser must stop passing too.
        unset["web_link_expires_at"] = ""
    ops: Dict[str, Any] = {"$set": update}
    if unset:
        ops["$unset"] = unset
    await db.sim_bindings.update_one({"user_id": user_id}, ops, upsert=True)
    return {"sim_changed": changed}


async def record_number_proof(
    user_id: str, *, method: str, phone_last4: str, subject: str = ""
) -> None:
    """Mark number ownership as proven by an EXTERNAL verifier only."""
    now_iso = _now().isoformat()
    await db.sim_bindings.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "user_id": user_id,
                "number_verified": True,
                "number_proof_method": method,
                "phone_last4": (phone_last4 or "")[-4:],
                "number_proof_subject": subject[:80],
                "verified_at": now_iso,
                "updated_at": now_iso,
                "revalidate_required": False,
            }
        },
        upsert=True,
    )


async def require_revalidation(user_id: str, reason: str) -> None:
    await db.sim_bindings.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "revalidate_required": True,
                "revalidate_reason": reason[:120],
                "updated_at": _now().isoformat(),
            },
            # Any linked browser loses access at the same moment.
            "$unset": {"web_link_expires_at": ""},
        },
        upsert=True,
    )


async def ensure_indexes() -> None:
    try:
        await db.sim_bindings.create_index("user_id", unique=True, name="uniq_sim_binding_user")
        await db.sim_challenges.create_index("id", unique=True, name="uniq_sim_challenge_id")
        await db.sim_challenges.create_index("user_id", name="sim_challenge_user")
        await db.sim_audit.create_index([("user_id", 1), ("created_at", -1)], name="sim_audit_user_time")
        await db.device_links.create_index("code", unique=True, name="uniq_device_link_code")
    except Exception as e:
        logger.warning(f"sim_binding index setup: {e}")


# ── Chat gate (server-side enforcement) ──────────────────────────────────
# Enforced here, in the API, NOT in the Android UI: a modified client or a
# stale session gets the same 403 as everyone else.
#
# Scope (owner's choice, Oct 2026): all customer–vendor and support chats.
# Deliberately NOT gated anywhere: browsing, cart, checkout, payments,
# wallet, cashback, recharge, orders, vendor operations, admin tools.
# Reading existing conversations also stays open — enforcement applies to
# starting a chat and sending a message, so no history is ever lost.
CHAT_BLOCK_CODE = "sim_verification_required"


def is_browser_caller(platform_header: str, user_agent: str) -> bool:
    """Is this request coming from a browser rather than the installed app?

    `X-Client-Platform` is set by the app's HTTP client; the User-Agent is the
    fallback for anything that doesn't send it. This decides whether the
    caller needs a LINKED phone, and is a product rule rather than a security
    boundary — the security boundary is the account's own phone having
    reported a SIM.
    """
    p = (platform_header or "").strip().lower()
    if p in ("android", "ios"):
        return False
    if p == "web":
        return True
    ua = (user_agent or "").lower()
    if not ua:
        return False
    if "okhttp" in ua or "expo" in ua or "cfnetwork" in ua or "dart" in ua:
        return False
    return "mozilla" in ua or "chrome" in ua or "safari" in ua or "firefox" in ua


async def chat_gate(
    user: Dict[str, Any],
    *,
    platform_header: str = "",
    user_agent: str = "",
) -> Dict[str, Any]:
    """Return {allowed, code, message, status} for a chat write action."""
    policy = await effective_policy()
    if not policy["enforce_chat"]:
        return {"allowed": True}
    # Support staff must always be able to answer, or a verification problem
    # becomes unreportable.
    if user.get("role") == "admin":
        return {"allowed": True}

    status = await status_for(user["id"])
    binding = await get_binding(user["id"]) or {}
    browser = is_browser_caller(platform_header, user_agent)

    if browser:
        # A browser has no SIM of its own. It needs BOTH a phone that
        # currently passes AND a live link made from that phone.
        if policy["allow_web_without_link"]:
            return {"allowed": True}
        link_ok = False
        web_expiry = binding.get("web_link_expires_at")
        if web_expiry:
            try:
                link_ok = _now() <= datetime.fromisoformat(web_expiry)
            except ValueError:
                link_ok = False
        if link_ok and status["meets_requirement"]:
            return {"allowed": True}
        return {
            "allowed": False,
            "code": CHAT_BLOCK_CODE,
            "message": (
                "Link your verified phone to chat from a browser."
                if status["meets_requirement"]
                else "Verify your phone's SIM, then link this browser to chat here."
            ),
            "status": status,
        }

    if status["meets_requirement"]:
        return {"allowed": True}

    sim_state = status["sim_state"]
    if sim_state == PERMISSION_DENIED:
        msg = "Allow Slangcart to check your SIM status, then chat will open up."
    elif sim_state == SIM_ABSENT:
        msg = "No SIM found in this phone. Insert your SIM and check again to use chat."
    elif sim_state == DEVICE_UNSUPPORTED:
        msg = "This device can't report its SIM status. Link a verified phone to use chat."
    elif status["revalidate_required"]:
        msg = "Your SIM changed, so chat needs a quick re-check."
    else:
        msg = "Verify your SIM to start chatting. Shopping and payments are unaffected."
    return {"allowed": False, "code": CHAT_BLOCK_CODE, "message": msg, "status": status}

