"""
tests/test_rules.py — rules.py 단위 테스트

합성 데이터만 사용 (LLM·네트워크 호출 없음).
각 룰마다 True/False 케이스, 경계값, None 처리 검증.

⚠️ 테스트 합격이 투자 판단 근거가 되지 않습니다.
"""

from __future__ import annotations

import pytest

from src.rules import (
    DISPARITY_OVERHEAT,
    GOLDEN_CROSS_PROXIMITY,
    PLUNGE_PCT,
    RSI_OVERHEAT,
    RSI_OVERSOLD,
    SURGE_PCT,
    TARGET_PROXIMITY,
    check_rules,
    _check_dead_cross,
    _check_disparity_overheat,
    _check_golden_cross,
    _check_plunge,
    _check_rsi_overheat,
    _check_rsi_oversold,
    _check_surge,
    _check_target_proximity,
)


# ──────────────────────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────────────────────

def _has(flags: list[str], keyword: str) -> bool:
    return any(keyword in f for f in flags)


# ──────────────────────────────────────────────────────────────
# 룰 1: RSI 과열
# ──────────────────────────────────────────────────────────────

class TestRsiOverheat:
    def test_triggered(self):
        assert _check_rsi_overheat({"rsi14": 75.0}) is not None

    def test_not_triggered(self):
        assert _check_rsi_overheat({"rsi14": 65.0}) is None

    def test_at_threshold_not_triggered(self):
        # 경계값 70.0은 strictly >70 조건에서 해당 없음
        assert _check_rsi_overheat({"rsi14": RSI_OVERHEAT}) is None

    def test_just_above_threshold(self):
        assert _check_rsi_overheat({"rsi14": RSI_OVERHEAT + 0.01}) is not None

    def test_none_returns_none(self):
        assert _check_rsi_overheat({"rsi14": None}) is None

    def test_missing_key_returns_none(self):
        assert _check_rsi_overheat({}) is None

    def test_flag_contains_value(self):
        flag = _check_rsi_overheat({"rsi14": 75.0})
        assert "75.0" in flag
        assert "RSI 과열" in flag


# ──────────────────────────────────────────────────────────────
# 룰 2: RSI 침체
# ──────────────────────────────────────────────────────────────

class TestRsiOversold:
    def test_triggered(self):
        assert _check_rsi_oversold({"rsi14": 25.0}) is not None

    def test_not_triggered(self):
        assert _check_rsi_oversold({"rsi14": 40.0}) is None

    def test_at_threshold_not_triggered(self):
        # 경계값 30.0은 strictly <30 조건에서 해당 없음
        assert _check_rsi_oversold({"rsi14": RSI_OVERSOLD}) is None

    def test_just_below_threshold(self):
        assert _check_rsi_oversold({"rsi14": RSI_OVERSOLD - 0.01}) is not None

    def test_none_returns_none(self):
        assert _check_rsi_oversold({"rsi14": None}) is None

    def test_missing_key_returns_none(self):
        assert _check_rsi_oversold({}) is None

    def test_flag_contains_value(self):
        flag = _check_rsi_oversold({"rsi14": 25.0})
        assert "25.0" in flag
        assert "RSI 침체" in flag


# ──────────────────────────────────────────────────────────────
# 룰 3: 데드크로스 임박
# ──────────────────────────────────────────────────────────────

class TestDeadCross:
    def _ind(self, is_aligned: bool, slope50: float) -> dict:
        return {"is_aligned": is_aligned, "slope50": slope50, "sma50": 90.0, "sma200": 100.0}

    def test_triggered(self):
        # 정배열 아님 + 기울기 음수 → 데드크로스 임박
        assert _check_dead_cross(self._ind(False, -0.002)) is not None

    def test_not_triggered_aligned(self):
        # 정배열 상태에서는 해당 없음
        assert _check_dead_cross(self._ind(True, -0.002)) is None

    def test_not_triggered_positive_slope(self):
        # 정배열 아니지만 slope 양수 → 해당 없음
        assert _check_dead_cross(self._ind(False, 0.001)) is None

    def test_not_triggered_zero_slope(self):
        # slope = 0 → 해당 없음 (strictly < 0)
        assert _check_dead_cross(self._ind(False, 0.0)) is None

    def test_none_is_aligned_returns_none(self):
        assert _check_dead_cross({"is_aligned": None, "slope50": -0.002}) is None

    def test_none_slope_returns_none(self):
        assert _check_dead_cross({"is_aligned": False, "slope50": None}) is None

    def test_flag_text(self):
        flag = _check_dead_cross(self._ind(False, -0.002))
        assert flag == "데드크로스 임박"


# ──────────────────────────────────────────────────────────────
# 룰 4: 골든크로스 임박
# ──────────────────────────────────────────────────────────────

