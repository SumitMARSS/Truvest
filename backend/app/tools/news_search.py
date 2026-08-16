"""India-focused news search via Tavily (NSE / Moneycontrol / ET / Business Standard)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.core.config import settings
from app.core.ticker import bare_symbol

logger = logging.getLogger(__name__)

# Prefer Indian financial press
_INDIA_DOMAINS = [
    "moneycontrol.com",
    "economictimes.indiatimes.com",
    "business-standard.com",
    "livemint.com",
    "reuters.com",
    "nseindia.com",
    "bseindia.com",
]


def search_ticker_news(
    ticker: str,
    company_name: str | None = None,
    max_results: int = 8,
) -> list[dict[str, Any]]:
    """Search recent India equity news for the NSE/BSE ticker."""
    bare = bare_symbol(ticker)
    name = company_name or bare
    query = (
        f"{name} {bare} NSE share price OR quarterly results OR earnings India"
    )

    if not settings.tavily_api_key:
        logger.warning("TAVILY_API_KEY missing — returning stub India news")
        return [
            {
                "title": f"[STUB] India market coverage of {bare} — set TAVILY_API_KEY",
                "url": f"https://www.moneycontrol.com/india/stockpricequote/{bare}",
                "content": "Placeholder. Configure Tavily for live Indian market headlines.",
                "published_date": datetime.utcnow().isoformat(),
                "provider": "stub",
            }
        ]

    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=settings.tavily_api_key)
        # UPDATE: tighten time_range when Tavily plan supports it
        result = client.search(
            query=query,
            max_results=max_results,
            search_depth="basic",
            include_answer=False,
            include_domains=_INDIA_DOMAINS,
        )
        articles = []
        for item in result.get("results", []):
            articles.append(
                {
                    "title": item.get("title") or "",
                    "url": item.get("url"),
                    "content": item.get("content") or "",
                    "published_date": item.get("published_date"),
                    "provider": "tavily",
                    "score": item.get("score"),
                }
            )

        # If domain filter returned nothing, retry without filter (still India query)
        if not articles:
            result = client.search(
                query=query,
                max_results=max_results,
                search_depth="basic",
                include_answer=False,
            )
            for item in result.get("results", []):
                articles.append(
                    {
                        "title": item.get("title") or "",
                        "url": item.get("url"),
                        "content": item.get("content") or "",
                        "published_date": item.get("published_date"),
                        "provider": "tavily",
                        "score": item.get("score"),
                    }
                )
        return articles
    except Exception as exc:
        logger.exception("Tavily India search failed: %s", exc)
        return []
