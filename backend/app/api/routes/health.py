from fastapi import APIRouter

from app.core.config import settings
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

    provider = settings.llm_provider.lower()
    active_model = {
        "openrouter": settings.openrouter_model,
        "openai": settings.openai_model,
        "anthropic": settings.anthropic_model,
    }.get(provider, settings.llm_model)

    return {
        "status": "ok",
        "redis": redis_ok,
        "job_store": "redis" if redis_ok else "memory",
        "llm_provider": settings.llm_provider,
        "llm_model": active_model,
    }
