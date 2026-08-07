"""
ingest_earnings.py — 실적 발표 일정·결과 수집 (R7)

★ 진단 결과가 설계를 정했다(2026-08-07 실측)
  ALB Q2(08-05)·CELH Q2(08-06)가 발표됐는데도 `fundamentals`에 없던 근본원인은
  **수집 미실행도 파서 실패도 아니고 소스(yfinance) 지연**이다:
    - yfinance `quarterly_financials` 최신 컬럼이 ALB·CELH 모두 2026-03-31(Q1)에 멈춰 있다.
      즉 지금 몇 번을 재수집해도 Q2 재무제표는 들어오지 않는다.
    - 반면 **`earnings_dates`에는 결과가 이미 있다** — CELH 08-06 컨센 0.42 / 실제 0.36 /
      서프라이즈 -13.88%, ALB 08-05 컨센 3.24 / 실제 3.75 / +15.71%.
  그래서 이 모듈은 두 층을 분리한다:
    ① **일정·EPS 결과**(즉시 가능) → `earnings_calendar`
    ② **재무제표 3종**(소스가 채운 뒤에야 가능) → 기존 `fundamentals` 경로를,
       "발표는 됐는데 아직 안 들어온 종목"만 골라 재시도(`tickers_needing_refetch`).
  ②를 전체 재수집으로 돌리면 비용만 쓰고 값은 안 들어온다 — 좁게 도는 것이 핵심이다.

소스 (둘 다 CI-safe: 로그인 불요, API 키 또는 공개 엔드포인트)
  - US: yfinance `Ticker.earnings_dates`(예정+실제+서프라이즈), `Ticker.calendar`(컨센 매출)
  - KR: DART `list.json` 정기보고서 접수 조회 — **사후 감지**. 한국은 사전 실적일정 공시가
        일반적이지 않아 `scheduled_date`는 법정기한 추정치(confirmed=false)로 둔다.

Gemini 호출 없음. 계산·팩터 로직 무변경(수집·저장 전용).
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date, timedelta
from typing import Optional

import psycopg

from src.external_timeout import run_with_timeout
from src.freshness import today_kst

logger = logging.getLogger(__name__)

# 상수(하드코딩 금지)
EARNINGS_HORIZON_DAYS: int = int(os.getenv("EARNINGS_HORIZON_DAYS", "14"))   # export 노출 창
EARNINGS_LOOKBACK_DAYS: int = int(os.getenv("EARNINGS_LOOKBACK_DAYS", "45")) # 발표 경과 추적 창
YF_TIMEOUT_SECONDS: float = float(os.getenv("YF_TIMEOUT_SECONDS", "30"))
DART_TIMEOUT_SECONDS: float = float(os.getenv("DART_TIMEOUT_SECONDS", "30"))
DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"

# KR 정기보고서 법정 제출기한(사업연도/반기/분기 종료 후 일수) — scheduled_date 추정 근거.
_KR_DEADLINE_DAYS = {"annual": 90, "half": 45, "quarter": 45}


# ── 공통 ────────────────────────────────────────────────────────────────────
def _quarter_end_before(d: date) -> date:
    """d 직전에 끝난 분기의 마지막 날. 발표일 → 대상 회계분기 매핑에 쓴다."""
    q_ends = [date(d.year - 1, 12, 31), date(d.year, 3, 31), date(d.year, 6, 30),
              date(d.year, 9, 30), date(d.year, 12, 31)]
    return max(q for q in q_ends if q < d)


def _fiscal_period(period_end: date) -> str:
    """분기 종료일 → '2026Q2'."""
    return f"{period_end.year}Q{(period_end.month - 1) // 3 + 1}"


def _f(value) -> Optional[float]:
    """NaN·None·비수치 → None (DB 결측은 None으로 명확히)."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # NaN 제외


