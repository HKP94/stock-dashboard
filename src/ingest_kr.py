"""
ingest_kr.py — KR 종목 가격·재무 수집

소스:
  가격/거래량 — pykrx  (KRX 직접 접속, yfinance KR 사용 금지)
  재무(연간·분기) — dart-fss (DART OpenAPI)

환경변수:
  DART_API_KEY  DART OpenAPI 발급 키 (https://opendart.fss.or.kr)

절대 규칙:
  - yfinance KR 의존 금지
  - 결측값은 반드시 None — 문자열 'N/A' 절대 금지
  - 자동 주문·매매 코드 없음
  - 시크릿은 환경변수에서만 읽음
"""

from __future__ import annotations

import logging
import os
import re
import time
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta
from typing import Callable, Optional, TypeVar
from zoneinfo import ZoneInfo

T = TypeVar("T")

import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.analyst_common import normalize_rating_label_score
from src.external_timeout import ExternalCallTimeout, run_with_timeout
from src.schemas import AnalystRow, FundamentalsRow, PriceDailyRow, ValuationRow

logger = logging.getLogger(__name__)

# ── 상수 ─────────────────────────────────────────────────────────
PRICE_LOOKBACK_DAYS: int = 730   # 2년치 (compute_indicators SMA200 용)
FS_BGN_YEARS: int = 4            # DART 재무 조회 연수
KR_DAILY_CLOSE_HOUR: int = 16    # KST 기준 일봉 종가 확정 후 조회 시각(완충 포함)
KST = ZoneInfo("Asia/Seoul")
# KR 외부 호출 하드 타임아웃(초). 무응답 시 종목/호출 단위로 끊고 다음으로 진행.
# (#37은 Gemini·yfinance만, #49는 pykrx OHLCV만 막았으나 실제 06시 행 지점은 dart-fss
#  회사목록 로드("Loading Stock Market Information")였다 — pykrx·DART 모든 진입점에 적용.)
KRX_HTTP_TIMEOUT_S: float = float(os.getenv("KRX_HTTP_TIMEOUT_S", "40"))   # pykrx
DART_HTTP_TIMEOUT_S: float = float(os.getenv("DART_HTTP_TIMEOUT_S", "40"))  # dart-fss


def _bounded(label: str, fn: Callable[[], T], timeout: float) -> T:
    """KR 외부(pykrx/dart-fss) 동기 호출을 하드 타임아웃으로 감싸는 공통 래퍼.

    - timeout 초과 시 ExternalCallTimeout → 호출부에서 종목/호출 단위 격리.
    - 라이브러리의 stdout 스피너·로그인 안내 소음을 억제(우리 logging은 별도 핸들러라 무관, 데이터 무영향).
    KR 수집의 모든 pykrx·DART 진입점은 반드시 이 래퍼를 거친다(누락 방지).
    """
    def _call() -> T:
        with open(os.devnull, "w") as devnull, redirect_stdout(devnull):
            return fn()

    try:
        return run_with_timeout(timeout, _call)
    except ExternalCallTimeout:
        logger.warning("%s: 외부 호출 타임아웃 (%.0fs 초과) — 끊고 진행", label, timeout)
        raise

# DART 손익계산서 계정과목 후보 (한국어)
_REVENUE_LABELS: frozenset[str] = frozenset({
    "매출액", "수익(매출액)", "영업수익", "매출",
})
_OP_INCOME_LABELS: frozenset[str] = frozenset({
    "영업이익", "영업이익(손실)", "영업손익",
})
_NET_INCOME_LABELS: frozenset[str] = frozenset({
    "당기순이익", "당기순이익(손실)", "분기순이익",
    "반기순이익", "당기순손익", "연결당기순이익",
})


def _clean_ticker(ticker: str) -> str:
    """'005930.KS' → '005930' (pykrx/DART는 6자리 코드)"""
    return ticker.split(".")[0]


