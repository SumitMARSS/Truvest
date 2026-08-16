"""Article clustering (spec 2.5) — pure logic (difflib), no network, no LLM."""

from app.core.dedup import cluster_articles


def test_near_duplicate_titles_cluster_together():
    articles = [
        {"title": "Reliance Q1 profit rises 12% on strong refining margins", "content": "short", "source_name": "ET"},
        {
            "title": "Reliance Q1 profit rises 12% on strong refining margin",
            "content": "a much longer piece of content with more detail than the other one",
            "source_name": "Moneycontrol",
        },
    ]
    out = cluster_articles(articles)
    assert len(out) == 1
    assert out[0]["corroboration_count"] == 2
    assert set(out[0]["corroborating_sources"]) == {"ET", "Moneycontrol"}
    # representative is the one with more content
    assert "much longer" in out[0]["content"]


def test_distinct_stories_do_not_cluster():
    articles = [
        {"title": "Reliance Q1 profit rises 12%", "content": "x", "source_name": "ET"},
        {"title": "TCS wins large European banking contract", "content": "y", "source_name": "Livemint"},
    ]
    out = cluster_articles(articles)
    assert len(out) == 2
    assert all(a["corroboration_count"] == 1 for a in out)


def test_same_outlet_publishing_twice_does_not_inflate_corroboration():
    articles = [
        {"title": "Reliance Q1 profit rises 12% on refining", "content": "a", "source_name": "ET"},
        {"title": "Reliance Q1 profit rises 12% on refining margin", "content": "b", "source_name": "ET"},
    ]
    out = cluster_articles(articles)
    assert len(out) == 1
    assert out[0]["corroboration_count"] == 1


def test_empty_input():
    assert cluster_articles([]) == []
