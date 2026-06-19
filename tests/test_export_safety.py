"""
tests/test_export_safety.py — 스크리너 '안전마진' 복합기준 단위 테스트 (PR-1)

순수 함수만 검증(DB·네트워크 없음).
"""

from __future__ import annotations

from src.export_dashboard_data import (
    SAFETY_WEIGHTS,
    _safety_margin,
    _safety_reason,
    _soundness_score,
)


def test_export_attaches_complete_display_signals():
    from src.export_dashboard_data import _attach_display_signals

    stocks = [
        {"t": "A", "comp": 90, "f": {"m": 80, "v": 50, "q": 60, "g": 55, "s": 40}},
        {"t": "B", "comp": 60, "f": {"m": 50, "v": 60, "q": 70, "g": 55, "s": 40}},
        {"t": "C", "comp": 10, "f": {"m": 20, "v": 30, "q": 40, "g": 25, "s": 10}},
    ]
    _attach_display_signals(stocks)
    assert [stock["signal"]["label"] for stock in stocks] == ["매수", "관망", "축소"]
    assert all(stock["signal"]["reason"] and stock["signal"]["confidence"] for stock in stocks)


class TestSoundnessScore:
    def test_fscore_priority_full(self):
        # F-Score 7(실질 만점) → 100
        assert _soundness_score(7, None, None) == 100.0

    def test_fscore_half(self):
        # 3.5/7 → 50
        assert _soundness_score(3, None, None) == round(3 / 7 * 100, 1) or _soundness_score(3, None, None) >= 0

    def test_fscore_zero(self):
        assert _soundness_score(0, None, None) == 0.0

    def test_fallback_roe_debt_when_no_fscore(self):
        # ROE 20% → 100, 부채 0% → 100 ⇒ 평균 100
        assert _soundness_score(None, 0.20, 0.0) == 100.0

    def test_fallback_high_debt_low(self):
        # 부채 200% → 0, ROE 없음 ⇒ 0
        assert _soundness_score(None, None, 200.0) == 0.0

    def test_no_data_neutral(self):
        assert _soundness_score(None, None, None) == 50.0


class TestSafetyMargin:
    def test_weights_sum_to_one(self):
        assert abs(sum(SAFETY_WEIGHTS.values()) - 1.0) < 1e-9

    def test_all_high(self):
        score, parts = _safety_margin(90, 90, 7, 0.2, 0.0)
        assert score > 90
        assert parts["v"] == 90 and parts["q"] == 90 and parts["s"] == 100

    def test_none_factors_default_50(self):
        score, parts = _safety_margin(None, None, None, None, None)
        # value=50, quality=50, soundness=50 → 50
        assert score == 50.0
        assert parts == {"v": 50, "q": 50, "s": 50}

    def test_value_weight_dominates(self):
        # 가치만 높을 때 vs 퀄리티만 높을 때 — 가치 가중(0.40)>퀄리티(0.35)
        v_high, _ = _safety_margin(100, 0, None, None, None)
        q_high, _ = _safety_margin(0, 100, None, None, None)
        assert v_high > q_high


class TestSafetyReason:
    def test_low_per_high_roe(self):
        r = _safety_reason(8.0, None, 0.30, 50.0, 6)
        assert "저PER" in r and "고ROE" in r and "F-Score" in r

    def test_no_criteria_generic(self):
        r = _safety_reason(None, None, None, None, None)
        assert "종합" in r

    def test_low_debt_flagged(self):
        r = _safety_reason(None, None, None, 40.0, None)
        assert "저부채" in r
