"""
Idempotency middleware — Dec 2026.

The frontend axios interceptor now retries POST/PUT/PATCH/DELETE up to
3 times when the network layer drops a response mid-flight.  Without a
server-side guard, a retry could execute the same write twice (e.g. a
duplicate order).

This middleware intercepts requests that carry an `Idempotency-Key`
HTTP header:
  * First seen key  → passes through, caches the response for 10 min.
  * Repeat within 10 min → returns the ORIGINAL response body + status
    without re-executing the handler (safe replay).
  * After 10 min → the cache entry expires and the write can re-run.

Keys are stored in an in-memory LRU dict (per-process; the pod runs a
single worker so this is sufficient).  For horizontal scale-out we'd
promote this to Redis, but until then the memory footprint is bounded
at 4096 keys × ~2 KB avg = ~8 MB max.

Read verbs (GET/HEAD/OPTIONS) skip the guard — they're already safe to
replay.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any, Callable, Dict, Optional, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


_MAX_ENTRIES = 4096
_TTL_SECONDS = 600.0
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class _LRU(OrderedDict):
    def __setitem__(self, key: Any, value: Any) -> None:  # noqa: D401
        if key in self:
            self.move_to_end(key)
        super().__setitem__(key, value)
        if len(self) > _MAX_ENTRIES:
            self.popitem(last=False)


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Cache-and-replay for keyed write requests."""

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        # key → (expires_at, status, body_bytes, media_type)
        self._cache: "_LRU[str, Tuple[float, int, bytes, str]]" = _LRU()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.method not in _UNSAFE_METHODS:
            return await call_next(request)
        key = request.headers.get("idempotency-key") or request.headers.get("Idempotency-Key")
        if not key:
            return await call_next(request)
        # Namespace by verb + path so a POST and a DELETE with the same
        # random key don't collide.
        cache_key = f"{request.method}:{request.url.path}:{key}"
        now = time.time()
        hit = self._cache.get(cache_key)
        if hit and hit[0] > now:
            _, status, body, media = hit
            return Response(
                content=body,
                status_code=status,
                media_type=media or "application/json",
                headers={"X-Idempotent-Replay": "1"},
            )

        # Fresh execution — capture the response body so we can replay.
        response = await call_next(request)
        try:
            chunks: list[bytes] = []
            async for c in response.body_iterator:
                chunks.append(c if isinstance(c, bytes) else c.encode("utf-8"))
            body = b"".join(chunks)
        except Exception:
            # If body_iterator isn't awaitable (streamed response), skip
            # caching — retries of a stream just replay from scratch.
            return response

        # Only cache successful writes (2xx).  4xx/5xx should still be
        # retryable — user might fix input / server might recover.
        if 200 <= response.status_code < 300:
            self._cache[cache_key] = (
                now + _TTL_SECONDS,
                response.status_code,
                body,
                response.media_type or "application/json",
            )

        return Response(
            content=body,
            status_code=response.status_code,
            media_type=response.media_type,
            headers=dict(response.headers),
        )
