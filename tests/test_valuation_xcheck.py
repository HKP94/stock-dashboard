"""밸류 교차검증 게이트 순수 함수 테스트(네트워크·DB 없음)."""
from src.compute_valuation_xcheck import crosscheck


def test_real_values_do_not_flag():
    """진단 실측: 저장(네이버) ≈ KRX 공식이면 flag 없음(정상 확정)."""
    # LS일렉트릭: PBR 거의 동일, PER은 EPS 관례차 14% (루즈 임계 35% 안이라 통과)
    assert crosscheck(16.50, 102.09, 16.49, 118.97)["flagged"] is False
    # 효성중공업 / KT&G / BNK — 전부 통과
    assert crosscheck(12.91, 61.36, 13.16, 59.52)["flagged"] is False
    assert crosscheck(1.96, 17.24, 1.96, 17.13)["flagged"] is False
    assert crosscheck(0.54, 6.88, 0.54, 7.48)["flagged"] is False  # PER 8% < 35%


def test_artificial_pbr_outlier_flags():
    """인위적 이상치: 저장 PBR이 실제(KRX)의 2.5배로 인플레되면 flag."""
    r = crosscheck(16.50, 100.0, 6.60, 100.0)  # 저장 PBR 16.5 vs 실제 6.6
    assert r["flagged"] is True
    assert "PBR" in r["reason"] and r["pbr_dev"] > 1.0


def test_gross_per_divergence_flags():
    """PER이 총체적으로(20%+) 벌어지면 flag(관례차 노이즈 아님)."""
    r = crosscheck(1.0, 50.0, 1.0, 100.0)  # PER 50 vs 100 = 50%
    assert r["flagged"] is True
    assert "PER" in r["reason"]


def test_small_per_noise_does_not_flag():
    """EPS 관례차 수준(≤20%) PER 편차는 통과."""
    assert crosscheck(1.0, 110.0, 1.0, 100.0)["flagged"] is False  # 10%


def test_missing_ref_not_flagged():
    """KRX 대조값 없음 = 검증 불가지, 이상치 아님 → flag 안 함."""
    r = crosscheck(16.5, 102.0, None, None)
    assert r["flagged"] is False
    assert r["pbr_dev"] is None and r["per_dev"] is None
    assert "없음" in r["reason"]


def test_zero_and_negative_treated_as_missing():
    """0·음수·NaN 대조값은 결측 취급(0으로 나눔 방지)."""
    r = crosscheck(16.5, 102.0, 0.0, -1.0)
    assert r["flagged"] is False
    assert r["pbr_dev"] is None and r["per_dev"] is None
