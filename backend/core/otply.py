"""OTPly WhatsApp OTP — provider client + OTP lifecycle.

Nov-2026. Mobile-number sign-in replaces the Truecaller flow. The customer
receives a six-digit code on WhatsApp through OTPly (api.adeptcode.in) and the
BACKEND alone decides whether a code is valid — the app can never declare a
number verified.

Security rules enforced here
---------------------------
* Codes are stored only as a salted SHA-256 hash, never in plain text.
* Five-minute expiry, single use, max 5 wrong attempts, 60 s resend cooldown.
* Per-mobile and per-IP rate limits (counts the sends, not the attempts).
* The provider URL carries the api_key AND the OTP as query parameters, so it
  is never logged: only the host and the provider's status code are.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
from datetime import timedelta
from typing import Any, Dict, Optional, Tuple

import httpx

from core.db import db
from core.utils import now_utc

logger = logging.getLogger(__name__)
# httpx logs every request URL at INFO — that URL carries api_key + OTP.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

OTPLY_ENDPOINT = "https://api.adeptcode.in/api.php"

OTP_TTL_SECONDS = 300          # 5 minutes
RESEND_COOLDOWN_SECONDS = 60
MAX_VERIFY_ATTEMPTS = 5
MAX_SENDS_PER_MOBILE_HOUR = 5
MAX_SENDS_PER_IP_HOUR = 20
REQUEST_TIMEOUT_SECONDS = 15.0


class OtpError(Exception):
    """Raised with a user-safe message + a machine code."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def normalise_mobile(raw: str) -> str:
    """Return a bare 10-digit Indian mobile number or raise."""
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    if digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    if len(digits) != 10 or digits[0] not in "6789":
        raise OtpError("invalid_mobile", "Enter a valid 10-digit Indian mobile number.")
    return digits


def _hash_otp(mobile: str, otp: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{mobile}:{otp}".encode()).hexdigest()


def _api_key() -> str:
    key = (os.environ.get("OTPLY_API_KEY") or "").strip()
    if not key:
        raise OtpError(
            "provider_unconfigured",
            "WhatsApp sign-in isn't set up yet. Please use Google or email sign-in.",
            status=503,
        )
    return key


async def _deliver(mobile: str, otp: str) -> None:
    """Hand the code to OTPly. Raises OtpError with a user-safe message."""
    params = {"api_key": _api_key(), "mobile": mobile, "otp": otp}
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            resp = await client.get(OTPLY_ENDPOINT, params=params)
    except httpx.TimeoutException:
        logger.warning("otply: timeout talking to api.adeptcode.in")
        raise OtpError("provider_timeout", "WhatsApp is slow right now. Please try again.", status=504)
    except Exception:
        # Never echo the exception text: it can contain the full request URL.
        logger.warning("otply: transport error talking to api.adeptcode.in")
        raise OtpError("provider_unreachable", "Couldn't reach WhatsApp. Please try again.", status=502)

    body: Dict[str, Any] = {}
    try:
        body = resp.json() or {}
    except Exception:
        body = {}
    code = str(body.get("code") or "").upper()
    status = str(body.get("status") or "").lower()
    # Log the verdict only — no key, no OTP, no number.
    logger.info("otply: http=%s status=%s code=%s", resp.status_code, status or "-", code or "-")

    if resp.status_code == 200 and (status == "success" or code == "OTP_SENT"):
        return
    if code == "INSUFFICIENT_CREDITS":
        raise OtpError(
            "provider_no_credits",
            "WhatsApp codes are temporarily unavailable. Please sign in with Google or email.",
            status=503,
        )
    if resp.status_code in (401, 403) or code in {"INVALID_API_KEY", "UNAUTHORIZED"}:
        raise OtpError(
            "provider_rejected",
            "WhatsApp sign-in isn't available right now. Please use Google or email sign-in.",
            status=503,
        )
    raise OtpError("provider_failed", "Couldn't send the code. Please try again.", status=502)


async def _rate_limit(mobile: str, ip: str) -> None:
    hour_ago = (now_utc() - timedelta(hours=1)).isoformat()
    by_mobile = await db.otp_requests.count_documents(
        {"mobile": mobile, "created_at": {"$gte": hour_ago}},
    )
    if by_mobile >= MAX_SENDS_PER_MOBILE_HOUR:
        raise OtpError(
            "too_many_requests",
            "Too many codes requested for this number. Please try again in an hour.",
            status=429,
        )
    if ip:
        by_ip = await db.otp_requests.count_documents(
            {"ip": ip, "created_at": {"$gte": hour_ago}},
        )
        if by_ip >= MAX_SENDS_PER_IP_HOUR:
            raise OtpError(
                "too_many_requests",
                "Too many codes requested from this device. Please try again later.",
                status=429,
            )


async def send_otp(mobile_raw: str, ip: str = "", purpose: str = "login") -> Dict[str, Any]:
    """Generate, deliver and store a code. Returns the client-safe payload."""
    mobile = normalise_mobile(mobile_raw)
    now = now_utc()

    existing = await db.otp_codes.find_one({"mobile": mobile, "consumed": False})
    if existing:
        sent_at = existing.get("created_at") or ""
        try:
            from datetime import datetime
            age = (now - datetime.fromisoformat(sent_at)).total_seconds()
        except Exception:
            age = RESEND_COOLDOWN_SECONDS
        if age < RESEND_COOLDOWN_SECONDS:
            wait = int(RESEND_COOLDOWN_SECONDS - age)
            raise OtpError(
                "cooldown",
                f"Please wait {wait}s before asking for another code.",
                status=429,
            )

    await _rate_limit(mobile, ip)

    otp = f"{secrets.randbelow(1_000_000):06d}"
    salt = secrets.token_hex(16)
    # Deliver FIRST: a code we couldn't send must not occupy the cooldown.
    await _deliver(mobile, otp)

    await db.otp_codes.delete_many({"mobile": mobile})
    await db.otp_codes.insert_one({
        "mobile": mobile,
        "otp_hash": _hash_otp(mobile, otp, salt),
        "salt": salt,
        "purpose": purpose,
        "attempts": 0,
        "consumed": False,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=OTP_TTL_SECONDS)).isoformat(),
    })
    await db.otp_requests.insert_one({
        "mobile": mobile, "ip": ip or "", "created_at": now.isoformat(),
    })
    return {
        "sent": True,
        "mobile": mobile,
        "expires_in": OTP_TTL_SECONDS,
        "resend_in": RESEND_COOLDOWN_SECONDS,
    }


