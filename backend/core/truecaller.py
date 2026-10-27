"""Truecaller OAuth server-side verification (the security boundary).

The phone only ever receives a short-lived authorization code. It cannot be
trusted to say "verified" or to report its own number: both are decided here,
by exchanging the code with Truecaller and reading the number back from
Truecaller's own `userinfo` endpoint.

Dormant until TRUECALLER_CLIENT_ID is configured. `is_enabled()` is False then
and every caller falls back to "number proof unavailable" — never to "verified".

Nothing from this module is ever logged: not the code, not the verifier, not
the access token.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict

import httpx

logger = logging.getLogger(__name__)

TOKEN_URL = "https://oauth-account-noneu.truecaller.com/v1/token"
USERINFO_URL = "https://oauth-account-noneu.truecaller.com/v1/userinfo"


def client_id() -> str:
    return (os.environ.get("TRUECALLER_CLIENT_ID") or "").strip()


def is_enabled() -> bool:
    return bool(client_id())


async def verify_authorization_code(code: str, code_verifier: str) -> Dict[str, Any]:
    """Exchange the one-time code and fetch the verified profile.

    Returns {ok, phone, subject, reason}. `ok` is True only when Truecaller
    itself reports `phone_number_verified: true`.
    """
    if not is_enabled():
        return {"ok": False, "reason": "provider_not_configured"}

    try:
        async with httpx.AsyncClient(timeout=10) as c:
            token_resp = await c.post(
                TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "client_id": client_id(),
                    "code": code,
                    "code_verifier": code_verifier,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if token_resp.status_code != 200:
                return {"ok": False, "reason": f"token_rejected_{token_resp.status_code}"}
            tok = token_resp.json()
            access = tok.get("access_token")
            if not access or str(tok.get("token_type", "")).lower() != "bearer":
                return {"ok": False, "reason": "bad_token_response"}

            profile_resp = await c.get(USERINFO_URL, headers={"Authorization": f"Bearer {access}"})
        if profile_resp.status_code != 200:
            return {"ok": False, "reason": f"userinfo_rejected_{profile_resp.status_code}"}
        p = profile_resp.json()
        if p.get("phone_number_verified") is not True or not p.get("phone_number"):
            return {"ok": False, "reason": "no_verified_phone"}
        return {
            "ok": True,
            "phone": str(p["phone_number"]),
            "subject": str(p.get("sub") or ""),
            "reason": "",
        }
    except httpx.HTTPError as e:
        # Deliberately coarse: the exception text can carry request details.
        logger.warning(f"truecaller: transport error ({type(e).__name__})")
        return {"ok": False, "reason": "provider_unreachable"}
