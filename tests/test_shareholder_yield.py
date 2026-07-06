"""주주환원(배당) 팩터 — export 백분위 + KR 배당 추출(중단=0) 테스트."""
from src.export_dashboard_data import _attach_shareholder_yield


def test_percentile_high_div_top_no_div_bottom():
    stocks = [{"t": "HI", "divYield": 6.0}, {"t": "MID", "divYield": 3.0},
              {"t": "LO", "divYield": 1.0}, {"t": "ZERO", "divYield": 0.0}]
    _attach_shareholder_yield(stocks)
    m = {s["t"]: s["shYield"] for s in stocks}
    assert m["HI"] == 100.0 and m["ZERO"] == 0.0     # 고배당 top, 무배당 bottom
    assert m["LO"] < m["MID"] < m["HI"]


def test_none_div_excluded_from_factor():
    stocks = [{"t": "A", "divYield": 4.0}, {"t": "B", "divYield": 2.0},
              {"t": "N", "divYield": None}]
    _attach_shareholder_yield(stocks)
    m = {s["t"]: s["shYield"] for s in stocks}
    assert m["N"] is None                            # 미수집 → 팩터 제외(중립)
    assert m["A"] == 100.0 and m["B"] == 0.0


def test_kr_dividend_cut_recent_blank_is_zero():
    # 네이버 기업실적분석: 배당 중단 종목은 최근 실적 연간이 공란 → 0.0(스테일 과거 폴백 금지).
    from bs4 import BeautifulSoup
    from src.ingest_kr import _parse_naver_financials
    html = """
    <div class="section cop_analysis"><table>
      <thead>
        <tr><th rowspan="2">주요재무정보</th><th colspan="3">최근 연간 실적</th><th colspan="1">최근 분기</th></tr>
        <tr><th>2023.12</th><th>2024.12</th><th>2025.12 (E)</th><th>2025.09</th></tr>
      </thead>
      <tbody>
        <tr><th>ROE(지배주주)</th><td>10.0</td><td>7.0</td><td>9.0</td><td>3.0</td></tr>
        <tr><th>시가배당률(%)</th><td>6.65</td><td></td><td></td><td></td></tr>
      </tbody>
    </table></div>
    """
    out = _parse_naver_financials(BeautifulSoup(html, "html.parser"))
    # 최근 실적 연간 = 2024.12(index1) 공란 → 0.0 (2023의 6.65로 폴백하면 안 됨)
    assert out["div_yield"] == 0.0
    assert out["roe"] == 7.0     # ROE는 종전대로 최근 실적(2024)


def test_kr_dividend_paying_uses_recent_annual():
    from bs4 import BeautifulSoup
    from src.ingest_kr import _parse_naver_financials
    html = """
    <div class="section cop_analysis"><table>
      <thead>
        <tr><th rowspan="2">주요재무정보</th><th colspan="3">최근 연간 실적</th><th colspan="1">최근 분기</th></tr>
        <tr><th>2023.12</th><th>2024.12</th><th>2025.12 (E)</th><th>2025.09</th></tr>
      </thead>
      <tbody><tr><th>시가배당률(%)</th><td>5.98</td><td>4.22</td><td>4.0</td><td></td></tr></tbody>
    </table></div>
    """
    out = _parse_naver_financials(BeautifulSoup(html, "html.parser"))
    assert out["div_yield"] == 4.22   # 최근 실적 연간(2024.12), (E)인 2025 아님
