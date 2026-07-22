"""PR-A: market_daily 체결일 키잉 · 배드틱 가드 · index_daily 정합 회귀 테스트."""
from __future__ import annotations

from datetime import date

import pytest

from src import ingest_market
from src.freshness import is_trading_day

# 실측 KOSPI 종가(KRX 공식·네이버 일치). 07-17은 제헌절 휴장이라 봉 자체가 없다.
KOSPI_BARS = [
    (date(2026, 7, 15), 7284.41),
    (date(2026, 7, 16), 6820.60),
    (date(2026, 7, 20), 6516.27),
]
SP500_BARS = [
    (date(2026, 7, 16), 7533.77),
    (date(2026, 7, 17), 7457.69),
    (date(2026, 7, 20), 7443.28),
]


def _fake_series(kospi=KOSPI_BARS, sp500=SP500_BARS):
    def _inner(symbol, *a, **k):
        if symbol == "^KS11":
            return kospi
        if symbol == "^GSPC":
            return sp500
        return []
    return _inner


def test_rows_are_keyed_by_source_bar_date(monkeypatch):
    """행의 asof = 소스 체결일. 실행일이 아니다 — 하루 밀림·유령봉의 근본 차단."""
    monkeypatch.setattr(ingest_market, "index_series", _fake_series())
    rows = {r.asof: r for r in ingest_market.fetch_market_rows()}

    assert rows[date(2026, 7, 16)].kospi == 6820.60
    assert rows[date(2026, 7, 20)].kospi == 6516.27


def test_kr_holiday_leaves_no_kospi_but_keeps_us(monkeypatch):
    """07-17은 KR 휴장(제헌절)·US 개장 → kospi는 없고 sp500만 있는 행."""
    monkeypatch.setattr(ingest_market, "index_series", _fake_series())
    rows = {r.asof: r for r in ingest_market.fetch_market_rows()}

    holiday = rows[date(2026, 7, 17)]
    assert holiday.kospi is None, "휴장일에 직전 종가가 복제되면 유령봉"
    assert holiday.sp500 == 7457.69


def test_no_weekend_rows(monkeypatch):
    """주말은 소스에 봉이 없으므로 행 자체가 생기지 않는다."""
    monkeypatch.setattr(ingest_market, "index_series", _fake_series())
    for r in ingest_market.fetch_market_rows():
        assert r.asof.weekday() < 5


def test_bad_tick_dropped(monkeypatch):
    """|일간 등락|이 임계를 넘는 봉은 버린다(소스 오류로 간주)."""
    bars = [(date(2026, 7, 15), 7284.41), (date(2026, 7, 16), 100.0)]  # -98.6%
    monkeypatch.setattr(ingest_market, "index_series", _fake_series(kospi=bars, sp500=[]))
    rows = {r.asof: r for r in ingest_market.fetch_market_rows()}

    assert date(2026, 7, 16) not in rows or rows[date(2026, 7, 16)].kospi is None


def test_change_pct_matches_real_move(monkeypatch):
    """07-16 실제 -6.37% 급락. 과거엔 +6.24% 급등으로 부호까지 뒤집혔다."""
    monkeypatch.setattr(ingest_market, "index_series", _fake_series())
    rows = {r.asof: r for r in ingest_market.fetch_market_rows()}
    assert rows[date(2026, 7, 16)].payload["changes"]["kospi"] == -6.37


def test_both_tables_share_one_fetch(monkeypatch):
    """market_daily·index_daily가 한 실행 안에서 같은 바이트를 본다.

    각자 HTTP를 때리면 그 사이 소스 갱신으로 두 테이블이 하루 갈릴 수 있다(실사고 재발 경로).
    """
    calls = []

    def _spy(symbol, period, pages, cutoff):
        calls.append(symbol)
        return tuple(KOSPI_BARS)

    monkeypatch.setattr(ingest_market, "_series_cache", {})
    monkeypatch.setattr(ingest_market, "_fetch_series", _spy)

    first = ingest_market.index_series("^KS11")            # market_daily 경로
    second = ingest_market.index_series("^KS11")           # index_daily 경로
    assert first == second
    assert calls.count("^KS11") == 1, "두 번 가져오면 두 테이블이 갈릴 수 있다"


def test_partial_holiday_row_keeps_open_market_data(monkeypatch):
    """한쪽 시장만 휴장이면 그 시장 컬럼만 비고 나머지는 실값이 남는다.

    07-17(KR 제헌절·US 개장)에서 행을 통째로 지우면 실제 US 데이터가 사라진다.
    """
    monkeypatch.setattr(ingest_market, "index_series", _fake_series())
    rows = {r.asof: r for r in ingest_market.fetch_market_rows()}
    row = rows[date(2026, 7, 17)]
    assert row.kospi is None and row.sp500 == 7457.69
    # 전 필드가 빈 행은 애초에 만들어지지 않는다(진짜 유령봉의 정의)
    assert all(
        any(getattr(r, f) is not None for f in ("kospi", "kosdaq", "sp500", "nasdaq"))
        for r in rows.values()
    )


@pytest.mark.parametrize("hour,market,expected", [
    # 00:20 KST — 미장은 아직 07-21 장중이라 07-20까지만 확정
    (0, "US", date(2026, 7, 20)),
    # 06:00 KST — 미 07-21 종가 확정
    (6, "US", date(2026, 7, 21)),
    # 06:00 KST — KR 07-22장은 아직 시작 전
    (6, "KR", date(2026, 7, 21)),
    # 18:00 KST — KR 당일 종가 확정
    (18, "KR", date(2026, 7, 22)),
])
def test_incomplete_session_is_not_collected(hour, market, expected):
    """장중 실시간가가 지수 이력에 박히는 것을 막는다(index_daily 오염 방지)."""
    from datetime import datetime
    from src.freshness import KST
    now = datetime(2026, 7, 22, hour, 20, tzinfo=KST)
    assert ingest_market.last_complete_session(market, now) == expected


@pytest.mark.parametrize("d,expected", [
    (date(2026, 7, 17), False),   # 제헌절 — 실측 확정
    (date(2026, 7, 16), True),
    (date(2026, 7, 20), True),
    (date(2026, 7, 18), False),   # 토
])
def test_krx_calendar_knows_july_17_holiday(d, expected):
    assert is_trading_day(d, "KR") is expected
