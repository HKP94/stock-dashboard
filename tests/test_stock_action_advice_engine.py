from src.stock_action_advice import (
    allocation_band_to_range,
    build_action_frame,
    compute_current_weight,
    derive_allocation_band,
)


def test_compute_current_weight_uses_eval_amount_over_asset_total():
    assert compute_current_weight(50_000, 1_000_000) == 5.0
    assert compute_current_weight(None, 1_000_000) == 0.0


def test_bear_regime_caps_core_band():
    low, high = allocation_band_to_range("core", regime="bear")
    assert (low, high) == (3.0, 6.0)


def test_non_holding_buy_signal_maps_to_starter_or_build():
    band = derive_allocation_band(
        is_holding=False,
        signal_label="매수",
        regime="neutral",
        confidence="상",
        consensus_gap=0.18,
    )
    assert band in {"starter", "build"}


def test_build_action_frame_exposes_supporting_sources_without_llm():
    stock = {
        "t": "AAPL",
        "signal": {"label": "매수", "reason": "백분위 상위 20%", "confidence": 82},
        "consensus": {"targetPrice": 240, "ratingLabel": "매수"},
        "price": 200,
        "analystViews": {"bull": [{"point": "수요 견조"}], "bear": []},
        "manualResearchLatest": None,
        "drivers": [],
        "holding": {"eval_amount": 50000},
        "sma20": 198,
        "sma50": 190,
        "sma200": 170,
    }
    advice = build_action_frame(stock, {"asset_total": 1_000_000}, "bull")
    assert advice["current_weight"] == 5.0
    assert advice["direction"] in {"매수", "비중확대", "유지"}
    assert advice["target_weight_high"] <= 10.0
    assert any(item["source"] == "퀀트신호" for item in advice["supporting_factors"])


def test_overweight_holding_prefers_reduce_direction_when_above_target_band():
    stock = {
        "t": "AAPL",
        "signal": {"label": "매수", "reason": "백분위 상위 20%", "confidence": 82},
        "consensus": {"targetPrice": 240, "ratingLabel": "매수"},
        "price": 200,
        "analystViews": {"bull": [{"point": "수요 견조"}], "bear": []},
        "manualResearchLatest": None,
        "drivers": [],
        "holding": {"eval_amount": 400000},
        "sma20": 198,
        "sma50": 190,
        "sma200": 170,
    }
    advice = build_action_frame(stock, {"asset_total": 1_000_000}, "bull")
    assert advice["weight_action"] == "줄임"
    assert advice["direction"] == "비중축소"
