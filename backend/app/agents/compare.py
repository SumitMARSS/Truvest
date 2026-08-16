"""
Compare mode — spec 2.7.

Deliberately NOT a new graph topology: this runs the existing compiled
single-ticker StateGraph TWICE (once per side, concurrently), then joins
the two already-finished, already-critic-passed briefs into a side-by-side
table + narrative. Each side gets the full existing planner -> workers ->
critic -> targeted-retry treatment, completely unmodified — "mostly
wiring", per spec, not a second orchestration style.

The metrics table is pure data assembly (no LLM, no new math — every number
in it was already computed by calc for each side individually). Only the
prose narrative touches an LLM, and it goes through the same SEBI-safe
compliance rewrite as a single-ticker brief before being returned.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.compliance_filter import rewrite_text
from app.core.text_quality import looks_like_prose
from app.models.schemas import ResearchBrief
from app.services.llm import get_chat_model

logger = logging.getLogger(__name__)


def build_metrics_table(brief_a: ResearchBrief, brief_b: ResearchBrief) -> list[dict[str, Any]]:
    rows = []
    for b in (brief_a, brief_b):
        rows.append(
            {
                "ticker": b.ticker,
                "company_name": b.company_name,
                "last_price": b.price_action.last_price,
                "currency": b.price_action.currency,
                "change_1y_pct": b.price_action.change_1y_pct,
                "pe_ratio": b.fundamentals.pe_ratio,
                "market_cap": b.fundamentals.market_cap,
                "yoy_revenue_growth": b.calculations.yoy_revenue_growth,
                "overall_news_sentiment": b.overall_news_sentiment,
                "promoter_pct": b.shareholding.promoter_pct if b.shareholding.available else None,
                "sector_pe": b.valuation.sector_pe.pe if b.valuation.sector_pe.available else None,
            }
        )
    return rows


def _fallback_comparison_summary(brief_a: ResearchBrief, brief_b: ResearchBrief) -> str:
    """Deterministic, data-driven — same fallback contract as the
    single-ticker synthesizer: never leak an error, never invent a number."""
    a, b = brief_a, brief_b
    parts: list[str] = []
    if a.price_action.last_price is not None and b.price_action.last_price is not None:
        parts.append(
            f"{a.ticker} last traded at {a.price_action.currency or 'INR'} "
            f"{a.price_action.last_price:,.2f}; {b.ticker} at "
            f"{b.price_action.currency or 'INR'} {b.price_action.last_price:,.2f}."
        )
    if a.fundamentals.pe_ratio is not None and b.fundamentals.pe_ratio is not None:
        cheaper = a.ticker if a.fundamentals.pe_ratio < b.fundamentals.pe_ratio else b.ticker
        parts.append(
            f"{a.ticker} trades at a P/E of {a.fundamentals.pe_ratio:.1f} versus "
            f"{b.ticker} at {b.fundamentals.pe_ratio:.1f} — {cheaper} is cheaper on trailing earnings."
        )
    if a.overall_news_sentiment and b.overall_news_sentiment:
        parts.append(
            f"Recent news flow reads {a.overall_news_sentiment} for {a.ticker} "
            f"and {b.overall_news_sentiment} for {b.ticker}."
        )
    parts.append(
        "This is a data comparison, not investment advice — verify each figure "
        "against the sources cited in the individual briefs below."
    )
    return " ".join(parts)


def _llm_comparison_summary(brief_a: ResearchBrief, brief_b: ResearchBrief, metrics: list[dict[str, Any]]) -> str:
    compact = {
        "metrics": metrics,
        "a_summary": (brief_a.analyst_summary or "")[:800],
        "b_summary": (brief_b.analyst_summary or "")[:800],
    }
    prompt = (
        "You are an India equity research associate. Compare these two "
        "NSE/BSE stocks side by side in 5-8 sentences of plain prose: "
        "valuation (P/E, incl. vs sector P/E if present), recent performance, "
        "news tone, and promoter shareholding trend where present.\n"
        "Rules: ONLY use facts in the JSON below. Never state a price target "
        "and never say 'buy'/'sell' — describe historical/current data only, "
        "never a forecast or recommendation. No markdown, no JSON — prose only.\n\n"
        f"DATA:\n{json.dumps(compact, default=str)[:6000]}"
    )
    try:
        llm = get_chat_model(temperature=0.2)
        msg = llm.invoke(prompt)
        text = getattr(msg, "content", str(msg)).strip()
        if looks_like_prose(text):
            return text
        logger.warning(
            "compare summary LLM returned empty or degenerate content (%r) — using fallback",
            text[:120],
        )
    except Exception as exc:
        logger.warning("compare summary LLM failed — using fallback: %s", exc)
    return _fallback_comparison_summary(brief_a, brief_b)


def build_comparison(brief_a: ResearchBrief, brief_b: ResearchBrief) -> dict[str, Any]:
    metrics = build_metrics_table(brief_a, brief_b)
    summary = _llm_comparison_summary(brief_a, brief_b, metrics)
    summary, _log = rewrite_text(summary, "comparison_summary")
    return {"metrics_table": metrics, "comparison_summary": summary}
