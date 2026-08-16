"""Advanced search is ranking logic, and ranking regressions are silent — a
bad score doesn't raise, it just puts the wrong company first. These tests pin
the behaviours that make the search box usable, plus the layer gating that
keeps it cheap (no network / no LLM when the local catalog is already sure).

Every test here runs offline: the catalog is bundled, and the Yahoo/LLM layers
are stubbed.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.services import stock_search
from app.services.stock_search import (
    HIGH_CONFIDENCE,
    StockSuggestion,
    catalog_exact,
    detect_compare_pair,
    local_suggestions,
    search_stocks,
)


def symbols(query: str, limit: int = 5) -> list[str]:
    return [s.symbol for s in local_suggestions(query, limit=limit)]


# --------------------------------------------------------------------------
# Layer 1 — local catalog ranking
# --------------------------------------------------------------------------


def test_exact_symbol_is_maximum_confidence():
    top = local_suggestions("RELIANCE", limit=5)[0]
    assert top.symbol == "RELIANCE"
    assert top.ticker == "RELIANCE.NS"
    assert top.score == 1.0
    assert top.confidence == "high"


def test_lowercase_and_whitespace_are_irrelevant():
    assert symbols("  tcs ")[0] == "TCS"


def test_curated_short_form_resolves():
    """'HUL' appears nowhere in 'Hindustan Unilever Limited' — only the
    curated overlay can make this work."""
    top = local_suggestions("hul", limit=3)[0]
    assert top.symbol == "HINDUNILVR"
    assert top.confidence == "high"


def test_former_name_still_resolves():
    """Users search the name they remember, not the renamed entity."""
    assert symbols("zomato")[0] == "ETERNAL"


def test_brand_keyword_finds_the_listed_parent():
    top = local_suggestions("maggi", limit=3)[0]
    assert top.symbol == "NESTLEIND"
    assert "Maggi" in top.match_reason


def test_multiple_brand_hits_outrank_a_single_one():
    """'jaguar cars' hits two of Tata Motors' keywords and only one of
    Maruti's, so the two-hit company must come first."""
    ranked = symbols("who makes jaguar cars")
    assert ranked[0] == "TMPV"


def test_initials_match_company_name():
    assert symbols("sbi")[0] == "SBIN"


def test_partial_typing_ranks_the_intended_company_first():
    assert symbols("asian pain")[0] == "ASIANPAINT"
    assert symbols("kotak mahindra bank")[0] == "KOTAKBANK"


def test_typo_still_finds_the_company_but_not_confidently():
    hits = local_suggestions("relaince", limit=5)
    assert hits, "a one-transposition typo must not return an empty list"
    assert hits[0].symbol == "RELIANCE"
    # Fuzzy is a guess: it must never claim high confidence.
    assert hits[0].confidence != "high"
    assert hits[0].match_reason == "Closest match to your spelling"


def test_short_name_tokens_do_not_match_everything():
    """Regression: name words like the 'R' in 'R R Kabel' used to match every
    query starting with R, flooding results with unrelated companies."""
    assert "RRKABEL" not in symbols("reliance", limit=5)


def test_keyword_matching_respects_word_boundaries():
    """Regression: the 'ev' keyword matched inside 'FEVICOL' and dragged a
    carmaker into an adhesives search."""
    ranked = symbols("fevicol")
    assert ranked[0] == "PIDILITIND"
    assert "TMPV" not in ranked


def test_weak_results_are_dropped_when_there_is_a_clear_winner():
    hits = local_suggestions("infosys ltd", limit=5)
    assert hits[0].symbol == "INFY"
    assert all(h.score >= 0.58 * hits[0].score for h in hits)


def test_no_match_returns_empty_not_an_error():
    assert local_suggestions("qwertyuiop zxcv", limit=5) == []


def test_sector_browse_returns_sector_members_not_symbol_lookalikes():
    """'IT companies' asks for a sector. ITC starts with 'IT' but is an FMCG
    company, so it must not lead the list."""
    ranked = symbols("it companies", limit=5)
    assert "INFY" in ranked and "TCS" in ranked
    assert ranked[0] != "ITC"


def test_bare_sector_word_does_not_hijack_a_name_search():
    """Without a browse cue ('stocks'/'companies'), an exact name still wins."""
    assert symbols("itc")[0] == "ITC"


def test_suggestion_payload_is_ui_ready():
    top = local_suggestions("infosys", limit=1)[0]
    payload = top.to_dict()
    assert payload["ticker"].endswith(".NS")
    assert payload["exchange"] == "NSE"
    assert 0.0 <= payload["score"] <= 1.0
    assert payload["confidence"] in {"high", "medium", "low"}
    assert payload["match_reason"]
    assert payload["sources"] == ["catalog"]


def test_catalog_exact_only_answers_when_confident():
    assert catalog_exact("RELIANCE").symbol == "RELIANCE"
    # A fuzzy-only hit is not a resolution — the pipeline must not silently
    # research a company the user never asked for.
    assert catalog_exact("relaince") is None


def test_compare_phrasing_is_detected_without_an_llm():
    assert detect_compare_pair("TCS vs INFY") == ("TCS", "INFY")
    assert detect_compare_pair("compare Reliance and ONGC") == ("Reliance", "ONGC")
    assert detect_compare_pair("RELIANCE") is None


