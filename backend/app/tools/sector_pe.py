"""
Sector-average P/E — spec 2.1.

Primary source: NSE's public `allIndices` endpoint, which publishes a
trailing P/E per sectoral index alongside the index level. Reached via
`nsepython` for the same reason as shareholding.py — a bare request to
nseindia.com from this environment returns nothing, nsepython's session
handling gets through (confirmed live for NIFTY IT/BANK/AUTO/etc. during
this pass).

Fallback: a small static table for sectors NSE has no clean standalone
index for (Telecom — there is no "NIFTY TELECOM") or when the live call
fails outright. The static values are frozen at the time this file was
written and clearly labeled `"source": "static_fallback"` with their own
`as_of` date — never presented as live data.

Cached once/day — sector P/E "barely moves intraday" per spec, no reason to
hit NSE on every brief.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any, Optional

from app.services.cache import cache_get_sync, cache_set_sync

logger = logging.getLogger(__name__)

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "peer_groups.json"
_CACHE_NAMESPACE = "sector_pe"
_CACHE_TTL_SECONDS = 60 * 60 * 24  # 1 day

# Manually curated, frozen at write time — refresh weekly in production via
# a cron job per spec; this is the "always have SOME honest number" floor.
_STATIC_FALLBACK: dict[str, dict[str, Any]] = {
    "Telecom": {"pe": 45.0, "as_of": "2026-08-01", "source": "static_fallback"},
}


def _load_index_map() -> dict[str, str]:
    try:
        data = json.loads(_DATA_PATH.read_text())
        return {k: v for k, v in data.get("nse_sector_index", {}).items() if not k.startswith("_")}
    except Exception as exc:
        logger.error("could not load nse_sector_index map: %s", exc)
        return {}


_SECTOR_INDEX = _load_index_map()


def _fetch_live_index_pe(index_name: str) -> Optional[float]:
    try:
        import nsepython
    except ImportError:
        return None
    try:
        payload = nsepython.nsefetch("https://www.nseindia.com/api/allIndices")
        rows = payload.get("data") or []
    except Exception as exc:
        logger.info("NSE allIndices fetch failed: %s", exc)
        return None

    for row in rows:
        if str(row.get("index", "")).strip().upper() == index_name.upper():
            try:
                return float(row.get("pe"))
            except (TypeError, ValueError):
                return None
    return None


def fetch_sector_pe(sector: Optional[str]) -> dict[str, Any]:
    """
    Returns:
      {"available": False, "reason": "..."}
      {"available": True, "sector": "IT Services", "index": "NIFTY IT",
       "pe": 20.0, "as_of": "2026-08-16", "source": "nse_live" | "static_fallback"}
    Never raises.
    """
    if not sector:
        return {"available": False, "reason": "Sector unknown for this ticker."}

    cached = cache_get_sync(_CACHE_NAMESPACE, sector)
    if cached is not None:
        return {**cached, "from_cache": True}

    index_name = _SECTOR_INDEX.get(sector)
    if index_name:
        pe = _fetch_live_index_pe(index_name)
        if pe is not None:
            result = {
                "available": True,
                "sector": sector,
                "index": index_name,
                "pe": pe,
                "as_of": date.today().isoformat(),
                "source": "nse_live",
            }
            cache_set_sync(_CACHE_NAMESPACE, sector, result, _CACHE_TTL_SECONDS)
            return result
        logger.info("live sector P/E unavailable for %s (%s) — trying static fallback", sector, index_name)

    static = _STATIC_FALLBACK.get(sector)
    if static:
        result = {"available": True, "sector": sector, "index": None, **static}
        # Shorter TTL for the fallback path so a transient NSE outage
        # doesn't lock us onto stale-static data longer than necessary.
        cache_set_sync(_CACHE_NAMESPACE, sector, result, ttl_seconds=60 * 60 * 4)
        return result

    return {
        "available": False,
        "reason": f"No live NSE sectoral index or static fallback configured for sector '{sector}'.",
    }
