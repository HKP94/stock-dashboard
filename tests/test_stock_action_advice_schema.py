from pathlib import Path

from src.schemas import StockActionAdviceRow


def test_stock_action_advice_row_accepts_expected_contract():
    row = StockActionAdviceRow(
        ticker="AAPL",
        asof="2026-06-21",
        direction="비중확대",
        current_weight=4.2,
        target_weight_low=3.0,
        target_weight_high=6.0,
        weight_action="늘림",
        entry_zone="SMA60 부근 재확인 시",
        exit_zone="목표가 근접 시",
        confidence="중",
        rationale="설명",
        supporting_factors=[{"source": "퀀트신호", "value": "매수"}],
        opposing_factors=[{"source": "드라이버", "value": "단기 약세"}],
        divergence_note="재료 혼조",
        model="gemini-2.5-pro",
    )
    assert row.direction == "비중확대"
    assert row.target_weight_high == 6.0


def test_schema_sql_defines_daily_unique_stock_action_advice_table():
    schema = Path("db/schema.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS stock_action_advice" in schema
    assert "UNIQUE (ticker, asof)" in schema
