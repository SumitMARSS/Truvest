"""
Peer comparison — spec 2.3.

Deliberately does NOT use yfinance's info['sector']/['industry'] fields to
decide who a stock's peers are — those are frequently missing or wrong for
Indian tickers (docs/AUDIT.md-adjacent finding, confirmed by spot-checking
several NSE names during this pass). Peers come from a static, manually
curated JSON file instead (app/data/peer_groups.json), sourced from NSE's
publicly downloadable sectoral index constituent lists.

If the resolved ticker isn't in that file, this returns an honest
"not available for this ticker yet" result — it never guesses a peer group.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from app.core.ticker import bare_symbol
from app.tools.code_exec import run_calculations
from app.tools.market_data import MarketDataUnavailable, fetch_market_bundle

logger = logging.getLogger(__name__)

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "peer_groups.json"
_MAX_PEERS = 4


def _load_peer_map() -> dict[str, Any]:
    try:
        return json.loads(_DATA_PATH.read_text())
    except Exception as exc:
        logger.error("could not load peer_groups.json: %s", exc)
        return {"peers": {}, "sector_of": {}}


_PEER_MAP = _load_peer_map()


def sector_of(ticker: str) -> str | None:
    """Our curated sector label for a ticker (not yfinance's unreliable
    info['sector']) — shared by peer comparison (2.3) and sector P/E (2.1)
    so both features agree on the same sector taxonomy."""
    return _PEER_MAP.get("sector_of", {}).get(bare_symbol(ticker).upper())


def _row_for(ticker: str) -> dict[str, Any] | None:
    """Fetch one comparison row; returns None (not a raised exception) if
    this single peer's data is unavailable — one bad peer must never take
    down the whole comparison table."""
    try:
        bundle = fetch_market_bundle(ticker)
    except MarketDataUnavailable as exc:
        logger.info("peer row unavailable for %s: %s", ticker, exc)
        return None

    calc = run_calculations(bundle)
    price = bundle.get("price") or {}
    funds = bundle.get("fundamentals") or {}
    return {
        "ticker": ticker,
        "company_name": None,
        "last_price": price.get("last_price"),
        "currency": price.get("currency") or "INR",
        "change_1y_pct": price.get("change_1y_pct"),
        "pe_ratio": funds.get("pe_ratio"),
        "market_cap": funds.get("market_cap"),
        "profit_margin": funds.get("profit_margin"),
        "yoy_revenue_growth": calc.get("yoy_revenue_growth"),
    }


def fetch_peer_comparison(ticker: str) -> dict[str, Any]:
    """
    Returns:
      {"available": False, "reason": "..."}   — ticker not in the static map
      {"available": True, "sector": ..., "rows": [...]}
    `rows` always includes the queried ticker first (even if a peer's data
    later fails), and any peer whose data failed is simply omitted rather
    than shown as a fabricated row.
    """
    bare = bare_symbol(ticker).upper()
    peers = _PEER_MAP.get("peers", {}).get(bare)
    if not peers:
        return {
            "available": False,
            "reason": f"Peer comparison not available for {bare} yet — not in the curated peer-group list.",
            "rows": [],
        }

    sector = _PEER_MAP.get("sector_of", {}).get(bare)
    candidates = [ticker] + [f"{p}.NS" for p in peers[:_MAX_PEERS]]

    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(len(candidates), 5)) as pool:
        futures = {pool.submit(_row_for, t): t for t in candidates}
        results: dict[str, dict[str, Any] | None] = {}
        for fut in as_completed(futures):
            t = futures[fut]
            try:
                results[t] = fut.result()
            except Exception as exc:
                logger.warning("peer row raised for %s: %s", t, exc)
                results[t] = None

    for t in candidates:
        row = results.get(t)
        if row is not None:
            rows.append({**row, "is_subject": t == ticker})

    if not any(r["is_subject"] for r in rows):
        return {
            "available": False,
            "reason": f"Peer comparison data for {bare} itself was unavailable this run.",
            "rows": [],
        }

    return {"available": True, "sector": sector, "rows": rows}
