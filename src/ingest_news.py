"""
ingest_news.py — 뉴스 수집 + url_hash dedupe → news_raw

소스:
  KR — 네이버 금융 뉴스 HTML 스크래핑 (requests + BeautifulSoup4)
       URL: https://finance.naver.com/item/news_news.naver?code={6자리코드}
  US — yfinance Ticker.news (구/신 API 모두 처리)

절대 규칙:
  - DDGS(DuckDuckGo) 의존성 없음
  - url_hash(SHA256) 자동 생성 → ON CONFLICT DO NOTHING (dedupe)
  - published_at 파싱 실패 시 None (문자열 금지)
  - 종목 단위 try/except 격리
  - 자동 주문·매매 코드 없음
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

import requests
import yfinance as yf
from bs4 import BeautifulSoup
from tenacity import (
    before_sleep_log,
    retry,
    stop_after_attempt,
    wait_exponential,
)

from src.schemas import NewsRawRow

logger = logging.getLogger(__name__)

# ── 상수 ─────────────────────────────────────────────────────────
NAVER_NEWS_URL: str = (
    "https://finance.naver.com/item/news_news.naver?code={code}&page={page}"
)
NAVER_BASE_URL: str = "https://finance.naver.com"

MAX_PAGES: int = 1     # 기본 스크래핑 페이지 수 (최근 뉴스면 충분)
MAX_ITEMS: int = 30    # 종목당 최대 수집 건수

_SCRAPE_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://finance.naver.com/",
}


def _clean_ticker(ticker: str) -> str:
    """'005930.KS' → '005930'"""
    return ticker.split(".")[0]


def _is_kr(ticker: str) -> bool:
    return ticker.upper().endswith((".KS", ".KQ"))


# ──────────────────────────────────────────────────────────────
# 날짜 파싱 헬퍼
# ──────────────────────────────────────────────────────────────

def _parse_naver_date(text: str) -> Optional[datetime]:
    """
    네이버 금융 날짜 텍스트 파싱.
    형식: 'YYYY.MM.DD HH:MM' | 'YYYY.MM.DD' | 'HH:MM' (당일)
    """
    s = text.strip()
    for fmt in ("%Y.%m.%d %H:%M", "%Y.%m.%d", "%y.%m.%d %H:%M", "%y.%m.%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    # 'HH:MM' 형식 → 오늘 날짜로 보완
    if len(s) == 5 and s[2] == ":":
        try:
            today = date.today().strftime("%Y.%m.%d")
            return datetime.strptime(f"{today} {s}", "%Y.%m.%d %H:%M")
        except ValueError:
            pass
    return None


def _parse_yf_date(content: dict, raw: dict) -> Optional[datetime]:
    """yfinance 뉴스 날짜 파싱 (ISO 문자열 / Unix 타임스탬프 모두 처리)."""
    # 신 API: pubDate (ISO 8601 문자열)
    pub_str = content.get("pubDate")
    if pub_str:
        try:
            return datetime.fromisoformat(str(pub_str).replace("Z", "+00:00"))
        except ValueError:
            pass
    # 구 API: providerPublishTime (Unix timestamp)
    for key in ("providerPublishTime", "pubTime"):
        ts = raw.get(key) or content.get(key)
        if ts:
            try:
                return datetime.utcfromtimestamp(int(ts))
            except (TypeError, ValueError):
                pass
    return None


def _extract_yf_url(content: dict, raw: dict) -> Optional[str]:
    """yfinance 뉴스 URL 추출 (구/신 API 모두 처리)."""
    # 신 API: canonicalUrl / clickThroughUrl (dict 또는 str)
    for key in ("canonicalUrl", "clickThroughUrl"):
        u = content.get(key)
        if isinstance(u, dict):
            url = u.get("url")
            if url and url.startswith("http"):
                return url
        elif isinstance(u, str) and u.startswith("http"):
            return u
    # 구 API: link / url
    for key in ("link", "url"):
        u = content.get(key) or raw.get(key)
        if u and str(u).startswith("http"):
            return str(u)
    return None


# ──────────────────────────────────────────────────────────────
# KR 뉴스 수집 (네이버 금융 스크래핑)
# ──────────────────────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=3, max=15),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _naver_get(url: str) -> requests.Response:
    resp = requests.get(url, headers=_SCRAPE_HEADERS, timeout=15)
    resp.raise_for_status()
    return resp


def fetch_naver_news(
    ticker: str,
    max_pages: int = MAX_PAGES,
    max_items: int = MAX_ITEMS,
) -> list[NewsRawRow]:
    """네이버 금융 뉴스 페이지 스크래핑 → list[NewsRawRow]."""
    code = _clean_ticker(ticker)
    rows: list[NewsRawRow] = []

    for page in range(1, max_pages + 1):
        url = NAVER_NEWS_URL.format(code=code, page=page)
        resp = _naver_get(url)

        # 인코딩은 BeautifulSoup에게 맡김 (meta charset 자동 감지)
        soup = BeautifulSoup(resp.content, "html.parser")

        # 뉴스 테이블 탐색 (여러 selector 시도)
        news_table = (
            soup.find("table", class_="type5")
            or soup.find("table", attrs={"summary": lambda x: x and "제목" in str(x)})
        )
        if news_table is None:
            # fallback: td.title 을 품은 첫 번째 table
            for tbl in soup.find_all("table"):
                if tbl.find("td", class_="title"):
                    news_table = tbl
                    break

        if news_table is None:
            logger.warning("%s: 네이버 뉴스 테이블 없음 (page=%d)", ticker, page)
            break

        page_count = 0
        for tr in news_table.find_all("tr"):
            td_title = tr.find("td", class_="title")
            if td_title is None:
                continue
            a_tag = td_title.find("a")
            if a_tag is None:
                continue

            title = a_tag.get_text(strip=True)
            if not title:
                continue

            href = a_tag.get("href", "")
            if href.startswith("/"):
                article_url = NAVER_BASE_URL + href
            elif href.startswith("http"):
                article_url = href
            else:
                continue

            td_date = tr.find("td", class_="date")
            date_text = td_date.get_text(strip=True) if td_date else ""
            published_at = _parse_naver_date(date_text)

            rows.append(NewsRawRow(
                ticker=ticker,
                source="naver",
                published_at=published_at,
                title=title,
                body=None,
                url=article_url,
            ))
            page_count += 1

        if page_count == 0:
            break
        if len(rows) >= max_items:
            break

    logger.info("%s: 네이버 뉴스 %d건 수집", ticker, len(rows))
    return rows[:max_items]


# ──────────────────────────────────────────────────────────────
# US 뉴스 수집 (yfinance Ticker.news)
# ──────────────────────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _yf_news(ticker: str) -> list:
    return yf.Ticker(ticker).news or []


def fetch_yahoo_news(
    ticker: str,
    max_items: int = MAX_ITEMS,
) -> list[NewsRawRow]:
    """yfinance Ticker.news → list[NewsRawRow]."""
    raw_list = _yf_news(ticker)
    rows: list[NewsRawRow] = []

    for raw in raw_list[:max_items]:
        # 신 API: raw = {"content": {...}}  구 API: raw = {...} 직접
        content = raw.get("content", raw)

        title = content.get("title") or raw.get("title")
        if not title:
            continue

        article_url = _extract_yf_url(content, raw)
        if not article_url:
            continue

        published_at = _parse_yf_date(content, raw)
        body = content.get("summary") or content.get("description") or None

        rows.append(NewsRawRow(
            ticker=ticker,
            source="yahoo",
            published_at=published_at,
            title=str(title),
            body=body,
            url=article_url,
        ))

    logger.info("%s: Yahoo 뉴스 %d건 수집", ticker, len(rows))
    return rows


# ──────────────────────────────────────────────────────────────
# 배치 실행
# ──────────────────────────────────────────────────────────────

def run_news_ingest(tickers: list[str]) -> dict:
    """
    종목 배치 뉴스 수집. 종목 단위 격리(try/except).
    반환: {"news": {ticker: [NewsRawRow, ...]}, "errors": [...]}
    """
    news: dict[str, list[NewsRawRow]] = {}
    errors: list[dict] = []

    for ticker in tickers:
        try:
            if _is_kr(ticker):
                news[ticker] = fetch_naver_news(ticker)
            else:
                news[ticker] = fetch_yahoo_news(ticker)
        except Exception as exc:
            logger.error("%s: 뉴스 수집 실패: %s", ticker, exc, exc_info=True)
            errors.append({
                "ticker": ticker,
                "step": "news",
                "error": str(exc),
                "ts": datetime.utcnow().isoformat(),
            })

    return {"news": news, "errors": errors}


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    KR_TICKER = "005930.KS"   # 삼성전자
    US_TICKER = "AAPL"

    for ticker in [KR_TICKER, US_TICKER]:
        logger.info("=== 스모크 테스트: %s ===", ticker)
        result = run_news_ingest([ticker])
        items = result["news"].get(ticker, [])
        errs = result["errors"]

        print(f"\n[{ticker}] {len(items)}건")
        for row in items[:3]:
            print(f"  [{row.source}] {row.published_at}  {row.title[:50]}")
            assert "N/A" not in str(row.model_dump()), f"N/A 문자열 금지: {row}"
            assert row.url.startswith("http"), f"URL 형식 오류: {row.url}"
            # url_hash 자동 생성 확인
            assert len(row.url_hash) == 64, f"url_hash SHA256 길이 오류"

        if errs:
            for e in errs:
                print(f"  ERROR: {e}")

    print("\n⚠️ 투자 자문 아님 / 원금 손실 가능")
