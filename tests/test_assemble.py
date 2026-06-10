"""
tests/test_assemble.py — assemble.py 단위 테스트

DB 없이 모듈-레벨 쿼리 함수를 패치해서 검증.
mock 포인트:
  assemble_one (단일 종목, per-ticker 쿼리):
    _q_watchlist_one / _q_price_chg / _q_indicators / _q_fundamentals
    _q_valuation / _q_analyst / _q_news / _q_quant
  assemble_daily (유니버스, bulk 쿼리):
    _q_watchlist + _bulk_prices / _bulk_indicators / _bulk_fundamentals
    _bulk_valuation / _bulk_analyst / _bulk_news / _bulk_quant
    (bulk 함수는 {ticker: value} dict 반환)
"""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

import src.assemble as assemble_mod
from src.assemble import (
    _build_record,
    assemble_daily,
    assemble_one,
)
from src.schemas import StockDailyRecord

# ── 픽스처 ────────────────────────────────────────────────────

ASOF = date(2026, 6, 9)
CONN = MagicMock()

_WL = {"ticker": "AAPL", "name": "애플", "market": "US", "sector": "Tech", "is_holding": False}
_WL_KR = {"ticker": "005930.KS", "name": "삼성전자", "market": "KR", "sector": "반도체", "is_holding": True}

_PRICE = {"close": 185.0, "chg_pct": 1.5}
_IND = {"rsi14": 58.3, "disparity20": 101.4, "is_aligned": True, "slope50": 0.002}
_FUND = {"rev_yoy": 0.11, "op_margin": 0.19, "last_q_rev_b": 95.0}
_VAL = {"per_f": 28.5, "per_t": 30.0, "pbr": 4.2, "roe": 0.15, "roa": 0.08,
        "ev_ebitda": 20.0, "debt_ratio": 180.0, "rev_growth": 0.05}
_ANA = {"rating": "BUY", "target_price": 200.0, "upside": 0.081}
_NEWS = {"sentiment": "긍정", "sentiment_score": 0.4, "summary_md": "- 좋은 뉴스", "based_on": "recent"}
_QUANT = {"composite": 71.0, "momentum": 78.0, "value": 55.0, "quality": 64.0,
          "growth": 70.0, "sentiment": 66.0, "flags": ["RSI 양호"]}


def _patch_all(price=_PRICE, ind=_IND, fund=_FUND, val=_VAL,
               ana=_ANA, news=_NEWS, quant=_QUANT, watchlist=None):
    """assemble_one용: per-ticker _q_* 함수를 단일 값으로 패치."""
    wl_list = [_WL] if watchlist is None else watchlist  # [] 처리: None과 구분
    return [
        patch("src.assemble._q_watchlist", return_value=wl_list),
        patch("src.assemble._q_watchlist_one", return_value=_WL),
        patch("src.assemble._q_price_chg", return_value=price),
        patch("src.assemble._q_indicators", return_value=ind),
        patch("src.assemble._q_fundamentals", return_value=fund),
        patch("src.assemble._q_valuation", return_value=val),
        patch("src.assemble._q_analyst", return_value=ana),
        patch("src.assemble._q_news", return_value=news),
        patch("src.assemble._q_quant", return_value=quant),
    ]


def _patch_bulk(price=_PRICE, ind=_IND, fund=_FUND, val=_VAL,
                ana=_ANA, news=_NEWS, quant=_QUANT, watchlist=None):
    """assemble_daily용: _q_watchlist + bulk 함수들을 {ticker: value} dict로 패치."""
    wl_list = [_WL] if watchlist is None else watchlist
    tickers = [w["ticker"] for w in wl_list]
    return [
        patch("src.assemble._q_watchlist", return_value=wl_list),
        patch("src.assemble._bulk_prices", return_value={t: price for t in tickers}),
        patch("src.assemble._bulk_indicators", return_value={t: ind for t in tickers}),
        patch("src.assemble._bulk_fundamentals", return_value={t: fund for t in tickers}),
        patch("src.assemble._bulk_valuation", return_value={t: val for t in tickers}),
        patch("src.assemble._bulk_analyst", return_value={t: ana for t in tickers}),
        patch("src.assemble._bulk_news", return_value={t: news for t in tickers}),
        patch("src.assemble._bulk_quant", return_value={t: quant for t in tickers}),
    ]


