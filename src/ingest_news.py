"""
ingest_news.py — 뉴스 수집 + url_hash dedupe → news_raw

소스:
  KR — 네이버 금융 뉴스 HTML 스크래핑 (requests + BeautifulSoup4)
       URL: https://finance.naver.com/item/news_news.naver?code={6자리코드}
  KR/US — Google News RSS (인증 불필요, PR-2 추가)
  US — yfinance Ticker.news (구/신 API 모두 처리)

절대 규칙:
  - DDGS(DuckDuckGo) 의존성 없음
  - url_hash(SHA256) 자동 생성 → ON CONFLICT DO NOTHING (dedupe)
  - published_at 파싱 실패 시 None (문자열 금지)
  - 종목 단위 try/except 격리
  - 자동 주문·매매 코드 없음
"""

from __future__ import annotations

import email.utils
import logging
import os
import urllib.parse
from datetime import date, datetime, timezone
from typing import Optional

import feedparser
import requests
import yfinance as yf
from bs4 import BeautifulSoup
from tenacity import (
    before_sleep_log,
    retry,
    stop_after_attempt,
    wait_exponential,
)

from src.external_timeout import run_with_timeout
from src.schemas import NewsRawRow
from src.freshness import today_kst

logger = logging.getLogger(__name__)

# ── 상수 ─────────────────────────────────────────────────────────
NAVER_NEWS_URL: str = (
    "https://finance.naver.com/item/news_news.naver?code={code}&page={page}"
)
NAVER_BASE_URL: str = "https://finance.naver.com"

GOOGLE_NEWS_RSS_BASE: str = "https://news.google.com/rss/search"

MAX_PAGES: int = 2       # PR-2: 네이버 스크래핑 페이지 수 (1→2, 더 자세히)
MAX_ITEMS: int = 40      # PR-2: 종목당 최대 수집 건수 (20/30→40, 소스별 합산)
GOOGLE_MAX_ITEMS: int = 25  # PR-2: Google News RSS 소스당 최대 건수
YFINANCE_TIMEOUT_SECONDS: float = 20.0

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
# PR-2: Google News RSS 날짜 파싱 (RFC 2822 / email.utils)
# ──────────────────────────────────────────────────────────────

def _parse_rfc822(text: str) -> Optional[datetime]:
    """
    RSS pubDate(RFC 2822) → UTC datetime.
    예: 'Thu, 05 Jun 2025 10:23:00 GMT'
    email.utils.parsedate_to_datetime가 timezone-aware datetime을 반환한다.
    """
    if not text:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(text.strip())
        # UTC로 정규화 (timezone-aware)
        return dt.astimezone(timezone.utc).replace(tzinfo=None)  # naive UTC
    except Exception:
        return None


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
            today = today_kst().strftime("%Y.%m.%d")
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
# PR-2: Google News RSS 수집
# ──────────────────────────────────────────────────────────────

def _google_news_url(query: str, is_kr: bool) -> str:
    """Google News RSS URL 생성."""
    params = {"q": query}
    if is_kr:
        params.update({"hl": "ko", "gl": "KR", "ceid": "KR:ko"})
    else:
        params.update({"hl": "en-US", "gl": "US", "ceid": "US:en"})
    return GOOGLE_NEWS_RSS_BASE + "?" + urllib.parse.urlencode(params)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _fetch_rss(url: str) -> feedparser.FeedParserDict:
    """requests로 RSS XML 다운로드 후 feedparser로 파싱.
    feedparser 단독 HTTPS는 macOS 시스템 인증서 문제로 실패하는 경우가 있으므로
    requests(certifi 번들 사용)로 먼저 내용을 받는다.
    """
    resp = requests.get(url, headers=_SCRAPE_HEADERS, timeout=15)
    resp.raise_for_status()
    return feedparser.parse(resp.content)


