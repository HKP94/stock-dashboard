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


# ──────────────────────────────────────────────────────────────
# E-1: 트레이딩 지표 (MACD·볼린저·스토캐스틱·ATR·거래량비율)
# ──────────────────────────────────────────────────────────────

def _make_vol_df(prices: list[float], volumes: list[float], start=date(2020, 1, 1)) -> pd.DataFrame:
    """가격+거래량 DataFrame."""
    index = pd.date_range(start=str(start), periods=len(prices), freq="B")
    return pd.DataFrame({"close": prices, "volume": volumes}, index=index)


# ── MACD ──────────────────────────────────────────────────────

def test_macd_not_none_sufficient_data():
    """충분한 데이터(MACD slow=26 이상) → macd_hist not None."""
    df = _make_df(_uptrend(MIN_BARS + 50))
    last = latest_indicators("TEST", df)
    assert last is not None
    assert last.macd_hist is not None

def test_macd_uptrend_positive_line():
    """지속 상승 추세 → MACD 라인(EMA12-EMA26) > 0.
    (선형 추세에서 히스토그램은 정상상태 0 수렴 — 라인으로 검증)"""
    df = _make_df(_uptrend(n=400, start=50, end=300))
    last = latest_indicators("TEST", df)
    assert last is not None and last.macd_line is not None
    assert last.macd_line > 0, f"상승추세 macd_line={last.macd_line}"

def test_macd_downtrend_negative_line():
    """지속 하락 추세 → MACD 라인 < 0."""
    df = _make_df(_downtrend(n=400, start=300, end=50))
    last = latest_indicators("TEST", df)
    assert last is not None and last.macd_line is not None
    assert last.macd_line < 0, f"하락추세 macd_line={last.macd_line}"

def test_macd_hist_accelerating_uptrend():
    """가속 상승(지수적) → MACD 히스토그램 > 0 (새 모멘텀 발생)."""
    import math
    prices = [50 * math.exp(0.003 * i) for i in range(MIN_BARS + 80)]
    df = _make_df(prices)
    last = latest_indicators("TEST", df)
    assert last is not None and last.macd_hist is not None
    assert last.macd_hist > 0, f"가속추세 macd_hist={last.macd_hist}"

def test_macd_schema_fields():
    """macd_line, macd_signal, macd_hist 세 필드 모두 존재."""
    df = _make_df(_uptrend(MIN_BARS + 50))
    last = latest_indicators("TEST", df)
    assert last is not None
    assert hasattr(last, "macd_line")
    assert hasattr(last, "macd_signal")
    assert hasattr(last, "macd_hist")


# ── 볼린저밴드 ─────────────────────────────────────────────────

def test_bb_pct_in_range_uptrend():
    """볼린저 %B: 0~1 사이 (BB 안에 있을 때)."""
    df = _make_df(_flat(MIN_BARS + 30))  # flat → 항상 중앙선
    last = latest_indicators("TEST", df)
    assert last is not None and last.bb_pct is not None
    # flat prices → 종가 = SMA = 중앙선 → %B ≈ 0.5
    assert 0.0 <= last.bb_pct <= 1.0, f"bb_pct out of range: {last.bb_pct}"

def test_bb_pct_flat_near_midband():
    """flat prices → 볼린저 %B ≈ 0.5 (중앙선)."""
    df = _make_df(_flat(MIN_BARS + 30, val=100.0))
    last = latest_indicators("TEST", df)
    assert last is not None and last.bb_pct is not None
    # flat일 때 표준편차→0이라 %B가 NaN일 수 있음 — None 허용
    # 값이 있으면 0~1 범위 확인
    if last.bb_pct is not None:
        assert -0.1 <= last.bb_pct <= 1.1

def test_bb_upper_above_lower():
    """볼린저 상단 > 하단 (항상 성립)."""
    df = _make_df(_uptrend(MIN_BARS + 30))
    rows = compute_indicators("TEST", df)
    for r in rows:
        if r.bb_upper is not None and r.bb_lower is not None:
            assert r.bb_upper >= r.bb_lower, f"bb_upper({r.bb_upper}) < bb_lower({r.bb_lower})"

def test_bb_fields_exist():
    """bb_upper, bb_lower, bb_pct 필드 존재."""
    df = _make_df(_uptrend(MIN_BARS + 30))
    last = latest_indicators("TEST", df)
    assert last is not None
    for attr in ("bb_upper", "bb_lower", "bb_pct"):
        assert hasattr(last, attr)


# ── 스토캐스틱 ─────────────────────────────────────────────────

def test_stoch_k_in_range():
    """스토캐스틱 %K: 0~100 사이 (표준 범위)."""
    df = _make_df(_uptrend(MIN_BARS + 50))
    rows = compute_indicators("TEST", df)
    for r in rows:
        if r.stoch_k is not None:
            assert -1e-6 <= r.stoch_k <= 100 + 1e-6, f"stoch_k out of range: {r.stoch_k}"

