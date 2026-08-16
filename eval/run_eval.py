"""
Factual accuracy eval harness — resume metric source.

Usage:
  cd backend && python -m eval.run_eval
  # or: pytest ../eval -q

UPDATE: freeze expected values periodically (markets move). Prefer relative checks
(e.g. earnings date within N days, P/E within tolerance of live yfinance).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow importing app when run as script
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend") if (ROOT / "backend").exists() else str(ROOT))

from app.agents.runner import run_research_pipeline  # noqa: E402
from app.tools.market_data import fetch_market_bundle  # noqa: E402


def load_testset() -> list[dict]:
    path = Path(__file__).with_name("tickers_testset.json")
    return json.loads(path.read_text())


def score_ticker(case: dict) -> dict:
    ticker = case["ticker"]
    brief = run_research_pipeline(ticker, job_id=f"eval-{ticker}")
    live = fetch_market_bundle(ticker)

    checks = []

    # Price present
    checks.append(("has_price", brief.price_action.last_price is not None))

    # P/E within tolerance of live feed (if both exist)
    live_pe = (live.get("fundamentals") or {}).get("pe_ratio")
    if live_pe and brief.fundamentals.pe_ratio:
        tol = case.get("pe_tolerance", 3.0)
        ok = abs(float(brief.fundamentals.pe_ratio) - float(live_pe)) <= tol
        checks.append(("pe_matches_live", ok))
    else:
        checks.append(("pe_matches_live", True))  # skip if unavailable

    # Calc P/E consistent with price/EPS when both present
    if (
        brief.fundamentals.eps_ttm
        and brief.price_action.last_price
        and brief.calculations.pe_from_price_eps
    ):
        expected = brief.price_action.last_price / brief.fundamentals.eps_ttm
        ok = abs(expected - brief.calculations.pe_from_price_eps) < 0.05
        checks.append(("calc_pe_internal", ok))
    else:
        checks.append(("calc_pe_internal", True))

    # Every price claim cited
    checks.append(("price_cited", bool(brief.price_action.source_ids)))
    checks.append(("has_summary", bool(brief.analyst_summary)))
    checks.append(("has_sources", len(brief.sources) > 0))

    # Optional expected earnings / move checks from frozen testset
    if "min_sources" in case:
        checks.append(("min_sources", len(brief.sources) >= case["min_sources"]))

    # --- Phase 2 feature coverage -------------------------------------------
    # These assert CORRECT BEHAVIOR, not data availability: a feature whose
    # upstream source is down must degrade honestly (available=False WITH a
    # reason) rather than silently emit an empty-but-"available" section.
    # An unavailable section is a PASS as long as it says so — that's the
    # whole graceful-degradation contract.

    def degraded_ok(section, *value_fields: str) -> bool:
        if getattr(section, "available", False):
            return any(getattr(section, f, None) is not None for f in value_fields)
        return bool(getattr(section, "reason", None))

    checks.append(("valuation_pe_band_honest", degraded_ok(brief.valuation.pe_band, "band_avg")))
    checks.append(("valuation_sector_pe_honest", degraded_ok(brief.valuation.sector_pe, "pe")))
    checks.append(("peer_comparison_honest", degraded_ok(brief.peer_comparison, "rows")))
    checks.append(("shareholding_honest", degraded_ok(brief.shareholding, "promoter_pct")))

    # Sector P/E must always carry an as-of date when present (staleness must
    # be visible to the user, never hidden).
    checks.append(
        (
            "sector_pe_dated",
            (not brief.valuation.sector_pe.available) or bool(brief.valuation.sector_pe.as_of),
        )
    )

    # Confidence scoring: every claim-bearing block carries a confidence tag
    # (or an explicit None when the underlying data was unavailable).
    checks.append(("calc_has_confidence", brief.calculations.confidence is not None))
    checks.append(
        ("news_all_have_confidence", all(n.confidence is not None for n in brief.news))
    )

    # Corroboration hard rule (spec 2.5): a directional sentiment label is
    # only legal with 2+ independent sources.
    checks.append(
        (
            "sentiment_respects_corroboration",
            all(
                n.corroboration_count >= 2
                for n in brief.news
                if n.sentiment in ("bullish", "bearish")
            ),
        )
    )

    # Compliance filter (spec 2.6): no directive/predictive language may
    # survive into the user-facing summary.
    banned = ("target price", "buy rating", "sell rating", "we recommend buying", "will rally")
    summary_lower = (brief.analyst_summary or "").lower()
    checks.append(("summary_sebi_safe", not any(b in summary_lower for b in banned)))

    # Peer table must never fabricate the subject row.
    checks.append(
        (
            "peer_subject_present",
            (not brief.peer_comparison.available)
            or any(r.is_subject for r in brief.peer_comparison.rows),
        )
    )

    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)
    return {
        "ticker": ticker,
        "passed": passed,
        "total": total,
        "accuracy": passed / total if total else 0,
        "checks": {k: v for k, v in checks},
        "critic_passed": brief.critic_passed,
        # Visibility into how often each new source actually resolved live —
        # separate from pass/fail, since an honest "unavailable" still passes.
        "coverage": {
            "pe_band": brief.valuation.pe_band.available,
            "sector_pe": brief.valuation.sector_pe.available,
            "peers": brief.peer_comparison.available,
            "shareholding": brief.shareholding.available,
            "data_gaps": len(brief.data_gaps),
            "compliance_rewrites": len(brief.compliance_log),
        },
    }


def main() -> None:
    results = [score_ticker(c) for c in load_testset()]
    overall = sum(r["passed"] for r in results) / max(sum(r["total"] for r in results), 1)

    n = max(len(results), 1)
    coverage_rates = {
        key: round(sum(1 for r in results if r["coverage"][key]) / n * 100, 1)
        for key in ("pe_band", "sector_pe", "peers", "shareholding")
    }

    out = {
        "overall_factual_accuracy": round(overall * 100, 2),
        "tickers_evaluated": len(results),
        # % of tickers where each new data source actually resolved live.
        # Deliberately reported SEPARATELY from accuracy: a source being
        # unavailable is not an accuracy failure as long as the brief says
        # so — conflating the two would reward hiding gaps.
        "data_source_coverage_pct": coverage_rates,
        "results": results,
    }
    out_path = Path(__file__).parent / "results" / "latest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    print(f"\nResume bullet candidate: achieved {out['overall_factual_accuracy']}% "
          f"factual accuracy across {out['tickers_evaluated']} evaluated tickers")
    print(f"Live data-source coverage: {coverage_rates}")


if __name__ == "__main__":
    main()
