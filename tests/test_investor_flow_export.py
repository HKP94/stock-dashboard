"""홈 4밴드 ① — investor_flow export에 **당일** 순매수가 실리는지.

3일 합계만으로는 "외인 순매수일" 같은 당일 규칙을 판정할 수 없다(3일 +인데 당일 -인
경우가 실제로 생긴다). 이 가드는 당일 필드가 조용히 사라지는 회귀를 막는다.
US는 구조적 부재이므로 None을 유지한다(가짜 0 금지).
"""
from src.export_dashboard_data import _format_investor_flow


ROW = {
    "date": "2026-08-07",
    "foreign_net": -1_444_800_000.0,
    "institution_net": 250_000_000.0,
    "foreign_3d_sum": 6_254_000_000.0,
    "institution_3d_sum": -864_000_000.0,
    "foreign_signal": "매수우호",
    "institution_signal": "매도우세",
    "combined_signal": "수급_혼조",
}


def test_daily_net_is_exported_alongside_3d():
    out = _format_investor_flow(ROW, "KR")
    assert out["foreignNet1d"] == -1_444_800_000.0
    assert out["institutionNet1d"] == 250_000_000.0
    # 3일 합계는 그대로 남는다(추세 병기용)
    assert out["foreignNet3d"] == 6_254_000_000.0
    assert out["institutionNet3d"] == -864_000_000.0


def test_daily_and_3d_can_disagree():
    """3일 +, 당일 - — 당일 필드가 없으면 이 종목을 '순매수'로 오판한다."""
    out = _format_investor_flow(ROW, "KR")
    assert out["foreignNet3d"] > 0 and out["foreignNet1d"] < 0


def test_missing_daily_net_is_none_not_zero():
    out = _format_investor_flow({**ROW, "foreign_net": None}, "KR")
    assert out["foreignNet1d"] is None


def test_us_stays_none():
    assert _format_investor_flow(ROW, "US") is None
