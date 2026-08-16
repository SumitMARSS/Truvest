"""
Confidence scoring — rule-based, zero external dependencies, zero LLM calls.

Why this exists: a brief that states "P/E is 24.3" and a brief that states
"sentiment is bullish based on one blog post" look identical in the UI today
(both just... claims). Confidence tagging makes the difference visible so a
user can tell "verified exchange data" from "one unconfirmed headline" at a
glance — this is a trust feature, not a data feature, which is exactly why
it has no external dependency and can be fully unit tested.

Rule set (spec'd, not invented per-case, so it's auditable):
  exchange_data      (yfinance price/fundamentals, calc-derived metrics) -> HIGH
  filing_extract     structured/cleanly-parsed filing                    -> HIGH
  filing_extract     partial/fallback-parsed filing                      -> MEDIUM
  news, 2+ independent corroborating sources                             -> MEDIUM
  news, single source                                                    -> LOW
  no real data (stub/placeholder)                                        -> LOW
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class Confidence(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


# Providers that represent a direct structured pull from the exchange/data
# vendor (as opposed to a scraped snippet or an LLM-adjacent guess).
_EXCHANGE_PROVIDERS = {"yfinance", "alpha_vantage", "calc"}
_STUB_PROVIDERS = {"stub", "N/A", "ERROR", "india_filings"}


def score_exchange_data(provider: str | None) -> tuple[Confidence, str]:
    if provider in _STUB_PROVIDERS:
        return Confidence.low, "No live data returned — placeholder only."
    return Confidence.high, f"Direct pull from {provider or 'exchange data provider'}."


def score_filing(provider: str | None, cleanly_parsed: bool) -> tuple[Confidence, str]:
    if provider in _STUB_PROVIDERS or provider is None:
        return Confidence.low, "No real filing content — placeholder only."
    if cleanly_parsed:
        return Confidence.high, "Structured filing data, cleanly parsed."
    return Confidence.medium, "Filing content available but only partially/fallback-parsed."


def score_news(source_count: int, is_stub: bool = False) -> tuple[Confidence, str]:
    if is_stub:
        return Confidence.low, "No live articles — placeholder only."
    if source_count >= 2:
        return Confidence.medium, f"Corroborated by {source_count} independent sources."
    return Confidence.low, "Single-source claim — not independently corroborated."


def annotate_claim(block: dict[str, Any], confidence: Confidence, reason: str) -> dict[str, Any]:
    """Return a shallow copy of a claim block with confidence fields set —
    never mutate the input in place, callers may reuse the source dict."""
    return {**block, "confidence": confidence.value, "confidence_reason": reason}


def apply_confidence(draft: dict[str, Any]) -> dict[str, Any]:
    """Tag every claim-bearing block in a draft brief with a confidence
    level. Pure function: same input always produces the same output, no
    I/O, no LLM. Safe to call on every critic pass (idempotent)."""
    out = dict(draft)
    market_unavailable = bool((draft.get("metadata") or {}).get("market_unavailable"))

    price_action = draft.get("price_action") or {}
    if market_unavailable:
        out["price_action"] = {**price_action, "confidence": None, "confidence_reason": "Market data unavailable this run."}
        out["fundamentals"] = {
            **(draft.get("fundamentals") or {}),
            "confidence": None,
            "confidence_reason": "Market data unavailable this run.",
        }
    else:
        c, r = score_exchange_data("yfinance")
        out["price_action"] = annotate_claim(price_action, c, r)
        out["fundamentals"] = annotate_claim(draft.get("fundamentals") or {}, c, r)

    calc_c, calc_r = score_exchange_data("calc")
    out["calculations"] = annotate_claim(draft.get("calculations") or {}, calc_c, calc_r)

    filings_out = []
    for f in draft.get("filings") or []:
        provider = f.get("provider")
        cleanly_parsed = provider == "yfinance" or bool(f.get("mda_highlights")) and provider not in _STUB_PROVIDERS
        c, r = score_filing(provider, cleanly_parsed)
        filings_out.append(annotate_claim(f, c, r))
    out["filings"] = filings_out

    news_out = []
    for n in draft.get("news") or []:
        is_stub = (n.get("title") or "").startswith("[STUB]")
        source_count = int(n.get("corroboration_count") or 1)
        c, r = score_news(source_count, is_stub=is_stub)
        news_out.append(annotate_claim(n, c, r))
    out["news"] = news_out

    risks_out = []
    for risk in draft.get("risks") or []:
        # Risks inherit the confidence of the block they were derived from;
        # default to medium (a flagged risk without a clear source lineage
        # shouldn't silently read as "high confidence").
        c = Confidence.medium
        r = "Derived risk flag."
        title = (risk.get("title") or "").lower()
        if "filing" in title:
            c, r = score_filing(None, False)  # conservative: treat as medium unless proven clean
            c = Confidence.medium
        elif "news" in title or "sentiment" in title:
            c, r = Confidence.low, "Derived from news sentiment, not independently corroborated."
        elif "metric consistency" in title:
            c, r = score_exchange_data("calc")
        risks_out.append(annotate_claim(risk, c, r))
    out["risks"] = risks_out

    return out
