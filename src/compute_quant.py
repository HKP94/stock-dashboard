"""
compute_quant.py — 팩터 스코어링 엔진 (PRD §F4)

점수·플래그·표시 신호는 결정론적으로 계산되며 자동 주문을 실행하지 않습니다.
   투자 판단과 결과의 책임은 전적으로 사용자에게 있습니다.

설계:
  - LLM 호출 없음 — 순수 Python/pandas/numpy
  - 데이터 없으면 50(중립) + "데이터 부족" flag
  - _fetch_market_history, _fetch_prices: 테스트 mock 포인트
  - 유니버스 전체 백분위 정규화 (0~100)
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

import psycopg

from src.db import get_conn, log_run_finish, log_run_start, upsert_quant_scores
from src.external_timeout import run_with_timeout
from src.rules import check_rules
from src.schemas import QuantScoresRow
from src.freshness import today_kst

logger = logging.getLogger(__name__)
YFINANCE_TIMEOUT_SECONDS: float = 20.0

# ── 레짐별 가중치 ─────────────────────────────────────────────
_REGIME_WEIGHTS: dict[str, dict[str, float]] = {
    "bull":    {"momentum": 0.45, "value": 0.20, "quality": 0.20, "growth": 0.10, "sentiment": 0.05},
    "neutral": {"momentum": 0.35, "value": 0.25, "quality": 0.25, "growth": 0.10, "sentiment": 0.05},
    "bear":    {"momentum": 0.10, "value": 0.35, "quality": 0.45, "growth": 0.05, "sentiment": 0.05},
}

# ── 상수 ─────────────────────────────────────────────────────
FSCORE_FILTER_THRESHOLD: int = 3

# 이상치 견고화: momentum은 z-score를 쓰므로 극단 수익률이 std를 부풀려 비이상치의 변별력을
# 압축한다. z-score 입력(수익률)을 오늘 크로스섹션 5/95 분위로 winsorize(§F7 룩어헤드 없음).
# 백분위(v/q/g/s)는 rank-불변이라 대상 아님(PM 결정: momentum z 입력만).
WINSOR_PCT: tuple[float, float] = (5.0, 95.0)
WINSOR_MIN_N: int = 10   # 유효표본 < 이 값이면 분위수 불안정 → 클립 생략(원본 유지)

# 금융 섹터(은행·보험·증권): 레버리지가 사업 본질이라 산업재식 부채 페널티·Piotroski가 부적합.
# watchlist.sector 값이 뒤섞여(insurance/Fiance오타/Financials 등) 있어 토큰 부분일치로 정규화.
# 'bond' 등 애매값은 제외(불명은 기존 로직 유지 — 비금융 회귀 방지).
_FINANCIAL_SECTOR_TOKENS: tuple[str, ...] = (
    "financ", "fiance", "insurance", "bank", "securities", "brokerage", "capital markets",
    "금융", "보험", "은행", "증권",
)


def _is_financial(sector: Optional[str]) -> bool:
    """섹터 문자열이 은행·보험·증권 계열이면 True(부분일치·대소문자 무시). 결측·불명은 False."""
    if not sector:
        return False
    s = sector.strip().lower()
    return any(tok in s for tok in _FINANCIAL_SECTOR_TOKENS)

IDIO_VOL_UNIV_PERCENTILE: float = 80.0
VIX_SPIKE_MULT: float = 1.15
KRW_SPIKE_MULT: float = 1.03

_F_MISSING = "데이터 부족"
_F_NO_SHARES = "발행주식수 데이터 없음"
_F_FILTERED = "사전필터 제외"


# ──────────────────────────────────────────────────────────────
# Mock 포인트 ① : 시장 지표 (레짐 감지용)
# ──────────────────────────────────────────────────────────────

def _fetch_market_history() -> pd.DataFrame:
    """
    yfinance로 ^KS11, ^GSPC, ^VIX, KRW=X 504일 다운로드.
    테스트: patch("src.compute_quant._fetch_market_history")
    반환 columns: kospi, sp500, vix, usdkrw  (DatetimeIndex)
    """
    symbols = {"^KS11": "kospi", "^GSPC": "sp500", "^VIX": "vix", "KRW=X": "usdkrw"}
    cols: list[pd.Series] = []
    for sym, col in symbols.items():
        try:
            df = run_with_timeout(YFINANCE_TIMEOUT_SECONDS, lambda sym=sym: yf.Ticker(sym).history(period="2y"))
            if not df.empty:
                cols.append(df["Close"].rename(col))
        except Exception as exc:
            logger.warning("시장 심볼 %s 실패: %s", sym, exc)
    return pd.concat(cols, axis=1) if cols else pd.DataFrame()


# ──────────────────────────────────────────────────────────────
# Mock 포인트 ② : 종목 가격 (prices_daily 테이블)
# ──────────────────────────────────────────────────────────────

def _fetch_prices(ticker: str, days: int, conn: psycopg.Connection) -> pd.DataFrame:
    """
    prices_daily에서 최근 days일치 close, volume 로드 (오름차순).
    테스트: patch("src.compute_quant._fetch_prices")
    반환 columns: close, volume  (DatetimeIndex)
    """
    sql = """
        SELECT date, close, volume
        FROM prices_daily
        WHERE ticker = %s
        ORDER BY date DESC
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (ticker, days))
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame(columns=["close", "volume"])
    df = pd.DataFrame([dict(r) for r in rows])
    df["date"] = pd.to_datetime(df["date"])
    # DB NUMERIC이 Decimal로 새어들면 np.log/나눗셈에서 TypeError → 읽기 경계에서 float 강제
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    return df.sort_values("date").set_index("date")


