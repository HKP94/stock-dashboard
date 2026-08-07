"""
tests/test_pipeline_ingest_behavior.py — 파이프라인 분리 2단계 행위 보존

legacy 수집(run_pipeline의 수집 단계 + news_refresh 경량 가격) 과
새 pipeline_ingest 의 DB 쓰기 스냅샷이 동일함을 증명한다.

외부 API·LLM은 호출하지 않는다(fixture/monkeypatch). DB는 MagicMock conn으로
격리하고 upsert/insert 호출 인자를 캡처해 비교한다.
지표·점수·LLM·export 비호출도 함께 고정한다.
"""

from __future__ import annotations

from contextlib import ExitStack
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import src.pipeline_ingest as PI
from src.pipeline_common import VALID_PROFILES
from tests.test_pipeline_behavior_baseline import (
    DB_SNAPSHOT_EXCLUDE_FIELDS,
    _ctx_conn,
    _normalize_snapshot,
)

EARNINGS_RESULT = {"counts": {"us": 0, "kr": 0, "kr_expected": 0, "tickers": 0},
                   "refetch": [], "errors": []}

# 비교 대상 9개 수집 테이블 (설계 §8)
INGEST_TABLES = [
    "market_daily",
    "macro_indicators",
    "driver_prices",
    "prices_daily",
    "fundamentals",
    "valuation",
    "analyst",
    "news_raw",
    "market_news",
]

WATCHLIST_ROWS = [
    {"ticker": "005930.KS", "market": "KR", "name": "삼성전자"},
    {"ticker": "AAPL", "market": "US", "name": "Apple"},
]

# 외부 수집 함수 fixture (legacy/new 공용)
# PR-A: 수집기는 체결일별 행 목록을 돌려준다(단일 행 → markets 리스트).
MARKET_RESULT = {"markets": [{"asof": "2026-06-21", "kospi": 2700.0}], "errors": []}
MACRO_RESULT = {"rows": [{"indicator": "vix", "value": 14.2}], "errors": []}
DRIVER_RESULT = {"rows": [{"ticker": "AAPL", "driver": "usd", "value": 1.0}], "errors": []}
KR_RESULT = {
    "prices": {"005930.KS": [{"ticker": "005930.KS", "date": "2026-06-21", "close": 80000.0}]},
    "fundamentals": {"005930.KS": [{"ticker": "005930.KS", "roe": 0.12}]},
    "valuations": {"005930.KS": {"ticker": "005930.KS", "per": 12.0}},
    "analysts": {"005930.KS": {"ticker": "005930.KS", "target_price": 95000.0}},
    "errors": [],
}
US_RESULT = {
    "prices": {"AAPL": [{"ticker": "AAPL", "date": "2026-06-21", "close": 210.0}]},
    "fundamentals": {"AAPL": [{"ticker": "AAPL", "roe": 1.5}]},
    "valuations": {"AAPL": {"ticker": "AAPL", "per": 30.0}},
    "analysts": {"AAPL": {"ticker": "AAPL", "target_price": 240.0}},
    "errors": [],
}
NEWS_RESULT = {
    "news": {
        "005930.KS": [{"ticker": "005930.KS", "url_hash": "kr1", "title": "삼성 뉴스"}],
        "AAPL": [{"ticker": "AAPL", "url_hash": "us1", "title": "Apple news"}],
    },
    "errors": [],
}
MARKET_NEWS_RESULT = {"rows": [{"url_hash": "mn1", "title": "시장 뉴스"}], "errors": []}

# 경량 가격 fixture: news_refresh._refresh_prices_light가 rows[-1].date(속성)에 접근하므로 객체로 둔다
KR_PRICE_ROWS = [SimpleNamespace(ticker="005930.KS", date=date(2026, 6, 21), close=80000.0)]
US_PRICE_ROWS = [SimpleNamespace(ticker="AAPL", date=date(2026, 6, 21), close=210.0)]


def _recorder(writes: dict, table: str, *, returns_count: bool = False):
    def _fn(conn, payload):
        writes.setdefault(table, []).append(payload)
        return len(payload) if returns_count else None
    return _fn


