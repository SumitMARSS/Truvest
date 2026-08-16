"""Regression test for the spec 2.5 hard rule: a story from fewer than 2
independent sources must never carry a bullish/bearish label."""

from unittest.mock import patch

from app.agents.workers import news_worker


def test_single_source_story_downgrades_to_insufficient_data():
    single_source_articles = [
        {
            "title": "Reliance signs new refining deal",
            "content": "single outlet story",
            "url": "https://a.com/1",
            "published_date": "2026-08-10T00:00:00",
            "provider": "rss",
            "source_name": "Economic Times Markets",
        }
    ]
    corroborated_articles = [
        {
            "title": "Reliance Q1 profit beats estimates on strong margins",
            "content": "corroborated story A",
            "url": "https://b.com/1",
            "published_date": "2026-08-11T00:00:00",
            "provider": "rss",
            "source_name": "Moneycontrol",
        },
        {
            "title": "Reliance Q1 profit beats estimates on strong margins report",
            "content": "corroborated story B, different outlet, longer text than the single-source one",
            "url": "https://c.com/1",
            "published_date": "2026-08-11T01:00:00",
            "provider": "rss",
            "source_name": "Livemint Markets",
        },
    ]

    def fake_sentiment_batch(articles):
        # Every article gets a confident bullish call from the LLM/heuristic —
        # the corroboration rule must override this in code regardless.
        return {i: ("bullish", "looks positive", "near-term positive") for i in range(len(articles))}

    with patch(
        "app.agents.workers.fetch_rss_news",
        return_value=single_source_articles + corroborated_articles,
    ), patch("app.agents.workers.search_ticker_news", return_value=[]), patch(
        "app.agents.workers._classify_sentiment_batch", side_effect=fake_sentiment_batch
    ):
        out = news_worker({"ticker": "RELIANCE.NS", "company_name": "Reliance Industries"})

    articles = out["news_data"]["articles"]
    by_corroboration = {a["corroboration_count"]: a for a in articles}
    assert by_corroboration[1]["sentiment"] == "insufficient_data"
    assert by_corroboration[2]["sentiment"] == "bullish"
