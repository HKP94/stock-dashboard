"""
tests/test_decimal_boundary.py — DB NUMERIC(Decimal) 경계 회귀 테스트

근본 버그: psycopg3가 NUMERIC을 decimal.Decimal로 반환 → compute_indicators(Decimal/float),
compute_quant(np.log(Decimal)), JSON 직렬화가 전부 실패해 indicators_daily=0, quant_scores=0.

기존 테스트는 float mock이라 이 버그를 못 잡았다. 여기서는 prices/valuation을
명시적으로 Decimal로 mock해 크래시 없이 float 결과가 나오는지 검증한다.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from src.compute_indicators import MIN_BARS, compute_indicators
from src.compute_quant import _compute_idio_vol, _momentum_raw, compute_quant_universe


# ──────────────────────────────────────────────────────────────
# 헬퍼: Decimal 종가 DataFrame
# ──────────────────────────────────────────────────────────────

def _decimal_price_df(n: int, start: float = 100.0, step: float = 0.5) -> pd.DataFrame:
    """close/volume이 Decimal/int인 object-dtype DataFrame (DB Decimal 재현)."""
    idx = pd.date_range(end="2026-06-10", periods=n, freq="B")
    closes = [Decimal(str(round(start + i * step, 2))) for i in range(n)]
    vols = [Decimal(str(1_000_000 + i)) for i in range(n)]
    df = pd.DataFrame({"close": closes, "volume": vols}, index=idx)
    # object dtype 보장 (Decimal 섞임 재현)
    assert df["close"].dtype == object
    return df


# ──────────────────────────────────────────────────────────────
# compute_indicators: Decimal 입력
# ──────────────────────────────────────────────────────────────

class TestIndicatorsDecimal:
    def test_no_crash_and_float_output(self):
        df = _decimal_price_df(MIN_BARS + 30)
        rows = compute_indicators("TEST", df)
        assert len(rows) > 0
        last = rows[-1]
        # 모든 수치 필드가 float(or None) — Decimal 아님
        for field in ("sma20", "sma50", "sma200", "rsi14", "disparity20", "slope50", "slope200"):
            val = getattr(last, field)
            assert val is None or isinstance(val, float), f"{field}={val!r} not float"

    def test_disparity_computed_with_decimal_close(self):
        df = _decimal_price_df(MIN_BARS + 30)
        rows = compute_indicators("TEST", df)
        # 이격도(close/sma20)가 Decimal/float 혼용 없이 계산됨
        assert any(r.disparity20 is not None for r in rows)


# ──────────────────────────────────────────────────────────────
# compute_quant 내부: Decimal np.log 경로
# ──────────────────────────────────────────────────────────────

class TestQuantDecimalInternals:
    def test_momentum_raw_decimal_no_crash(self):
        df = _decimal_price_df(300)
        flags: list[str] = []
        # _momentum_raw는 .astype(float)로 캐스팅 → Decimal이어도 안전해야 함
        raw = _momentum_raw(df, "TEST", flags)
        assert raw is not None
        for k in ("m_1m", "m_3m", "m_6m", "m_12m"):
            assert raw[k] is None or isinstance(raw[k], float)

    def test_idio_vol_decimal_no_crash(self):
        price_df = _decimal_price_df(60)
        market_df = pd.DataFrame()  # kospi 없음 → 단순 표준편차 경로
        v = _compute_idio_vol(price_df, market_df)
        assert v is None or isinstance(v, float)


# ──────────────────────────────────────────────────────────────
# compute_quant_universe: 전 구간 Decimal mock
# ──────────────────────────────────────────────────────────────

class TestQuantUniverseDecimal:
    def test_universe_with_decimal_fetches(self):
        conn = MagicMock()
        df = _decimal_price_df(300)
        decimal_val = {
            "per_f": Decimal("15.5"), "per_t": Decimal("16.0"),
            "pbr": Decimal("1.5"), "ev_ebitda": Decimal("12.0"),
            "roe": Decimal("0.15"), "roa": Decimal("0.08"),
            "debt_ratio": Decimal("80.0"), "rev_growth": Decimal("0.05"),
        }
        decimal_fund = [{
            "period_end": date(2025, 12, 31), "revenue": Decimal("1000"),
            "op_income": Decimal("100"), "op_margin": Decimal("0.10"),
            "net_income": Decimal("80"),
        }, {
            "period_end": date(2024, 12, 31), "revenue": Decimal("950"),
            "op_income": Decimal("90"), "op_margin": Decimal("0.095"),
            "net_income": Decimal("70"),
        }]

        with patch("src.compute_quant._fetch_market_history", return_value=pd.DataFrame()), \
             patch("src.compute_quant._fetch_prices", return_value=df), \
             patch("src.compute_quant._fetch_ticker_market", return_value="US"), \
             patch("src.compute_quant.piotroski_fscore", return_value=(6, [])), \
             patch("src.compute_quant._fetch_valuation_two", return_value=[decimal_val]), \
             patch("src.compute_quant._fetch_fundamentals_annual", return_value=decimal_fund), \
             patch("src.compute_quant._fetch_analyst_records", return_value=(None, None)), \
             patch("src.compute_quant._fetch_sentiment_score", return_value=Decimal("0.3")):
            rows = compute_quant_universe(["AAPL", "MSFT"], conn)

        assert len(rows) == 2
        for r in rows:
            # composite/팩터가 float(or None) — Decimal 아님, 직렬화 가능
            for field in ("momentum", "value", "quality", "growth", "sentiment", "composite"):
                val = getattr(r, field)
                assert val is None or isinstance(val, float), f"{r.ticker}.{field}={val!r}"
            # flags JSON 직렬화 가능
            json.dumps(r.flags, ensure_ascii=False)


# ──────────────────────────────────────────────────────────────
# JSON 직렬화 방어 (Decimal default=str)
# ──────────────────────────────────────────────────────────────

class TestJsonDecimalSafe:
    def test_market_prompt_decimal_safe(self):
        from src.enrich_gemini import _build_market_prompt
        metrics = {"KOSPI": Decimal("2700.5"), "VIX": Decimal("15.2")}
        rollup = {"긍정": 3, "중립": 2}
        # default=str 덕분에 Decimal이 섞여도 죽지 않아야 함
        prompt = _build_market_prompt(metrics, rollup)
        assert "2700.5" in prompt
        assert "KOSPI" in prompt
