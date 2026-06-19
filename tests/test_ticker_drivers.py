from __future__ import annotations

from datetime import date

from src.export_dashboard_data import _build_driver_cards
from src.ingest_drivers import (
    DriverCandidate,
    _merge_driver_candidates,
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
        fetch_history=lambda symbol: [
            (date(2026, 6, 18), 100.0),
            (date(2026, 6, 19), 102.0),
        ],
    )

    assert len(rows) == 2
    assert all(row.driver_code == "SOXX" for row in rows)


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
