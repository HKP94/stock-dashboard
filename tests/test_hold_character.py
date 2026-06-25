"""
tests/test_hold_character.py — 신규-D 보유성격 분류 + 집중 리스크 관찰(결정론)

- 보유성격(장기보유/모멘텀/단기/정보부족) 규칙 분기·우선순위·근거
- 집중 리스크 관찰 노트: 트리거·톤(금지어 없음)·LLM 다듬기 가드
- 비중 권고(target_weight/weight_action)는 프레임에 '보존'됨(표시만 제외) 확인
- 분포 스모크: 다양한 프로필이 단일 라벨로 쏠리지 않는지(CI-safe, DB·LLM 불요)
"""

from __future__ import annotations

from collections import Counter

from src.stock_action_advice import (
    CONCENTRATION_OBSERVE_PCT,
    build_action_frame,
    derive_concentration_note,
    derive_hold_character,
    finalize_concentration_note,
    is_observation_clean,
)


def _stock(**kw):
    base = {"t": "X", "f": {}, "aiDecompositionSummary": {"labels": {}}}
    base.update(kw)
    return base


# ── 보유성격 분기 ────────────────────────────────────────────────

def test_long_hold_via_manual_long_label():
    s = _stock(aiDecompositionSummary={"labels": {"long": "매력적"}})
    primary, secondary, basis = derive_hold_character(s, "neutral")
    assert primary == "장기보유"
    assert any(b["effect"] == "장기보유" for b in basis)


def test_long_hold_via_safety_and_quality():
    s = _stock(safety=70, f={"q": 65})
    primary, _sec, _b = derive_hold_character(s, "neutral")
    assert primary == "장기보유"


def test_momentum_via_align_slope_factor():
    s = _stock(align=True, slope=2.0, f={"m": 70})
    primary, _sec, _b = derive_hold_character(s, "bull")
    assert primary == "모멘텀"


def test_short_via_manual_short_label():
    assert derive_hold_character(_stock(aiDecompositionSummary={"labels": {"short": "매력적"}}), "neutral")[0] == "단기"


def test_short_via_curated_news_event():
    assert derive_hold_character(_stock(newsCuratedCount=3), "neutral")[0] == "단기"


def test_short_via_rsi_extreme():
    assert derive_hold_character(_stock(rsi=75), "neutral")[0] == "단기"
    assert derive_hold_character(_stock(rsi=25), "neutral")[0] == "단기"


def test_insufficient_when_no_material():
    primary, secondary, basis = derive_hold_character(_stock(), "neutral")
    assert primary == "정보부족" and secondary == []


def test_priority_long_beats_momentum_with_secondary():
    # 장기·모멘텀 동시 충족 → primary 장기보유, secondary 모멘텀(집중 철학상 장기 우선)
    s = _stock(aiDecompositionSummary={"labels": {"long": "매력적"}}, align=True, slope=2.0, f={"m": 70})
    primary, secondary, _b = derive_hold_character(s, "bull")
    assert primary == "장기보유"
    assert "모멘텀" in secondary


# ── 집중 리스크 관찰 ─────────────────────────────────────────────

def test_concentration_note_triggers_above_threshold_and_is_clean():
    note = derive_concentration_note(33.9)
    assert note is not None
    assert "33.9%" in note
    assert is_observation_clean(note)          # 가치판단·지시어 없음
    assert "줄" not in note and "축소" not in note and "부담" not in note


def test_concentration_note_none_below_threshold():
    assert derive_concentration_note(CONCENTRATION_OBSERVE_PCT - 0.1) is None
    assert derive_concentration_note(0.0) is None
    assert derive_concentration_note(None) is None


def test_concentration_note_includes_beta_when_present():
    note = derive_concentration_note(20.0, beta=1.4)
    assert "베타 1.4" in note and "20.0%" in note


def test_is_observation_clean_flags_value_judgments_and_directives():
    assert not is_observation_clean("현재 36%로 비중이 과도합니다")     # 가치판단
    assert not is_observation_clean("비중을 줄이세요")                  # 지시
    assert not is_observation_clean("적정 비중은 10%입니다")           # 가치판단
    assert is_observation_clean("현재 36% — 시장 급락 시 변동성 기여 큼")


def test_finalize_keeps_deterministic_when_polished_violates_or_drops_number():
    det = derive_concentration_note(36.0)
    # 금지어 포함 → 결정론 노트로 폴백
    assert finalize_concentration_note(det, "비중이 과도하니 줄이세요", 36.0) == det
    # 숫자 누락 → 폴백(새 숫자 창작/수치 증발 방지)
    assert finalize_concentration_note(det, "비중이 높아 변동성이 큽니다", 36.0) == det
    # 깨끗 + 수치 보존 → 다듬은 버전 채택
    polished = "현재 비중 36.0% 수준으로, 시장이 크게 흔들릴 때 포트폴리오 출렁임에 많이 기여합니다."
    assert finalize_concentration_note(det, polished, 36.0) == polished


# ── 비중 데이터 보존(표시만 제외) ────────────────────────────────

def test_build_action_frame_preserves_weight_fields_and_adds_character():
    s = _stock(t="AAPL", signal={"label": "매수"}, holding={"eval_amount": 100.0},
               aiDecompositionSummary={"labels": {"long": "매력적"}})
    frame = build_action_frame(s, {"asset_total": 1000.0}, "bull")
    # 비중 권고 숫자는 프레임에 그대로 보존(DB 저장·포트폴리오 탭 재사용)
    assert "target_weight_low" in frame and "weight_action" in frame and "direction" in frame
    # 신규-D 필드 추가
    assert frame["hold_character"] == "장기보유"
    assert frame["current_weight"] == 10.0  # 100/1000*100
    # 비중 10% < 15% 트리거 → 관찰 노트 없음
    assert frame["concentration_note"] is None


# ── 분포 스모크(CI-safe): 단일 라벨 쏠림 방지 ─────────────────────

def test_label_distribution_differentiates_across_profiles():
    profiles = [
        _stock(aiDecompositionSummary={"labels": {"long": "매력적"}}),            # 장기
        _stock(safety=72, f={"q": 68}),                                          # 장기
        _stock(align=True, slope=3.1, f={"m": 75}),                              # 모멘텀
        _stock(newsCuratedCount=2),                                              # 단기
        _stock(rsi=78),                                                          # 단기
        _stock(),                                                                # 정보부족
    ]
    dist = Counter(derive_hold_character(p, "neutral")[0] for p in profiles)
    assert len(dist) >= 3, dist                       # 최소 3종 라벨로 분화(전부 장기보유 쏠림 아님)
    assert dist["장기보유"] >= 1 and dist["모멘텀"] >= 1 and dist["단기"] >= 1