def _collect_rss_rows(
    store_ticker: str,
    queries: list[str],
    is_kr: bool,
    max_items: int,
) -> list[NewsRawRow]:
    """주어진 쿼리들로 Google News RSS 수집 → store_ticker로 태깅된 NewsRawRow 리스트."""
    seen_urls: set[str] = set()
    rows: list[NewsRawRow] = []

    for query in queries:
        if len(rows) >= max_items:
            break
        url = _google_news_url(query, is_kr)
        try:
            feed = _fetch_rss(url)
        except Exception as exc:
            logger.warning("%s: Google News RSS 실패 (query=%r): %s", store_ticker, query, exc)
            continue

        for entry in feed.entries:
            if len(rows) >= max_items:
                break
            title = (entry.get("title") or "").strip()
            link  = (entry.get("link") or entry.get("id") or "").strip()
            if not title or not link or not link.startswith("http"):
                continue
            if link in seen_urls:
                continue
            seen_urls.add(link)

            published_at = _parse_rfc822(entry.get("published", ""))
            body = (entry.get("summary") or entry.get("description") or None)
            if body:
                body = BeautifulSoup(body, "html.parser").get_text(separator=" ")[:500]

            rows.append(NewsRawRow(
                ticker=store_ticker,
                source="google_news",
                published_at=published_at,
                title=title,
                body=body,
                url=link,
            ))

    logger.info("%s: Google News RSS %d건 수집", store_ticker, len(rows))
    return rows


# PR-0: US 종목 영문 정식명 — watchlist.name이 한글이라 영문 Google News 쿼리 품질이 낮고
# "Meta"/"Alpha" 등 일반명사 충돌이 생긴다. 정식명+티커로 쿼리를 구체화해 무관 결과를 줄인다.
_US_ENGLISH_NAME: dict[str, str] = {
    "AAPL": "Apple", "ALB": "Albemarle", "ASML": "ASML", "BA": "Boeing",
    "BBW": "Build-A-Bear Workshop", "BE": "Bloom Energy", "CELH": "Celsius Holdings",
    "CRDO": "Credo Technology", "ELV": "Elevance Health", "FUTU": "Futu Holdings",
    "GOOG": "Alphabet", "HSY": "Hershey", "LITE": "Lumentum", "META": "Meta Platforms",
    "MSFT": "Microsoft", "NVDA": "Nvidia", "RCL": "Royal Caribbean", "SLB": "SLB Schlumberger",
    "SMR": "NuScale Power", "SPCE": "Virgin Galactic", "TSLA": "Tesla",
    "TSM": "Taiwan Semiconductor", "VRT": "Vertiv", "WM": "Waste Management", "XOM": "Exxon Mobil",
}


def build_google_news_queries(ticker: str, company_name: str) -> list[str]:
    """종목별 Google News 쿼리 집합. 기본 쿼리 + 부정/리스크 쿼리를 함께 반환."""
    kr = _is_kr(ticker)
    code = _clean_ticker(ticker)
    if kr:
        return [
            f"{company_name} 주가",
            f"{company_name} 실적",
            f"{company_name} OR {code}",
            f"{company_name} 리스크",
            f"{company_name} 하락",
            f"{company_name} 우려",
        ]

    eng = _US_ENGLISH_NAME.get(ticker, company_name)
    return [
        f"{eng} {ticker} stock",
        f"{eng} earnings",
        f"{ticker} stock forecast",
        f"{ticker} news",
        f"{ticker} risk",
        f"{ticker} decline",
        f"{ticker} concern",
    ]


def fetch_google_news(
    ticker: str,
    company_name: str,
    max_items: int = GOOGLE_MAX_ITEMS,
) -> list[NewsRawRow]:
    """
    Google News RSS에서 종목 관련 뉴스 수집.
    KR: 기본 쿼리 + "{회사명} 리스크", "{회사명} 하락", "{회사명} 우려"
    US: 기본 쿼리 + "{ticker} risk", "{ticker} decline", "{ticker} concern"
    """
    kr = _is_kr(ticker)
    queries = build_google_news_queries(ticker, company_name)
    return _collect_rss_rows(ticker, queries, kr, max_items)


