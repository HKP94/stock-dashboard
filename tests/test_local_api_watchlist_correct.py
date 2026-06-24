"""
tests/test_local_api_watchlist_correct.py — 관심종목 티커/국가 오타 정정

정정 = 잘못된 종목 비활성 + 올바른 종목 추가(제거+추가, 단순 UPDATE 금지 — 데이터 정합성).
한 트랜잭션(commit/rollback), 입력 검증, 중복/미존재 처리, 메타 승계를 고정한다.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

import src.local_api as API
from src.local_api import WatchlistCorrectIn, correct_watchlist


class FakeCursor:
    def __init__(self, fetch_results):
        self._fetch = list(fetch_results)
        self.calls: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        self.calls.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self._fetch.pop(0) if self._fetch else None


class FakeConn:
    def __init__(self, fetch_results):
        self.cur = FakeCursor(fetch_results)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeBG:
    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *a, **k):
        self.tasks.append((fn, a, k))


def _patch_conn(monkeypatch, fetch_results):
    conn = FakeConn(fetch_results)
    monkeypatch.setattr(API, "get_conn", lambda: conn)
    return conn


def test_correct_inserts_new_and_deactivates_old(monkeypatch):
    # 새 티커가 아직 없을 때: 기존 비활성 + 신규 INSERT, 메타(종목명/섹터) 승계, 한 번 commit.
    conn = _patch_conn(monkeypatch, [{"name": "삼성전자", "sector": "반도체"}, None])
    bg = FakeBG()

    out = correct_watchlist("005935.KS", WatchlistCorrectIn(ticker="005930.KS", market="kr"), bg)

    sqls = [c[0] for c in conn.cur.calls]
    # 1) 잘못된 티커 비활성 (단순 UPDATE ticker 금지 — active=false로 제거)
    assert any("UPDATE watchlist SET active=false WHERE ticker=%s" in s for s in sqls)
    deact = next(c for c in conn.cur.calls if "SET active=false" in c[0])
    assert deact[1] == ("005935.KS",)
    # 2) 올바른 티커 INSERT (종목명·섹터 승계, market 대문자화)
    ins = next(c for c in conn.cur.calls if c[0].startswith("INSERT INTO watchlist"))
    assert ins[1] == ("005930.KS", "삼성전자", "KR", "반도체")
    assert conn.commits == 1 and conn.rollbacks == 0
    # 새 종목만 백그라운드 백필
    assert bg.tasks and bg.tasks[0][1] == ("005930.KS", "KR")
    assert out["old_ticker"] == "005935.KS" and out["ticker"] == "005930.KS"


def test_correct_reactivates_existing_inactive_ticker(monkeypatch):
    # 새 티커가 이미 (비활성) 존재하면 INSERT 대신 되살림 + 메타 갱신.
    conn = _patch_conn(monkeypatch, [{"name": "Apple", "sector": "기술"}, {"active": False}])
    out = correct_watchlist("APPL", WatchlistCorrectIn(ticker="AAPL", market="us"), FakeBG())

    assert any("SET active=false WHERE ticker=%s" in c[0] for c in conn.cur.calls)
    react = next(c for c in conn.cur.calls if "SET active=true" in c[0])
    assert react[1] == ("Apple", "US", "기술", "AAPL")
    assert not any(c[0].startswith("INSERT INTO watchlist") for c in conn.cur.calls)
    assert conn.commits == 1
    assert out["ticker"] == "AAPL"


def test_correct_rejects_duplicate_active_ticker(monkeypatch):
    conn = _patch_conn(monkeypatch, [{"name": "X", "sector": None}, {"active": True}])
    with pytest.raises(HTTPException) as ei:
        correct_watchlist("BADX", WatchlistCorrectIn(ticker="AAPL", market="us"), FakeBG())
    assert ei.value.status_code == 409
    assert conn.commits == 0  # 변경 없음


def test_correct_404_when_old_missing(monkeypatch):
    conn = _patch_conn(monkeypatch, [None])
    with pytest.raises(HTTPException) as ei:
        correct_watchlist("NOPE", WatchlistCorrectIn(ticker="AAPL", market="us"), FakeBG())
    assert ei.value.status_code == 404
    assert conn.commits == 0


def test_correct_rejects_same_ticker():
    with pytest.raises(HTTPException) as ei:
        correct_watchlist("AAPL", WatchlistCorrectIn(ticker="AAPL", market="us"), FakeBG())
    assert ei.value.status_code == 400


def test_correct_rejects_bad_market():
    with pytest.raises(HTTPException) as ei:
        correct_watchlist("AAPL", WatchlistCorrectIn(ticker="TSLA", market="JP"), FakeBG())
    assert ei.value.status_code == 400


@pytest.mark.parametrize("bad", ["", "   ", "00 5930"])
def test_correct_rejects_blank_or_whitespace_ticker(bad):
    with pytest.raises(HTTPException) as ei:
        correct_watchlist("OLD", WatchlistCorrectIn(ticker=bad, market="kr"), FakeBG())
    assert ei.value.status_code == 400


def test_correct_overrides_name_and_sector_when_provided(monkeypatch):
    conn = _patch_conn(monkeypatch, [{"name": "old name", "sector": "old"}, None])
    correct_watchlist(
        "OLD", WatchlistCorrectIn(ticker="NEW", market="us", name="새 이름", sector="새섹터"), FakeBG()
    )
    ins = next(c for c in conn.cur.calls if c[0].startswith("INSERT INTO watchlist"))
    assert ins[1] == ("NEW", "새 이름", "US", "새섹터")