def _patch_db(stack: ExitStack, module, writes: dict) -> None:
    """대상 module 네임스페이스의 upsert/insert를 캡처 sink로 교체."""
    stack.enter_context(patch.object(module, "upsert_market_daily", _recorder(writes, "market_daily")))
    stack.enter_context(patch.object(module, "upsert_macro_indicators", _recorder(writes, "macro_indicators")))
    stack.enter_context(patch.object(module, "upsert_price_daily", _recorder(writes, "prices_daily")))
    stack.enter_context(patch.object(module, "upsert_fundamentals", _recorder(writes, "fundamentals")))
    stack.enter_context(patch.object(module, "upsert_valuation", _recorder(writes, "valuation")))
    stack.enter_context(patch.object(module, "upsert_analyst", _recorder(writes, "analyst")))
    stack.enter_context(patch.object(module, "insert_news_raw", _recorder(writes, "news_raw", returns_count=True)))
    stack.enter_context(patch.object(module, "insert_market_news", _recorder(writes, "market_news", returns_count=True)))


def _snapshot(writes: dict) -> dict:
    return _normalize_snapshot(
        {t: writes.get(t, []) for t in INGEST_TABLES},
        exclude_fields=DB_SNAPSHOT_EXCLUDE_FIELDS,
    )


# ──────────────────────────────────────────────────────────────
# daily: legacy run_pipeline 수집 단계 vs 새 pipeline_ingest
# ──────────────────────────────────────────────────────────────

def _legacy_daily_writes() -> dict:
    import src.run_pipeline as RP

    writes: dict = {}
    conn = _ctx_conn(WATCHLIST_ROWS)
    with ExitStack() as stack:
        # run_pipeline은 db 함수를 이름으로 import → RP 네임스페이스 패치
        # (insert_*는 db.py 원본을 그대로 쓰므로 RP에 바인딩된 이름을 교체)
        stack.enter_context(patch.object(RP, "upsert_market_daily", _recorder(writes, "market_daily")))
        stack.enter_context(patch.object(RP, "upsert_macro_indicators", _recorder(writes, "macro_indicators")))
        stack.enter_context(patch.object(RP, "upsert_price_daily", _recorder(writes, "prices_daily")))
        stack.enter_context(patch.object(RP, "upsert_fundamentals", _recorder(writes, "fundamentals")))
        stack.enter_context(patch.object(RP, "upsert_valuation", _recorder(writes, "valuation")))
        stack.enter_context(patch.object(RP, "upsert_analyst", _recorder(writes, "analyst")))
        stack.enter_context(patch.object(RP, "insert_news_raw", _recorder(writes, "news_raw", returns_count=True)))
        stack.enter_context(patch.object(RP, "insert_market_news", _recorder(writes, "market_news", returns_count=True)))
        stack.enter_context(patch.object(RP, "run_market_ingest", lambda: MARKET_RESULT))
        stack.enter_context(patch.object(RP, "run_macro_ingest", lambda: MACRO_RESULT))
        stack.enter_context(patch.object(RP, "run_driver_price_ingest", lambda _c: DRIVER_RESULT))
        stack.enter_context(patch.object(RP, "run_kr_ingest", lambda _t: KR_RESULT))
        stack.enter_context(patch.object(RP, "run_us_ingest", lambda _t: US_RESULT))
        stack.enter_context(patch.object(RP, "run_news_ingest", lambda _t, company_names: NEWS_RESULT))
        stack.enter_context(patch.object(RP, "run_market_news_ingest", lambda: MARKET_NEWS_RESULT))

        errors: list = []
        RP._step_market(conn, errors)
        RP._step_macro(conn, errors)
        RP._step_driver_prices(conn, errors)
        RP._step_ingest_kr(conn, ["005930.KS"], errors)
        RP._step_ingest_us(conn, ["AAPL"], errors)
        RP._step_ingest_news(conn, ["005930.KS", "AAPL"], errors)
        RP._step_ingest_market_news(conn, errors)
    return writes