def _safe_float(val) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, float) and (np.isnan(val) or val == 0.0):
        return None
    try:
        f = float(val)
        return None if np.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _safe_int(val) -> Optional[int]:
    if val is None:
        return None
    try:
        f = float(val)
        return None if np.isnan(f) else int(f)
    except (TypeError, ValueError):
        return None


# ──────────────────────────────────────────────────────────────
# 가격 수집 (pykrx)
# ──────────────────────────────────────────────────────────────

def _resolve_kr_price_target_date(now: Optional[datetime] = None) -> date:
    """KR 일봉 조회 종료일(KST 기준).
    - 장마감 전이면 직전 영업일
    - 장마감 후면 당일
    - 주말이면 직전 금요일
    휴장 평일은 pykrx가 직전 거래일로 자연스럽게 폴백한다.
    """
    now = now or datetime.now(KST)
    if now.tzinfo is not None:
        now = now.astimezone(KST)
    target = now.date() if now.hour >= KR_DAILY_CLOSE_HOUR else now.date() - timedelta(days=1)
    while target.weekday() >= 5:
        target -= timedelta(days=1)
    return target

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _pykrx_ohlcv(code: str, fromdate: str, todate: str) -> pd.DataFrame:
    from pykrx import stock as pykrx_stock  # 지연 임포트 (단위 테스트 격리)

    # pykrx는 KRX_ID/KRX_PW 없이도 익명 조회가 동작(경고는 무해). 무응답 시 하드 타임아웃으로 끊는다.
    return _bounded(
        f"pykrx.ohlcv:{code}",
        lambda: pykrx_stock.get_market_ohlcv_by_date(fromdate, todate, code),
        KRX_HTTP_TIMEOUT_S,
    )


def fetch_kr_prices(
    ticker: str,
    lookback_days: int = PRICE_LOOKBACK_DAYS,
    now: Optional[datetime] = None,
) -> list[PriceDailyRow]:
    """pykrx로 KR 종목 일별 OHLCV 수집."""
    code = _clean_ticker(ticker)
    target_date = _resolve_kr_price_target_date(now)
    fromdate = (target_date - timedelta(days=lookback_days)).strftime("%Y%m%d")
    todate = target_date.strftime("%Y%m%d")

    df = _pykrx_ohlcv(code, fromdate, todate)
    if df.empty:
        logger.warning("%s: pykrx OHLCV 응답 없음 (target=%s)", ticker, target_date.isoformat())
        return []

    # pykrx 한국어 컬럼 → 표준화
    col_map = {
        "시가": "open", "고가": "high", "저가": "low",
        "종가": "close", "거래량": "volume",
    }
    df = df.rename(columns=col_map)

    rows: list[PriceDailyRow] = []
    for idx, row in df.iterrows():
        dt: date = idx.date() if hasattr(idx, "date") else date.fromisoformat(str(idx)[:10])
        close = _safe_float(row.get("close"))
        if close is None:
            continue  # 종가 없는 행은 스킵

        rows.append(PriceDailyRow(
            ticker=ticker,
            date=dt,
            open=_safe_float(row.get("open")),
            high=_safe_float(row.get("high")),
            low=_safe_float(row.get("low")),
            close=close,
            volume=_safe_int(row.get("volume")),
            source="pykrx",
        ))

    resolved_last = rows[-1].date.isoformat() if rows else None
    logger.info("%s: pykrx %d rows (request=%s~%s, resolved_last=%s)", ticker, len(rows), fromdate, todate, resolved_last)
    return rows


# ──────────────────────────────────────────────────────────────
# 재무 수집 (dart-fss)
# ──────────────────────────────────────────────────────────────

def _get_dart_api_key() -> str:
    key = os.environ.get("DART_API_KEY")
    if not key:
        raise RuntimeError("DART_API_KEY 환경변수가 설정되지 않았습니다.")
    return key


