from src.schemas import StockActionAdviceRow


class _Cursor:
    def __init__(self):
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _Conn:
    def __init__(self):
        self.cur = _Cursor()

    def cursor(self):
        return self.cur


def test_upsert_stock_action_advice_persists_daily_row():
    from src.db import upsert_stock_action_advice

    conn = _Conn()
    row = StockActionAdviceRow(
        ticker="AAPL",
        asof="2026-06-21",
        direction="비중확대",
        current_weight=4.2,
        target_weight_low=3.0,
        target_weight_high=6.0,
        weight_action="늘림",
        entry_zone="SMA60 부근",
        exit_zone=None,
        confidence="중",
        rationale="설명",
        supporting_factors=[{"source": "퀀트신호", "value": "매수"}],
        opposing_factors=[],
        divergence_note=None,
        model="gemini-2.5-pro",
    )

    upsert_stock_action_advice(conn, row)

    sql, params = conn.cur.executed[0]
    assert "INSERT INTO stock_action_advice" in sql
    assert "ON CONFLICT (ticker, asof) DO UPDATE SET" in sql
    assert params[0] == "AAPL"
    assert params[2] == "비중확대"
