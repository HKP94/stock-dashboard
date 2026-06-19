"""
test_backtest.py — backtest.py 단위 테스트 (합성 시계열, 네트워크/DB 없음)

검증:
  - 모멘텀 선정 단조성: 더 강하게 상승한 종목이 더 높은 모멘텀 점수
  - equity curve = (1+r) 누적곱 일치
  - MDD / Sharpe 계산 정확성
  - 회고 기간수익률 매핑 정확성
"""
import math
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from src import backtest as bt


# ── 합성 가격 매트릭스 ──────────────────────────────────────────
def _make_matrix(n=300):
    """date×ticker 매트릭스. UP: 강한 상승, FLAT: 횡보, DOWN: 하락."""
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    up   = 100 * (1.004 ** np.arange(n))      # 일 0.4% 복리 상승
    flat = 100 * np.ones(n)
    down = 100 * (0.997 ** np.arange(n))      # 일 0.3% 하락
    return pd.DataFrame({"UP": up, "FLAT": flat, "DOWN": down}, index=idx)


# ── 모멘텀 단조성 ──────────────────────────────────────────────
class TestMomentumMonotonic:
    def test_up_beats_flat_beats_down(self):
        mat = _make_matrix()
        scores = bt._momentum_scores_at(mat, len(mat) - 1)
        assert "UP" in scores and "DOWN" in scores
        assert scores["UP"] > scores["FLAT"] > scores["DOWN"]

    def test_components_none_when_insufficient(self):
        mat = _make_matrix()
        prices = mat["UP"].values.astype(float)
        assert bt._momentum_components(prices, 5) is None  # t<21

    def test_strong_uptrend_positive_logret(self):
        mat = _make_matrix()
        prices = mat["UP"].values.astype(float)
        comp = bt._momentum_components(prices, len(prices) - 1)
        assert comp["m_12m"] > 0 and comp["m_6m"] > 0


# ── equity / 지표 ──────────────────────────────────────────────
class TestEquityMetrics:
    def test_cumulative_product(self):
        # 월 +10% 3회 → 누적 1.1^3
        curve = [
            {"date": "2025-01-31", "value": 1.0},
            {"date": "2025-02-28", "value": 1.1},
            {"date": "2025-03-31", "value": 1.21},
            {"date": "2025-04-30", "value": 1.331},
        ]
        m = bt._metrics_from_equity(curve)
        assert m["cum_return"] == pytest.approx(0.331, abs=1e-3)

    def test_mdd(self):
        # 1.0 → 1.2 → 0.9 → 1.1 : MDD = (0.9-1.2)/1.2 = -0.25
        curve = [
            {"date": "2025-01-31", "value": 1.0},
            {"date": "2025-02-28", "value": 1.2},
            {"date": "2025-03-31", "value": 0.9},
            {"date": "2025-04-30", "value": 1.1},
        ]
        m = bt._metrics_from_equity(curve)
        assert m["mdd"] == pytest.approx(-0.25, abs=1e-4)

    def test_sharpe_constant_returns_high(self):
        # 일정한 양(+5%/월) 수익률 → std≈0 → sharpe 0 처리(분모 0 보호)
        curve = [{"date": f"2025-{m:02d}-15", "value": 1.05 ** i} for i, m in enumerate(range(1, 7), start=0)]
        res = bt._metrics_from_equity(curve)
        assert res["cum_return"] > 0
        assert res["sharpe"] == 0.0  # 분산 0 → 0 반환

    def test_sharpe_sign_positive(self):
        curve = [
            {"date": "2025-01-31", "value": 1.0},
            {"date": "2025-02-28", "value": 1.05},
            {"date": "2025-03-31", "value": 1.02},
            {"date": "2025-04-30", "value": 1.10},
            {"date": "2025-05-31", "value": 1.15},
        ]
        m = bt._metrics_from_equity(curve)
        assert m["sharpe"] > 0
        assert m["vol"] > 0

    def test_empty_curve(self):
        m = bt._metrics_from_equity([{"date": "2025-01-31", "value": 1.0}])
        assert m["cum_return"] == 0.0