def _parse_dart_col_date(col) -> Optional[date]:
    """dart-fss DataFrame 컬럼명에서 기간 종료일 파싱 (다양한 형식 대응)."""
    # pandas Timestamp / datetime
    if hasattr(col, "year") and hasattr(col, "month") and hasattr(col, "day"):
        try:
            return date(col.year, col.month, col.day)
        except (TypeError, ValueError):
            pass

    # MultiIndex 컬럼 튜플이면 level0(기간 문자열)을 쓴다. 예: ('20240101-20241231', ('연결재무제표',))
    if isinstance(col, tuple) and col:
        return _parse_dart_col_date(col[0])

    s = str(col).strip()

    # 기간 범위 'YYYYMMDD-YYYYMMDD' → 종료일 (extract_fs 데이터 컬럼 형식)
    if "-" in s:
        last = s.split("-")[-1].strip()
        if len(last) == 8 and last.isdigit():
            try:
                return date(int(last[:4]), int(last[4:6]), int(last[6:8]))
            except ValueError:
                pass

    # YYYYMMDD
    if len(s) == 8 and s.isdigit():
        try:
            return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        except ValueError:
            pass

    # YYYY-MM-DD (앞 10자만)
    if len(s) >= 10:
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            pass

    return None


def _find_label_col(df: pd.DataFrame):
    """extract_fs DataFrame에서 계정명(한국어) 메타 컬럼을 찾는다.

    extract_fs는 계정명을 index가 아니라 'label_ko' 컬럼에 담는다(MultiIndex면
    레벨 마지막이 'label_ko'). 못 찾으면 None.
    """
    for c in df.columns:
        name = c[-1] if isinstance(c, tuple) else c
        if str(name).strip().lower() in ("label_ko", "label_kr", "계정명", "항목명"):
            return c
    return None


def _find_fs_value(
    df: pd.DataFrame,
    label_col,
    candidates: frozenset[str],
    data_col,
) -> Optional[float]:
    """label_col(계정명) 값이 candidates에 속하는 행에서 data_col 값을 반환."""
    if df is None or df.empty:
        return None
    labels = df.iloc[:, list(df.columns).index(label_col)].astype(str).str.strip()
    mask = labels.isin(candidates)
    if not mask.any():
        return None
    # data_col로 직접 라벨 인덱싱하면 중첩 튜플 level 때문에 부분매칭(DataFrame 반환)이
    # 일어날 수 있으므로 정확한 컬럼 위치(iloc)로 Series를 고른다.
    series = df.iloc[:, list(df.columns).index(data_col)]
    for val in series[mask].tolist():
        if pd.notna(val):
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return None


def _parse_fs_rows(
    ticker: str,
    fs,
    period_type: str,
) -> list[FundamentalsRow]:
    """dart-fss FinancialStatement → list[FundamentalsRow]."""
    # 손익계산서 우선, 없으면 포괄손익계산서
    is_df: Optional[pd.DataFrame] = None
    for key in ("is", "IS", "cis", "CIS", "pl", "PL"):
        try:
            candidate = fs[key]
            if candidate is not None and not candidate.empty:
                is_df = candidate
                break
        except (KeyError, TypeError):
            continue

    if is_df is None or is_df.empty:
        logger.debug("%s: DART %s 손익계산서 없음", ticker, period_type)
        return []

    label_col = _find_label_col(is_df)
    if label_col is None:
        logger.warning("%s: DART %s 계정명(label_ko) 컬럼 없음", ticker, period_type)
        return []

    rows: list[FundamentalsRow] = []
    for col in is_df.columns:
        if col == label_col:
            continue
        period_end = _parse_dart_col_date(col)
        if period_end is None:
            continue  # 메타 컬럼(concept_id/label_en/class*) 등은 날짜 파싱 불가 → 스킵

        revenue = _find_fs_value(is_df, label_col, _REVENUE_LABELS, col)
        op_income = _find_fs_value(is_df, label_col, _OP_INCOME_LABELS, col)
        net_income = _find_fs_value(is_df, label_col, _NET_INCOME_LABELS, col)
        op_margin = (
            op_income / revenue
            if revenue and op_income and revenue != 0
            else None
        )

        rows.append(FundamentalsRow(
            ticker=ticker,
            period_type=period_type,
            period_end=period_end,
            revenue=revenue,
            op_income=op_income,
            op_margin=op_margin,
            net_income=net_income,
            source="dart",
        ))

    return rows


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=5, max=60),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _dart_extract_fs(corp, bgn_de: str, separate: bool, report_tp: str):
    # dart-fss 0.4.16: Corp.extract_fs(bgn_de, separate, report_tp, ...).
    # separate=False → 연결(CFS), True → 개별/별도(OFS). report_tp: 'annual'/'quarter'.
    # DART 재무 추출 HTTP는 무응답 가능 → 하드 타임아웃으로 끊고 상위 try/except가 격리.
    return _bounded(
        f"dart.extract_fs:{getattr(corp, 'corp_code', '?')}:{report_tp}:{'OFS' if separate else 'CFS'}",
        lambda: corp.extract_fs(
            bgn_de=bgn_de,
            separate=separate,
            report_tp=report_tp,
            progressbar=False,
        ),
        DART_HTTP_TIMEOUT_S,
    )