# ── US: yfinance ────────────────────────────────────────────────────────────
def fetch_us_earnings(ticker: str) -> list[dict]:
    """
    yfinance earnings_dates → 캘린더 행 목록.

    과거 발표분은 실제 EPS·서프라이즈까지, 미래 예정분은 컨센서스만 채운다.
    ETF 등 실적이 없는 티커는 빈 리스트(호출부에서 종목 단위 격리).
    """
    import yfinance as yf

    tk = yf.Ticker(ticker)
    try:
        df = run_with_timeout(YF_TIMEOUT_SECONDS, lambda: tk.earnings_dates)
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s: earnings_dates 실패 — %s", ticker, str(exc)[:120])
        return []
    if df is None or df.empty:
        return []

    today = today_kst()
    lo, hi = today - timedelta(days=EARNINGS_LOOKBACK_DAYS), today + timedelta(days=180)
    rows: list[dict] = []
    for ts, row in df.iterrows():
        try:
            sched = ts.date()
        except AttributeError:
            continue
        if not (lo <= sched <= hi):
            continue
        actual = _f(row.get("Reported EPS"))
        rows.append({
            "ticker": ticker,
            "fiscal_period": _fiscal_period(_quarter_end_before(sched)),
            "scheduled_date": sched,
            "confirmed": True,           # yfinance는 확정 발표일을 준다
            "reported": actual is not None,
            "consensus_eps": _f(row.get("EPS Estimate")),
            "consensus_rev": None,       # earnings_dates에는 없음 — calendar에서 보강
            "actual_eps": actual,
            "surprise_pct": _f(row.get("Surprise(%)")),
            "source": "yfinance",
        })

    # 다음 발표 1건에 한해 컨센서스 매출을 보강(calendar가 '다음 이벤트'만 제공).
    try:
        cal = run_with_timeout(YF_TIMEOUT_SECONDS, lambda: tk.calendar) or {}
        rev = _f(cal.get("Revenue Average"))
        dates = cal.get("Earnings Date") or []
        if rev is not None and dates:
            nxt = dates[0]
            for r in rows:
                if r["scheduled_date"] == nxt:
                    r["consensus_rev"] = rev
    except Exception as exc:  # noqa: BLE001
        logger.debug("%s: calendar 보강 스킵 — %s", ticker, str(exc)[:80])
    return rows


# ── KR: DART 정기보고서 접수(사후 감지) ──────────────────────────────────────
_REPORT_PATTERNS = [
    (re.compile(r"사업보고서"), "annual"),
    (re.compile(r"반기보고서"), "half"),
    (re.compile(r"분기보고서"), "quarter"),
]


def _kr_report_kind(report_nm: str) -> Optional[str]:
    """report_nm → annual|half|quarter. 정정·기한연장 신고서는 제외."""
    if "제출기한연장" in report_nm:
        return None
    for pat, kind in _REPORT_PATTERNS:
        if pat.search(report_nm):
            return kind
    return None


def _kr_period_end(report_nm: str) -> Optional[date]:
    """'반기보고서 (2026.06)' → 2026-06-30 (해당 월 말일 = 분기 종료일)."""
    m = re.search(r"\((\d{4})\.(\d{2})\)", report_nm)
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    if month not in (3, 6, 9, 12):
        return None
    return _quarter_end_before(date(year, month, 28) + timedelta(days=10))


