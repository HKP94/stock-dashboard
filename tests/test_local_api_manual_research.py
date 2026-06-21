from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.local_api import ManualResearchPatch


class FakeCursor:
    rowcount = 1

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


def test_manual_research_patch_requires_any_supported_field() -> None:
    with pytest.raises(ValidationError):
        ManualResearchPatch()


def test_manual_research_patch_raw_text_marks_redecomposition_path() -> None:
    from src.local_api import _patch_manual_research_entry

    conn = FakeConnection()
    result = _patch_manual_research_entry(conn, 7, ManualResearchPatch(raw_text="  새 원문  ", source="메리츠"))

    assert conn.commits == 1
    assert result["needs_redecomposition"] is True
    assert conn.cur.calls[-1][1] == ("새 원문", "메리츠", 7)
