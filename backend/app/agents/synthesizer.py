"""Synthesizer — draft structured brief with citation IDs on every claim."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from app.agents.state import AgentState
from app.core.text_quality import looks_like_prose
from app.core.ticker import exchange_of
from app.services.llm import get_chat_model

logger = logging.getLogger(__name__)


def _dedupe_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sources use operator.add across retries, so a worker retried after a
    critic failure appends a second copy of the same source id alongside the
    stale first attempt (docs/AUDIT.md #3.1). Keep the LAST occurrence per id
    — the most recently written value is the one that survived to the brief
    that's actually being assembled right now."""
    by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for s in sources:
        sid = s.get("id")
        if not sid:
            continue
        if sid not in by_id:
            order.append(sid)
        by_id[sid] = s
    return [by_id[sid] for sid in order]


def synthesizer_node(state: AgentState) -> dict[str, Any]:
    ticker = state["ticker"]
    company = state.get("company_name")
    market = state.get("market_data") or {}
    news = state.get("news_data") or {}
    filings = state.get("filings_data") or {}
    calcs = state.get("calc_data") or {}
    peers = state.get("peer_data") or {"available": False, "reason": "Peer comparison did not run.", "rows": []}
    shareholding = state.get("shareholding_data") or {
        "available": False,
        "reason": "Shareholding lookup did not run.",
    }
    sources = _dedupe_sources(state.get("sources") or [])

    price = market.get("price") or {}
    funds = market.get("fundamentals") or {}
    market_sid = f"src-market-{ticker}"
    calc_sid = f"src-calc-{ticker}"
    data_gaps: list[str] = []
    if market.get("unavailable"):
        data_gaps.append(
            "Market data (price, fundamentals) was unavailable this run — "
            + str(market.get("unavailable_reason") or "upstream data source did not respond.")
        )
    if not peers.get("available"):
        data_gaps.append(str(peers.get("reason") or "Peer comparison unavailable."))
    if not shareholding.get("available"):
        data_gaps.append(str(shareholding.get("reason") or "Shareholding data unavailable this cycle."))
    valuation = calcs.get("valuation") or {}
    pe_band = valuation.get("pe_band") or {}
    sector_pe = valuation.get("sector_pe") or {}
    if not pe_band.get("available"):
        data_gaps.append(str(pe_band.get("reason") or "Historical P/E band unavailable."))
    if not sector_pe.get("available"):
        data_gaps.append(str(sector_pe.get("reason") or "Sector-average P/E unavailable."))

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
        "valuation": {
            "pe_band": pe_band,
            "sector_pe": sector_pe,
            "source_ids": [calc_sid] if pe_band.get("available") or sector_pe.get("available") else [],
        },
        "peer_comparison": peers,
        "shareholding": shareholding,
        "sources": sources,
        "risks": _build_risks_with_shareholding(_build_risks(filings, calcs, news), shareholding),
        "analyst_summary": "",
        "data_gaps": data_gaps,
        "critic_passed": False,
        "critic_notes": [],
        "metadata": {
            "plan": state.get("plan") or [],
            "market": "IN",
            "exchange": exchange_of(str(ticker)),
            "market_unavailable": bool(market.get("unavailable")),
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


def _build_risks_with_shareholding(risks: list[dict[str, Any]], shareholding: dict[str, Any]) -> list[dict[str, Any]]:
    """A falling promoter stake is the single highest-signal shareholding
    number per spec 2.2 — surface it as a real risk flag, not just a stat."""
    if not shareholding.get("available"):
        return risks
    delta = shareholding.get("promoter_qoq_delta")
    if delta is not None and delta < 0:
        risks = [
            *risks,
            {
                "severity": "high" if delta <= -1.0 else "medium",
                "title": "Promoter stake declined QoQ",
                "detail": (
                    f"Promoter holding fell {abs(delta):.2f} percentage points "
                    f"quarter-over-quarter (as of {shareholding.get('as_of')})."
                ),
                "source_ids": [],
            },
        ]
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
        "valuation": draft.get("valuation"),
        "shareholding": draft.get("shareholding"),
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
        "or reasonable vs its own historical P/E band and vs its sector-average P/E, if present?\n"
        "3. News flow: the overall sentiment and the likely near-term vs long-term impact "
        "based on the per-article impact notes.\n"
        "4. Promoter shareholding trend, if present — a falling promoter stake is a caution "
        "flag worth naming explicitly.\n"
        "5. A clear one-line takeaway on near-future and far-future outlook.\n"
        "Rules: ONLY use facts from the JSON below. Mention the NSE/BSE ticker. Never invent "
        "numbers, never state a price target, and never use directive language like 'buy' or "
        "'sell' — describe historical patterns, not recommendations. If a data point is "
        "missing, skip it silently. End with a one-line risk caveat for Indian markets. "
        "Do not output JSON, headers, or markdown — prose only.\n\n"
        f"DATA:\n{json.dumps(compact, default=str)[:6000]}"
    )
    try:
        llm = get_chat_model(temperature=0.2)
        msg = llm.invoke(prompt)
        text = getattr(msg, "content", str(msg)).strip()
        if looks_like_prose(text):
            return text
        logger.warning(
            "summary LLM returned empty or degenerate content (%r) — using data-driven fallback",
            text[:120],
        )
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

    valuation = draft.get("valuation") or {}
    sector_pe = valuation.get("sector_pe") or {}
    if sector_pe.get("available") and funds.get("pe_ratio") is not None:
        parts.append(
            f"Sector average P/E ({sector_pe.get('sector')}) is {sector_pe['pe']:.1f} "
            f"as of {sector_pe.get('as_of')}, versus this stock's {funds['pe_ratio']:.1f}."
        )

    shareholding = draft.get("shareholding") or {}
    if shareholding.get("available"):
        delta = shareholding.get("promoter_qoq_delta")
        delta_bit = f" ({delta:+.2f} pts QoQ)" if delta is not None else ""
        parts.append(
            f"Promoter holding stood at {shareholding.get('promoter_pct')}% as of "
            f"{shareholding.get('as_of')}{delta_bit}."
        )

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
