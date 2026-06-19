from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pandas as pd

from src import backtest as bt
from src import export_dashboard_data as export_mod


def test_strategy_registry_contains_required_names():
    from src.strategies import RETROSPECTIVE_STRATEGIES, TRUE_STRATEGIES

    assert [s.name for s in TRUE_STRATEGIES] == ["momentum_12_1", "low_vol", "equal_weight_bh"]
    assert [s.name for s in RETROSPECTIVE_STRATEGIES] == ["value", "quality", "multifactor"]
    assert all(s.track == "true" for s in TRUE_STRATEGIES)
    assert all(s.track == "retrospective" for s in RETROSPECTIVE_STRATEGIES)


def test_rebase_curve_starts_at_100():
    series = pd.Series(
        [100.0, 110.0, 121.0],
        index=pd.to_datetime(["2026-01-31", "2026-02-28", "2026-03-31"]),
    )

    curve = bt._rebase_curve_from_series(series)

    assert curve[0]["value"] == 100.0
    assert curve[-1]["value"] == 121.0


def test_regime_returns_compound_by_bucket():
    periods = [
        {"regime": "bull", "return": 0.10},
        {"regime": "bull", "return": -0.05},
        {"regime": "bear", "return": 0.02},
    ]

    out = bt._regime_returns_from_periods(periods)

    assert out["bull"] == 0.045
    assert out["bear"] == 0.02
    assert out["neutral"] is None


class _FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql):
        self.sql = sql

    def fetchall(self):
        return self.rows


def test_load_backtest_groups_by_track_and_horizon():
    rows = [
        {
            "strategy": "momentum_12_1",
            "track": "true",
            "horizon": "5y",
            "cum_return": 0.8,
            "cagr": 0.12,
            "mdd": -0.2,
            "sharpe": 0.9,
            "regime_returns": {"bull": 0.4, "neutral": 0.1, "bear": -0.05},
            "payload": {
                "label": "모멘텀 12-1",
                "equity_curve": [{"date": "2026-01-31", "value": 100.0}],
                "benchmarks": {"^GSPC": [{"date": "2026-01-31", "value": 100.0}]},
            },
        },
        {
            "strategy": "value",
            "track": "retrospective",
            "horizon": "5y",
            "cum_return": 0.5,
            "cagr": 0.08,
            "mdd": -0.3,
            "sharpe": 0.5,
            "regime_returns": {"bull": 0.2, "neutral": 0.1, "bear": -0.08},
            "payload": {
                "label": "가치",
                "warning": "선택편향 경고",
                "selected_tickers": ["AAA", "BBB"],
                "equity_curve": [{"date": "2026-01-31", "value": 100.0}],
                "benchmarks": {"^KS11": [{"date": "2026-01-31", "value": 100.0}]},
            },
        },
    ]

    conn = MagicMock()
    conn.cursor.return_value = _FakeCursor(rows)

    out = export_mod._load_backtest(conn)

    assert out["trueTrack"]["strategies"][0]["name"] == "momentum_12_1"
    assert out["trueTrack"]["strategies"][0]["horizons"]["5y"]["cumReturn"] == 0.8
    assert out["retrospective"]["warning"] == "선택편향 경고"
    assert out["retrospective"]["strategies"][0]["horizons"]["5y"]["selectedTickers"] == ["AAA", "BBB"]


def test_build_strategy_guidance_prefers_true_track_and_keeps_retro_as_reference():
    backtest = {
        "trueTrack": {
            "strategies": [
                {"name": "momentum_12_1", "label": "모멘텀 12-1", "horizons": {"5y": {"regimeReturns": {"bull": 0.42, "neutral": 0.11, "bear": -0.08}}}},
                {"name": "low_vol", "label": "저변동성", "horizons": {"5y": {"regimeReturns": {"bull": 0.20, "neutral": 0.18, "bear": 0.05}}}},
            ]
        },
        "retrospective": {
            "warning": "선택편향 경고",
            "strategies": [
                {"name": "multifactor", "label": "멀티팩터", "horizons": {"5y": {"regimeReturns": {"bull": 0.55, "neutral": 0.10, "bear": -0.12}}}},
            ],
        },
    }

    out = export_mod._build_strategy_guidance(backtest, {"overall": "bull"})

    assert out["primary"]["track"] == "true"
    assert out["primary"]["name"] == "momentum_12_1"
    assert "상승" in out["primary"]["reason"]
    assert out["reference"]["track"] == "retrospective"
    assert out["reference"]["warning"] == "선택편향 경고"
