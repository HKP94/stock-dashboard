from unittest.mock import MagicMock, patch

from src.ingest_market_news import (
    _fetch_feed_rows,
    _fetch_fred_rows,
    _fetch_google_rows,
    run_market_news_ingest,
)


def _feed(entries):
    feed = MagicMock()
    feed.entries = entries
    return feed


def test_fetch_feed_rows_builds_market_news_rows():
    entry = MagicMock()
    entry.get = lambda k, d="": {
        "title": "US market rallies",
        "link": "https://example.com/us1",
        "published": "Thu, 05 Jun 2025 10:23:00 GMT",
    }.get(k, d)
    with patch("src.ingest_market_news._fetch_rss", return_value=_feed([entry])):
        rows = _fetch_feed_rows("marketwatch_rss_us", "https://example.com/rss")
    assert len(rows) == 1
    assert rows[0].source == "marketwatch_rss_us"
    assert rows[0].title == "US market rallies"
    assert len(rows[0].url_hash) == 64


def test_fetch_google_rows_dedupes_urls():
    entry = MagicMock()
    entry.get = lambda k, d="": {
        "title": "Nasdaq tumbles",
        "link": "https://example.com/n1",
        "published": "Thu, 05 Jun 2025 10:23:00 GMT",
    }.get(k, d)
    with patch("src.ingest_market_news._fetch_rss", return_value=_feed([entry, entry])):
        rows = _fetch_google_rows("google_news_market_us", ["Nasdaq"], False)
    assert len(rows) == 1


def test_fetch_fred_rows_skips_without_key(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    assert _fetch_fred_rows() == []


def test_run_market_news_ingest_collects_and_isolates_errors():
    with patch("src.ingest_market_news._fetch_feed_rows", side_effect=[[MagicMock()], Exception("boom"), []]), \
         patch("src.ingest_market_news._fetch_google_rows", return_value=[]), \
         patch("src.ingest_market_news._fetch_fred_rows", return_value=[]):
        result = run_market_news_ingest()
    assert "rows" in result and "errors" in result
    assert len(result["errors"]) >= 1
