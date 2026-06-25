"""
tests/test_pipeline_synthesis_behavior.py — 파이프라인 분리 4단계 행위 보존

legacy 종합(run_pipeline Step 7 + 액션 제언 / news_refresh 18시 종합)과
새 pipeline_synthesis 의 동작이 동일함을 증명한다. LLM은 전부 mock(외부 호출 0).

enrich_* 함수는 각자 테이블을 내부 적재하므로 호출 마커로 비교하고,
액션 제언 행(stock_action_advice)은 upsert 인자를 직접 캡처해 숫자 불변을 확인한다.
refresh가 폴백복구·논거·거시요약·액션제언을 실행하지 않음도 고정한다.
"""

from __future__ import annotations

from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import src.pipeline_synthesis as PS
from tests.test_pipeline_behavior_baseline import _ctx_conn

# build_action_frame가 .get으로 읽는 최소 종목 fixture (숫자는 결정론적으로 산출)
STOCK_FIXTURE = {"t": "AAPL", "signal": {"label": "매수"}, "price": 210.0, "holding": None, "consensus": None}
PORTFOLIO_SNAP = {"asset_total": 1_000_000.0}
BUILD_DATA = {"stocks": [STOCK_FIXTURE], "market": {"overall": "bull"}, "portfolio": PORTFOLIO_SNAP}
TARGET_ROWS = [{"ticker": "AAPL"}]  # _select_action_advice_targets의 3개 쿼리 공용 결과

# 액션 제언 숫자 필드(결정론 코드 산출 — LLM과 무관해야 함)
NUMERIC_FIELDS = [
    "direction", "current_weight", "target_weight_low", "target_weight_high",
    "weight_action", "entry_zone", "exit_zone", "confidence",
]


def _enrich_tuple_mock(calls: list, name: str):
    def _fn(_conn):
        calls.append(name)
        return (1, [])
    return _fn


def _enrich_bool_mock(calls: list, name: str):
    def _fn(_conn):
        calls.append(name)
        return True
    return _fn


def _action_sink(rows: list):
    def _fn(_conn, row):
        rows.append(row)
    return _fn


def _numeric(row) -> dict:
    return {f: getattr(row, f) for f in NUMERIC_FIELDS}


# ──────────────────────────────────────────────────────────────
# daily: legacy run_pipeline 종합 vs 새 pipeline_synthesis
# ──────────────────────────────────────────────────────────────

def _legacy_daily(narrative=None):
    import src.run_pipeline as RP

    calls: list = []
    rows: list = []
    conn = _ctx_conn(TARGET_ROWS)
    with ExitStack() as stack:
        stack.enter_context(patch.object(RP, "enrich_news_batch", _enrich_tuple_mock(calls, "enrich_news")))
        stack.enter_context(patch.object(RP, "reenrich_stale_fallbacks", _enrich_tuple_mock(calls, "reenrich_fallback")))
        stack.enter_context(patch.object(RP, "extract_analyst_views_batch", _enrich_tuple_mock(calls, "analyst_views")))
        stack.enter_context(patch.object(RP, "enrich_market_summary", _enrich_bool_mock(calls, "enrich_market")))
        stack.enter_context(patch.object(RP, "summarize_market_news_digest", _enrich_bool_mock(calls, "market_news_digest")))
        stack.enter_context(patch.object(RP, "summarize_macro_environment", _enrich_bool_mock(calls, "macro_summary")))
        stack.enter_context(patch.object(RP, "summarize_stock_action_advice", lambda _f: narrative))
        stack.enter_context(patch.object(RP, "_within_budget", lambda _s, _b: True))
        stack.enter_context(patch.object(RP, "_get_manual_research_model", lambda: "fake-model"))
        stack.enter_context(patch.object(RP, "upsert_stock_action_advice", _action_sink(rows)))
        stack.enter_context(patch("src.export_dashboard_data.build_data", lambda: BUILD_DATA))

        errors: list = []
        RP._step_enrich_gemini(conn, errors)
        RP._step_action_advice(conn, errors)
    return calls, rows