# DART 회사 목록은 종목 무관 1회 로드("Loading Stock Market Information")다 — 이 로드가 무응답이면
# (06시 행의 실제 지점) 종목마다 재시도하면 매번 재행한다. 성공/실패를 이번 실행 동안 캐시해 막는다.
_corp_list_state: Optional[tuple[str, object]] = None


def _reset_corp_list_cache() -> None:
    """테스트/재실행용 — 모듈 캐시 초기화."""
    global _corp_list_state
    _corp_list_state = None


def _get_corp_list_bounded(dart) -> object:
    """`dart.get_corp_list()`(회사목록 로드)를 하드 타임아웃으로 감싼다.

    dart-fss의 CorpList는 Singleton이지만 로드 도중 끊기면 미완료 상태로 남아 다음 호출이 다시
    로드(재행)한다. 따라서 실패를 모듈 캐시에 남겨 이번 실행의 나머지 종목은 즉시 건너뛴다.
    """
    global _corp_list_state
    if _corp_list_state is not None:
        kind, value = _corp_list_state
        if kind == "ok":
            return value
        raise ExternalCallTimeout("DART 회사 목록 로드가 이번 실행에서 실패 — 종목별 재시도 생략")
    try:
        corp_list = _bounded("dart.get_corp_list", dart.get_corp_list, DART_HTTP_TIMEOUT_S)
    except Exception:
        _corp_list_state = ("fail", None)
        raise
    _corp_list_state = ("ok", corp_list)
    return corp_list


_dart_spinner_disabled = False


def _disable_dart_spinner() -> None:
    """P0: dart-fss의 yaspin 스피너를 끈다.

    스피너 스레드는 비-데몬이고 `_load()`에 try/finally가 없어, 우리 DART 타임아웃(SIGALRM)이
    회사목록 다운로드 중 발화하면 `spinner.stop()`을 건너뛰어 스레드가 영구 회전한다.
    비-데몬 스레드 1개면 `sys.exit()`가 join 대기로 막혀 90분 워크플로 timeout까지 매달린다.
    스피너를 비활성화하면 스레드 자체가 생기지 않아 누수가 원천 차단된다.
    """
    global _dart_spinner_disabled
    if _dart_spinner_disabled:
        return
    try:
        from dart_fss.utils import enable_spinner
        enable_spinner(False)
        _dart_spinner_disabled = True
    except Exception as exc:  # pragma: no cover - 방어적
        logger.warning("dart-fss 스피너 비활성화 실패(비치명적): %s", exc)


