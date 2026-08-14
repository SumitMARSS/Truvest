"""Research job endpoints — kick off agent graph, poll status."""

import asyncio
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.core.config import settings
from app.models.schemas import JobStatus, ResearchJobResponse, ResearchRequest
from app.services import job_store
from app.agents.runner import run_research_pipeline

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/research", response_model=ResearchJobResponse)
async def start_research(body: ResearchRequest, background: BackgroundTasks):
    job_id = str(uuid.uuid4())
    job = ResearchJobResponse(
        job_id=job_id,
        status=JobStatus.pending,
        query=body.query.strip(),
        progress="queued",
    )
    await job_store.save_job(job)

    # Run agent graph in background so HTTP returns immediately
    background.add_task(_execute_job, job_id, body.query.strip())
    return job


@router.get("/research/{job_id}", response_model=ResearchJobResponse)
async def get_research(job_id: str):
    job = await job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# UPDATE: add SSE endpoint GET /research/{job_id}/events for live node progress
# UPDATE: add GET /research/{job_id}/brief.md for markdown export


async def _execute_job(job_id: str, query: str) -> None:
    await job_store.update_job(
        job_id,
        status=JobStatus.running,
        progress="starting_agents",
        updated_at=datetime.utcnow(),
    )

    loop = asyncio.get_running_loop()

    def on_progress(message: str) -> None:
        # Called from the worker thread — hop back onto the event loop
        asyncio.run_coroutine_threadsafe(
            job_store.update_job(
                job_id,
                progress=message,
                updated_at=datetime.utcnow(),
            ),
            loop,
        )

    try:
        # Hard cap so a stalled LLM/tool never leaves the job "running" forever.
        # NOTE: the worker thread may keep running after timeout (Python threads
        # can't be force-killed); the job is still marked failed for the client.
        brief = await asyncio.wait_for(
            asyncio.to_thread(run_research_pipeline, query, job_id, on_progress),
            timeout=settings.pipeline_timeout_seconds,
        )
        await job_store.update_job(
            job_id,
            status=JobStatus.completed,
            progress="done",
            brief=brief,
            updated_at=datetime.utcnow(),
        )
    except asyncio.TimeoutError:
        logger.error("Research job %s timed out after %ss", job_id, settings.pipeline_timeout_seconds)
        await job_store.update_job(
            job_id,
            status=JobStatus.failed,
            progress="timeout",
            error=(
                f"Research timed out after {settings.pipeline_timeout_seconds}s. "
                "The local LLM may be too slow — try a smaller model "
                "(e.g. LLM_MODEL=llama3:latest in .env) or raise PIPELINE_TIMEOUT_SECONDS."
            ),
            updated_at=datetime.utcnow(),
        )
    except Exception as exc:
        logger.exception("Research job %s failed", job_id)
        await job_store.update_job(
            job_id,
            status=JobStatus.failed,
            progress="failed",
            error=str(exc),
            updated_at=datetime.utcnow(),
        )
