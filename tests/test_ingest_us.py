from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from src.ingest_us import fetch_us_analyst


class TestFetchUsAnalyst:
    def test_normalizes_buy_consensus_and_source_fields(self):
        info = {
            "currentPrice": 100.0,
            "targetMeanPrice": 130.0,
            "recommendationKey": "buy",
            "numberOfAnalystOpinions": 18,
            "forwardEps": 6.25,
        }
        with patch("src.ingest_us._yf_info", return_value=info):
            row = fetch_us_analyst("AAPL", asof=date(2026, 6, 20))

        assert row is not None
        assert row.rating_label == "매수"
        assert row.rating_score == 1.0
        assert row.target_price == 130.0
        assert row.eps_fwd == 6.25
        assert row.source == "yfinance"
        assert row.upside == pytest.approx(0.30)
        assert row.n_analysts == 18

    def test_normalizes_hold_to_neutral(self):
        info = {
            "currentPrice": 200.0,
            "targetMeanPrice": 210.0,
            "recommendationKey": "hold",
            "numberOfAnalystOpinions": 9,
        }
        with patch("src.ingest_us._yf_info", return_value=info):
            row = fetch_us_analyst("MSFT", asof=date(2026, 6, 20))

        assert row is not None
        assert row.rating_label == "중립"
        assert row.rating_score == 0.0
        assert row.source == "yfinance"

