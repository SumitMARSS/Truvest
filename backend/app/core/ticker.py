"""Single source of truth for NSE/BSE ticker-format assumptions.

Every place that used to hand-roll `.replace(".NS", "").replace(".BO", "")`
or `.endswith(".BO")` should import from here instead — see docs/AUDIT.md #2.1.
"""

from __future__ import annotations

NSE_SUFFIX = ".NS"
BSE_SUFFIX = ".BO"


def bare_symbol(ticker: str) -> str:
    """'RELIANCE.NS' -> 'RELIANCE'."""
    return ticker.replace(NSE_SUFFIX, "").replace(BSE_SUFFIX, "")


def is_bse(ticker: str) -> bool:
    return ticker.upper().endswith(BSE_SUFFIX)


def exchange_of(ticker: str) -> str:
    """'BSE' or 'NSE'."""
    return "BSE" if is_bse(ticker) else "NSE"


def nse_quote_url(ticker: str) -> str:
    return f"https://www.nseindia.com/get-quotes/equity?symbol={bare_symbol(ticker)}"
