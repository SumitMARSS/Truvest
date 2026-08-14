"""Specialized worker nodes."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from app.agents.state import AgentState
from app.core.config import settings
from app.services.llm import get_chat_model
from app.tools.code_exec import run_calculations
from app.tools.market_data import fetch_market_bundle
from app.tools.news_search import search_ticker_news
from app.tools.india_filings import fetch_latest_filings  # India: replaces SEC EDGAR

logger = logging.getLogger(__name__)


def market_worker(state: AgentState) -> dict[str, Any]:
    ticker = state["ticker"]
    bundle = fetch_market_bundle(ticker)
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
    ticker = state["ticker"]
    company = state.get("company_name")
    articles = search_ticker_news(ticker, company, max_results=settings.news_max_articles)

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
        sentiment, rationale, impact = sentiments.get(
            i, _heuristic_sentiment(art)
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


def calc_worker(state: AgentState) -> dict[str, Any]:
    market = state.get("market_data") or {}
    if not market:
        # Dependency: market must run first — planner should enforce on retry
        return {
            "calc_data": {"error": "market_data missing"},
            "completed_workers": ["calc"],
            "status_message": "calc_skipped",
        }

    calcs = run_calculations(market)
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
    counts = {k: labels.count(k) for k in ("bullish", "bearish", "neutral")}
    return max(counts, key=counts.get)
