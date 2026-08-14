"""
Critic node — factual consistency + citation + freshness gates.

On failure: emit critic_issues with failed_subtask so planner retries ONLY those workers.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from app.agents.state import AgentState, CriticIssue
from app.core.config import settings

logger = logging.getLogger(__name__)


def critic_node(state: AgentState) -> dict[str, Any]:
    draft = state.get("draft_brief") or {}
    issues: list[CriticIssue] = []
    notes: list[str] = []

    issues.extend(_check_pe_consistency(draft))
    issues.extend(_check_citations(draft))
    issues.extend(_check_news_freshness(draft))
    issues.extend(_check_required_sections(draft))

    # UPDATE: LLM-as-judge pass for unsupported claims in analyst_summary
    # UPDATE: numeric tolerance tables per metric (market_cap can be stale vs live price)

    retry_count = int(state.get("retry_count") or 0)
    truly_passed = len(issues) == 0
    force_accept = (not truly_passed) and retry_count >= settings.max_critic_retries

    if truly_passed:
        notes.append("All critic checks passed.")
    else:
        notes.append(f"{len(issues)} issue(s) found.")
        for i in issues:
            notes.append(f"[{i.get('failed_subtask')}] {i.get('code')}: {i.get('message')}")
        if force_accept:
            notes.append(
                f"Max critic retries ({settings.max_critic_retries}) reached — "
                "accepting brief with warnings."
            )

    accept = truly_passed or force_accept
    brief = {
        **draft,
        "critic_passed": truly_passed,
        "critic_notes": notes,
        "metadata": {
            **(draft.get("metadata") or {}),
            "force_accepted": force_accept,
            "retry_count": retry_count,
        },
    }

    return {
        "critic_passed": accept,
        "critic_issues": [] if accept else issues,
        "critic_notes": notes,
        "brief": brief if accept else draft,
        "draft_brief": brief,
        "retry_count": retry_count if accept else retry_count + 1,
        "status_message": "critic_pass" if accept else "critic_fail",
    }


def _check_pe_consistency(draft: dict[str, Any]) -> list[CriticIssue]:
    funds = draft.get("fundamentals") or {}
    calcs = draft.get("calculations") or {}
    reported = funds.get("pe_ratio")
    derived = calcs.get("pe_from_price_eps")
    issues: list[CriticIssue] = []
    if reported is None or derived is None:
        return issues
    if abs(float(reported) - float(derived)) > 2.5:
        issues.append(
            {
                "code": "PE_MISMATCH",
                "message": f"Reported P/E {reported} vs price/EPS {derived}",
                "failed_subtask": "market",
                "claim": "pe_ratio",
            }
        )
    return issues


def _check_citations(draft: dict[str, Any]) -> list[CriticIssue]:
    """Every numeric claim block must list source_ids present in sources."""
    source_ids = {s.get("id") for s in (draft.get("sources") or []) if s.get("id")}
    issues: list[CriticIssue] = []

    def need(block_name: str, block: dict[str, Any], worker: str) -> None:
        sids = block.get("source_ids") or []
        if not sids:
            issues.append(
                {
                    "code": "MISSING_CITATION",
                    "message": f"{block_name} has no source_ids",
                    "failed_subtask": worker,  # type: ignore[typeddict-item]
                    "claim": block_name,
                }
            )
            return
        for sid in sids:
            if sid not in source_ids:
                issues.append(
                    {
                        "code": "DANGLING_CITATION",
                        "message": f"{block_name} cites unknown source {sid}",
                        "failed_subtask": worker,  # type: ignore[typeddict-item]
                        "claim": sid,
                    }
                )

    need("price_action", draft.get("price_action") or {}, "market")
    need("fundamentals", draft.get("fundamentals") or {}, "market")
    need("calculations", draft.get("calculations") or {}, "calc")

    for i, n in enumerate(draft.get("news") or []):
        if not n.get("source_ids"):
            issues.append(
                {
                    "code": "NEWS_UNCITED",
                    "message": f"News item {i} missing source_ids",
                    "failed_subtask": "news",
                    "claim": n.get("title") or str(i),
                }
            )
    return issues


def _check_news_freshness(draft: dict[str, Any], max_age_days: int = 45) -> list[CriticIssue]:
    """Reject if articles are stale; stubs alone are allowed for keyless demos."""
    news = draft.get("news") or []
    issues: list[CriticIssue] = []
    if not news:
        issues.append(
            {
                "code": "NO_NEWS",
                "message": "No news articles attached — sentiment may be hallucinated",
                "failed_subtask": "news",
                "claim": "news",
            }
        )
        return issues

    stubby = sum(1 for n in news if (n.get("title") or "").startswith("[STUB]"))
    if stubby == len(news):
        # Soft path for demos without Tavily
        # UPDATE: hard-fail in CI eval when TAVILY_API_KEY is present
        return issues

    cutoff = datetime.utcnow() - timedelta(days=max_age_days)
    dated = 0
    fresh = 0
    for n in news:
        pub = n.get("published")
        if not pub:
            continue
        dated += 1
        try:
            dt = datetime.fromisoformat(str(pub).replace("Z", "+00:00")).replace(tzinfo=None)
            if dt >= cutoff:
                fresh += 1
        except Exception:
            continue

    if dated >= 2 and fresh == 0:
        issues.append(
            {
                "code": "STALE_NEWS",
                "message": f"No articles within last {max_age_days} days",
                "failed_subtask": "news",
                "claim": "freshness",
            }
        )

    with_url = sum(
        1 for n in news if n.get("url") and urlparse(str(n["url"])).scheme in {"http", "https"}
    )
    if with_url == 0:
        issues.append(
            {
                "code": "NEWS_NO_URL",
                "message": "News items lack URLs — not traceable",
                "failed_subtask": "news",
                "claim": "url",
            }
        )
    return issues


def _check_required_sections(draft: dict[str, Any]) -> list[CriticIssue]:
    issues: list[CriticIssue] = []
    if not draft.get("analyst_summary"):
        issues.append(
            {
                "code": "EMPTY_SUMMARY",
                "message": "analyst_summary empty",
                "failed_subtask": "market",
                "claim": "analyst_summary",
            }
        )
    pa = draft.get("price_action") or {}
    if pa.get("last_price") is None:
        issues.append(
            {
                "code": "NO_PRICE",
                "message": "last_price missing",
                "failed_subtask": "market",
                "claim": "last_price",
            }
        )
    return issues
