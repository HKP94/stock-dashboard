from __future__ import annotations

from datetime import date
from src.export_dashboard_data import _build_driver_cards
from src.external_timeout import ExternalCallTimeout
from src.ingest_drivers import (
    DriverCandidate,
    _fallback_driver_candidates,
    _merge_driver_candidates,
    _suggest_driver_candidates,
    auto_map_active_watchlist_drivers,
    collect_driver_price_rows,
)


def test_merge_driver_candidates_keeps_user_origin_rows() -> None:
    existing = [
        {
            "ticker": "AAPL",
            "driver_code": "WTI",
            "driver_name": "유가",
            "driver_source": "shared_macro",
            "weight": 5,
            "origin": "user",
            "rationale": "직접 지정",
        }
    ]
    suggested = [
        DriverCandidate(
            ticker="AAPL",
            driver_code="WTI",
            driver_name="유가",
            driver_source="shared_macro",
            weight=2,
            origin="auto",
            rationale="자동 추정",
        ),
        DriverCandidate(
            ticker="AAPL",
            driver_code="SOXX",
            driver_name="반도체 ETF",
            driver_source="yfinance_proxy",
            weight=3,
            origin="auto",
            rationale="AI 반도체 수요 프록시",
        ),
    ]

    merged = _merge_driver_candidates(existing, suggested)

    codes = {row.driver_code: row for row in merged}
    assert codes["WTI"].origin == "user"
    assert codes["WTI"].weight == 5
    assert codes["SOXX"].origin == "auto"


def test_collect_driver_price_rows_skips_shared_macro_codes() -> None:
    rows = collect_driver_price_rows(
        [
            {"driver_code": "WTI", "driver_name": "유가", "driver_source": "shared_macro"},
            {"driver_code": "SOXX", "driver_name": "반도체 ETF", "driver_source": "yfinance_proxy"},
        ],
        fetch_history=lambda symbol, period: [
            (date(2026, 6, 18), 100.0),
            (date(2026, 6, 19), 102.0),
        ],
    )

    assert len(rows) == 2
    assert all(row.driver_code == "SOXX" for row in rows)


def test_collect_driver_price_rows_requests_five_year_history_once_per_proxy_code() -> None:
    calls: list[tuple[str, str]] = []

    def fake_fetch(symbol: str, period: str) -> list[tuple[date, float]]:
        calls.append((symbol, period))
        return [(date(2026, 6, 19), 1.0)]

    rows = collect_driver_price_rows(
        [
            {"driver_code": "SOXX", "driver_name": "반도체 ETF", "driver_source": "yfinance_proxy"},
            {"driver_code": "SOXX", "driver_name": "반도체 ETF", "driver_source": "yfinance_proxy"},
            {"driver_code": "LIT", "driver_name": "리튬 ETF", "driver_source": "yfinance_proxy"},
        ],
        fetch_history=fake_fetch,
    )

    assert {(row.driver_code, row.asof) for row in rows} == {
        ("SOXX", date(2026, 6, 19)),
        ("LIT", date(2026, 6, 19)),
    }
    assert calls == [("SOXX", "5y"), ("LIT", "5y")]


def test_fallback_driver_candidates_map_alb_to_lit() -> None:
    rows = _fallback_driver_candidates("ALB", "Albemarle", "Specialty Chemicals", "US")
    assert "LIT" in {row.driver_code for row in rows}


def test_suggest_driver_candidates_falls_back_on_timeout(monkeypatch) -> None:
    from src import ingest_drivers

    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setattr(ingest_drivers, "_get_gemini_client", lambda: object())
    monkeypatch.setattr(
        ingest_drivers,
        "_call_gemini_with_backoff",
        lambda *args, **kwargs: (_ for _ in ()).throw(ExternalCallTimeout("timed out")),
    )

    rows = _suggest_driver_candidates("ALB", "Albemarle", "Specialty Chemicals", "US")

    assert "LIT" in {row.driver_code for row in rows}


class _Cursor:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.sql: list[tuple[str, tuple | None]] = []

    def execute(self, sql: str, params: tuple | None = None) -> None:
        self.sql.append((" ".join(sql.split()), params))

    def fetchall(self) -> list[dict]:
        return self.rows

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class _Conn:
    def __init__(self, rows: list[dict]) -> None:
        self.cur = _Cursor(rows)

    def cursor(self) -> _Cursor:
        return self.cur


def test_auto_map_active_watchlist_drivers_isolates_per_ticker_failures() -> None:
    conn = _Conn(
        [
            {"ticker": "005930.KS", "name": "삼성전자", "sector": "반도체", "market": "KR"},
            {"ticker": "ALB", "name": "Albemarle", "sector": "Specialty Chemicals", "market": "US"},
        ]
    )
    calls: list[str] = []

    def fake_mapper(conn, ticker: str, *, name: str, sector: str, market: str):
        calls.append(ticker)
        if ticker == "ALB":
            raise RuntimeError("gemini timeout")
        return [DriverCandidate(ticker, "SOXX", "반도체 ETF", "yfinance_proxy", 5, "auto", "ok")]

    result = auto_map_active_watchlist_drivers(conn, mapper=fake_mapper)

    assert calls == ["005930.KS", "ALB"]
    assert result["mapped_tickers"] == ["005930.KS"]
    assert result["failed_tickers"] == ["ALB"]
    assert len(result["errors"]) == 1
    assert "WHERE active = TRUE" in conn.cur.sql[0][0]


def test_build_driver_cards_prefers_latest_per_driver_and_support_oppose_tone() -> None:
    driver_rows = [
        {
            "ticker": "005930.KS",
            "driver_code": "SOXX",
            "driver_name": "반도체 ETF",
            "driver_source": "yfinance_proxy",
            "weight": 5,
            "origin": "auto",
            "rationale": "메모리 업황의 상장 프록시",
        },
        {
            "ticker": "005930.KS",
            "driver_code": "WTI",
            "driver_name": "유가",
            "driver_source": "shared_macro",
            "weight": 2,
            "origin": "user",
            "rationale": "물류·원가 보조 지표",
        },
    ]
    price_rows = {
        "SOXX": [
            {"asof": date(2026, 6, 18), "close": 200.0},
            {"asof": date(2026, 6, 19), "close": 210.0},
        ],
        "WTI": [
            {"asof": date(2026, 5, 20), "close": 80.0},
            {"asof": date(2026, 6, 19), "close": 70.0},
        ],
    }

    cards = _build_driver_cards(driver_rows, price_rows)

    assert cards[0]["code"] == "SOXX"
    assert cards[0]["origin"] == "auto"
    assert cards[0]["badge"] == "추정"
    assert cards[0]["implication"]["tone"] == "support"
    assert cards[1]["origin"] == "user"
    assert cards[1]["implication"]["tone"] == "oppose"