# ──────────────────────────────────────────────────────────────
# _build_record 단위 테스트
# ──────────────────────────────────────────────────────────────

class TestBuildRecord:
    def test_complete_data_fills_all_fields(self):
        rec = _build_record(_WL, _PRICE, _IND, _FUND, _VAL, _ANA, _NEWS, _QUANT)
        assert isinstance(rec, StockDailyRecord)
        assert rec.ticker == "AAPL"
        assert rec.name == "애플"
        assert rec.market == "US"
        assert rec.is_holding is False

        # PriceView
        assert rec.price.close == 185.0
        assert rec.price.chg_pct == 1.5
        assert rec.price.rsi14 == 58.3
        assert rec.price.disparity20 == 101.4
        assert rec.price.is_aligned is True

        # FundamentalsView
        assert rec.fundamentals.rev_yoy == 0.11
        assert rec.fundamentals.op_margin == 0.19
        assert rec.fundamentals.last_q_rev_b == 95.0

        # ValuationView
        assert rec.valuation.per_f == 28.5
        assert rec.valuation.pbr == 4.2
        assert rec.valuation.roe == 0.15

        # AnalystView (target_price → target)
        assert rec.analyst.rating == "BUY"
        assert rec.analyst.target == 200.0
        assert rec.analyst.upside == 0.081

        # NewsView
        assert rec.news.sentiment == "긍정"
        assert rec.news.score == 0.4
        assert rec.news.based_on == "recent"

        # QuantView
        assert rec.quant.composite == 71.0
        assert rec.quant.momentum == 78.0
        assert "RSI 양호" in rec.quant.flags

    def test_no_price_sets_price_fields_none(self):
        rec = _build_record(_WL, None, _IND, _FUND, _VAL, _ANA, _NEWS, _QUANT)
        assert rec.price.close is None
        assert rec.price.chg_pct is None
        # indicators는 별도이므로 채워져 있어야 함
        assert rec.price.rsi14 == 58.3

    def test_no_indicators_sets_ind_fields_none(self):
        rec = _build_record(_WL, _PRICE, None, _FUND, _VAL, _ANA, _NEWS, _QUANT)
        assert rec.price.rsi14 is None
        assert rec.price.is_aligned is None
        # price 자체는 정상
        assert rec.price.close == 185.0

    def test_no_quant_sets_composite_none(self):
        rec = _build_record(_WL, _PRICE, _IND, _FUND, _VAL, _ANA, _NEWS, None)
        assert rec.quant.composite is None
        assert rec.quant.momentum is None
        assert rec.quant.flags == []
        # 나머지 필드는 정상
        assert rec.price.close == 185.0
        assert rec.news.sentiment == "긍정"

    def test_no_news_sets_news_fields_none(self):
        rec = _build_record(_WL, _PRICE, _IND, _FUND, _VAL, _ANA, None, _QUANT)
        assert rec.news.sentiment is None
        assert rec.news.score is None
        assert rec.news.summary_md is None

    def test_no_analyst_sets_analyst_fields_none(self):
        rec = _build_record(_WL, _PRICE, _IND, _FUND, _VAL, None, _NEWS, _QUANT)
        assert rec.analyst.rating is None
        assert rec.analyst.target is None
        assert rec.analyst.upside is None

    def test_no_valuation_sets_val_fields_none(self):
        rec = _build_record(_WL, _PRICE, _IND, _FUND, None, _ANA, _NEWS, _QUANT)
        assert rec.valuation.per_f is None
        assert rec.valuation.pbr is None
        assert rec.valuation.roe is None

    def test_per_f_fallback_to_per_t(self):
        val_no_f = {**_VAL, "per_f": None}
        rec = _build_record(_WL, _PRICE, _IND, _FUND, val_no_f, _ANA, _NEWS, _QUANT)
        assert rec.valuation.per_f == 30.0  # per_t 값

    def test_invalid_sentiment_becomes_none(self):
        bad_news = {**_NEWS, "sentiment": "데이터 없음"}
        rec = _build_record(_WL, _PRICE, _IND, _FUND, _VAL, _ANA, bad_news, _QUANT)
        assert rec.news.sentiment is None

    def test_invalid_based_on_becomes_none(self):
        bad_news = {**_NEWS, "based_on": "unknown"}
        rec = _build_record(_WL, _PRICE, _IND, _FUND, _VAL, _ANA, bad_news, _QUANT)
        assert rec.news.based_on is None

    def test_flags_jsonb_string_parsed(self):
        """quant.flags가 JSON 문자열이면 파싱."""
        q = {**_QUANT, "flags": json.dumps(["플래그1", "플래그2"])}
        rec = _build_record(_WL, _PRICE, _IND, _FUND, _VAL, _ANA, _NEWS, q)
        assert rec.quant.flags == ["플래그1", "플래그2"]

    def test_flags_none_becomes_empty_list(self):
        q = {**_QUANT, "flags": None}
        rec = _build_record(_WL, _PRICE, _IND, _FUND, _VAL, _ANA, _NEWS, q)
        assert rec.quant.flags == []

    def test_is_holding_true(self):
        rec = _build_record(_WL_KR, _PRICE, _IND, _FUND, _VAL, _ANA, _NEWS, _QUANT)
        assert rec.is_holding is True
        assert rec.market == "KR"

    def test_no_na_strings_in_output(self):
        """결측은 None, 문자열 'N/A' 절대 금지."""
        rec = _build_record(_WL, None, None, {"rev_yoy": None, "op_margin": None, "last_q_rev_b": None},
                            None, None, None, None)
        output = rec.model_dump()
        assert "N/A" not in json.dumps(output, ensure_ascii=False)


