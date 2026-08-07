"""R7 실적 캘린더 회귀 가드 — 전부 모킹(실호출·실DB 없음).

핵심 계약:
  1) 발표일 → 회계분기 매핑이 정확해야 fundamentals 대조(T+1 트리거)가 성립한다.
  2) T+1 트리거는 '발표 경과 & 해당 분기 미적재' 종목만 골라야 한다(전체 재수집 금지).
  3) KR 추정 행이 이미 발표된 행을 되돌리지 않는다.
  4) §F7: 캘린더는 표시·트리거 전용 — 점수·팩터 계산 경로에 들어가지 않는다.
"""
from __future__ import annotations

from datetime import date

import pytest

from src import ingest_earnings as ie


class TestPeriodMapping:
    @pytest.mark.parametrize("announce,expected", [
        (date(2026, 8, 6), "2026Q2"),    # CELH Q2 발표
        (date(2026, 8, 5), "2026Q2"),    # ALB Q2 발표
        (date(2026, 7, 29), "2026Q2"),   # MSFT (6/30 종료 분기)
        (date(2026, 1, 15), "2025Q4"),   # 연초 발표 = 직전 4분기
        (date(2026, 4, 20), "2026Q1"),
        (date(2026, 11, 5), "2026Q3"),
    ])
    def test_announce_date_to_fiscal_period(self, announce, expected):
        assert ie._fiscal_period(ie._quarter_end_before(announce)) == expected

    def test_quarter_end_is_strictly_before(self):
        """분기 종료 당일 발표는 그 분기가 아니라 직전 분기 실적이다."""
        assert ie._quarter_end_before(date(2026, 6, 30)) == date(2026, 3, 31)


class TestKrReportParsing:
    @pytest.mark.parametrize("nm,kind", [
        ("반기보고서 (2026.06)", "half"),
        ("분기보고서 (2026.03)", "quarter"),
        ("사업보고서 (2025.12)", "annual"),
        ("[기재정정]분기보고서 (2026.03)", "quarter"),
    ])
    def test_report_kind(self, nm, kind):
        assert ie._kr_report_kind(nm) == kind

    def test_deadline_extension_notice_is_not_a_report(self):
        """'반기보고서제출기한연장신고서'는 발표가 아니다 — 오탐하면 reported가 잘못 켜진다."""
        assert ie._kr_report_kind("반기보고서제출기한연장신고서 (2026.06)") is None

    @pytest.mark.parametrize("nm,pend", [
        ("반기보고서 (2026.06)", date(2026, 6, 30)),
        ("분기보고서 (2026.03)", date(2026, 3, 31)),
        ("사업보고서 (2025.12)", date(2025, 12, 31)),
    ])
    def test_period_end(self, nm, pend):
        assert ie._kr_period_end(nm) == pend

    def test_period_end_none_without_marker(self):
        assert ie._kr_period_end("반기보고서") is None


class TestKrExpectedRows:
    def test_half_year_deadline_is_45_days(self):
        """반기(6/30) 법정기한 = 8/14 — 뉴프렉스 반기 임박 이벤트가 여기서 나온다."""
        rows = ie.kr_expected_rows(["085670.KQ"], today=date(2026, 8, 7))
        assert len(rows) == 1
        r = rows[0]
        assert r["fiscal_period"] == "2026Q2"
        assert r["scheduled_date"] == date(2026, 8, 14)
        assert r["confirmed"] is False and r["reported"] is False
        assert r["consensus_eps"] is None      # DART는 컨센서스를 주지 않는다

    def test_annual_deadline_is_90_days(self):
        rows = ie.kr_expected_rows(["005930.KS"], today=date(2026, 2, 10))
        assert rows[0]["scheduled_date"] == date(2026, 3, 31)   # 12/31 + 90일
        assert rows[0]["fiscal_period"] == "2025Q4"

    def test_only_immediately_prior_quarter(self):
        """직전 완료 분기 1건만 만든다 — 과거 분기 추정행을 소급 양산하면 캘린더가 오염된다."""
        rows = ie.kr_expected_rows(["005930.KS", "085670.KQ"], today=date(2026, 6, 29))
        assert {r["fiscal_period"] for r in rows} == {"2026Q1"}
        assert len(rows) == 2  # 종목당 1건


