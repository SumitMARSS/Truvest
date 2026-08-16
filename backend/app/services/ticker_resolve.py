"""Resolve Indian company name / NSE symbol → Yahoo Finance ticker (*.NS / *.BO)."""

from __future__ import annotations

import logging
import re
from typing import Optional

import httpx
import yfinance as yf

logger = logging.getLogger(__name__)

YAHOO_SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"
# Yahoo exchange codes for India
_INDIA_EXCHANGES = {"NSI", "BSE", "BOM"}

# Common NSE names → Yahoo symbols (fast path, avoids network lookup)
_ALIASES = {
    "RELIANCE": "RELIANCE.NS",
    "RELIANCE INDUSTRIES": "RELIANCE.NS",
    "RELIANCE INDUSTRIES LTD": "RELIANCE.NS",
    "RELIANCE INDUSTRIES LIMITED": "RELIANCE.NS",
    "TCS": "TCS.NS",
    "TATA CONSULTANCY SERVICES": "TCS.NS",
    "INFY": "INFY.NS",
    "INFOSYS": "INFY.NS",
    "HDFCBANK": "HDFCBANK.NS",
    "HDFC BANK": "HDFCBANK.NS",
    "ICICIBANK": "ICICIBANK.NS",
    "ICICI": "ICICIBANK.NS",
    "ICICI BANK": "ICICIBANK.NS",
    "SBIN": "SBIN.NS",
    "SBI": "SBIN.NS",
    "STATE BANK OF INDIA": "SBIN.NS",
    "BHARTIARTL": "BHARTIARTL.NS",
    "AIRTEL": "BHARTIARTL.NS",
    "BHARTI AIRTEL": "BHARTIARTL.NS",
    "ITC": "ITC.NS",
    "LT": "LT.NS",
    "LARSEN": "LT.NS",
    "LARSEN AND TOUBRO": "LT.NS",
    "HINDUNILVR": "HINDUNILVR.NS",
    "HUL": "HINDUNILVR.NS",
    "HINDUSTAN UNILEVER": "HINDUNILVR.NS",
    "BAJFINANCE": "BAJFINANCE.NS",
    "BAJAJ FINANCE": "BAJFINANCE.NS",
    "AXISBANK": "AXISBANK.NS",
    "AXIS BANK": "AXISBANK.NS",
    "KOTAKBANK": "KOTAKBANK.NS",
    "KOTAK": "KOTAKBANK.NS",
    "MARUTI": "MARUTI.NS",
    "MARUTI SUZUKI": "MARUTI.NS",
    "ASIANPAINT": "ASIANPAINT.NS",
    "ASIAN PAINTS": "ASIANPAINT.NS",
    "SUNPHARMA": "SUNPHARMA.NS",
    "SUN PHARMA": "SUNPHARMA.NS",
    "WIPRO": "WIPRO.NS",
    "TATAMOTORS": "TATAMOTORS.NS",
    "TATA MOTORS": "TATAMOTORS.NS",
    "TATASTEEL": "TATASTEEL.NS",
    "TATA STEEL": "TATASTEEL.NS",
    "NTPC": "NTPC.NS",
    "POWERGRID": "POWERGRID.NS",
    "ONGC": "ONGC.NS",
    "ADANIENT": "ADANIENT.NS",
    "ADANI ENTERPRISES": "ADANIENT.NS",
    "ADANIPORTS": "ADANIPORTS.NS",
    "ADANI PORTS": "ADANIPORTS.NS",
}

# Corporate suffixes that never appear in NSE symbols
_SUFFIXES = re.compile(r"\b(LTD|LIMITED|PVT|PRIVATE|CO|CORP|INC)\.?$")


class TickerResolutionError(ValueError):
    """Raised when a query cannot be mapped to a live NSE/BSE symbol."""


def _clean_query(query: str) -> str:
    q = query.strip().upper()
    q = re.sub(r"^(NSE:|BSE:|IN:)", "", q)
    q = q.replace(".", " ").replace(",", " ")
    q = re.sub(r"\s+", " ", q).strip()
    # Strip trailing corporate suffixes ("RELIANCE INDUSTRIES LTD" → "RELIANCE INDUSTRIES")
    while True:
        stripped = _SUFFIXES.sub("", q).strip()
        if stripped == q or not stripped:
            break
        q = stripped
    return q