# ──────────────────────────────────────────────────────────────
# assemble_daily 통합 테스트
# ──────────────────────────────────────────────────────────────

class TestAssembleDaily:
    def test_complete_pipeline(self):
        patches = _patch_bulk()
        with patches[0], patches[1], patches[2], patches[3], \
             patches[4], patches[5], patches[6], patches[7]:
            records = assemble_daily(CONN, asof=ASOF)
        assert len(records) == 1
        assert records[0].ticker == "AAPL"
        assert records[0].price.close == 185.0
        assert records[0].quant.composite == 71.0

    def test_multiple_tickers(self):
        two_wl = [_WL, _WL_KR]
        patches = _patch_bulk(watchlist=two_wl)
        with patches[0], patches[1], patches[2], patches[3], \
             patches[4], patches[5], patches[6], patches[7]:
            records = assemble_daily(CONN, asof=ASOF)
        assert len(records) == 2
        tickers = {r.ticker for r in records}
        assert "AAPL" in tickers
        assert "005930.KS" in tickers

    def test_empty_watchlist_returns_empty(self):
        # watchlist 비면 bulk 함수 호출 없이 즉시 [] 반환
        patches = _patch_bulk(watchlist=[])
        with patches[0], patches[1], patches[2], patches[3], \
             patches[4], patches[5], patches[6], patches[7]:
            records = assemble_daily(CONN, asof=ASOF)
        assert records == []

    def test_no_price_no_crash(self):
        """prices bulk에서 해당 ticker None이어도 크래시 없이 None 필드."""
        patches = _patch_bulk(price=None)
        with patches[0], patches[1], patches[2], patches[3], \
             patches[4], patches[5], patches[6], patches[7]:
            records = assemble_daily(CONN, asof=ASOF)
        assert len(records) == 1
        assert records[0].price.close is None

    def test_no_quant_composite_none(self):
        """quant bulk에서 해당 ticker None → composite=None."""
        patches = _patch_bulk(quant=None)
        with patches[0], patches[1], patches[2], patches[3], \
             patches[4], patches[5], patches[6], patches[7]:
            records = assemble_daily(CONN, asof=ASOF)
        assert records[0].quant.composite is None
        assert records[0].quant.flags == []

    def test_no_na_string_in_full_output(self):
        """모든 데이터 None이어도 출력에 'N/A' 없음."""
        patches = _patch_bulk(price=None, ind=None, val=None, ana=None, news=None, quant=None,
                              fund={"rev_yoy": None, "op_margin": None, "last_q_rev_b": None})
        with patches[0], patches[1], patches[2], patches[3], \
             patches[4], patches[5], patches[6], patches[7]:
            records = assemble_daily(CONN, asof=ASOF)
        for rec in records:
            assert "N/A" not in json.dumps(rec.model_dump(), ensure_ascii=False)

    def test_one_ticker_error_does_not_stop_others(self):
        """한 종목 조립이 예외를 던져도 나머지 종목은 정상 반환 (try/except 격리)."""
        two_wl = [_WL, _WL_KR]
        real_build = assemble_mod._build_record

        def _build_sometimes_fails(*, wl, **kwargs):
            if wl["ticker"] == "AAPL":
                raise RuntimeError("AAPL 조립 실패")
            return real_build(wl=wl, **kwargs)

        patches = _patch_bulk(watchlist=two_wl)
        with patches[0], patches[1], patches[2], patches[3], \
             patches[4], patches[5], patches[6], patches[7], \
             patch("src.assemble._build_record", side_effect=_build_sometimes_fails):
            records = assemble_daily(CONN, asof=ASOF)

        # AAPL은 실패했지만 삼성전자는 반환돼야 함
        assert len(records) == 1
        assert records[0].ticker == "005930.KS"

    def test_today_used_when_asof_none(self):
        """asof=None이면 오늘 날짜 사용."""
        patches = _patch_bulk()
        with patches[0], patches[1], patches[2], patches[3], \
             patches[4], patches[5], patches[6], patches[7]:
            records = assemble_daily(CONN, asof=None)
        assert len(records) == 1


