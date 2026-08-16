"""Peer comparison (spec 2.3) — market/calc calls are mocked so this runs
offline; the point under test is the graceful-degradation behavior, not
live NSE data."""

from unittest.mock import patch

from app.tools.market_data import MarketDataUnavailable
from app.tools.peer_data import fetch_peer_comparison, sector_of


def test_sector_of_known_ticker():
    assert sector_of("TCS.NS") == "IT Services"


def test_sector_of_unknown_ticker_is_none():
    assert sector_of("NOTAREALTICKER.NS") is None


def test_unavailable_for_ticker_not_in_curated_map():
    out = fetch_peer_comparison("SOMERANDOMTICKER.NS")
    assert out["available"] is False
    assert "not available" in out["reason"]


def _fake_bundle(ticker: str):
    if "WIPRO" in ticker:
        raise MarketDataUnavailable("simulated outage")
    return {
        "price": {"last_price": 100.0, "currency": "INR", "change_1y_pct": 5.0},
        "fundamentals": {"pe_ratio": 20.0, "market_cap": 1000.0, "profit_margin": 0.1},
        "close_prices": [100.0],
        "annual_revenue": [],
    }


def test_available_ticker_returns_rows_and_omits_failed_peer():
    with patch("app.tools.peer_data.fetch_market_bundle", side_effect=_fake_bundle):
        out = fetch_peer_comparison("TCS.NS")
    assert out["available"] is True
    tickers = [r["ticker"] for r in out["rows"]]
    assert "TCS.NS" in tickers
    assert "WIPRO.NS" not in tickers  # simulated outage — omitted, not fabricated
    subject_rows = [r for r in out["rows"] if r["is_subject"]]
    assert len(subject_rows) == 1
    assert subject_rows[0]["ticker"] == "TCS.NS"


def test_subject_unavailable_reports_unavailable_not_partial_table():
    def all_fail(ticker: str):
        raise MarketDataUnavailable("down")

    with patch("app.tools.peer_data.fetch_market_bundle", side_effect=all_fail):
        out = fetch_peer_comparison("TCS.NS")
    assert out["available"] is False
