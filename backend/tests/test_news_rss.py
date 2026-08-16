"""RSS news fetch (spec 2.5) — httpx is mocked so this runs offline;
feedparser itself parses real (small, inline) RSS XML deterministically."""

from unittest.mock import MagicMock, patch

from app.tools.news_rss import fetch_rss_news

_SAMPLE_RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
<title>Test Feed</title>
<item>
  <title>Reliance Industries share price gains after strong Q1 results</title>
  <link>https://example.com/reliance-q1</link>
  <description>Reliance posted strong quarterly results.</description>
  <pubDate>Mon, 10 Aug 2026 09:00:00 +0530</pubDate>
</item>
<item>
  <title>Unrelated company announces new product</title>
  <link>https://example.com/unrelated</link>
  <description>Nothing to do with our ticker.</description>
  <pubDate>Mon, 10 Aug 2026 08:00:00 +0530</pubDate>
</item>
</channel></rss>"""


def _fake_response():
    resp = MagicMock()
    resp.content = _SAMPLE_RSS
    resp.raise_for_status = MagicMock()
    return resp


def test_filters_to_articles_mentioning_the_company():
    with patch("app.tools.news_rss.httpx.get", return_value=_fake_response()):
        out = fetch_rss_news("RELIANCE", "Reliance Industries", max_results=10)
    assert len(out) >= 1
    assert all("reliance" in (a["title"] + a["content"]).lower() for a in out)
    assert all(a["provider"] == "rss" for a in out)


def test_feed_timeout_returns_empty_not_raise():
    with patch("app.tools.news_rss.httpx.get", side_effect=TimeoutError("slow")):
        out = fetch_rss_news("RELIANCE", "Reliance Industries", max_results=10)
    assert out == []


def test_no_keywords_returns_empty():
    out = fetch_rss_news("", None, max_results=10)
    assert out == []
