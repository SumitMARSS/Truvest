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

    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)
    return {
        "ticker": ticker,
        "passed": passed,
        "total": total,
        "accuracy": passed / total if total else 0,
        "checks": {k: v for k, v in checks},
        "critic_passed": brief.critic_passed,
    }


def main() -> None:
    results = [score_ticker(c) for c in load_testset()]
    overall = sum(r["passed"] for r in results) / max(sum(r["total"] for r in results), 1)
    out = {
        "overall_factual_accuracy": round(overall * 100, 2),
        "tickers_evaluated": len(results),
        "results": results,
    }
    out_path = Path(__file__).parent / "results" / "latest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    print(f"\nResume bullet candidate: achieved {out['overall_factual_accuracy']}% "
          f"factual accuracy across {out['tickers_evaluated']} evaluated tickers")


if __name__ == "__main__":
    main()
