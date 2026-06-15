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

from src.ingest_kr import _parse_dart_col_date, _parse_fs_rows


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
