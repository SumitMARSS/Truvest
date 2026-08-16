"""ticker_resolve had zero tests before this pass (docs/AUDIT.md #7.3).
Network calls (_yahoo_search_india, _validate) are mocked so this suite runs
offline and deterministically in CI."""

from unittest.mock import patch

import pytest

from app.services.ticker_resolve import TickerResolutionError, _clean_query, resolve_ticker


def test_clean_query_strips_exchange_prefix_and_suffix():
    assert _clean_query("NSE:RELIANCE") == "RELIANCE"
    assert _clean_query("Reliance Industries Ltd.") == "RELIANCE INDUSTRIES"
    assert _clean_query("tcs") == "TCS"


def test_resolve_alias_fast_path():
    with patch(
        "app.services.ticker_resolve._validate",
        return_value={"shortName": "Reliance Industries", "symbol": "RELIANCE.NS", "currency": "INR"},
    ):
        out = resolve_ticker("Reliance Industries Ltd")
    assert out["ticker"] == "RELIANCE.NS"
    assert out["exchange"] == "NSE"


def test_resolve_bare_symbol_tries_ns_then_bo():
    calls = []

    def fake_validate(ticker):
        calls.append(ticker)
        if ticker == "SOMECO.NS":
            return {}
        if ticker == "SOMECO.BO":
            return {"shortName": "Some Co", "symbol": "SOMECO.BO", "currency": "INR"}
        return {}

    with patch("app.services.ticker_resolve._validate", side_effect=fake_validate):
        out = resolve_ticker("SOMECO")
    assert out["ticker"] == "SOMECO.BO"
    assert out["exchange"] == "BSE"
    assert calls == ["SOMECO.NS", "SOMECO.BO"]


def test_resolve_explicitly_suffixed_symbol():
    """Regression test for docs/AUDIT.md #9.1 — '*.NS' / '*.BO' input used to
    fail to resolve entirely, because _clean_query splits on dots and the
    re-join was dead code. This is the exact format eval/tickers_testset.json
    uses, so the whole eval harness was unrunnable."""
    calls = []

    def fake_validate(ticker):
        calls.append(ticker)
        return {"shortName": "Tata Consultancy", "symbol": ticker, "currency": "INR"}

    with patch("app.services.ticker_resolve._validate", side_effect=fake_validate), patch(
        "app.services.ticker_resolve._yahoo_search_india"
    ) as search:
        out = resolve_ticker("TCS.NS")

    assert out["ticker"] == "TCS.NS"
    assert out["exchange"] == "NSE"
    assert calls == ["TCS.NS"]  # resolved directly, no ".NS"/".BO" guessing
    search.assert_not_called()  # and no needless network round-trip


def test_resolve_explicitly_suffixed_bse_symbol():
    with patch(
        "app.services.ticker_resolve._validate",
        return_value={"shortName": "Some Co", "symbol": "SOMECO.BO", "currency": "INR"},
    ), patch("app.services.ticker_resolve._yahoo_search_india"):
        out = resolve_ticker("SOMECO.BO")
    assert out["ticker"] == "SOMECO.BO"
    assert out["exchange"] == "BSE"


def test_resolve_raises_when_nothing_matches():
    with patch("app.services.ticker_resolve._validate", return_value={}), patch(
        "app.services.ticker_resolve._yahoo_search_india", return_value=None
    ):
        with pytest.raises(TickerResolutionError):
            resolve_ticker("NOT-A-REAL-COMPANY-XYZ")