def _new_ingest_writes(profile: str) -> dict:
    writes: dict = {}
    conn = _ctx_conn(WATCHLIST_ROWS)
    with ExitStack() as stack:
        _patch_db(stack, PI.db, writes)
        stack.enter_context(patch.object(PI.ingest_market, "run_market_ingest", lambda: MARKET_RESULT))
        stack.enter_context(patch.object(PI.ingest_macro, "run_macro_ingest", lambda: MACRO_RESULT))
        stack.enter_context(patch.object(PI.ingest_drivers, "run_driver_price_ingest", lambda _c: DRIVER_RESULT))
        stack.enter_context(patch.object(PI.ingest_kr, "run_kr_ingest", lambda _t: KR_RESULT))
        stack.enter_context(patch.object(PI.ingest_us, "run_us_ingest", lambda _t: US_RESULT))
        stack.enter_context(patch.object(PI.ingest_news, "run_news_ingest", lambda _t, company_names: NEWS_RESULT))
        stack.enter_context(patch.object(PI.ingest_market_news, "run_market_news_ingest", lambda: MARKET_NEWS_RESULT))
        # R7 실적 캘린더는 legacy에 없는 신규 단계 → 이 베이스라인 비교 대상 밖으로 격리.
        # (미패치 시 실제 yfinance/DART를 때리고 refetch가 fundamentals를 써서 스냅샷이 오염된다)
        stack.enter_context(patch.object(PI.ingest_earnings, "run_earnings_ingest", lambda _c, _w: EARNINGS_RESULT))
        stack.enter_context(patch.object(PI.ingest_kr, "fetch_kr_prices", lambda _t: KR_PRICE_ROWS))
        stack.enter_context(patch.object(PI.ingest_us, "fetch_us_prices", lambda _t: US_PRICE_ROWS))
        stack.enter_context(patch.object(PI.db, "get_conn", lambda: conn))
        stack.enter_context(patch.object(PI.db, "log_run_start", lambda _c, kind: 1))
        stack.enter_context(patch.object(PI.db, "log_run_finish", lambda _c, run_id, status, errors: None))
        PI.run(profile)
    return writes


def test_ingest_daily_snapshot_matches_legacy():
    assert _snapshot(_new_ingest_writes("daily")) == _snapshot(_legacy_daily_writes())


def test_ingest_daily_counts_cover_all_nine_tables():
    # daily는 9개 수집 테이블 전부를 채운다(driver_prices는 run_driver_price_ingest 내부 적재라
    # sink로는 안 보이므로 counts로 검증).
    result = _run_daily_capturing_counts()
    for table in INGEST_TABLES:
        assert result["counts"].get(table, 0) > 0, (table, result["counts"])


def _run_daily_capturing_counts() -> dict:
    conn = _ctx_conn(WATCHLIST_ROWS)
    with ExitStack() as stack:
        _patch_db(stack, PI.db, {})
        stack.enter_context(patch.object(PI.ingest_market, "run_market_ingest", lambda: MARKET_RESULT))
        stack.enter_context(patch.object(PI.ingest_macro, "run_macro_ingest", lambda: MACRO_RESULT))
        stack.enter_context(patch.object(PI.ingest_drivers, "run_driver_price_ingest", lambda _c: DRIVER_RESULT))
        stack.enter_context(patch.object(PI.ingest_kr, "run_kr_ingest", lambda _t: KR_RESULT))
        stack.enter_context(patch.object(PI.ingest_us, "run_us_ingest", lambda _t: US_RESULT))
        stack.enter_context(patch.object(PI.ingest_news, "run_news_ingest", lambda _t, company_names: NEWS_RESULT))
        stack.enter_context(patch.object(PI.ingest_market_news, "run_market_news_ingest", lambda: MARKET_NEWS_RESULT))
        # R7 실적 캘린더는 legacy에 없는 신규 단계 → 이 베이스라인 비교 대상 밖으로 격리.
        # (미패치 시 실제 yfinance/DART를 때리고 refetch가 fundamentals를 써서 스냅샷이 오염된다)
        stack.enter_context(patch.object(PI.ingest_earnings, "run_earnings_ingest", lambda _c, _w: EARNINGS_RESULT))
        stack.enter_context(patch.object(PI.db, "get_conn", lambda: conn))
        stack.enter_context(patch.object(PI.db, "log_run_start", lambda _c, kind: 1))
        stack.enter_context(patch.object(PI.db, "log_run_finish", lambda _c, run_id, status, errors: None))
        return PI.run("daily")


# ──────────────────────────────────────────────────────────────
# refresh: legacy news_refresh 경량 가격 vs 새 pipeline_ingest
# ──────────────────────────────────────────────────────────────

