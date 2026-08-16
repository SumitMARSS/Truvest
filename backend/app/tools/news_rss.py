"""
RSS news feeds — spec 2.5. Primary news source; Tavily becomes a secondary
freshness/coverage supplement (wired in agents/workers.py:news_worker).

Why RSS-first: these are free, no API key, structured (title/summary/
timestamp/link) feeds straight from India's major financial press — far
higher signal-to-noise than generic web search snippets, and pulling from
them doesn't burn Tavily's metered search quota on every request.

NewsAPI.org/GNews were deliberately not integrated — weak Indian financial-
press coverage on their free tiers, not worth the integration cost for this
project (spec 2.5).

Each feed is fetched independently and defensively — one feed being down
(confirmed live: Business Standard 403s without a browser User-Agent, which
is why one is set below) must never take down news_worker; it just
contributes zero articles from that outlet.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Optional

import feedparser
import httpx

logger = logging.getLogger(__name__)

_FEEDS: list[dict[str, str]] = [
    {"name": "Economic Times Markets", "url": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"},
    {"name": "Moneycontrol", "url": "https://www.moneycontrol.com/rss/business.xml"},
    {"name": "Livemint Markets", "url": "https://www.livemint.com/rss/markets"},
    {"name": "Business Standard Markets", "url": "https://www.business-standard.com/rss/markets-106.rss"},
]

# A default httpx/urllib UA gets 403'd by at least one of these feeds
# (confirmed live) — a browser-shaped UA is enough to pass.
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
_TIMEOUT_SECONDS = 10.0


def _parse_entry_date(entry: Any) -> Optional[str]:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            try:
                return datetime(*t[:6]).isoformat()
            except Exception:
                continue
    return entry.get("published") or entry.get("updated")


def _fetch_one_feed(feed: dict[str, str]) -> list[dict[str, Any]]:
    try:
        resp = httpx.get(
            feed["url"], headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT_SECONDS, follow_redirects=True
        )
        resp.raise_for_status()
    except Exception as exc:
        logger.info("RSS feed unreachable (%s): %s", feed["name"], exc)
        return []

    try:
        parsed = feedparser.parse(resp.content)
    except Exception as exc:
        logger.info("RSS feed failed to parse (%s): %s", feed["name"], exc)
        return []

    return [
        {
            "title": entry.get("title") or "",
            "url": entry.get("link"),
            "content": entry.get("summary") or "",
            "published_date": _parse_entry_date(entry),
            "provider": "rss",
            "source_name": feed["name"],
        }
        for entry in parsed.entries
    ]


def _mentions_company(article: dict[str, Any], keywords: list[str]) -> bool:
    text = f"{article.get('title') or ''} {article.get('content') or ''}".lower()
    return any(kw.lower() in text for kw in keywords if kw)


def fetch_rss_news(
    bare_symbol_str: str, company_name: Optional[str], max_results: int = 10
) -> list[dict[str, Any]]:
    """
    Pull recent India financial-press RSS entries mentioning this company,
    across all configured feeds, fetched concurrently. Never raises — a
    feed outage (or all of them) just contributes zero articles.
    """
    keywords = [k for k in {bare_symbol_str, company_name} if k]
    if not keywords:
        return []

    matched: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=len(_FEEDS)) as pool:
        futures = {pool.submit(_fetch_one_feed, feed): feed for feed in _FEEDS}
        for fut in as_completed(futures):
            feed = futures[fut]
            try:
                entries = fut.result()
            except Exception as exc:
                logger.info("RSS feed raised (%s): %s", feed["name"], exc)
                continue
            matched.extend(a for a in entries if _mentions_company(a, keywords))

    return matched[: max_results * 3]  # generous pre-dedup pool; caller dedupes/clusters
