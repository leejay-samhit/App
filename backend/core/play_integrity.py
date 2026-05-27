"""Google Play Integrity API token verifier (server-side).

This module verifies the integrity token that an Android app obtained from
the Play Integrity API via the on-device SDK. The verification is done
against Google's servers using a service account that has been granted the
"Play Integrity API" role on the linked Google Cloud project.

Flow:
  1. App on device calls Play Integrity SDK with a nonce we generated.
  2. Google issues a signed integrity token.
  3. App POSTs the token to /api/security/integrity-report.
  4. THIS module decodes the token via the playintegrity.googleapis.com
     `decodeIntegrityToken` endpoint, returning structured verdicts.
  5. server.py compares the verdicts to expected values and decides
     block_level.

To activate:
  • Create a Google Cloud project linked to the Play Console app.
  • Enable the "Play Integrity API" in the GCP project.
  • Create a service account with role "Play Integrity API · Service Account
    User", download its JSON key.
  • Set env vars in backend/.env:
      PLAY_INTEGRITY_ENABLED=1
      PLAY_INTEGRITY_PACKAGE_NAME=com.networkpay.app
      GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
  • Restart backend.

Until activated, server.py's PLAY_INTEGRITY_ENABLED check skips this
module entirely and the FE token is recorded but not verified — that's
fine: jail-monkey / SSL pinning / app signature already catch most tampering
even without Play Integrity.
"""
from __future__ import annotations

import os
import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("play_integrity")

PACKAGE_NAME = os.environ.get("PLAY_INTEGRITY_PACKAGE_NAME", "com.networkpay.app")
GOOGLE_CREDS_PATH = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
PLAY_INTEGRITY_API_URL = (
    "https://playintegrity.googleapis.com/v1/{package}:decodeIntegrityToken"
)


def is_enabled() -> bool:
    """The endpoint enables itself only when env vars are present AND the
    google-auth dependency is importable. This keeps `pip install` lean
    until you're ready to use Play Integrity."""
    if os.environ.get("PLAY_INTEGRITY_ENABLED") != "1":
        return False
    try:
        import google.auth  # noqa: F401
        return True
    except Exception:
        logger.warning("PLAY_INTEGRITY_ENABLED=1 but google-auth not installed; falling back to disabled")
        return False


async def verify_integrity_token(token: str) -> Optional[Dict[str, Any]]:
    """Returns the decoded `tokenPayloadExternal` dict, or None on failure.

    Structure (per Google docs):
      {
        "requestDetails":     {"requestPackageName", "nonce", "timestampMillis"},
        "appIntegrity":       {"appRecognitionVerdict", "packageName", "certificateSha256Digest", "versionCode"},
        "deviceIntegrity":    {"deviceRecognitionVerdict": ["MEETS_DEVICE_INTEGRITY", ...]},
        "accountDetails":     {"appLicensingVerdict"},
        "environmentDetails": {"playProtectVerdict", "appAccessRiskVerdict"}
      }

    Caller is responsible for mapping these to block_level.
    """
    if not is_enabled():
        return None
    try:
        import httpx
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request as _GReq
    except Exception as e:
        logger.warning(f"play integrity deps missing: {e}")
        return None

    if not GOOGLE_CREDS_PATH or not os.path.exists(GOOGLE_CREDS_PATH):
        logger.warning("GOOGLE_APPLICATION_CREDENTIALS not set or file missing")
        return None

    try:
        creds = service_account.Credentials.from_service_account_file(
            GOOGLE_CREDS_PATH,
            scopes=["https://www.googleapis.com/auth/playintegrity"],
        )
        creds.refresh(_GReq())
        access_token = creds.token

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                PLAY_INTEGRITY_API_URL.format(package=PACKAGE_NAME),
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"integrity_token": token},
            )
        if resp.status_code != 200:
            logger.warning(f"play integrity verify HTTP {resp.status_code}: {resp.text[:300]}")
            return None
        body = resp.json()
        return body.get("tokenPayloadExternal")
    except Exception as e:
        logger.warning(f"play integrity verify error: {e}")
        return None


def evaluate_verdicts(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Convert the decoded Play Integrity payload into our block_level + reasons.

    Returns: {"passed": bool, "reasons": [str, ...], "raw_verdicts": {...}}
    """
    if not payload:
        return {"passed": True, "reasons": [], "raw_verdicts": {}}
    reasons: list[str] = []

    device = (payload.get("deviceIntegrity") or {}).get("deviceRecognitionVerdict") or []
    # Device must meet basic integrity. STRONG verdicts: MEETS_DEVICE_INTEGRITY,
    # MEETS_BASIC_INTEGRITY, MEETS_STRONG_INTEGRITY.
    if not any(v.startswith("MEETS_") for v in device):
        reasons.append("device_integrity_failed")

    app = (payload.get("appIntegrity") or {}).get("appRecognitionVerdict") or ""
    # PLAY_RECOGNIZED is the gold standard. UNRECOGNIZED_VERSION means the
    # APK on the device has been re-signed or tampered with.
    if app not in ("PLAY_RECOGNIZED",):
        reasons.append(f"app_recognition_{app or 'unknown'}")

    licensing = (payload.get("accountDetails") or {}).get("appLicensingVerdict") or ""
    if licensing not in ("LICENSED", "UNEVALUATED"):
        reasons.append(f"licensing_{licensing}")

    return {
        "passed": len(reasons) == 0,
        "reasons": reasons,
        "raw_verdicts": {
            "device": device,
            "app": app,
            "licensing": licensing,
            "play_protect": (payload.get("environmentDetails") or {}).get("playProtectVerdict"),
        },
    }
