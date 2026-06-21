from src.enrich_gemini import _build_stock_action_advice_prompt


def test_action_advice_prompt_explicitly_forbids_numeric_generation():
    prompt = _build_stock_action_advice_prompt({
        "ticker": "AAPL",
        "direction": "비중확대",
        "current_weight": 5.0,
        "target_weight_low": 3.0,
        "target_weight_high": 6.0,
        "entry_zone": "SMA60 부근",
        "exit_zone": None,
        "supporting_factors": [{"source": "퀀트신호", "value": "매수"}],
        "opposing_factors": [],
    })
    assert "새로운 숫자" in prompt
    assert "입력으로 받은 값만" in prompt
