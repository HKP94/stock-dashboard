"""
tests/test_pipeline_wrapper_behavior.py — 파이프라인 분리 6단계 호환 래퍼 검증

run_pipeline/news_refresh가 새 세 실행기를 호출하는 얇은 래퍼로 전환된 뒤에도
반환 계약·asof 전달·오류 집계·assemble/export 동작이 보존됨을 고정한다.
외부·LLM은 호출하지 않는다(실행기 .run 자체를 mock).
"""

from __future__ import annotations

from contextlib import ExitStack
from datetime import date
from unittest.mock import mock_open, patch

from tests.test_pipeline_behavior_baseline import _ctx_conn


def _runner_ok(captured: list, name: str, counts: dict | None = None, errors: list | None = None):
    def _fn(profile, asof=None):
        captured.append((name, profile, asof))
        return {"status": "success", "errors": errors or [], "counts": counts or {}}
    return _fn


# ──────────────────────────────────────────────────────────────
# run_pipeline (daily)
# ──────────────────────────────────────────────────────────────

def test_run_pipeline_propagates_daily_profile_and_asof_to_all_runners():
    import src.run_pipeline as RP

    captured: list = []
    asof = date(2026, 6, 21)
    with ExitStack() as stack:
        stack.enter_context(patch.object(RP.pipeline_ingest, "run", _runner_ok(captured, "ingest")))
        stack.enter_context(patch.object(RP.pipeline_analysis, "run", _runner_ok(captured, "analysis")))
        stack.enter_context(patch.object(RP.pipeline_synthesis, "run", _runner_ok(captured, "synthesis")))
        stack.enter_context(patch.object(RP, "get_conn", lambda: _ctx_conn()))
        stack.enter_context(patch.object(RP, "_step_assemble", lambda _c, _e: ["rec"]))
        records = RP.run_pipeline(asof)

    assert records == ["rec"]
    assert [c[0] for c in captured] == ["ingest", "analysis", "synthesis"]
    assert all(profile == "daily" and a == asof for _, profile, a in captured)


def test_run_pipeline_returns_empty_when_assemble_fails_gracefully():
    # _step_assemble가 assemble_daily 예외를 잡아 []를 돌려주는 계약 보존
    import src.run_pipeline as RP

    with ExitStack() as stack:
        stack.enter_context(patch.object(RP.pipeline_ingest, "run", _runner_ok([], "ingest")))
        stack.enter_context(patch.object(RP.pipeline_analysis, "run", _runner_ok([], "analysis")))
        stack.enter_context(patch.object(RP.pipeline_synthesis, "run", _runner_ok([], "synthesis")))
        stack.enter_context(patch.object(RP, "get_conn", lambda: _ctx_conn()))
        stack.enter_context(patch.object(RP, "assemble_daily", lambda _c: (_ for _ in ()).throw(RuntimeError("boom"))))
        records = RP.run_pipeline(date(2026, 6, 21))

    assert records == []


def test_run_pipeline_does_not_invoke_legacy_step_functions():
    # 래퍼는 위임만 한다 — 레거시 _step_market 등은 호출되지 않아야 한다(중복본은 stage 8까지 잔존)
    import src.run_pipeline as RP

    called: list = []
    with ExitStack() as stack:
        stack.enter_context(patch.object(RP.pipeline_ingest, "run", _runner_ok([], "ingest")))
        stack.enter_context(patch.object(RP.pipeline_analysis, "run", _runner_ok([], "analysis")))
        stack.enter_context(patch.object(RP.pipeline_synthesis, "run", _runner_ok([], "synthesis")))
        stack.enter_context(patch.object(RP, "get_conn", lambda: _ctx_conn()))
        stack.enter_context(patch.object(RP, "_step_assemble", lambda _c, _e: []))
        stack.enter_context(patch.object(RP, "_step_market", lambda *a, **k: called.append("market")))
        stack.enter_context(patch.object(RP, "_step_compute_quant", lambda *a, **k: called.append("quant")))
        stack.enter_context(patch.object(RP, "_step_action_advice", lambda *a, **k: called.append("action")))
        RP.run_pipeline(date(2026, 6, 21))

    assert called == []


# ──────────────────────────────────────────────────────────────
# news_refresh (refresh)
# ──────────────────────────────────────────────────────────────

def _run_news_refresh(ing_counts=None, ing_errors=None, ana_errors=None, syn_counts=None, syn_errors=None):
    import src.news_refresh as NR

    with ExitStack() as stack:
        stack.enter_context(patch.object(NR.pipeline_ingest, "run", _runner_ok([], "ingest", ing_counts, ing_errors)))
        stack.enter_context(patch.object(NR.pipeline_analysis, "run", _runner_ok([], "analysis", None, ana_errors)))
        stack.enter_context(patch.object(NR.pipeline_synthesis, "run", _runner_ok([], "synthesis", syn_counts, syn_errors)))
        stack.enter_context(patch("src.export_dashboard_data.build_data", lambda: {"stocks": []}))
        stack.enter_context(patch("builtins.open", mock_open()))
        stack.enter_context(patch("json.dump", lambda data, fh, **kwargs: None))
        return NR.run_news_refresh()


def test_news_refresh_maps_counts_to_return_contract():
    result = _run_news_refresh(
        ing_counts={"news_raw": 7, "prices_daily": 11},
        syn_counts={"news_analysis": 3},
    )
    assert result["new_news"] == 7
    assert result["prices"] == 11
    assert result["enriched"] == 3


def test_news_refresh_aggregates_errors_from_all_three_runners():
    result = _run_news_refresh(
        ing_errors=[{"step": "price", "error": "x", "ts": "t"}],
        ana_errors=[{"step": "compute_quant", "error": "y", "ts": "t"}],
        syn_errors=[{"step": "enrich_news", "error": "z", "ts": "t"}],
    )
    steps = [e["step"] for e in result["errors"]]
    assert steps == ["price", "compute_quant", "enrich_news"]
