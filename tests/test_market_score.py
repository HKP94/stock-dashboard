"""
tests/test_market_score.py — Wave 5-B 시장 매력도 점수(결정론)

- 서브스코어(추세·변동성·매크로) 방향
- 점수 공식·방향 임계·신뢰도 분기
- **정확도 가드**: 강한 divergence → 신뢰도 '하' + 점수 중립(50) 수축 (강화 요구사항)
- 데이터 부족 → 하 + 수축
- 베타 경로 관찰 문구(매매 단정 없음)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd

import src.compute_market_score as M
from src.export_dashboard_data import _market_beta_note


def _bench(daily_return: float, n: int = 210) -> pd.DataFrame:
    closes = [100.0]
    for _ in range(n):
        closes.append(closes[-1] * (1 + daily_return))
    return pd.DataFrame({"close": closes}, index=pd.date_range("2025-01-01", periods=len(closes)))


def _conn(breadth_rows=None):
    conn = MagicMock()
    cur = MagicMock()
    cur.__enter__.return_value = cur
    cur.__exit__.return_value = False
    cur.fetchall.return_value = breadth_rows or []
    conn.cursor.return_value = cur
    return conn


# ── 서브스코어 ───────────────────────────────────────────────────

def test_trend_subscore_sign():
    assert M._trend_subscore(_bench(0.004)) > 0.5      # 우상향
    assert M._trend_subscore(_bench(-0.004)) < -0.5    # 급락
    assert M._trend_subscore(pd.DataFrame(columns=["close"])) is None


def test_vol_subscore_vix_levels():
    assert M._vol_subscore(12.0) > 0       # 저변동성 우호
    assert M._vol_subscore(35.0) == -1.0   # 고변동성 비우호
    assert M._vol_subscore(None) is None


def test_macro_subscore_easing_vs_tightening():
    easing = M._macro_subscore({"FEDFUNDS": (4.0, 4.5), "DGS10": (3.8, 4.2), "DXY": (100, 103)}, "US")
    tightening = M._macro_subscore({"FEDFUNDS": (5.5, 5.0), "DGS10": (4.5, 4.0), "DXY": (108, 104)}, "US")
    assert easing > 0 and tightening < 0


# ── 점수·방향·신뢰도 ─────────────────────────────────────────────

def test_bull_when_all_favorable():
    r = M.compute_region_score("US", _bench(0.004), 12.0,
                               {"FEDFUNDS": (4.0, 4.5), "DGS10": (3.8, 4.2), "DXY": (100, 103)}, _conn())
    assert r.direction == "강세" and r.score >= M.MS_DIR_BULL and r.confidence == "상"


def test_bear_when_all_unfavorable():
    r = M.compute_region_score("KR", _bench(-0.004), 35.0,
                               {"KR_BASE_RATE": (3.5, 3.0), "DXY": (108, 104)}, _conn())
    assert r.direction == "약세" and r.score <= M.MS_DIR_BEAR and r.confidence == "상"


def test_strong_divergence_shrinks_score_and_lowers_confidence():
    # 지수 강세(+) vs VIX 35 + 긴축 + 강달러(−) → 강한 충돌
    r = M.compute_region_score("US", _bench(0.005), 35.0,
                               {"FEDFUNDS": (5.5, 5.0), "DGS10": (4.5, 4.0), "DXY": (108, 104)}, _conn())
    raw = r.components["raw_score"]
    assert r.confidence == "하"
    assert r.direction == "중립"
    assert abs(r.score - 50) < abs(raw - 50)        # 점수가 50쪽으로 수축
    assert r.divergence_note and "수축" in r.divergence_note


def test_insufficient_components_lowers_confidence_and_shrinks():
    # 변동성만(1개) — MIN_COMPONENTS 미만
    r = M.compute_region_score("US", pd.DataFrame(columns=["close"]), 12.0, {}, _conn())
    assert r.confidence == "하"
    assert len(r.components["subscores"]) < M.MS_MIN_COMPONENTS


def test_direction_thresholds():
    r = M.compute_region_score("US", _bench(0.0005), 18.0,
                               {"FEDFUNDS": (4.5, 4.5), "DXY": (103, 103)}, _conn())
    assert r.direction in ("강세", "중립", "약세")
    assert 0 <= r.score <= 100


# ── 베타 경로 관찰 ───────────────────────────────────────────────

def test_market_beta_note_bear_high_beta():
    note = _market_beta_note(38, "약세", 1.5)
    assert note and "낙폭" in note
    for bad in ("줄이", "매도", "사세요", "팔"):
        assert bad not in note


def test_market_beta_note_bull_high_beta_and_low_beta():
    assert "탄력" in _market_beta_note(72, "강세", 1.5)
    assert "둔감" in _market_beta_note(50, "중립", 0.5)


def test_market_beta_note_none_when_unremarkable_or_missing():
    assert _market_beta_note(50, "중립", 1.0) is None   # 중립·평범한 베타
    assert _market_beta_note(None, "강세", 1.5) is None
    assert _market_beta_note(60, "강세", None) is None