class TestGoldenCross:
    def _ind(self, is_aligned: bool, slope50: float, sma50: float, sma200: float = 100.0) -> dict:
        return {
            "is_aligned": is_aligned,
            "slope50": slope50,
            "sma50": sma50,
            "sma200": sma200,
        }

    def test_triggered(self):
        # 정배열 아님 + slope 양수 + SMA50이 SMA200의 99% (≥98%)
        ind = self._ind(False, 0.002, sma50=99.0, sma200=100.0)
        assert _check_golden_cross(ind) is not None

    def test_not_triggered_too_far(self):
        # SMA50이 SMA200의 96% (< 98%) → 해당 없음
        ind = self._ind(False, 0.002, sma50=96.0, sma200=100.0)
        assert _check_golden_cross(ind) is None

    def test_not_triggered_aligned(self):
        # 정배열 상태에서는 해당 없음
        ind = self._ind(True, 0.002, sma50=102.0, sma200=100.0)
        assert _check_golden_cross(ind) is None

    def test_not_triggered_negative_slope(self):
        # slope 음수 → 해당 없음
        ind = self._ind(False, -0.001, sma50=99.0, sma200=100.0)
        assert _check_golden_cross(ind) is None

    def test_at_proximity_threshold(self):
        # sma50 = sma200 × 0.98 (정확히 경계) → 해당 있음 (≥)
        sma200 = 100.0
        sma50 = sma200 * GOLDEN_CROSS_PROXIMITY  # 98.0
        ind = self._ind(False, 0.001, sma50=sma50, sma200=sma200)
        assert _check_golden_cross(ind) is not None

    def test_just_below_proximity_threshold(self):
        sma200 = 100.0
        sma50 = sma200 * GOLDEN_CROSS_PROXIMITY - 0.01  # 97.99
        ind = self._ind(False, 0.001, sma50=sma50, sma200=sma200)
        assert _check_golden_cross(ind) is None

    def test_missing_value_returns_none(self):
        assert _check_golden_cross({"is_aligned": False, "slope50": 0.001}) is None

    def test_flag_text(self):
        ind = self._ind(False, 0.002, sma50=99.0, sma200=100.0)
        flag = _check_golden_cross(ind)
        assert flag == "골든크로스 임박"


# ──────────────────────────────────────────────────────────────
# 룰 5: 목표가 근접
# ──────────────────────────────────────────────────────────────

class TestTargetProximity:
    def test_triggered(self):
        # 현재가 97 = 목표가 100의 97% (≥95%)
        ind = {"close": 97.0}
        ana = {"target_price": 100.0}
        assert _check_target_proximity(ind, ana) is not None

    def test_not_triggered(self):
        # 현재가 93 = 목표가 100의 93% (<95%)
        ind = {"close": 93.0}
        ana = {"target_price": 100.0}
        assert _check_target_proximity(ind, ana) is None

    def test_at_threshold(self):
        # 현재가 = 목표가 × 0.95 (정확히 경계) → 해당 있음 (≥)
        target = 100.0
        close = target * TARGET_PROXIMITY  # 95.0
        ind = {"close": close}
        ana = {"target_price": target}
        assert _check_target_proximity(ind, ana) is not None

    def test_above_target(self):
        # 현재가 > 목표가 → 해당 있음 (이미 초과)
        ind = {"close": 105.0}
        ana = {"target_price": 100.0}
        assert _check_target_proximity(ind, ana) is not None

    def test_none_close(self):
        assert _check_target_proximity({"close": None}, {"target_price": 100.0}) is None

    def test_none_target(self):
        assert _check_target_proximity({"close": 97.0}, {"target_price": None}) is None

    def test_zero_target(self):
        assert _check_target_proximity({"close": 97.0}, {"target_price": 0.0}) is None

    def test_flag_contains_upside(self):
        ind = {"close": 97.0}
        ana = {"target_price": 100.0}
        flag = _check_target_proximity(ind, ana)
        assert "목표가 근접" in flag
        assert "%" in flag

    def test_flag_upside_value_correct(self):
        # close=97, target=100 → 남은 상승여력 ≈ 3.1%
        ind = {"close": 97.0}
        ana = {"target_price": 100.0}
        flag = _check_target_proximity(ind, ana)
        assert "3.1" in flag


# ──────────────────────────────────────────────────────────────
# 룰 6: 급등
# ──────────────────────────────────────────────────────────────

class TestSurge:
    def test_triggered(self):
        assert _check_surge({"chg_pct": 8.0}) is not None

    def test_not_triggered(self):
        assert _check_surge({"chg_pct": 5.0}) is None

    def test_at_threshold(self):
        # 정확히 7% → 해당 있음 (≥7)
        assert _check_surge({"chg_pct": SURGE_PCT}) is not None

    def test_just_below_threshold(self):
        assert _check_surge({"chg_pct": SURGE_PCT - 0.01}) is None

    def test_none_returns_none(self):
        assert _check_surge({"chg_pct": None}) is None

    def test_flag_format(self):
        flag = _check_surge({"chg_pct": 8.5})
        assert "급등" in flag
        assert "+8.5%" in flag


