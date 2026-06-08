"""
tests/test_indicators.py — compute_indicators 단위 테스트

합성 데이터만 사용 (LLM·네트워크 호출 없음).
검증 항목:
  - 데이터 부족 → 빈 리스트
  - SMA 값 정확성 (flat prices)
  - 이격도 = close / SMA20 * 100
  - RSI 범위 0~100
  - is_aligned = True (상승 추세)
  - is_aligned = False (하락 추세)
  - flat prices → is_aligned = False (기울기 = 0, 양수 조건 불충족)
  - 출력 ticker 일치
  - 출력 날짜 오름차순
  - N/A 문자열 없음
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.compute_indicators import MIN_BARS, SMA_LONG, compute_indicators, latest_indicators


# ──────────────────────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────────────────────

def _make_df(prices: list[float], start: date = date(2020, 1, 1)) -> pd.DataFrame:
    """가격 리스트 → DatetimeIndex DataFrame (close 컬럼)."""
    index = pd.date_range(start=str(start), periods=len(prices), freq="B")
    return pd.DataFrame({"close": prices}, index=index)


def _flat(n: int, val: float = 100.0) -> list[float]:
    return [val] * n


def _uptrend(n: int, start: float = 100.0, end: float = 300.0) -> list[float]:
    return [start + (end - start) * i / (n - 1) for i in range(n)]


def _downtrend(n: int, start: float = 300.0, end: float = 100.0) -> list[float]:
    return [start + (end - start) * i / (n - 1) for i in range(n)]


# ──────────────────────────────────────────────────────────────
# 기본 동작
# ──────────────────────────────────────────────────────────────

def test_insufficient_data_returns_empty():
    df = _make_df(_flat(MIN_BARS - 1))
    assert compute_indicators("TEST", df) == []


def test_exactly_min_bars_raises_no_error():
    df = _make_df(_flat(MIN_BARS))
    rows = compute_indicators("TEST", df)
    # SMA200+SLOPE_WINDOW 충족 → 적어도 1행
    assert isinstance(rows, list)


def test_sufficient_data_returns_rows():
    df = _make_df(_flat(MIN_BARS + 20))
    rows = compute_indicators("TEST", df)
    assert len(rows) > 0


def test_empty_df_returns_empty():
    df = pd.DataFrame({"close": []})
    assert compute_indicators("TEST", df) == []


# ──────────────────────────────────────────────────────────────
# SMA 값 검증
# ──────────────────────────────────────────────────────────────

def test_sma_flat_prices_equal_close():
    """flat prices → 모든 SMA == close."""
    val = 150.0
    df = _make_df(_flat(MIN_BARS + 20, val=val))
    rows = compute_indicators("TEST", df)
    assert len(rows) > 0
    for r in rows:
        assert r.sma20 == pytest.approx(val, rel=1e-5)
        assert r.sma50 == pytest.approx(val, rel=1e-5)
        assert r.sma200 == pytest.approx(val, rel=1e-5)


def test_sma_manual_last_row():
    """마지막 20개 평균 = SMA20 수동 검증."""
    prices = list(range(1, MIN_BARS + 21))  # 1, 2, ..., MIN_BARS+20
    df = _make_df(prices)
    rows = compute_indicators("TEST", df)
    assert len(rows) > 0
    last = rows[-1]
    expected_sma20 = float(np.mean(prices[-20:]))
    assert last.sma20 == pytest.approx(expected_sma20, rel=1e-4)


# ──────────────────────────────────────────────────────────────
# 이격도 검증
# ──────────────────────────────────────────────────────────────

def test_disparity_flat_prices():
    """flat prices → 이격도 == 100.0."""
    df = _make_df(_flat(MIN_BARS + 10, val=200.0))
    rows = compute_indicators("TEST", df)
    for r in rows:
        assert r.disparity20 == pytest.approx(100.0, rel=1e-5)


def test_disparity_formula():
    """이격도 = close / SMA20 * 100 수동 검증."""
    prices = _flat(MIN_BARS + 10, val=100.0)
    prices[-1] = 120.0  # 마지막 봉만 120
    df = _make_df(prices)
    rows = compute_indicators("TEST", df)
    last = rows[-1]
    # SMA20 = average of last 20 prices
    sma20_expected = float(np.mean(prices[-20:]))
    expected = 120.0 / sma20_expected * 100
    assert last.disparity20 == pytest.approx(expected, rel=1e-4)


# ──────────────────────────────────────────────────────────────
# RSI 범위
# ──────────────────────────────────────────────────────────────

def test_rsi_in_range():
    """RSI 14 값은 0~100 사이 (부동소수점 오차 1e-6 허용)."""
    df = _make_df(_uptrend(MIN_BARS + 50))
    rows = compute_indicators("TEST", df)
    for r in rows:
        if r.rsi14 is not None:
            assert -1e-6 <= r.rsi14 <= 100 + 1e-6, f"RSI out of range: {r.rsi14}"


def test_rsi_downtrend_low():
    """지속 하락 → RSI 낮음 (<50)."""
    df = _make_df(_downtrend(MIN_BARS + 50))
    rows = compute_indicators("TEST", df)
    last = rows[-1]
    if last.rsi14 is not None:
        assert last.rsi14 < 50


def test_rsi_uptrend_high():
    """지속 상승 → RSI 높음 (>50)."""
    df = _make_df(_uptrend(MIN_BARS + 50))
    rows = compute_indicators("TEST", df)
    last = rows[-1]
    if last.rsi14 is not None:
        assert last.rsi14 > 50


# ──────────────────────────────────────────────────────────────
# 정배열 (is_aligned)
# ──────────────────────────────────────────────────────────────

def test_is_aligned_true_uptrend():
    """장기 상승 추세 → 최후 구간에서 is_aligned=True."""
    df = _make_df(_uptrend(n=400, start=100, end=300))
    rows = compute_indicators("TEST", df)
    # 마지막 10행 중 is_aligned=True가 하나 이상
    last = [r for r in rows[-10:] if r.is_aligned is not None]
    assert any(r.is_aligned for r in last), (
        f"uptrend에서 is_aligned=True가 없음: {[(r.date, r.is_aligned) for r in last]}"
    )


def test_is_aligned_false_downtrend():
    """장기 하락 추세 → is_aligned=False."""
    df = _make_df(_downtrend(n=400, start=300, end=100))
    rows = compute_indicators("TEST", df)
    last = [r for r in rows[-10:] if r.is_aligned is not None]
    assert all(not r.is_aligned for r in last), (
        f"downtrend에서 is_aligned=True 발생: {[(r.date, r.is_aligned) for r in last]}"
    )


def test_is_aligned_false_flat():
    """flat prices → 기울기 = 0 → is_aligned=False (양수 기울기 조건 미충족)."""
    df = _make_df(_flat(MIN_BARS + 30))
    rows = compute_indicators("TEST", df)
    last = [r for r in rows[-10:] if r.is_aligned is not None]
    assert all(not r.is_aligned for r in last)


# ──────────────────────────────────────────────────────────────
# 출력 메타데이터
# ──────────────────────────────────────────────────────────────

def test_ticker_in_all_rows():
    df = _make_df(_flat(MIN_BARS + 10))
    rows = compute_indicators("AAPL", df)
    for r in rows:
        assert r.ticker == "AAPL"


def test_dates_ascending():
    df = _make_df(_flat(MIN_BARS + 20))
    rows = compute_indicators("TEST", df)
    dates = [r.date for r in rows]
    assert dates == sorted(dates), "날짜가 오름차순이 아님"


def test_no_na_string_in_output():
    """결측은 None, 문자열 'N/A' 금지."""
    df = _make_df(_uptrend(MIN_BARS + 20))
    rows = compute_indicators("TEST", df)
    for r in rows:
        assert "N/A" not in str(r.model_dump()), "N/A 문자열이 출력에 포함됨"


# ──────────────────────────────────────────────────────────────
# latest_indicators 헬퍼
# ──────────────────────────────────────────────────────────────

def test_latest_indicators_returns_single_row():
    df = _make_df(_flat(MIN_BARS + 10))
    row = latest_indicators("TEST", df)
    assert row is not None
    assert row.ticker == "TEST"


def test_latest_indicators_returns_none_on_insufficient():
    df = _make_df(_flat(5))
    assert latest_indicators("TEST", df) is None


def test_latest_indicators_is_last_row():
    df = _make_df(_flat(MIN_BARS + 10))
    rows = compute_indicators("TEST", df)
    latest = latest_indicators("TEST", df)
    assert latest is not None and rows
    assert latest.date == rows[-1].date
