"""Confidence scoring is pure logic with zero external dependency (spec 2.4)
— no excuse for it to be untested."""

from app.core.confidence import Confidence, apply_confidence, score_exchange_data, score_filing, score_news


def test_score_exchange_data_high_for_yfinance():
    c, reason = score_exchange_data("yfinance")
    assert c is Confidence.high
    assert "yfinance" in reason


def test_score_exchange_data_low_for_stub():
    c, _ = score_exchange_data("stub")
    assert c is Confidence.low


def test_score_filing_high_when_cleanly_parsed():
    c, _ = score_filing("yfinance", cleanly_parsed=True)
    assert c is Confidence.high


def test_score_filing_medium_when_partial():
    c, _ = score_filing("tavily_india", cleanly_parsed=False)
    assert c is Confidence.medium


def test_score_filing_low_for_stub_provider():
    c, _ = score_filing("stub", cleanly_parsed=False)
    assert c is Confidence.low


def test_score_news_single_source_is_low():
    c, _ = score_news(1)
    assert c is Confidence.low


def test_score_news_corroborated_is_medium():
    c, _ = score_news(2)
    assert c is Confidence.medium
    c3, _ = score_news(3)
    assert c3 is Confidence.medium


def test_apply_confidence_tags_all_blocks():
    draft = {
        "price_action": {"last_price": 100, "source_ids": ["src-market-X"]},
        "fundamentals": {"pe_ratio": 20, "source_ids": ["src-market-X"]},
        "calculations": {"pe_from_price_eps": 20, "source_ids": ["src-calc-X"]},
        "filings": [{"form": "EARNINGS_CALENDAR", "provider": "yfinance", "mda_highlights": ["x"]}],
        "news": [{"title": "Result beats estimates", "corroboration_count": 1}],
        "risks": [{"title": "Bearish news tone", "detail": "..."}],
        "metadata": {},
    }
    out = apply_confidence(draft)
    assert out["price_action"]["confidence"] == "high"
    assert out["fundamentals"]["confidence"] == "high"
    assert out["calculations"]["confidence"] == "high"
    assert out["filings"][0]["confidence"] == "high"
    assert out["news"][0]["confidence"] == "low"
    assert out["risks"][0]["confidence"] == "low"


def test_apply_confidence_market_unavailable_sets_none_not_a_guess():
    draft = {
        "price_action": {"last_price": None},
        "fundamentals": {},
        "calculations": {},
        "filings": [],
        "news": [],
        "risks": [],
        "metadata": {"market_unavailable": True},
    }
    out = apply_confidence(draft)
    assert out["price_action"]["confidence"] is None
    assert out["fundamentals"]["confidence"] is None


def test_apply_confidence_is_pure_does_not_mutate_input():
    draft = {
        "price_action": {"last_price": 100},
        "fundamentals": {},
        "calculations": {},
        "filings": [],
        "news": [],
        "risks": [],
        "metadata": {},
    }
    apply_confidence(draft)
    assert "confidence" not in draft["price_action"]