# ──────────────────────────────────────────────────────────────
# 룰 7: 급락
# ──────────────────────────────────────────────────────────────

class TestPlunge:
    def test_triggered(self):
        assert _check_plunge({"chg_pct": -8.0}) is not None

    def test_not_triggered(self):
        assert _check_plunge({"chg_pct": -5.0}) is None

    def test_at_threshold(self):
        # 정확히 -7% → 해당 있음 (≤-7)
        assert _check_plunge({"chg_pct": PLUNGE_PCT}) is not None

    def test_just_above_threshold(self):
        assert _check_plunge({"chg_pct": PLUNGE_PCT + 0.01}) is None

    def test_none_returns_none(self):
        assert _check_plunge({"chg_pct": None}) is None

    def test_flag_format(self):
        flag = _check_plunge({"chg_pct": -9.1})
        assert "급락" in flag
        assert "-9.1%" in flag


# ──────────────────────────────────────────────────────────────
# 룰 8: 이격도 과열
# ──────────────────────────────────────────────────────────────

class TestDisparityOverheat:
    def test_triggered(self):
        assert _check_disparity_overheat({"disparity20": 120.0}) is not None

    def test_not_triggered(self):
        assert _check_disparity_overheat({"disparity20": 110.0}) is None

    def test_at_threshold_not_triggered(self):
        # 정확히 115.0 → strictly >115 이므로 해당 없음
        assert _check_disparity_overheat({"disparity20": DISPARITY_OVERHEAT}) is None

    def test_just_above_threshold(self):
        assert _check_disparity_overheat({"disparity20": DISPARITY_OVERHEAT + 0.01}) is not None

    def test_none_returns_none(self):
        assert _check_disparity_overheat({"disparity20": None}) is None

    def test_flag_contains_value(self):
        flag = _check_disparity_overheat({"disparity20": 118.5})
        assert "이격도 과열" in flag
        assert "118.5" in flag


# ──────────────────────────────────────────────────────────────
# check_rules 통합 테스트
# ──────────────────────────────────────────────────────────────

class TestCheckRules:
    def test_empty_dicts_return_empty_list(self):
        assert check_rules("TEST", {}, {}, {}) == []

    def test_no_flags_return_empty_list(self):
        ind = {
            "rsi14": 55.0,
            "is_aligned": True,
            "slope50": 0.001,
            "sma50": 110.0,
            "sma200": 100.0,
            "disparity20": 102.0,
            "close": 50.0,
            "chg_pct": 1.0,
        }
        ana = {"target_price": 200.0}
        assert check_rules("TEST", ind, {}, ana) == []

    def test_multiple_flags_returned(self):
        ind = {
            "rsi14": 75.0,          # RSI 과열
            "disparity20": 120.0,   # 이격도 과열
            "chg_pct": 8.0,         # 급등
            "close": 98.0,
        }
        ana = {"target_price": 100.0}  # 목표가 근접 (98%)
        flags = check_rules("TEST", ind, {}, ana)
        assert _has(flags, "RSI 과열")
        assert _has(flags, "이격도 과열")
        assert _has(flags, "급등")
        assert _has(flags, "목표가 근접")
        assert len(flags) == 4

    def test_returns_list_type(self):
        result = check_rules("TEST", {}, {}, {})
        assert isinstance(result, list)

    def test_none_values_no_flags(self):
        ind = {k: None for k in ["rsi14", "is_aligned", "slope50", "sma50", "sma200",
                                   "disparity20", "close", "chg_pct"]}
        assert check_rules("TEST", ind, {}, {"target_price": None}) == []

    def test_flag_strings_are_str_type(self):
        ind = {"rsi14": 75.0}
        flags = check_rules("TEST", ind, {}, {})
        for f in flags:
            assert isinstance(f, str)

    def test_ticker_does_not_affect_result(self):
        ind = {"rsi14": 75.0}
        flags_a = check_rules("AAPL", ind, {}, {})
        flags_b = check_rules("005930.KS", ind, {}, {})
        assert flags_a == flags_b

    def test_dead_cross_not_triggered_when_golden_cross_imminent(self):
        # 골든크로스 임박 상태: slope50 양수 → 데드크로스 미트리거
        ind = {
            "is_aligned": False,
            "slope50": 0.002,
            "sma50": 99.0,
            "sma200": 100.0,
        }
        flags = check_rules("TEST", ind, {}, {})
        assert not _has(flags, "데드크로스 임박")
        assert _has(flags, "골든크로스 임박")