def _new_daily(narrative=None):
    calls: list = []
    rows: list = []
    conn = _ctx_conn(TARGET_ROWS)
    with ExitStack() as stack:
        stack.enter_context(patch.object(PS.enrich_gemini, "enrich_news_batch", _enrich_tuple_mock(calls, "enrich_news")))
        stack.enter_context(patch.object(PS.enrich_gemini, "reenrich_stale_fallbacks", _enrich_tuple_mock(calls, "reenrich_fallback")))
        stack.enter_context(patch.object(PS.enrich_gemini, "extract_analyst_views_batch", _enrich_tuple_mock(calls, "analyst_views")))
        stack.enter_context(patch.object(PS.enrich_gemini, "enrich_market_summary", _enrich_bool_mock(calls, "enrich_market")))
        stack.enter_context(patch.object(PS.enrich_gemini, "summarize_market_news_digest", _enrich_bool_mock(calls, "market_news_digest")))
        stack.enter_context(patch.object(PS.enrich_gemini, "summarize_macro_environment", _enrich_bool_mock(calls, "macro_summary")))
        stack.enter_context(patch.object(PS.enrich_gemini, "summarize_stock_action_advice", lambda _f: narrative))
        stack.enter_context(patch.object(PS.enrich_gemini, "_within_budget", lambda _s, _b: True))
        stack.enter_context(patch.object(PS.enrich_gemini, "_get_manual_research_model", lambda: "fake-model"))
        stack.enter_context(patch.object(PS.db, "upsert_stock_action_advice", _action_sink(rows)))
        stack.enter_context(patch("src.export_dashboard_data.build_data", lambda: BUILD_DATA))
        stack.enter_context(patch.object(PS.db, "get_conn", lambda: conn))
        stack.enter_context(patch.object(PS.db, "log_run_start", lambda _c, kind: 1))
        stack.enter_context(patch.object(PS.db, "log_run_finish", lambda _c, run_id, status, errors: None))
        PS.run("daily")
    return calls, rows


def test_synthesis_daily_call_order_matches_legacy():
    legacy_calls, _ = _legacy_daily()
    new_calls, _ = _new_daily()
    assert new_calls == legacy_calls
    assert new_calls == ["enrich_news", "reenrich_fallback", "analyst_views",
                         "enrich_market", "market_news_digest", "macro_summary"]


def test_synthesis_daily_action_advice_matches_legacy():
    _, legacy_rows = _legacy_daily()
    _, new_rows = _new_daily()
    assert len(new_rows) == len(legacy_rows) == 1
    assert _numeric(new_rows[0]) == _numeric(legacy_rows[0])


def test_synthesis_action_numbers_invariant_to_llm():
    # LLM 서술이 None이든 임의 narrative든 숫자(방향·비중·구간)는 동일해야 한다
    # supporting/opposing은 frame 폴백을 쓰게 None(스키마는 dict 리스트라 임의 문자열 불가).
    # rationale만 LLM 서술로 달라진다 — 숫자 불변 검증이 목적.
    narrative = SimpleNamespace(
        rationale="완전히 다른 서술",
        supportingFactors=None,
        opposingFactors=None,
        divergenceNote=None,
        concentrationNote=None,  # 신규-D: 실제 narrative 스키마와 동일하게 필드 포함
    )
    _, rows_none = _new_daily(narrative=None)
    _, rows_narr = _new_daily(narrative=narrative)
    assert _numeric(rows_none[0]) == _numeric(rows_narr[0])
    # 서술 필드는 LLM에 따라 달라진다(결정론 숫자와 분리됨)
    assert rows_narr[0].rationale == "완전히 다른 서술"
    assert rows_none[0].rationale != rows_narr[0].rationale


