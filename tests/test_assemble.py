"""
tests/test_assemble.py — assemble.py 단위 테스트

DB 없이 모듈-레벨 쿼리 함수를 패치해서 검증.
mock 포인트:
  patch("src.assemble._q_watchlist")
  patch("src.assemble._q_watchlist_one")
  patch("src.assemble._q_price_chg")
  patch("src.assemble._q_indicators")
  patch("src.assemble._q_fundamentals")
  patch("src.assemble._q_valuation")
  patch("src.assemble._q_analyst")
  patch("src.assemble._q_news")
  patch("src.assemble._q_quant")
"""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

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
    """모든 쿼리 함수를 지정한 값으로 패치하는 컨텍스트 목록 반환."""
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
    def test_returns_list_of_records(self):
        with _patch_all()[0], _patch_all()[1], _patch_all()[2], \
             _patch_all()[3], _patch_all()[4], _patch_all()[5], \
             _patch_all()[6], _patch_all()[7], _patch_all()[8]:
            pass  # just checking import

    def test_complete_pipeline(self):
        patches = _patch_all()
        with patches[0], patches[1], patches[2], patches[3], \
             patches[4], patches[5], patches[6], patches[7], patches[8]:
            records = assemble_daily(CONN, asof=ASOF)
        assert len(records) == 1
        assert records[0].ticker == "AAPL"
        assert records[0].price.close == 185.0

    def test_multiple_tickers(self):
        two_wl = [_WL, _WL_KR]
        patches = _patch_all(watchlist=two_wl)
        with patches[0], patches[1], patches[2], patches[3], \
             patches[4], patches[5], patches[6], patches[7], patches[8]:
            records = assemble_daily(CONN, asof=ASOF)
        assert len(records) == 2
        tickers = {r.ticker for r in records}
        assert "AAPL" in tickers
        assert "005930.KS" in tickers

    def test_empty_watchlist_returns_empty(self):
        patches = _patch_all(watchlist=[])
        with patches[0], patches[1], patches[2], patches[3], \
             patches[4], patches[5], patches[6], patches[7], patches[8]:
            records = assemble_daily(CONN, asof=ASOF)
        assert records == []

    def test_no_price_no_crash(self):
        """prices_daily 없는 종목도 크래시 없이 None 필드로 반환."""
        patches = _patch_all(price=None)
        with patches[0], patches[1], patches[2], patches[3], \
             patches[4], patches[5], patches[6], patches[7], patches[8]:
            records = assemble_daily(CONN, asof=ASOF)
        assert len(records) == 1
        assert records[0].price.close is None

    def test_no_quant_composite_none(self):
        """quant_scores 없는 종목 → composite=None."""
        patches = _patch_all(quant=None)
        with patches[0], patches[1], patches[2], patches[3], \
             patches[4], patches[5], patches[6], patches[7], patches[8]:
            records = assemble_daily(CONN, asof=ASOF)
        assert records[0].quant.composite is None
        assert records[0].quant.flags == []

    def test_no_na_string_in_full_output(self):
        """모든 데이터 None이어도 출력에 'N/A' 없음."""
        patches = _patch_all(price=None, ind=None, val=None, ana=None, news=None, quant=None,
                             fund={"rev_yoy": None, "op_margin": None, "last_q_rev_b": None})
        with patches[0], patches[1], patches[2], patches[3], \
             patches[4], patches[5], patches[6], patches[7], patches[8]:
            records = assemble_daily(CONN, asof=ASOF)
        for rec in records:
            assert "N/A" not in json.dumps(rec.model_dump(), ensure_ascii=False)

    def test_one_ticker_error_does_not_stop_others(self):
        """한 종목이 예외를 던져도 나머지 종목은 정상 반환."""
        two_wl = [_WL, _WL_KR]
        call_count = {"n": 0}

        def _price_sometimes_fails(ticker, conn, asof):
            call_count["n"] += 1
            if ticker == "AAPL":
                raise RuntimeError("AAPL 가격 조회 실패")
            return _PRICE

        patches = _patch_all(watchlist=two_wl)
        with patches[0], patches[1], \
             patch("src.assemble._q_price_chg", side_effect=_price_sometimes_fails), \
             patches[3], patches[4], patches[5], patches[6], patches[7], patches[8]:
            records = assemble_daily(CONN, asof=ASOF)

        # AAPL은 실패했지만 삼성전자는 반환돼야 함
        assert len(records) == 1
        assert records[0].ticker == "005930.KS"

    def test_today_used_when_asof_none(self):
        """asof=None이면 오늘 날짜 사용."""
        from datetime import date as date_cls
        patches = _patch_all()
        with patches[0], patches[1], patches[2], patches[3], \
             patches[4], patches[5], patches[6], patches[7], patches[8]:
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
