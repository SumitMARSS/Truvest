"""Persist research jobs in Redis (JSON). Falls back to in-memory if Redis is down."""

import json
import logging
from datetime import datetime
from typing import Any, Optional

from app.core.config import settings
from app.models.schemas import JobStatus, ResearchBrief, ResearchJobResponse
from app.services.redis_client import get_redis

logger = logging.getLogger(__name__)

_memory: dict[str, dict[str, Any]] = {}


def _key(job_id: str) -> str:
    return f"research:job:{job_id}"


async def save_job(job: ResearchJobResponse) -> None:
    payload = job.model_dump(mode="json")
    r = get_redis()
    if r is not None:
        try:
            await r.set(
                _key(job.job_id),
                json.dumps(payload),
                ex=settings.brief_cache_ttl_seconds * 6,
            )
            return
        except Exception:
            logger.warning("Redis save failed — using memory store")
    _memory[job.job_id] = payload


async def get_job(job_id: str) -> Optional[ResearchJobResponse]:
    raw: Optional[dict[str, Any]] = None
    r = get_redis()
    if r is not None:
        try:
            data = await r.get(_key(job_id))
            if data:
                raw = json.loads(data)
        except Exception:
            raw = _memory.get(job_id)

    if not raw:
        raw = _memory.get(job_id)
    if not raw:
        return None
    return ResearchJobResponse.model_validate(raw)


async def update_job(job_id: str, **fields: Any) -> Optional[ResearchJobResponse]:
    job = await get_job(job_id)
    if not job:
        return None

    data = job.model_dump(mode="json")
    for k, v in fields.items():
        if isinstance(v, JobStatus):
            data[k] = v.value
        elif isinstance(v, ResearchBrief):
            data[k] = v.model_dump(mode="json")
        elif isinstance(v, datetime):
            data[k] = v.isoformat()
        else:
            data[k] = v

    updated = ResearchJobResponse.model_validate(data)
    await save_job(updated)
    return updated