# ──────────────────────────────────────────────────────────────
# DB 조회 헬퍼 (패치 가능, conn 의존)
# ──────────────────────────────────────────────────────────────

# 날짜/문자열은 그대로 두고 수치형(Decimal 포함)만 float로 변환할 컬럼
_NUMERIC_COLS = frozenset({
    "revenue", "op_income", "op_margin", "net_income",
    "per_t", "per_f", "pbr", "ev_ebitda", "roe", "roa", "debt_ratio", "rev_growth",
    "target_price", "upside", "sentiment_score",
})


def _floatify(row: dict) -> dict:
    """DB 행의 NUMERIC(Decimal) 컬럼을 float로 변환(읽기 경계). None은 유지."""
    out = dict(row)
    for col in _NUMERIC_COLS:
        if col in out and out[col] is not None:
            try:
                out[col] = float(out[col])
            except (TypeError, ValueError):
                out[col] = None
    return out


# ──────────────────────────────────────────────────────────────
# 신규-A1: 시장 베타·상관 (자국 지수 대비, index_daily 저장 데이터·결정론·§F7 진짜 계산)
#   - 퀀트 축 안의 별도 시장 민감도 팩터(composite에 합산하지 않음).
#   - 라이브 yfinance가 아니라 index_daily(저장)를 써 재현성·무네트워크.
# ──────────────────────────────────────────────────────────────
BETA_WINDOW_DAYS = int(os.getenv("BETA_WINDOW_DAYS", "252"))   # 약 1년 거래일
BETA_MIN_OBS = int(os.getenv("BETA_MIN_OBS", "60"))           # 공통 거래일 최소 관측 수
# 벤치마크: KR→코스피, US→S&P500. 코스닥 상장은 ^KQ11.
# 코스닥 판별 자동화(pykrx 보드 엔드포인트)가 현재 불가 → 1차 ^KS11 기본 +
# 확정 코스닥 종목 allowlist(env KOSDAQ_TICKERS로 보강). 보드 자동 분류는 후속 백로그.
_KOSDAQ_DEFAULT: frozenset[str] = frozenset({"059090", "213420", "338220"})  # 미코·덕산네오룩스·뷰노


def _kosdaq_codes() -> set[str]:
    env = os.getenv("KOSDAQ_TICKERS", "")
    extra = {c.strip().split(".")[0] for c in env.split(",") if c.strip()}
    return set(_KOSDAQ_DEFAULT) | extra


def _market_benchmark(ticker: str, market: str) -> str:
    """종목의 벤치마크 지수 코드. US→^GSPC, KR→^KQ11(코스닥)·^KS11(코스피 기본)."""
    if market == "US":
        return "^GSPC"
    code = ticker.split(".")[0]
    return "^KQ11" if code in _kosdaq_codes() else "^KS11"


