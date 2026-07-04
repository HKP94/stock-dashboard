"""
test_ingest_kr.py — KR DART 재무 파싱 단위 테스트 (네트워크 없음)

dart-fss 0.4.16 extract_fs() 출력 구조를 합성 DataFrame으로 모사한다.
실제 구조:
  - 2-level MultiIndex 컬럼
  - 메타 컬럼: (긴_재무제표_제목, 'concept_id'|'label_ko'|'label_en'|'class0'..)
  - 데이터 컬럼: ('YYYYMMDD-YYYYMMDD', ('연결재무제표',))  ← 기간범위 + 구분 튜플
  - 행: RangeIndex, 계정명은 'label_ko' 컬럼 값
"""
import datetime as dt

import pandas as pd
import pytest

from src.ingest_kr import _parse_dart_col_date, _parse_fs_rows, _resolve_kr_price_target_date


_TITLE = (
    "[D431410] 단일 포괄손익계산서, 기능별 분류, 세후 - 연결 | "
    "Statement of comprehensive income - Consolidated (Unit: KRW)"
)


def _make_cis_df() -> pd.DataFrame:
    """extract_fs()['cis']와 동일한 구조의 합성 손익계산서."""
    cols = pd.MultiIndex.from_tuples([
        (_TITLE, "concept_id"),
        (_TITLE, "label_ko"),
        (_TITLE, "label_en"),
        (_TITLE, "class0"),
        ("20240101-20241231", ("연결재무제표",)),
        ("20230101-20231231", ("연결재무제표",)),
    ])
    data = [
        ["ifrs-full_Revenue", "매출액", "Revenue", "y", 4_310_141_690_000.0, 3_966_519_720_000.0],
        ["dart_OperatingIncome", "영업이익", "Operating income", "y", 700_000_000_000.0, 650_000_000_000.0],
        ["ifrs-full_ProfitLoss", "당기순이익", "Profit", "y", 500_000_000_000.0, 480_000_000_000.0],
    ]
    return pd.DataFrame(data, columns=cols)


class _FakeFS:
    """dart-fss FinancialStatement의 fs['cis'] 접근만 모사."""
    def __init__(self, mapping):
        self._m = mapping

    def __getitem__(self, key):
        return self._m[key]  # 없는 키는 KeyError → _parse_fs_rows가 처리


def test_parse_period_range_returns_end_date():
    # 'YYYYMMDD-YYYYMMDD' → 종료일
    assert _parse_dart_col_date("20240101-20241231") == dt.date(2024, 12, 31)


def test_parse_single_yyyymmdd():
    assert _parse_dart_col_date("20241231") == dt.date(2024, 12, 31)


def test_parse_fs_rows_extracts_revenue_op_net():
    fs = _FakeFS({"cis": _make_cis_df()})
    rows = _parse_fs_rows("021240.KS", fs, "annual")

    assert len(rows) == 2, "데이터 컬럼 2개(2024, 2023)에서 2행 나와야 함"
    by_year = {r.period_end.year: r for r in rows}

    r24 = by_year[2024]
    assert r24.revenue == pytest.approx(4_310_141_690_000.0)
    assert r24.op_income == pytest.approx(700_000_000_000.0)
    assert r24.net_income == pytest.approx(500_000_000_000.0)
    assert r24.op_margin == pytest.approx(700_000_000_000.0 / 4_310_141_690_000.0)
    assert r24.period_type == "annual"
    assert r24.source == "dart"

    assert by_year[2023].revenue == pytest.approx(3_966_519_720_000.0)


def test_parse_fs_rows_empty_when_no_income_statement():
    fs = _FakeFS({"cis": pd.DataFrame()})
    assert _parse_fs_rows("021240.KS", fs, "annual") == []


# ──────────────────────────────────────────────────────────────
# PR-1: KR 밸류에이션·컨센서스 무료 수집 (네이버 + FnGuide) 파싱 테스트
# ──────────────────────────────────────────────────────────────
from unittest.mock import patch
from datetime import date as _date
from src.ingest_kr import (
    _parse_kr_number,
    _fetch_naver_main,
    _parse_naver_financials,
    fetch_kr_valuation_analyst,
)
from bs4 import BeautifulSoup as _BS

# 네이버 종목 메인 최소 fixture (실제 구조의 핵심 요소만)
# 기업실적분석 표: 연간 3열(2023·2024·2025E) + 분기 2열. 파서는 '추정 아닌 최근 연간'=2024.12를
# 골라야 하므로 ROE/부채/영업이익률의 index1(2024.12)=7.11/45.21/17.44가 채택돼야 한다
# (2025.12는 (E)라 제외, 분기값 3.00/50.0도 제외).
_NAVER_FIN_TABLE = """
<div class="section cop_analysis"><table>
  <thead>
    <tr><th rowspan="2">주요재무정보</th><th colspan="3">최근 연간 실적</th><th colspan="2">최근 분기 실적</th></tr>
    <tr><th>2023.12</th><th>2024.12</th><th>2025.12 (E)</th><th>2025.09</th><th>2025.12 (E)</th></tr>
  </thead>
  <tbody>
    <tr><th>ROE(지배주주)</th><td>10.83</td><td>7.11</td><td>9.99</td><td>3.00</td><td>4.00</td></tr>
    <tr><th>부채비율</th><td>41.59</td><td>45.21</td><td></td><td>50.0</td><td>60.0</td></tr>
    <tr><th>영업이익률</th><td>18.18</td><td>17.44</td><td>20.0</td><td>19.0</td><td>21.0</td></tr>
  </tbody>
</table></div>
"""