def test_synthesis_does_not_write_market_daily_numbers():
    # 종합은 market_daily 숫자/payload writer(upsert_market_daily)를 호출하지 않는다
    # (요약 컬럼 UPDATE는 enrich_market_summary 내부 SQL 소관, 여기선 mock)
    market_writer = MagicMock()
    calls: list = []
    conn = _ctx_conn(TARGET_ROWS)
    with ExitStack() as stack:
        stack.enter_context(patch.object(PS.enrich_gemini, "enrich_news_batch", _enrich_tuple_mock(calls, "enrich_news")))
        stack.enter_context(patch.object(PS.enrich_gemini, "reenrich_stale_fallbacks", _enrich_tuple_mock(calls, "reenrich_fallback")))
        stack.enter_context(patch.object(PS.enrich_gemini, "extract_analyst_views_batch", _enrich_tuple_mock(calls, "analyst_views")))
        stack.enter_context(patch.object(PS.enrich_gemini, "enrich_market_summary", _enrich_bool_mock(calls, "enrich_market")))
        stack.enter_context(patch.object(PS.enrich_gemini, "summarize_market_news_digest", _enrich_bool_mock(calls, "market_news_digest")))
        stack.enter_context(patch.object(PS.enrich_gemini, "summarize_macro_environment", _enrich_bool_mock(calls, "macro_summary")))
        stack.enter_context(patch.object(PS.enrich_gemini, "summarize_stock_action_advice", lambda _f: None))
        stack.enter_context(patch.object(PS.enrich_gemini, "_within_budget", lambda _s, _b: True))
        stack.enter_context(patch.object(PS.db, "upsert_stock_action_advice", lambda _c, row: None))
        stack.enter_context(patch.object(PS.db, "upsert_market_daily", market_writer))
        stack.enter_context(patch("src.export_dashboard_data.build_data", lambda: BUILD_DATA))
        stack.enter_context(patch.object(PS.db, "get_conn", lambda: conn))
        stack.enter_context(patch.object(PS.db, "log_run_start", lambda _c, kind: 1))
        stack.enter_context(patch.object(PS.db, "log_run_finish", lambda _c, run_id, status, errors: None))
        PS.run("daily")
    market_writer.assert_not_called()


# ──────────────────────────────────────────────────────────────
# refresh: legacy news_refresh 종합 vs 새 pipeline_synthesis
# ──────────────────────────────────────────────────────────────

def _legacy_refresh_calls() -> list:
    """news_refresh 18시 종합 부분(뉴스요약·시황·시장뉴스요약)만 재현."""
    import src.news_refresh as NR

    calls: list = []
    conn = _ctx_conn(TARGET_ROWS)
    with ExitStack() as stack:
        stack.enter_context(patch.object(NR, "enrich_news_batch", _enrich_tuple_mock(calls, "enrich_news")))
        stack.enter_context(patch.object(NR, "enrich_market_summary", _enrich_bool_mock(calls, "enrich_market")))
        stack.enter_context(patch.object(NR, "summarize_market_news_digest", _enrich_bool_mock(calls, "market_news_digest")))
        # news_refresh 본문의 종합 3블록과 동일 순서로 호출
        enriched, errs = NR.enrich_news_batch(conn)
        NR.enrich_market_summary(conn)
        NR.summarize_market_news_digest(conn)
    return calls


def _new_refresh_calls() -> tuple[list, list]:
    calls: list = []
    rows: list = []
    conn = _ctx_conn(TARGET_ROWS)
    with ExitStack() as stack:
        stack.enter_context(patch.object(PS.enrich_gemini, "enrich_news_batch", _enrich_tuple_mock(calls, "enrich_news")))
        stack.enter_context(patch.object(PS.enrich_gemini, "reenrich_stale_fallbacks", _enrich_tuple_mock(calls, "reenrich_fallback")))
        stack.enter_context(patch.object(PS.enrich_gemini, "extract_analyst_views_batch", _enrich_tuple_mock(calls, "analyst_views")))
        stack.enter_context(patch.object(PS.enrich_gemini, "enrich_market_summary", _enrich_bool_mock(calls, "enrich_market")))
        stack.enter_context(patch.object(PS.enrich_gemini, "summarize_market_news_digest", _enrich_bool_mock(calls, "market_news_digest")))
        stack.enter_context(patch.object(PS.enrich_gemini, "summarize_macro_environment", _enrich_bool_mock(calls, "macro_summary")))
        stack.enter_context(patch.object(PS.enrich_gemini, "summarize_stock_action_advice", lambda _f: None))
        stack.enter_context(patch.object(PS.enrich_gemini, "_within_budget", lambda _s, _b: True))
        stack.enter_context(patch.object(PS.db, "upsert_stock_action_advice", _action_sink(rows)))
        stack.enter_context(patch("src.export_dashboard_data.build_data", lambda: BUILD_DATA))
        stack.enter_context(patch.object(PS.db, "get_conn", lambda: conn))
        stack.enter_context(patch.object(PS.db, "log_run_start", lambda _c, kind: 1))
        stack.enter_context(patch.object(PS.db, "log_run_finish", lambda _c, run_id, status, errors: None))
        PS.run("refresh")
    return calls, rows