def _fetch_index_closes(conn: psycopg.Connection, index_code: str, days: int) -> pd.DataFrame:
    """index_daily에서 최근 days일치 종가(오름차순). 읽기 경계 float."""
    sql = "SELECT asof, close FROM index_daily WHERE index_code=%s ORDER BY asof DESC LIMIT %s"
    with conn.cursor() as cur:
        cur.execute(sql, (index_code, days))
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame(columns=["close"])
    df = pd.DataFrame([dict(r) for r in rows])
    df["asof"] = pd.to_datetime(df["asof"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df.sort_values("asof").set_index("asof")[["close"]]


def compute_beta_corr(
    price_df: pd.DataFrame,
    bench_df: pd.DataFrame,
    *,
    window: Optional[int] = None,
    min_obs: Optional[int] = None,
) -> tuple[Optional[float], Optional[float]]:
    """종목 vs 벤치마크 일간 수익률로 베타·상관 산출(OLS cov/var). 결측·부족 시 (None, None).

    beta = cov(x,y)/var(x), corr = cov/(std_x*std_y). x=지수 수익률, y=종목 수익률.
    §F7: asof까지의 과거 수익률만 사용하는 진짜 통계(룩어헤드 없음, 회고 아님).
    """
    window = window or BETA_WINDOW_DAYS
    min_obs = min_obs or BETA_MIN_OBS
    if price_df is None or price_df.empty or bench_df is None or bench_df.empty:
        return None, None
    rs = pd.to_numeric(price_df["close"], errors="coerce").pct_change(fill_method=None).dropna()
    rm = pd.to_numeric(bench_df["close"], errors="coerce").pct_change(fill_method=None).dropna()
    common = rs.index.intersection(rm.index)
    if len(common) < min_obs:
        return None, None
    common = common.sort_values()[-window:]
    y = rs.loc[common].to_numpy(dtype=float)
    x = rm.loc[common].to_numpy(dtype=float)
    xm = x - x.mean()
    ym = y - y.mean()
    var_x = float((xm ** 2).mean())
    if var_x == 0:
        return None, None
    cov = float((xm * ym).mean())
    beta = cov / var_x
    std_x = var_x ** 0.5
    std_y = float((ym ** 2).mean()) ** 0.5
    corr = cov / (std_x * std_y) if std_x > 0 and std_y > 0 else None
    return round(beta, 3), (round(corr, 3) if corr is not None else None)


def _fetch_ticker_market(ticker: str, conn: psycopg.Connection) -> str:
    sql = "SELECT market FROM watchlist WHERE ticker = %s"
    with conn.cursor() as cur:
        cur.execute(sql, (ticker,))
        row = cur.fetchone()
        return row["market"] if row else "US"


def _fetch_ticker_sector(ticker: str, conn: psycopg.Connection) -> Optional[str]:
    sql = "SELECT sector FROM watchlist WHERE ticker = %s"
    with conn.cursor() as cur:
        cur.execute(sql, (ticker,))
        row = cur.fetchone()
        return (row["sector"] if row else None)


def _fetch_fundamentals_annual(ticker: str, conn: psycopg.Connection) -> list[dict]:
    sql = """
        SELECT period_end, revenue, op_income, op_margin, net_income
        FROM fundamentals
        WHERE ticker = %s AND period_type = 'annual'
        ORDER BY period_end DESC LIMIT 2
    """
    with conn.cursor() as cur:
        cur.execute(sql, (ticker,))
        return [_floatify(r) for r in cur.fetchall()]


def _fetch_valuation_two(ticker: str, conn: psycopg.Connection) -> list[dict]:
    sql = """
        SELECT asof, per_t, per_f, pbr, ev_ebitda, roe, roa, debt_ratio, rev_growth
        FROM valuation WHERE ticker = %s
        ORDER BY asof DESC LIMIT 2
    """
    with conn.cursor() as cur:
        cur.execute(sql, (ticker,))
        return [_floatify(r) for r in cur.fetchall()]


def _fetch_analyst_records(
    ticker: str, conn: psycopg.Connection, asof: date
) -> tuple[Optional[dict], Optional[dict]]:
    """(최신 analyst, ~21일 전 analyst)"""
    asof_21 = asof - timedelta(days=21)
    asof_28 = asof - timedelta(days=28)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT target_price, upside FROM analyst WHERE ticker=%s AND asof<=%s ORDER BY asof DESC LIMIT 1",
            (ticker, asof),
        )
        row = cur.fetchone()
        latest = _floatify(row) if row else None

    with conn.cursor() as cur:
        cur.execute(
            "SELECT target_price FROM analyst WHERE ticker=%s AND asof>=%s AND asof<=%s ORDER BY asof ASC LIMIT 1",
            (ticker, asof_28, asof_21),
        )
        row = cur.fetchone()
        prev = _floatify(row) if row else None

    return latest, prev


def _fetch_sentiment_score(
    ticker: str, conn: psycopg.Connection, asof: date
) -> Optional[float]:
    sql = "SELECT sentiment_score FROM news_analysis WHERE ticker=%s AND asof=%s"
    with conn.cursor() as cur:
        cur.execute(sql, (ticker, asof))
        row = cur.fetchone()
        return float(row["sentiment_score"]) if row else None


# ──────────────────────────────────────────────────────────────
# 레짐 감지
# ──────────────────────────────────────────────────────────────

def compute_regime(market_df: pd.DataFrame) -> str:
    """
    Returns 'bull' | 'neutral' | 'bear'.
    bull  : sma200_bull AND NOT bear_24m AND NOT vix_spike
    bear  : bear_24m OR vix_spike
    neutral: 그 외 (데이터 부족 포함)
    """
    if market_df.empty or len(market_df) < 22:
        return "neutral"

    def _last(col: str) -> Optional[float]:
        if col not in market_df.columns:
            return None
        s = market_df[col].dropna()
        return float(s.iloc[-1]) if len(s) else None

    def _sma(col: str, w: int) -> Optional[float]:
        if col not in market_df.columns:
            return None
        s = market_df[col].dropna()
        if len(s) < w:
            return None
        return float(s.rolling(w).mean().iloc[-1])

    k, k200 = _last("kospi"), _sma("kospi", 200)
    s, s200 = _last("sp500"), _sma("sp500", 200)
    sma200_bull = (
        all(v is not None for v in [k, k200, s, s200])
        and k > k200 and s > s200
    )

    bear_24m = False
    if "kospi" in market_df.columns:
        ks = market_df["kospi"].dropna()
        if len(ks) >= 504:
            bear_24m = bool(np.log(ks.iloc[-1] / ks.iloc[-504]) < 0)

    vix_spike = False
    v, v20 = _last("vix"), _sma("vix", 20)
    if v is not None and v20 is not None:
        vix_spike = v > v20 * VIX_SPIKE_MULT

    if bear_24m or vix_spike:
        return "bear"
    if sma200_bull and not bear_24m and not vix_spike:
        return "bull"
    return "neutral"


# ──────────────────────────────────────────────────────────────
# Piotroski F-Score
# ──────────────────────────────────────────────────────────────

def piotroski_fscore(
    ticker: str, conn: psycopg.Connection
) -> tuple[int, list[str]]:
    """
    0~9점 (signals 7·8은 데이터 없어 0점, 최대 실질 7점).
    데이터 없으면 4(중간) + flag.
    """
    flags: list[str] = []
    funds = _fetch_fundamentals_annual(ticker, conn)
    vals = _fetch_valuation_two(ticker, conn)

    if not funds:
        flags.append(f"{_F_MISSING}(F-Score)")
        return 4, flags

    f0, f1 = funds[0], (funds[1] if len(funds) > 1 else None)
    v0, v1 = (vals[0] if vals else None), (vals[1] if len(vals) > 1 else None)

    score = 0

    # 수익성 4점
    if (f0.get("op_income") or 0) > 0:
        score += 1
    if v0 and (v0.get("roa") or 0) > 0:
        score += 1
    if (f0.get("op_margin") or 0) > 0:
        score += 1
    if f1 and (f0.get("op_margin") or 0) > (f1.get("op_margin") or 0):
        score += 1

    # 재무 건전성 3점
    if v0 and v1 and (v0.get("debt_ratio") or 0) < (v1.get("debt_ratio") or 0):
        score += 1
    if v0 and (v0.get("rev_growth") or 0) > 0:
        score += 1
    flags.append(_F_NO_SHARES)  # signal 7: 발행주식수 없음

    # 운영효율 2점 (signal 8: gross_margin 없음 → 0)
    if f1 and (f0.get("revenue") or 0) > (f1.get("revenue") or 0):
        score += 1

    return score, flags


# ──────────────────────────────────────────────────────────────
# 사전 필터
# ──────────────────────────────────────────────────────────────

def is_filtered(
    fscore: int,
    idio_vol: Optional[float],
    univ_p80: float,
    market: str,
    is_financial: bool = False,
) -> bool:
    """True이면 composite=None. 금융(은행·보험·증권)은 Piotroski가 부적합하므로 fscore
    사전필터를 적용하지 않는다(레버리지=사업본질 → 저fscore로 랭킹 전체 제외되던 왜곡 해소).
    고유변동성 필터는 섹터 무관하게 유지."""
    if not is_financial and fscore <= FSCORE_FILTER_THRESHOLD:
        return True
    if market == "KR" and idio_vol is not None and idio_vol > univ_p80:
        return True
    return False


# ──────────────────────────────────────────────────────────────
# 통계 헬퍼
# ──────────────────────────────────────────────────────────────

def _safe_pct_rank(values: dict[str, Optional[float]]) -> dict[str, float]:
    """None/NaN → 50(중립). 유효값 1개 이하면 모두 50."""
    valid = {k: v for k, v in values.items() if v is not None and np.isfinite(float(v))}
    if len(valid) < 2:
        return {k: 50.0 for k in values}
    s = pd.Series(valid)
    ranked = s.rank(pct=True) * 100
    return {k: float(ranked.get(k, 50.0)) for k in values}


def _zscore(values: dict[str, Optional[float]]) -> dict[str, float]:
    """Z-score 정규화. None/NaN → 0.0(중립)."""
    valid = {k: v for k, v in values.items() if v is not None and np.isfinite(float(v))}
    if len(valid) < 2:
        return {k: 0.0 for k in values}
    arr = np.array(list(valid.values()), dtype=float)
    std = arr.std()
    if std == 0:
        return {k: 0.0 for k in values}
    mean = arr.mean()
    z = {k: float((v - mean) / std) for k, v in valid.items()}
    return {k: z.get(k, 0.0) for k in values}


def _winsorize(values: dict[str, Optional[float]]) -> dict[str, Optional[float]]:
    """크로스섹션 이상치 클립: 오늘 유효값의 5/95 분위로 상하한(§F7 — 오늘 분포만, 룩어헤드 없음).

    None/NaN은 그대로 유지(결측은 클립 대상 아님). 유효표본 < WINSOR_MIN_N이면 분위수가
    불안정하므로 클립을 생략(원본 반환). z-score 입력 오염 방지 전용(백분위 팩터엔 미적용).
    """
    valid = [float(v) for v in values.values() if v is not None and np.isfinite(float(v))]
    if len(valid) < WINSOR_MIN_N:
        return dict(values)
    lo_b, hi_b = np.percentile(valid, WINSOR_PCT[0]), np.percentile(valid, WINSOR_PCT[1])
    return {
        k: (min(max(float(v), lo_b), hi_b) if v is not None and np.isfinite(float(v)) else None)
        for k, v in values.items()
    }


# ──────────────────────────────────────────────────────────────
# 고유변동성
# ──────────────────────────────────────────────────────────────

def _compute_idio_vol(
    price_df: pd.DataFrame, market_df: pd.DataFrame
) -> Optional[float]:
    """60일 OLS 잔차 표준편차."""
    if price_df.empty or len(price_df) < 20:
        return None
    close = pd.to_numeric(price_df["close"], errors="coerce")  # Decimal 방어
    ret = np.log(close / close.shift(1)).dropna()

    if "kospi" in market_df.columns and len(market_df["kospi"].dropna()) > 0:
        mret = market_df["kospi"].pct_change().reindex(ret.index).dropna()
        common = ret.index.intersection(mret.index)
        if len(common) >= 20:
            y = ret.loc[common].values.astype(float)
            x = mret.loc[common].values.astype(float)
            try:
                # 순수 numpy OLS: beta = cov(x,y)/var(x)
                xm = x - x.mean()
                ym = y - y.mean()
                var_x = (xm ** 2).mean()
                beta = (xm * ym).mean() / var_x if var_x != 0 else 0.0
                alpha = y.mean() - beta * x.mean()
                residuals = y - (beta * x + alpha)
                return float(np.std(residuals))
            except Exception:
                pass
    return float(ret.std())


# ──────────────────────────────────────────────────────────────
# 모멘텀 원시값 계산
# ──────────────────────────────────────────────────────────────

def _momentum_raw(
    prices: pd.DataFrame, ticker: str, flags: list[str]
) -> Optional[dict]:
    """M_1M, M_3M, M_6M, M_12M, vol_126 계산."""
    if prices.empty or len(prices) < 22:
        flags.append(f"{_F_MISSING}(모멘텀)")
        return None

    p = prices["close"].values.astype(float)
    n = len(p)

    if n < 252:
        flags.append(f"{_F_MISSING}(모멘텀 {n}일<252)")

    def lr(i_from: int, i_to: int) -> Optional[float]:
        if i_from < 0 or i_to < 0 or i_from >= n or i_to >= n or i_from == i_to:
            return None
        a, b = p[i_from], p[i_to]
        return float(np.log(b / a)) if a > 0 and b > 0 else None

    last = n - 1
    m_1m  = lr(max(0, last - 21), last)
    m_3m  = lr(max(0, last - 63), max(0, last - 5))
    m_6m  = lr(max(0, last - 126), max(0, last - 21))
    m_12m = lr(max(0, last - 252), max(0, last - 21))

    vol_126 = None
    if "volume" in prices.columns:
        v = prices["volume"].iloc[max(0, n - 126):]
        if len(v) and v.notna().any():
            vol_126 = float(v.dropna().mean())

    return {"m_1m": m_1m, "m_3m": m_3m, "m_6m": m_6m, "m_12m": m_12m, "vol_126": vol_126}


# ──────────────────────────────────────────────────────────────
# 팩터 점수 (유니버스 집계)
# ──────────────────────────────────────────────────────────────

def _score_momentum(
    raw_map: dict[str, Optional[dict]],
    flags_map: dict[str, list[str]],
) -> dict[str, float]:
    """모멘텀 팩터 0~100. 원시 데이터 없는 종목은 None → _safe_pct_rank가 50 반환."""
    # z-score 입력 수익률을 winsorize(이상치가 std를 부풀려 비이상치 변별력을 압축하는 것 방지).
    z1m  = _zscore(_winsorize({t: (r["m_1m"]  if r else None) for t, r in raw_map.items()}))
    z3m  = _zscore(_winsorize({t: (r["m_3m"]  if r else None) for t, r in raw_map.items()}))
    z6m  = _zscore(_winsorize({t: (r["m_6m"]  if r else None) for t, r in raw_map.items()}))
    z12m = _zscore(_winsorize({t: (r["m_12m"] if r else None) for t, r in raw_map.items()}))

    # 원시 데이터 없는 종목은 f_mom=None (→ combined=None → _safe_pct_rank 50)
    f_mom: dict[str, Optional[float]] = {}
    for t in raw_map:
        if raw_map[t] is None:
            f_mom[t] = None
        else:
            f_mom[t] = 0.10 * z1m[t] + 0.20 * z3m[t] + 0.30 * z6m[t] + 0.40 * z12m[t]

    # VCM
    m12_raw = {t: (r["m_12m"] if r else None) for t, r in raw_map.items()}
    vol_raw = {t: (r["vol_126"] if r else None) for t, r in raw_map.items()}
    m12_rank = _safe_pct_rank(m12_raw)
    vol_rank = _safe_pct_rank(vol_raw)
    vcm: dict[str, Optional[float]] = {
        t: ((m12_rank[t] / 100) * (1 - vol_rank[t] / 100) * 100 if raw_map[t] is not None else None)
        for t in raw_map
    }

    combined: dict[str, Optional[float]] = {
        t: (0.7 * f_mom[t] + 0.3 * vcm[t]
            if f_mom[t] is not None and vcm[t] is not None else None)
        for t in raw_map
    }
    return _safe_pct_rank(combined)


def _score_value(
    val_map: dict[str, Optional[dict]],
    flags_map: dict[str, list[str]],
) -> dict[str, float]:
    """가치 팩터 0~100."""
    def _inv1(v) -> Optional[float]:
        # 나눗셈 직전 float 캐스팅 — Decimal이 새어들어도 float/Decimal TypeError 방지
        if v is None:
            return None
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return (1.0 / f) if f != 0 else None

    def inv(d, key_f, key_t) -> Optional[float]:
        if d is None:
            return None
        return _inv1(d.get(key_f) or d.get(key_t))

    per_inv  = {t: inv(v, "per_f", "per_t") for t, v in val_map.items()}
    pbr_inv  = {t: (_inv1(v.get("pbr")) if v else None) for t, v in val_map.items()}
    ev_inv   = {t: (_inv1(v.get("ev_ebitda")) if v else None) for t, v in val_map.items()}

    for t, v in val_map.items():
        if v is None or (not v.get("per_f") and not v.get("per_t")):
            flags_map[t].append(f"{_F_MISSING}(PER)")

    v1 = _safe_pct_rank(per_inv)
    v2 = _safe_pct_rank(pbr_inv)
    v3 = _safe_pct_rank(ev_inv)
    return {t: (v1[t] + v2[t] + v3[t]) / 3 for t in val_map}


def _score_quality(
    val_map: dict[str, Optional[dict]],
    fscore_map: dict[str, int],
    flags_map: dict[str, list[str]],
    fund_map: Optional[dict[str, list[dict]]] = None,
    financial_map: Optional[dict[str, bool]] = None,
) -> dict[str, float]:
    """퀄리티 팩터 0~100. op_margin은 fundamentals에서 가져옴.

    **섹터 인지형**: 비금융은 종전 그대로(ROE·ROA·op_margin·역부채 4균등의 60% + fscore 40%).
    금융(은행·보험·증권)은 부채(레버리지=사업본질)·ROA(구조적 저값 횡단면 왜곡)·Piotroski(부적합)를
    제외하고 **ROE 중심**(+op_margin 있으면 평균)으로 계산 — discovery의 ROE 프록시와 방향 정합.
    """
    financial_map = financial_map or {}
    q1 = _safe_pct_rank({t: (v.get("roe") if v else None) for t, v in val_map.items()})
    q2 = _safe_pct_rank({t: (v.get("roa") if v else None) for t, v in val_map.items()})
    # op_margin: fundamentals 최신 연도에서 가져옴 (없으면 None → 50)
    op_m: dict[str, Optional[float]] = {}
    for t in val_map:
        funds = (fund_map or {}).get(t, [])
        op_m[t] = funds[0].get("op_margin") if funds else None
    q3 = _safe_pct_rank(op_m)
    # debt_ratio 낮을수록 좋음 → 역순
    dr  = _safe_pct_rank({t: (v.get("debt_ratio") if v else None) for t, v in val_map.items()})
    q4  = {t: 100.0 - dr[t] for t in val_map}

    fs_scores = _safe_pct_rank({t: float(fscore_map.get(t, 4)) for t in val_map})
    out: dict[str, float] = {}
    for t in val_map:
        if financial_map.get(t):
            parts = [q1[t]]                       # ROE(백분위) 중심
            if op_m.get(t) is not None:
                parts.append(q3[t])               # op_margin 있으면 함께
            out[t] = sum(parts) / len(parts)
        else:
            qmj = (q1[t] + q2[t] + q3[t] + q4[t]) / 4
            out[t] = 0.6 * qmj + 0.4 * fs_scores[t]
    return out


def _score_growth(
    fund_map: dict[str, list[dict]],
    val_map: dict[str, Optional[dict]],
    analyst_map: dict[str, tuple[Optional[dict], Optional[dict]]],
    flags_map: dict[str, list[str]],
) -> dict[str, float]:
    """성장 팩터 0~100."""
    rev_growth = {t: (v["rev_growth"] if v else None) for t, v in val_map.items()}

    op_growth: dict[str, Optional[float]] = {}
    for t, funds in fund_map.items():
        if len(funds) >= 2:
            o0 = funds[0].get("op_income") or 0
            o1 = funds[1].get("op_income") or 0
            op_growth[t] = ((o0 - o1) / abs(o1)) if o1 != 0 else None
        else:
            op_growth[t] = None

    g3: dict[str, float] = {}
    for t, (latest, prev_21) in analyst_map.items():
        if latest and prev_21:
            cur_tgt = latest.get("target_price")
            prv_tgt = prev_21.get("target_price")
            if cur_tgt and prv_tgt:
                g3[t] = 100.0 if cur_tgt > prv_tgt else 0.0
            else:
                g3[t] = 50.0
        elif latest:
            up = latest.get("upside") or 0.0
            g3[t] = 70.0 if up > 0.10 else 40.0
        else:
            g3[t] = 50.0

    g1 = _safe_pct_rank(rev_growth)
    g2 = _safe_pct_rank(op_growth)
    return {t: 0.4 * g1[t] + 0.4 * g2[t] + 0.2 * g3[t] for t in val_map}


def _score_sentiment(
    sent_map: dict[str, Optional[float]],
) -> dict[str, float]:
    """감성 팩터 0~100."""
    return _safe_pct_rank(sent_map)


# ──────────────────────────────────────────────────────────────
# 메인 함수
# ──────────────────────────────────────────────────────────────

def compute_quant_universe(
    tickers: list[str],
    conn: psycopg.Connection,
    asof: Optional[date] = None,
) -> list[QuantScoresRow]:
    """
    유니버스 전체 퀀트 점수 계산.

    반환값은 표시 전용이며 주문 실행 경로가 없습니다.
    """
    asof = asof or today_kst()
    if not tickers:
        return []

    # 레짐 — yfinance 실패해도 전체가 멈추지 않게 neutral 폴백
    try:
        market_df = _fetch_market_history()
        regime = compute_regime(market_df)
    except Exception as exc:
        logger.warning("레짐 감지 실패(%s) → 'neutral' 폴백", exc)
        market_df = pd.DataFrame()
        regime = "neutral"
    weights = _REGIME_WEIGHTS[regime]
    logger.info("레짐=%s 가중치=%s", regime, weights)

    # 종목별 원시 데이터 수집
    flags_map: dict[str, list[str]] = {t: [] for t in tickers}
    markets: dict[str, str] = {}
    fin_map: dict[str, bool] = {}   # 금융 섹터(은행·보험·증권) 여부 — 섹터 인지형 quality/필터
    fscore_map: dict[str, int] = {}
    prices_252: dict[str, pd.DataFrame] = {}
    prices_60: dict[str, pd.DataFrame] = {}
    val_map: dict[str, Optional[dict]] = {}
    fund_map: dict[str, list[dict]] = {}
    analyst_map: dict[str, tuple] = {}
    sent_map: dict[str, Optional[float]] = {}
    idio_vol_map: dict[str, Optional[float]] = {}
    beta_map: dict[str, Optional[float]] = {}
    corr_map: dict[str, Optional[float]] = {}

    # 신규-A1: 벤치마크 지수 종가를 1회 로드·캐시(종목마다 재쿼리 금지). index_daily 저장 데이터.
    bench_cache: dict[str, pd.DataFrame] = {}
    for idx_code in ("^KS11", "^KQ11", "^GSPC"):
        try:
            bench_cache[idx_code] = _fetch_index_closes(conn, idx_code, BETA_WINDOW_DAYS + 40)
        except Exception as exc:
            logger.warning("벤치마크 %s 로드 실패(베타 None 처리): %s", idx_code, exc)
            bench_cache[idx_code] = pd.DataFrame(columns=["close"])

    for ticker in tickers:
        markets[ticker] = _fetch_ticker_market(ticker, conn)
        fin_map[ticker] = _is_financial(_fetch_ticker_sector(ticker, conn))
        fs, fflags = piotroski_fscore(ticker, conn)
        fscore_map[ticker] = fs
        flags_map[ticker].extend(fflags)

        prices_252[ticker] = _fetch_prices(ticker, 252, conn)
        prices_60[ticker]  = _fetch_prices(ticker, 60, conn)

        idio_vol_map[ticker] = _compute_idio_vol(prices_60[ticker], market_df)
        # 시장 베타·상관(자국 지수, index_daily). 결측·부족 시 None(0·추정 금지).
        bench_df = bench_cache.get(_market_benchmark(ticker, markets[ticker]))
        beta_map[ticker], corr_map[ticker] = compute_beta_corr(prices_252[ticker], bench_df)

        v_rows = _fetch_valuation_two(ticker, conn)
        val_map[ticker] = v_rows[0] if v_rows else None
        fund_map[ticker] = _fetch_fundamentals_annual(ticker, conn)
        analyst_map[ticker] = _fetch_analyst_records(ticker, conn, asof)
        sent_map[ticker] = _fetch_sentiment_score(ticker, conn, asof)

    # 고유변동성 80th percentile (KR 필터용)
    valid_ivols = [v for v in idio_vol_map.values() if v is not None]
    univ_p80 = float(np.percentile(valid_ivols, IDIO_VOL_UNIV_PERCENTILE)) if valid_ivols else float("inf")

    # 모멘텀 원시값
    mom_raw: dict[str, Optional[dict]] = {}
    for ticker in tickers:
        mom_raw[ticker] = _momentum_raw(prices_252[ticker], ticker, flags_map[ticker])

    # 팩터 점수 (유니버스 백분위)
    mom_scores  = _score_momentum(mom_raw, flags_map)
    val_scores  = _score_value(val_map, flags_map)
    qual_scores = _score_quality(val_map, fscore_map, flags_map, fund_map, fin_map)
    grow_scores = _score_growth(fund_map, val_map, analyst_map, flags_map)
    sent_scores = _score_sentiment(sent_map)

    # 복합 점수 & QuantScoresRow 생성
    results: list[QuantScoresRow] = []
    for ticker in tickers:
        filtered = is_filtered(fscore_map[ticker], idio_vol_map.get(ticker), univ_p80,
                               markets[ticker], is_financial=fin_map[ticker])

        mom  = mom_scores.get(ticker, 50.0)
        val  = val_scores.get(ticker, 50.0)
        qual = qual_scores.get(ticker, 50.0)
        grow = grow_scores.get(ticker, 50.0)
        sent = sent_scores.get(ticker, 50.0)

        if filtered:
            composite = None
            flags_map[ticker].append(_F_FILTERED)
        else:
            composite = (
                weights["momentum"]  * mom
                + weights["value"]   * val
                + weights["quality"] * qual
                + weights["growth"]  * grow
                + weights["sentiment"] * sent
            )

        # rules.py 알림 플래그
        latest_price = prices_252[ticker]
        ind_dict: dict = {}
        if not latest_price.empty:
            row = latest_price.iloc[-1]
            ind_dict = {
                "close":       float(row.get("close", 0)) if row.get("close") else None,
                "rsi14":       None,
                "sma50":       None,
                "sma200":      None,
                "slope50":     None,
                "is_aligned":  None,
                "disparity20": None,
                "chg_pct":     None,
            }
        ana_latest, _ = analyst_map.get(ticker, (None, None))
        ana_dict = ana_latest or {}
        rule_flags = check_rules(ticker, ind_dict, {"composite": composite}, ana_dict)
        flags_map[ticker].extend(rule_flags)

        results.append(
            QuantScoresRow(
                ticker=ticker,
                asof=asof,
                momentum=round(mom, 2),
                value=round(val, 2),
                quality=round(qual, 2),
                growth=round(grow, 2),
                sentiment=round(sent, 2),
                composite=round(composite, 2) if composite is not None else None,
                # 금융은 Piotroski 부적합 → fscore=None 저장(스크리너 안전마진이 ROE·부채 폴백 사용).
                fscore=None if fin_map.get(ticker) else fscore_map.get(ticker),
                flags=flags_map[ticker],
                beta=beta_map.get(ticker),          # 신규-A1: 시장 민감도(별도 팩터, composite 미합산)
                market_corr=corr_map.get(ticker),
            )
        )

    return results


# ──────────────────────────────────────────────────────────────
# 실행 진입점
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info("=== compute_quant 시작 ===")

    with get_conn() as conn:
        run_id = log_run_start(conn, "compute_quant")
        errors: list[dict] = []
        status = "success"

        try:
            sql = "SELECT ticker FROM watchlist WHERE active=TRUE"
            with conn.cursor() as cur:
                cur.execute(sql)
                tickers = [r["ticker"] for r in cur.fetchall()]
            logger.info("유니버스 %d종목", len(tickers))

            rows = compute_quant_universe(tickers, conn)
            upsert_quant_scores(conn, rows)
            logger.info("compute_quant 완료: %d행 저장", len(rows))

        except Exception as exc:
            logger.error("compute_quant 오류: %s", exc, exc_info=True)
            errors.append({"step": "compute_quant", "error": str(exc), "ts": datetime.utcnow().isoformat()})
            status = "failed"

        log_run_finish(conn, run_id, status=status, errors=errors)
