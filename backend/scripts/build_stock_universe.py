#!/usr/bin/env python3
"""
Regenerate `backend/app/data/nse_universe.json` — the offline search catalog.

Why a bundled catalog instead of hitting an API per keystroke: a typeahead
fires on every character. Yahoo's search endpoint is unofficial, rate-limited
and ~200-400ms away; NSE's own autocomplete needs a cookie handshake. Neither
is acceptable in the hot path, and neither knows that "HUL" means
HINDUNILVR. So the primary index is local and the network is only a
supplement (see app/services/stock_search.py).

Sources (all public NSE archives, no key required):
  * EQUITY_L.csv        — every symbol listed in the NSE cash market
  * ind_nifty50list     — index membership, used as a popularity prior
  * ind_nifty100list      so "TATA" ranks TATAMOTORS above TATAINVEST
  * ind_nifty500list    — also the only free source of an industry label

Curated aliases/brand keywords live in a SEPARATE file
(`app/data/stock_aliases.json`) so regenerating this catalog never destroys
hand-written curation. This script only validates that every curated symbol
still exists in the listing.

Usage:
    python backend/scripts/build_stock_universe.py
    python backend/scripts/build_stock_universe.py --out /tmp/universe.json
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from datetime import date
from pathlib import Path

import httpx

ARCHIVES = "https://nsearchives.nseindia.com/content"
EQUITY_LIST_URL = f"{ARCHIVES}/equities/EQUITY_L.csv"
INDEX_URLS = {
    50: f"{ARCHIVES}/indices/ind_nifty50list.csv",
    100: f"{ARCHIVES}/indices/ind_nifty100list.csv",
    500: f"{ARCHIVES}/indices/ind_nifty500list.csv",
}

# BE/BZ are surveillance/trade-to-trade series — still real equities, but we
# keep only EQ + BE; BZ names are typically suspended and would pollute
# suggestions with dead symbols.
KEPT_SERIES = {"EQ", "BE"}

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / "backend" / "app" / "data" / "nse_universe.json"
ALIASES_PATH = REPO_ROOT / "backend" / "app" / "data" / "stock_aliases.json"

HEADERS = {"User-Agent": "Mozilla/5.0 (sourcebrief-universe-builder)"}


def _fetch_csv(url: str) -> list[dict[str, str]]:
    with httpx.Client(timeout=45.0, headers=HEADERS, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
    reader = csv.DictReader(io.StringIO(resp.text))
    rows = []
    for row in reader:
        rows.append({(k or "").strip(): (v or "").strip() for k, v in row.items()})
    return rows


def build() -> dict:
    equities = _fetch_csv(EQUITY_LIST_URL)
    print(f"EQUITY_L.csv: {len(equities)} rows", file=sys.stderr)

    # symbol -> (tier, industry). Lower tier = larger/more searched.
    tier: dict[str, int] = {}
    industry: dict[str, str] = {}
    for tier_value, url in INDEX_URLS.items():
        for row in _fetch_csv(url):
            symbol = row.get("Symbol", "")
            if not symbol:
                continue
            tier.setdefault(symbol, tier_value)
            if row.get("Industry"):
                industry.setdefault(symbol, row["Industry"])
        print(f"nifty{tier_value}: cumulative {len(tier)} symbols", file=sys.stderr)

    stocks = []
    for row in equities:
        symbol = row.get("SYMBOL", "")
        name = row.get("NAME OF COMPANY", "")
        if not symbol or not name:
            continue
        if row.get("SERIES", "") not in KEPT_SERIES:
            continue
        entry = {
            "symbol": symbol,
            "name": name,
            # 1000 = listed but outside the Nifty 500; used only as a
            # tie-breaker, never as a filter — small caps stay searchable.
            "tier": tier.get(symbol, 1000),
        }
        if symbol in industry:
            entry["industry"] = industry[symbol]
        stocks.append(entry)

    stocks.sort(key=lambda s: (s["tier"], s["symbol"]))
    _validate_aliases({s["symbol"] for s in stocks})

    return {
        "_comment": (
            "GENERATED FILE — do not hand-edit. Rebuild with "
            "`python backend/scripts/build_stock_universe.py`. Curated aliases and "
            "brand keywords belong in stock_aliases.json, which this file never touches. "
            "tier = Nifty index membership (50/100/500, else 1000) used as a "
            "popularity prior when two names score equally."
        ),
        "generated_at": date.today().isoformat(),
        "sources": [EQUITY_LIST_URL, *INDEX_URLS.values()],
        "count": len(stocks),
        "stocks": stocks,
    }


def _validate_aliases(known: set[str]) -> None:
    """Warn (don't fail) when curation drifts out of sync with the listing —
    symbols do get renamed (ZOMATO → ETERNAL) and delisted."""
    if not ALIASES_PATH.exists():
        return
    data = json.loads(ALIASES_PATH.read_text())
    stale = sorted(s for s in data.get("entries", {}) if s not in known)
    if stale:
        print(
            f"WARNING: {len(stale)} curated symbol(s) no longer in the NSE listing: "
            f"{', '.join(stale)}",
            file=sys.stderr,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    payload = build()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {payload['count']} symbols -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