# ──────────────────────────────────────────────────────────────
# PR-4: 시장 뉴스 (pseudo-ticker _MARKET_KR / _MARKET_US)
# ──────────────────────────────────────────────────────────────

MARKET_KR_TICKER: str = "_MARKET_KR"
MARKET_US_TICKER: str = "_MARKET_US"

_MARKET_QUERIES: dict[str, tuple[list[str], bool]] = {
    MARKET_KR_TICKER: (["코스피 전망", "한국 증시 시황", "코스닥 시황"], True),
    # PR-2: US 시장 뉴스 소스 다양화
    MARKET_US_TICKER: (
        ["US stock market today", "S&P 500", "Nasdaq", "Federal Reserve", "US stocks outlook"],
        False,
    ),
}


def fetch_market_news(max_items: int = GOOGLE_MAX_ITEMS) -> dict[str, list[NewsRawRow]]:
    """KR/US 시장 시황 뉴스를 _MARKET_KR/_MARKET_US pseudo-ticker로 수집."""
    out: dict[str, list[NewsRawRow]] = {}
    for pseudo_ticker, (queries, is_kr) in _MARKET_QUERIES.items():
        try:
            out[pseudo_ticker] = _collect_rss_rows(pseudo_ticker, queries, is_kr, max_items)
        except Exception as exc:
            logger.warning("%s: 시장 뉴스 수집 실패: %s", pseudo_ticker, exc)
            out[pseudo_ticker] = []
    return out


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
    return run_with_timeout(YFINANCE_TIMEOUT_SECONDS, lambda: yf.Ticker(ticker).news or [])


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
# PR-2: Yahoo Finance RSS (US 뉴스 보강, 무료·인증불필요)
# ──────────────────────────────────────────────────────────────

YAHOO_RSS_URL: str = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"


def fetch_yahoo_rss(ticker: str, max_items: int = GOOGLE_MAX_ITEMS) -> list[NewsRawRow]:
    """Yahoo Finance RSS 헤드라인 피드 → list[NewsRawRow]. 실패/레이트리밋(429) 시 [].
    재시도하지 않는다(429는 빠르게 회복 안 됨 → 파이프라인 지연 방지)."""
    url = YAHOO_RSS_URL.format(ticker=ticker)
    try:
        resp = requests.get(url, headers=_SCRAPE_HEADERS, timeout=12)
        if resp.status_code != 200:
            logger.info("%s: Yahoo RSS %d (스킵)", ticker, resp.status_code)
            return []
        feed = feedparser.parse(resp.content)
    except Exception as exc:
        logger.warning("%s: Yahoo RSS 실패: %s", ticker, exc)
        return []
    rows: list[NewsRawRow] = []
    for entry in feed.entries[:max_items]:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or entry.get("id") or "").strip()
        if not title or not link or not link.startswith("http"):
            continue
        published_at = _parse_rfc822(entry.get("published", ""))
        body = entry.get("summary") or entry.get("description") or None
        if body:
            body = BeautifulSoup(body, "html.parser").get_text(separator=" ")[:500]
        rows.append(NewsRawRow(
            ticker=ticker, source="yahoo_rss",
            published_at=published_at, title=title, body=body, url=link,
        ))
    logger.info("%s: Yahoo RSS %d건 수집", ticker, len(rows))
    return rows


# ──────────────────────────────────────────────────────────────
# PR-2: Finnhub company-news (옵션, FINNHUB_API_KEY 있을 때만)
# ──────────────────────────────────────────────────────────────

def finnhub_enabled() -> bool:
    return bool(os.environ.get("FINNHUB_API_KEY"))