def _yahoo_search_india(query: str) -> Optional[dict[str, str]]:
    """Search Yahoo Finance for an Indian listing matching a company name."""
    try:
        with httpx.Client(
            timeout=15.0,
            headers={"User-Agent": "Mozilla/5.0 (stock-research-agent)"},
        ) as client:
            resp = client.get(
                YAHOO_SEARCH_URL,
                params={"q": query, "quotesCount": 10, "newsCount": 0},
            )
            resp.raise_for_status()
            quotes = resp.json().get("quotes") or []
    except Exception as exc:
        logger.warning("Yahoo search failed for %r: %s", query, exc)
        return None

    # Prefer NSE, then BSE equities
    for want_ns in (True, False):
        for qte in quotes:
            symbol = str(qte.get("symbol") or "")
            exch = str(qte.get("exchange") or "")
            is_equity = (qte.get("quoteType") or "").upper() == "EQUITY"
            in_india = exch in _INDIA_EXCHANGES or symbol.endswith((".NS", ".BO"))
            if not (is_equity and in_india):
                continue
            if want_ns and not symbol.endswith(".NS"):
                continue
            return {
                "ticker": symbol,
                "company_name": qte.get("longname") or qte.get("shortname"),
            }
    return None


def _validate(ticker: str) -> dict:
    """Return yfinance info if the symbol is live, else {}."""
    try:
        info = yf.Ticker(ticker).info or {}
        if info.get("shortName") or info.get("longName") or info.get("regularMarketPrice"):
            return info
    except Exception as exc:
        logger.debug("validate %s failed: %s", ticker, exc)
    return {}


def resolve_ticker(query: str) -> dict[str, Optional[str]]:
    """
    Returns {"ticker": "RELIANCE.NS", "company_name": "...", "exchange": "NSE"}.
    Handles both symbols (RELIANCE, TCS.NS) and company names
    ("Reliance Industries Ltd"). Raises TickerResolutionError when nothing matches,
    so the pipeline fails fast instead of retrying a dead symbol.
    """
    cleaned = _clean_query(query)
    candidates: list[str] = []

    # 1. Alias fast path
    if cleaned in _ALIASES:
        candidates.append(_ALIASES[cleaned])

    # _clean_query splits on dots, so an explicitly-suffixed symbol arrives
    # here as "TCS NS" rather than "TCS.NS". Re-join it BEFORE the
    # single-word test below — this check used to live inside that block,
    # where a string containing a space was unreachable by construction, so
    # every "*.NS"/"*.BO" query fell through to the company-name search path
    # and failed to resolve at all (docs/AUDIT.md #9.1).
    if cleaned.endswith((" NS", " BO")):
        head, _, suffix = cleaned.rpartition(" ")
        cleaned = f"{head}.{suffix}"

    # 2. Single word → likely a bare NSE symbol
    if " " not in cleaned:
        base = cleaned.replace(" ", "")
        if base.endswith((".NS", ".BO")):
            candidates.append(base)
        else:
            candidates.extend([f"{base}.NS", f"{base}.BO"])

    # 3. Multi-word (company name) → Yahoo search
    searched: Optional[dict[str, str]] = None
    if " " in cleaned or not candidates:
        searched = _yahoo_search_india(cleaned)
        if searched:
            candidates.insert(0 if " " in cleaned else len(candidates), searched["ticker"])

    seen: set[str] = set()
    for ticker in candidates:
        if ticker in seen:
            continue
        seen.add(ticker)
        info = _validate(ticker)
        if not info:
            continue
        company = (
            info.get("shortName")
            or info.get("longName")
            or (searched or {}).get("company_name")
        )
        symbol = info.get("symbol") or ticker
        currency = (info.get("currency") or "").upper()
        if currency and currency != "INR":
            logger.warning("%s currency=%s — expected INR for India mode", symbol, currency)
        return {
            "ticker": symbol,
            "company_name": company,
            "exchange": "BSE" if str(symbol).upper().endswith(".BO") else "NSE",
        }

    raise TickerResolutionError(
        f"Could not resolve '{query}' to a live NSE/BSE symbol. "
        f"Tried: {', '.join(sorted(seen)) or 'nothing'}. "
        "Try the exchange symbol instead (e.g. RELIANCE, TCS, INFY)."
    )
