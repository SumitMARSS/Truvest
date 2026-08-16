"""Compare mode's metrics table is pure data assembly, no LLM, no new math
(spec 2.7) — every number was already computed by calc for each side."""

from app.agents.compare import _fallback_comparison_summary, build_metrics_table
from app.models.schemas import Fundamentals, PriceAction, ResearchBrief


def _brief(ticker: str, price: float, pe: float) -> ResearchBrief:
    return ResearchBrief(
        ticker=ticker,
        price_action=PriceAction(last_price=price, currency="INR"),
        fundamentals=Fundamentals(pe_ratio=pe),
    )


def test_metrics_table_has_one_row_per_side():
    a, b = _brief("RELIANCE.NS", 2500.0, 24.0), _brief("TCS.NS", 3800.0, 28.0)
    table = build_metrics_table(a, b)
    assert len(table) == 2
    assert table[0]["ticker"] == "RELIANCE.NS"
    assert table[1]["ticker"] == "TCS.NS"
    assert table[0]["pe_ratio"] == 24.0


def test_fallback_summary_identifies_cheaper_pe_and_never_recommends():
    a, b = _brief("RELIANCE.NS", 2500.0, 24.0), _brief("TCS.NS", 3800.0, 28.0)
    summary = _fallback_comparison_summary(a, b)
    assert "RELIANCE.NS" in summary and "TCS.NS" in summary
    assert "cheaper" in summary
    assert "not investment advice" in summary
    for banned in ("buy", "sell", "target price"):
        assert banned not in summary.lower()
