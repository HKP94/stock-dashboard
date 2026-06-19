from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from src.local_api import NoteIn


class FakeCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params: tuple) -> None:
        self.calls.append((" ".join(sql.split()), params))


class FakeConnection:
    def __init__(self) -> None:
        self.cur = FakeCursor()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self) -> FakeCursor:
        return self.cur

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_schema_contains_append_only_note_history() -> None:
    schema = Path("db/schema.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS stock_note_history" in schema
    assert "created_at" in schema


def test_append_note_inserts_history_and_updates_latest_once() -> None:
    from src.local_api import _append_note

    conn = FakeConnection()
    _append_note(conn, "AAPL", NoteIn(horizon="long", attractiveness=4, thesis="현금흐름 개선"))

    sql = [call[0] for call in conn.cur.calls]
    assert "INSERT INTO stock_note_history" in sql[0]
    assert "INSERT INTO stock_notes" in sql[1]
    assert conn.commits == 1
    assert conn.rollbacks == 0


def test_append_note_rejects_blank_thesis() -> None:
    from src.local_api import _append_note

    with pytest.raises(HTTPException) as error:
        _append_note(FakeConnection(), "AAPL", NoteIn(thesis="  "))
    assert error.value.status_code == 400


def test_export_note_history_is_grouped_newest_first() -> None:
    from src.export_dashboard_data import _group_note_history

    rows = [
        {"id": 2, "ticker": "AAPL", "horizon": "long", "attractiveness": 4, "thesis": "둘", "created_at": "2026-06-19T02:00:00"},
        {"id": 1, "ticker": "AAPL", "horizon": "watch", "attractiveness": 3, "thesis": "하나", "created_at": "2026-06-19T01:00:00"},
    ]
    grouped = _group_note_history(rows)
    assert [item["id"] for item in grouped["AAPL"]] == [2, 1]
