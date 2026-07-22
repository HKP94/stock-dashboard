"""
ingest_market_news.py — 시장 단위 뉴스/리포트 수집 → market_news

채널:
  - MarketWatch RSS (US)
  - 한국경제 RSS (KR)
  - 매일경제 RSS (KR, file.mk 공개 XML)
  - Google News RSS (KR/US/Global 시장 쿼리)
  - FRED API (옵션, FRED_API_KEY 있을 때만)

규칙:
  - 공개 URL만 사용
  - url_hash SHA256 dedupe는 DB insert_market_news에서 처리
  - 소스 실패는 전체 실행을 중단하지 않는다
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, date, datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

from src.ingest_news import _fetch_rss, _google_news_url, _parse_rfc822
from src.schemas import MarketNewsRow
from src.freshness import today_kst

logger = logging.getLogger(__name__)

MARKETWATCH_RSS_URL = "https://feeds.content.dowjones.io/public/rss/mw_topstories"
HANKYUNG_RSS_URL = "https://www.hankyung.com/feed/finance"
MK_RSS_URL = "https://file.mk.co.kr/news/rss/rss_50200011.xml"

KR_GOOGLE_QUERIES = ["주식시장", "코스피", "코스닥", "한국 증시"]
US_GOOGLE_QUERIES = ["S&P500", "나스닥", "US stock market", "Wall Street"]
GLOBAL_GOOGLE_QUERIES = ["global stock market", "Federal Reserve", "inflation market"]

RSS_LIMIT = 20
GOOGLE_LIMIT = 20
FRED_SERIES = {
    "DGS10": "미국 10년 금리",
    "CPIAUCSL": "미국 소비자물가",
}


def _clean_html(text: Optional[str], cap: int = 500) -> Optional[str]:
    if not text:
        return None
    return BeautifulSoup(text, "html.parser").get_text(separator=" ").strip()[:cap]


def _fetch_feed_rows(source: str, url: str, max_items: int = RSS_LIMIT) -> list[MarketNewsRow]:
    feed = _fetch_rss(url)
    rows: list[MarketNewsRow] = []
    for entry in feed.entries[:max_items]:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or entry.get("id") or "").strip()
        if not title or not link or not link.startswith("http"):
            continue
        rows.append(MarketNewsRow(
            source=source,
            title=title,
            url=link,
            published_at=_parse_rfc822(entry.get("published", "")),
        ))
    logger.info("%s: market feed %d건", source, len(rows))
    return rows


def _fetch_google_rows(source: str, queries: list[str], is_kr: bool, max_items: int = GOOGLE_LIMIT) -> list[MarketNewsRow]:
    rows: list[MarketNewsRow] = []
    seen_urls: set[str] = set()
    for query in queries:
        if len(rows) >= max_items:
            break
        feed = _fetch_rss(_google_news_url(query, is_kr))
        for entry in feed.entries:
            if len(rows) >= max_items:
                break
            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or entry.get("id") or "").strip()
            if not title or not link or not link.startswith("http") or link in seen_urls:
                continue
            seen_urls.add(link)
            rows.append(MarketNewsRow(
                source=source,
                title=title,
                url=link,
                published_at=_parse_rfc822(entry.get("published", "")),
            ))
    logger.info("%s: Google market news %d건", source, len(rows))
    return rows


def _fetch_fred_rows(today: Optional[date] = None) -> list[MarketNewsRow]:
    key = os.environ.get("FRED_API_KEY")
    if not key:
        return []
    today = today or today_kst()
    rows: list[MarketNewsRow] = []
    for series_id, label in FRED_SERIES.items():
        request_url = (
            "https://api.stlouisfed.org/fred/series/observations"
            f"?series_id={series_id}&api_key={key}&file_type=json&sort_order=desc&limit=2"
        )
        public_url = f"https://fred.stlouisfed.org/series/{series_id}"
        try:
            response = requests.get(request_url, timeout=15)
            response.raise_for_status()
            payload = response.json()
            observations = payload.get("observations") or []
            if not observations:
                continue
            latest = observations[0]
            value = latest.get("value")
            obs_date = latest.get("date") or today.isoformat()
            rows.append(MarketNewsRow(
                source="fred_api_global",
                title=f"{label} 최신치 {value} ({obs_date})",
                url=public_url,
                published_at=datetime.strptime(obs_date, "%Y-%m-%d"),
            ))
        except Exception as exc:  # noqa: BLE001
            logger.warning("FRED %s 수집 실패: %s", series_id, exc)
    return rows


def run_market_news_ingest() -> dict:
    errors: list[dict] = []
    rows: list[MarketNewsRow] = []
    sources = [
        ("marketwatch_rss_us", lambda: _fetch_feed_rows("marketwatch_rss_us", MARKETWATCH_RSS_URL)),
        ("hankyung_rss_kr", lambda: _fetch_feed_rows("hankyung_rss_kr", HANKYUNG_RSS_URL)),
        ("mk_rss_kr", lambda: _fetch_feed_rows("mk_rss_kr", MK_RSS_URL)),
        ("google_news_market_kr", lambda: _fetch_google_rows("google_news_market_kr", KR_GOOGLE_QUERIES, True)),
        ("google_news_market_us", lambda: _fetch_google_rows("google_news_market_us", US_GOOGLE_QUERIES, False)),
        ("google_news_market_global", lambda: _fetch_google_rows("google_news_market_global", GLOBAL_GOOGLE_QUERIES, False)),
        ("fred_api_global", _fetch_fred_rows),
    ]
    for source_name, loader in sources:
        try:
            rows.extend(loader())
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s 시장 뉴스 수집 실패: %s", source_name, exc)
            errors.append({"step": "market_news", "source": source_name, "error": str(exc), "ts": datetime.now(UTC).isoformat()})
    return {"rows": rows, "errors": errors}
