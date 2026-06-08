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
from datetime import date, datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
from tenacity import (
    before_sleep_log,
    retry,
    stop_after_attempt,
    wait_exponential,
)

from src.schemas import FundamentalsRow, PriceDailyRow

logger = logging.getLogger(__name__)

# ── 상수 ─────────────────────────────────────────────────────────
PRICE_LOOKBACK_DAYS: int = 730   # 2년치 (compute_indicators SMA200 용)
FS_BGN_YEARS: int = 4            # DART 재무 조회 연수

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

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _pykrx_ohlcv(code: str, fromdate: str, todate: str) -> pd.DataFrame:
    from pykrx import stock as pykrx_stock  # 지연 임포트 (단위 테스트 격리)
    return pykrx_stock.get_market_ohlcv_by_date(fromdate, todate, code)


def fetch_kr_prices(
    ticker: str,
    lookback_days: int = PRICE_LOOKBACK_DAYS,
) -> list[PriceDailyRow]:
    """pykrx로 KR 종목 일별 OHLCV 수집."""
    code = _clean_ticker(ticker)
    today = date.today()
    fromdate = (today - timedelta(days=lookback_days)).strftime("%Y%m%d")
    todate = today.strftime("%Y%m%d")

    df = _pykrx_ohlcv(code, fromdate, todate)
    if df.empty:
        logger.warning("%s: pykrx OHLCV 응답 없음", ticker)
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

    logger.info("%s: pykrx %d rows (%s~%s)", ticker, len(rows), fromdate, todate)
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

    s = str(col).strip()

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


def _find_fs_value(
    df: pd.DataFrame,
    candidates: frozenset[str],
    col,
) -> Optional[float]:
    """재무제표 DataFrame에서 계정과목 후보를 찾아 값 반환."""
    if df is None or df.empty:
        return None

    # MultiIndex / 단순 Index 공통 처리
    idx_lv0 = (
        df.index.get_level_values(0)
        if isinstance(df.index, pd.MultiIndex)
        else df.index
    )

    for label in candidates:
        mask = idx_lv0 == label
        if not mask.any():
            continue
        try:
            val = df.loc[mask].iloc[0][col]
            if pd.notna(val):
                return float(val)
        except (KeyError, IndexError, TypeError, ValueError):
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

    rows: list[FundamentalsRow] = []
    for col in is_df.columns:
        period_end = _parse_dart_col_date(col)
        if period_end is None:
            logger.debug("%s: DART 컬럼 날짜 파싱 불가 — %s", ticker, col)
            continue

        revenue = _find_fs_value(is_df, _REVENUE_LABELS, col)
        op_income = _find_fs_value(is_df, _OP_INCOME_LABELS, col)
        net_income = _find_fs_value(is_df, _NET_INCOME_LABELS, col)
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
def _dart_load_fs(corp, bgn_de: str, fs_tp: str, report_tp: str):
    return corp.load_fs(bgn_de=bgn_de, fs_tp=fs_tp, report_tp=report_tp)


def fetch_kr_fundamentals(ticker: str) -> list[FundamentalsRow]:
    """dart-fss로 KR 종목 연간·분기 재무 수집."""
    import dart_fss as dart  # 지연 임포트

    dart.set_api_key(api_key=_get_dart_api_key())
    code = _clean_ticker(ticker)
    bgn_de = (date.today() - timedelta(days=365 * FS_BGN_YEARS)).strftime("%Y%m%d")

    # 기업 검색
    corp_list = dart.get_corp_list()
    corps = corp_list.find_by_stock_code(code)
    if not corps:
        logger.warning("%s: DART 기업 코드 없음 (code=%s)", ticker, code)
        return []
    corp = corps[0]
    logger.info("%s: DART 기업 = %s", ticker, getattr(corp, "corp_name", corp))

    rows: list[FundamentalsRow] = []

    for period_type, rpt_tp in [("annual", "annual"), ("quarter", "quarter")]:
        loaded = False
        for fs_tp in ("CFS", "OFS"):  # 연결 우선, 실패 시 개별
            try:
                fs = _dart_load_fs(corp, bgn_de=bgn_de, fs_tp=fs_tp, report_tp=rpt_tp)
                parsed = _parse_fs_rows(ticker, fs, period_type)
                if parsed:
                    rows.extend(parsed)
                    loaded = True
                    break
            except Exception as e:
                logger.warning(
                    "%s: DART %s %s 실패: %s", ticker, period_type, fs_tp, e
                )
        if not loaded:
            logger.warning("%s: DART %s 재무 로드 실패 (CFS/OFS 모두)", ticker, period_type)

    logger.info("%s: dart-fss %d fundamentals rows", ticker, len(rows))
    return rows


# ──────────────────────────────────────────────────────────────
# 배치 실행 (n8n Execute Command 또는 직접 호출)
# ──────────────────────────────────────────────────────────────

def run_kr_ingest(tickers: list[str]) -> dict:
    """
    KR 종목 배치 수집. 종목 단위 격리(try/except).
    반환: {"prices": {ticker: [...]}, "fundamentals": {ticker: [...]}, "errors": [...]}
    """
    prices: dict[str, list[PriceDailyRow]] = {}
    fundamentals: dict[str, list[FundamentalsRow]] = {}
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
            fundamentals[ticker] = fetch_kr_fundamentals(ticker)
        except Exception as exc:
            logger.error("%s: 재무 수집 실패: %s", ticker, exc, exc_info=True)
            errors.append({
                "ticker": ticker, "step": "fundamentals",
                "error": str(exc), "ts": datetime.utcnow().isoformat(),
            })

    return {"prices": prices, "fundamentals": fundamentals, "errors": errors}


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

    print("\n⚠️ 투자 자문 아님 / 원금 손실 가능")