def fetch_kr_fundamentals(ticker: str) -> list[FundamentalsRow]:
    """dart-fss로 KR 종목 연간·분기 재무 수집."""
    import dart_fss as dart  # 지연 임포트

    _disable_dart_spinner()  # P0: 비-데몬 스피너 스레드 누수 원천 차단(어떤 DART 호출보다 먼저)
    dart.set_api_key(api_key=_get_dart_api_key())
    code = _clean_ticker(ticker)
    bgn_de = (date.today() - timedelta(days=365 * FS_BGN_YEARS)).strftime("%Y%m%d")

    # 기업 검색
    # dart-fss 버전에 따라 find_by_stock_code가 단일 Corp 또는 list[Corp]를 반환한다.
    # 단일 Corp를 corps[0]로 인덱싱하면 "'Corp' object is not subscriptable"로 죽으므로
    # 두 형태를 모두 처리한다.
    corp_list = _get_corp_list_bounded(dart)
    found = corp_list.find_by_stock_code(code)
    if not found:
        logger.warning("%s: DART 기업 코드 없음 (code=%s)", ticker, code)
        return []
    if isinstance(found, (list, tuple)):
        corp = found[0] if found else None
    else:
        corp = found  # 단일 Corp 객체
    if corp is None:
        logger.warning("%s: DART 기업 매칭 실패 (code=%s)", ticker, code)
        return []
    logger.info("%s: DART 기업 = %s", ticker, getattr(corp, "corp_name", corp))

    rows: list[FundamentalsRow] = []

    for period_type, rpt_tp in [("annual", "annual"), ("quarter", "quarter")]:
        loaded = False
        for separate in (False, True):  # 연결(CFS) 우선, 실패 시 개별(OFS)
            fs_label = "OFS" if separate else "CFS"
            try:
                fs = _dart_extract_fs(corp, bgn_de=bgn_de, separate=separate, report_tp=rpt_tp)
                parsed = _parse_fs_rows(ticker, fs, period_type)
                if parsed:
                    rows.extend(parsed)
                    loaded = True
                    break
            except Exception as e:
                logger.warning(
                    "%s: DART %s %s 실패: %s", ticker, period_type, fs_label, e
                )
        if not loaded:
            logger.warning("%s: DART %s 재무 로드 실패 (CFS/OFS 모두)", ticker, period_type)

    logger.info("%s: dart-fss %d fundamentals rows", ticker, len(rows))
    return rows


# ──────────────────────────────────────────────────────────────
# 배치 실행 (n8n Execute Command 또는 직접 호출)
# ──────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────
# KR 밸류에이션·컨센서스 (무료 공개 페이지 — 네이버 금융 + FnGuide)
#
# 개인·비상업 분석 용도. 계좌 불필요. yfinance KR 사용 금지 규칙 유지.
# 소스:
#   - 네이버 금융 종목 메인: PER(#_per)·PBR(#_pbr)·현재가·목표주가·투자의견
#   - FnGuide Company Guide(#highlight_D_A): ROE·부채비율·매출증가율 보강
# 규칙: 종목 단위 try/except, 값 없으면 None('N/A' 문자열 금지), 요청 사이 sleep,
#       User-Agent 설정, 천단위 콤마/%/음수/공란 견고 파싱.
# ──────────────────────────────────────────────────────────────

NAVER_MAIN_URL: str = "https://finance.naver.com/item/main.naver?code={code}"
FNGUIDE_URL: str = "https://comp.fnguide.com/SVO2/ASP/SVD_Main.asp?pGB=1&gicode=A{code}"
_KR_WEB_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}
KR_WEB_SLEEP: float = 1.0   # 요청 사이 정중한 간격(레이트리밋 회피)
# P1: connect/read 분리 타임아웃. CI에서 comp.fnguide.com이 connect 단계에서 막히면(이그레스 차단)
# 종목당 15초×재시도3회≈51초를 낭비했다 → connect를 짧게(5초)로 끊고 connect 실패는 재시도하지 않는다.
KR_WEB_CONNECT_TIMEOUT: float = float(os.getenv("KR_WEB_CONNECT_TIMEOUT", "5"))
KR_WEB_READ_TIMEOUT: float = float(os.getenv("KR_WEB_READ_TIMEOUT", "15"))