# ── 회고 기간수익률 ────────────────────────────────────────────
class TestRetroReturns:
    def test_period_returns_known(self):
        # 252영업일 0.4% 복리 → ret12m ≈ 1.004^252 - 1
        mat = _make_matrix(300)
        pr = bt._period_returns_for(mat, "UP")
        expected_12m = 1.004 ** 252 - 1
        assert pr["ret12m"] == pytest.approx(expected_12m, rel=0.02)
        assert pr["ret1m"] == pytest.approx(1.004 ** 21 - 1, rel=0.02)

    def test_period_returns_missing_ticker(self):
        mat = _make_matrix()
        pr = bt._period_returns_for(mat, "NOPE")
        assert all(v is None for v in pr.values())

    def test_down_negative_return(self):
        mat = _make_matrix()
        pr = bt._period_returns_for(mat, "DOWN")
        assert pr["ret12m"] < 0


# ── 백테스트 통합 (가격 매트릭스/watchlist/upsert 패치) ──────────
class TestBacktestIntegration:
    def test_momentum_backtest_selects_uptrend(self):
        mat = _make_matrix(320)
        upserts = []

        def fake_upsert(conn, definition, horizon, metrics, regime_returns, payload):
            if horizon == "5y":
                upserts.append({
                    "name": definition.name,
                    "track": definition.track,
                    "metrics": metrics,
                    "payload": payload,
                })

        conn = MagicMock()
        with patch.object(bt, "_load_watchlist", return_value={"UP": "Up", "FLAT": "Flat", "DOWN": "Down"}), \
             patch.object(bt, "_load_price_matrix", return_value=mat), \
             patch.object(bt, "_load_regime_frame", return_value=pd.DataFrame()), \
             patch.object(bt, "_load_index_matrix", return_value=pd.DataFrame()), \
             patch.object(bt, "_upsert_backtest_row", side_effect=fake_upsert):
            res = bt.compute_momentum_backtest(conn, top_n=1)

        assert res["ok"] is True
        names = {u["name"] for u in upserts}
        assert names == {"momentum_12_1", "low_vol", "equal_weight_bh"}
        assert all(u["track"] == "true" for u in upserts)
        mom = next(u for u in upserts if u["name"] == "momentum_12_1")["metrics"]
        eqw = next(u for u in upserts if u["name"] == "equal_weight_bh")["metrics"]
        assert mom["cum_return"] > eqw["cum_return"]
        # 최근 선정에 UP 포함
        sel = next(u for u in upserts if u["name"] == "momentum_12_1")["payload"]["selection_examples"]
        assert any("UP" in s["tickers"] for s in sel)

    def test_retrospective_maps_top_factors(self):
        mat = _make_matrix(300)
        upserts = []

        def fake_upsert(conn, definition, horizon, metrics, regime_returns, payload):
            if horizon == "5y":
                upserts.append({"name": definition.name, "track": definition.track, "payload": payload})

        # quant_scores fake: UP이 모든 팩터 최고
        quant_rows = [
            {"ticker": "UP", "momentum": 90, "value": 80, "quality": 85, "growth": 88, "composite": 87},
            {"ticker": "FLAT", "momentum": 50, "value": 50, "quality": 50, "growth": 50, "composite": 50},
            {"ticker": "DOWN", "momentum": 10, "value": 20, "quality": 15, "growth": 12, "composite": None},
        ]
        conn = MagicMock()

        with patch.object(bt, "_load_watchlist", return_value={"UP": "Up", "FLAT": "Flat", "DOWN": "Down"}), \
             patch.object(bt, "_load_price_matrix", return_value=mat), \
             patch.object(bt, "_load_latest_quant_rows", return_value=(mat.index[-1].date(), quant_rows)), \
             patch.object(bt, "_load_regime_frame", return_value=pd.DataFrame()), \
             patch.object(bt, "_load_index_matrix", return_value=pd.DataFrame()), \
             patch.object(bt, "_upsert_backtest_row", side_effect=fake_upsert):
            res = bt.compute_retrospective(conn)

        assert res["ok"] is True
        assert all(u["track"] == "retrospective" for u in upserts)
        assert {u["name"] for u in upserts} == {"value", "quality", "multifactor"}
        for u in upserts:
            top = u["payload"]["selected_tickers"]
            assert top[0]["ticker"] == "UP"
            if u["name"] == "multifactor":
                assert all(t["ticker"] != "DOWN" for t in top)
