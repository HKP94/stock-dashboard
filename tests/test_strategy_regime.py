"""전략비교 고도화: 현재 장세→전략 매핑(Part 2) 순수 로직 테스트(네트워크·DB 없음)."""
from src.export_dashboard_data import _build_regime_strategy, _DIRECTION_TO_REGIME


def _bt():
    """합성 backtest: true 2전략·retro 1전략, regimeReturns 세팅."""
    return {
        "trueTrack": {"strategies": [
            {"name": "momentum_12_1", "label": "모멘텀 12-1", "horizons": {
                "5y": {"regimeReturns": {"bull": 2.5, "neutral": 0.1, "bear": 1.1}},
            }},
            {"name": "equal_weight_bh", "label": "동일가중", "horizons": {
                "5y": {"regimeReturns": {"bull": 1.5, "neutral": 0.4, "bear": 0.7}},
            }},
        ]},
        "retrospective": {"strategies": [
            {"name": "quality", "label": "우량성", "horizons": {
                "5y": {"regimeReturns": {"bull": 1.9, "neutral": 0.3, "bear": 0.8}},
            }},
        ]},
    }


def _market(kr_dir, us_dir):
    m = {}
    if kr_dir:
        m["kr"] = {"marketScore": {"direction": kr_dir, "score": 70, "confidence": "중"}}
    if us_dir:
        m["us"] = {"marketScore": {"direction": us_dir}}
    return m


def test_direction_maps_to_regime():
    assert _DIRECTION_TO_REGIME == {"강세": "bull", "중립": "neutral", "약세": "bear"}


def test_bull_ranks_momentum_top_neutral_ranks_equalweight():
    out = _build_regime_strategy(_bt(), _market("강세", "중립"))
    # KR 강세 → bull: 모멘텀(2.5) > 동일가중(1.5)
    assert out["kr"]["regime"] == "bull"
    assert [s["name"] for s in out["kr"]["trueRanked"]] == ["momentum_12_1", "equal_weight_bh"]
    assert out["kr"]["trueRanked"][0]["regimeReturn"] == 2.5
    # US 중립 → neutral: 동일가중(0.4) > 모멘텀(0.1)
    assert out["us"]["regime"] == "neutral"
    assert out["us"]["trueRanked"][0]["name"] == "equal_weight_bh"


def test_retro_separated_and_flagged_in_observation():
    out = _build_regime_strategy(_bt(), _market("강세", None))
    kr = out["kr"]
    # 회고는 별도 랭킹(true와 안 섞임)
    assert [s["name"] for s in kr["retroRanked"]] == ["quality"]
    assert kr["retroRanked"][0]["track"] == "retrospective"
    # 관찰 문구에 방향 + 선택편향 경고
    assert "강세" in kr["observation"] and "선택편향" in kr["observation"]


def test_region_without_marketscore_omitted():
    out = _build_regime_strategy(_bt(), _market("강세", None))
    assert "kr" in out and "us" not in out


def test_none_regime_return_skips_to_next_horizon():
    bt = {"trueTrack": {"strategies": [
        {"name": "momentum_12_1", "label": "모멘텀", "horizons": {
            "5y": {"regimeReturns": {"bear": None}},          # 5y bear 없음 → 스킵
            "3y": {"regimeReturns": {"bear": 0.9}},           # 3y bear 사용
        }},
    ]}, "retrospective": {"strategies": []}}
    out = _build_regime_strategy(bt, _market("약세", None))
    assert out["kr"]["trueRanked"][0]["horizon"] == "3y"
    assert out["kr"]["trueRanked"][0]["regimeReturn"] == 0.9
