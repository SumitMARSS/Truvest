"""Deterministic numeric calculations — agents compute YoY / SMAs instead of guessing."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def run_calculations(market_bundle: dict[str, Any]) -> dict[str, Any]:
    """Pure-Python calcs over market_bundle — no LLM."""
    price = (market_bundle.get("price") or {}).get("last_price")
    eps = (market_bundle.get("fundamentals") or {}).get("eps_ttm")
    closes: list[float] = market_bundle.get("close_prices") or []
    annual = market_bundle.get("annual_revenue") or []

    pe_from_price_eps = None
    if price is not None and eps not in (None, 0):
        pe_from_price_eps = round(float(price) / float(eps), 4)

    yoy = None
    if len(annual) >= 2:
        # annual_revenue is newest-first from yfinance financials columns
        newest = annual[0].get("revenue")
        older = annual[1].get("revenue")
        if newest and older and older != 0:
            yoy = round((float(newest) - float(older)) / float(older) * 100, 4)

    sma_20 = _sma(closes, 20)
    sma_50 = _sma(closes, 50)

    notes = []
    reported_pe = (market_bundle.get("fundamentals") or {}).get("pe_ratio")
    if pe_from_price_eps is not None and reported_pe is not None:
        drift = abs(float(reported_pe) - pe_from_price_eps)
        if drift > 1.0:
            notes.append(
                f"Reported P/E ({reported_pe}) differs from price/EPS ({pe_from_price_eps}) by {drift:.2f}"
            )

    return {
        "pe_from_price_eps": pe_from_price_eps,
        "yoy_revenue_growth": yoy,
        "sma_20": sma_20,
        "sma_50": sma_50,
        "notes": notes,
        "provider": "calc",
    }


def _sma(series: list[float], window: int) -> float | None:
    if len(series) < window or window <= 0:
        return None
    chunk = series[-window:]
    return round(sum(chunk) / window, 4)


# 8 quarters is the spec's own threshold for "enough history to call this a
# band rather than a guess" — below that we still compute what's available
# but the result is labeled partial, never silently presented as complete.
_MIN_QUARTERS_FOR_FULL_BAND = 8


def compute_pe_band(dates: list[str], closes: list[float], quarterly_eps: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Rolling trailing-twelve-month (TTM) P/E band from historical price x EPS
    — pure math, no LLM, no I/O (spec 2.1). `quarterly_eps` is newest-first
    (as returned by tools/market_data.py); `dates`/`closes` are oldest-first.

    Returns {"available": False, "reason": ...} if there isn't even one full
    4-quarter TTM window to compute — never fabricates a band from less.
    """
    if not quarterly_eps or not dates or not closes:
        return {"available": False, "reason": "Insufficient price or EPS history.", "series": []}

    n_quarters = len(quarterly_eps)
    eps_oldest_first = list(reversed(quarterly_eps))

    def nearest_close_on_or_before(target_date: str) -> float | None:
        for i in range(len(dates) - 1, -1, -1):
            if dates[i][:10] <= target_date[:10]:
                return closes[i]
        return closes[0] if closes else None

    series: list[dict[str, Any]] = []
    for i in range(3, len(eps_oldest_first)):
        window = eps_oldest_first[i - 3 : i + 1]
        if any(w.get("eps") is None for w in window):
            continue
        ttm_eps = sum(w["eps"] for w in window)
        if not ttm_eps:
            continue
        q_date = eps_oldest_first[i]["period"]
        price = nearest_close_on_or_before(q_date)
        if price is None:
            continue
        series.append({"date": q_date[:10], "pe": round(price / ttm_eps, 2)})

    if not series:
        return {
            "available": False,
            "reason": (
                f"Only {n_quarters} quarter(s) of EPS available — need at least 4 "
                "consecutive quarters to compute one TTM P/E point."
            ),
            "series": [],
        }

    pes = [p["pe"] for p in series]
    return {
        "available": True,
        "series": series,
        "band_min": round(min(pes), 2),
        "band_max": round(max(pes), 2),
        "band_avg": round(sum(pes) / len(pes), 2),
        "partial_history": n_quarters < _MIN_QUARTERS_FOR_FULL_BAND,
        "quarters_used": n_quarters,
    }
