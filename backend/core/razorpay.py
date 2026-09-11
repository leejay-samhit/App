"""Razorpay credentials + primitives shared by every payment flow.

Two flows use Razorpay today:
  • the one-time registration / subscription fee  (server.py)
  • shop order checkout                          (routes/order_payments.py)

Both must read the SAME credentials (Admin Panel → Payment Gateway wins over
`.env`) and fall back to the same MOCK mode when no keys are configured, so
the logic lives here instead of being copy-pasted.
"""
import hashlib
import hmac
import logging
import os
import secrets
from typing import Any, Dict, Optional

import httpx

from core.utils import get_settings

logger = logging.getLogger(__name__)

ENV_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "").strip()
ENV_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "").strip()


async def get_creds() -> Dict[str, Any]:
    """Active Razorpay credentials. Precedence: admin settings > env > mock."""
    s = await get_settings()
    rzp = (s.get("razorpay") or {}) if isinstance(s.get("razorpay"), dict) else {}
    db_id = (rzp.get("key_id") or "").strip()
    db_secret = (rzp.get("key_secret") or "").strip()
    if db_id and db_secret:
        return {"key_id": db_id, "key_secret": db_secret, "source": "db", "is_mock": False}
    if ENV_KEY_ID and ENV_KEY_SECRET:
        return {"key_id": ENV_KEY_ID, "key_secret": ENV_KEY_SECRET, "source": "env", "is_mock": False}
    return {"key_id": "", "key_secret": "", "source": "none", "is_mock": True}


def verify_signature(order_id: str, payment_id: str, signature: str, secret: str) -> bool:
    """Timing-safe HMAC-SHA256 check of `order_id|payment_id`."""
    expected = hmac.new(
        secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature or "")


async def create_order(
    amount_paise: int,
    receipt: str,
    notes: Optional[Dict[str, Any]] = None,
    creds: Optional[Dict[str, Any]] = None,
) -> str:
    """Create a Razorpay order and return its id. Mock mode returns a fake id."""
    creds = creds or await get_creds()
    if creds["is_mock"]:
        return f"order_MOCK_{secrets.token_hex(8)}"
    async with httpx.AsyncClient(timeout=15.0, auth=(creds["key_id"], creds["key_secret"])) as client:
        r = await client.post(
            "https://api.razorpay.com/v1/orders",
            json={
                "amount": int(amount_paise),
                "currency": "INR",
                "receipt": receipt[:40],
                "notes": notes or {},
            },
        )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Razorpay order failed: {r.text[:200]}")
    return r.json().get("id")


async def fetch_payment(payment_id: str, creds: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Cross-check a payment with Razorpay. None in mock mode / on failure."""
    creds = creds or await get_creds()
    if creds.get("is_mock") or not creds.get("key_secret") or not payment_id:
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0, auth=(creds["key_id"], creds["key_secret"])) as client:
            r = await client.get(f"https://api.razorpay.com/v1/payments/{payment_id}")
        if r.status_code == 200:
            return r.json()
        logger.warning(f"Razorpay payment fetch returned {r.status_code}: {r.text[:200]}")
    except Exception as e:  # network hiccup — caller falls back to HMAC trust
        logger.warning(f"Razorpay payment fetch failed: {e}")
    return None
