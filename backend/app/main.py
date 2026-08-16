"""FastAPI entrypoint for the Stock Research multi-agent system."""

import asyncio
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import health, research, search
from app.core.config import settings
from app.core.logging import setup_logging
from app.services.redis_client import close_redis, init_redis

logger = logging.getLogger(__name__)


async def _warm_ollama_model() -> None:
    """Preload the model into memory so the first research job doesn't pay load time."""
    if settings.llm_provider.lower() != "ollama":
        return
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            # Empty prompt = load model only; keep_alive matches the chat client
            await client.post(
                f"{settings.ollama_base_url}/api/generate",
                json={"model": settings.llm_model, "keep_alive": "30m"},
            )
        logger.info("Ollama model %s warmed and resident", settings.llm_model)
    except Exception as exc:
        logger.warning("Ollama warmup failed (%s) — first request will be slower", exc)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_logging()
    await init_redis()
    # Fire-and-forget so startup isn't blocked while the model loads
    warmup = asyncio.create_task(_warm_ollama_model())
    yield
    warmup.cancel()
    await close_redis()


app = FastAPI(
    title="Stock Research Agent API",
    description="Planner → Worker → Critic multi-agent equity research briefs",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(research.router, prefix="/api/v1", tags=["research"])
app.include_router(search.router, prefix="/api/v1", tags=["search"])
