from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.local_api import WatchlistPatch


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


def test_watchlist_patch_requires_at_least_one_field() -> None:
    with pytest.raises(ValidationError):
        WatchlistPatch()


def test_sector_only_patch_normalizes_empty_to_none() -> None:
    from src.local_api import _patch_watchlist_row

    conn = FakeConnection()
    result = _patch_watchlist_row(conn, "AAPL", WatchlistPatch(sector="  "))

    assert conn.cur.calls[-1][1] == (None, "AAPL")
    assert result == {"active": None, "sector": None}
    assert conn.commits == 1


def test_active_and_sector_patch_updates_both() -> None:
    from src.local_api import _patch_watchlist_row

    conn = FakeConnection()
    result = _patch_watchlist_row(conn, "AAPL", WatchlistPatch(active=False, sector="기술"))

    assert conn.cur.calls[-1][1] == (False, "기술", "AAPL")
    assert result == {"active": False, "sector": "기술"}
