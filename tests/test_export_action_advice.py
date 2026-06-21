from src.export_dashboard_data import _group_action_advice_rows


def test_group_action_advice_rows_returns_latest_and_history_in_desc_order():
    rows = [
        {
            "ticker": "AAPL",
            "asof": "2026-06-20",
            "direction": "유지",
            "current_weight": 4.0,
            "target_weight_low": 3.0,
            "target_weight_high": 6.0,
            "weight_action": "유지",
            "entry_zone": None,
            "exit_zone": None,
            "confidence": "중",
            "rationale": "old",
            "supporting_factors": [],
            "opposing_factors": [],
            "divergence_note": None,
            "model": "m1",
        },
        {
            "ticker": "AAPL",
            "asof": "2026-06-21",
            "direction": "비중확대",
            "current_weight": 5.0,
            "target_weight_low": 3.0,
            "target_weight_high": 6.0,
            "weight_action": "늘림",
            "entry_zone": "SMA60",
            "exit_zone": None,
            "confidence": "상",
            "rationale": "new",
            "supporting_factors": [],
            "opposing_factors": [],
            "divergence_note": None,
            "model": "m1",
        },
    ]
    grouped = _group_action_advice_rows(rows)
    assert grouped["AAPL"][0]["direction"] == "비중확대"
    assert grouped["AAPL"][1]["direction"] == "유지"
