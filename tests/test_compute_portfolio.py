from __future__ import annotations

from datetime import date
from decimal import Decimal

from src import compute_portfolio as module


class FakeCursor:
    def __init__(self, conn: "FakeConnection") -> None:
        self.conn = conn
        self.rows: list[dict] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple | None = None) -> None:
        normalized = " ".join(sql.split())
        self.conn.executed.append((normalized, params))
        if "FROM portfolio_holdings" in normalized:
            self.rows = list(self.conn.holdings)
        elif "FROM portfolio_cash" in normalized:
            self.rows = list(self.conn.cash)
        elif "FROM market_daily" in normalized:
            self.rows = [{"usdkrw": Decimal("1400")}]
        elif "FROM prices_daily" in normalized:
            ticker = params[0] if params else ""
            self.rows = [{"close": self.conn.prices[ticker]}]
        else:
            self.rows = []

    def fetchone(self) -> dict | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[dict]:
        return list(self.rows)


class FakeConnection:
    def __init__(self) -> None:
        self.holdings = [
            {"ticker": "AAPL", "qty": Decimal("2"), "avg_price": Decimal("100"), "currency": "USD"},
            {"ticker": "005930.KS", "qty": Decimal("1"), "avg_price": Decimal("70000"), "currency": "KRW"},
        ]
        self.cash = [
            {"currency": "USD", "amount": Decimal("10")},
            {"currency": "KRW", "amount": Decimal("1000")},
        ]
        self.prices = {"AAPL": Decimal("120"), "005930.KS": Decimal("75000")}
        self.executed: list[tuple[str, tuple | None]] = []
        self.commit_count = 0

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.commit_count += 1


def test_compute_portfolio_returns_canonical_asset_total() -> None:
    conn = FakeConnection()

    result = module.compute_portfolio(conn, date(2026, 6, 19))

    assert result["total_eval_krw"] == 411_000.0
    assert result["cash_total_krw"] == 15_000.0
    assert result["asset_total_krw"] == 426_000.0
    assert conn.commit_count == 1


def test_compute_portfolio_queries_latest_price_per_ticker() -> None:
    conn = FakeConnection()

    module.compute_portfolio(conn, date(2026, 6, 19))

    price_params = [params for sql, params in conn.executed if "FROM prices_daily" in sql]
    assert price_params == [("AAPL",), ("005930.KS",)]
    assert all("ORDER BY date DESC LIMIT 1" in sql for sql, _ in conn.executed if "FROM prices_daily" in sql)
