"""모멘텀 추세확인 게이트 + 매수/매도 구간 (export 레이어 오버레이) 단위 테스트.
팩터는 불변 — 여기선 단기 추세 판정·레벨 산출만 검증(결정론·§F7, DB/네트워크 없음)."""
from src.export_dashboard_data import _momentum_trend, _momentum_zones


def _ser(high, last, n=60):
    """60일 고점=high, 최근값=last인 단순 하강 시계열(스윙로우 판정용 길이 확보)."""
    return [high] + [last] * (n - 1)


def test_broken_high_momentum_but_collapsed():
    # 효성類: 고점 150 → 현재 100(-33%), 전 이평 하회, MACD 음전환
    ser = _ser(150, 100)
    t = _momentum_trend(close=100, sma20=115, sma50=130, ser=ser,
                        macd_line=-1.0, macd_signal=0.5, macd_hist=-1.5)
    assert t["state"] == "broken" and t["label"] == "고점 후 붕괴"
    assert t["dd60"] == -33.3
    z = _momentum_zones(t, close=100, sma20=115, sma50=130, ser=ser, atr14=3.0)
    assert z["buy"] is None                      # 붕괴주는 매수 없음
    assert z["reclaim"] == 115.0                 # 현재가 위 가장 가까운 이평(sma20)


def test_intact_uptrend_holds():
    # APR類: 고점 106 → 현재 100(-5.7%), sma20 위
    ser = _ser(106, 100)
    t = _momentum_trend(close=100, sma20=95, sma50=90, ser=ser,
                        macd_line=1.0, macd_signal=0.5, macd_hist=0.3)
    assert t["state"] == "intact" and t["label"] == "상승 유지"
    z = _momentum_zones(t, close=100, sma20=95, sma50=90, ser=ser, atr14=2.0)
    assert z["buy"] == 95.0                       # 가장 가까운 하방 지지(sma20)
    assert z["stop"] is not None and z["stop"] < z["buy"]
    assert z["target"] == 106.0                   # 직전 60일 고점 회복


def test_pullback_middle_state():
    # 되돌림: sma20 아래지만 sma50 위·드로다운 얕음(-8%) → broken도 intact도 아님
    ser = _ser(108.7, 100)                         # dd ≈ -8%
    t = _momentum_trend(close=100, sma20=102, sma50=95, ser=ser,
                        macd_line=0.2, macd_signal=0.3, macd_hist=-0.1)
    assert t["state"] == "pullback"
    z = _momentum_zones(t, close=100, sma20=102, sma50=95, ser=ser, atr14=2.0)
    assert z["buy"] == 95.0                        # sma20은 위라 지지 아님 → sma50


def test_missing_data_returns_none():
    assert _momentum_trend(close=None, sma20=100, sma50=90, ser=[1, 2],
                           macd_line=0, macd_signal=0, macd_hist=0) is None
    assert _momentum_zones(None, close=100, sma20=1, sma50=1, ser=[], atr14=1) is None