# --------------------------------------------------------------------------
# Orchestration — layer gating, corroboration, caching
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_cache():
    """Each test starts from a cold cache so gating assertions are real."""
    with patch("app.services.stock_search.cache_get", AsyncMock(return_value=None)), patch(
        "app.services.stock_search.cache_set", AsyncMock()
    ):
        yield


async def test_confident_local_hit_skips_the_network_and_the_llm():
    yahoo = AsyncMock(return_value=[])
    llm = AsyncMock(return_value=[])
    with patch.object(stock_search, "_yahoo_suggestions", yahoo), patch.object(
        stock_search, "_llm_suggestions", llm
    ):
        result = await search_stocks("RELIANCE", limit=5)

    assert result["suggestions"][0]["symbol"] == "RELIANCE"
    assert result["layers_used"] == ["catalog"]
    yahoo.assert_not_awaited()
    llm.assert_not_awaited()


async def test_weak_local_hit_falls_back_to_yahoo():
    remote = StockSuggestion(
        symbol="SOMENEWCO",
        ticker="SOMENEWCO.NS",
        name="Some New Co Limited",
        score=0.8,
        confidence="medium",
        match_reason="Listed on Yahoo Finance",
        sources=["yahoo"],
    )
    with patch.object(stock_search, "_yahoo_suggestions", AsyncMock(return_value=[remote])), patch.object(
        stock_search, "_llm_suggestions", AsyncMock(return_value=[])
    ):
        result = await search_stocks("some new co", limit=5)

    assert "yahoo" in result["layers_used"]
    assert "SOMENEWCO" in [s["symbol"] for s in result["suggestions"]]


async def test_agreement_between_layers_raises_confidence():
    """Corroboration is the same rule the news pipeline uses: two independent
    sources agreeing is worth more than either alone."""
    solo = local_suggestions("relaince", limit=1)[0]
    remote = StockSuggestion(
        symbol=solo.symbol,
        ticker=solo.ticker,
        name=solo.name,
        score=0.70,
        confidence="medium",
        match_reason="Listed on Yahoo Finance",
        sources=["yahoo"],
    )
    with patch.object(stock_search, "_yahoo_suggestions", AsyncMock(return_value=[remote])), patch.object(
        stock_search, "_llm_suggestions", AsyncMock(return_value=[])
    ):
        result = await search_stocks("relaince", limit=5)

    merged = result["suggestions"][0]
    assert merged["symbol"] == solo.symbol
    assert merged["sources"] == ["catalog", "yahoo"]
    assert merged["score"] > solo.score


async def test_descriptive_question_reaches_the_llm_layer():
    interpreted = StockSuggestion(
        symbol="BRITANNIA",
        ticker="BRITANNIA.NS",
        name="Britannia Industries Limited",
        score=0.70,
        confidence="medium",
        match_reason="Interpreted from your question",
        sources=["llm", "catalog"],
    )
    llm = AsyncMock(return_value=[interpreted])
    with patch.object(stock_search, "_yahoo_suggestions", AsyncMock(return_value=[])), patch.object(
        stock_search, "_llm_suggestions", llm
    ):
        result = await search_stocks("which firm sells packaged snacks everywhere", limit=5)

    llm.assert_awaited()
    assert "llm" in result["layers_used"]
    assert result["suggestions"][0]["symbol"] == "BRITANNIA"


async def test_llm_guesses_are_resolved_through_the_catalog_and_capped():
    """The LLM proposes names, never tickers — a hallucinated company simply
    resolves to nothing, and a real one can't be marked high confidence."""
    with patch.object(
        stock_search, "_llm_company_guesses", lambda q: ["Nestle India Limited", "Definitely Not Listed Plc"]
    ):
        hits = await stock_search._llm_suggestions("who makes maggi", limit=5)

    assert [h.symbol for h in hits] == ["NESTLEIND"]
    assert hits[0].score <= 0.70
    assert hits[0].confidence != "high"
    assert hits[0].sources == ["llm", "catalog"]


async def test_llm_layer_is_disabled_by_configuration():
    with patch.object(stock_search.settings, "search_llm_fallback", False):
        assert await stock_search._llm_suggestions("anything at all", limit=5) == []


async def test_llm_failure_degrades_to_lexical_results():
    def boom(_query):
        raise RuntimeError("no LLM configured")

    with patch.object(stock_search, "_llm_company_guesses", boom):
        assert await stock_search._llm_suggestions("something descriptive", limit=5) == []


async def test_compare_pair_rides_along_with_the_response():
    with patch.object(stock_search, "_yahoo_suggestions", AsyncMock(return_value=[])), patch.object(
        stock_search, "_llm_suggestions", AsyncMock(return_value=[])
    ):
        result = await search_stocks("TCS vs INFY", limit=5)
    assert result["compare_pair"] == ["TCS", "INFY"]


async def test_high_confidence_threshold_is_meaningful():
    """A 'high' badge is a promise that we'd run the pipeline on it without
    asking — keep the label tied to the constant, not to a stray literal."""
    top = local_suggestions("TCS", limit=1)[0]
    assert top.score >= HIGH_CONFIDENCE
    assert top.confidence == "high"
