"""Synthesizer — draft structured brief with citation IDs on every claim."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from app.agents.state import AgentState
from app.services.llm import get_chat_model

logger = logging.getLogger(__name__)


def synthesizer_node(state: AgentState) -> dict[str, Any]:
    ticker = state["ticker"]
    company = state.get("company_name")
    market = state.get("market_data") or {}
    news = state.get("news_data") or {}
    filings = state.get("filings_data") or {}
    calcs = state.get("calc_data") or {}
    sources = state.get("sources") or []

    price = market.get("price") or {}
    funds = market.get("fundamentals") or {}
    market_sid = f"src-market-{ticker}"
    calc_sid = f"src-calc-{ticker}"

    draft: dict[str, Any] = {
        "ticker": ticker,
        "company_name": company,
        "as_of": datetime.utcnow().isoformat(),
        "price_action": {
            **price,
            "source_ids": [market_sid],
        },
        "price_history": _downsample_history(
            market.get("dates") or [], market.get("close_prices") or []
        ),
        "fundamentals": {
            "market_cap": funds.get("market_cap"),
            "pe_ratio": funds.get("pe_ratio"),
            "eps_ttm": funds.get("eps_ttm"),
            "revenue_ttm": funds.get("revenue_ttm"),
            "profit_margin": funds.get("profit_margin"),
            "source_ids": [market_sid],
        },
        "news": news.get("articles") or [],
        "overall_news_sentiment": news.get("overall_sentiment"),
        "filings": filings.get("filings") or [],
        "calculations": {
            "pe_from_price_eps": calcs.get("pe_from_price_eps"),
            "yoy_revenue_growth": calcs.get("yoy_revenue_growth"),
            "sma_20": calcs.get("sma_20"),
            "sma_50": calcs.get("sma_50"),
            "notes": calcs.get("notes") or [],
            "source_ids": calcs.get("source_ids") or [calc_sid],
        },
        "sources": sources,
        "risks": _build_risks(filings, calcs, news),
        "analyst_summary": "",
        "critic_passed": False,
        "critic_notes": [],
        "metadata": {
            "plan": state.get("plan") or [],
            "market": "IN",
            "exchange": "BSE" if str(ticker).upper().endswith(".BO") else "NSE",
        },
    }

    draft["analyst_summary"] = _llm_summary(draft)
    return {"draft_brief": draft, "status_message": "synthesized"}


def _downsample_history(
    dates: list[str], closes: list[float], max_points: int = 240
) -> list[dict[str, Any]]:
    """Thin 3y of daily closes to <=240 points for the frontend chart."""
    n = min(len(dates), len(closes))
    if n == 0:
        return []
    step = max(1, n // max_points)
    points = [
        {"date": dates[i][:10], "close": round(closes[i], 2)}
        for i in range(0, n, step)
    ]
    # Always include the latest close so the chart ends at the current price
    if points and points[-1]["date"] != dates[n - 1][:10]:
        points.append({"date": dates[n - 1][:10], "close": round(closes[n - 1], 2)})
    return points


def _build_risks(filings: dict, calcs: dict, news: dict) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    for f in filings.get("filings") or []:
        for rf in (f.get("risk_factors") or [])[:3]:
            risks.append(
                {
                    "severity": "medium",
                    "title": f"Filing risk ({f.get('form')})",
                    "detail": rf,
                    "source_ids": f.get("source_ids") or [],
                }
            )
    for note in calcs.get("notes") or []:
        risks.append(
            {
                "severity": "low",
                "title": "Metric consistency",
                "detail": note,
                "source_ids": calcs.get("source_ids") or [],
            }
        )
    if news.get("overall_sentiment") == "bearish":
        risks.append(
            {
                "severity": "medium",
                "title": "Bearish news tone",
                "detail": "Majority of recent articles classified bearish.",
                "source_ids": [],
            }
        )
    return risks


def _llm_summary(draft: dict[str, Any]) -> str:
    """
    Analyst-style paragraph. Must only use provided facts.
    Falls back to a deterministic data-driven summary — never leaks error text
    into the user-facing brief.
    """
    compact = {
        "ticker": draft["ticker"],
        "company_name": draft.get("company_name"),
        "price_action": draft.get("price_action"),
        "fundamentals": draft.get("fundamentals"),
        "calculations": draft.get("calculations"),
        "overall_news_sentiment": draft.get("overall_news_sentiment"),
        "news": [
            {"title": n.get("title"), "sentiment": n.get("sentiment"), "impact": n.get("impact")}
            for n in (draft.get("news") or [])[:5]
        ],
        "risk_titles": [r.get("title") for r in (draft.get("risks") or [])[:5]],
    }
    prompt = (
        "You are an India equity research associate covering NSE/BSE stocks.\n"
        "Write an analyst-style summary (6-9 sentences, plain prose, INR terms) covering:\n"
        "1. Recent performance across horizons (1W/1M/3M/6M/1Y/3Y % changes where present) "
        "and what the trend suggests.\n"
        "2. Valuation and fundamentals (P/E, EPS, margin, revenue growth) — is it expensive "
        "or reasonable vs its own numbers?\n"
        "3. News flow: the overall sentiment and the likely near-term vs long-term impact "
        "based on the per-article impact notes.\n"
        "4. A clear one-line takeaway on near-future and far-future outlook.\n"
        "Rules: ONLY use facts from the JSON below. Mention the NSE/BSE ticker. Never invent "
        "numbers. If a data point is missing, skip it silently. End with a one-line risk "
        "caveat for Indian markets. Do not output JSON, headers, or markdown — prose only.\n\n"
        f"DATA:\n{json.dumps(compact, default=str)[:6000]}"
    )
    try:
        llm = get_chat_model(temperature=0.2)
        msg = llm.invoke(prompt)
        text = getattr(msg, "content", str(msg)).strip()
        if text:
            return text
        logger.warning("summary LLM returned empty content — using data-driven fallback")
    except Exception as exc:
        logger.warning("summary LLM failed — using data-driven fallback: %s", exc)
    return _fallback_summary(draft)


def _fallback_summary(draft: dict[str, Any]) -> str:
    """Readable summary composed purely from fetched data (no LLM, no error text)."""
    ticker = draft["ticker"]
    name = draft.get("company_name") or ticker
    pa = draft.get("price_action") or {}
    funds = draft.get("fundamentals") or {}
    calcs = draft.get("calculations") or {}

    parts: list[str] = []
    if pa.get("last_price") is not None:
        parts.append(f"{name} ({ticker}) last traded at ₹{pa['last_price']:,.2f}.")

    horizons = [
        ("1 week", pa.get("change_1w_pct")),
        ("1 month", pa.get("change_1m_pct")),
        ("3 months", pa.get("change_3m_pct")),
        ("6 months", pa.get("change_6m_pct")),
        ("1 year", pa.get("change_1y_pct")),
        ("3 years", pa.get("change_3y_pct")),
    ]
    moves = [f"{label}: {v:+.1f}%" for label, v in horizons if v is not None]
    if moves:
        parts.append("Performance — " + ", ".join(moves) + ".")

    if funds.get("pe_ratio") is not None:
        pe_bit = f"The stock trades at a P/E of {funds['pe_ratio']:.1f}"
        if funds.get("eps_ttm") is not None:
            pe_bit += f" on trailing EPS of ₹{funds['eps_ttm']:.2f}"
        parts.append(pe_bit + ".")
    if calcs.get("yoy_revenue_growth") is not None:
        parts.append(f"Revenue grew {calcs['yoy_revenue_growth']:+.1f}% year over year.")

    sentiment = draft.get("overall_news_sentiment")
    if sentiment:
        parts.append(f"Recent news flow is {sentiment} on balance.")

    sma20, sma50, last = calcs.get("sma_20"), calcs.get("sma_50"), pa.get("last_price")
    if sma20 and sma50 and last:
        trend = "above" if last > sma20 and last > sma50 else "below" if last < sma20 and last < sma50 else "around"
        parts.append(f"Price is trading {trend} its 20-day and 50-day averages.")

    parts.append(
        "Caveat: Indian equities carry market, currency, and regulatory risk — verify with the cited sources."
    )
    return " ".join(parts)
