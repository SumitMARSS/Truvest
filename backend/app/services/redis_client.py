"""Redis connection helpers — optional in local/dev (falls back to in-memory job store)."""

from __future__ import annotations

import logging
from typing import Optional

import redis.asyncio as redis

from app.core.config import settings

logger = logging.getLogger(__name__)

_redis: Optional[redis.Redis] = None


async def init_redis() -> Optional[redis.Redis]:
    """Connect to Redis if available. Does not crash the app when Redis is down."""
    global _redis
    try:
        client = redis.from_url(settings.redis_url, decode_responses=True)
        await client.ping()
        _redis = client
        logger.info("Redis connected at %s", settings.redis_url)
        return _redis
    except Exception as exc:
        logger.warning("Redis unavailable (%s) — using in-memory job store", exc)
        _redis = None
        return None


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


def get_redis() -> Optional[redis.Redis]:
    return _redis