# ──────────────────────────────────────────────────────────────
# assemble_one 테스트
# ──────────────────────────────────────────────────────────────

class TestAssembleOne:
    def test_returns_record_when_in_watchlist(self):
        patches = _patch_all()
        with patches[0], patches[1], patches[2], patches[3], \
             patches[4], patches[5], patches[6], patches[7], patches[8]:
            rec = assemble_one("AAPL", CONN, asof=ASOF)
        assert rec is not None
        assert rec.ticker == "AAPL"

    def test_returns_none_when_not_in_watchlist(self):
        with patch("src.assemble._q_watchlist_one", return_value=None):
            rec = assemble_one("UNKNOWN", CONN, asof=ASOF)
        assert rec is None

    def test_disclaimer_excluded_from_model_dump(self):
        """DISCLAIMER 필드는 model_dump() 출력에서 제외."""
        patches = _patch_all()
        with patches[0], patches[1], patches[2], patches[3], \
             patches[4], patches[5], patches[6], patches[7], patches[8]:
            rec = assemble_one("AAPL", CONN, asof=ASOF)
        d = rec.model_dump()
        assert "DISCLAIMER" not in d


# ──────────────────────────────────────────────────────────────
# Bulk 헬퍼 join 로직 테스트 (가짜 커서로 실제 SQL 결과 처리 검증)
# ──────────────────────────────────────────────────────────────

class _FakeCursor:
    """conn.cursor() 컨텍스트 매니저 흉내. fetchall()로 미리 준 rows 반환."""
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **k):
        return None

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


def _fake_conn(rows):
    conn = MagicMock()
    conn.cursor.return_value = _FakeCursor(rows)
    return conn


_PREV = date(2026, 6, 8)


class TestBulkPrices:
    def test_close_and_chg_pct(self):
        from src.assemble import _bulk_prices
        rows = [
            {"ticker": "AAPL", "date": ASOF, "close": 110.0},
            {"ticker": "AAPL", "date": _PREV, "close": 100.0},
        ]
        out = _bulk_prices(["AAPL"], _fake_conn(rows), ASOF)
        assert out["AAPL"]["close"] == 110.0
        assert out["AAPL"]["chg_pct"] == pytest.approx(10.0)

    def test_latest_not_asof_returns_none(self):
        """가장 최근 행이 asof 당일이 아니면 (휴장) None."""
        from src.assemble import _bulk_prices
        rows = [{"ticker": "AAPL", "date": _PREV, "close": 100.0}]
        out = _bulk_prices(["AAPL"], _fake_conn(rows), ASOF)
        assert out["AAPL"] is None

    def test_single_row_chg_pct_none(self):
        """asof 종가만 있고 전일 없으면 chg_pct=None."""
        from src.assemble import _bulk_prices
        rows = [{"ticker": "AAPL", "date": ASOF, "close": 110.0}]
        out = _bulk_prices(["AAPL"], _fake_conn(rows), ASOF)
        assert out["AAPL"]["close"] == 110.0
        assert out["AAPL"]["chg_pct"] is None

    def test_missing_ticker_is_none(self):
        from src.assemble import _bulk_prices
        out = _bulk_prices(["AAPL", "MSFT"], _fake_conn([]), ASOF)
        assert out["AAPL"] is None and out["MSFT"] is None

    def test_empty_tickers(self):
        from src.assemble import _bulk_prices
        assert _bulk_prices([], _fake_conn([]), ASOF) == {}