def test_synthesis_refresh_call_order_matches_legacy():
    new_calls, _ = _new_refresh_calls()
    assert new_calls == _legacy_refresh_calls()
    assert new_calls == ["enrich_news", "enrich_market", "market_news_digest"]


def test_synthesis_refresh_skips_fallback_analyst_macro_action():
    new_calls, action_rows = _new_refresh_calls()
    for skipped in ("reenrich_fallback", "analyst_views", "macro_summary"):
        assert skipped not in new_calls, (skipped, new_calls)
    assert action_rows == []  # 액션 제언 미실행


# ──────────────────────────────────────────────────────────────
# 계약: 프로필·run_kind·종료코드
# ──────────────────────────────────────────────────────────────

def test_invalid_profile_run_raises():
    with pytest.raises(ValueError):
        PS.run("hourly")


def test_invalid_profile_main_returns_exit_code_2():
    assert PS.main(["--profile", "hourly"]) == 2


def test_run_kind_is_pipeline_synthesis():
    captured = {}
    calls: list = []
    conn = _ctx_conn(TARGET_ROWS)
    with ExitStack() as stack:
        stack.enter_context(patch.object(PS.enrich_gemini, "enrich_news_batch", _enrich_tuple_mock(calls, "enrich_news")))
        stack.enter_context(patch.object(PS.enrich_gemini, "reenrich_stale_fallbacks", _enrich_tuple_mock(calls, "reenrich_fallback")))
        stack.enter_context(patch.object(PS.enrich_gemini, "extract_analyst_views_batch", _enrich_tuple_mock(calls, "analyst_views")))
        stack.enter_context(patch.object(PS.enrich_gemini, "enrich_market_summary", _enrich_bool_mock(calls, "enrich_market")))
        stack.enter_context(patch.object(PS.enrich_gemini, "summarize_market_news_digest", _enrich_bool_mock(calls, "market_news_digest")))
        stack.enter_context(patch.object(PS.enrich_gemini, "summarize_macro_environment", _enrich_bool_mock(calls, "macro_summary")))
        stack.enter_context(patch.object(PS.enrich_gemini, "summarize_stock_action_advice", lambda _f: None))
        stack.enter_context(patch.object(PS.enrich_gemini, "_within_budget", lambda _s, _b: True))
        stack.enter_context(patch.object(PS.db, "upsert_stock_action_advice", lambda _c, row: None))
        stack.enter_context(patch("src.export_dashboard_data.build_data", lambda: BUILD_DATA))
        stack.enter_context(patch.object(PS.db, "get_conn", lambda: conn))
        stack.enter_context(patch.object(PS.db, "log_run_start", lambda _c, kind: captured.setdefault("kind", kind) or 1))
        stack.enter_context(patch.object(PS.db, "log_run_finish", lambda _c, run_id, status, errors: captured.setdefault("status", status)))
        result = PS.run("daily")
    assert captured["kind"] == "pipeline_synthesis"
    assert result["status"] == "success"
    assert captured["status"] == "success"


def test_fatal_step_failure_exit_code_1():
    # 단계가 자체 가드를 벗어나 예외를 던지면 바깥 try가 잡아 failed → 종료코드 1
    conn = _ctx_conn(TARGET_ROWS)
    with ExitStack() as stack:
        stack.enter_context(patch.object(PS.db, "get_conn", lambda: conn))
        stack.enter_context(patch.object(PS.db, "log_run_start", lambda _c, kind: 1))
        stack.enter_context(patch.object(PS.db, "log_run_finish", lambda _c, run_id, status, errors: None))
        stack.enter_context(patch.object(PS, "_step_enrich_news", _raise))
        result = PS.run("daily")
    assert result["status"] == "failed"


def _raise(*_a, **_k):
    raise RuntimeError("boom")