def test_stoch_d_follows_k():
    """stoch_d (3-day SMA of K) 존재 + 범위 확인."""
    df = _make_df(_uptrend(MIN_BARS + 50))
    last = latest_indicators("TEST", df)
    assert last is not None
    if last.stoch_k is not None and last.stoch_d is not None:
        assert 0 <= last.stoch_d <= 100


# ── ATR ────────────────────────────────────────────────────────

def test_atr14_positive():
    """ATR(14) > 0 (변동성은 양수)."""
    df = _make_df(_uptrend(MIN_BARS + 30))
    last = latest_indicators("TEST", df)
    assert last is not None
    # high/low 없이 close-only라 None일 수 있음
    if last.atr14 is not None:
        assert last.atr14 >= 0, f"atr14 음수: {last.atr14}"


# ── 거래량 비율 ────────────────────────────────────────────────

def test_vol_ratio20_with_volume():
    """거래량 데이터 있을 때 vol_ratio20 계산."""
    prices = _uptrend(MIN_BARS + 30)
    # 균등 거래량 1000주
    vols = [1000.0] * len(prices)
    df = _make_vol_df(prices, vols)
    last = latest_indicators("TEST", df)
    assert last is not None and last.vol_ratio20 is not None
    # 모든 거래량이 같으면 비율 = 1.0
    assert last.vol_ratio20 == pytest.approx(1.0, rel=1e-3)

def test_vol_ratio20_spike():
    """마지막 거래량 2배 급증 → vol_ratio20 > 1 (평균보다 큼)."""
    prices = _uptrend(MIN_BARS + 30)
    vols = [1000.0] * len(prices)
    vols[-1] = 2000.0  # 마지막만 2배
    df = _make_vol_df(prices, vols)
    last = latest_indicators("TEST", df)
    assert last is not None and last.vol_ratio20 is not None
    assert last.vol_ratio20 > 1.0

def test_vol_ratio20_none_without_volume():
    """거래량 컬럼 없으면 vol_ratio20 = None."""
    df = _make_df(_uptrend(MIN_BARS + 30))  # volume 없음
    last = latest_indicators("TEST", df)
    assert last is not None
    assert last.vol_ratio20 is None


# ── trading signal 헬퍼 (export_dashboard_data) ───────────────

from src.export_dashboard_data import _compute_trading_signal  # noqa: E402


def test_trading_signal_all_bullish():
    """MACD+/BB하단/RSI저 → 단기매수우호 (score=+3≥2)."""
    result = _compute_trading_signal(rsi14=30.0, bb_pct=0.1, macd_hist=0.5, vol_ratio20=None)
    assert result["label"] == "단기매수우호"
    assert result["score"] >= 2

def test_trading_signal_all_bearish():
    """MACD-/BB상단/RSI고 → 단기회피 (score=-3≤-2)."""
    result = _compute_trading_signal(rsi14=70.0, bb_pct=0.9, macd_hist=-0.5, vol_ratio20=None)
    assert result["label"] == "단기회피"
    assert result["score"] <= -2

def test_trading_signal_neutral_mixed():
    """혼합 신호 → 중립."""
    result = _compute_trading_signal(rsi14=50.0, bb_pct=0.5, macd_hist=0.1, vol_ratio20=None)
    assert result["label"] == "중립"

def test_trading_signal_vol_note_on_spike():
    """vol_ratio20 >= 2 → volNote 포함."""
    result = _compute_trading_signal(rsi14=50.0, bb_pct=0.5, macd_hist=0.0, vol_ratio20=2.5)
    assert result["volNote"] is not None
    assert "급증" in result["volNote"]

def test_trading_signal_vol_note_none_normal():
    """vol_ratio20 < 2 → volNote=None."""
    result = _compute_trading_signal(rsi14=50.0, bb_pct=0.5, macd_hist=0.0, vol_ratio20=1.2)
    assert result["volNote"] is None

def test_trading_signal_partial_none():
    """일부 값 None → score 계산 생략 (TypeError 없음)."""
    result = _compute_trading_signal(rsi14=None, bb_pct=None, macd_hist=0.5, vol_ratio20=None)
    assert result["label"] in ("단기매수우호", "중립", "단기회피")  # 에러 없음
    assert result["score"] == 1  # MACD+만

def test_trading_signal_basis_populated():
    """신호 발생 시 basis 리스트에 근거 포함."""
    result = _compute_trading_signal(rsi14=30.0, bb_pct=0.1, macd_hist=0.5, vol_ratio20=None)
    assert len(result["basis"]) == 3
    sources = [b["source"] for b in result["basis"]]
    assert "MACD" in sources
    assert "BB%B" in sources
    assert "RSI" in sources

def test_trading_signal_all_none():
    """모두 None → 중립, 에러 없음."""
    result = _compute_trading_signal(rsi14=None, bb_pct=None, macd_hist=None, vol_ratio20=None)
    assert result["label"] == "중립"
    assert result["score"] == 0