class _FakeRow(dict):
    def get(self, k, default=None):
        return dict.get(self, k, default)


class TestUsParsing:
    def _df(self, rows):
        import pandas as pd
        idx = pd.to_datetime([r[0] for r in rows])
        return pd.DataFrame(
            {"EPS Estimate": [r[1] for r in rows],
             "Reported EPS": [r[2] for r in rows],
             "Surprise(%)": [r[3] for r in rows]},
            index=idx,
        )

    def test_reported_and_upcoming_split(self, monkeypatch):
        import pandas as pd

        df = self._df([
            ("2026-08-06", 0.42, 0.36, -13.88),   # 발표 완료
            ("2026-11-09", 0.42, float("nan"), float("nan")),  # 예정
        ])

        class _TK:
            earnings_dates = df
            calendar = {"Earnings Date": [date(2026, 11, 9)], "Revenue Average": 8.7e8}

        monkeypatch.setattr(ie, "today_kst", lambda: date(2026, 8, 7))
        monkeypatch.setitem(__import__("sys").modules, "yfinance",
                            type("m", (), {"Ticker": staticmethod(lambda t: _TK())}))
        rows = ie.fetch_us_earnings("CELH")
        by_date = {r["scheduled_date"]: r for r in rows}

        done = by_date[date(2026, 8, 6)]
        assert done["reported"] is True and done["actual_eps"] == pytest.approx(0.36)
        assert done["surprise_pct"] == pytest.approx(-13.88)
        assert done["fiscal_period"] == "2026Q2"

        nxt = by_date[date(2026, 11, 9)]
        assert nxt["reported"] is False
        assert nxt["actual_eps"] is None           # NaN → None
        assert nxt["consensus_rev"] == pytest.approx(8.7e8)   # calendar 보강
        assert all(r["confirmed"] for r in rows)
        assert pd is not None


class _Cur:
    def __init__(self, rows):
        self._rows = rows
        self.sql = ""
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.sql = " ".join(sql.split())
        self.params = params

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.last = None

    def cursor(self):
        self.last = _Cur(self.rows)
        return self.last


class TestRefetchTrigger:
    def test_only_reported_and_missing(self):
        conn = _Conn([{"ticker": "ALB"}, {"ticker": "CELH"}])
        assert ie.tickers_needing_refetch(conn) == ["ALB", "CELH"]
        sql = conn.last.sql.upper()
        assert "E.REPORTED" in sql                    # 발표된 것만
        assert "NOT EXISTS" in sql and "FUNDAMENTALS" in sql   # 미적재만
        assert "PERIOD_TYPE = 'QUARTER'" in sql

    def test_empty_when_all_loaded(self):
        assert ie.tickers_needing_refetch(_Conn([])) == []

    def test_upcoming_excludes_reported(self):
        conn = _Conn([])
        ie.upcoming_earnings(conn, days=14)
        assert "NOT REPORTED" in conn.last.sql.upper()


def test_upsert_does_not_downgrade_reported_row():
    """KR 추정행(reported=false)이 이미 발표된 행의 실제 접수일을 덮지 않아야 한다."""
    import inspect

    from src import db

    src = inspect.getsource(db.upsert_earnings_calendar)
    assert "CASE" in src and "earnings_calendar.reported AND NOT EXCLUDED.reported" in src
    # 결과·컨센은 소스가 한쪽만 줘도 기존값 보존
    for col in ("consensus_eps", "consensus_rev", "actual_eps", "surprise_pct"):
        assert f"COALESCE(EXCLUDED.{col}" in src


def test_calendar_not_used_in_scoring_paths():
    """§F7: 캘린더는 표시·트리거 전용 — 점수·팩터 계산 모듈이 참조하면 실패."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for mod in ("compute_quant.py", "compute_indicators.py", "backtest.py",
                "compute_market_score.py", "display_signals.py"):
        text = (root / "src" / mod).read_text(encoding="utf-8")
        assert "earnings_calendar" not in text, f"{mod}가 실적 캘린더를 참조 — 룩어헤드 위험"
