"""
Tiny TTL cache for data that changes slowly (sector P/E, shareholding patterns).

Why this exists (docs/AUDIT.md #5): before this pass there was zero caching of
market/news/filing data anywhere — every request hit yfinance/Tavily fresh.
That's fine for a live price, but wrong for data that only updates 4x/year
(shareholding pattern) or once a day (sector-average P/E) — refetching those
on every brief burns free-tier quota and adds latency for no benefit.

Backend: Redis if connected (shared across API workers, survives restarts),
in-memory dict otherwise (same in-memory fallback pattern as job_store.py).
Callers should treat this as best-effort — a cache miss or Redis outage must
never fail a request, only make it slower.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

from app.services.redis_client import get_redis

logger = logging.getLogger(__name__)

_memory: dict[str, tuple[float, Any]] = {}


@dataclass
class CacheEntry:
    value: Any
    as_of: str  # ISO timestamp the value was fetched, surfaced to the UI for staleness
    stale: bool = False


def _key(namespace: str, key: str) -> str:
    return f"cache:{namespace}:{key}"


async def cache_get(namespace: str, key: str) -> Optional[Any]:
    full_key = _key(namespace, key)
    r = get_redis()
    if r is not None:
        try:
            raw = await r.get(full_key)
            if raw:
                return json.loads(raw)
        except Exception:
            logger.debug("cache_get redis miss/fail for %s", full_key, exc_info=True)

    entry = _memory.get(full_key)
    if entry is None:
        return None
    expires_at, value = entry
    if expires_at < time.time():
        _memory.pop(full_key, None)
        return None
    return value


async def cache_set(namespace: str, key: str, value: Any, ttl_seconds: int) -> None:
    full_key = _key(namespace, key)
    r = get_redis()
    if r is not None:
        try:
            await r.set(full_key, json.dumps(value, default=str), ex=ttl_seconds)
            return
        except Exception:
            logger.debug("cache_set redis fail for %s — using memory", full_key, exc_info=True)
    _memory[full_key] = (time.time() + ttl_seconds, value)


def cache_get_sync(namespace: str, key: str) -> Optional[Any]:
    """Sync variant for use inside LangGraph worker nodes (which run in a
    background thread, not the asyncio event loop) — memory-only, since the
    redis.asyncio client can't be awaited here. Redis-backed reads only
    happen from async API code paths (there are none yet that need it)."""
    full_key = _key(namespace, key)
    entry = _memory.get(full_key)
    if entry is None:
        return None
    expires_at, value = entry
    if expires_at < time.time():
        _memory.pop(full_key, None)
        return None
    return value


def cache_set_sync(namespace: str, key: str, value: Any, ttl_seconds: int) -> None:
    full_key = _key(namespace, key)
    _memory[full_key] = (time.time() + ttl_seconds, value)