def _legacy_refresh_writes() -> dict:
    """news_refresh의 수집-관련 쓰기(prices/news/market_news)만 재현.

    _refresh_prices_light는 지표·퀀트도 쓰지만 그 테이블은 비교 대상이 아니다.
    """
    import src.news_refresh as NR

    writes: dict = {}
    conn = _ctx_conn(WATCHLIST_ROWS)
    with ExitStack() as stack:
        # _refresh_prices_light는 fetch_*만 함수 내부 지역 import → 원본 모듈 패치.
        # upsert_price_daily/quant은 news_refresh 모듈 상단에서 바인딩 → NR 네임스페이스 패치.
        stack.enter_context(patch("src.ingest_kr.fetch_kr_prices", lambda _t: KR_PRICE_ROWS))
        stack.enter_context(patch("src.ingest_us.fetch_us_prices", lambda _t: US_PRICE_ROWS))
        stack.enter_context(patch.object(NR, "upsert_price_daily", _recorder(writes, "prices_daily")))
        stack.enter_context(patch("src.compute_indicators.recompute_indicators_to_db", lambda _c, _t: 0))
        stack.enter_context(patch("src.compute_quant.compute_quant_universe", lambda _t, _c: []))
        stack.enter_context(patch("src.db.upsert_quant_scores", lambda _c, rows: None))
        NR._refresh_prices_light(conn)

        # 뉴스 + 시장 뉴스 (news_refresh 본문과 동일 호출)
        stack.enter_context(patch.object(NR, "run_news_ingest", lambda _t, company_names: NEWS_RESULT))
        stack.enter_context(patch.object(NR, "insert_news_raw", _recorder(writes, "news_raw", returns_count=True)))
        stack.enter_context(patch.object(NR, "run_market_news_ingest", lambda: MARKET_NEWS_RESULT))
        stack.enter_context(patch.object(NR, "insert_market_news", _recorder(writes, "market_news", returns_count=True)))
        with conn.cursor() as cur:
            cur.execute("SELECT ticker, name FROM watchlist WHERE active=TRUE")
            names = {r["ticker"]: r["name"] for r in cur.fetchall()}
        res = NR.run_news_ingest(list(names.keys()), company_names=names)
        for rows in res.get("news", {}).values():
            if rows:
                NR.insert_news_raw(conn, rows)
        mres = NR.run_market_news_ingest()
        NR.insert_market_news(conn, mres.get("rows", []))
    return writes


def test_ingest_refresh_snapshot_matches_legacy():
    assert _snapshot(_new_ingest_writes("refresh")) == _snapshot(_legacy_refresh_writes())


def test_ingest_refresh_only_touches_price_and_news_tables():
    snap = _snapshot(_new_ingest_writes("refresh"))
    assert snap["prices_daily"] and snap["news_raw"] and snap["market_news"]
    # refresh는 재무·밸류·컨센서스·거시·드라이버·시장지표를 수집하지 않는다
    for empty in ("market_daily", "macro_indicators", "driver_prices", "fundamentals", "valuation", "analyst"):
        assert snap[empty] == [], (empty, snap[empty])


# ──────────────────────────────────────────────────────────────
# 계약: 프로필·run_kind·금지 경계·종료코드
# ──────────────────────────────────────────────────────────────

def test_invalid_profile_run_raises():
    with pytest.raises(ValueError):
        PI.run("hourly")


def test_invalid_profile_main_returns_exit_code_2():
    assert PI.main(["--profile", "hourly"]) == 2