def _parse_kr_number(text: Optional[str]) -> Optional[float]:
    """천단위 콤마·%·공란·음수·'배'/'원' 단위 텍스트 → float. 실패 시 None."""
    if not text:
        return None
    s = str(text).strip().replace(",", "").replace("%", "").replace("배", "").replace("원", "")
    s = s.replace("\xa0", "").strip()
    if s in ("", "-", "N/A", "n/a"):
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group())
    except ValueError:
        return None


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    # connect 실패(ConnectTimeout 등 ConnectionError 계열)는 재시도하지 않고 즉시 포기(빠른 스킵).
    # read timeout·HTTP 오류 등은 일시적일 수 있어 기존대로 3회 재시도.
    retry=retry_if_not_exception_type(requests.exceptions.ConnectionError),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _get_html(url: str) -> bytes:
    resp = requests.get(
        url,
        headers=_KR_WEB_HEADERS,
        timeout=(KR_WEB_CONNECT_TIMEOUT, KR_WEB_READ_TIMEOUT),
    )
    resp.raise_for_status()
    return resp.content


def _fetch_naver_main(code: str) -> dict:
    """네이버 금융 종목 메인 → {per_t, pbr, current_price, target_price, rating}."""
    soup = BeautifulSoup(_get_html(NAVER_MAIN_URL.format(code=code)), "html.parser")
    out: dict = {}

    def _em(sel: str) -> Optional[float]:
        el = soup.select_one(sel)
        return _parse_kr_number(el.get_text(strip=True)) if el else None

    out["per_t"] = _em("#_per")
    out["pbr"] = _em("#_pbr")

    # 현재가
    nt = soup.select_one(".no_today .blind") or soup.select_one("p.no_today")
    out["current_price"] = _parse_kr_number(nt.get_text(strip=True)) if nt else None

    # 투자의견 l 목표주가  (예: "투자의견 l 목표주가 4.00 매수 l 329,227")
    target = rating = None
    info = soup.select_one(".aside_invest_info")
    if info:
        for tr in info.select("tr"):
            t = tr.get_text(" ", strip=True)
            if "목표주가" in t or "투자의견" in t:
                m = re.search(r"(\d\.\d{2})\s*([가-힣A-Za-z]+)?\s*l\s*([\d,]+)", t)
                if m:
                    rating = (m.group(2) or "").strip() or None
                    target = _parse_kr_number(m.group(3))
                break
    out["target_price"] = target
    out["rating"] = rating
    return out


def _fetch_fnguide(code: str) -> dict:
    """FnGuide #highlight_D_A → {roe, debt_ratio, rev_growth, op_margin, n_analysts}. best-effort."""
    out: dict = {}
    try:
        soup = BeautifulSoup(_get_html(FNGUIDE_URL.format(code=code)), "html.parser")
    except Exception as exc:
        logger.warning("FnGuide 조회 실패 (A%s): %s", code, exc)
        return out

    tbl = soup.select_one("#highlight_D_A")
    if tbl:
        for tr in tbl.select("tr"):
            th = tr.select_one("th")
            if not th:
                continue
            label = th.get_text(" ", strip=True)
            vals = [td.get_text(strip=True) for td in tr.select("td")]
            # 마지막 비어있지 않은 값(가장 최근 실적/추정)
            last = next((v for v in reversed(vals) if v and v.strip() not in ("", "-")), None)
            num = _parse_kr_number(last)
            if "ROE" in label:
                out["roe"] = num
            elif "부채비율" in label:
                out["debt_ratio"] = num
            elif "매출액증가율" in label or "매출증가율" in label:
                out["rev_growth"] = num
            elif "영업이익률" in label:
                out["op_margin"] = num

    # 추정기관수(컨센서스 참여 기관) — 목표주가 영역
    txt = soup.get_text(" ", strip=True)
    m = re.search(r"추정기관수\s*([\d.]+)", txt)
    if m:
        out["n_analysts"] = int(float(m.group(1)))
    return out


