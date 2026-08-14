"""Sync entrypoint used by FastAPI background tasks."""

from __future__ import annotations

import logging
from typing import Callable, Optional

from app.agents.graph import get_graph
from app.models.schemas import ResearchBrief

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
