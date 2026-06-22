"""
tests/test_pipeline_behavior_baseline.py — 파이프라인 분리 1단계 행위 고정

프로덕션 코드는 바꾸지 않고 현재 오케스트레이션 경계만 잠근다.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, mock_open, patch


DAILY_STAGE_ORDER = [
    "market",
    "macro",
    "driver_prices",
    "ingest_kr",
    "ingest_us",
    "ingest_news",
    "ingest_market_news",
    "compute_indicators",
    "compute_quant",
    "enrich_gemini",
    "compute_portfolio",
    "backtest",
    "action_advice",
    "assemble",
]

REFRESH_STAGE_ORDER = [
    "price_refresh",
    "ingest_news",
    "ingest_market_news",
    "enrich_news",
    "enrich_market",
    "market_news_digest",
]

DB_SNAPSHOT_EXCLUDE_FIELDS = {"created_at", "generated_at", "run_id", "ts"}
EXPORT_SNAPSHOT_EXCLUDE_FIELDS = {"generatedAt", "generatedAtLabel"}


def _ctx_conn(cursor_rows: list[dict] | None = None):
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    cur = MagicMock()
    cur.__enter__.return_value = cur
    cur.__exit__.return_value = False
    cur.fetchall.return_value = cursor_rows or []
    conn.cursor.return_value = cur
    return conn


def _normalize_snapshot(value, *, exclude_fields: set[str]):
    if isinstance(value, dict):
        return {
            key: _normalize_snapshot(val, exclude_fields=exclude_fields)
            for key, val in sorted(value.items())
            if key not in exclude_fields
        }
    if isinstance(value, list):
        if value and all(isinstance(item, dict) for item in value):
            rows = [_normalize_snapshot(item, exclude_fields=exclude_fields) for item in value]
            return sorted(rows, key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True))
        return [_normalize_snapshot(item, exclude_fields=exclude_fields) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def test_run_pipeline_daily_stage_order_locked(monkeypatch):
    import src.run_pipeline as RP

    order: list[str] = []
    conn = _ctx_conn()

    monkeypatch.setattr(RP, "get_conn", lambda: conn)
    monkeypatch.setattr(RP, "log_run_start", lambda _conn, kind: 101)
    monkeypatch.setattr(RP, "log_run_finish", lambda _conn, run_id, status, errors: None)
    monkeypatch.setattr(
        RP,
        "_get_active_tickers",
        lambda _conn: [{"ticker": "005930.KS", "market": "KR"}, {"ticker": "AAPL", "market": "US"}],
    )

    for name in DAILY_STAGE_ORDER[:-1]:
        monkeypatch.setattr(RP, f"_step_{name}", lambda _conn, _arg=None, _errors=None, _name=name: order.append(_name))
    monkeypatch.setattr(RP, "_step_assemble", lambda _conn, _errors: order.append("assemble") or ["record"])

    records = RP.run_pipeline(date(2026, 6, 21))

    assert records == ["record"]
    assert order == DAILY_STAGE_ORDER


def test_news_refresh_stage_order_locked(monkeypatch):
    import src.news_refresh as NR

    order: list[str] = []
    conn = _ctx_conn([{"ticker": "005930.KS", "name": "삼성전자"}])

    monkeypatch.setattr(NR, "get_conn", lambda: conn)
    monkeypatch.setattr(NR, "log_run_start", lambda _conn, kind: 202)
    monkeypatch.setattr(NR, "log_run_finish", lambda _conn, run_id, status, errors: order.append(f"log:{status}"))
    monkeypatch.setattr(NR, "_refresh_prices_light", lambda _conn: order.append("price_refresh") or {"price_rows": 2, "errors": []})
    monkeypatch.setattr(NR, "run_news_ingest", lambda tickers, company_names: order.append("ingest_news") or {"news": {"005930.KS": [{"id": 1}]}, "errors": []})
    monkeypatch.setattr(NR, "insert_news_raw", lambda _conn, rows: len(rows))
    monkeypatch.setattr(NR, "run_market_news_ingest", lambda: order.append("ingest_market_news") or {"rows": [{"id": 1}], "errors": []})
    monkeypatch.setattr(NR, "insert_market_news", lambda _conn, rows: len(rows))
    monkeypatch.setattr(NR, "enrich_news_batch", lambda _conn: (order.append("enrich_news") or 1, []))
    monkeypatch.setattr(NR, "enrich_market_summary", lambda _conn: order.append("enrich_market") or True)
    monkeypatch.setattr(NR, "summarize_market_news_digest", lambda _conn: order.append("market_news_digest") or True)

    with patch("src.export_dashboard_data.build_data", side_effect=lambda: order.append("export") or {"stocks": []}), \
         patch("builtins.open", mock_open()), \
         patch("json.dump", side_effect=lambda data, fh, **kwargs: None):
        result = NR.run_news_refresh()

    assert result["prices"] == 2
    assert result["new_news"] == 1
    assert order[:-2] == REFRESH_STAGE_ORDER
    assert order[-2:] == ["log:success", "export"]


def test_step_market_commits_success_and_rolls_back_on_error(monkeypatch):
    import src.run_pipeline as RP

    conn = _ctx_conn()
    errors: list[dict] = []

    monkeypatch.setattr(RP, "run_market_ingest", lambda: {"market": {"asof": "2026-06-21"}, "errors": []})
    monkeypatch.setattr(RP, "upsert_market_daily", lambda _conn, row: None)
    RP._step_market(conn, errors)
    assert conn.commit.call_count == 1
    assert conn.rollback.call_count == 0
    assert errors == []

    conn.reset_mock()
    errors.clear()
    monkeypatch.setattr(RP, "run_market_ingest", lambda: (_ for _ in ()).throw(RuntimeError("market down")))
    RP._step_market(conn, errors)
    assert conn.commit.call_count == 0
    assert conn.rollback.call_count == 1
    assert errors and errors[0]["step"] == "market"


def test_step_compute_indicators_commits_per_ticker_and_isolates_failures(monkeypatch):
    import pandas as pd
    import src.run_pipeline as RP

    conn = _ctx_conn()
    errors: list[dict] = []
    df = pd.DataFrame({"close": [1.0], "volume": [1]})

    monkeypatch.setattr(RP, "_load_price_df", lambda ticker, _conn: df)

    def _compute(ticker, _df):
        if ticker == "BAD":
            raise ValueError("broken")
        return [f"{ticker}-row"]

    monkeypatch.setattr(RP, "compute_indicators", _compute)
    monkeypatch.setattr(RP, "upsert_indicators_daily", lambda _conn, rows: None)

    RP._step_compute_indicators(conn, ["BAD", "GOOD"], errors)

    assert conn.rollback.call_count == 1
    assert conn.commit.call_count == 1
    assert [item["step"] for item in errors] == ["indicators:BAD"]


def test_db_snapshot_normalization_excludes_only_declared_volatile_fields():
    rows = [
        {
            "ticker": "AAPL",
            "asof": date(2026, 6, 21),
            "direction": "비중축소",
            "score": Decimal("35.9"),
            "created_at": datetime(2026, 6, 21, 6, 0),
            "run_id": 77,
        }
    ]

    assert _normalize_snapshot(rows, exclude_fields=DB_SNAPSHOT_EXCLUDE_FIELDS) == [
        {"asof": "2026-06-21", "direction": "비중축소", "score": "35.9", "ticker": "AAPL"}
    ]


def test_export_snapshot_normalization_preserves_contract_fields():
    payload = {
        "generatedAt": "2026-06-21T06:31",
        "generatedAtLabel": "2026-06-21 06:31 KST",
        "stocks": [
            {
                "t": "AAPL",
                "signal": {"label": "매수", "percentile": 70, "reason": "상위 30%", "confidence": "상"},
                "actionAdviceLatest": {"direction": "비중축소", "confidence": "상"},
            }
        ],
        "market": {"overall": "bull"},
    }

    assert _normalize_snapshot(payload, exclude_fields=EXPORT_SNAPSHOT_EXCLUDE_FIELDS) == {
        "market": {"overall": "bull"},
        "stocks": [
            {
                "actionAdviceLatest": {"confidence": "상", "direction": "비중축소"},
                "signal": {"confidence": "상", "label": "매수", "percentile": 70, "reason": "상위 30%"},
                "t": "AAPL",
            }
        ],
    }