def fetch_kr_valuation_analyst(
    ticker: str, asof: Optional[date] = None
) -> tuple[Optional[ValuationRow], Optional[AnalystRow]]:
    """
    KR 종목 밸류에이션 + 컨센서스 수집(네이버 + FnGuide). 계좌 불필요·무료.
    반환: (ValuationRow, AnalystRow). 페이지 실패 시 해당 항목 None.
    """
    asof = asof or date.today()
    code = _clean_ticker(ticker)

    naver = _fetch_naver_main(code)
    time.sleep(KR_WEB_SLEEP)
    fn = _fetch_fnguide(code)
    time.sleep(KR_WEB_SLEEP)

    # PR-4: KIS 옵션 경로(키 있을 때만) — '있으면 우선'으로 보강. 키 없으면 {} 반환→무영향.
    try:
        from src.ingest_kis import fetch_kis_metrics
        kis = fetch_kis_metrics(code)
    except Exception:
        kis = {}
    if kis.get("roe") is not None:
        fn["roe"] = kis["roe"] * 100.0 if kis["roe"] < 1.5 else kis["roe"]  # 비율→%로 통일(아래서 /100)
    if kis.get("debt_ratio") is not None:
        fn["debt_ratio"] = kis["debt_ratio"]
    if kis.get("target_price") is not None:
        naver["target_price"] = kis["target_price"]
    if kis.get("rating"):
        naver["rating"] = kis["rating"]
    if kis.get("n_analysts") is not None:
        fn["n_analysts"] = kis["n_analysts"]

    # ROE는 %값(예: 7.11) → US와 단위 일관성 위해 그대로 % 단위 저장 안 함:
    # US yfinance returnOnEquity는 비율(0.07). KR FnGuide ROE는 %(7.11). 일관성 위해 /100.
    roe = fn.get("roe")
    roe_ratio = roe / 100.0 if roe is not None else None
    rev_growth = fn.get("rev_growth")
    rev_growth_ratio = rev_growth / 100.0 if rev_growth is not None else None

    val = ValuationRow(
        ticker=ticker,
        asof=asof,
        per_t=naver.get("per_t"),
        per_f=None,                       # 무료 소스 Fwd PER 미확보 → None(중립 처리)
        pbr=naver.get("pbr"),
        ev_ebitda=None,
        roe=roe_ratio,
        roa=None,
        debt_ratio=fn.get("debt_ratio"),  # %단위(US debtToEquity와 의미 다르나 분포 랭킹용)
        rev_growth=rev_growth_ratio,
    )

    target = naver.get("target_price")
    curr = naver.get("current_price")
    upside = ((target / curr) - 1) if (target and curr and curr != 0) else None
    rating_raw = naver.get("rating")
    rating_label, rating_score = normalize_rating_label_score(rating_raw)
    ana = AnalystRow(
        ticker=ticker,
        asof=asof,
        rating=rating_label or rating_raw,
        rating_label=rating_label,
        rating_score=rating_score,
        target_price=target,
        upside=upside,
        n_analysts=fn.get("n_analysts"),
        source="naver+fnguide",
    )

    has_val = any(v is not None for v in (val.per_t, val.pbr, val.roe, val.debt_ratio))
    has_ana = ana.target_price is not None
    logger.info(
        "%s: KR valuation per_t=%s pbr=%s roe=%s debt=%s | analyst target=%s rating=%s upside=%s",
        ticker, val.per_t, val.pbr, val.roe, val.debt_ratio, ana.target_price, ana.rating, ana.upside,
    )
    return (val if has_val else None), (ana if has_ana else None)


