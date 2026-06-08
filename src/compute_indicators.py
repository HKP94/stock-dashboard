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
    close: pd.Series = df["close"].astype(float)

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

    rows: list[IndicatorDailyRow] = []
    for idx, row in df.iterrows():
        if pd.isna(row["sma200"]):  # SMA200 미완성 구간 스킵
            continue

        dt: date = idx.date() if hasattr(idx, "date") else idx
        is_aligned: Optional[bool] = (
            bool(aligned_raw.loc[idx]) if all_present.loc[idx] else None
        )

        rows.append(IndicatorDailyRow(
            ticker=ticker,
            date=dt,
            sma20=_safe_float(row["sma20"]),
            sma50=_safe_float(row["sma50"]),
            sma200=_safe_float(row["sma200"]),
            rsi14=_safe_float(row["rsi14"]),
            disparity20=_safe_float(row["disparity20"]),
            slope50=_safe_float(row["slope50"]),
            slope200=_safe_float(row["slope200"]),
            is_aligned=is_aligned,
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
