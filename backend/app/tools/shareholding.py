"""
Promoter shareholding pattern + QoQ delta — spec 2.2.

Confirmed live during this pass (not assumed): `yfinance.Ticker(...).institutional_holders`
returns an **empty** DataFrame for NSE tickers (checked against RELIANCE.NS),
and `.major_holders` returns a generic "insiders/institutions percent held"
breakdown that doesn't match NSE's disclosed promoter % and isn't sourced
from SEBI shareholding-pattern filings at all — Yahoo's ownership data comes
from US SEC 13F filings, which don't cover NSE/BSE-listed companies. So
yfinance is structurally the wrong source for this and was correctly never
the plan; this comment is the guard the spec asked for instead of just
assuming it.

Real source: NSE's own shareholding-pattern disclosure endpoint, reached via
`nsepython`. A bare `requests.get`/`curl` to nseindia.com from this sandbox
returns nothing (NSE's WAF blocks generic clients) — nsepython's `nsefetch`
succeeds because it replays a real browser session (headers + cookie
handshake). Confirmed live for RELIANCE/TCS/INFY during this pass; an
unresolvable symbol returns an empty list, which is the "unavailable" path.

v1 scope (per spec): promoter holding % + QoQ delta only — the single
highest-signal, most reliably scrapable number. FII/DII is deferred to v2
(separate, noisier, monthly NSDL depository data).

Isolation: this module is the ONLY place that imports nsepython or knows the
NSE endpoint shape. Swapping to a licensed data vendor later means rewriting
this file, not touching workers.py/graph.py/synthesizer.py.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.core.ticker import bare_symbol
from app.services.cache import cache_get_sync, cache_set_sync

logger = logging.getLogger(__name__)

_CACHE_NAMESPACE = "shareholding"
# Updates ~4x/year — a week of staleness is invisible next to that cadence,
# and `as_of` is always shown in the UI so staleness is never hidden.
_CACHE_TTL_SECONDS = 60 * 60 * 24 * 7
_ENDPOINT = "https://www.nseindia.com/api/corporate-share-holdings-master?index=equities&symbol={symbol}"


class ShareholdingUnavailable(RuntimeError):
    """Always caught by shareholding_worker — never propagates."""


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fetch_live_rows(symbol: str) -> list[dict[str, Any]]:
    try:
        import nsepython
    except ImportError as exc:
        raise ShareholdingUnavailable(f"nsepython not installed: {exc}") from exc

    try:
        rows = nsepython.nsefetch(_ENDPOINT.format(symbol=symbol))
    except Exception as exc:
        raise ShareholdingUnavailable(f"NSE shareholding endpoint failed for {symbol}: {exc}") from exc

    if not rows:
        raise ShareholdingUnavailable(f"NSE returned no shareholding disclosures for {symbol}")
    return rows


def fetch_shareholding(ticker: str) -> dict[str, Any]:
    """
    Returns one of:
      {"available": False, "reason": "..."}
      {"available": True, "as_of": "30-JUN-2026", "promoter_pct": 50.48,
       "promoter_qoq_delta": -0.4, "prior_quarter_date": "31-MAR-2026",
       "public_pct": 49.52, "provider": "nse_shareholding", "quarters_available": 22}
    Never raises.
    """
    symbol = bare_symbol(ticker).upper()

    cached = cache_get_sync(_CACHE_NAMESPACE, symbol)
    if cached is not None:
        return {**cached, "from_cache": True}

    try:
        rows = _fetch_live_rows(symbol)
    except ShareholdingUnavailable as exc:
        logger.info("shareholding unavailable for %s: %s", symbol, exc)
        return {"available": False, "reason": str(exc)}

    # NSE returns rows newest-first, one per disclosed quarter.
    latest, prior = rows[0], (rows[1] if len(rows) > 1 else None)
    latest_pct = _as_float(latest.get("pr_and_prgrp"))
    prior_pct = _as_float(prior.get("pr_and_prgrp")) if prior else None
    delta = round(latest_pct - prior_pct, 2) if latest_pct is not None and prior_pct is not None else None

    result: dict[str, Any] = {
        "available": True,
        "as_of": latest.get("date"),
        "promoter_pct": latest_pct,
        "promoter_qoq_delta": delta,
        "prior_quarter_date": prior.get("date") if prior else None,
        "public_pct": _as_float(latest.get("public_val")),
        "provider": "nse_shareholding",
        "quarters_available": len(rows),
    }
    cache_set_sync(_CACHE_NAMESPACE, symbol, result, _CACHE_TTL_SECONDS)
    return result
