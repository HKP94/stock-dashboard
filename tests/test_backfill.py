"""
tests/test_backfill.py — backfill 단위 테스트

네트워크·DB 없이 수집/upsert/지표 함수를 mock해서
라우팅(KR/US)·격리(try/except)·집계 로직만 검증.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.backfill import (
    _is_kr,
    backfill_prices,
    recompute_indicators,
)

CONN = MagicMock()

_TICKERS = [
    {"ticker": "AAPL", "market": "US"},
    {"ticker": "005930.KS", "market": "KR"},
]


# ──────────────────────────────────────────────────────────────
# _is_kr 라우팅
# ──────────────────────────────────────────────────────────────

class TestIsKr:
    def test_market_kr(self):
        assert _is_kr("005930.KS", "KR") is True

    def test_market_us(self):
        assert _is_kr("AAPL", "US") is False

    def test_suffix_fallback_ks(self):
        assert _is_kr("005930.KS", None) is True

    def test_suffix_fallback_us(self):
        assert _is_kr("AAPL", None) is False

    def test_market_overrides_suffix(self):
        # market 명시되면 우선
        assert _is_kr("AAPL", "KR") is True


# ──────────────────────────────────────────────────────────────
# backfill_prices: 라우팅 + 격리
# ──────────────────────────────────────────────────────────────

class TestBackfillPrices:
    def test_routes_kr_and_us(self):
        errors: list = []
        with patch("src.backfill.fetch_us_prices", return_value=["us_row"]) as us, \
             patch("src.backfill.fetch_kr_prices", return_value=["kr_row"]) as kr, \
             patch("src.backfill.upsert_price_daily") as up, \
             patch("time.sleep"):
            ok = backfill_prices(CONN, _TICKERS, errors)
        assert ok == 2
        us.assert_called_once_with("AAPL")
        kr.assert_called_once_with("005930.KS")
        assert up.call_count == 2
        assert errors == []

    def test_empty_rows_not_upserted(self):
        errors: list = []
        with patch("src.backfill.fetch_us_prices", return_value=[]), \
             patch("src.backfill.fetch_kr_prices", return_value=[]), \
             patch("src.backfill.upsert_price_daily") as up, \
             patch("time.sleep"):
            ok = backfill_prices(CONN, _TICKERS, errors)
        assert ok == 0
        up.assert_not_called()
        assert errors == []

    def test_one_ticker_failure_isolated(self):
        errors: list = []

        def _us_fails(ticker):
            raise RuntimeError("yfinance 다운")

        with patch("src.backfill.fetch_us_prices", side_effect=_us_fails), \
             patch("src.backfill.fetch_kr_prices", return_value=["kr_row"]), \
             patch("src.backfill.upsert_price_daily"), \
             patch("time.sleep"):
            ok = backfill_prices(CONN, _TICKERS, errors)
        # AAPL 실패, 삼성전자 성공
        assert ok == 1
        assert len(errors) == 1
        assert errors[0]["ticker"] == "AAPL"
        assert errors[0]["step"] == "backfill_price"

    def test_sleep_called_per_ticker(self):
        errors: list = []
        with patch("src.backfill.fetch_us_prices", return_value=["r"]), \
             patch("src.backfill.fetch_kr_prices", return_value=["r"]), \
             patch("src.backfill.upsert_price_daily"), \
             patch("time.sleep") as slp:
            backfill_prices(CONN, _TICKERS, errors)
        assert slp.call_count == 2  # 종목당 1회


# ──────────────────────────────────────────────────────────────
# recompute_indicators
# ──────────────────────────────────────────────────────────────

class TestRecomputeIndicators:
    def test_computes_and_upserts(self):
        errors: list = []
        fake_df = pd.DataFrame({"close": [1.0], "volume": [1]})
        with patch("src.backfill._load_price_df", return_value=fake_df), \
             patch("src.backfill.compute_indicators", return_value=["ind_row"]), \
             patch("src.backfill.upsert_indicators_daily") as up:
            ok = recompute_indicators(CONN, _TICKERS, errors)
        assert ok == 2
        assert up.call_count == 2
        assert errors == []

    def test_insufficient_data_skipped(self):
        errors: list = []
        with patch("src.backfill._load_price_df", return_value=pd.DataFrame()), \
             patch("src.backfill.compute_indicators", return_value=[]), \
             patch("src.backfill.upsert_indicators_daily") as up:
            ok = recompute_indicators(CONN, _TICKERS, errors)
        assert ok == 0
        up.assert_not_called()
        assert errors == []  # 데이터 부족은 에러 아님

    def test_failure_isolated(self):
        errors: list = []

        def _compute_fails(ticker, df):
            if ticker == "AAPL":
                raise ValueError("계산 오류")
            return ["ind_row"]

        with patch("src.backfill._load_price_df", return_value=pd.DataFrame({"close": [1.0]})), \
             patch("src.backfill.compute_indicators", side_effect=_compute_fails), \
             patch("src.backfill.upsert_indicators_daily"):
            ok = recompute_indicators(CONN, _TICKERS, errors)
        assert ok == 1
        assert len(errors) == 1
        assert errors[0]["ticker"] == "AAPL"
        assert errors[0]["step"] == "recompute_indicators"