def run_kr_ingest(tickers: list[str]) -> dict:
    """
    KR 종목 배치 수집. 종목 단위 격리(try/except).
    반환: {"prices", "fundamentals", "valuations", "analysts", "errors"}
    """
    prices: dict[str, list[PriceDailyRow]] = {}
    fundamentals: dict[str, list[FundamentalsRow]] = {}
    valuations: dict[str, ValuationRow] = {}
    analysts: dict[str, AnalystRow] = {}
    errors: list[dict] = []

    for ticker in tickers:
        try:
            prices[ticker] = fetch_kr_prices(ticker)
        except Exception as exc:
            logger.error("%s: 가격 수집 실패: %s", ticker, exc, exc_info=True)
            errors.append({
                "ticker": ticker, "step": "price",
                "error": str(exc), "ts": datetime.utcnow().isoformat(),
            })

        try:
            f_rows = fetch_kr_fundamentals(ticker)
            fundamentals[ticker] = f_rows
            # fetch_kr_fundamentals는 DART 실패를 내부에서 삼키고 []를 반환한다.
            # 0건이면 원인이 runs.errors에 드러나도록 비치명적 노트를 남긴다(값은 None 유지).
            if not f_rows:
                logger.warning("%s: DART 재무 0건 — runs.errors에 기록", ticker)
                errors.append({
                    "ticker": ticker, "step": "fundamentals_empty",
                    "error": "DART 재무 0건 (조회 실패 또는 미제공) — 값 None 유지",
                    "ts": datetime.utcnow().isoformat(),
                })
        except Exception as exc:
            logger.error("%s: 재무 수집 실패: %s", ticker, exc, exc_info=True)
            errors.append({
                "ticker": ticker, "step": "fundamentals",
                "error": str(exc), "ts": datetime.utcnow().isoformat(),
            })

        # KR 밸류에이션 + 컨센서스 (네이버 + FnGuide, 무료)
        try:
            val_row, ana_row = fetch_kr_valuation_analyst(ticker)
            if val_row is not None:
                valuations[ticker] = val_row
            if ana_row is not None:
                analysts[ticker] = ana_row
            if val_row is None and ana_row is None:
                errors.append({
                    "ticker": ticker, "step": "valuation_empty",
                    "error": "네이버/FnGuide 밸류·컨센서스 0건 — 값 None 유지",
                    "ts": datetime.utcnow().isoformat(),
                })
        except Exception as exc:
            logger.error("%s: KR 밸류/컨센서스 수집 실패: %s", ticker, exc, exc_info=True)
            errors.append({
                "ticker": ticker, "step": "kr_valuation",
                "error": str(exc), "ts": datetime.utcnow().isoformat(),
            })

    return {"prices": prices, "fundamentals": fundamentals,
            "valuations": valuations, "analysts": analysts, "errors": errors}


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    SMOKE_TICKER = "005930.KS"  # 삼성전자
    logger.info("=== 스모크 테스트: %s ===", SMOKE_TICKER)

    result = run_kr_ingest([SMOKE_TICKER])

    p_list = result["prices"].get(SMOKE_TICKER, [])
    f_list = result["fundamentals"].get(SMOKE_TICKER, [])
    errs = result["errors"]

    print(f"\n[가격] {len(p_list)} rows")
    if p_list:
        latest = p_list[-1]
        print(f"  최신: {latest.date}  close={latest.close}  volume={latest.volume}")
        assert latest.close is not None, "close는 None이면 안 됨"
        assert "N/A" not in str(latest.model_dump()), "N/A 문자열 금지"

    print(f"\n[재무] {len(f_list)} rows")
    for row in f_list[:4]:
        print(f"  {row.period_type} {row.period_end}: revenue={row.revenue}  op_margin={row.op_margin}")

    print(f"\n[에러] {len(errs)} 건")
    for e in errs:
        print(f"  {e}")
