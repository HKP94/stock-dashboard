"""PR-B: atr14 저장 배선 회귀 가드.

atr14는 계산·스키마·upsert가 전부 배선돼 있었는데도 DB가 26/26 NULL이었다.
원인은 지표 입력 로더가 close/volume만 SELECT해서 compute_indicators의 ATR 분기가
항상 else(nan)로 떨어진 것 — #90 ATR 손절 폴백이 조용히 죽어 있었다.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from src.compute_indicators import compute_indicators

ROOT = Path(__file__).resolve().parents[1]

# 지표 계산 입력을 만드는 로더들 — 전부 high/low를 실어야 ATR이 산다.
_LOADER_SITES = (
    "src/compute_indicators.py",
    "src/pipeline_analysis.py",
    "src/run_pipeline.py",
)


def _price_frame(n: int = 260, with_hl: bool = True) -> pd.DataFrame:
    idx = pd.bdate_range("2026-01-01", periods=n)
    close = pd.Series(np.linspace(100, 140, n), index=idx)
    data = {"close": close, "volume": pd.Series(np.full(n, 1_000_000.0), index=idx)}
    if with_hl:
        data["high"] = close * 1.02
        data["low"] = close * 0.98
    return pd.DataFrame(data)


def test_atr14_computed_when_high_low_present():
    rows = compute_indicators("TEST", _price_frame())
    atrs = [r.atr14 for r in rows if r.atr14 is not None]
    assert atrs, "high/low가 있으면 atr14가 나와야 한다"
    assert all(a > 0 for a in atrs)


def test_atr14_none_without_high_low():
    """입력에 high/low가 없으면 None — 이게 DB 전량 NULL의 정체였다."""
    rows = compute_indicators("TEST", _price_frame(with_hl=False))
    assert all(r.atr14 is None for r in rows)


def test_indicator_loaders_select_high_low():
    """로더 SQL이 high/low를 빼먹으면 계산은 멀쩡한데 값만 조용히 사라진다."""
    for rel in _LOADER_SITES:
        text = (ROOT / rel).read_text()
        selects = re.findall(r"SELECT\s+date,[^\"']*?FROM prices_daily", text, re.I | re.S)
        assert selects, f"{rel}: prices_daily 로더 SQL을 찾지 못함"
        for sql in selects:
            flat = " ".join(sql.split())
            assert "high" in flat and "low" in flat, f"{rel}: high/low 누락 → atr14가 NULL이 된다 ({flat})"