def fetch_finnhub_news(ticker: str, max_items: int = GOOGLE_MAX_ITEMS) -> list[NewsRawRow]:
    """
    Finnhub company-news → list[NewsRawRow]. FINNHUB_API_KEY 없으면 [] (자동 스킵).
    무료 티어 레이트리밋(분당 60) 고려. 키 발급·검증은 사용자 몫.
    """
    key = os.environ.get("FINNHUB_API_KEY")
    if not key:
        return []
    from datetime import timedelta
    today = today_kst()
    frm = (today - timedelta(days=14)).isoformat()
    url = (
        f"https://finnhub.io/api/v1/company-news?symbol={ticker}"
        f"&from={frm}&to={today.isoformat()}&token={key}"
    )
    try:
        resp = requests.get(url, headers=_SCRAPE_HEADERS, timeout=15)
        resp.raise_for_status()
        items = resp.json()
    except Exception as exc:
        logger.warning("%s: Finnhub 뉴스 실패(스킵): %s", ticker, exc)
        return []
    rows: list[NewsRawRow] = []
    for it in (items or [])[:max_items]:
        headline = (it.get("headline") or "").strip()
        link = (it.get("url") or "").strip()
        if not headline or not link or not link.startswith("http"):
            continue
        ts = it.get("datetime")
        pub = None
        if ts:
            try:
                pub = datetime.fromtimestamp(int(ts), tz=timezone.utc).replace(tzinfo=None)
            except (TypeError, ValueError):
                pub = None
        rows.append(NewsRawRow(
            ticker=ticker, source="finnhub",
            published_at=pub, title=headline,
            body=(it.get("summary") or None), url=link,
        ))
    logger.info("%s: Finnhub %d건 수집", ticker, len(rows))
    return rows


# ──────────────────────────────────────────────────────────────
# 배치 실행
# ──────────────────────────────────────────────────────────────

def run_news_ingest(
    tickers: list[str],
    company_names: Optional[dict[str, str]] = None,
    include_market: bool = True,
) -> dict:
    """
    종목 배치 뉴스 수집. 종목 단위 격리(try/except).
    PR-2: 기존 소스(네이버/yfinance)에 Google News RSS 추가.
    PR-4: include_market=True면 _MARKET_KR/_MARKET_US 시장 뉴스도 함께 수집.
    company_names: {ticker: 회사명} — 없으면 ticker를 그대로 사용
    반환: {"news": {ticker: [NewsRawRow, ...]}, "errors": [...]}
    """
    news: dict[str, list[NewsRawRow]] = {}
    errors: list[dict] = []
    if company_names is None:
        company_names = {}

    for ticker in tickers:
        try:
            rows: list[NewsRawRow] = []
            name = company_names.get(ticker, _clean_ticker(ticker))

            if _is_kr(ticker):
                rows += fetch_naver_news(ticker)
            else:
                rows += fetch_yahoo_news(ticker)
                # PR-2: US 뉴스 보강 — Yahoo RSS + Finnhub(옵션). 소스별 실패 격리.
                for fn in (fetch_yahoo_rss, fetch_finnhub_news):
                    try:
                        rows += fn(ticker)
                    except Exception as se:
                        logger.warning("%s: %s 보조 수집 실패: %s", ticker, fn.__name__, se)

            # Google News RSS 추가 수집 (전 소스 합산, url_hash dedupe는 insert_news_raw에서)
            try:
                rows += fetch_google_news(ticker, name)
            except Exception as ge:
                logger.warning("%s: Google News RSS 보조 수집 실패: %s", ticker, ge)
                # 보조 소스 실패는 종목 전체를 막지 않음

            news[ticker] = rows[:MAX_ITEMS]
        except Exception as exc:
            logger.error("%s: 뉴스 수집 실패: %s", ticker, exc, exc_info=True)
            errors.append({
                "ticker": ticker,
                "step": "news",
                "error": str(exc),
                "ts": datetime.utcnow().isoformat(),
            })

    # PR-4: 시장 뉴스 (_MARKET_KR / _MARKET_US)
    if include_market:
        try:
            market_news = fetch_market_news()
            for pseudo_ticker, rows in market_news.items():
                news[pseudo_ticker] = rows
        except Exception as exc:
            logger.warning("시장 뉴스 수집 실패: %s", exc)
            errors.append({
                "ticker": "_MARKET",
                "step": "market_news",
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
