"""
tests/test_ingest_kr_timeout.py — pykrx/KRX 호출 하드 타임아웃 핫픽스 검증

배경: ingest_kr의 pykrx 호출에 timeout이 없어 KRX 무응답 시 무한 대기(06시 split 90분 timeout 잘림).
이 테스트는 ① 무응답 종목이 timeout으로 끊기는지 ② 그 종목만 건너뛰고 다음 종목이 진행되는지
③ 정상 종목 파싱은 그대로인지를 고정한다. 외부 네트워크 없이 mock으로 검증.
"""

from __future__ import annotations

import time

import pandas as pd
import pytest

import src.ingest_kr as KR
from src.external_timeout import ExternalCallTimeout


def _ohlcv_df() -> pd.DataFrame:
    return pd.DataFrame(
        {"시가": [100.0], "고가": [110.0], "저가": [95.0], "종가": [105.0], "거래량": [1000]},
        index=pd.to_datetime(["2026-06-23"]),
    )


def test_pykrx_ohlcv_hard_timeout_raises(monkeypatch):
    # KRX 호출이 무응답(sleep)이면 하드 타임아웃 후 ExternalCallTimeout으로 끊긴다.
    import pykrx.stock as pykrx_stock

    def _hang(*_a, **_k):
        time.sleep(5)
        return pd.DataFrame()

    monkeypatch.setattr(pykrx_stock, "get_market_ohlcv_by_date", _hang)
    monkeypatch.setattr(KR, "KRX_HTTP_TIMEOUT_S", 0.1)
    # 재시도 backoff 대기는 테스트에서 생략(타임아웃 동작만 검증)
    monkeypatch.setattr(KR._pykrx_ohlcv.retry, "sleep", lambda *_a: None)

    with pytest.raises(ExternalCallTimeout):
        KR._pykrx_ohlcv("005930", "20260101", "20260623")


def test_fetch_kr_prices_normal_path_unchanged(monkeypatch):
    # 정상 응답은 기존과 동일하게 PriceDailyRow로 표준화된다(행위 보존).
    monkeypatch.setattr(KR, "_pykrx_ohlcv", lambda code, fromdate, todate: _ohlcv_df())

    rows = KR.fetch_kr_prices("005930.KS")

    assert len(rows) == 1
    r = rows[0]
    assert r.ticker == "005930.KS"
    assert r.close == 105.0
    assert r.open == 100.0 and r.high == 110.0 and r.low == 95.0
    assert r.volume == 1000
    assert r.source == "pykrx"
    assert r.date.isoformat() == "2026-06-23"


def test_run_kr_ingest_skips_timed_out_ticker_and_continues(monkeypatch):
    # 한 종목이 타임아웃이어도 그 종목만 건너뛰고 errors 기록 + 다음 종목 정상 수집(종목 단위 격리).
    def _by_code(code, fromdate, todate):
        if code == "000660":
            raise ExternalCallTimeout("KRX timed out")
        return _ohlcv_df()

    monkeypatch.setattr(KR, "_pykrx_ohlcv", _by_code)
    # 재무·밸류/컨센서스는 네트워크라 격리(가격 격리 동작만 검증)
    monkeypatch.setattr(KR, "fetch_kr_fundamentals", lambda ticker: [])
    monkeypatch.setattr(KR, "fetch_kr_valuation_analyst", lambda ticker: (None, None))

    result = KR.run_kr_ingest(["000660.KS", "005930.KS"])

    # 정상 종목은 수집됨
    assert len(result["prices"].get("005930.KS", [])) == 1
    # 타임아웃 종목은 prices에 없고 errors에 price 단계로 기록됨
    assert "000660.KS" not in result["prices"]
    price_errs = [e for e in result["errors"] if e.get("ticker") == "000660.KS" and e.get("step") == "price"]
    assert len(price_errs) == 1
    assert "timed out" in price_errs[0]["error"].lower() or "timeout" in price_errs[0]["error"].lower()
