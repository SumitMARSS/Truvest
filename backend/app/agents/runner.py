"""Sync entrypoint used by FastAPI background tasks."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from app.agents.compare import build_comparison
from app.agents.graph import get_graph
from app.models.schemas import CompareBrief, ResearchBrief

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str], None]


def run_research_pipeline(
    query: str,
    job_id: str,
    progress_cb: Optional[ProgressCallback] = None,
) -> ResearchBrief:
    graph = get_graph()
    initial = {
        "query": query,
        "job_id": job_id,
        "sources": [],
        "completed_workers": [],
        "retry_count": 0,
        "critic_issues": [],
        "pending_workers": [],
    }

    # Stream node-by-node so the API can surface live progress instead of
    # a job that silently says "running" for many minutes.
    final_state: dict = {}
    for update in graph.stream(initial, stream_mode="updates"):
        for node_name, node_out in update.items():
            if isinstance(node_out, dict):
                final_state.update(node_out)
            if progress_cb:
                try:
                    progress_cb(node_out.get("status_message") or node_name)
                except Exception:
                    logger.debug("progress callback failed", exc_info=True)

    brief_dict = final_state.get("brief") or final_state.get("draft_brief") or {}
    if not brief_dict:
        raise RuntimeError(final_state.get("error") or "Pipeline produced empty brief")
    return ResearchBrief.model_validate(brief_dict)


def run_compare_pipeline(
    query_a: str,
    query_b: str,
    job_id: str,
    progress_cb: Optional[ProgressCallback] = None,
) -> CompareBrief:
    """
    Compare mode (spec 2.7) — runs the SAME single-ticker pipeline twice,
    concurrently (each in its own thread; this function is itself already
    called from a background thread via asyncio.to_thread, so this is a
    plain ThreadPoolExecutor, not asyncio). Each side gets the full
    planner -> workers -> critic -> retry treatment independently; if one
    side fails to resolve or times out, that exception propagates as-is —
    the caller (api/routes/research.py) handles it the same way it handles
    a single-ticker failure.
    """

    def _run_side(label: str, query: str) -> ResearchBrief:
        def _cb(message: str) -> None:
            if progress_cb:
                progress_cb(f"{label}:{message}")

        return run_research_pipeline(query, job_id=f"{job_id}-{label}", progress_cb=_cb)

    with ThreadPoolExecutor(max_workers=2) as pool:
        future_a = pool.submit(_run_side, "a", query_a)
        future_b = pool.submit(_run_side, "b", query_b)
        brief_a = future_a.result()
        brief_b = future_b.result()

    extra = build_comparison(brief_a, brief_b)
    return CompareBrief(tickers=[brief_a.ticker, brief_b.ticker], briefs=[brief_a, brief_b], **extra)
