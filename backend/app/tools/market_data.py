"""Indian market data via yfinance (NSE/BSE) with optional Alpha Vantage fallback."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx
import pandas as pd
import yfinance as yf

from app.core.config import settings
from app.core.ticker import bare_symbol, exchange_of, nse_quote_url

logger = logging.getLogger(__name__)


class MarketDataUnavailable(RuntimeError):
    """Raised when yfinance has no usable data at all for a ticker (network
    failure, rate-limit, or delisted symbol). Callers must catch this and
    degrade the section honestly rather than let it crash the whole brief —
    see docs/AUDIT.md #1.1."""


def fetch_market_bundle(ticker: str) -> dict[str, Any]:
    """
    Pull NSE/BSE price history + fundamentals for Indian equities (*.NS / *.BO).
    Raises MarketDataUnavailable (never a raw yfinance/network exception) if
    nothing at all could be fetched — the caller (market_worker) is
    responsible for turning that into a degraded-but-honest brief section.
    """
    t = yf.Ticker(ticker)
    try:
        # 3y history so 6M / 1Y / 3Y performance windows can be computed
        hist = t.history(period="3y")
    except Exception as exc:
        logger.warning("history() failed for %s: %s", ticker, exc)
        hist = pd.DataFrame()

    info: dict = {}
    try:
        info = t.info or {}
    except Exception as exc:
        logger.warning("info() failed for %s: %s", ticker, exc)

    closes = hist["Close"] if not hist.empty and "Close" in hist.columns else pd.Series(dtype=float)
    last = float(closes.iloc[-1]) if len(closes) else None

    def pct_change(calendar_days: int) -> float | None:
        """Return % change vs the close nearest to `calendar_days` ago (date-based,
        so weekends/holidays don't skew the window)."""
        if len(closes) < 2:
            return None
        target = closes.index[-1] - pd.Timedelta(days=calendar_days)
        prior = closes[closes.index <= target]
        if prior.empty:
            # History window slightly shorter than requested (e.g. 3y request,
            # 2.9y of data) — accept the oldest close if it covers >=90%
            span_days = (closes.index[-1] - closes.index[0]).days
            if span_days < calendar_days * 0.9:
                return None
            prev = float(closes.iloc[0])
        else:
            prev = float(prior.iloc[-1])
        if prev == 0:
            return None
        return round((float(closes.iloc[-1]) - prev) / prev * 100, 4)

    bundle: dict[str, Any] = {
        "ticker": ticker,
        "market": "IN",
        "exchange": exchange_of(ticker),
        "retrieved_at": datetime.utcnow().isoformat(),
        "provider": "yfinance",
        "price": {
            "last_price": last,
            "currency": info.get("currency") or "INR",
            "change_1d_pct": pct_change(1),
            "change_1w_pct": pct_change(7),
            "change_1m_pct": pct_change(30),
            "change_3m_pct": pct_change(91),
            "change_6m_pct": pct_change(182),
            "change_1y_pct": pct_change(365),
            "change_3y_pct": pct_change(1095),
            "volume": float(hist["Volume"].iloc[-1]) if not hist.empty and "Volume" in hist else None,
            "avg_volume": info.get("averageVolume"),
        },
        "fundamentals": {
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE") or info.get("forwardPE"),
            "eps_ttm": info.get("trailingEps"),
            "revenue_ttm": info.get("totalRevenue"),
            "profit_margin": info.get("profitMargins"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
        },
        "close_prices": [float(x) for x in closes.tolist()] if len(closes) else [],
        "dates": [d.isoformat() for d in closes.index.to_pydatetime()] if len(closes) else [],
        "annual_revenue": _annual_revenue(t),
        "quarterly_eps": _quarterly_eps(t),
        "url": f"https://finance.yahoo.com/quote/{ticker}",
        "nse_url": nse_quote_url(ticker),
    }

    # If yfinance returned no price, try Alpha Vantage (limited India coverage)
    if last is None and settings.alpha_vantage_api_key:
        av = _alpha_vantage_quote(ticker)
        if av:
            bundle["price"].update(av.get("price") or {})
            bundle["provider"] = "alpha_vantage"
            bundle["url"] = av.get("url") or bundle["url"]
            last = av.get("price", {}).get("last_price")

    if last is None and not bundle["fundamentals"].get("market_cap"):
        # Nothing at all came back — yfinance down/rate-limited and no AV
        # fallback. Fail loudly to the caller instead of returning a bundle
        # that *looks* complete but is all-None (docs/AUDIT.md #1.1).
        raise MarketDataUnavailable(
            f"No price or fundamentals could be fetched for {ticker} "
            "(yfinance unavailable, no Alpha Vantage fallback configured)."
        )

    return bundle


def _annual_revenue(t: yf.Ticker) -> list[dict[str, Any]]:
    try:
        fin = t.financials
        if fin is None or fin.empty or "Total Revenue" not in fin.index:
            return []
        row = fin.loc["Total Revenue"]
        return [
            {"period": str(idx.date()), "revenue": float(val)}
            for idx, val in row.items()
            if pd.notna(val)
        ]
    except Exception as exc:
        logger.debug("annual revenue unavailable: %s", exc)
        return []


def _quarterly_eps(t: yf.Ticker) -> list[dict[str, Any]]:
    """Newest-first quarterly diluted EPS, for the P/E-band valuation calc
    (spec 2.1). yfinance coverage on NSE tickers is inconsistent — expect
    fewer than 8 quarters on many names; the null-guard for "partial
    history" lives in tools/code_exec.py, not here (this just reports what
    actually came back, no padding/guessing)."""
    try:
        stmt = t.quarterly_income_stmt
        if stmt is None or stmt.empty:
            return []
        row_name = "Diluted EPS" if "Diluted EPS" in stmt.index else "Basic EPS"
        if row_name not in stmt.index:
            return []
        row = stmt.loc[row_name]
        return [
            {"period": str(idx.date()), "eps": float(val)}
            for idx, val in row.items()
            if pd.notna(val)
        ]
    except Exception as exc:
        logger.debug("quarterly EPS unavailable: %s", exc)
        return []


def _alpha_vantage_quote(ticker: str) -> dict[str, Any] | None:
    """
    Fallback quote. Alpha Vantage India symbols are often SYMBOL.BSE / SYMBOL.NSE.
    UPDATE: map more NSE symbols if AV coverage improves on your key tier.
    """
    candidates = []
    base = ticker.replace(".NS", "").replace(".BO", "")
    if ticker.upper().endswith(".BO"):
        candidates = [f"{base}.BSE", ticker]
    else:
        candidates = [f"{base}.NSE", f"{base}.BSE", ticker]

    for sym in candidates:
        try:
            with httpx.Client(timeout=20.0) as client:
                resp = client.get(
                    "https://www.alphavantage.co/query",
                    params={
                        "function": "GLOBAL_QUOTE",
                        "symbol": sym,
                        "apikey": settings.alpha_vantage_api_key,
                    },
                )
                resp.raise_for_status()
                data = resp.json().get("Global Quote") or {}
            price = data.get("05. price")
            if not price:
                continue
            return {
                "price": {
                    "last_price": float(price),
                    "currency": "INR",
                    "change_1d_pct": float(data.get("10. change percent", "0").replace("%", "") or 0),
                    "volume": float(data.get("06. volume") or 0) or None,
                },
                "url": f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={sym}",
            }
        except Exception as exc:
            logger.debug("Alpha Vantage miss for %s: %s", sym, exc)
    return None
