"""LangGraph shared state for the research pipeline."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, Optional, TypedDict


WorkerName = Literal["market", "news", "filings", "calc"]


def _last_value(_old: str, new: str) -> str:
    """Reducer for progress text — parallel workers may write it in the same step."""
    return new


class CriticIssue(TypedDict, total=False):
    code: str
    message: str
    failed_subtask: WorkerName
    claim: str


class AgentState(TypedDict, total=False):
    # Input
    query: str
    job_id: str

    # Resolved identity
    ticker: str
    company_name: Optional[str]

    # Planner output
    plan: list[str]  # human-readable subtasks
    pending_workers: list[WorkerName]
    completed_workers: Annotated[list[WorkerName], operator.add]
    retry_count: int

    # Worker payloads (raw)
    market_data: dict[str, Any]
    news_data: dict[str, Any]
    filings_data: dict[str, Any]
    calc_data: dict[str, Any]

    # Sources accumulated across workers
    sources: Annotated[list[dict[str, Any]], operator.add]

    # Synthesis + critique
    draft_brief: dict[str, Any]
    critic_passed: bool
    critic_issues: list[CriticIssue]
    critic_notes: list[str]

    # Final
    brief: dict[str, Any]
    error: Optional[str]
    status_message: Annotated[str, _last_value]
