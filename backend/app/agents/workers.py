"""Specialized worker nodes."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from app.agents.state import AgentState
from app.core.config import settings
from app.core.dedup import cluster_articles
from app.core.ticker import bare_symbol, nse_quote_url
from app.services.llm import get_chat_model
from app.tools.code_exec import compute_pe_band, run_calculations
from app.tools.market_data import MarketDataUnavailable, fetch_market_bundle
from app.tools.news_rss import fetch_rss_news
from app.tools.news_search import search_ticker_news
from app.tools.india_filings import fetch_latest_filings  # India: replaces SEC EDGAR
from app.tools.peer_data import fetch_peer_comparison, sector_of
from app.tools.sector_pe import fetch_sector_pe
from app.tools.shareholding import fetch_shareholding

# Below this many independent corroborating sources, a directional sentiment
# label is not allowed to survive — spec 2.5's hard rule. Enforced here in
# code (not the LLM prompt) so it can't silently drift.
_MIN_SOURCES_FOR_DIRECTIONAL_SENTIMENT = 2

logger = logging.getLogger(__name__)


def market_worker(state: AgentState) -> dict[str, Any]:
    ticker = state["ticker"]
    try:
        bundle = fetch_market_bundle(ticker)
    except MarketDataUnavailable as exc:
        # Degrade honestly instead of crashing the whole job (docs/AUDIT.md
        # #1.1) — the brief still gets news/filings/calc sections, and the
        # UI shows "market data unavailable" rather than a blank failed job.
        logger.warning("market data unavailable for %s: %s", ticker, exc)
        return {
            "market_data": {
                "ticker": ticker,
                "unavailable": True,
                "unavailable_reason": str(exc),
                "price": {},
                "fundamentals": {},
                "close_prices": [],
                "dates": [],
                "annual_revenue": [],
                "nse_url": nse_quote_url(ticker),
            },
            "sources": [],
            "completed_workers": ["market"],
            "status_message": "market_unavailable",
        }

    source = {
        "id": f"src-market-{ticker}",
        "title": f"NSE/BSE market data for {ticker}",
        "url": bundle.get("nse_url") or bundle.get("url"),
        "retrieved_at": datetime.utcnow().isoformat(),
        "provider": bundle.get("provider") or "yfinance",
    }
    return {
        "market_data": bundle,
        "sources": [source],
        "completed_workers": ["market"],
        "status_message": "market_done",
    }


def news_worker(state: AgentState) -> dict[str, Any]:
    """
    RSS (Economic Times / Moneycontrol / Livemint / Business Standard) is
    the primary news source (spec 2.5) — structured, free, higher signal
    than generic web search. Tavily supplements it for freshness/coverage,
    not the other way around. Every article is clustered against the rest
    before sentiment is assigned, and a story with fewer than 2 independent
    outlets is barred from a directional (bullish/bearish) label — it comes
    back `insufficient_data` instead, never a confident-looking guess off
    one headline.
    """
    ticker = state["ticker"]
    company = state.get("company_name")
    bare = bare_symbol(ticker)

    rss_articles = fetch_rss_news(bare, company, max_results=settings.news_max_articles)
    tavily_articles = search_ticker_news(ticker, company, max_results=settings.news_max_articles)

    real_candidates = [a for a in (rss_articles + tavily_articles) if a.get("provider") != "stub"]
    clustered = cluster_articles(real_candidates) if real_candidates else []
    clustered.sort(key=lambda a: a.get("published_date") or "", reverse=True)
    articles = clustered[: settings.news_max_articles] or tavily_articles  # keep stub if nothing real came back

    # ONE batched LLM call for all articles; deterministic keyword fallback if
    # the LLM is unreachable so the brief never says "sentiment unavailable"
    sentiments = _classify_sentiment_batch(articles)

    classified = []
    sources = []
    for i, art in enumerate(articles):
        sid = f"src-news-{ticker}-{i}"
        sources.append(
            {
                "id": sid,
                "title": art.get("title") or f"News {i}",
                "url": art.get("url"),
                "retrieved_at": datetime.utcnow().isoformat(),
                "provider": art.get("provider") or "tavily",
            }
        )
        sentiment, rationale, impact = sentiments.get(i, _heuristic_sentiment(art))
        corroboration = int(art.get("corroboration_count") or 1)
        if sentiment in ("bullish", "bearish") and corroboration < _MIN_SOURCES_FOR_DIRECTIONAL_SENTIMENT:
            sentiment = "insufficient_data"
            rationale = (
                f"Only {corroboration} independent source reported this — "
                "a directional call needs at least 2 (spec 2.5 corroboration rule)."
            )
        classified.append(
            {
                "title": art.get("title"),
                "url": art.get("url"),
                "published": art.get("published_date"),
                "sentiment": sentiment,
                "rationale": rationale,
                "impact": impact,
                "source_ids": [sid],
                "corroboration_count": corroboration,
            }
        )

    overall = _majority_sentiment([c["sentiment"] for c in classified])
    return {
        "news_data": {"articles": classified, "overall_sentiment": overall},
        "sources": sources,
        "completed_workers": ["news"],
        "status_message": "news_done",
    }


def filings_worker(state: AgentState) -> dict[str, Any]:
    ticker = state["ticker"]
    filings = fetch_latest_filings(ticker)
    sources = []
    enriched = []
    for i, f in enumerate(filings):
        sid = f"src-filing-{ticker}-{i}"
        sources.append(
            {
                "id": sid,
                "title": f"{f.get('form')} {f.get('filed_at') or ''} — {ticker} (India)",
                "url": f.get("url"),
                "retrieved_at": datetime.utcnow().isoformat(),
                "provider": f.get("provider") or "india_filings",
            }
        )
        enriched.append({**f, "source_ids": [sid]})
    return {
        "filings_data": {"filings": enriched},
        "sources": sources,
        "completed_workers": ["filings"],
        "status_message": "filings_done",
    }


def peers_worker(state: AgentState) -> dict[str, Any]:
    """Sector peer comparison (spec 2.3) — reuses fetch_market_bundle/run_calculations
    across peers, so a bad peer degrades that one row, never the whole worker."""
    ticker = state["ticker"]
    try:
        comparison = fetch_peer_comparison(ticker)
    except Exception as exc:
        logger.warning("peer comparison worker failed for %s: %s", ticker, exc)
        comparison = {"available": False, "reason": f"Peer comparison failed: {exc}", "rows": []}
    return {
        "peer_data": comparison,
        "completed_workers": ["peers"],
        "status_message": "peers_done",
    }


def shareholding_worker(state: AgentState) -> dict[str, Any]:
    """Promoter shareholding % + QoQ delta (spec 2.2). Wrapped defensively —
    an NSE endpoint outage must render as an honest 'unavailable' section,
    never retry-loop the whole brief or crash the job."""
    ticker = state["ticker"]
    try:
        holding = fetch_shareholding(ticker)
    except Exception as exc:
        logger.warning("shareholding worker failed for %s: %s", ticker, exc)
        holding = {"available": False, "reason": f"Shareholding lookup failed: {exc}"}
    return {
        "shareholding_data": holding,
        "completed_workers": ["shareholding"],
        "status_message": "shareholding_done",
    }


def calc_worker(state: AgentState) -> dict[str, Any]:
    market = state.get("market_data") or {}
    if not market or market.get("unavailable"):
        # Dependency: market must run first — planner should enforce on retry
        return {
            "calc_data": {"error": "market_data missing"},
            "completed_workers": ["calc"],
            "status_message": "calc_skipped",
        }

    calcs = run_calculations(market)

    # Valuation context (spec 2.1): P/E band is pure math over data already
    # fetched by market_worker; sector P/E is a small cached I/O call kept
    # inside calc rather than spun into its own LLM-calling worker, per the
    # "extend calc, don't add a new worker for pure computation" principle.
    ticker = state["ticker"]
    try:
        pe_band = compute_pe_band(
            market.get("dates") or [], market.get("close_prices") or [], market.get("quarterly_eps") or []
        )
    except Exception as exc:
        logger.warning("pe band computation failed for %s: %s", ticker, exc)
        pe_band = {"available": False, "reason": f"P/E band computation failed: {exc}"}

    sector = sector_of(ticker)
    try:
        sector_pe = fetch_sector_pe(sector)
    except Exception as exc:
        logger.warning("sector P/E fetch failed for %s: %s", ticker, exc)
        sector_pe = {"available": False, "reason": f"Sector P/E lookup failed: {exc}"}

    calcs["valuation"] = {"pe_band": pe_band, "sector_pe": sector_pe}

    source = {
        "id": f"src-calc-{state['ticker']}",
        "title": f"Derived calculations for {state['ticker']}",
        "url": None,
        "retrieved_at": datetime.utcnow().isoformat(),
        "provider": "calc",
    }
    return {
        "calc_data": {**calcs, "source_ids": [source["id"]]},
        "sources": [source],
        "completed_workers": ["calc"],
        "status_message": "calc_done",
    }


SentimentResult = tuple[str, str, str]  # (sentiment, rationale, impact)

_BULLISH_WORDS = (
    "surge", "surges", "jump", "jumps", "rally", "rallies", "beats", "beat estimates",
    "record", "profit rises", "profit up", "gains", "upgrade", "buy rating", "strong",
    "growth", "wins", "order win", "expansion", "dividend", "bonus", "all-time high",
    "raises guidance", "outperform",
)
_BEARISH_WORDS = (
    "fall", "falls", "drop", "drops", "decline", "declines", "loss", "losses",
    "plunge", "plunges", "slump", "downgrade", "probe", "fraud", "penalty", "weak",
    "cuts guidance", "misses", "miss estimates", "lawsuit", "recall", "strike",
    "debt concerns", "sell rating", "underperform", "52-week low",
)


def _heuristic_sentiment(article: dict[str, Any]) -> SentimentResult:
    """Deterministic fallback when the LLM can't be reached — reads the headline
    and content for directional keywords instead of reporting 'unavailable'."""
    text = f"{article.get('title') or ''} {article.get('content') or ''}".lower()
    bull = [w for w in _BULLISH_WORDS if w in text]
    bear = [w for w in _BEARISH_WORDS if w in text]

    if len(bull) > len(bear):
        return (
            "bullish",
            f"Headline signals strength ({', '.join(bull[:3])}).",
            "Likely positive for the stock in the near term.",
        )
    if len(bear) > len(bull):
        return (
            "bearish",
            f"Headline signals weakness ({', '.join(bear[:3])}).",
            "Likely negative pressure on the stock in the near term.",
        )
    return (
        "neutral",
        "Routine coverage (results announcements / factual reporting) with no clear directional signal.",
        "Limited near-term price impact expected; useful for tracking fundamentals.",
    )


def _classify_sentiment_batch(articles: list[dict[str, Any]]) -> dict[int, SentimentResult]:
    """
    Classify ALL articles in a single LLM call.
    Returns {article_index: (sentiment, rationale, impact)}.
    Missing indexes fall back to keyword heuristics in the caller.
    """
    results: dict[int, SentimentResult] = {}
    real = [
        (i, a) for i, a in enumerate(articles)
        if a.get("provider") != "stub" and (a.get("title") or a.get("content"))
    ]
    for i, a in enumerate(articles):
        if a.get("provider") == "stub":
            results[i] = (
                "neutral",
                "Stub article — configure TAVILY_API_KEY for live sentiment.",
                "No impact — placeholder item.",
            )

    if not real:
        return results

    items = "\n".join(
        f'{i}. Title: {a.get("title") or ""} | Content: {(a.get("content") or "")[:300]}'
        for i, a in real
    )
    prompt = (
        "You are an Indian equity analyst. For each numbered news item about an "
        "NSE/BSE-listed stock, judge:\n"
        "- sentiment: bullish, bearish, or neutral for the stock\n"
        "- rationale: one short sentence explaining why\n"
        "- impact: whether it should affect the stock positively or negatively, "
        "and whether in the near future (days-weeks) or far future (quarters-years). "
        'Example: "Positive in the near term as results beat estimates."\n'
        "Respond ONLY with a JSON array, no other text:\n"
        '[{"index": 0, "sentiment": "bullish", "rationale": "...", "impact": "..."}]\n\n'
        f"{items}"
    )
    try:
        llm = get_chat_model(temperature=0)
        msg = llm.invoke(prompt)
        text = getattr(msg, "content", str(msg))
        for row in _safe_json_list(text):
            idx = row.get("index")
            sentiment = str(row.get("sentiment", "neutral")).lower()
            if sentiment not in {"bullish", "bearish", "neutral"}:
                sentiment = "neutral"
            if isinstance(idx, int):
                results[idx] = (
                    sentiment,
                    str(row.get("rationale") or ""),
                    str(row.get("impact") or ""),
                )
    except Exception as exc:
        logger.warning("batch sentiment LLM failed, using keyword heuristics: %s", exc)

    return results


def _safe_json_list(text: str) -> list[dict[str, Any]]:
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end > start:
        text = text[start : end + 1]
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else []
    except Exception:
        logger.debug("could not parse sentiment JSON: %s", text[:200])
        return []


def _majority_sentiment(labels: list[str]) -> str:
    if not labels:
        return "neutral"
    counts = {k: labels.count(k) for k in ("bullish", "bearish", "neutral", "insufficient_data")}
    return max(counts, key=counts.get)
