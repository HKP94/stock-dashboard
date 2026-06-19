from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd

from src import backfill as bf
from src import db as db_mod
from src.schemas import IndexDailyRow


class _CursorCtx:
    def __init__(self, fetch_rows=None):
        self.fetch_rows = fetch_rows or []
        self.executed_sql: str | None = None
        self.executemany_sql: str | None = None
        self.executemany_params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.executed_sql = sql

    def executemany(self, sql, params):
        self.executemany_sql = sql
        self.executemany_params = list(params)

    def fetchall(self):
        return self.fetch_rows


class _Conn:
    def __init__(self, fetch_rows=None):
        self.cur = _CursorCtx(fetch_rows=fetch_rows)

    def cursor(self):
        return self.cur


def test_index_daily_row_defaults_source():
    row = IndexDailyRow(index_code="^GSPC", asof=date(2026, 6, 19), close=6123.45)
    assert row.source == "yfinance"


def test_upsert_index_daily_uses_index_code_and_asof():
    conn = _Conn()
    rows = [IndexDailyRow(index_code="^IXIC", asof=date(2026, 6, 19), close=19999.1)]

    db_mod.upsert_index_daily(conn, rows)

    assert conn.cur.executemany_sql is not None
    assert "ON CONFLICT (index_code, asof)" in conn.cur.executemany_sql
    assert conn.cur.executemany_params == [("^IXIC", date(2026, 6, 19), 19999.1, "yfinance")]


def test_fetch_index_history_maps_yfinance_rows():
    from src import ingest_index_history as idx

    hist = pd.DataFrame(
        {"Close": [3000.0, 3010.5]},
        index=pd.to_datetime(["2026-06-18", "2026-06-19"]),
    )

    with patch.object(idx, "_yf_history", return_value=hist):
        rows = idx.fetch_index_history("^KS11")

    assert [r.index_code for r in rows] == ["^KS11", "^KS11"]
    assert [r.asof for r in rows] == [date(2026, 6, 18), date(2026, 6, 19)]
    assert rows[-1].close == 3010.5


def test_find_missing_business_days_flags_large_gap_but_not_holiday_weekend():
    from src import ingest_index_history as idx

    rows = [
        IndexDailyRow(index_code="^GSPC", asof=date(2026, 1, 2), close=100.0),   # Fri
        IndexDailyRow(index_code="^GSPC", asof=date(2026, 1, 5), close=101.0),   # Mon, holiday/weekend gap 허용
        IndexDailyRow(index_code="^GSPC", asof=date(2026, 1, 13), close=102.0),  # 큰 공백
    ]

    gaps = idx.find_missing_business_days(rows, max_gap_days=5)

    assert len(gaps) == 1
    assert gaps[0]["index_code"] == "^GSPC"
    assert gaps[0]["start"] == "2026-01-05"
    assert gaps[0]["end"] == "2026-01-13"


def test_detect_gap_tickers_flags_five_year_readiness():
    conn = _Conn(
        fetch_rows=[
            {"ticker": "AAA", "market": "US", "name": "Alpha", "rows": 480, "last_date": date(2026, 6, 18)},
            {"ticker": "BBB", "market": "KR", "name": "Beta", "rows": 1300, "last_date": date(2026, 6, 18)},
        ]
    )

    default_gaps = bf.detect_gap_tickers(conn)
    deep_history_gaps = bf.detect_gap_tickers(conn, required_years=5)

    assert default_gaps == []
    assert len(deep_history_gaps) == 1
    assert deep_history_gaps[0]["ticker"] == "AAA"
    assert "5년" in deep_history_gaps[0]["reason"]


def test_backfill_one_uses_five_year_window_when_requested():
    with patch("src.ingest_us.fetch_us_prices", return_value=["ok"]) as mock_us, \
         patch("src.ingest_kr.fetch_kr_prices", return_value=["ok"]) as mock_kr:
        us_rows = bf._backfill_one("AAPL", "US", years=5)
        kr_rows = bf._backfill_one("005930.KS", "KR", years=5)

    assert us_rows == ["ok"]
    assert kr_rows == ["ok"]
    mock_us.assert_called_once_with("AAPL", period="5y")
    mock_kr.assert_called_once_with("005930.KS", lookback_days=1830)


def test_run_backfill_five_year_recomputes_indicators_and_quant_without_manual_step():
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False

    gaps = [{"ticker": "AAPL", "market": "US", "name": "Apple", "reason": "가격 부족", "rows": 0, "last_date": None}]
    fake_price_rows = [MagicMock()]
    fake_quant_rows = [MagicMock(), MagicMock()]

    with patch("src.backfill.get_conn", return_value=conn), \
         patch("src.backfill.log_run_start", return_value=101), \
         patch("src.backfill.log_run_finish") as finish, \
         patch("src.backfill.detect_gap_tickers", return_value=gaps), \
         patch("src.backfill._backfill_one", return_value=fake_price_rows), \
         patch("src.backfill.upsert_price_daily") as upsert_prices, \
         patch("src.backfill.compute_quant_universe", return_value=fake_quant_rows), \
         patch("src.backfill.upsert_quant_scores") as upsert_quant, \
         patch("src.backfill.recompute_indicators_to_db", return_value=1) as recompute_indicators:
        result = bf.run_backfill(required_years=5)

    recompute_indicators.assert_called_once_with(conn, ["AAPL"])
    upsert_prices.assert_called_once_with(conn, fake_price_rows)
    upsert_quant.assert_called_once_with(conn, fake_quant_rows)
    finish.assert_called_once()
    assert result["backfilled"] == 1
    assert result["indicators"] == 1
    assert result["quant"] == 2
    assert result["errors"] == []