def fetch_kr_earnings(codes: set[str]) -> list[dict]:
    """
    DART 공시목록에서 관심 종목의 정기보고서 접수를 찾아 캘린더 행으로.

    한국은 사전 실적일정 공시가 일반적이지 않으므로 **사후 감지**다.
    scheduled_date = 실제 접수일(발표됨) 또는 법정기한 추정(미접수) — confirmed=false로 구분.
    codes: 6자리 종목코드 집합.
    """
    import requests

    key = os.environ.get("DART_API_KEY")
    if not key:
        logger.warning("DART_API_KEY 미설정 — KR 실적 캘린더 스킵")
        return []

    today = today_kst()
    bgn = (today - timedelta(days=EARNINGS_LOOKBACK_DAYS)).strftime("%Y%m%d")
    rows: list[dict] = []
    page = 1
    while page <= 5:  # 안전 상한(정기보고서 시즌엔 수천 건) — 관심 종목만 골라내면 충분
        try:
            resp = requests.get(
                DART_LIST_URL,
                params={"crtfc_key": key, "bgn_de": bgn, "end_de": today.strftime("%Y%m%d"),
                        "pblntf_ty": "A", "page_no": str(page), "page_count": "100"},
                timeout=DART_TIMEOUT_SECONDS,
            )
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("DART 공시목록 조회 실패(page %d) — %s", page, str(exc)[:120])
            break
        if data.get("status") != "000":
            logger.warning("DART 응답 상태 %s: %s", data.get("status"), data.get("message"))
            break
        for item in data.get("list") or []:
            code = (item.get("stock_code") or "").strip()
            if code not in codes:
                continue
            kind = _kr_report_kind(item.get("report_nm") or "")
            if kind is None:
                continue
            pend = _kr_period_end(item.get("report_nm") or "")
            if pend is None:
                continue
            try:
                rcept = date(int(item["rcept_dt"][:4]), int(item["rcept_dt"][4:6]), int(item["rcept_dt"][6:8]))
            except (KeyError, ValueError):
                continue
            rows.append({
                "ticker": code,          # 호출부가 ATLAS 티커로 매핑
                "fiscal_period": _fiscal_period(pend),
                "scheduled_date": rcept,
                "confirmed": True,       # 실제 접수일이므로 확정
                "reported": True,
                "consensus_eps": None,   # DART는 컨센서스를 주지 않는다(결측 명확히)
                "consensus_rev": None,
                "actual_eps": None,
                "surprise_pct": None,
                "source": "dart",
            })
        if int(data.get("page_no", page)) >= int(data.get("total_page", page)):
            break
        page += 1
    return rows


def kr_expected_deadline(period_end: date, kind: str = "half") -> date:
    """미접수 KR 정기보고서의 법정 제출기한(추정 scheduled_date)."""
    return period_end + timedelta(days=_KR_DEADLINE_DAYS.get(kind, 45))


def _kr_report_kind_for(period_end: date) -> str:
    """분기 종료 월 → 보고서 종류(12월=사업보고서, 6월=반기, 3·9월=분기)."""
    return {12: "annual", 6: "half"}.get(period_end.month, "quarter")


def kr_expected_rows(tickers: list[str], today: Optional[date] = None) -> list[dict]:
    """
    KR '예정' 행 — 직전 완료 분기의 **법정 제출기한**을 추정 발표일로 둔다.

    한국은 사전 실적일정 공시가 일반적이지 않아 DART로는 접수(사후)만 잡힌다. 그러면
    "뉴프렉스 반기가 언제 나오나"를 화면에서 못 본다(수기 추적의 원인). 법정기한은
    공개된 규칙이므로 이를 `confirmed=false` 추정치로 넣어 임박 이벤트를 보이게 한다.
    실제 접수가 잡히면 `fetch_kr_earnings`가 실제 접수일·reported=true로 덮어쓴다
    (upsert가 발표된 행을 추정치로 되돌리지 않도록 방어).
    """
    # 항상 '직전 완료 분기' 하나만 만든다 — 과거 분기 행을 소급 양산하지 않는다.
    today = today or today_kst()
    period_end = _quarter_end_before(today)
    deadline = kr_expected_deadline(period_end, _kr_report_kind_for(period_end))
    return [{
        "ticker": t,
        "fiscal_period": _fiscal_period(period_end),
        "scheduled_date": deadline,
        "confirmed": False,   # 법정기한 추정 — 화면에서 '예상'으로 구분 표기
        "reported": False,
        "consensus_eps": None, "consensus_rev": None,
        "actual_eps": None, "surprise_pct": None,
        "source": "dart",
    } for t in tickers]


