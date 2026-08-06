"""R4·R6 회귀 가드 — KR 티커 접미사 관례(코스닥 벤치마크) + 환율 단일 소스.

R4: 코스닥 종목이 코스피 벤치마크로 베타 계산되던 드리프트(신규 종목마다 allowlist 수동 등록).
R6: 표시(export)와 계산(compute_portfolio)이 환율을 다른 방식으로 읽어 어긋나던 문제.
"""
from __future__ import annotations

import pytest

from src.compute_quant import _market_benchmark
from src.db import latest_usdkrw


class TestKosdaqBenchmark:
    def test_kq_suffix_maps_to_kosdaq_index(self):
        """관례: .KQ = 코스닥 → ^KQ11. allowlist 등록 없이도 성립해야 한다."""
        assert _market_benchmark("085670.KQ", "KR") == "^KQ11"   # 뉴프렉스(보유)
        assert _market_benchmark("440110.KQ", "KR") == "^KQ11"   # 파두

    def test_ks_suffix_maps_to_kospi_index(self):
        assert _market_benchmark("005930.KS", "KR") == "^KS11"
        assert _market_benchmark("001450.KS", "KR") == "^KS11"

    def test_legacy_allowlist_still_honored(self):
        """과거 .KS로 잘못 저장된 코스닥 종목 하위호환(일괄 정정 전까지 유지)."""
        assert _market_benchmark("059090.KS", "KR") == "^KQ11"   # 미코
        assert _market_benchmark("213420.KS", "KR") == "^KQ11"   # 덕산네오룩스

    def test_us_unchanged(self):
        assert _market_benchmark("MSFT", "US") == "^GSPC"

    def test_case_insensitive_suffix(self):
        assert _market_benchmark("085670.kq", "KR") == "^KQ11"


class _Cur:
    def __init__(self, rows):
        self._rows = rows
        self.sql = ""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.sql = " ".join(sql.split())

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _Conn:
    def __init__(self, rows):
        self.rows = rows
        self.last: _Cur | None = None

    def cursor(self):
        self.last = _Cur(self.rows)
        return self.last


class TestLatestUsdkrw:
    def test_filters_null_rows(self):
        """★핵심 — 최신 '행'의 컬럼이 아니라 최신 non-null asof를 골라야 한다."""
        conn = _Conn([{"usdkrw": 1421.87}])
        assert latest_usdkrw(conn) == pytest.approx(1421.87)
        assert "USDKRW IS NOT NULL" in conn.last.sql.upper()
        assert "ORDER BY ASOF DESC" in conn.last.sql.upper()

    def test_returns_none_when_no_data(self):
        assert latest_usdkrw(_Conn([])) is None

    def test_numeric_cast_to_float(self):
        """DB NUMERIC → float 경계(Decimal 혼용 금지)."""
        from decimal import Decimal
        v = latest_usdkrw(_Conn([{"usdkrw": Decimal("1421.87")}]))
        assert isinstance(v, float)


def test_compute_portfolio_uses_shared_source():
    """R6: 포폴 계산이 export와 같은 함수를 쓰는지(각자 쿼리하면 다시 어긋난다)."""
    from src import compute_portfolio
    conn = _Conn([{"usdkrw": 1421.87}])
    assert compute_portfolio._get_usdkrw(conn) == pytest.approx(1421.87)


def test_export_imports_shared_source():
    """R6: export가 latest['usdkrw'] 직접 읽기로 되돌아가면 실패."""
    import inspect

    from src import export_dashboard_data as ex

    src = inspect.getsource(ex)
    assert "from src.db import latest_usdkrw" in src
    assert 'latest["usdkrw"]' not in src, "최신 행 컬럼 직접 읽기 금지(R6)"
