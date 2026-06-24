"""
tests/test_ingest_kr_timeout.py — KR 수집 외부 호출 하드 타임아웃 핫픽스 검증

배경: KR 수집 외부 호출에 timeout이 없어 무응답 시 무한 대기(06시 split 90분 timeout 잘림).
- #49: pykrx OHLCV(`_pykrx_ohlcv`)에 timeout 적용 → OHLCV는 막힘.
- 그래도 또 잘림. 실제 행 지점은 dart-fss 회사목록 로드("Loading Stock Market Information",
  `dart.get_corp_list`)와 `extract_fs` — pykrx가 아닌 DART였다. 이 파일은 pykrx + DART
  모든 진입점에 timeout이 걸리고, 무응답 시 종목 단위로 건너뛰고 진행하는지 고정한다.
외부 네트워크 없이 mock으로 검증.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pandas as pd
import pytest

import src.ingest_kr as KR
from src.external_timeout import ExternalCallTimeout


@pytest.fixture(autouse=True)
def _reset_corp_cache():
    # 모듈 전역 corp_list 캐시가 테스트 간 누수되지 않게 초기화
    KR._reset_corp_list_cache()
    yield
    KR._reset_corp_list_cache()


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


# ── DART(dart-fss) 진입점 타임아웃: 실제 06시 행 지점 ─────────────────────────

def test_dart_get_corp_list_hard_timeout_and_failure_cached(monkeypatch):
    # dart.get_corp_list(회사목록 로드)가 무응답이면 타임아웃으로 끊기고,
    # 실패는 캐시되어 다음 종목에서 느린 로더를 다시 호출하지 않는다(재행 방지).
    calls = {"n": 0}

    def _hang_get_corp_list():
        calls["n"] += 1
        time.sleep(5)
        return object()

    fake_dart = SimpleNamespace(get_corp_list=_hang_get_corp_list)
    monkeypatch.setattr(KR, "DART_HTTP_TIMEOUT_S", 0.1)

    with pytest.raises(ExternalCallTimeout):
        KR._get_corp_list_bounded(fake_dart)
    # 두 번째 종목 — 캐시된 실패로 즉시 차단(느린 로더 재호출 없음)
    with pytest.raises(ExternalCallTimeout):
        KR._get_corp_list_bounded(fake_dart)

    assert calls["n"] == 1  # 느린 get_corp_list는 단 1회만 시도됨


def test_dart_get_corp_list_success_cached(monkeypatch):
    # 성공 시 결과를 캐시해 종목마다 재로드하지 않는다.
    calls = {"n": 0}
    sentinel = object()

    def _ok_get_corp_list():
        calls["n"] += 1
        return sentinel

    fake_dart = SimpleNamespace(get_corp_list=_ok_get_corp_list)
    assert KR._get_corp_list_bounded(fake_dart) is sentinel
    assert KR._get_corp_list_bounded(fake_dart) is sentinel
    assert calls["n"] == 1


def test_dart_extract_fs_hard_timeout_raises(monkeypatch):
    # 종목별 재무 추출(extract_fs)이 무응답이면 타임아웃으로 끊긴다.
    monkeypatch.setattr(KR, "DART_HTTP_TIMEOUT_S", 0.1)
    # 재시도 backoff 대기는 생략(원본 Retrying 객체의 sleep을 무력화 — 타임아웃 동작만 검증)
    monkeypatch.setattr(KR._dart_extract_fs.retry, "sleep", lambda *_a: None)

    class _Corp:
        corp_code = "00164779"

        def extract_fs(self, **_k):
            time.sleep(5)
            return object()

    with pytest.raises(ExternalCallTimeout):
        KR._dart_extract_fs(_Corp(), bgn_de="20220101", separate=False, report_tp="annual")


def test_run_kr_ingest_continues_when_dart_corp_list_hangs(monkeypatch):
    # 실제 시나리오: OHLCV는 성공하나 DART 회사목록 로드가 타임아웃 → 재무는 전 종목 실패하되
    # 가격은 정상 수집되고 루프가 끝까지 진행(종목 단위 격리).
    monkeypatch.setattr(KR, "_pykrx_ohlcv", lambda code, fromdate, todate: _ohlcv_df())
    monkeypatch.setattr(KR, "_get_dart_api_key", lambda: "fake-key")
    monkeypatch.setattr("dart_fss.set_api_key", lambda **_k: None)

    def _corp_list_timeout(_dart):
        raise ExternalCallTimeout("DART 회사목록 로드 타임아웃")

    monkeypatch.setattr(KR, "_get_corp_list_bounded", _corp_list_timeout)
    monkeypatch.setattr(KR, "fetch_kr_valuation_analyst", lambda ticker: (None, None))

    result = KR.run_kr_ingest(["000660.KS", "005930.KS"])

    # 가격은 두 종목 모두 정상 수집
    assert len(result["prices"]["000660.KS"]) == 1
    assert len(result["prices"]["005930.KS"]) == 1
    # 재무는 두 종목 모두 fundamentals 단계 에러로 기록(전체 중단 없음)
    fund_errs = {e["ticker"] for e in result["errors"] if e.get("step") == "fundamentals"}
    assert fund_errs == {"000660.KS", "005930.KS"}


def test_bounded_transparent_on_fast_success():
    # 빠른 호출은 그대로 반환(래퍼가 정상 경로 행위를 바꾸지 않음).
    assert KR._bounded("x", lambda: 42, 5.0) == 42
