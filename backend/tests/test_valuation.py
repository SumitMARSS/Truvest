"""compute_pe_band is pure math (spec 2.1) — no LLM, no I/O, fully testable
offline with synthetic price/EPS series."""

from app.tools.code_exec import compute_pe_band


def _dates(n: int) -> list[str]:
    # one point per quarter-ish, oldest first
    return [f"202{y}-{m:02d}-30" for y in range(4) for m in (3, 6, 9, 12)][:n]


def test_unavailable_with_no_eps_history():
    out = compute_pe_band(["2024-01-01"], [100.0], [])
    assert out["available"] is False
    assert "series" in out


def test_unavailable_with_fewer_than_four_quarters():
    quarterly_eps = [
        {"period": "2026-06-30", "eps": 5.0},
        {"period": "2026-03-31", "eps": 4.5},
    ]
    out = compute_pe_band(_dates(8), [100.0] * 8, quarterly_eps)
    assert out["available"] is False


def test_available_with_exactly_four_quarters_marks_partial_history():
    quarterly_eps = [
        {"period": "2026-06-30", "eps": 5.0},
        {"period": "2026-03-31", "eps": 4.5},
        {"period": "2025-12-31", "eps": 4.0},
        {"period": "2025-09-30", "eps": 3.5},
    ]
    dates = ["2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30"]
    closes = [100.0, 110.0, 120.0, 130.0]
    out = compute_pe_band(dates, closes, quarterly_eps)
    assert out["available"] is True
    assert out["partial_history"] is True  # only 4 quarters, spec threshold is 8
    assert out["quarters_used"] == 4
    assert len(out["series"]) == 1
    ttm_eps = 5.0 + 4.5 + 4.0 + 3.5
    assert out["series"][0]["pe"] == round(130.0 / ttm_eps, 2)


def test_full_history_not_marked_partial():
    quarterly_eps = [{"period": f"2025-{q:02d}-28", "eps": 5.0} for q in range(1, 9)]
    dates = [f"2025-{q:02d}-28" for q in range(1, 9)]
    closes = [100.0 + i * 5 for i in range(8)]
    out = compute_pe_band(dates, closes, quarterly_eps)
    assert out["available"] is True
    assert out["partial_history"] is False
    assert out["quarters_used"] == 8
    assert out["band_min"] <= out["band_avg"] <= out["band_max"]


def test_skips_windows_with_missing_eps_quarter():
    quarterly_eps = [
        {"period": "2026-06-30", "eps": 5.0},
        {"period": "2026-03-31", "eps": None},
        {"period": "2025-12-31", "eps": 4.0},
        {"period": "2025-09-30", "eps": 3.5},
    ]
    dates = ["2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30"]
    closes = [100.0, 110.0, 120.0, 130.0]
    out = compute_pe_band(dates, closes, quarterly_eps)
    assert out["available"] is False
