from app.agents.planner import planner_node
from app.agents.critic import critic_node


def test_planner_initial_queues_all_workers():
    out = planner_node({"query": "AAPL", "ticker": "AAPL"})
    assert set(out["pending_workers"]) == {"market", "news", "filings", "calc"}


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