class TestBulkFundamentals:
    def test_rev_yoy_and_last_q(self):
        from src.assemble import _bulk_fundamentals
        rows = [
            {"ticker": "AAPL", "period_type": "annual", "period_end": date(2025, 12, 31),
             "revenue": 1100.0, "op_margin": 0.20},
            {"ticker": "AAPL", "period_type": "annual", "period_end": date(2024, 12, 31),
             "revenue": 1000.0, "op_margin": 0.18},
            {"ticker": "AAPL", "period_type": "quarter", "period_end": date(2026, 3, 31),
             "revenue": 3e9, "op_margin": 0.21},
        ]
        out = _bulk_fundamentals(["AAPL"], _fake_conn(rows))
        assert out["AAPL"]["op_margin"] == 0.20         # 최신 연간
        assert out["AAPL"]["rev_yoy"] == pytest.approx(0.10)  # (1100-1000)/1000
        assert out["AAPL"]["last_q_rev_b"] == pytest.approx(3.0)  # 3e9 / 1e9

    def test_no_data_all_none(self):
        from src.assemble import _bulk_fundamentals
        out = _bulk_fundamentals(["AAPL"], _fake_conn([]))
        assert out["AAPL"] == {"rev_yoy": None, "op_margin": None, "last_q_rev_b": None}

    def test_single_annual_no_yoy(self):
        from src.assemble import _bulk_fundamentals
        rows = [
            {"ticker": "AAPL", "period_type": "annual", "period_end": date(2025, 12, 31),
             "revenue": 1100.0, "op_margin": 0.20},
        ]
        out = _bulk_fundamentals(["AAPL"], _fake_conn(rows))
        assert out["AAPL"]["op_margin"] == 0.20
        assert out["AAPL"]["rev_yoy"] is None       # 비교 연도 없음
        assert out["AAPL"]["last_q_rev_b"] is None   # 분기 없음


class TestBulkSimple:
    """indicators/valuation/analyst/news/quant: ticker 키 매핑만 검증."""

    def test_indicators_maps_by_ticker(self):
        from src.assemble import _bulk_indicators
        rows = [{"ticker": "AAPL", "rsi14": 58.0, "disparity20": 101.0,
                 "is_aligned": True, "slope50": 0.002}]
        out = _bulk_indicators(["AAPL", "MSFT"], _fake_conn(rows), ASOF)
        assert out["AAPL"]["rsi14"] == 58.0
        assert out["MSFT"] is None

    def test_valuation_maps_by_ticker(self):
        from src.assemble import _bulk_valuation
        rows = [{"ticker": "AAPL", "per_t": 30.0, "per_f": 28.0, "pbr": 4.0,
                 "ev_ebitda": 20.0, "roe": 0.15, "roa": 0.08,
                 "debt_ratio": 100.0, "rev_growth": 0.05}]
        out = _bulk_valuation(["AAPL"], _fake_conn(rows))
        assert out["AAPL"]["per_f"] == 28.0

    def test_quant_maps_by_ticker(self):
        from src.assemble import _bulk_quant
        rows = [{"ticker": "AAPL", "momentum": 70.0, "value": 50.0, "quality": 60.0,
                 "growth": 65.0, "sentiment": 55.0, "composite": 62.0, "flags": ["x"]}]
        out = _bulk_quant(["AAPL", "MSFT"], _fake_conn(rows), ASOF)
        assert out["AAPL"]["composite"] == 62.0
        assert out["MSFT"] is None
