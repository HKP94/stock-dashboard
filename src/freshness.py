"""데이터 신선도 감시 (데이터 신뢰성 트랙 ①).

테이블별 max(date/asof)를 시장 캘린더 기준 '기대 최신 거래일'과 대조해
스테일(조용히 오래됨)을 잡는다. 이번 주 수급 06-26 정지·스테일 export가 근거.

시장 캘린더 인지:
  - KR: 장마감(15:30)+수집확정(~18:00) 후 당일(T+0), 그 전엔 직전 거래일.
  - US: 미장은 KST 다음날 새벽 마감 → 어제(KST) 이하 마지막 미 거래일(T-1).
  - 휴장일 예외: 주말 + 아래 휴장 세트. 목록 누락/오류는 grace(기본 2거래일)로 흡수
    (스테일은 '2거래일 이상 뒤처짐'일 때만 — 실제 사고는 5거래일+라 확실히 잡힌다).

CI·로컬 양쪽 호출 가능. Gemini/네트워크 없음(DB 읽기만).
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import psycopg

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")

# 스테일 판정 임계(거래일). 1거래일 뒤처짐=lagging(정상 범위), 2거래일+=stale.
# 휴장 목록 누락도 이 grace로 흡수 → 오경보 방지.
STALE_THRESHOLD_TRADING_DAYS = 2

# NYSE 휴장 2026 (알려진 값. 누락/오류는 grace로 흡수, 연도 넘어가면 갱신).
NYSE_HOLIDAYS: frozenset[date] = frozenset({
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3),
    date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7),
    date(2026, 11, 26), date(2026, 12, 25),
})
# KRX 휴장 2026 (주요 공휴일·설·추석. 임시공휴일 등은 grace 흡수).
KRX_HOLIDAYS: frozenset[date] = frozenset({
    date(2026, 1, 1),                                      # 신정
    date(2026, 2, 16), date(2026, 2, 17), date(2026, 2, 18),  # 설날 연휴
    date(2026, 3, 1), date(2026, 3, 2),                   # 삼일절(+대체)
    date(2026, 5, 5), date(2026, 5, 24), date(2026, 5, 25),  # 어린이날·부처님오신날(+대체)
    date(2026, 6, 6),                                      # 현충일
    date(2026, 7, 17),                                     # 제헌절 (KRX 휴장 — 지수·개별종목 봉 부재로 실측 확정)
    date(2026, 8, 15), date(2026, 8, 17),                 # 광복절(+대체)
    date(2026, 9, 24), date(2026, 9, 25), date(2026, 9, 26),  # 추석 연휴
    date(2026, 10, 3), date(2026, 10, 5), date(2026, 10, 9),  # 개천절(+대체)·한글날
    date(2026, 12, 25),                                   # 성탄절
})
_HOLIDAYS = {"KR": KRX_HOLIDAYS, "US": NYSE_HOLIDAYS}


def today_kst() -> date:
    """**시스템 기준 오늘 = KST 날짜.**

    `date.today()`는 프로세스 로컬시간이라 CI(UTC)에서 KST 전날을 준다. cron이
    `0 21 * * *`(=06:00 KST)라 아침 실행은 전날, 저녁 실행(18:00 KST=09:00 UTC)은
    당일로 asof가 엇갈렸고, 그 결과 **아침 수집분이 전날 저녁 행을 덮어써** 전 테이블이
    KST 기준 하루씩 밀렸다. asof(=실행일 스냅샷)는 전부 이 함수를 쓴다.
    """
    return datetime.now(KST).date()


def is_trading_day(d: date, market: str) -> bool:
    return d.weekday() < 5 and d not in _HOLIDAYS.get(market, frozenset())


_is_trading_day = is_trading_day  # 하위호환 별칭


def _last_trading_day_on_or_before(d: date, market: str) -> date:
    while not is_trading_day(d, market):
        d -= timedelta(days=1)
    return d


def _trading_days_between(after: date, upto: date, market: str) -> int:
    """after(제외)~upto(포함) 사이 거래일 수. after>=upto면 0(신선/앞섬)."""
    if after >= upto:
        return 0
    n, d = 0, after + timedelta(days=1)
    while d <= upto:
        if is_trading_day(d, market):
            n += 1
        d += timedelta(days=1)
    return n


def expected_latest(market: str, now_kst: Optional[datetime] = None) -> date:
    """시장별 기대 최신 거래일."""
    now_kst = now_kst or datetime.now(KST)
    today = now_kst.date()
    if market == "KR":
        # 수집 확정(~18:00) 후 & 오늘 거래일이면 오늘, 아니면 직전 거래일.
        if is_trading_day(today, "KR") and now_kst.hour >= 18:
            return today
        return _last_trading_day_on_or_before(today - timedelta(days=1), "KR")
    # US: 미장 종가는 KST 다음날 새벽에 확정 → 어제(KST) 이하 마지막 미 거래일.
    return _last_trading_day_on_or_before(today - timedelta(days=1), "US")


def _status(behind: int) -> str:
    if behind <= 0:
        return "fresh"
    if behind < STALE_THRESHOLD_TRADING_DAYS:
        return "lagging"
    return "stale"


def _max_date(conn: psycopg.Connection, table: str, datecol: str, tickers: list[str]) -> Optional[date]:
    if not tickers:
        return None
    with conn.cursor() as cur:
        cur.execute(f"SELECT MAX({datecol}) AS mx FROM {table} WHERE ticker = ANY(%s)", (tickers,))
        row = cur.fetchone()
    return row["mx"] if row else None


# (table, date_col, markets) — 감시 대상. investor_flow는 KR 전용.
_TABLES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("prices_daily", "date", ("KR", "US")),
    ("indicators_daily", "date", ("KR", "US")),
    ("quant_scores", "asof", ("KR", "US")),
    ("news_analysis", "asof", ("KR", "US")),
    ("signal_grade_track", "asof", ("KR", "US")),
    ("investor_flow", "date", ("KR",)),
)

_STATE_FILE = Path.home() / "atlas_logs" / "local_refresh_state.json"


def _local_refresh_state(now_utc: Optional[datetime] = None) -> Optional[dict]:
    """로컬 보조 수집(local_refresh.py) 상태파일 — 로컬 수집 신선도 포함."""
    if not _STATE_FILE.exists():
        return None
    try:
        st = json.loads(_STATE_FILE.read_text())
    except Exception:
        return None
    out = {"lastSuccessUtc": st.get("last_success_utc"), "lastRows": st.get("last_investor_flow_rows"),
           "lastOk": st.get("last_ok")}
    ts = st.get("last_success_utc")
    if ts:
        try:
            age = (now_utc or datetime.now(ZoneInfo("UTC"))) - datetime.fromisoformat(ts)
            out["ageHours"] = round(age.total_seconds() / 3600, 1)
        except Exception:
            pass
    return out


# market_daily 지수 컬럼 ↔ index_daily 정본 매핑(PR-A 불변식).
_INDEX_PAIRS: tuple[tuple[str, str], ...] = (
    ("^KS11", "kospi"), ("^KQ11", "kosdaq"), ("^GSPC", "sp500"), ("^IXIC", "nasdaq"),
)
INDEX_MATCH_TOLERANCE = 0.005


def check_index_consistency(conn: psycopg.Connection, since: Optional[date] = None) -> dict:
    """`market_daily` 지수 컬럼이 `index_daily` 정본과 일치하는지 검사(읽기 전용).

    두 테이블은 같은 취득 함수·같은 체결일 키를 쓰므로 **모든 거래일에 diff=0.00이어야
    한다**. 어긋나면 수집 경로가 갈렸다는 뜻 — 하루 밀림 사고의 조기 경보다.
    최신일 누락(한쪽에만 행 존재)도 불일치로 잡는다.
    """
    since = since or (datetime.now(KST).date() - timedelta(days=30))
    items: list[dict] = []
    for index_code, col in _INDEX_PAIRS:
        with conn.cursor() as cur:
            cur.execute(f"""
                WITH ix AS (
                    SELECT asof, close FROM index_daily
                    WHERE index_code = %s AND asof >= %s
                )
                SELECT COALESCE(m.asof, ix.asof) AS asof, m.{col} AS market_val, ix.close AS index_val
                FROM market_daily m
                FULL OUTER JOIN ix ON ix.asof = m.asof
                WHERE COALESCE(m.asof, ix.asof) >= %s
                  AND (
                      (m.{col} IS NULL) <> (ix.close IS NULL)
                      OR abs(m.{col} - ix.close) > %s
                  )
                ORDER BY 1
            """, (index_code, since, since, INDEX_MATCH_TOLERANCE))
            bad = [dict(r) for r in cur.fetchall()]
        for b in bad:
            items.append({
                "indexCode": index_code, "column": col,
                "asof": b["asof"].isoformat() if b["asof"] else None,
                "marketVal": float(b["market_val"]) if b["market_val"] is not None else None,
                "indexVal": float(b["index_val"]) if b["index_val"] is not None else None,
            })
            logger.warning(
                "지수 정합 위반: %s[%s] market_daily=%s index_daily=%s — 수집 경로가 갈렸다",
                index_code, b["asof"], b["market_val"], b["index_val"],
            )
    return {"consistent": not items, "mismatches": items, "since": since.isoformat()}


def build_freshness(conn: psycopg.Connection, now_kst: Optional[datetime] = None) -> dict:
    """테이블×시장 신선도 판정 → data.json freshness 섹션. 스테일은 WARNING 로그."""
    now_kst = now_kst or datetime.now(KST)
    from src.pipeline_common import active_universe, split_kr_us

    kr_tickers, us_tickers, _all = split_kr_us(active_universe(conn))
    by_market = {"KR": kr_tickers, "US": us_tickers}

    items: list[dict] = []
    for table, datecol, markets in _TABLES:
        for market in markets:
            tickers = by_market[market]
            mx = _max_date(conn, table, datecol, tickers)
            exp = expected_latest(market, now_kst)
            behind = _trading_days_between(mx, exp, market) if mx else 999
            status = _status(behind) if mx else "missing"
            items.append({
                "table": table, "market": market,
                "maxDate": mx.isoformat() if mx else None,
                "expected": exp.isoformat(),
                "behindTradingDays": behind if mx else None,
                "status": status,
            })
            if status in ("stale", "missing"):
                logger.warning(
                    "신선도 경고: %s[%s] max=%s 기대=%s (%d거래일 뒤처짐, status=%s)",
                    table, market, mx, exp, behind if mx else -1, status,
                )

    any_stale = any(it["status"] in ("stale", "missing") for it in items)
    index_check = check_index_consistency(conn)
    return {
        "checkedAt": now_kst.strftime("%Y-%m-%dT%H:%M"),
        "anyStale": any_stale,
        "items": items,
        "localRefresh": _local_refresh_state(),
        "indexConsistency": index_check,
    }


def main() -> int:
    import os
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    # secrets.toml 폴백(export와 동일 경로) — DB_* 환경변수 없을 때
    if not os.getenv("DB_HOST"):
        try:
            from src.export_dashboard_data import _load_secrets
            _load_secrets()
        except Exception:
            pass

    from src.db import get_conn
    with get_conn() as conn:
        result = build_freshness(conn)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\nanyStale={result['anyStale']}")
    for it in result["items"]:
        mark = {"fresh": "✓", "lagging": "·", "stale": "✗", "missing": "✗"}.get(it["status"], "?")
        print(f"  {mark} {it['table']:20s}[{it['market']}] max={it['maxDate']} 기대={it['expected']} status={it['status']}")
    return 1 if result["anyStale"] else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
