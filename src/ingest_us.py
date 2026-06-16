"""
ingest_us.py — US 종목 가격·재무·밸류에이션·애널리스트 수집

소스: yfinance (US는 신뢰도 충분, FMP/Finnhub 연동은 Phase 2 TODO)

절대 규칙:
  - 결측값은 None (문자열 'N/A' 절대 금지)
  - 자동 주문·매매 코드 없음
  - 시크릿 하드코딩 금지
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf
from tenacity import (
    before_sleep_log,
    retry,
    stop_after_attempt,
    wait_exponential,
)

from src.schemas import AnalystRow, FundamentalsRow, PriceDailyRow, ValuationRow

logger = logging.getLogger(__name__)

# ── 상수 ─────────────────────────────────────────────────────────
PRICE_PERIOD: str = "2y"  # SMA200 계산에 최소 200봉 필요

# yfinance financials index 후보
_YF_REVENUE_LABELS: list[str] = ["Total Revenue", "Operating Revenue"]
_YF_OP_INCOME_LABELS: list[str] = ["Operating Income", "Operating Income Loss"]
_YF_NET_INCOME_LABELS: list[str] = ["Net Income", "Net Income Common Stockholders"]
# PR-2: 현금흐름 계정과목 후보
_YF_OCF_LABELS: list[str] = ["Operating Cash Flow", "Total Cash From Operating Activities", "Cash Flow From Continuing Operating Activities"]
_YF_CAPEX_LABELS: list[str] = ["Capital Expenditure", "Capital Expenditures", "Purchase Of PPE"]
_YF_FCF_LABELS: list[str] = ["Free Cash Flow"]


def _safe_float(val) -> Optional[float]:
    if val is None:
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


def _find_yf_value(df: pd.DataFrame, candidates: list[str], col) -> Optional[float]:
    """yfinance financials DataFrame에서 계정과목 후보를 찾아 값 반환."""
    for label in candidates:
        if label in df.index:
            try:
                val = df.loc[label, col]
                if pd.notna(val):
                    return float(val)
            except (KeyError, TypeError, ValueError):
                continue
    return None


# ──────────────────────────────────────────────────────────────
# 가격 수집
# ──────────────────────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _yf_history(ticker: str, period: str) -> pd.DataFrame:
    return yf.Ticker(ticker).history(period=period)


def fetch_us_prices(
    ticker: str,
    period: str = PRICE_PERIOD,
) -> list[PriceDailyRow]:
    """yfinance로 US 종목 일별 OHLCV 수집 (2년치 기본)."""
    df = _yf_history(ticker, period)
    if df.empty or len(df) < 5:
        logger.warning("%s: yfinance OHLCV 응답 없음", ticker)
        return []

    rows: list[PriceDailyRow] = []
    for idx, row in df.iterrows():
        dt: date = idx.date() if hasattr(idx, "date") else date.fromisoformat(str(idx)[:10])
        close = _safe_float(row.get("Close"))
        if close is None:
            continue

        rows.append(PriceDailyRow(
            ticker=ticker,
            date=dt,
            open=_safe_float(row.get("Open")),
            high=_safe_float(row.get("High")),
            low=_safe_float(row.get("Low")),
            close=close,
            volume=_safe_int(row.get("Volume")),
            source="yfinance",
        ))

    logger.info("%s: yfinance prices %d rows", ticker, len(rows))
    return rows


# ──────────────────────────────────────────────────────────────
# 재무 수집 (기존 main.py get_fundamental_data 이식)
# ──────────────────────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _yf_financials(ticker: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    stock = yf.Ticker(ticker)
    return stock.financials, stock.quarterly_financials


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _yf_cashflow(ticker: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """PR-2: 연간·분기 현금흐름표."""
    stock = yf.Ticker(ticker)
    return stock.cashflow, stock.quarterly_cashflow


def _cashflow_for(cf_df: Optional[pd.DataFrame], period_end: date) -> tuple[Optional[float], Optional[float]]:
    """현금흐름표에서 해당 기말의 (OCF, FCF) 추출. FCF는 직접값 우선, 없으면 OCF+CapEx(음수)."""
    if cf_df is None or cf_df.empty:
        return None, None
    # period_end와 일치하는 컬럼 탐색
    match_col = None
    for col in cf_df.columns:
        try:
            cd = col.date() if hasattr(col, "date") else date.fromisoformat(str(col)[:10])
        except (AttributeError, ValueError):
            continue
        if cd == period_end:
            match_col = col
            break
    if match_col is None:
        return None, None
    ocf = _find_yf_value(cf_df, _YF_OCF_LABELS, match_col)
    fcf = _find_yf_value(cf_df, _YF_FCF_LABELS, match_col)
    if fcf is None and ocf is not None:
        capex = _find_yf_value(cf_df, _YF_CAPEX_LABELS, match_col)
        if capex is not None:
            fcf = ocf + capex  # yfinance CapEx는 음수
    return ocf, fcf


def fetch_us_fundamentals(ticker: str) -> list[FundamentalsRow]:
    """yfinance로 US 종목 연간·분기 재무 + 현금흐름(OCF/FCF) 수집."""
    ann_df, qtr_df = _yf_financials(ticker)
    try:
        ann_cf, qtr_cf = _yf_cashflow(ticker)
    except Exception as exc:  # 현금흐름 실패가 재무 전체를 막지 않게
        logger.warning("%s: 현금흐름 수집 실패(무시): %s", ticker, exc)
        ann_cf, qtr_cf = None, None
    rows: list[FundamentalsRow] = []

    for df, cf_df, period_type in [(ann_df, ann_cf, "annual"), (qtr_df, qtr_cf, "quarter")]:
        if df is None or df.empty:
            continue
        for col in df.columns:
            # col은 pandas Timestamp
            try:
                period_end: date = col.date() if hasattr(col, "date") else date.fromisoformat(str(col)[:10])
            except (AttributeError, ValueError):
                logger.debug("%s: yfinance financials 컬럼 날짜 파싱 불가: %s", ticker, col)
                continue

            revenue = _find_yf_value(df, _YF_REVENUE_LABELS, col)
            op_income = _find_yf_value(df, _YF_OP_INCOME_LABELS, col)
            net_income = _find_yf_value(df, _YF_NET_INCOME_LABELS, col)
            op_margin = (
                op_income / revenue
                if revenue and op_income and revenue != 0
                else None
            )
            ocf, fcf = _cashflow_for(cf_df, period_end)

            rows.append(FundamentalsRow(
                ticker=ticker,
                period_type=period_type,
                period_end=period_end,
                revenue=revenue,
                op_income=op_income,
                op_margin=op_margin,
                net_income=net_income,
                ocf=ocf,
                fcf=fcf,
                source="yfinance",
            ))

    logger.info("%s: yfinance fundamentals %d rows", ticker, len(rows))
    return rows


# ──────────────────────────────────────────────────────────────
# 밸류에이션 (기존 main.py get_valuation_data 이식)
# ──────────────────────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _yf_info(ticker: str) -> dict:
    return yf.Ticker(ticker).info


def fetch_us_valuation(ticker: str, asof: Optional[date] = None) -> Optional[ValuationRow]:
    """yfinance info로 US 종목 밸류에이션 지표 수집."""
    info = _yf_info(ticker)
    asof = asof or date.today()

    roe = _safe_float(info.get("returnOnEquity"))
    roa = _safe_float(info.get("returnOnAssets"))

    row = ValuationRow(
        ticker=ticker,
        asof=asof,
        per_t=_safe_float(info.get("trailingPE")),
        per_f=_safe_float(info.get("forwardPE")),
        pbr=_safe_float(info.get("priceToBook")),
        ev_ebitda=_safe_float(info.get("enterpriseToEbitda")),
        roe=roe,
        roa=roa,
        debt_ratio=_safe_float(info.get("debtToEquity")),
        rev_growth=_safe_float(info.get("revenueGrowth")),
    )
    logger.info("%s: valuation per_f=%s pbr=%s roe=%s", ticker, row.per_f, row.pbr, row.roe)
    return row


# ──────────────────────────────────────────────────────────────
# 애널리스트 컨센서스 (기존 main.py get_analyst_data 이식)
# ──────────────────────────────────────────────────────────────

def fetch_us_analyst(ticker: str, asof: Optional[date] = None) -> Optional[AnalystRow]:
    """yfinance info로 US 종목 애널리스트 컨센서스 수집."""
    info = _yf_info(ticker)  # ValuationRow와 같은 호출이라 캐시 이점은 없지만 단순성 우선
    asof = asof or date.today()

    curr = _safe_float(info.get("currentPrice"))
    target = _safe_float(info.get("targetMeanPrice"))
    upside = ((target / curr) - 1) if (curr and target and curr != 0) else None

    rating_raw = info.get("recommendationKey")
    rating: Optional[str] = str(rating_raw).upper() if rating_raw else None

    row = AnalystRow(
        ticker=ticker,
        asof=asof,
        rating=rating,
        target_price=target,
        upside=upside,
        n_analysts=_safe_int(info.get("numberOfAnalystOpinions")),
    )
    logger.info(
        "%s: analyst rating=%s target=%s upside=%s",
        ticker, row.rating, row.target_price, row.upside,
    )
    return row


# ──────────────────────────────────────────────────────────────
# 배치 실행
# ──────────────────────────────────────────────────────────────

def run_us_ingest(tickers: list[str]) -> dict:
    """
    US 종목 배치 수집. 종목 단위 격리(try/except).
    반환: {"prices": {}, "fundamentals": {}, "valuations": {}, "analysts": {}, "errors": []}
    """
    prices: dict[str, list[PriceDailyRow]] = {}
    fundamentals: dict[str, list[FundamentalsRow]] = {}
    valuations: dict[str, Optional[ValuationRow]] = {}
    analysts: dict[str, Optional[AnalystRow]] = {}
    errors: list[dict] = []

    today = date.today()

    for ticker in tickers:
        try:
            prices[ticker] = fetch_us_prices(ticker)
        except Exception as exc:
            logger.error("%s: 가격 수집 실패: %s", ticker, exc, exc_info=True)
            errors.append({
                "ticker": ticker, "step": "price",
                "error": str(exc), "ts": datetime.utcnow().isoformat(),
            })

        try:
            fundamentals[ticker] = fetch_us_fundamentals(ticker)
        except Exception as exc:
            logger.error("%s: 재무 수집 실패: %s", ticker, exc, exc_info=True)
            errors.append({
                "ticker": ticker, "step": "fundamentals",
                "error": str(exc), "ts": datetime.utcnow().isoformat(),
            })

        try:
            valuations[ticker] = fetch_us_valuation(ticker, asof=today)
        except Exception as exc:
            logger.error("%s: 밸류에이션 수집 실패: %s", ticker, exc, exc_info=True)
            errors.append({
                "ticker": ticker, "step": "valuation",
                "error": str(exc), "ts": datetime.utcnow().isoformat(),
            })

        try:
            analysts[ticker] = fetch_us_analyst(ticker, asof=today)
        except Exception as exc:
            logger.error("%s: 애널리스트 수집 실패: %s", ticker, exc, exc_info=True)
            errors.append({
                "ticker": ticker, "step": "analyst",
                "error": str(exc), "ts": datetime.utcnow().isoformat(),
            })

    return {
        "prices": prices,
        "fundamentals": fundamentals,
        "valuations": valuations,
        "analysts": analysts,
        "errors": errors,
    }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    SMOKE_TICKER = "AAPL"
    logger.info("=== 스모크 테스트: %s ===", SMOKE_TICKER)

    result = run_us_ingest([SMOKE_TICKER])

    p_list = result["prices"].get(SMOKE_TICKER, [])
    f_list = result["fundamentals"].get(SMOKE_TICKER, [])
    val = result["valuations"].get(SMOKE_TICKER)
    ana = result["analysts"].get(SMOKE_TICKER)

    print(f"\n[가격] {len(p_list)} rows")
    if p_list:
        latest = p_list[-1]
        print(f"  최신: {latest.date}  close={latest.close}  volume={latest.volume}")
        assert latest.close is not None, "close는 None이면 안 됨"
        assert "N/A" not in str(latest.model_dump()), "N/A 문자열 금지"

    print(f"\n[재무] {len(f_list)} rows")
    for row in f_list[:4]:
        print(f"  {row.period_type} {row.period_end}: revenue={row.revenue}  op_margin={row.op_margin}")

    if val:
        print(f"\n[밸류에이션] per_f={val.per_f}  pbr={val.pbr}  roe={val.roe}")
    if ana:
        print(f"\n[애널리스트] rating={ana.rating}  target={ana.target_price}  upside={ana.upside}")

    errs = result["errors"]
    print(f"\n[에러] {len(errs)} 건")
    for e in errs:
        print(f"  {e}")

    print("\n⚠️ 투자 자문 아님 / 원금 손실 가능")
