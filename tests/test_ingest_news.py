"""
test_ingest_news.py — ingest_news.py 단위 테스트 (PR-2: Google News RSS 파싱)
네트워크 없이 실행.
"""
from datetime import datetime
from unittest.mock import MagicMock, patch
import pytest

from src.ingest_news import (
    _parse_rfc822,
    _google_news_url,
    _is_kr,
    fetch_google_news,
)


# ── RFC 2822 날짜 파싱 ──────────────────────────────────────────
class TestParseRfc822:
    def test_standard_gmt(self):
        dt = _parse_rfc822("Thu, 05 Jun 2025 10:23:00 GMT")
        assert dt is not None
        assert dt.year == 2025
        assert dt.month == 6
        assert dt.day == 5
        assert dt.hour == 10

    def test_with_timezone_offset(self):
        dt = _parse_rfc822("Mon, 09 Jun 2025 01:00:00 +0900")
        assert dt is not None
        # +0900 → UTC: 01:00 - 09:00 = 전날 16:00
        assert dt.hour == 16

    def test_none_on_empty(self):
        assert _parse_rfc822("") is None
        assert _parse_rfc822(None) is None

    def test_invalid_format_returns_none(self):
        assert _parse_rfc822("not-a-date") is None

    def test_utc_explicit(self):
        dt = _parse_rfc822("Fri, 13 Jun 2025 15:30:00 UTC")
        assert dt is not None
        assert dt.hour == 15


# ── Google News RSS URL 생성 ────────────────────────────────────
class TestGoogleNewsUrl:
    def test_kr_url_params(self):
        url = _google_news_url("삼성전자 주가", is_kr=True)
        assert "ceid=KR%3Ako" in url or "ceid=KR:ko" in url
        assert "hl=ko" in url
        assert "gl=KR" in url
        assert "삼성전자" in url or "%EC%82%BC%EC%84%B1" in url

    def test_us_url_params(self):
        url = _google_news_url("AAPL stock", is_kr=False)
        assert "ceid=US%3Aen" in url or "ceid=US:en" in url
        assert "hl=en-US" in url
        assert "gl=US" in url

    def test_url_starts_with_https(self):
        url = _google_news_url("test", is_kr=False)
        assert url.startswith("https://news.google.com/rss/search")


# ── _is_kr ──────────────────────────────────────────────────────
class TestIsKr:
    def test_ks_suffix(self):
        assert _is_kr("005930.KS") is True

    def test_kq_suffix(self):
        assert _is_kr("000660.KQ") is True

    def test_us_ticker(self):
        assert _is_kr("AAPL") is False

    def test_case_insensitive(self):
        assert _is_kr("005930.ks") is True


