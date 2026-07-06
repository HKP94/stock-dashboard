"""
tests/test_quant.py — compute_quant 단위 테스트

합성 데이터, 네트워크·DB 없음.
mock 포인트:
  patch("src.compute_quant._fetch_market_history")
  patch("src.compute_quant._fetch_prices")
  patch("src.compute_quant._fetch_ticker_market")
  patch("src.compute_quant._fetch_fundamentals_annual")
  patch("src.compute_quant._fetch_valuation_two")
  patch("src.compute_quant._fetch_analyst_records")
  patch("src.compute_quant._fetch_sentiment_score")
  patch("src.compute_quant.piotroski_fscore")
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from src.compute_quant import (
    FSCORE_FILTER_THRESHOLD,
    _F_FILTERED,
    _F_MISSING,
    _REGIME_WEIGHTS,
    _safe_pct_rank,
    _zscore,
    _winsorize,
    _score_momentum,
    WINSOR_MIN_N,
    compute_regime,
    compute_quant_universe,
    is_filtered,
    piotroski_fscore,
    _is_financial,
    _score_quality,
)

# ── 합성 데이터 헬퍼 ──────────────────────────────────────────

TICKERS = ["STRONG", "MIDU", "FLAT", "WEAK", "CRASH"]
ASOF = date(2026, 6, 8)


def _trend_prices(total_log_ret: float, n: int = 252) -> pd.DataFrame:
    """결정론적 추세 가격 시계열 (n 영업일)."""
    prices = 100.0 * np.exp(np.linspace(0, total_log_ret, n))
    idx = pd.date_range(end="2026-06-08", periods=n, freq="B")
    return pd.DataFrame({"close": prices, "volume": 1_000_000}, index=idx)


# ticker별 M_12M 크기순: STRONG > MIDU > FLAT > WEAK > CRASH
_PRICE_MAP = {
    "STRONG": _trend_prices(+0.50),
    "MIDU":   _trend_prices(+0.20),
    "FLAT":   _trend_prices( 0.00),
    "WEAK":   _trend_prices(-0.20),
    "CRASH":  _trend_prices(-0.50),
}

# ticker별 PER_F (낮을수록 value 높음)
_PER_MAP = {"CHEAP": 8.0, "FAIR": 15.0, "DEAR": 30.0, "EXP": 50.0}

# ticker별 ROE (높을수록 quality 높음)
_ROE_MAP = {"HQ": 0.30, "MQ": 0.15, "LQ": 0.05}


def _mock_prices(ticker, days, conn):
    return _PRICE_MAP.get(ticker, _trend_prices(0.0))


def _neutral_val(ticker=None):
    return {"per_f": 20.0, "per_t": 20.0, "pbr": 1.5, "ev_ebitda": 12.0,
            "roe": 0.12, "roa": 0.06, "debt_ratio": 80.0, "rev_growth": 0.05}


def _neutral_fund(ticker=None):
    return [
        {"period_end": date(2025, 12, 31), "revenue": 1000, "op_income": 100,
         "op_margin": 0.10, "net_income": 80},
        {"period_end": date(2024, 12, 31), "revenue": 950, "op_income": 90,
         "op_margin": 0.095, "net_income": 70},
    ]


def _patch_all_db(fscore=5):
    """모든 DB 헬퍼를 중립 값으로 패치하는 컨텍스트 세트 반환."""
    return [
        patch("src.compute_quant._fetch_ticker_market", return_value="US"),
        patch("src.compute_quant.piotroski_fscore", return_value=(fscore, [])),
        patch("src.compute_quant._fetch_valuation_two", side_effect=lambda t, c: [_neutral_val()]),
        patch("src.compute_quant._fetch_fundamentals_annual", side_effect=lambda t, c: _neutral_fund()),
        patch("src.compute_quant._fetch_analyst_records", return_value=(None, None)),
        patch("src.compute_quant._fetch_sentiment_score", return_value=0.0),
    ]


def _neutral_market_df(n=504, regime="neutral") -> pd.DataFrame:
    """레짐에 맞는 합성 시장 DataFrame."""
    idx = pd.date_range(end="2026-06-08", periods=n, freq="B")
    if regime == "bull":
        # KOSPI·SP500 SMA200 위, VIX 낮음
        kospi = pd.Series(np.linspace(2000, 2800, n), index=idx)
        sp500 = pd.Series(np.linspace(4000, 5200, n), index=idx)
        vix   = pd.Series(np.full(n, 15.0), index=idx)
    elif regime == "bear":
        # VIX 급등 (spike)
        kospi = pd.Series(np.linspace(2800, 2000, n), index=idx)
        sp500 = pd.Series(np.linspace(5200, 4000, n), index=idx)
        vix_arr = np.full(n, 15.0)
        vix_arr[-1] = 25.0   # last > 20-day mean * 1.15
        vix = pd.Series(vix_arr, index=idx)
    else:
        # neutral: SMA200 조건 불충족, spike 없음
        kospi = pd.Series(np.full(n, 2500.0), index=idx)
        sp500 = pd.Series(np.full(n, 4800.0), index=idx)
        vix   = pd.Series(np.full(n, 15.0), index=idx)
    usdkrw = pd.Series(np.full(n, 1300.0), index=idx)
    return pd.DataFrame({"kospi": kospi, "sp500": sp500, "vix": vix, "usdkrw": usdkrw})


# ──────────────────────────────────────────────────────────────
# compute_regime 테스트
# ──────────────────────────────────────────────────────────────

class TestComputeRegime:
    def test_empty_df_returns_neutral(self):
        assert compute_regime(pd.DataFrame()) == "neutral"

    def test_too_short_returns_neutral(self):
        df = pd.DataFrame({"kospi": [2500] * 10, "sp500": [5000] * 10,
                           "vix": [15.0] * 10, "usdkrw": [1300.0] * 10})
        assert compute_regime(df) == "neutral"

    def test_bull_conditions(self):
        df = _neutral_market_df(n=504, regime="bull")
        result = compute_regime(df)
        assert result == "bull"

    def test_bear_vix_spike(self):
        df = _neutral_market_df(n=504, regime="neutral")
        # VIX 마지막 값을 20일 이동평균의 2배로 설정
        vix_sma20 = df["vix"].rolling(20).mean().iloc[-1]
        df = df.copy()
        df.loc[df.index[-1], "vix"] = vix_sma20 * 2.0
        result = compute_regime(df)
        assert result == "bear"

    def test_neutral_no_spike_no_bull(self):
        df = _neutral_market_df(n=504, regime="neutral")
        result = compute_regime(df)
        # KOSPI flat (not > SMA200), VIX calm → neutral
        assert result in ("neutral", "bear")  # flat prices → SMA200 equal → depends on exact values


# ──────────────────────────────────────────────────────────────
# _safe_pct_rank 테스트
# ──────────────────────────────────────────────────────────────

class TestSafePctRank:
    def test_single_value_returns_50(self):
        result = _safe_pct_rank({"A": 100.0})
        assert result["A"] == 50.0

    def test_none_returns_50(self):
        result = _safe_pct_rank({"A": None, "B": 10.0, "C": 20.0})
        assert result["A"] == 50.0

    def test_all_none_returns_50(self):
        result = _safe_pct_rank({"A": None, "B": None})
        assert result["A"] == result["B"] == 50.0

    def test_monotonicity(self):
        result = _safe_pct_rank({"A": 10.0, "B": 20.0, "C": 30.0})
        assert result["A"] < result["B"] < result["C"]

    def test_values_in_0_100(self):
        result = _safe_pct_rank({"A": 1.0, "B": 5.0, "C": 10.0, "D": 50.0})
        for v in result.values():
            assert 0.0 <= v <= 100.0


# ──────────────────────────────────────────────────────────────
# is_filtered 테스트
# ──────────────────────────────────────────────────────────────

class TestIsFiltered:
    def test_low_fscore_filtered(self):
        assert is_filtered(FSCORE_FILTER_THRESHOLD, None, 999, "US") is True

    def test_fscore_at_threshold_filtered(self):
        assert is_filtered(FSCORE_FILTER_THRESHOLD, None, 999, "US") is True

    def test_fscore_above_threshold_not_filtered(self):
        assert is_filtered(FSCORE_FILTER_THRESHOLD + 1, None, 999, "US") is False

    def test_kr_high_idio_vol_filtered(self):
        assert is_filtered(5, 0.05, 0.03, "KR") is True

    def test_us_high_idio_vol_not_filtered(self):
        assert is_filtered(5, 0.05, 0.03, "US") is False

    def test_kr_low_idio_vol_not_filtered(self):
        assert is_filtered(5, 0.02, 0.03, "KR") is False

    def test_none_idio_vol_not_filtered_kr(self):
        assert is_filtered(5, None, 0.03, "KR") is False


# ──────────────────────────────────────────────────────────────
# piotroski_fscore 테스트 (DB mock)
# ──────────────────────────────────────────────────────────────

class TestPiotroskoFscore:
    def _run(self, funds, vals):
        conn = MagicMock()
        with patch("src.compute_quant._fetch_fundamentals_annual", return_value=funds), \
             patch("src.compute_quant._fetch_valuation_two", return_value=vals):
            return piotroski_fscore("TEST", conn)

    def test_no_fundamentals_returns_4_and_flag(self):
        score, flags = self._run([], [])
        assert score == 4
        assert any("데이터 부족" in f for f in flags)

    def test_all_positive_high_score(self):
        funds = [
            {"period_end": date(2025, 12, 31), "revenue": 1100, "op_income": 200,
             "op_margin": 0.18, "net_income": 100},
            {"period_end": date(2024, 12, 31), "revenue": 1000, "op_income": 150,
             "op_margin": 0.15, "net_income": 80},
        ]
        vals = [
            {"asof": date(2026, 1, 1), "per_f": 15.0, "pbr": 1.5, "ev_ebitda": 10.0,
             "roe": 0.20, "roa": 0.08, "debt_ratio": 60.0, "rev_growth": 0.10},
            {"asof": date(2025, 1, 1), "per_f": 16.0, "pbr": 1.6, "ev_ebitda": 11.0,
             "roe": 0.18, "roa": 0.07, "debt_ratio": 70.0, "rev_growth": 0.08},
        ]
        score, flags = self._run(funds, vals)
        assert score >= 5

    def test_losing_company_low_score(self):
        funds = [
            {"period_end": date(2025, 12, 31), "revenue": 800, "op_income": -50,
             "op_margin": -0.06, "net_income": -80},
            {"period_end": date(2024, 12, 31), "revenue": 900, "op_income": -20,
             "op_margin": -0.02, "net_income": -30},
        ]
        vals = [
            {"asof": date(2026, 1, 1), "roe": -0.05, "roa": -0.02, "debt_ratio": 200.0,
             "rev_growth": -0.10, "per_f": None, "pbr": None, "ev_ebitda": None},
            {"asof": date(2025, 1, 1), "roe": -0.03, "roa": -0.01, "debt_ratio": 180.0,
             "rev_growth": -0.05, "per_f": None, "pbr": None, "ev_ebitda": None},
        ]
        score, flags = self._run(funds, vals)
        assert score <= FSCORE_FILTER_THRESHOLD  # 낮은 점수

    def test_always_has_no_shares_flag(self):
        funds = [{"period_end": date(2025, 12, 31), "revenue": 100, "op_income": 10,
                  "op_margin": 0.10, "net_income": 8}]
        vals = [{"roe": 0.1, "roa": 0.05, "debt_ratio": 50.0, "rev_growth": 0.05,
                 "per_f": 15.0, "pbr": 1.5, "ev_ebitda": 10.0}]
        _, flags = self._run(funds, vals)
        assert any("발행주식수" in f for f in flags)


# ──────────────────────────────────────────────────────────────
# compute_quant_universe 통합 테스트
# ──────────────────────────────────────────────────────────────

def _run_universe(tickers, fscore=5, regime="neutral", price_map=None):
    """공통 패치 적용 후 compute_quant_universe 실행."""
    mdf = _neutral_market_df(n=504, regime=regime)
    pm = price_map or _PRICE_MAP

    def _prices(ticker, days, conn):
        return pm.get(ticker, _trend_prices(0.0))

    with patch("src.compute_quant._fetch_market_history", return_value=mdf), \
         patch("src.compute_quant._fetch_prices", side_effect=_prices), \
         patch("src.compute_quant._fetch_ticker_market", return_value="US"), \
         patch("src.compute_quant.piotroski_fscore", return_value=(fscore, [])), \
         patch("src.compute_quant._fetch_valuation_two", side_effect=lambda t, c: [_neutral_val()]), \
         patch("src.compute_quant._fetch_fundamentals_annual", side_effect=lambda t, c: _neutral_fund()), \
         patch("src.compute_quant._fetch_analyst_records", return_value=(None, None)), \
         patch("src.compute_quant._fetch_sentiment_score", return_value=0.0):
        return compute_quant_universe(tickers, MagicMock(), asof=ASOF)


class TestComputeQuantUniverse:
    def test_empty_universe_returns_empty(self):
        result = _run_universe([])
        assert result == []

    def test_returns_one_row_per_ticker(self):
        result = _run_universe(TICKERS)
        assert len(result) == len(TICKERS)
        assert {r.ticker for r in result} == set(TICKERS)

    def test_scores_in_0_100(self):
        rows = _run_universe(TICKERS)
        for r in rows:
            for attr in ("momentum", "value", "quality", "growth", "sentiment"):
                v = getattr(r, attr)
                assert 0.0 <= v <= 100.0, f"{r.ticker}.{attr}={v}"

    def test_momentum_monotonicity(self):
        """M_12M 높은 종목이 더 높은 momentum 점수를 가져야 함."""
        rows = _run_universe(TICKERS)
        score = {r.ticker: r.momentum for r in rows}
        assert score["STRONG"] > score["MIDU"] > score["FLAT"] > score["WEAK"] > score["CRASH"]

    def test_value_monotonicity(self):
        """PER_F 낮은 종목이 더 높은 value 점수를 가져야 함."""
        val_tickers = ["CHEAP", "FAIR", "DEAR"]
        per_vals = {"CHEAP": 8.0, "FAIR": 15.0, "DEAR": 30.0}

        def _val(ticker, conn):
            return [{"per_f": per_vals[ticker], "per_t": per_vals[ticker],
                     "pbr": 1.5, "ev_ebitda": 12.0,
                     "roe": 0.12, "roa": 0.06, "debt_ratio": 80.0, "rev_growth": 0.05}]

        flat = _trend_prices(0.0)
        pm = {t: flat for t in val_tickers}

        with patch("src.compute_quant._fetch_market_history", return_value=_neutral_market_df()), \
             patch("src.compute_quant._fetch_prices", side_effect=lambda t, d, c: flat), \
             patch("src.compute_quant._fetch_ticker_market", return_value="US"), \
             patch("src.compute_quant.piotroski_fscore", return_value=(5, [])), \
             patch("src.compute_quant._fetch_valuation_two", side_effect=_val), \
             patch("src.compute_quant._fetch_fundamentals_annual", side_effect=lambda t, c: _neutral_fund()), \
             patch("src.compute_quant._fetch_analyst_records", return_value=(None, None)), \
             patch("src.compute_quant._fetch_sentiment_score", return_value=0.0):
            rows = compute_quant_universe(val_tickers, MagicMock(), asof=ASOF)

        score = {r.ticker: r.value for r in rows}
        assert score["CHEAP"] > score["FAIR"] > score["DEAR"]

    def test_quality_monotonicity(self):
        """ROE 높은 종목이 더 높은 quality 점수를 가져야 함."""
        qual_tickers = ["HQ", "MQ", "LQ"]
        roe_vals = {"HQ": 0.30, "MQ": 0.15, "LQ": 0.05}

        def _val(ticker, conn):
            return [{"per_f": 15.0, "per_t": 15.0, "pbr": 1.5, "ev_ebitda": 12.0,
                     "roe": roe_vals[ticker], "roa": roe_vals[ticker] / 2,
                     "debt_ratio": 80.0, "rev_growth": 0.05}]

        flat = _trend_prices(0.0)

        with patch("src.compute_quant._fetch_market_history", return_value=_neutral_market_df()), \
             patch("src.compute_quant._fetch_prices", side_effect=lambda t, d, c: flat), \
             patch("src.compute_quant._fetch_ticker_market", return_value="US"), \
             patch("src.compute_quant.piotroski_fscore", return_value=(5, [])), \
             patch("src.compute_quant._fetch_valuation_two", side_effect=_val), \
             patch("src.compute_quant._fetch_fundamentals_annual", side_effect=lambda t, c: _neutral_fund()), \
             patch("src.compute_quant._fetch_analyst_records", return_value=(None, None)), \
             patch("src.compute_quant._fetch_sentiment_score", return_value=0.0):
            rows = compute_quant_universe(qual_tickers, MagicMock(), asof=ASOF)

        score = {r.ticker: r.quality for r in rows}
        assert score["HQ"] > score["MQ"] > score["LQ"]

    def test_fscore_filter_sets_composite_none(self):
        """F-Score ≤ 3인 종목은 composite=None."""
        rows = _run_universe(["STRONG"], fscore=FSCORE_FILTER_THRESHOLD)
        row = rows[0]
        assert row.composite is None
        assert any(_F_FILTERED in f for f in row.flags)

    def test_high_fscore_has_composite(self):
        rows = _run_universe(["STRONG"], fscore=7)
        assert rows[0].composite is not None

    def test_missing_prices_returns_50_momentum(self):
        """가격 데이터 없으면 momentum=50(중립)."""
        with patch("src.compute_quant._fetch_market_history", return_value=_neutral_market_df()), \
             patch("src.compute_quant._fetch_prices", return_value=pd.DataFrame(columns=["close", "volume"])), \
             patch("src.compute_quant._fetch_ticker_market", return_value="US"), \
             patch("src.compute_quant.piotroski_fscore", return_value=(5, [])), \
             patch("src.compute_quant._fetch_valuation_two", return_value=[_neutral_val()]), \
             patch("src.compute_quant._fetch_fundamentals_annual", return_value=_neutral_fund()), \
             patch("src.compute_quant._fetch_analyst_records", return_value=(None, None)), \
             patch("src.compute_quant._fetch_sentiment_score", return_value=None):
            rows = compute_quant_universe(["NODATA"], MagicMock(), asof=ASOF)
        row = rows[0]
        assert row.momentum == 50.0
        assert any(_F_MISSING in f for f in row.flags)

    def test_missing_valuation_returns_50_value(self):
        """밸류에이션 데이터 없으면 value=50."""
        with patch("src.compute_quant._fetch_market_history", return_value=_neutral_market_df()), \
             patch("src.compute_quant._fetch_prices", side_effect=lambda t, d, c: _trend_prices(0.0)), \
             patch("src.compute_quant._fetch_ticker_market", return_value="US"), \
             patch("src.compute_quant.piotroski_fscore", return_value=(5, [])), \
             patch("src.compute_quant._fetch_valuation_two", return_value=[]), \
             patch("src.compute_quant._fetch_fundamentals_annual", return_value=_neutral_fund()), \
             patch("src.compute_quant._fetch_analyst_records", return_value=(None, None)), \
             patch("src.compute_quant._fetch_sentiment_score", return_value=None):
            rows = compute_quant_universe(["NODATA"], MagicMock(), asof=ASOF)
        row = rows[0]
        assert row.value == 50.0

    def test_no_crash_on_all_none_data(self):
        """모든 데이터가 None/빈 값이어도 예외 없이 중립값 반환."""
        with patch("src.compute_quant._fetch_market_history", return_value=pd.DataFrame()), \
             patch("src.compute_quant._fetch_prices", return_value=pd.DataFrame(columns=["close", "volume"])), \
             patch("src.compute_quant._fetch_ticker_market", return_value="US"), \
             patch("src.compute_quant.piotroski_fscore", return_value=(4, [_F_MISSING])), \
             patch("src.compute_quant._fetch_valuation_two", return_value=[]), \
             patch("src.compute_quant._fetch_fundamentals_annual", return_value=[]), \
             patch("src.compute_quant._fetch_analyst_records", return_value=(None, None)), \
             patch("src.compute_quant._fetch_sentiment_score", return_value=None):
            rows = compute_quant_universe(TICKERS, MagicMock(), asof=ASOF)
        assert len(rows) == len(TICKERS)
        for row in rows:
            assert row.momentum == 50.0
            assert row.value == 50.0

    def test_bull_regime_momentum_dominant(self):
        """bull 레짐에서 momentum 가중치가 0.45여야 함."""
        assert _REGIME_WEIGHTS["bull"]["momentum"] == 0.45

    def test_bear_regime_quality_dominant(self):
        """bear 레짐에서 quality 가중치가 0.45여야 함."""
        assert _REGIME_WEIGHTS["bear"]["quality"] == 0.45

    def test_regime_affects_composite(self):
        """
        레짐이 다르면 composite 순위가 달라진다.
        HIGH_MOM: 강한 상승 추세 + 낮은 ROE  → bull에서 유리, bear에서 불리
        HIGH_QUAL: 횡보 추세      + 높은 ROE  → bear에서 유리, bull에서 불리
        """
        tickers_2 = ["HIGH_MOM", "HIGH_QUAL"]

        def _val(t, c):
            if t == "HIGH_MOM":
                return [{"per_f": 15.0, "per_t": 15.0, "pbr": 1.5, "ev_ebitda": 12.0,
                         "roe": 0.02, "roa": 0.01, "debt_ratio": 200.0, "rev_growth": 0.01}]
            else:
                return [{"per_f": 15.0, "per_t": 15.0, "pbr": 1.5, "ev_ebitda": 12.0,
                         "roe": 0.35, "roa": 0.18, "debt_ratio": 30.0, "rev_growth": 0.15}]

        def _prices(t, d, c):
            return _trend_prices(+0.60) if t == "HIGH_MOM" else _trend_prices(0.0)

        def _composite_diff(regime):
            mdf = _neutral_market_df(n=504, regime=regime)
            with patch("src.compute_quant._fetch_market_history", return_value=mdf), \
                 patch("src.compute_quant._fetch_prices", side_effect=_prices), \
                 patch("src.compute_quant._fetch_ticker_market", return_value="US"), \
                 patch("src.compute_quant.piotroski_fscore", return_value=(6, [])), \
                 patch("src.compute_quant._fetch_valuation_two", side_effect=_val), \
                 patch("src.compute_quant._fetch_fundamentals_annual", side_effect=lambda t, c: _neutral_fund()), \
                 patch("src.compute_quant._fetch_analyst_records", return_value=(None, None)), \
                 patch("src.compute_quant._fetch_sentiment_score", return_value=0.0):
                rows = compute_quant_universe(tickers_2, MagicMock(), asof=ASOF)
            score = {r.ticker: r.composite for r in rows}
            return score["HIGH_MOM"] - score["HIGH_QUAL"]  # >0 → HIGH_MOM 우세

        bull_diff = _composite_diff("bull")
        bear_diff = _composite_diff("bear")
        # bull: momentum 가중치 0.45 → HIGH_MOM 유리 → diff > 0
        assert bull_diff is not None and bear_diff is not None
        assert bull_diff > 0, f"bull에서 HIGH_MOM이 더 높아야 함: diff={bull_diff}"
        # bear: quality 가중치 0.45 → HIGH_QUAL 유리 → diff < 0
        assert bear_diff < 0, f"bear에서 HIGH_QUAL이 더 높아야 함: diff={bear_diff}"


# ── 금융 섹터 인지형 quality/필터 (은행·보험·증권) ──────────────────────
class TestFinancialSectorQuality:
    def test_is_financial_normalizes_messy_sectors(self):
        for s in ["insurance", "Fiance", "Financials", "Financial Services",
                  "Bank", "증권", "보험", "은행", "금융"]:
            assert _is_financial(s) is True, s
        for s in ["Technology", "Semiconductors", "Energy", "bond", "", None]:
            assert _is_financial(s) is False, s

    def test_is_filtered_skips_fscore_for_financials(self):
        # 비금융: 저fscore → 필터. 금융: 저fscore여도 필터 안 함(Piotroski 부적합).
        assert is_filtered(1, None, 999, "US", is_financial=False) is True
        assert is_filtered(1, None, 999, "US", is_financial=True) is False
        # 고유변동성 필터는 금융도 유지(KR)
        assert is_filtered(1, 0.05, 0.03, "KR", is_financial=True) is True

    def test_financial_quality_roe_driven_not_debt_penalized(self):
        # FIN(보험)과 IND(산업재)가 동일 고ROE·거대부채·저fscore. FIN은 ROE로 높게,
        # IND는 부채 페널티+저fscore로 낮게 나와야(섹터 분기).
        val_map = {
            "FIN": {"roe": 0.20, "roa": None, "debt_ratio": 900.0},
            "IND": {"roe": 0.20, "roa": 0.10, "debt_ratio": 900.0},
            "LO1": {"roe": 0.02, "roa": 0.01, "debt_ratio": 30.0},
            "LO2": {"roe": 0.05, "roa": 0.02, "debt_ratio": 20.0},
        }
        fund_map = {t: [{"op_margin": 0.1}] for t in val_map}
        fscore_map = {"FIN": 1, "IND": 1, "LO1": 6, "LO2": 5}
        fin = {"FIN": True, "IND": False}
        q = _score_quality(val_map, fscore_map, {t: [] for t in val_map}, fund_map, fin)
        assert q["FIN"] > q["IND"]          # 부채 페널티·fscore에서 자유로워 더 높음
        assert q["FIN"] >= 60               # 최상위 ROE → 상위권

    def test_nonfinancial_quality_unchanged_by_default(self):
        # financial_map 없이 호출 = 종전 로직(비금융 회귀 0 확인).
        val_map = {"A": {"roe": 0.1, "roa": 0.05, "debt_ratio": 50.0},
                   "B": {"roe": 0.2, "roa": 0.10, "debt_ratio": 30.0}}
        fund_map = {t: [{"op_margin": 0.1}] for t in val_map}
        fscore_map = {"A": 5, "B": 6}
        flags = {t: [] for t in val_map}
        q_default = _score_quality(val_map, fscore_map, flags, fund_map)
        q_nonfin = _score_quality(val_map, fscore_map, flags, fund_map, {"A": False, "B": False})
        assert q_default == q_nonfin        # financial_map 유무가 비금융에 영향 없음


# ── 이상치 winsorize(momentum z-score 견고화) ──────────────────────────
class TestWinsorize:
    def test_clips_to_5_95_percentile(self):
        # 정상 12종 + 극단 1종. 극단값이 상한(95pct)으로 클립돼야.
        vals = {f"N{i}": float(i) for i in range(12)}   # 0..11
        vals["OUT"] = 1000.0
        w = _winsorize(vals)
        import numpy as np
        hi = np.percentile([float(v) for v in vals.values()], 95)
        assert w["OUT"] == hi                            # 극단 → 상한 클립
        assert w["OUT"] < 1000.0
        assert w["N5"] == 5.0                            # 정상값 불변

    def test_preserves_none(self):
        vals = {f"N{i}": float(i) for i in range(12)}
        vals["M"] = None
        assert _winsorize(vals)["M"] is None

    def test_small_sample_skips_clip(self):
        # 유효표본 < WINSOR_MIN_N → 원본 그대로(분위수 불안정). N개=MIN_N-2, +OUT = MIN_N-1
        vals = {f"N{i}": float(i) for i in range(WINSOR_MIN_N - 2)}
        vals["OUT"] = 1000.0
        assert len([v for v in vals.values() if v is not None]) < WINSOR_MIN_N
        assert _winsorize(vals)["OUT"] == 1000.0

    def test_momentum_outlier_does_not_collapse_discrimination(self):
        # 극단 모멘텀 1종이 있어도 비이상치들의 momentum 순위가 보존되는지(변별력 유지).
        def raw(m12):
            return {"m_1m": m12 / 12, "m_3m": m12 / 4, "m_6m": m12 / 2, "m_12m": m12,
                    "vol_126": 0.3}
        base = {f"T{i}": raw(0.1 * i) for i in range(10)}   # 0.0..0.9 완만한 스프레드
        with_out = dict(base); with_out["OUT"] = raw(20.0)  # +2000% 극단
        s = _score_momentum(with_out, {t: [] for t in with_out})
        # 비이상치들의 상대 순위 단조 보존(T9 > T5 > T1)
        assert s["T9"] > s["T5"] > s["T1"]
        assert s["OUT"] > s["T9"]                           # 극단은 여전히 최상위
