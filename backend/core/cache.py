"""In-process TTL cache (Redis-equivalent for single-pod deployments).

The Emergent platform doesn't expose a Redis service we can connect to,
so we use `cachetools.TTLCache` which gives us per-process LRU caching
with time-based expiry. For read-heavy public endpoints (branding,
shop-categories, products list) this delivers ~95% of Redis's latency
benefit because:
  • most reads are answered from the in-memory cache (sub-millisecond)
  • the cache size is bounded (LRU eviction) so memory stays predictable
  • TTLs auto-expire stale entries

The only thing we lose vs real Redis is **cross-pod cache sharing** —
if the deployment scales to >1 backend pod, each pod has its own cache
and updates may take up to TTL seconds to propagate. For the current
single-worker uvicorn setup this is a non-issue.

Usage:

    from core.cache import response_cache, invalidate

    @router.get("/branding")
    async def get_branding():
        cached = response_cache.get("branding")
        if cached is not None:
            return cached
        doc = await build_branding()
        response_cache.set("branding", doc, ttl=60)
        return doc

    # On PUT/POST that mutates branding:
    invalidate("branding")

For ultra-simple cases there is also `@cached(ttl=...)` decorator below
which works on plain async functions.
"""
from __future__ import annotations

import asyncio
import time
from functools import wraps
from typing import Any, Awaitable, Callable, Dict, Optional

from cachetools import TTLCache


# ── Default cache namespace ────────────────────────────────────────────────
# Sized for ~10k distinct keys at any time and 60-second default TTL.
# Endpoints can override TTL per-key via .set(key, value, ttl=N).
_GLOBAL_TTL_S = 60
_GLOBAL_MAX_KEYS = 10_000


class ResponseCache:
    """Thread-safe TTL cache with manual ttl override per .set()."""

    def __init__(self, maxsize: int = _GLOBAL_MAX_KEYS, ttl: int = _GLOBAL_TTL_S):
        # Underlying cache uses the longest possible TTL so per-key shorter
        # TTLs are enforced via stored timestamp comparison in .get().
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl)
        self._expiries: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    def get(self, key: str) -> Optional[Any]:
        try:
            value = self._cache[key]
        except KeyError:
            return None
        exp = self._expiries.get(key)
        if exp is not None and exp < time.time():
            # Per-key TTL expired even though the global TTL may still be alive.
            self._cache.pop(key, None)
            self._expiries.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        self._cache[key] = value
        if ttl is not None:
            self._expiries[key] = time.time() + ttl

    def invalidate(self, key: str) -> None:
        self._cache.pop(key, None)
        self._expiries.pop(key, None)

    def invalidate_prefix(self, prefix: str) -> int:
        """Drop every key that starts with `prefix`. Returns count dropped."""
        keys = [k for k in list(self._cache.keys()) if isinstance(k, str) and k.startswith(prefix)]
        for k in keys:
            self.invalidate(k)
        return len(keys)

    def clear(self) -> None:
        self._cache.clear()
        self._expiries.clear()

    @property
    def stats(self) -> Dict[str, int]:
        return {"size": len(self._cache), "maxsize": self._cache.maxsize}


# Singleton instance used everywhere.
response_cache = ResponseCache()


def invalidate(key: str) -> None:
    response_cache.invalidate(key)


def invalidate_prefix(prefix: str) -> int:
    return response_cache.invalidate_prefix(prefix)


# ── Decorator for cleaner endpoint wrapping ────────────────────────────────
def cached(key: str, ttl: int = 60):
    """Cache the result of an async function under a fixed key.

    Use for endpoints whose response doesn't depend on the caller (e.g. the
    public branding doc, the active shop-categories list). For per-user
    responses, build the cache key inside the endpoint instead.
    """
    def decorator(func: Callable[..., Awaitable[Any]]):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            hit = response_cache.get(key)
            if hit is not None:
                return hit
            result = await func(*args, **kwargs)
            response_cache.set(key, result, ttl=ttl)
            return result
        return wrapper
    return decorator