# ── fetch_google_news (mock) ─────────────────────────────────────
class TestFetchGoogleNews:
    def _make_feed(self, entries):
        feed = MagicMock()
        feed.entries = entries
        return feed

    def test_returns_newsrawrow_list(self):
        entry = MagicMock()
        entry.get = lambda k, d="": {
            "title": "삼성전자 주가 급등",
            "link": "https://news.google.com/articles/abc123",
            "published": "Thu, 05 Jun 2025 10:23:00 GMT",
            "summary": "<p>삼성전자 주가</p>",
        }.get(k, d)

        with patch("src.ingest_news._fetch_rss", return_value=self._make_feed([entry])):
            rows = fetch_google_news("005930.KS", "삼성전자", max_items=5)

        assert len(rows) == 1
        row = rows[0]
        assert row.ticker == "005930.KS"
        assert row.source == "google_news"
        assert row.title == "삼성전자 주가 급등"
        assert row.url.startswith("https://")
        assert len(row.url_hash) == 64  # SHA256

    def test_dedupes_same_url(self):
        def make_entry():
            e = MagicMock()
            e.get = lambda k, d="": {
                "title": "뉴스", "link": "https://example.com/same", "published": "",
            }.get(k, d)
            return e

        with patch("src.ingest_news._fetch_rss", return_value=self._make_feed([make_entry(), make_entry()])):
            rows = fetch_google_news("005930.KS", "삼성전자")

        assert len(rows) == 1  # dedupe

    def test_skips_entry_without_url(self):
        entry = MagicMock()
        entry.get = lambda k, d="": {"title": "뉴스", "link": "", "published": ""}.get(k, d)

        with patch("src.ingest_news._fetch_rss", return_value=self._make_feed([entry])):
            rows = fetch_google_news("AAPL", "Apple")

        assert rows == []

    def test_max_items_cap(self):
        entries = []
        for i in range(30):
            e = MagicMock()
            url = f"https://example.com/article{i}"
            e.get = lambda k, d="", i=i, u=url: {
                "title": f"뉴스 {i}", "link": u, "published": "",
            }.get(k, d)
            entries.append(e)

        with patch("src.ingest_news._fetch_rss", return_value=self._make_feed(entries)):
            rows = fetch_google_news("AAPL", "Apple", max_items=5)

        assert len(rows) <= 5

    def test_rss_failure_returns_empty(self):
        with patch("src.ingest_news._fetch_rss", side_effect=Exception("network error")):
            rows = fetch_google_news("AAPL", "Apple")

        assert rows == []


# ──────────────────────────────────────────────────────────────
# PR-2: US 뉴스 보강 소스 (Yahoo RSS, Finnhub) 테스트
# ──────────────────────────────────────────────────────────────
class TestYahooRss:
    def test_parses_entries(self):
        from src.ingest_news import fetch_yahoo_rss
        rss = b"""<?xml version="1.0"?><rss><channel>
          <item><title>Apple hits record</title><link>https://finance.yahoo.com/news/a1</link>
            <pubDate>Mon, 15 Jun 2026 12:00:00 GMT</pubDate><description>x</description></item>
        </channel></rss>"""
        class R: status_code=200; content=rss
        with patch("src.ingest_news.requests.get", return_value=R()):
            rows = fetch_yahoo_rss("AAPL")
        assert len(rows) == 1
        assert rows[0].source == "yahoo_rss"
        assert rows[0].url == "https://finance.yahoo.com/news/a1"
        assert len(rows[0].url_hash) == 64

    def test_429_returns_empty(self):
        from src.ingest_news import fetch_yahoo_rss
        class R: status_code=429; content=b"Too Many Requests"
        with patch("src.ingest_news.requests.get", return_value=R()):
            assert fetch_yahoo_rss("AAPL") == []


class TestFinnhub:
    def test_disabled_without_key(self, monkeypatch):
        from src.ingest_news import finnhub_enabled, fetch_finnhub_news
        monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
        assert finnhub_enabled() is False
        assert fetch_finnhub_news("AAPL") == []

    def test_parses_with_key(self, monkeypatch):
        from src.ingest_news import fetch_finnhub_news
        monkeypatch.setenv("FINNHUB_API_KEY", "dummy")
        payload = [
            {"headline": "Nvidia surges", "url": "https://x.com/n1", "datetime": 1781000000, "summary": "s"},
            {"headline": "", "url": "https://x.com/skip", "datetime": 1781000001},  # 제목없음 → 스킵
        ]
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return payload
        with patch("src.ingest_news.requests.get", return_value=R()):
            rows = fetch_finnhub_news("NVDA")
        assert len(rows) == 1
        assert rows[0].source == "finnhub"
        assert rows[0].title == "Nvidia surges"

    def test_api_error_returns_empty(self, monkeypatch):
        from src.ingest_news import fetch_finnhub_news
        monkeypatch.setenv("FINNHUB_API_KEY", "dummy")
        with patch("src.ingest_news.requests.get", side_effect=Exception("boom")):
            assert fetch_finnhub_news("NVDA") == []
