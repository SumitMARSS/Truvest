"""Research job endpoints — kick off agent graph, poll status."""

import asyncio
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.core.config import settings
from app.models.schemas import JobStatus, ResearchJobResponse, ResearchRequest, StockSuggestion
from app.services import job_store
from app.services.intent import detect_compare_intent
from app.services.ticker_resolve import TickerResolutionError
from app.agents.runner import run_compare_pipeline, run_research_pipeline

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/research", response_model=ResearchJobResponse)
async def start_research(body: ResearchRequest, background: BackgroundTasks):
    job_id = str(uuid.uuid4())
    query = body.query.strip()

    # Compare mode (spec 2.7) — "RELIANCE vs TCS", "compare X and Y". Detected
    # up front so the job record's `mode` is correct from the very first poll.
    pair = detect_compare_intent(query)
    mode = "compare" if pair else "single"

    job = ResearchJobResponse(
        job_id=job_id,
        status=JobStatus.pending,
        query=query,
        progress="queued",
        mode=mode,
    )
    await job_store.save_job(job)

    if pair:
        background.add_task(_execute_compare_job, job_id, pair[0], pair[1])
    else:
        background.add_task(_execute_job, job_id, query)
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
            error_code="timeout",
            error=(
                f"Research timed out after {settings.pipeline_timeout_seconds}s. "
                "The local LLM may be too slow — try a smaller model "
                "(e.g. LLM_MODEL=llama3:latest in .env) or raise PIPELINE_TIMEOUT_SECONDS."
            ),
            updated_at=datetime.utcnow(),
        )
    except TickerResolutionError as exc:
        # Distinct from an internal failure (docs/AUDIT.md #1.3) — the user
        # mistyped or asked for a ticker we can't resolve, not a bug on our end.
        # The ranked alternatives ride along so the UI can offer one-click
        # recovery instead of an apology.
        logger.info("Research job %s: ticker not resolved (%s)", job_id, exc)
        await job_store.update_job(
            job_id,
            status=JobStatus.failed,
            progress="ticker_not_found",
            error_code="ticker_not_found",
            error=str(exc),
            suggestions=[StockSuggestion(**s) for s in getattr(exc, "suggestions", [])],
            updated_at=datetime.utcnow(),
        )
    except Exception as exc:
        logger.exception("Research job %s failed", job_id)
        await job_store.update_job(
            job_id,
            status=JobStatus.failed,
            progress="failed",
            error_code="internal_error",
            error=str(exc),
            updated_at=datetime.utcnow(),
        )


async def _execute_compare_job(job_id: str, query_a: str, query_b: str) -> None:
    await job_store.update_job(
        job_id,
        status=JobStatus.running,
        progress="starting_agents",
        updated_at=datetime.utcnow(),
    )

    loop = asyncio.get_running_loop()

    def on_progress(message: str) -> None:
        asyncio.run_coroutine_threadsafe(
            job_store.update_job(job_id, progress=message, updated_at=datetime.utcnow()),
            loop,
        )

    try:
        compare_brief = await asyncio.wait_for(
            asyncio.to_thread(run_compare_pipeline, query_a, query_b, job_id, on_progress),
            # Both sides run concurrently in run_compare_pipeline, so the same
            # single-ticker budget applies — wall-clock is bounded by the
            # slower of the two, not their sum.
            timeout=settings.pipeline_timeout_seconds,
        )
        await job_store.update_job(
            job_id,
            status=JobStatus.completed,
            progress="done",
            compare_brief=compare_brief,
            updated_at=datetime.utcnow(),
        )
    except asyncio.TimeoutError:
        logger.error("Compare job %s timed out after %ss", job_id, settings.pipeline_timeout_seconds)
        await job_store.update_job(
            job_id,
            status=JobStatus.failed,
            progress="timeout",
            error_code="timeout",
            error=f"Comparison timed out after {settings.pipeline_timeout_seconds}s.",
            updated_at=datetime.utcnow(),
        )
    except TickerResolutionError as exc:
        logger.info("Compare job %s: ticker not resolved (%s)", job_id, exc)
        await job_store.update_job(
            job_id,
            status=JobStatus.failed,
            progress="ticker_not_found",
            error_code="ticker_not_found",
            error=str(exc),
            suggestions=[StockSuggestion(**s) for s in getattr(exc, "suggestions", [])],
            updated_at=datetime.utcnow(),
        )
    except Exception as exc:
        logger.exception("Compare job %s failed", job_id)
        await job_store.update_job(
            job_id,
            status=JobStatus.failed,
            progress="failed",
            error_code="internal_error",
            error=str(exc),
            updated_at=datetime.utcnow(),
        )
