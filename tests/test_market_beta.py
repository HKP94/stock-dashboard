"""
tests/test_market_beta.py — 신규-A1 시장 베타·상관(결정론)

- 공식(beta=cov/var, corr) 정확성
- 기간(window)·최소관측(min_obs)·결측·var0 → None
- 벤치마크 매핑(KR ^KS11 / 코스닥 ^KQ11 / US ^GSPC, env KOSDAQ_TICKERS 보강)
- composite에 베타가 섞이지 않음(3축/합산 경계)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.compute_quant import (
    BETA_MIN_OBS,
    _kosdaq_codes,
    _market_benchmark,
    compute_beta_corr,
)


def _series(returns: list[float], start=100.0) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(returns) + 1, freq="D")
    closes = [start]
    for r in returns:
        closes.append(closes[-1] * (1 + r))
    return pd.DataFrame({"close": closes}, index=idx)


def test_beta_exact_scaling():
    rng = np.random.RandomState(1)
    m = rng.normal(0, 0.01, 200).tolist()
    s = [x * 1.5 for x in m]            # 종목 = 1.5 × 시장
    beta, corr = compute_beta_corr(_series(s), _series(m))
    assert abs(beta - 1.5) < 1e-6
    assert abs(corr - 1.0) < 1e-6


def test_beta_none_when_too_few_common_obs():
    short = [0.01] * (BETA_MIN_OBS - 5)
    assert compute_beta_corr(_series(short), _series(short)) == (None, None)


def test_beta_none_when_market_flat_var_zero():
    rng = np.random.RandomState(2)
    s = rng.normal(0, 0.01, 120).tolist()
    flat = [0.0] * 120                  # 지수 무변동 → var(x)=0
    assert compute_beta_corr(_series(s), _series(flat)) == (None, None)


def test_beta_none_on_empty_inputs():
    assert compute_beta_corr(pd.DataFrame(columns=["close"]), _series([0.01] * 80)) == (None, None)
    assert compute_beta_corr(_series([0.01] * 80), None) == (None, None)


def test_beta_window_limits_to_recent_observations(monkeypatch):
    # window=80이면 최근 80개 수익률만 사용(앞쪽 다른 베타 구간 무시)
    rng = np.random.RandomState(3)
    m = rng.normal(0, 0.01, 200).tolist()
    s = [x * 0.5 for x in m[:120]] + [x * 2.0 for x in m[120:]]   # 뒤쪽 베타 2.0
    beta, _c = compute_beta_corr(_series(s), _series(m), window=70, min_obs=30)
    assert abs(beta - 2.0) < 1e-6


def test_benchmark_mapping():
    assert _market_benchmark("AAPL", "US") == "^GSPC"
    assert _market_benchmark("005930.KS", "KR") == "^KS11"     # 코스피 기본
    assert _market_benchmark("059090.KS", "KR") == "^KQ11"     # 미코(코스닥 default)
    assert _market_benchmark("338220.KS", "KR") == "^KQ11"     # 뷰노(코스닥)


def test_kosdaq_env_override(monkeypatch):
    monkeypatch.setenv("KOSDAQ_TICKERS", "111111.KS, 222222")
    codes = _kosdaq_codes()
    assert "111111" in codes and "222222" in codes
    assert _market_benchmark("111111.KS", "KR") == "^KQ11"
    # 기본 코스닥 종목도 유지
    assert "059090" in codes


def test_beta_not_in_composite():
    # composite은 5팩터 가중합만 — beta/market_corr가 섞이지 않음(3축 비합산 경계).
    import inspect
    import src.compute_quant as q
    src = inspect.getsource(q.compute_quant_universe)
    composite_block = src[src.index("composite = ("):src.index("composite = (") + 400]
    assert "beta" not in composite_block and "market_corr" not in composite_block
