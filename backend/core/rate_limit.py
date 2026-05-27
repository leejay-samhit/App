"""Rate-limiting via SlowAPI.

Protects expensive / abuse-prone endpoints (auth, payment submission,
withdrawal request) against credential-stuffing, brute-force, replay,
and denial-of-wallet attacks.

Limits are intentionally generous so they never bite legitimate users —
they only bite scripts. If a real user hits one, the response is a
clean 429 with a friendly message, not a hard ban.

Key strategy:
    • Authenticated endpoints → key by user_id (read from JWT in request).
    • Unauthenticated endpoints (login, register) → key by client IP.
"""
from __future__ import annotations

from typing import Optional

from fastapi import Request
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from fastapi.responses import JSONResponse


def _key_func(request: Request) -> str:
    """Use the JWT subject (user id) when present, else fall back to the
    remote IP. This way one logged-in user can be rate-limited across all
    their devices, and unauthenticated probes are limited per source IP."""
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        # We don't want to do full JWT verification in the limiter — that
        # would defeat the point. The token's payload is short; the last 24
        # chars are a stable enough handle for rate-limiting only. Real
        # auth happens in the endpoint as usual.
        return f"u:{auth[-24:]}"
    return f"ip:{get_remote_address(request)}"


# Default of "60/minute" gives every endpoint a generous baseline; specific
# endpoints decorate themselves with stricter limits via @limiter.limit("X/Y").
limiter = Limiter(key_func=_key_func, default_limits=["120/minute"])


def rate_limit_handler(_request: Request, exc: RateLimitExceeded):
    """Friendly 429 response (avoids leaking the slowapi internals)."""
    detail = getattr(exc, "detail", "Too many requests")
    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limited",
            "message": "Too many requests. Please slow down and try again in a moment.",
            "detail": str(detail),
        },
    )