async def verify_otp(mobile_raw: str, otp_raw: str) -> str:
    """Consume the code. Returns the verified 10-digit mobile or raises."""
    mobile = normalise_mobile(mobile_raw)
    otp = "".join(ch for ch in str(otp_raw or "") if ch.isdigit())
    if len(otp) != 6:
        raise OtpError("invalid_otp", "Enter the 6-digit code from WhatsApp.")

    rec = await db.otp_codes.find_one({"mobile": mobile, "consumed": False})
    if not rec:
        raise OtpError("no_code", "Request a new code to continue.")
    if rec.get("expires_at", "") < now_utc().isoformat():
        await db.otp_codes.delete_many({"mobile": mobile})
        raise OtpError("expired", "That code has expired. Please request a new one.")
    if int(rec.get("attempts") or 0) >= MAX_VERIFY_ATTEMPTS:
        await db.otp_codes.delete_many({"mobile": mobile})
        raise OtpError("too_many_attempts", "Too many wrong codes. Please request a new one.", status=429)

    if not hmac.compare_digest(rec["otp_hash"], _hash_otp(mobile, otp, rec["salt"])):
        await db.otp_codes.update_one({"_id": rec["_id"]}, {"$inc": {"attempts": 1}})
        left = MAX_VERIFY_ATTEMPTS - int(rec.get("attempts") or 0) - 1
        raise OtpError(
            "wrong_otp",
            "That code isn't right." + (f" {left} attempt{'' if left == 1 else 's'} left." if left > 0 else ""),
        )

    # Single use: consume immediately so a replay can't log anyone in twice.
    await db.otp_codes.delete_many({"mobile": mobile})
    return mobile


async def ensure_indexes() -> None:
    await db.otp_codes.create_index("mobile", name="ix_otp_mobile")
    await db.otp_requests.create_index([("mobile", 1), ("created_at", -1)], name="ix_otpreq_mobile")
    await db.otp_requests.create_index([("ip", 1), ("created_at", -1)], name="ix_otpreq_ip")
