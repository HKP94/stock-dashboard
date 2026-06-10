"""
tests/test_recompute.py — recompute / 저장 경로 단위 테스트

네트워크·DB 없이 mock으로 검증:
  - recompute_indicators_to_db: prices→지표→upsert+commit, 부분 실패 격리
  - recompute_quant_to_db: 빈 결과는 upsert 안 함, 결과 있으면 commit
  - compute_quant 레짐 폴백: _fetch_market_history 실패 → neutral
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


# ──────────────────────────────────────────────────────────────
# compute_indicators.recompute_indicators_to_db
# ──────────────────────────────────────────────────────────────

class TestRecomputeIndicatorsToDb:
    def _conn_with_tickers(self, tickers):
        """DISTINCT ticker 쿼리에 응답하는 가짜 conn."""
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__.return_value = cur
        cur.__exit__.return_value = False
        cur.fetchall.return_value = [{"ticker": t} for t in tickers]
        conn.cursor.return_value = cur
        return conn

    def test_upsert_and_commit_per_ticker(self):
        import src.compute_indicators as ci
        conn = self._conn_with_tickers([])  # tickers 인자로 직접 전달하므로 무관
        df = pd.DataFrame({"close": [1.0], "volume": [1]})
        with patch("src.compute_indicators._load_price_df_from_db", return_value=df), \
             patch("src.compute_indicators.compute_indicators", return_value=["row1", "row2"]), \
             patch("src.db.upsert_indicators_daily") as up:
            n = ci.recompute_indicators_to_db(conn, tickers=["AAPL", "MSFT"])
        assert n == 2
        assert up.call_count == 2
        assert conn.commit.call_count == 2   # 종목별 commit

    def test_insufficient_data_skipped_no_commit(self):
        import src.compute_indicators as ci
        conn = MagicMock()
        with patch("src.compute_indicators._load_price_df_from_db", return_value=pd.DataFrame()), \
             patch("src.compute_indicators.compute_indicators", return_value=[]), \
             patch("src.db.upsert_indicators_daily") as up:
            n = ci.recompute_indicators_to_db(conn, tickers=["AAPL"])
        assert n == 0
        up.assert_not_called()
        conn.commit.assert_not_called()

    def test_failure_rolls_back_and_isolates(self):
        import src.compute_indicators as ci
        conn = MagicMock()
        df = pd.DataFrame({"close": [1.0]})

        def _compute(ticker, d):
            if ticker == "BAD":
                raise ValueError("계산 오류")
            return ["row"]

        with patch("src.compute_indicators._load_price_df_from_db", return_value=df), \
             patch("src.compute_indicators.compute_indicators", side_effect=_compute), \
             patch("src.db.upsert_indicators_daily"):
            n = ci.recompute_indicators_to_db(conn, tickers=["BAD", "GOOD"])
        assert n == 1                      # GOOD만 저장
        assert conn.rollback.call_count == 1   # BAD에서 롤백
        assert conn.commit.call_count == 1     # GOOD에서 커밋


# ──────────────────────────────────────────────────────────────
# recompute.recompute_quant_to_db
# ──────────────────────────────────────────────────────────────

class TestRecomputeQuantToDb:
    def test_empty_result_no_upsert(self):
        import src.recompute as rc
        conn = MagicMock()
        with patch("src.recompute.compute_quant_universe", return_value=[]), \
             patch("src.recompute.upsert_quant_scores") as up:
            n = rc.recompute_quant_to_db(conn, ["AAPL"])
        assert n == 0
        up.assert_not_called()
        conn.commit.assert_not_called()

    def test_results_upserted_and_committed(self):
        import src.recompute as rc
        conn = MagicMock()
        fake_rows = [MagicMock(composite=70.0), MagicMock(composite=None)]
        with patch("src.recompute.compute_quant_universe", return_value=fake_rows), \
             patch("src.recompute.upsert_quant_scores") as up:
            n = rc.recompute_quant_to_db(conn, ["AAPL", "MSFT"])
        assert n == 2
        up.assert_called_once()
        conn.commit.assert_called_once()


# ──────────────────────────────────────────────────────────────
# compute_quant 레짐 폴백
# ──────────────────────────────────────────────────────────────

class TestRegimeFallback:
    def test_market_history_failure_falls_back_to_neutral(self):
        """_fetch_market_history가 던져도 neutral로 진행, 크래시 없음."""
        import src.compute_quant as cq
        conn = MagicMock()

        with patch("src.compute_quant._fetch_market_history", side_effect=RuntimeError("yfinance 다운")), \
             patch("src.compute_quant._fetch_ticker_market", return_value="US"), \
             patch("src.compute_quant.piotroski_fscore", return_value=(5, [])), \
             patch("src.compute_quant._fetch_prices", return_value=pd.DataFrame(columns=["close", "volume"])), \
             patch("src.compute_quant._fetch_valuation_two", return_value=[]), \
             patch("src.compute_quant._fetch_fundamentals_annual", return_value=[]), \
             patch("src.compute_quant._fetch_analyst_records", return_value=(None, None)), \
             patch("src.compute_quant._fetch_sentiment_score", return_value=None):
            rows = cq.compute_quant_universe(["AAPL"], conn)
        # 폴백으로 정상 반환 (종목 1개)
        assert len(rows) == 1
        assert rows[0].ticker == "AAPL"
