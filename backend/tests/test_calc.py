"""run_calculations is the load-bearing proof of "no LLM does math" — it had
zero tests before this pass (docs/AUDIT.md #7.1)."""

from app.tools.code_exec import run_calculations


def _bundle(**overrides):
    base = {
        "price": {"last_price": 100.0},
        "fundamentals": {"eps_ttm": 5.0, "pe_ratio": 20.0},
        "close_prices": [float(i) for i in range(1, 61)],  # 1..60
        "annual_revenue": [{"period": "2024", "revenue": 1100.0}, {"period": "2023", "revenue": 1000.0}],
    }
    base.update(overrides)
    return base


def test_pe_from_price_eps():
    out = run_calculations(_bundle())
    assert out["pe_from_price_eps"] == 20.0


def test_pe_none_when_eps_missing():
    out = run_calculations(_bundle(fundamentals={"eps_ttm": None, "pe_ratio": 20.0}))
    assert out["pe_from_price_eps"] is None


def test_pe_none_when_eps_zero():
    out = run_calculations(_bundle(fundamentals={"eps_ttm": 0, "pe_ratio": 20.0}))
    assert out["pe_from_price_eps"] is None


def test_yoy_revenue_growth():
    out = run_calculations(_bundle())
    assert out["yoy_revenue_growth"] == 10.0


def test_yoy_none_with_insufficient_history():
    out = run_calculations(_bundle(annual_revenue=[{"period": "2024", "revenue": 1100.0}]))
    assert out["yoy_revenue_growth"] is None


def test_sma_20_and_50():
    out = run_calculations(_bundle())
    closes = [float(i) for i in range(1, 61)]
    assert out["sma_20"] == round(sum(closes[-20:]) / 20, 4)
    assert out["sma_50"] == round(sum(closes[-50:]) / 50, 4)


def test_sma_none_when_series_too_short():
    out = run_calculations(_bundle(close_prices=[1.0, 2.0, 3.0]))
    assert out["sma_20"] is None
    assert out["sma_50"] is None


def test_pe_drift_note_emitted_when_reported_diverges():
    out = run_calculations(_bundle(fundamentals={"eps_ttm": 5.0, "pe_ratio": 30.0}))
    assert out["pe_from_price_eps"] == 20.0
    assert any("differs" in n for n in out["notes"])


def test_no_drift_note_when_reported_close():
    out = run_calculations(_bundle(fundamentals={"eps_ttm": 5.0, "pe_ratio": 20.5}))
    assert out["notes"] == []