_NAVER_HTML = """
<html><body>
  <div class="rate_info"><p class="no_today"><em><span class="blind">248,000</span></em></p></div>
  <table summary="투자정보"><tr><th>PER</th><td><em id="_per">21.53</em></td></tr>
  <tr><th>PBR</th><td><em id="_pbr">1.26</em></td></tr></table>
  <div class="aside_invest_info"><table><tbody>
    <tr><th>투자의견 l 목표주가</th><td><em>4.00</em> 매수 l <em>329,227</em></td></tr>
  </tbody></table></div>
  <div>추정기관수 4.0 목표주가</div>
  __FIN__
</body></html>
""".replace("__FIN__", _NAVER_FIN_TABLE)


class TestParseKrNumber:
    def test_comma(self):
        assert _parse_kr_number("329,227") == 329227.0
    def test_percent(self):
        assert _parse_kr_number("45.21%") == 45.21
    def test_unit_bae_won(self):
        assert _parse_kr_number("21.53배") == 21.53
        assert _parse_kr_number("248,000원") == 248000.0
    def test_negative(self):
        assert _parse_kr_number("-8.4") == -8.4
    def test_blank_dash_na(self):
        assert _parse_kr_number("") is None
        assert _parse_kr_number("-") is None
        assert _parse_kr_number("N/A") is None
        assert _parse_kr_number(None) is None


class TestFetchNaverMain:
    def test_parses_per_pbr_target_rating(self):
        with patch("src.ingest_kr._get_html", return_value=_NAVER_HTML.encode()):
            out = _fetch_naver_main("035420")
        assert out["per_t"] == 21.53
        assert out["pbr"] == 1.26
        assert out["current_price"] == 248000.0
        assert out["target_price"] == 329227.0
        assert out["rating"] == "매수"
        # 같은 페이지 기업실적분석 표에서 ROE/부채/추정기관수도 파싱(FnGuide 대체)
        assert out["roe"] == 7.11
        assert out["debt_ratio"] == 45.21
        assert out["n_analysts"] == 4


class TestParseNaverFinancials:
    def test_picks_most_recent_actual_annual(self):
        # 최근 '실적' 연간(2024.12)을 골라야 함: 2025.12는 (E) 추정, 분기값도 제외.
        soup = _BS(_NAVER_FIN_TABLE, "html.parser")
        out = _parse_naver_financials(soup)
        assert out["roe"] == 7.11        # index1(2024.12), not 9.99(E)/3.00(분기)
        assert out["debt_ratio"] == 45.21
        assert out["op_margin"] == 17.44

    def test_empty_when_no_table(self):
        assert _parse_naver_financials(_BS("<html></html>", "html.parser")) == {}


class TestFetchKrValuationAnalyst:
    def test_combines_and_converts(self):
        # 단일 네이버 페이지에서 밸류+컨센서스+재무 모두 파싱(FnGuide 제거).
        with patch("src.ingest_kr._get_html", return_value=_NAVER_HTML.encode()), \
             patch("src.ingest_kr.time.sleep", return_value=None):
            val, ana = fetch_kr_valuation_analyst("035420.KS", asof=_date(2026, 6, 15))
        # ROE %→비율 변환 (7.11% → 0.0711)
        assert val.roe == pytest.approx(0.0711)
        assert val.per_t == 21.53
        assert val.pbr == 1.26
        assert val.debt_ratio == 45.21
        # upside = 329227/248000 - 1
        assert ana.target_price == 329227.0
        assert ana.rating == "매수"
        assert ana.rating_label == "매수"
        assert ana.rating_score == 1.0
        assert ana.upside == pytest.approx(329227.0 / 248000.0 - 1, rel=1e-4)
        assert ana.n_analysts == 4
        assert ana.source == "naver"

    def test_none_when_pages_empty(self):
        with patch("src.ingest_kr._get_html", return_value=b"<html></html>"), \
             patch("src.ingest_kr.time.sleep", return_value=None):
            val, ana = fetch_kr_valuation_analyst("000000.KS")
        assert val is None and ana is None


class TestResolveKrPriceTargetDate:
    def test_after_close_uses_same_kst_day(self):
        out = _resolve_kr_price_target_date(dt.datetime(2026, 6, 19, 18, 5))
        assert out == dt.date(2026, 6, 19)

    def test_utc_runner_time_converts_to_same_kst_close_day(self):
        out = _resolve_kr_price_target_date(
            dt.datetime(2026, 6, 19, 9, 5, tzinfo=dt.timezone.utc)
        )
        assert out == dt.date(2026, 6, 19)

    def test_before_close_uses_previous_business_day(self):
        out = _resolve_kr_price_target_date(dt.datetime(2026, 6, 19, 6, 0))
        assert out == dt.date(2026, 6, 18)

    def test_weekend_rolls_back_to_friday(self):
        out = _resolve_kr_price_target_date(dt.datetime(2026, 6, 21, 18, 0))
        assert out == dt.date(2026, 6, 19)
