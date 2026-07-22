"""
compute_indicators.py — 기술적 지표 계산 (LLM·네트워크 호출 없음)

입력: ticker + DataFrame(index=date, 'close' column)
출력: list[IndicatorDailyRow]

상수:
  SMA_SHORT  = 20    SMA20
  SMA_MID    = 50    SMA50
  SMA_LONG   = 200   SMA200
  RSI_PERIOD = 14
  SLOPE_WINDOW = 10  선형회귀 기울기 윈도우 (종가 정규화)
  MIN_BARS   = SMA_LONG + SLOPE_WINDOW (지표 계산 최소 봉 수)
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
import pandas_ta as ta

from src.schemas import IndicatorDailyRow

logger = logging.getLogger(__name__)

# ── 상수 ─────────────────────────────────────────────────────────
SMA_SHORT: int = 20
SMA_MID: int = 50
SMA_LONG: int = 200
RSI_PERIOD: int = 14
SLOPE_WINDOW: int = 10
MIN_BARS: int = SMA_LONG + SLOPE_WINDOW

# E-1: 트레이딩 지표 상수
MACD_FAST: int = 12
MACD_SLOW: int = 26
MACD_SIGNAL: int = 9
BB_PERIOD: int = 20
BB_STD: float = 2.0
STOCH_K: int = 14
STOCH_D: int = 3
ATR_PERIOD: int = 14

# E-1: 트레이딩 신호 임계값 (4팩터, 합계≥2 → 신호 발생)
TRADING_RSI_LOW: float = 35.0    # 침체권 → 반등 기대
TRADING_RSI_HIGH: float = 65.0   # 과열권 → 조정 경계
TRADING_BB_LOW: float = 0.2      # 볼린저 하단 → 과매도
TRADING_BB_HIGH: float = 0.8     # 볼린저 상단 → 과매수
TRADING_STOCH_LOW: float = 20.0  # 스토캐스틱 과매도
TRADING_STOCH_HIGH: float = 80.0 # 스토캐스틱 과매수


def _derive_trading_signal(
    rsi14: Optional[float],
    bb_pct: Optional[float],
    macd_hist: Optional[float],
    stoch_k: Optional[float],
) -> tuple[str, int]:
    """4팩터(MACD/볼린저/RSI/스토캐스틱) 결정론 트레이딩 신호.
    합계 ≥+2 → 단기매수우호, ≤-2 → 단기회피, 나머지 → 중립.
    반환: (label, score)
    """
    score = 0
    if macd_hist is not None:
        score += 1 if macd_hist > 0 else (-1 if macd_hist < 0 else 0)
    if bb_pct is not None:
        score += 1 if bb_pct < TRADING_BB_LOW else (-1 if bb_pct > TRADING_BB_HIGH else 0)
    if rsi14 is not None:
        score += 1 if rsi14 < TRADING_RSI_LOW else (-1 if rsi14 > TRADING_RSI_HIGH else 0)
    if stoch_k is not None:
        score += 1 if stoch_k < TRADING_STOCH_LOW else (-1 if stoch_k > TRADING_STOCH_HIGH else 0)

    if score >= 2:
        return "단기매수우호", score
    elif score <= -2:
        return "단기회피", score
    return "중립", score


def _safe_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
        return None if np.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _rolling_slope(series: pd.Series, window: int = SLOPE_WINDOW) -> pd.Series:
    """
    rolling window 내 선형회귀 기울기 (종가 정규화).
    slope / last_value → 같은 퍼센트 변화가 같은 기울기값을 갖도록 스케일 독립.
    """
    def _slope(arr: np.ndarray) -> float:
        if np.any(np.isnan(arr)):
            return np.nan
        x = np.arange(len(arr), dtype=float)
        slope_val = np.polyfit(x, arr, 1)[0]
        last = arr[-1]
        return float(slope_val / last) if last != 0 else np.nan

    return series.rolling(window).apply(_slope, raw=True)


def compute_indicators(ticker: str, price_df: pd.DataFrame) -> list[IndicatorDailyRow]:
    """
    price_df: DatetimeIndex, 'close' column 필수.
    MIN_BARS 미만이면 빈 리스트 반환.
    """
    if price_df.empty or len(price_df) < MIN_BARS:
        logger.warning(
            "%s: 데이터 부족 (%d봉 < MIN_BARS %d), 지표 계산 스킵",
            ticker, len(price_df), MIN_BARS,
        )
        return []

    df = price_df.sort_index().copy()
    # DB NUMERIC이 Decimal로 새어들 수 있으므로 읽기 경계에서 float로 강제
    # (Decimal/float 혼용 시 pandas-ta·나눗셈에서 TypeError 발생)
    df["close"] = df["close"].astype(float)
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    close: pd.Series = df["close"]
    has_volume = "volume" in df.columns and df["volume"].notna().any()

    # ── SMA ──────────────────────────────────────────────────
    df["sma20"] = ta.sma(close, length=SMA_SHORT)
    df["sma50"] = ta.sma(close, length=SMA_MID)
    df["sma200"] = ta.sma(close, length=SMA_LONG)

    # ── RSI ──────────────────────────────────────────────────
    df["rsi14"] = ta.rsi(close, length=RSI_PERIOD)

    # ── 이격도 (disparity20) = close / SMA20 * 100 ───────────
    df["disparity20"] = np.where(
        df["sma20"].notna() & (df["sma20"] != 0),
        df["close"] / df["sma20"] * 100,
        np.nan,
    )

    # ── 추세기울기 ────────────────────────────────────────────
    df["slope50"] = _rolling_slope(df["sma50"])
    df["slope200"] = _rolling_slope(df["sma200"])

    # ── 정배열: SMA50 > SMA200 AND 두 기울기 모두 양수 ───────
    # 어느 한 값이라도 NaN이면 None
    all_present = df[["sma50", "sma200", "slope50", "slope200"]].notna().all(axis=1)
    aligned_raw: pd.Series = (
        (df["sma50"] > df["sma200"])
        & (df["slope50"] > 0)
        & (df["slope200"] > 0)
    )

    # ── E-1: 트레이딩 지표 ────────────────────────────────────
    # MACD(12,26,9)
    _macd = ta.macd(close, fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL)
    if _macd is not None and not _macd.empty:
        df["macd_line"]   = _macd.iloc[:, 0]
        df["macd_hist"]   = _macd.iloc[:, 1]
        df["macd_signal"] = _macd.iloc[:, 2]
    else:
        df["macd_line"] = df["macd_hist"] = df["macd_signal"] = np.nan

    # 볼린저밴드(20,2)
    _bb = ta.bbands(close, length=BB_PERIOD, std=BB_STD)
    if _bb is not None and not _bb.empty:
        # pandas_ta bbands: BBL, BBM, BBU, BBB, BBP
        bb_col = {c.split("_")[0]: c for c in _bb.columns}
        df["bb_lower"] = _bb[bb_col.get("BBL", _bb.columns[0])]
        df["bb_upper"] = _bb[bb_col.get("BBU", _bb.columns[2])]
        # BBP는 pandas_ta가 이미 0~1 범위로 반환 (close < BBL이면 음수, > BBU이면 1 초과)
        df["bb_pct"]   = _bb[bb_col.get("BBP", _bb.columns[4])]
    else:
        df["bb_lower"] = df["bb_upper"] = df["bb_pct"] = np.nan

    # 스토캐스틱(14,3) — high/low 필요, 없으면 close 대체
    if "high" in df.columns and "low" in df.columns:
        _stoch = ta.stoch(
            df["high"].astype(float), df["low"].astype(float), close,
            k=STOCH_K, d=STOCH_D,
        )
    else:
        # ponytail: close-only stochastic approximation (no high/low data)
        _stoch = ta.stoch(close, close, close, k=STOCH_K, d=STOCH_D)
    if _stoch is not None and not _stoch.empty:
        df["stoch_k"] = _stoch.iloc[:, 0]
        df["stoch_d"] = _stoch.iloc[:, 1]
    else:
        df["stoch_k"] = df["stoch_d"] = np.nan

    # ATR(14) — high/low 없으면 None
    if "high" in df.columns and "low" in df.columns:
        _atr = ta.atr(df["high"].astype(float), df["low"].astype(float), close, length=ATR_PERIOD)
        df["atr14"] = _atr if _atr is not None else np.nan
    else:
        df["atr14"] = np.nan

    # 거래량 대비 20일 평균 비율
    if has_volume:
        vol_sma20 = df["volume"].rolling(20).mean()
        df["vol_ratio20"] = np.where(
            vol_sma20.notna() & (vol_sma20 > 0),
            df["volume"] / vol_sma20,
            np.nan,
        )
    else:
        df["vol_ratio20"] = np.nan

    rows: list[IndicatorDailyRow] = []
    for idx, row in df.iterrows():
        if pd.isna(row["sma200"]):  # SMA200 미완성 구간 스킵
            continue

        dt: date = idx.date() if hasattr(idx, "date") else idx
        is_aligned: Optional[bool] = (
            bool(aligned_raw.loc[idx]) if all_present.loc[idx] else None
        )

        _rsi   = _safe_float(row["rsi14"])
        _bb_p  = _safe_float(row["bb_pct"])
        _mhist = _safe_float(row["macd_hist"])
        _sk    = _safe_float(row["stoch_k"])
        _sig_label, _sig_score = _derive_trading_signal(_rsi, _bb_p, _mhist, _sk)

        rows.append(IndicatorDailyRow(
            ticker=ticker,
            date=dt,
            sma20=_safe_float(row["sma20"]),
            sma50=_safe_float(row["sma50"]),
            sma200=_safe_float(row["sma200"]),
            rsi14=_rsi,
            disparity20=_safe_float(row["disparity20"]),
            slope50=_safe_float(row["slope50"]),
            slope200=_safe_float(row["slope200"]),
            is_aligned=is_aligned,
            macd_line=_safe_float(row["macd_line"]),
            macd_signal=_safe_float(row["macd_signal"]),
            macd_hist=_mhist,
            bb_upper=_safe_float(row["bb_upper"]),
            bb_lower=_safe_float(row["bb_lower"]),
            bb_pct=_bb_p,
            stoch_k=_sk,
            stoch_d=_safe_float(row["stoch_d"]),
            vol_ratio20=_safe_float(row["vol_ratio20"]),
            atr14=_safe_float(row["atr14"]),
            trading_signal=_sig_label,
            trading_signal_score=_sig_score,
        ))

    logger.info("%s: compute_indicators %d rows", ticker, len(rows))
    return rows


def latest_indicators(
    ticker: str,
    price_df: pd.DataFrame,
) -> Optional[IndicatorDailyRow]:
    """최신 1행만 반환 (n8n 단일 종목 연산 용)."""
    rows = compute_indicators(ticker, price_df)
    return rows[-1] if rows else None


# ──────────────────────────────────────────────────────────────
# DB 엔트리포인트: prices_daily 전체 → 지표 계산 → indicators_daily upsert
#   db 의존은 함수 내부에서 지연 임포트(순수 계산 단위 테스트 격리 유지)
# ──────────────────────────────────────────────────────────────

def _load_price_df_from_db(ticker: str, conn) -> pd.DataFrame:
    """prices_daily → DatetimeIndex DataFrame(close, volume)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT date, high, low, close, volume FROM prices_daily WHERE ticker = %s ORDER BY date ASC",
            (ticker,),
        )
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame(columns=["close", "volume"])
    df = pd.DataFrame([dict(r) for r in rows])
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")


