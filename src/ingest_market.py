"""
ingest_market.py — 글로벌 시장 지표 수집 → market_daily

심볼 → 필드:
  ^KS11  → kospi      ^KQ11 → kosdaq
  ^GSPC  → sp500      ^IXIC → nasdaq
  ^VIX   → vix        KRW=X → usdkrw
  ^TNX   → ust10y

소스:
  - KR 지수(^KS11/^KQ11) = 네이버 모바일 지수 API (실제 봉 날짜 포함, 로그인 불요=CI 안전)
  - 나머지 = yfinance

절대 규칙:
  - 심볼 단위 격리 — 한 심볼 실패가 전체 막으면 안 됨
  - summary_md / payload 는 None / {} — Phase 2에서 Gemini가 채움
  - 자동 주문·매매 코드 없음
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from typing import Optional

import requests
import yfinance as yf
from tenacity import (
    before_sleep_log,
    retry,
    stop_after_attempt,
    wait_exponential,
)

from src.external_timeout import run_with_timeout
from src.freshness import KST, _last_trading_day_on_or_before, is_trading_day
from src.schemas import MarketDailyRow

logger = logging.getLogger(__name__)
YFINANCE_TIMEOUT_SECONDS: float = 20.0
NAVER_TIMEOUT_SECONDS: float = 10.0

# ── 심볼 → MarketDailyRow 필드 매핑 ─────────────────────────────
MARKET_SYMBOLS: dict[str, str] = {
    "^KS11": "kospi",
    "^KQ11": "kosdaq",
    "^GSPC": "sp500",
    "^IXIC": "nasdaq",
    "^VIX":  "vix",
    "KRW=X": "usdkrw",
    "^TNX":  "ust10y",
}

# KR 지수는 yfinance가 하루 이상 스테일해 시황·등락률을 왜곡한다(PR-A 진단).
# 네이버 모바일 API는 실제 체결일(localTradedAt)을 주므로 날짜 정렬이 가능하다.
NAVER_INDEX_SYMBOLS: dict[str, str] = {"^KS11": "KOSPI", "^KQ11": "KOSDAQ"}
NAVER_INDEX_URL = "https://m.stock.naver.com/api/index/{sym}/price"

# 심볼이 속한 시장(휴장 캘린더 판정용). KR 지수만 KR, 나머지는 US 캘린더.
SYMBOL_MARKET: dict[str, str] = {s: ("KR" if s in NAVER_INDEX_SYMBOLS else "US") for s in MARKET_SYMBOLS}

# 배드틱 가드: 지수 하루 등락이 이 임계를 넘으면 소스 오류로 보고 그 필드만 버린다.
# (실제 폭락장도 지수 기준 ±15%는 극히 드물다. 넘으면 다음 실행이 정상값으로 덮는다.)
MAX_ABS_CHANGE_PCT = float(os.environ.get("MARKET_MAX_ABS_CHANGE_PCT", "15"))

# 매 실행 이 개수만큼의 최근 봉을 upsert한다 — 하루 결번(실행 실패·지연)이 자가치유된다.
LOOKBACK_BARS = int(os.environ.get("MARKET_LOOKBACK_BARS", "5"))


def _naver_index_series(symbol: str, pages: int = 1) -> list[tuple[date, float]]:
    """네이버 지수 일봉 (오름차순 [(체결일, 종가), ...]). 로그인 불요·CI 안전."""
    sym = NAVER_INDEX_SYMBOLS[symbol]
    out: list[tuple[date, float]] = []
    for page in range(1, pages + 1):
        resp = requests.get(
            NAVER_INDEX_URL.format(sym=sym),
            params={"pageSize": 60, "page": page},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=NAVER_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        for item in resp.json():
            try:
                out.append((
                    date.fromisoformat(item["localTradedAt"]),
                    float(str(item["closePrice"]).replace(",", "")),
                ))
            except (KeyError, TypeError, ValueError):
                continue
    return sorted(set(out))


def _yf_series(symbol: str, period: str = "1mo") -> list[tuple[date, float]]:
    """yfinance 종가 시계열 (오름차순 [(봉 날짜, 종가), ...])."""
    df = run_with_timeout(YFINANCE_TIMEOUT_SECONDS, lambda: yf.Ticker(symbol).history(period=period))
    if df.empty or "Close" not in df:
        return []
    closes = df["Close"].dropna()
    return [
        (idx.date() if hasattr(idx, "date") else date.fromisoformat(str(idx)[:10]), float(v))
        for idx, v in closes.items()
    ]


def last_complete_session(market: str, now_kst: Optional[datetime] = None) -> date:
    """**종가가 확정된** 마지막 거래일.

    장중에 수집하면 소스의 마지막 봉이 종가가 아니라 실시간가라 지수 이력이 오염된다
    (정규 06:00 KST 실행은 안전하지만 수동·로컬 실행은 미장 개장 중일 수 있다).
    KR은 마감(15:30)+확정 여유로 16:00 KST, US 종가는 KST 다음날 06:00에 확정된다.
    """
    now_kst = now_kst or datetime.now(KST)
    if market == "KR":
        ref = now_kst.date() if now_kst.hour >= 16 else now_kst.date() - timedelta(days=1)
    else:
        ref = (now_kst - timedelta(hours=6)).date() - timedelta(days=1)
    return _last_trading_day_on_or_before(ref, market)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _fetch_series(symbol: str, period: str, pages: int, cutoff: date) -> tuple[tuple[date, float], ...]:
    if symbol in NAVER_INDEX_SYMBOLS:
        series = _naver_index_series(symbol, pages=pages)
    else:
        series = _yf_series(symbol, period=period)
    return tuple((d, c) for d, c in series if d <= cutoff)


# ponytail: 프로세스 수명 캐시. 파이프라인은 단명 프로세스라 TTL 불필요하고,
# cutoff가 키에 있어 세션이 넘어가면 자동으로 새 데이터를 받는다.
_series_cache: dict[tuple, tuple[tuple[date, float], ...]] = {}


def index_series(symbol: str, period: str = "1mo", pages: int = 1) -> list[tuple[date, float]]:
    """심볼별 **확정 종가** 시계열. KR 지수=네이버, 나머지=yfinance.

    ★`market_daily`와 `index_daily`가 **같은 실행 안에서 동일한 바이트를 보도록** 결과를
    캐시한다. 둘이 각자 HTTP를 때리면 그 사이에 소스가 갱신될 때 두 테이블이 갈릴 수
    있는데(실제로 하루 어긋난 사고의 재발 경로), 캐시가 그 창을 없앤다.
    미확정(장중) 봉도 여기서 잘라내므로 두 테이블이 함께 보호된다.
    """
    cutoff = last_complete_session(SYMBOL_MARKET.get(symbol, "US"))
    key = (symbol, period, pages, cutoff)
    if key not in _series_cache:
        _series_cache[key] = _fetch_series(symbol, period, pages, cutoff)
    return list(_series_cache[key])


def _fetch_bars(symbol: str, lookback: int = LOOKBACK_BARS) -> list[tuple[date, float, Optional[float]]]:
    """
    최근 봉들의 (체결일, 종가, 직전 거래일 대비 등락률%).

    체결일을 함께 돌려주는 게 핵심 — 이전 구현은 종가만 받아 **실행일(asof)** 에 찍는 바람에
    소스가 스테일하면 값이 하루씩 밀리고 휴장일엔 직전 종가가 복제된 유령봉이 생겼다.
    """
    series = index_series(symbol)
    out: list[tuple[date, float, Optional[float]]] = []
    for i, (bar_date, close) in enumerate(series):
        prev = series[i - 1][1] if i > 0 else None
        change = round((close - prev) / prev * 100, 2) if prev else None
        out.append((bar_date, close, change))
    return out[-lookback:]


def is_market_open_day(asof: date) -> bool:
    """KR·US 중 한 곳이라도 거래일이면 True."""
    return is_trading_day(asof, "KR") or is_trading_day(asof, "US")


def fetch_market_rows() -> list[MarketDailyRow]:
    """
    시장 심볼 수집 → **체결일별** MarketDailyRow 목록.

    ★asof = 실행일이 아니라 **소스가 준 실제 체결일**이다. 이 한 가지가 유령봉·하루 밀림·
    `index_daily`와의 값 괴리를 구조적으로 없앤다(같은 취득 함수 + 같은 날짜 규칙 →
    `market_daily.kospi`와 `index_daily.^KS11`는 정의상 같은 값).
    시장별 휴장은 자연히 처리된다 — 봉이 없는 날은 그 시장 필드가 애초에 안 생긴다
    (예 07-17 KR 휴장 = kospi 없음 / US는 개장이라 sp500만 있는 행).

    심볼 단위 격리: 실패한 심볼만 빠지고 나머지는 정상.
    배드틱(|등락|>MAX_ABS_CHANGE_PCT) 봉은 버린다.
    """
    by_date: dict[date, dict[str, float]] = {}
    changes: dict[date, dict[str, float]] = {}

    for symbol, field in MARKET_SYMBOLS.items():
        try:
            bars = _fetch_bars(symbol)
        except Exception as exc:
            logger.warning("시장 심볼 %s 수집 실패 (필드=%s): %s", symbol, field, exc)
            continue  # 다른 심볼에 영향 없음

        for bar_date, close, chg in bars:
            if chg is not None and abs(chg) > MAX_ABS_CHANGE_PCT:
                logger.warning(
                    "배드틱 의심 — %s(%s) %s@%s (chg=%s%%, 임계 ±%s%%) 버림",
                    symbol, field, close, bar_date, chg, MAX_ABS_CHANGE_PCT,
                )
                continue
            by_date.setdefault(bar_date, {})[field] = close
            if chg is not None:
                changes.setdefault(bar_date, {})[field] = chg

        if bars:
            logger.info("시장 %s (%s) 최신 = %s @ %s", symbol, field, bars[-1][1], bars[-1][0])

    rows = [
        MarketDailyRow(
            asof=d,
            kospi=f.get("kospi"), kosdaq=f.get("kosdaq"),
            sp500=f.get("sp500"), nasdaq=f.get("nasdaq"),
            vix=f.get("vix"), usdkrw=f.get("usdkrw"), ust10y=f.get("ust10y"),
            summary_md=None,
            payload={"changes": changes.get(d, {})},
        )
        for d, f in sorted(by_date.items())
    ]
    if rows:
        last = rows[-1]
        logger.info(
            "market_daily %d행 (최신 asof=%s kospi=%s sp500=%s vix=%s)",
            len(rows), last.asof, last.kospi, last.sp500, last.vix,
        )
    return rows


def run_market_ingest(asof: Optional[date] = None) -> dict:
    """
    시장 지표 수집 실행.
    반환: {"markets": [MarketDailyRow...], "errors": [...]}
    asof 인자는 하위호환용으로 받되 무시한다 — 행의 날짜는 소스 체결일이 정한다.
    """
    errors: list[dict] = []
    try:
        markets = fetch_market_rows()
    except Exception as exc:
        logger.error("시장 지표 수집 전체 실패: %s", exc, exc_info=True)
        errors.append({
            "step": "market",
            "error": str(exc),
            "ts": datetime.utcnow().isoformat(),
        })
        markets = []

    return {"markets": markets, "errors": errors}


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    logger.info("=== 스모크 테스트: market_daily ===")
    result = run_market_ingest()
    if not result["markets"]:
        print("\n수집된 봉 없음")
        raise SystemExit(0)
    m = result["markets"][-1]

    print(f"\n최신 체결일: {m.asof}  (총 {len(result['markets'])}행)")
    print(f"  KOSPI   = {m.kospi}")
    print(f"  KOSDAQ  = {m.kosdaq}")
    print(f"  S&P500  = {m.sp500}")
    print(f"  NASDAQ  = {m.nasdaq}")
    print(f"  VIX     = {m.vix}")
    print(f"  USD/KRW = {m.usdkrw}")
    print(f"  US10Y   = {m.ust10y}")

    assert "N/A" not in str(m.model_dump()), "N/A 문자열 금지"

    collected = sum(1 for v in [m.kospi, m.kosdaq, m.sp500, m.nasdaq, m.vix, m.usdkrw, m.ust10y] if v is not None)
    print(f"\n수집 성공: {collected}/7 심볼")

    errs = result["errors"]
    if errs:
        print(f"에러: {errs}")
