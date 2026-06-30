"""
tests/test_pipeline_analysis_behavior.py — 파이프라인 분리 3단계 행위 보존

legacy 분석(run_pipeline의 지표→퀀트→포폴→백테스트 / news_refresh의 refresh 지표·퀀트)과
새 pipeline_analysis 의 DB 쓰기 스냅샷이 동일함을 증명한다.

외부 수집·LLM은 호출하지 않는다(fixture/monkeypatch). DB는 MagicMock conn으로 격리.
indicators_daily/quant_scores 는 upsert 인자를 직접 캡처하고,
portfolio/portfolio_snapshot/backtest_results 는 내부에서 적재하므로 호출 마커로 비교한다.
refresh가 포폴·백테스트를 실행하지 않음도 함께 고정한다.
"""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import src.pipeline_analysis as PA
from src.pipeline_common import VALID_PROFILES
from tests.test_pipeline_behavior_baseline import (
    DB_SNAPSHOT_EXCLUDE_FIELDS,
    _ctx_conn,
    _normalize_snapshot,
)

# 비교 대상 5개 분석 테이블 (설계 §8)
ANALYSIS_TABLES = [
    "indicators_daily",
    "quant_scores",
    "portfolio",
    "portfolio_snapshot",
    "backtest_results",
]

WATCHLIST_ROWS = [
    {"ticker": "005930.KS", "market": "KR", "name": "삼성전자"},
    {"ticker": "AAPL", "market": "US", "name": "Apple"},
]

QUANT_ROWS = [
    {"ticker": "005930.KS", "composite": 55.0},
    {"ticker": "AAPL", "composite": 60.0},
]
PORTFOLIO_RESULT = {"n": 2}
BACKTEST_RESULT = {"true_backtest": {"ok": True}, "retrospective": {"ok": True}}
DUMMY_DF = pd.DataFrame({"close": [1.0], "volume": [1]})


def _indicators_fixture(ticker, _df):
    return [{"ticker": ticker, "date": "2026-06-21", "sma20": 1.0}]


def _recorder(writes: dict, table: str):
    def _fn(conn, payload):
        writes.setdefault(table, []).append(payload)
    return _fn


def _portfolio_mock(writes: dict):
    def _fn(conn, *_a, **_k):
        # compute_portfolio는 portfolio + portfolio_snapshot 두 테이블을 내부 적재
        writes.setdefault("portfolio", []).append({"called": True})
        writes.setdefault("portfolio_snapshot", []).append({"called": True})
        return PORTFOLIO_RESULT
    return _fn


def _backtest_mock(writes: dict):
    def _fn(conn, *_a, **_k):
        writes.setdefault("backtest_results", []).append({"called": True})
        return BACKTEST_RESULT
    return _fn


def _recompute_marker(writes: dict):
    def _fn(conn, tickers=None):
        writes.setdefault("indicators_daily", []).append({"recompute_tickers": list(tickers or [])})
        return len(tickers or [])
    return _fn


def _snapshot(writes: dict) -> dict:
    return _normalize_snapshot(
        {t: writes.get(t, []) for t in ANALYSIS_TABLES},
        exclude_fields=DB_SNAPSHOT_EXCLUDE_FIELDS,
    )


# ──────────────────────────────────────────────────────────────
# daily: legacy run_pipeline 계산 단계 vs 새 pipeline_analysis
# ──────────────────────────────────────────────────────────────

def _legacy_daily_writes() -> dict:
    import src.run_pipeline as RP

    writes: dict = {}
    conn = _ctx_conn(WATCHLIST_ROWS)
    with ExitStack() as stack:
        stack.enter_context(patch.object(RP, "_load_price_df", lambda _t, _c: DUMMY_DF))
        stack.enter_context(patch.object(RP, "compute_indicators", _indicators_fixture))
        stack.enter_context(patch.object(RP, "upsert_indicators_daily", _recorder(writes, "indicators_daily")))
        stack.enter_context(patch.object(RP, "compute_quant_universe", lambda _t, _c: QUANT_ROWS))
        stack.enter_context(patch.object(RP, "upsert_quant_scores", _recorder(writes, "quant_scores")))
        stack.enter_context(patch.object(RP, "compute_portfolio", _portfolio_mock(writes)))
        stack.enter_context(patch("src.backtest.run_backtest", _backtest_mock(writes)))

        errors: list = []
        RP._step_compute_indicators(conn, ["005930.KS", "AAPL"], errors)
        RP._step_compute_quant(conn, ["005930.KS", "AAPL"], errors)
        RP._step_compute_portfolio(conn, errors)
        RP._step_backtest(conn, errors)
    return writes