def recompute_indicators_to_db(conn, tickers: Optional[list[str]] = None) -> int:
    """
    prices_daily 기준으로 지표를 계산해 indicators_daily에 upsert(+종목별 commit).
    외부 시세 재수집 없이 DB 데이터만 사용.

    tickers=None이면 prices_daily에 존재하는 모든 종목 대상.
    반환: 저장(1행 이상 upsert)된 종목 수.
    """
    from src.db import upsert_indicators_daily  # 지연 임포트

    if tickers is None:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT ticker FROM prices_daily ORDER BY ticker")
            tickers = [r["ticker"] for r in cur.fetchall()]

    saved = 0
    for ticker in tickers:
        try:
            df = _load_price_df_from_db(ticker, conn)
            rows = compute_indicators(ticker, df)
            if rows:
                upsert_indicators_daily(conn, rows)
                conn.commit()  # 종목별 커밋 → 부분 실패 격리
                saved += 1
                logger.info("%s: indicators_daily upsert %d행 (commit)", ticker, len(rows))
            else:
                logger.warning("%s: 지표 0행 (데이터 부족) — 스킵", ticker)
        except Exception as exc:
            conn.rollback()
            logger.error("%s: 지표 계산/저장 실패 — %s", ticker, exc, exc_info=True)

    logger.info("recompute_indicators_to_db: %d/%d 종목 저장", saved, len(tickers))
    return saved


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    from src.db import get_conn, log_run_finish, log_run_start

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info("=== compute_indicators 단독 재계산 시작 ===")
    with get_conn() as conn:
        run_id = log_run_start(conn, "recompute_indicators")
        try:
            n = recompute_indicators_to_db(conn)
            log_run_finish(conn, run_id, status="success" if n else "partial", errors=[])
            logger.info("=== 완료: %d종목 indicators 저장 ===", n)
        except Exception as exc:
            conn.rollback()
            log_run_finish(conn, run_id, status="failed", errors=[{"error": str(exc)}])
            raise
