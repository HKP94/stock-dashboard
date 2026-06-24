"""
tests/test_ingest_speed_fixes.py — 06시 수집 timeout 근본 수정(P0/P1/P2) 검증

P0: dart-fss yaspin 스피너 비활성화 → SIGALRM이 _load 중 끊겨도 비-데몬 스레드 누수 없음.
P1: FnGuide connect 실패는 재시도하지 않고 빠르게 스킵(connect/read 분리 타임아웃).
P2: 뉴스 insert를 executemany 배치로(행위/카운트 보존).
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests

import src.db as DB
import src.ingest_kr as KR
import src.pipeline_ingest as PI
from src.external_timeout import ExternalCallTimeout


# ── P0: 스피너 비활성화 + 잔류 스레드 점검 ───────────────────────────────

@pytest.fixture
def _restore_spinner():
    import dart_fss.utils.spinner as sp
    prev = sp.Spinner.spinner_enable
    prev_flag = KR._dart_spinner_disabled
    yield
    sp.Spinner.spinner_enable = prev
    KR._dart_spinner_disabled = prev_flag


def test_disable_dart_spinner_turns_off_yaspin(_restore_spinner):
    import dart_fss.utils.spinner as sp
    sp.Spinner.spinner_enable = True
    KR._dart_spinner_disabled = False

    KR._disable_dart_spinner()

    assert sp.Spinner.spinner_enable is False  # 스레드가 아예 안 생김 → 누수 원천 차단


def test_fetch_fundamentals_disables_spinner_even_when_dart_times_out(monkeypatch, _restore_spinner):
    # DART 회사목록 타임아웃이 나도, 그 전에 스피너가 비활성화돼 비-데몬 스레드가 안 생긴다.
    import dart_fss.utils.spinner as sp
    sp.Spinner.spinner_enable = True
    KR._dart_spinner_disabled = False

    monkeypatch.setattr(KR, "_get_dart_api_key", lambda: "fake")
    monkeypatch.setattr("dart_fss.set_api_key", lambda **_k: None)
    monkeypatch.setattr(KR, "_get_corp_list_bounded", lambda _d: (_ for _ in ()).throw(ExternalCallTimeout("hang")))

    before = threading.active_count()
    with pytest.raises(ExternalCallTimeout):
        KR.fetch_kr_fundamentals("005930.KS")

    assert sp.Spinner.spinner_enable is False
    # 비-데몬 스레드가 새로 생기지 않았다
    assert threading.active_count() <= before


def test_residual_nondaemon_threads_detects_and_ignores_daemon():
    assert PI._residual_nondaemon_threads() == []

    stop = threading.Event()
    t = threading.Thread(target=stop.wait, name="leaky-nondaemon", daemon=False)
    t.start()
    try:
        assert "leaky-nondaemon" in PI._residual_nondaemon_threads()
    finally:
        stop.set()
        t.join()

    # 데몬 스레드는 종료를 막지 않으므로 목록에서 제외
    stop2 = threading.Event()
    d = threading.Thread(target=stop2.wait, name="daemon-ok", daemon=True)
    d.start()
    try:
        assert "daemon-ok" not in PI._residual_nondaemon_threads()
    finally:
        stop2.set()
        d.join()


# ── P1: FnGuide connect 실패 빠른 스킵 ───────────────────────────────────

def test_get_html_does_not_retry_on_connect_timeout(monkeypatch):
    calls = {"n": 0}

    def _connfail(*_a, **_k):
        calls["n"] += 1
        raise requests.exceptions.ConnectTimeout("connect blocked")

    monkeypatch.setattr(KR.requests, "get", _connfail)
    monkeypatch.setattr(KR._get_html.retry, "sleep", lambda *_a: None)

    with pytest.raises(requests.exceptions.ConnectTimeout):
        KR._get_html("https://comp.fnguide.com/x")

    assert calls["n"] == 1  # connect 실패는 재시도 없이 즉시 포기


def test_get_html_retries_on_read_timeout(monkeypatch):
    calls = {"n": 0}

    def _readfail(*_a, **_k):
        calls["n"] += 1
        raise requests.exceptions.ReadTimeout("slow read")

    monkeypatch.setattr(KR.requests, "get", _readfail)
    monkeypatch.setattr(KR._get_html.retry, "sleep", lambda *_a: None)

    with pytest.raises(requests.exceptions.ReadTimeout):
        KR._get_html("https://finance.naver.com/x")

    assert calls["n"] == 3  # read/일시 오류는 기존대로 3회 재시도


def test_get_html_uses_split_connect_read_timeout(monkeypatch):
    captured = {}

    def _ok(url, headers=None, timeout=None):
        captured["timeout"] = timeout
        return SimpleNamespace(content=b"<html>ok</html>", raise_for_status=lambda: None)

    monkeypatch.setattr(KR.requests, "get", _ok)

    assert KR._get_html("https://x") == b"<html>ok</html>"  # 정상 경로 불변
    assert captured["timeout"] == (KR.KR_WEB_CONNECT_TIMEOUT, KR.KR_WEB_READ_TIMEOUT)


# ── P2: 배치 insert 행위 보존 ────────────────────────────────────────────

class _FakeCur:
    def __init__(self, rowcount):
        self.rowcount = rowcount
        self.executemany_calls = []
        self.execute_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def executemany(self, sql, params):
        self.executemany_calls.append((sql, list(params)))

    def execute(self, *a, **k):
        self.execute_calls += 1


def _conn_with(cur):
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn


def test_insert_news_raw_batches_with_executemany():
    cur = _FakeCur(rowcount=2)
    conn = _conn_with(cur)
    rows = [
        SimpleNamespace(ticker="AAPL", source="rss", published_at=None, title="t1", body="b", url="u1", url_hash="h1"),
        SimpleNamespace(ticker="AAPL", source="rss", published_at=None, title="t2", body="b", url="u2", url_hash="h2"),
        SimpleNamespace(ticker="AAPL", source="rss", published_at=None, title="t3", body="b", url="u3", url_hash="h3"),
    ]
    n = DB.insert_news_raw(conn, rows)

    assert n == 2                       # cur.rowcount 누적 = 삽입 행 수 보존
    assert cur.execute_calls == 0       # per-row execute 안 씀
    assert len(cur.executemany_calls) == 1
    sql, params = cur.executemany_calls[0]
    assert "ON CONFLICT (url_hash) DO NOTHING" in sql
    assert len(params) == 3             # 모든 행이 한 배치로
    assert params[0][-1] == "h1"        # url_hash 마지막 컬럼 보존


def test_insert_market_news_batches_with_executemany():
    cur = _FakeCur(rowcount=1)
    conn = _conn_with(cur)
    rows = [
        SimpleNamespace(source="mw", title="m1", url="u1", url_hash="mh1", published_at=None),
        SimpleNamespace(source="mw", title="m2", url="u2", url_hash="mh2", published_at=None),
    ]
    n = DB.insert_market_news(conn, rows)

    assert n == 1
    assert cur.execute_calls == 0
    assert len(cur.executemany_calls) == 1
    assert "ON CONFLICT (url_hash) DO NOTHING" in cur.executemany_calls[0][0]
    assert len(cur.executemany_calls[0][1]) == 2


def test_insert_empty_returns_zero_without_db():
    conn = MagicMock()
    assert DB.insert_news_raw(conn, []) == 0
    assert DB.insert_market_news(conn, []) == 0
    conn.cursor.assert_not_called()


def test_insert_news_raw_negative_rowcount_guarded():
    # rowcount가 -1(미결정)이면 0으로 방어(음수 카운트 방지)
    cur = _FakeCur(rowcount=-1)
    rows = [SimpleNamespace(ticker="AAPL", source="rss", published_at=None, title="t", body="b", url="u", url_hash="h")]
    assert DB.insert_news_raw(_conn_with(cur), rows) == 0
