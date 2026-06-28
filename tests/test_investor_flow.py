"""
tests/test_investor_flow.py — E-2 투자자 수급 신호 단위 테스트

합성 데이터만 사용 (pykrx·네트워크·DB 의존 없음).
결정론 함수 _derive_investor_signal / _derive_combined_signal 검증.
"""

from __future__ import annotations

import pytest

from src.ingest_investor_flow import (
    _derive_combined_signal,
    _derive_investor_signal,
)


# ── _derive_investor_signal ────────────────────────────────────

def test_positive_net_returns_buy():
    """양수 순매수 → 매수우호."""
    assert _derive_investor_signal(1_000_000_000) == "매수우호"


def test_negative_net_returns_sell():
    """음수 순매수 → 매도우세."""
    assert _derive_investor_signal(-500_000_000) == "매도우세"


def test_zero_returns_neutral():
    """0원 → 중립."""
    assert _derive_investor_signal(0.0) == "중립"


def test_none_returns_neutral():
    """None → 중립 (데이터 없음)."""
    assert _derive_investor_signal(None) == "중립"


def test_small_positive_above_threshold():
    """기본 임계값 0에서 1원도 매수우호."""
    assert _derive_investor_signal(1.0) == "매수우호"


def test_small_negative_above_threshold():
    """기본 임계값 0에서 -1원도 매도우세."""
    assert _derive_investor_signal(-1.0) == "매도우세"


def test_large_buy():
    """수십억 순매수 → 매수우호."""
    assert _derive_investor_signal(50_000_000_000) == "매수우호"


def test_large_sell():
    """수십억 순매도 → 매도우세."""
    assert _derive_investor_signal(-50_000_000_000) == "매도우세"


# ── _derive_combined_signal ────────────────────────────────────

def test_both_buy_returns_strong():
    """외국인+기관 모두 매수우호 → 수급_강세."""
    assert _derive_combined_signal("매수우호", "매수우호") == "수급_강세"


def test_both_sell_returns_weak():
    """외국인+기관 모두 매도우세 → 수급_약세."""
    assert _derive_combined_signal("매도우세", "매도우세") == "수급_약세"


def test_foreign_buy_instit_sell_diverge():
    """외국인 매수 + 기관 매도 → 수급_혼조."""
    assert _derive_combined_signal("매수우호", "매도우세") == "수급_혼조"


def test_foreign_sell_instit_buy_diverge():
    """외국인 매도 + 기관 매수 → 수급_혼조."""
    assert _derive_combined_signal("매도우세", "매수우호") == "수급_혼조"


def test_one_neutral_returns_neutral():
    """한쪽 중립 → 중립."""
    assert _derive_combined_signal("중립", "매수우호") == "중립"
    assert _derive_combined_signal("매수우호", "중립") == "중립"


def test_both_neutral_returns_neutral():
    """양쪽 모두 중립 → 중립."""
    assert _derive_combined_signal("중립", "중립") == "중립"


def test_one_sell_one_neutral():
    """한쪽 매도 + 다른쪽 중립 → 중립 (다수가 한 방향이어야 수급_약세)."""
    assert _derive_combined_signal("매도우세", "중립") == "중립"
    assert _derive_combined_signal("중립", "매도우세") == "중립"


# ── 시나리오 테스트 ────────────────────────────────────────────

def test_scenario_typical_kr_strong_buying():
    """전형적 KR 외국인 집중 매수 시나리오."""
    f_3d = 100_000_000_000   # 외국인 3일 1000억 순매수
    i_3d = 20_000_000_000    # 기관 3일 200억 순매수
    f_sig = _derive_investor_signal(f_3d)
    i_sig = _derive_investor_signal(i_3d)
    combined = _derive_combined_signal(f_sig, i_sig)
    assert f_sig == "매수우호"
    assert i_sig == "매수우호"
    assert combined == "수급_강세"


def test_scenario_typical_divergence():
    """외국인 매도 + 기관 매수 혼조 시나리오."""
    f_3d = -80_000_000_000   # 외국인 순매도
    i_3d = 30_000_000_000    # 기관 순매수
    f_sig = _derive_investor_signal(f_3d)
    i_sig = _derive_investor_signal(i_3d)
    combined = _derive_combined_signal(f_sig, i_sig)
    assert f_sig == "매도우세"
    assert i_sig == "매수우호"
    assert combined == "수급_혼조"


def test_scenario_both_selling():
    """외국인+기관 동반 매도 → 수급_약세."""
    f_3d = -200_000_000_000
    i_3d = -50_000_000_000
    f_sig = _derive_investor_signal(f_3d)
    i_sig = _derive_investor_signal(i_3d)
    assert _derive_combined_signal(f_sig, i_sig) == "수급_약세"