def _new_daily_writes() -> dict:
    writes: dict = {}
    conn = _ctx_conn(WATCHLIST_ROWS)
    with ExitStack() as stack:
        stack.enter_context(patch.object(PA, "_load_price_df", lambda _t, _c: DUMMY_DF))
        stack.enter_context(patch.object(PA.compute_indicators, "compute_indicators", _indicators_fixture))
        stack.enter_context(patch.object(PA.db, "upsert_indicators_daily", _recorder(writes, "indicators_daily")))
        stack.enter_context(patch.object(PA.compute_quant, "compute_quant_universe", lambda _t, _c: QUANT_ROWS))
        stack.enter_context(patch.object(PA.db, "upsert_quant_scores", _recorder(writes, "quant_scores")))
        stack.enter_context(patch.object(PA.compute_portfolio, "compute_portfolio", _portfolio_mock(writes)))
        stack.enter_context(patch("src.backtest.run_backtest", _backtest_mock(writes)))
        stack.enter_context(patch.object(PA.db, "get_conn", lambda: conn))
        stack.enter_context(patch.object(PA, "_step_market_score", lambda *a, **k: None))
        stack.enter_context(patch.object(PA.db, "log_run_start", lambda _c, kind: 1))
        stack.enter_context(patch.object(PA.db, "log_run_finish", lambda _c, run_id, status, errors: None))
        PA.run("daily")
    return writes


def test_analysis_daily_snapshot_matches_legacy():
    assert _snapshot(_new_daily_writes()) == _snapshot(_legacy_daily_writes())


def test_analysis_daily_runs_indicators_quant_portfolio_backtest():
    snap = _snapshot(_new_daily_writes())
    assert all(snap[t] for t in ANALYSIS_TABLES), snap


# ──────────────────────────────────────────────────────────────
# refresh: legacy news_refresh 분석(recompute 지표 + 퀀트) vs 새 pipeline_analysis
# ──────────────────────────────────────────────────────────────

def _legacy_refresh_writes() -> dict:
    import src.news_refresh as NR

    writes: dict = {}
    conn = _ctx_conn(WATCHLIST_ROWS)
    with ExitStack() as stack:
        # 가격 루프는 비우고(분석 비교 대상 아님) 지표·퀀트만 실행시킨다
        stack.enter_context(patch("src.ingest_kr.fetch_kr_prices", lambda _t: []))
        stack.enter_context(patch("src.ingest_us.fetch_us_prices", lambda _t: []))
        stack.enter_context(patch("src.compute_indicators.recompute_indicators_to_db", _recompute_marker(writes)))
        stack.enter_context(patch("src.compute_quant.compute_quant_universe", lambda _t, _c: QUANT_ROWS))
        stack.enter_context(patch("src.db.upsert_quant_scores", _recorder(writes, "quant_scores")))
        NR._refresh_prices_light(conn)
    return writes


def _new_refresh_writes() -> dict:
    writes: dict = {}
    conn = _ctx_conn(WATCHLIST_ROWS)
    with ExitStack() as stack:
        stack.enter_context(patch.object(PA.compute_indicators, "recompute_indicators_to_db", _recompute_marker(writes)))
        stack.enter_context(patch.object(PA.compute_quant, "compute_quant_universe", lambda _t, _c: QUANT_ROWS))
        stack.enter_context(patch.object(PA.db, "upsert_quant_scores", _recorder(writes, "quant_scores")))
        stack.enter_context(patch.object(PA.db, "get_conn", lambda: conn))
        stack.enter_context(patch.object(PA, "_step_market_score", lambda *a, **k: None))
        stack.enter_context(patch.object(PA.db, "log_run_start", lambda _c, kind: 1))
        stack.enter_context(patch.object(PA.db, "log_run_finish", lambda _c, run_id, status, errors: None))
        PA.run("refresh")
    return writes


def test_analysis_refresh_snapshot_matches_legacy():
    assert _snapshot(_new_refresh_writes()) == _snapshot(_legacy_refresh_writes())


