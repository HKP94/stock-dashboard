from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.local_api import DriverIn, DriverPatch


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


def test_driver_patch_requires_at_least_one_change() -> None:
    with pytest.raises(ValidationError):
        DriverPatch()


def test_driver_in_marks_user_origin() -> None:
    body = DriverIn(ticker="AAPL", driver_code="SOXX", driver_name="반도체 ETF", driver_source="yfinance_proxy", weight=4)
    assert body.origin == "user"


def test_patch_driver_row_updates_weight_and_rationale() -> None:
    from src.local_api import _patch_driver_row

    conn = FakeConnection()
    result = _patch_driver_row(conn, "AAPL", "SOXX", DriverPatch(weight=5, rationale="직접 수정"))

    assert conn.commits == 1
    assert result == {"weight": 5, "rationale": "직접 수정"}
    assert conn.cur.calls[-1][1] == (5, "직접 수정", "AAPL", "SOXX")