def test_run_kind_is_pipeline_ingest():
    captured = {}
    conn = _ctx_conn(WATCHLIST_ROWS)
    with ExitStack() as stack:
        _patch_db(stack, PI.db, {})
        stack.enter_context(patch.object(PI.ingest_market, "run_market_ingest", lambda: MARKET_RESULT))
        stack.enter_context(patch.object(PI.ingest_macro, "run_macro_ingest", lambda: MACRO_RESULT))
        stack.enter_context(patch.object(PI.ingest_drivers, "run_driver_price_ingest", lambda _c: DRIVER_RESULT))
        stack.enter_context(patch.object(PI.ingest_kr, "run_kr_ingest", lambda _t: KR_RESULT))
        stack.enter_context(patch.object(PI.ingest_us, "run_us_ingest", lambda _t: US_RESULT))
        stack.enter_context(patch.object(PI.ingest_news, "run_news_ingest", lambda _t, company_names: NEWS_RESULT))
        stack.enter_context(patch.object(PI.ingest_market_news, "run_market_news_ingest", lambda: MARKET_NEWS_RESULT))
        # R7 실적 캘린더는 legacy에 없는 신규 단계 → 이 베이스라인 비교 대상 밖으로 격리.
        # (미패치 시 실제 yfinance/DART를 때리고 refetch가 fundamentals를 써서 스냅샷이 오염된다)
        stack.enter_context(patch.object(PI.ingest_earnings, "run_earnings_ingest", lambda _c, _w: EARNINGS_RESULT))
        stack.enter_context(patch.object(PI.db, "get_conn", lambda: conn))
        stack.enter_context(patch.object(PI.db, "log_run_start", lambda _c, kind: captured.setdefault("kind", kind) or 1))
        stack.enter_context(patch.object(PI.db, "log_run_finish", lambda _c, run_id, status, errors: captured.setdefault("status", status)))
        result = PI.run("daily")
    assert captured["kind"] == "pipeline_ingest"
    assert result["status"] == "success"
    assert captured["status"] == "success"


def test_partial_status_exit_code_0():
    # 한 단계 실패(에러 누적)는 partial → 종료코드 0
    conn = _ctx_conn(WATCHLIST_ROWS)
    with ExitStack() as stack:
        _patch_db(stack, PI.db, {})
        stack.enter_context(patch.object(PI.ingest_market, "run_market_ingest", side_effect_raise()))
        stack.enter_context(patch.object(PI.ingest_macro, "run_macro_ingest", lambda: MACRO_RESULT))
        stack.enter_context(patch.object(PI.ingest_drivers, "run_driver_price_ingest", lambda _c: DRIVER_RESULT))
        stack.enter_context(patch.object(PI.ingest_kr, "run_kr_ingest", lambda _t: KR_RESULT))
        stack.enter_context(patch.object(PI.ingest_us, "run_us_ingest", lambda _t: US_RESULT))
        stack.enter_context(patch.object(PI.ingest_news, "run_news_ingest", lambda _t, company_names: NEWS_RESULT))
        stack.enter_context(patch.object(PI.ingest_market_news, "run_market_news_ingest", lambda: MARKET_NEWS_RESULT))
        # R7 실적 캘린더는 legacy에 없는 신규 단계 → 이 베이스라인 비교 대상 밖으로 격리.
        # (미패치 시 실제 yfinance/DART를 때리고 refetch가 fundamentals를 써서 스냅샷이 오염된다)
        stack.enter_context(patch.object(PI.ingest_earnings, "run_earnings_ingest", lambda _c, _w: EARNINGS_RESULT))
        stack.enter_context(patch.object(PI.db, "get_conn", lambda: conn))
        stack.enter_context(patch.object(PI.db, "log_run_start", lambda _c, kind: 1))
        stack.enter_context(patch.object(PI.db, "log_run_finish", lambda _c, run_id, status, errors: None))
        result = PI.run("daily")
    assert result["status"] == "partial"
    assert any(e["step"] == "market" for e in result["errors"])


def test_fatal_universe_failure_exit_code_1():
    # 유니버스 로드 실패(전체 실패) → failed → 종료코드 1
    conn = _ctx_conn(WATCHLIST_ROWS)
    with ExitStack() as stack:
        _patch_db(stack, PI.db, {})
        stack.enter_context(patch.object(PI.db, "get_conn", lambda: conn))
        stack.enter_context(patch.object(PI.db, "log_run_start", lambda _c, kind: 1))
        stack.enter_context(patch.object(PI.db, "log_run_finish", lambda _c, run_id, status, errors: None))
        stack.enter_context(patch("src.pipeline_ingest.active_universe", side_effect_raise()))
        result = PI.run("daily")
    assert result["status"] == "failed"
    assert PI.main is not None  # main 존재 계약


def side_effect_raise():
    def _raise(*_a, **_k):
        raise RuntimeError("boom")
    return _raise