def test_analysis_refresh_skips_portfolio_and_backtest():
    conn = _ctx_conn(WATCHLIST_ROWS)
    portfolio_mock = MagicMock()
    backtest_mock = MagicMock()
    with ExitStack() as stack:
        stack.enter_context(patch.object(PA.compute_indicators, "recompute_indicators_to_db", lambda _c, _t: 0))
        stack.enter_context(patch.object(PA.compute_quant, "compute_quant_universe", lambda _t, _c: []))
        stack.enter_context(patch.object(PA.db, "upsert_quant_scores", lambda _c, rows: None))
        stack.enter_context(patch.object(PA.compute_portfolio, "compute_portfolio", portfolio_mock))
        stack.enter_context(patch("src.backtest.run_backtest", backtest_mock))
        stack.enter_context(patch.object(PA.db, "get_conn", lambda: conn))
        stack.enter_context(patch.object(PA, "_step_market_score", lambda *a, **k: None))
        stack.enter_context(patch.object(PA.db, "log_run_start", lambda _c, kind: 1))
        stack.enter_context(patch.object(PA.db, "log_run_finish", lambda _c, run_id, status, errors: None))
        result = PA.run("refresh")
    portfolio_mock.assert_not_called()
    backtest_mock.assert_not_called()
    assert "portfolio" not in result["counts"]
    assert "backtest" not in result["counts"]


def test_analysis_refresh_uses_recompute_not_per_ticker_loop():
    # refresh 지표는 recompute_indicators_to_db 경로(daily의 per-ticker compute_indicators 아님)
    writes = _new_refresh_writes()
    assert writes["indicators_daily"] == [{"recompute_tickers": ["005930.KS", "AAPL"]}]


# ──────────────────────────────────────────────────────────────
# 계약: 프로필·run_kind·종료코드
# ──────────────────────────────────────────────────────────────

def test_invalid_profile_run_raises():
    with pytest.raises(ValueError):
        PA.run("hourly")


def test_invalid_profile_main_returns_exit_code_2():
    assert PA.main(["--profile", "hourly"]) == 2


def test_run_kind_is_pipeline_analysis():
    captured = {}
    conn = _ctx_conn(WATCHLIST_ROWS)
    with ExitStack() as stack:
        stack.enter_context(patch.object(PA, "_load_price_df", lambda _t, _c: DUMMY_DF))
        stack.enter_context(patch.object(PA.compute_indicators, "compute_indicators", _indicators_fixture))
        stack.enter_context(patch.object(PA.db, "upsert_indicators_daily", lambda _c, rows: None))
        stack.enter_context(patch.object(PA.compute_quant, "compute_quant_universe", lambda _t, _c: QUANT_ROWS))
        stack.enter_context(patch.object(PA.db, "upsert_quant_scores", lambda _c, rows: None))
        stack.enter_context(patch.object(PA.compute_portfolio, "compute_portfolio", lambda _c: PORTFOLIO_RESULT))
        stack.enter_context(patch("src.backtest.run_backtest", lambda _c: BACKTEST_RESULT))
        stack.enter_context(patch.object(PA.db, "get_conn", lambda: conn))
        stack.enter_context(patch.object(PA, "_step_market_score", lambda *a, **k: None))
        stack.enter_context(patch.object(PA, "_step_signal_track", lambda *a, **k: None))
        stack.enter_context(patch.object(PA.db, "log_run_start", lambda _c, kind: captured.setdefault("kind", kind) or 1))
        stack.enter_context(patch.object(PA.db, "log_run_finish", lambda _c, run_id, status, errors: captured.setdefault("status", status)))
        result = PA.run("daily")
    assert captured["kind"] == "pipeline_analysis"
    assert result["status"] == "success"
    assert captured["status"] == "success"


def test_fatal_universe_failure_exit_code_1():
    conn = _ctx_conn(WATCHLIST_ROWS)
    with ExitStack() as stack:
        stack.enter_context(patch.object(PA.db, "get_conn", lambda: conn))
        stack.enter_context(patch.object(PA, "_step_market_score", lambda *a, **k: None))
        stack.enter_context(patch.object(PA.db, "log_run_start", lambda _c, kind: 1))
        stack.enter_context(patch.object(PA.db, "log_run_finish", lambda _c, run_id, status, errors: None))
        stack.enter_context(patch("src.pipeline_analysis.active_universe", side_effect_raise()))
        result = PA.run("daily")
    assert result["status"] == "failed"


def side_effect_raise():
    def _raise(*_a, **_k):
        raise RuntimeError("boom")
    return _raise
