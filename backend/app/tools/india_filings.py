"""
Indian corporate filings / results highlights.

SEC EDGAR does not cover Indian companies. This worker gathers:
  1) Latest results / annual report snippets via Tavily (Moneycontrol, NSE, company IR)
  2) Light fundamentals context from yfinance calendar when available

UPDATE: plug NSE corporate-announcements API or BSE XBRL feeds for production.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any

import yfinance as yf

from app.core.config import settings
from app.core.ticker import bare_symbol, nse_quote_url

logger = logging.getLogger(__name__)

# Scraped pages carry markdown headers, nav menus, and ticker-tape junk
_NOISE = re.compile(r"#{1,6}|\[\.\.\.\]|\|")
_WS = re.compile(r"\s+")
_MENU_HINTS = (
    "sign up", "invest now", "add to followers", "open trading a/c",
    "global markets indian indices", "stock scanner", "newspaper clippings",
)


def _clean_snippets(content: str, max_items: int = 3, max_len: int = 240) -> list[str]:
    """Turn scraped page text into short readable bullets, dropping nav junk."""
    text = _WS.sub(" ", _NOISE.sub(" ", content or "")).strip()
    out: list[str] = []
    for raw in text.split(". "):
        s = raw.strip(" .•·-")
        if len(s) < 40:
            continue
        low = s.lower()
        if any(h in low for h in _MENU_HINTS):
            continue
        # Skip ticker-tape fragments (mostly digits/punctuation)
        letters = sum(c.isalpha() for c in s)
        if letters < len(s) * 0.55:
            continue
        if len(s) > max_len:
            s = s[: max_len - 1].rsplit(" ", 1)[0] + "…"
        if s not in out:
            out.append(s + ("." if not s.endswith((".", "…")) else ""))
        if len(out) >= max_items:
            break
    return out


def _fmt_earnings_date(value: Any) -> str:
    """yfinance calendar returns lists of datetime.date — render them readably."""
    if isinstance(value, (list, tuple)):
        return " – ".join(_fmt_earnings_date(v) for v in value if v)
    if isinstance(value, (date, datetime)):
        return value.strftime("%d %b %Y")
    return str(value or "")


def fetch_latest_filings(ticker: str, limit: int = 2) -> list[dict[str, Any]]:
    bare = bare_symbol(ticker)
    company_bits: list[dict[str, Any]] = []

    # Earnings / calendar hints from Yahoo (often sparse for India)
    try:
        t = yf.Ticker(ticker)
        cal = getattr(t, "calendar", None) or {}
        if isinstance(cal, dict) and cal:
            earnings_date = _fmt_earnings_date(cal.get("Earnings Date") or cal.get("earningsDate"))
            highlights = []
            if earnings_date:
                highlights.append(f"Next earnings date: {earnings_date}")
            ex_div = cal.get("Ex-Dividend Date") or cal.get("exDividendDate")
            if ex_div:
                highlights.append(f"Ex-dividend date: {_fmt_earnings_date(ex_div)}")
            company_bits.append(
                {
                    "form": "EARNINGS_CALENDAR",
                    "filed_at": earnings_date or None,
                    "accession": None,
                    "url": f"https://finance.yahoo.com/quote/{ticker}",
                    "risk_factors": [],
                    "mda_highlights": highlights or ["Earnings calendar available on Yahoo Finance."],
                    "retrieved_at": datetime.utcnow().isoformat(),
                    "provider": "yfinance",
                }
            )
    except Exception as exc:
        logger.debug("yfinance calendar unavailable: %s", exc)

    # India results / annual report via Tavily
    company_bits.extend(_tavily_india_filings(bare, ticker, limit=limit))

    if not company_bits:
        return [
            {
                "form": "N/A",
                "note": (
                    f"No India filings found for {bare}. "
                    "UPDATE: wire NSE corporate announcements API."
                ),
                "risk_factors": [],
                "mda_highlights": [],
                "retrieved_at": datetime.utcnow().isoformat(),
                "provider": "india_filings",
            }
        ]
    return company_bits[: max(limit, 1) + 1]


def _tavily_india_filings(bare: str, ticker: str, limit: int = 2) -> list[dict[str, Any]]:
    if not settings.tavily_api_key:
        return [
            {
                "form": "RESULTS_STUB",
                "filed_at": None,
                "url": nse_quote_url(ticker),
                "risk_factors": [
                    "Configure TAVILY_API_KEY to pull latest quarterly results / annual report text."
                ],
                "mda_highlights": [
                    "Indian companies file with MCA / exchange — not SEC EDGAR."
                ],
                "retrieved_at": datetime.utcnow().isoformat(),
                "provider": "stub",
            }
        ]

    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=settings.tavily_api_key)
        query = (
            f"{bare} NSE quarterly results OR annual report OR board meeting "
            f"OR financial results India {ticker}"
        )
        result = client.search(
            query=query,
            max_results=max(limit, 3),
            search_depth="basic",
            include_answer=False,
            include_domains=[
                "moneycontrol.com",
                "economictimes.indiatimes.com",
                "nseindia.com",
                "bseindia.com",
                "business-standard.com",
            ],
        )
        out: list[dict[str, Any]] = []
        # Tavily frequently returns two different URLs whose scraped text is
        # the same exchange disclosure — without this the brief renders the
        # identical filing twice and derives duplicate risk flags from it
        # (observed live for RELIANCE during the Phase 3 UI verification).
        seen_snippets: set[str] = set()
        for item in result.get("results", [])[:limit]:
            snippets = _clean_snippets(item.get("content") or "", max_items=4)
            if not snippets:
                continue
            fingerprint = snippets[0][:120].lower()
            if fingerprint in seen_snippets:
                continue
            seen_snippets.add(fingerprint)
            out.append(
                {
                    "form": "INDIA_RESULTS",
                    "filed_at": item.get("published_date"),
                    "accession": None,
                    "url": item.get("url"),
                    "risk_factors": snippets[:2],
                    "mda_highlights": snippets[2:] or snippets[:1],
                    "retrieved_at": datetime.utcnow().isoformat(),
                    "provider": "tavily_india",
                    "title": item.get("title"),
                }
            )
        return out
    except Exception as exc:
        logger.exception("India filings search failed: %s", exc)
        return [{"form": "ERROR", "note": str(exc), "provider": "tavily_india", "risk_factors": [], "mda_highlights": []}]
