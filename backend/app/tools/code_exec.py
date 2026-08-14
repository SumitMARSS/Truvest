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
