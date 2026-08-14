"""Planner node — decompose research request; honor critic retry targets."""

from __future__ import annotations

import logging
from typing import Any

from app.agents.state import AgentState, WorkerName

logger = logging.getLogger(__name__)

DEFAULT_WORKERS: list[WorkerName] = ["market", "news", "filings", "calc"]


def planner_node(state: AgentState) -> dict[str, Any]:
    """
    First pass: queue all workers.
    On critic failure: only re-queue failed_subtasks from critic_issues.
    """
    ticker = state.get("ticker") or state.get("query", "").upper()
    issues = state.get("critic_issues") or []
    retry_count = int(state.get("retry_count") or 0)

    if issues:
        failed = []
        for issue in issues:
            w = issue.get("failed_subtask")
            if w and w not in failed:
                failed.append(w)
        # calc depends on market — if market retries, also re-run calc
        if "market" in failed and "calc" not in failed:
            failed.append("calc")

        plan = [f"RETRY[{retry_count}]: re-run worker '{w}' for {ticker}" for w in failed]
        logger.info("Planner retry plan for %s: %s", ticker, failed)
        return {
            "plan": plan,
            "pending_workers": failed,
            "critic_issues": [],  # clear for next critic pass
            "status_message": f"planner_retry_{retry_count}",
        }

    plan = [
        f"Fetch NSE/BSE price & fundamentals for {ticker}",
        f"Fetch India market news + sentiment for {ticker}",
        f"Fetch latest quarterly/annual results highlights for {ticker}",
        f"Compute derived metrics (P/E check, SMAs, YoY) for {ticker}",
        f"Synthesize INR research brief for {ticker}",
    ]
    # UPDATE: use LLM planner (get_chat_model) to dynamically add subtasks
    # e.g. peer comparison, options skew — keep deterministic for MVP reliability
    return {
        "plan": plan,
        "pending_workers": list(DEFAULT_WORKERS),
        "completed_workers": [],
        "retry_count": 0,
        "status_message": "planned",
    }
