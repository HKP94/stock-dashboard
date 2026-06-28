"""
tests/test_local_api_delete_note.py — 내 판단 삭제 엔드포인트 단위 테스트

FastAPI TestClient + 인메모리 mock DB 사용. 네트워크·실DB 의존 없음.
검증:
  1. DELETE /api/notes/{ticker} 응답 200
  2. stock_notes 행 삭제 + stock_note_history active=FALSE 처리
  3. 이미 없는 종목도 에러 없이 200
  4. _fetch_note_history 가 active=TRUE 행만 반환
  5. _patch_data_json_note(ticker, None) 호출 — data.json note=None, noteHistory=[]
  6. CORS DELETE 허용 확인
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest


# ── 헬퍼: DB cursor mock 빌더 ─────────────────────────────────────────

def _make_cursor(rows: list[dict] | None = None):
    cur = MagicMock()
    cur.fetchone.return_value = rows[0] if rows else None
    cur.fetchall.return_value = rows or []
    cur.__iter__ = lambda self: iter(self.fetchall())
    return cur


def _make_conn(cursor):
    conn = MagicMock()
    conn.cursor.return_value = cursor
    conn.__enter__ = lambda s: s
    conn.__exit__ = MagicMock(return_value=False)
    return conn


# ── DELETE 엔드포인트 ──────────────────────────────────────────────────

def test_delete_note_returns_ok():
    """DELETE /api/notes/{ticker} → 200 {"ok": True}."""
    from fastapi.testclient import TestClient
    from src.local_api import app

    cur = _make_cursor()
    conn = _make_conn(cur)

    with patch("src.local_api.get_conn") as mock_gc, \
         patch("src.local_api._patch_data_json_note"):
        mock_gc.return_value.__enter__ = lambda s: conn
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        client = TestClient(app)
        res = client.delete("/api/notes/005930")

    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert res.json()["ticker"] == "005930"


def test_delete_note_executes_correct_sql():
    """DELETE 실행 시 stock_notes DELETE + history UPDATE active=FALSE."""
    from fastapi.testclient import TestClient
    from src.local_api import app

    cur = _make_cursor()
    conn = _make_conn(cur)

    with patch("src.local_api.get_conn") as mock_gc, \
         patch("src.local_api._patch_data_json_note"):
        mock_gc.return_value.__enter__ = lambda s: conn
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        client = TestClient(app)
        client.delete("/api/notes/AAPL")

    calls = [str(c.args[0]).strip() for c in cur.execute.call_args_list]
    assert any("DELETE FROM stock_notes" in s for s in calls), f"DELETE missing in {calls}"
    assert any("UPDATE stock_note_history" in s and "active=FALSE" in s for s in calls), \
        f"active=FALSE update missing in {calls}"


def test_delete_note_commits_or_rollbacks():
    """정상 흐름에서 commit이 호출된다."""
    from fastapi.testclient import TestClient
    from src.local_api import app

    cur = _make_cursor()
    conn = _make_conn(cur)

    with patch("src.local_api.get_conn") as mock_gc, \
         patch("src.local_api._patch_data_json_note"):
        mock_gc.return_value.__enter__ = lambda s: conn
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        client = TestClient(app)
        client.delete("/api/notes/TSLA")

    conn.commit.assert_called_once()


def test_delete_note_calls_patch_with_none():
    """_patch_data_json_note(ticker, None) 로 data.json 클리어."""
    from fastapi.testclient import TestClient
    from src.local_api import app

    cur = _make_cursor()
    conn = _make_conn(cur)

    with patch("src.local_api.get_conn") as mock_gc, \
         patch("src.local_api._patch_data_json_note") as mock_patch:
        mock_gc.return_value.__enter__ = lambda s: conn
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        client = TestClient(app)
        client.delete("/api/notes/META")

    mock_patch.assert_called_once_with("META", None)


def test_delete_note_nonexistent_ticker_no_error():
    """존재하지 않는 종목도 200 (DELETE/UPDATE 0 rows는 에러 아님)."""
    from fastapi.testclient import TestClient
    from src.local_api import app

    cur = _make_cursor()
    conn = _make_conn(cur)

    with patch("src.local_api.get_conn") as mock_gc, \
         patch("src.local_api._patch_data_json_note"):
        mock_gc.return_value.__enter__ = lambda s: conn
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        client = TestClient(app)
        res = client.delete("/api/notes/NONEXISTENT")

    assert res.status_code == 200


# ── _fetch_note_history active=TRUE 필터 ─────────────────────────────

def test_fetch_note_history_filters_active():
    """_fetch_note_history SQL에 active=TRUE 조건이 포함된다."""
    from src.local_api import _fetch_note_history

    cur = _make_cursor([])
    conn = _make_conn(cur)

    with patch("src.local_api.get_conn") as mock_gc:
        mock_gc.return_value.__enter__ = lambda s: conn
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        _fetch_note_history("005930")

    sql = cur.execute.call_args[0][0]
    assert "active=TRUE" in sql or "active = TRUE" in sql.upper(), \
        f"active filter missing in: {sql}"


# ── _patch_data_json_note None 처리 ──────────────────────────────────

def test_patch_data_json_note_none_clears_note():
    """note_data=None 이면 data.json의 note=None, noteHistory=[] 로 기록."""
    from src.local_api import _patch_data_json_note

    stock = {"t": "AAPL", "note": {"horizon": "long", "attractiveness": 4, "thesis": "좋음"}, "noteHistory": [{"id": 1}]}
    data = {"stocks": [stock]}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(data, f)
        tmp_path = Path(f.name)

    with patch("src.local_api._DATA_JSON", tmp_path), \
         patch("src.local_api._fetch_note_history", return_value=[]):
        _patch_data_json_note("AAPL", None)

    result = json.loads(tmp_path.read_text(encoding="utf-8"))
    assert result["stocks"][0]["note"] is None
    assert result["stocks"][0]["noteHistory"] == []
    tmp_path.unlink()


def test_patch_data_json_note_with_data_sets_history():
    """note_data가 있으면 _fetch_note_history 결과로 noteHistory 갱신."""
    from src.local_api import _patch_data_json_note

    stock = {"t": "AAPL", "note": None, "noteHistory": []}
    data = {"stocks": [stock]}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(data, f)
        tmp_path = Path(f.name)

    fake_hist = [{"id": 5, "thesis": "테스트"}]
    note_data = {"horizon": "long", "attractiveness": 5, "thesis": "최고"}

    with patch("src.local_api._DATA_JSON", tmp_path), \
         patch("src.local_api._fetch_note_history", return_value=fake_hist):
        _patch_data_json_note("AAPL", note_data)

    result = json.loads(tmp_path.read_text(encoding="utf-8"))
    assert result["stocks"][0]["note"] == note_data
    assert result["stocks"][0]["noteHistory"] == fake_hist
    tmp_path.unlink()


# ── CORS DELETE 허용 ──────────────────────────────────────────────────

def test_cors_allows_delete():
    """CORS allow_methods에 DELETE가 포함돼야 함 (브라우저 프리플라이트 차단 방지)."""
    from src.local_api import app
    for mw in app.user_middleware:
        if mw.cls.__name__ == "CORSMiddleware":
            opts = getattr(mw, "kwargs", None) or getattr(mw, "options", None) or {}
            methods = opts.get("allow_methods", [])
            assert "DELETE" in methods, f"DELETE must be in CORS allow_methods, got {methods}"
            return
    raise AssertionError("CORSMiddleware not found")
