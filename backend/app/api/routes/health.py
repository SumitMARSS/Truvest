from fastapi import APIRouter

from app.core.config import settings
from app.services.llm import active_model_id
from app.services.redis_client import get_redis

router = APIRouter()


@router.get("/health")
async def health():
    redis_ok = False
    r = get_redis()
    if r is not None:
        try:
            redis_ok = bool(await r.ping())
        except Exception:
            redis_ok = False

    return {
        "status": "ok",
        "redis": redis_ok,
        "job_store": "redis" if redis_ok else "memory",
        "llm_provider": settings.llm_provider,
        # The server default. What a given job ran on is on the job record —
        # the user can now pick a different model per run (GET /api/v1/models).
        "llm_model": active_model_id(),
    }
