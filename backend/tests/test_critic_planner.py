from app.agents.planner import planner_node
from app.agents.critic import critic_node
from app.agents.synthesizer import _dedupe_sources


def test_planner_initial_queues_all_workers():
    out = planner_node({"query": "AAPL", "ticker": "AAPL"})
    assert set(out["pending_workers"]) == {"market", "news", "filings", "calc", "peers", "shareholding"}


def test_planner_retry_only_failed():
    out = planner_node(
        {
            "ticker": "AAPL",
            "critic_issues": [
                {"code": "STALE_NEWS", "failed_subtask": "news", "message": "stale"},
            ],
            "retry_count": 1,
        }
    )
    assert out["pending_workers"] == ["news"]


def test_critic_flags_missing_price():
    draft = {
        "ticker": "AAPL",
        "analyst_summary": "test",
        "price_action": {"source_ids": ["src-market-AAPL"]},
        "fundamentals": {"source_ids": ["src-market-AAPL"]},
        "calculations": {"source_ids": ["src-calc-AAPL"]},
        "sources": [
            {"id": "src-market-AAPL"},
            {"id": "src-calc-AAPL"},
        ],
        "news": [{"title": "x", "url": "https://example.com", "source_ids": ["src-market-AAPL"]}],
    }
    out = critic_node({"draft_brief": draft, "retry_count": 0})
    assert out["critic_passed"] is False
    assert any(i.get("code") == "NO_PRICE" for i in out["critic_issues"])


def test_critic_flags_uncited_filing():
    """Regression test for docs/AUDIT.md #3.2 — filings previously had no
    citation check at all, so 'filings' could never be a retry target."""
    draft = {
        "ticker": "AAPL",
        "analyst_summary": "test",
        "price_action": {"last_price": 100, "source_ids": ["src-market-AAPL"]},
        "fundamentals": {"source_ids": ["src-market-AAPL"]},
        "calculations": {"source_ids": ["src-calc-AAPL"]},
        "sources": [{"id": "src-market-AAPL"}, {"id": "src-calc-AAPL"}],
        "news": [{"title": "x", "url": "https://example.com", "source_ids": ["src-market-AAPL"]}],
        "filings": [{"form": "INDIA_RESULTS", "source_ids": []}],
    }
    out = critic_node({"draft_brief": draft, "retry_count": 0})
    assert out["critic_passed"] is False
    issue = next(i for i in out["critic_issues"] if i.get("code") == "FILING_UNCITED")
    assert issue["failed_subtask"] == "filings"


def test_dedupe_sources_keeps_last_occurrence():
    """Regression test for docs/AUDIT.md #3.1 — operator.add duplicates a
    source id across retries; the brief must show only the latest value."""
    sources = [
        {"id": "src-news-AAPL-0", "title": "stale title"},
        {"id": "src-market-AAPL", "title": "market"},
        {"id": "src-news-AAPL-0", "title": "corrected title"},
    ]
    out = _dedupe_sources(sources)
    assert len(out) == 2
    by_id = {s["id"]: s for s in out}
    assert by_id["src-news-AAPL-0"]["title"] == "corrected title"
