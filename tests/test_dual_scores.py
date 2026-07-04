"""점수 이원화(장기/모멘텀) 결정론 블렌드 테스트(§2 재합산 금지)."""
import pytest
from src.export_dashboard_data import _blend, _dual_scores, LONG_SCORE_WEIGHTS, MOMO_SCORE_WEIGHTS


def test_weights_documented_and_sum_to_one():
    assert pytest.approx(sum(LONG_SCORE_WEIGHTS.values())) == 1.0
    assert pytest.approx(sum(MOMO_SCORE_WEIGHTS.values())) == 1.0


def test_blend_weighted_average():
    # quality0.35·value0.35·growth0.30 of (80,60,40) = 28+21+12 = 61.0
    assert _blend([(80, 0.35), (60, 0.35), (40, 0.30)]) == 61.0


def test_blend_missing_axis_renormalizes():
    # growth 결측 → 남은 quality/value(0.35/0.35)로 정규화: (80+60)/2 = 70.0
    assert _blend([(80, 0.35), (60, 0.35), (None, 0.30)]) == 70.0


def test_blend_all_missing_none():
    assert _blend([(None, 0.5), (None, 0.5)]) is None


def test_dual_scores_separates_long_and_momentum():
    # NVDA류: 펀더 강(q87/v44/g83) · 타이밍 약(m6/s27)
    out = _dual_scores(momentum=6, value=44, quality=87, growth=83, sentiment=27)
    assert out["longScore"] == round(87 * 0.35 + 44 * 0.35 + 83 * 0.30, 1)   # 69.75→69.8
    assert out["momoScore"] == round(6 * 0.60 + 27 * 0.40, 1)                # 14.4
    # 두 점수는 독립(하나로 안 합침) — 장기 高, 모멘텀 低 괴리가 그대로 남음
    assert out["longScore"] > 60 and out["momoScore"] < 20
    assert out["longParts"] == {"q": 87, "v": 44, "g": 83}
    assert out["momoParts"] == {"m": 6, "s": 27}


def test_dual_scores_reverse_divergence():
    # 모멘텀 종목: 타이밍 강 · 펀더 중
    out = _dual_scores(momentum=98, value=40, quality=45, growth=40, sentiment=90)
    assert out["momoScore"] > out["longScore"]
