from src.run_pipeline import _prioritize_action_advice_targets, _step_action_advice


def test_prioritize_action_advice_targets_orders_holdings_first():
    targets = _prioritize_action_advice_targets(
        holdings=["AAPL", "MSFT"],
        event_tickers=["NVDA", "AAPL", "TSLA"],
        remaining=["TSLA", "GOOGL", "MSFT", "AMZN"],
    )
    assert targets[:2] == ["AAPL", "MSFT"]
    assert targets[2:4] == ["NVDA", "TSLA"]
    assert "GOOGL" in targets and "AMZN" in targets


def test_action_advice_step_records_budget_rollover(monkeypatch):
    from src import run_pipeline as RP

    class Conn:
        def rollback(self):
            return None

    monkeypatch.setattr(RP, "_select_action_advice_targets", lambda conn: ["AAPL", "TSLA", "NVDA"])
    monkeypatch.setattr(RP, "_within_budget", lambda started_at, budget_seconds=0: False)

    errors = []
    RP._step_action_advice(Conn(), errors)
    assert any(item["step"] == "action_advice_budget" for item in errors)
