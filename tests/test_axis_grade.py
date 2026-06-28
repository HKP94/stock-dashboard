"""
tests/test_axis_grade.py — 신규-A2 매력도 3축 종합 등급(결정론)

- 등급 규칙 테이블 전 분기(세 축 정렬→매수, 충돌→관망, 다수 약→축소, 한 축만 강→관망)
- 결측 축(컨센서스·내 판단 없음) 처리 + 단일 축 신뢰도 '하'
- 시장·베타 보정 비대칭(약세+고베타 보수화 / 강세 미상향)
- 합산이 아님(정렬 패턴) · build_action_frame 통합 · 폴백 해설
CI-safe: DB·LLM·네트워크 불요.
"""

from __future__ import annotations

from collections import Counter

from src.stock_action_advice import (
    GRADE_BETA_HIGH,
    build_action_frame,
    derive_grade,
    grade_fallback_rationale,
)


def _stock(comp=None, up=None, attractiveness=None, beta=None, **kw):
    s = {"t": "X", "f": {}, "comp": comp, "up": up, "beta": beta}
    if attractiveness is not None:
        s["note"] = {"attractiveness": attractiveness}
    s.update(kw)
    return s


# ── 정렬 패턴 → 등급 ────────────────────────────────────────────

def test_three_axes_strong_is_buy_high_confidence():
    grade, conf, basis = derive_grade(_stock(comp=70, up=25, attractiveness=5))
    assert grade == "매수"
    assert conf == "상"  # 세 축 모두 강
    assert basis["strong"] == 3 and basis["weak"] == 0


def test_two_strong_one_neutral_is_buy_mid():
    grade, conf, _ = derive_grade(_stock(comp=70, up=25, attractiveness=3))
    assert grade == "매수"
    assert conf == "중"  # 하나는 중립


def test_conflict_strong_and_weak_is_hold_low():
    # 퀀트 강 ↔ 컨센서스 약 = 축 충돌 → 관망/하
    grade, conf, basis = derive_grade(_stock(comp=70, up=2))
    assert grade == "관망"
    assert conf == "하"
    assert basis["divergence"]


def test_majority_weak_is_reduce():
    grade, conf, _ = derive_grade(_stock(comp=30, up=2))
    assert grade == "축소"
    assert conf == "상"  # 두 축 모두 약(present=2)


def test_one_strong_only_is_hold_not_weak_buy():
    # 한 축만 강(컨센서스 중립) → 약한 매수 만들지 않음(상방 신중)
    grade, conf, _ = derive_grade(_stock(comp=70, up=10))
    assert grade == "관망"
    assert conf == "중"


def test_one_weak_only_is_reduce_downside_sensitive():
    grade, conf, _ = derive_grade(_stock(comp=30, up=10))
    assert grade == "축소"
    assert conf == "중"


def test_all_neutral_is_hold_low():
    grade, conf, _ = derive_grade(_stock(comp=50, up=10))
    assert grade == "관망"
    assert conf == "하"


# ── 결측 축 처리 ────────────────────────────────────────────────

def test_single_axis_present_is_hold_low():
    # 퀀트만 있고 컨센서스·내 판단 결측 → 근거 부족, 매수/축소 단정 금지
    grade, conf, basis = derive_grade(_stock(comp=85))
    assert grade == "관망"
    assert conf == "하"
    assert basis["present"] == 1
    assert basis["axes"]["consensus"] is None and basis["axes"]["judgment"] is None


def test_missing_axes_are_none_not_zero():
    _, _, basis = derive_grade(_stock(comp=70, up=25))
    assert basis["axes"]["judgment"] is None  # 별점 미입력 = 0점 아님


# ── 시장·베타 보정(비대칭) ──────────────────────────────────────

def test_bear_market_high_beta_demotes_quant_strong():
    # 약세장 + 고베타 → 퀀트 강을 중으로 보수화 → 매수가 관망으로 내려감
    base = _stock(comp=70, up=25, beta=GRADE_BETA_HIGH + 0.3)
    g0, _, _ = derive_grade(base, market_direction="중립")
    g1, _, b1 = derive_grade(base, market_direction="약세")
    assert g0 == "매수"
    assert g1 == "관망"  # 보수화로 강이 하나 사라져 한 축만 강
    assert b1["marketAdjust"]["applied"] and b1["axes"]["quant"] == "중"


def test_bull_market_does_not_inflate_grade():
    # 강세장 + 고베타라도 등급을 끌어올리지 않는다(고점 매수 방지)
    base = _stock(comp=55, up=10, beta=2.0)  # 퀀트 중·컨센서스 중 → 관망
    g_bull, _, b = derive_grade(base, market_direction="강세")
    assert g_bull == "관망"
    assert b["marketAdjust"] is None  # 강세는 보정 없음


def test_low_beta_no_market_adjust():
    base = _stock(comp=70, up=25, beta=0.5)
    _, _, b = derive_grade(base, market_direction="약세")
    assert b["marketAdjust"] is None  # 저베타는 보정 트리거 미충족


# ── 합산이 아님(정렬 패턴) ──────────────────────────────────────

def test_grade_is_pattern_not_sum():
    # 평균이면 (70+2)/.. 식으로 중간 등급이 나오겠지만, 충돌 패턴이라 관망/하여야 한다
    grade, conf, _ = derive_grade(_stock(comp=72, up=2, attractiveness=5))
    # 퀀트 강·컨센서스 약·내 판단 강 → 강∧약 동시 = 충돌
    assert grade == "관망" and conf == "하"


# ── build_action_frame 통합 ─────────────────────────────────────

def test_build_action_frame_emits_grade():
    s = _stock(comp=70, up=25, attractiveness=5, marketScoreDirection="중립")
    frame = build_action_frame(s, {"asset_total": 0}, "neutral")
    assert frame["grade"] == "매수"
    assert frame["grade_confidence"] == "상"
    assert "axes" in frame["grade_basis"]


def test_frame_uses_market_direction_from_stock():
    s = _stock(comp=70, up=25, beta=1.5, marketScoreDirection="약세")
    frame = build_action_frame(s, {"asset_total": 0}, "bear")
    assert frame["grade"] == "관망"  # 약세+고베타 보수화 반영


# ── 폴백 해설(결정론, 매매 단정 없음) ───────────────────────────

def test_grade_fallback_rationale_mentions_axes_and_is_observational():
    _, _, basis = derive_grade(_stock(comp=70, up=25, attractiveness=5))
    text = grade_fallback_rationale({"grade": "매수", "grade_confidence": "상", "grade_basis": basis})
    assert "매수" in text and "퀀트" in text
    for banned in ("사라", "팔아라"):
        assert banned not in text


# ── 분포 스모크(단일 등급 쏠림 아님) ───────────────────────────

def test_grade_distribution_not_single_bucket():
    profiles = [
        _stock(comp=75, up=30, attractiveness=5),
        _stock(comp=30, up=2),
        _stock(comp=70, up=2),
        _stock(comp=55, up=12),
        _stock(comp=35, up=10),
        _stock(comp=80, up=25),
    ]
    grades = Counter(derive_grade(p)[0] for p in profiles)
    assert len(grades) >= 3  # 매수·관망·축소가 모두 출현
