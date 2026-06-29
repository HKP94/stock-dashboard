"""
tests/test_compute_signal_track.py — 신규-F 신호 적중률 추적 단위 테스트

CI-safe: DB·LLM·네트워크 불요. 순수 계산 함수만 검증.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.compute_signal_track import (
    GRADE_NEUTRAL_BAND,
    benchmark_for,
    compute_returns,
    hit_excess,
    hit_raw,
    n_warning,
    resolve_entry_exit,
    spearman_ic,
)


# ── hit_excess ────────────────────────────────────────────────

def test_hit_excess_buy_positive():
    assert hit_excess("매수", 0.05) is True


def test_hit_excess_buy_zero():
    # excess=0은 매수 비적중 (strictly greater)
    assert hit_excess("매수", 0.0) is False


def test_hit_excess_buy_negative():
    assert hit_excess("매수", -0.03) is False


def test_hit_excess_sell_negative():
    assert hit_excess("축소", -0.05) is True


def test_hit_excess_sell_zero():
    # excess=0은 축소 비적중 (strictly less)
    assert hit_excess("축소", 0.0) is False


def test_hit_excess_sell_positive():
    assert hit_excess("축소", 0.02) is False


def test_hit_excess_hold_within_band():
    # |excess| <= GRADE_NEUTRAL_BAND → 관망 적중
    assert hit_excess("관망", 0.05) is True
    assert hit_excess("관망", -0.05) is True
    assert hit_excess("관망", GRADE_NEUTRAL_BAND) is True


def test_hit_excess_hold_outside_band():
    assert hit_excess("관망", GRADE_NEUTRAL_BAND + 0.001) is False
    assert hit_excess("관망", -(GRADE_NEUTRAL_BAND + 0.001)) is False


def test_hit_excess_unknown_grade():
    assert hit_excess("미확정", 0.1) is None


# ── hit_raw ───────────────────────────────────────────────────

def test_hit_raw_buy_positive():
    assert hit_raw("매수", 0.01) is True


def test_hit_raw_buy_negative():
    assert hit_raw("매수", -0.01) is False


def test_hit_raw_sell_negative():
    assert hit_raw("축소", -0.01) is True


# ── benchmark_for ─────────────────────────────────────────────

def test_benchmark_kr_default_is_kospi():
    assert benchmark_for("005930.KS", "KR") == "^KS11"


def test_benchmark_us_is_sp500():
    assert benchmark_for("AAPL", "US") == "^GSPC"


def test_benchmark_kosdaq_via_env(monkeypatch):
    monkeypatch.setenv("KOSDAQ_TICKERS", "091990.KQ,112040.KQ")
    # Reload to pick up env
    import importlib
    import src.compute_signal_track as m
    importlib.reload(m)
    assert m.benchmark_for("091990.KQ", "KR") == "^KQ11"
    assert m.benchmark_for("005930.KS", "KR") == "^KS11"
    importlib.reload(m)  # 원복


# ── resolve_entry_exit ────────────────────────────────────────

def _make_prices(dates: list[str], closes: list[float]) -> pd.DataFrame:
    df = pd.DataFrame({"close": closes}, index=pd.to_datetime(dates))
    df.index.name = "date"
    return df


def test_resolve_entry_next_day():
    # asof=2026-01-05, 다음 거래일=2026-01-06
    prices = _make_prices(["2026-01-05", "2026-01-06", "2026-01-07"], [100, 102, 104])
    r = resolve_entry_exit(prices, date(2026, 1, 5), n=1)
    assert r["entry_date"] == date(2026, 1, 6)
    assert r["entry_price"] == pytest.approx(102.0)


def test_resolve_exit_n_days():
    prices = _make_prices(
        ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"],
        [100, 102, 103, 105],
    )
    # asof=2026-01-05, entry=2026-01-06, n=2 → exit=2026-01-08
    r = resolve_entry_exit(prices, date(2026, 1, 5), n=2)
    assert r["entry_date"] == date(2026, 1, 6)
    assert r["exit_date"] == date(2026, 1, 8)
    assert r["exit_price"] == pytest.approx(105.0)
    assert r["pending"] is False


def test_resolve_pending_if_not_enough_data():
    prices = _make_prices(["2026-01-05", "2026-01-06", "2026-01-07"], [100, 102, 103])
    r = resolve_entry_exit(prices, date(2026, 1, 5), n=5)
    assert r["pending"] is True
    assert r["exit_date"] is None
    # entry는 채워짐
    assert r["entry_date"] == date(2026, 1, 6)


def test_resolve_no_prices_after_asof():
    prices = _make_prices(["2026-01-04", "2026-01-05"], [99, 100])
    r = resolve_entry_exit(prices, date(2026, 1, 5), n=1)
    assert r["pending"] is True
    assert r["entry_date"] is None


def test_resolve_exact_n_not_enough():
    # len(future) == n 이면 pending(>n 필요)
    prices = _make_prices(["2026-01-05", "2026-01-06", "2026-01-07"], [100, 102, 103])
    # asof=2026-01-05 → future = [01-06, 01-07] (len=2), n=2 → 2 > 2은 False → pending
    r = resolve_entry_exit(prices, date(2026, 1, 5), n=2)
    assert r["pending"] is True


# ── compute_returns ───────────────────────────────────────────

def test_compute_returns_basic():
    r = compute_returns(100.0, 110.0, 100.0, 105.0, "매수")
    assert r["raw_return"] == pytest.approx(0.10)
    assert r["bench_return"] == pytest.approx(0.05)
    assert r["excess_return"] == pytest.approx(0.05)
    assert r["hit_excess"] is True
    assert r["hit_raw"] is True


def test_compute_returns_no_bench():
    r = compute_returns(100.0, 90.0, None, None, "축소")
    assert r["raw_return"] == pytest.approx(-0.10)
    assert r["bench_return"] is None
    assert r["excess_return"] is None
    assert r["hit_excess"] is None
    assert r["hit_raw"] is True  # 축소 + raw < 0 → 적중


def test_compute_returns_buy_loss():
    r = compute_returns(100.0, 95.0, 100.0, 103.0, "매수")
    # raw=-5%, bench=+3%, excess=-8% → 매수 비적중
    assert r["raw_return"] == pytest.approx(-0.05)
    assert r["excess_return"] == pytest.approx(-0.08)
    assert r["hit_excess"] is False


def test_compute_returns_hold_within_band():
    # 매수 +1%, bench +1.5% → excess -0.5% → 관망 적중(|excess|<=10%)
    r = compute_returns(100.0, 101.0, 100.0, 101.5, "관망")
    assert abs(r["excess_return"]) <= GRADE_NEUTRAL_BAND
    assert r["hit_excess"] is True


# ── spearman_ic ───────────────────────────────────────────────

def test_spearman_ic_perfect_positive():
    # 3축 모두 달라야 타이 없이 IC=1.0
    grades = ["매수", "관망", "축소"]
    excesses = [0.05, 0.00, -0.05]
    result = spearman_ic(grades, excesses)
    assert result["ic"] == pytest.approx(1.0, abs=0.01)
    assert result["n"] == 3


def test_spearman_ic_negative():
    # 역방향
    grades = ["매수", "축소"]
    excesses = [-0.05, 0.05]
    result = spearman_ic(grades, excesses)
    assert result["ic"] < 0


def test_spearman_ic_insufficient_data():
    result = spearman_ic(["매수"], [0.05])
    assert result["ic"] is None
    assert result["n"] == 1


def test_spearman_ic_empty():
    result = spearman_ic([], [])
    assert result["ic"] is None
    assert result["n"] == 0


# ── n_warning ─────────────────────────────────────────────────

def test_n_warning_too_few():
    assert "참고 불가" in n_warning(5)


def test_n_warning_small():
    assert "추세 참고" in n_warning(15)


def test_n_warning_ok():
    assert n_warning(30) is None
    assert n_warning(100) is None
