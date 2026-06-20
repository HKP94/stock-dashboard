from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.export_dashboard_data import _group_analyst_consensus_history_rows


def test_group_analyst_consensus_history_rows_sorts_oldest_to_latest_per_ticker() -> None:
    rows = [
        {
            "ticker": "AAPL",
            "asof": "2026-06-20",
            "target_price": 220.0,
            "rating_label": "매수",
            "rating_score": 1.0,
            "eps_fwd": 8.21,
            "n_analysts": 31,
            "source": "yfinance",
        },
        {
            "ticker": "AAPL",
            "asof": "2026-05-20",
            "target_price": 205.0,
            "rating_label": "매수",
            "rating_score": 1.0,
            "eps_fwd": 7.95,
            "n_analysts": 29,
            "source": "yfinance",
        },
    ]

    grouped = _group_analyst_consensus_history_rows(rows)

    assert [item["asof"] for item in grouped["AAPL"]] == ["2026-05-20", "2026-06-20"]
    assert grouped["AAPL"][1]["targetPrice"] == 220.0
    assert grouped["AAPL"][1]["nAnalysts"] == 31


def test_group_analyst_consensus_history_rows_preserves_empty_numeric_fields() -> None:
    rows = [
        {
            "ticker": "005930.KS",
            "asof": "2026-06-20",
            "target_price": None,
            "rating_label": "중립",
            "rating_score": 0.0,
            "eps_fwd": None,
            "n_analysts": None,
            "source": "naver",
        },
    ]

    grouped = _group_analyst_consensus_history_rows(rows)

    assert grouped["005930.KS"] == [{
        "asof": "2026-06-20",
        "targetPrice": None,
        "ratingLabel": "중립",
        "ratingScore": 0.0,
        "epsFwd": None,
        "nAnalysts": None,
        "source": "naver",
    }]
