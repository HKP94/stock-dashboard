"""tests/test_freshness.py — 신선도 감시 캘린더 로직 단위 테스트 (DB·네트워크 불요)."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.freshness import (
    STALE_THRESHOLD_TRADING_DAYS,
    _is_trading_day,
    _last_trading_day_on_or_before,
    _status,
    _trading_days_between,
    expected_latest,
)

KST = ZoneInfo("Asia/Seoul")


# ── 거래일 판정 ────────────────────────────────────────────────

def test_weekend_not_trading():
    assert _is_trading_day(date(2026, 7, 4), "US") is False  # 토
    assert _is_trading_day(date(2026, 7, 5), "US") is False  # 일


def test_us_independence_holiday():
    # 2026-07-03(금)은 독립기념일 대체휴장 → 미장 휴장
    assert _is_trading_day(date(2026, 7, 3), "US") is False
    # KR은 7/3 정상 거래일
    assert _is_trading_day(date(2026, 7, 3), "KR") is True


def test_normal_weekday_trading():
    assert _is_trading_day(date(2026, 7, 2), "US") is True   # 목
    assert _is_trading_day(date(2026, 7, 2), "KR") is True


# ── 마지막 거래일 ──────────────────────────────────────────────

def test_last_trading_day_skips_holiday_and_weekend():
    # 07-04(토) 이하 마지막 미 거래일 = 07-02(목) (07-03 휴장, 07-04 토)
    assert _last_trading_day_on_or_before(date(2026, 7, 4), "US") == date(2026, 7, 2)


# ── 기대 최신 거래일 (오경보 방지 핵심) ─────────────────────────

def test_us_expected_on_holiday_no_false_alarm():
    # 오늘 2026-07-04(토) 아침. US 기대 최신 = 07-02 (07-03 휴장 인지).
    now = datetime(2026, 7, 4, 9, 0, tzinfo=KST)
    assert expected_latest("US", now) == date(2026, 7, 2)


def test_us_expected_normal_day():
    # 2026-07-08(수) 아침. 어제 07-07(화) 거래일 → 기대 07-07.
    now = datetime(2026, 7, 8, 9, 0, tzinfo=KST)
    assert expected_latest("US", now) == date(2026, 7, 7)


def test_kr_expected_after_close():
    # 2026-07-02(목) 19:00 (18시 이후) → 당일 07-02.
    now = datetime(2026, 7, 2, 19, 0, tzinfo=KST)
    assert expected_latest("KR", now) == date(2026, 7, 2)


def test_kr_expected_before_close():
    # 2026-07-02(목) 10:00 (18시 전) → 직전 거래일 07-01(수).
    now = datetime(2026, 7, 2, 10, 0, tzinfo=KST)
    assert expected_latest("KR", now) == date(2026, 7, 1)


def test_kr_expected_weekend():
    # 2026-07-04(토) → 직전 거래일 07-03(금, KR 정상).
    now = datetime(2026, 7, 4, 9, 0, tzinfo=KST)
    assert expected_latest("KR", now) == date(2026, 7, 3)


# ── 뒤처짐 거래일 수 ───────────────────────────────────────────

def test_trading_days_between_fresh():
    assert _trading_days_between(date(2026, 7, 2), date(2026, 7, 2), "US") == 0
    # db가 기대보다 앞서면 0
    assert _trading_days_between(date(2026, 7, 3), date(2026, 7, 2), "US") == 0


def test_trading_days_between_skips_holiday():
    # 07-02 → 07-06(월): 07-03 휴장·07-04/05 주말 제외 → 07-06 한 거래일
    assert _trading_days_between(date(2026, 7, 2), date(2026, 7, 6), "US") == 1


def test_trading_days_between_stale_gap():
    # 수급 06-26 정지 재현: 06-26 → 07-03 사이 KR 거래일 수 (6/29,30 7/1,2,3 = 5)
    assert _trading_days_between(date(2026, 6, 26), date(2026, 7, 3), "KR") == 5


# ── status 매핑 ────────────────────────────────────────────────

def test_status_fresh_lagging_stale():
    assert _status(0) == "fresh"
    assert _status(1) == "lagging"
    assert _status(STALE_THRESHOLD_TRADING_DAYS) == "stale"
    assert _status(5) == "stale"