# ── T+1 재수집 트리거 ────────────────────────────────────────────────────────
def tickers_needing_refetch(conn: psycopg.Connection) -> list[str]:
    """
    **발표는 끝났는데 fundamentals에 그 분기가 아직 없는** 종목만 반환.

    전체 재수집을 막는 것이 이 함수의 존재 이유다(§8 비용규율). 소스 지연으로 아직
    안 들어온 종목은 다음 실행에서 다시 후보가 되므로 자연히 재시도된다.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT e.ticker
              FROM earnings_calendar e
             WHERE e.reported
               AND e.scheduled_date >= %s
               AND NOT EXISTS (
                     SELECT 1 FROM fundamentals f
                      WHERE f.ticker = e.ticker
                        AND f.period_type = 'quarter'
                        AND to_char(f.period_end, 'YYYY"Q"Q') = e.fiscal_period
                   )
             ORDER BY e.scheduled_date DESC
            """,
            (today_kst() - timedelta(days=EARNINGS_LOOKBACK_DAYS),),
        )
        return [r["ticker"] for r in cur.fetchall()]


def run_earnings_ingest(conn: psycopg.Connection, watchlist: list[dict]) -> dict:
    """
    실적 캘린더 수집 실행기 — 종목 단위 격리, 단계별 commit.

    반환: {"counts": {...}, "refetch": [발표 경과·미적재 종목], "errors": [...]}
    """
    from src.db import upsert_earnings_calendar

    counts = {"us": 0, "kr": 0, "kr_expected": 0, "tickers": 0}
    errors: list[dict] = []

    us = [w["ticker"] for w in watchlist if w["market"] == "US"]
    kr = [w["ticker"] for w in watchlist if w["market"] == "KR"]

    for ticker in us:
        try:
            rows = fetch_us_earnings(ticker)
            if rows:
                upsert_earnings_calendar(conn, rows)
                conn.commit()
                counts["us"] += len(rows)
                counts["tickers"] += 1
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            logger.warning("%s: 실적 캘린더 실패 — %s", ticker, str(exc)[:150])
            errors.append({"ticker": ticker, "error": str(exc)[:200]})

    # KR: ①법정기한 추정행을 먼저 깔고 ②실제 접수분으로 덮어쓴다(순서 중요).
    #     공시목록은 1회 조회로 전 종목을 훑는다(종목당 호출 아님).
    by_code = {t.split(".")[0]: t for t in kr}
    try:
        expected = kr_expected_rows(kr)
        if expected:
            upsert_earnings_calendar(conn, expected)
            conn.commit()
            counts["kr_expected"] = len(expected)
        kr_rows = fetch_kr_earnings(set(by_code))
        for r in kr_rows:
            r["ticker"] = by_code.get(r["ticker"], r["ticker"])
        if kr_rows:
            upsert_earnings_calendar(conn, kr_rows)
            conn.commit()
            counts["kr"] = len(kr_rows)
            counts["tickers"] += len({r["ticker"] for r in kr_rows})
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        logger.warning("KR 실적 캘린더 실패 — %s", str(exc)[:150])
        errors.append({"ticker": "KR", "error": str(exc)[:200]})

    refetch = tickers_needing_refetch(conn)
    logger.info(
        "실적 캘린더: US %d행 · KR 접수 %d행/예정 %d행 · 재수집 대상 %d종목%s",
        counts["us"], counts["kr"], counts["kr_expected"], len(refetch),
        f" {refetch[:8]}" if refetch else "",
    )
    return {"counts": counts, "refetch": refetch, "errors": errors}


def upcoming_earnings(conn: psycopg.Connection, days: int = EARNINGS_HORIZON_DAYS) -> list[dict]:
    """향후 `days`일 실적 예정(발표 전만). export·claude_pm 조회용."""
    today = today_kst()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ticker, fiscal_period, scheduled_date, confirmed,
                   consensus_eps, consensus_rev, source
              FROM earnings_calendar
             WHERE NOT reported AND scheduled_date BETWEEN %s AND %s
             ORDER BY scheduled_date, ticker
            """,
            (today, today + timedelta(days=days)),
        )
        return [dict(r) for r in cur.fetchall()]
