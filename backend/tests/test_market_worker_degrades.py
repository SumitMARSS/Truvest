"""Regression test for docs/AUDIT.md #1.1: a market-data outage must degrade
the brief honestly, never crash the whole job."""

from unittest.mock import patch

from app.agents.workers import market_worker
from app.tools.market_data import MarketDataUnavailable


def test_market_worker_degrades_instead_of_raising():
    with patch(
        "app.agents.workers.fetch_market_bundle",
        side_effect=MarketDataUnavailable("yfinance timed out"),
    ):
        out = market_worker({"ticker": "RELIANCE.NS"})

    assert out["status_message"] == "market_unavailable"
    assert out["market_data"]["unavailable"] is True
    assert "yfinance timed out" in out["market_data"]["unavailable_reason"]
    assert out["sources"] == []
    assert out["completed_workers"] == ["market"]
