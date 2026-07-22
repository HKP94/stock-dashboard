"""
ingest_index_history.py — 장기 벤치마크 지수(5년) 백필

true backtest 비교용 벤치마크 시계열을 별도 테이블(index_daily)에 저장한다.
latest snapshot 성격의 market_daily와 분리해 §F7 분리 원칙을 지킨다.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime

import pandas as pd

from src.db import get_conn, upsert_index_daily
from src.ingest_market import NAVER_INDEX_SYMBOLS, index_series
from src.schemas import IndexDailyRow

logger = logging.getLogger(__name__)

BENCHMARK_INDEXES: tuple[str, ...] = ("^KS11", "^KQ11", "^GSPC", "^IXIC")
DEFAULT_PERIOD = "5y"
MAX_EXPECTED_BUSINESS_GAP = 5

# 네이버 지수 API는 페이지당 60거래일 — 기간별 대략 페이지 수(5y는 KR 이력 상한에 걸릴 수 있음).
_NAVER_PAGES = {"1mo": 1, "3mo": 2, "6mo": 3, "1y": 5, "2y": 9, "5y": 22}


def fetch_index_history(index_code: str, period: str = DEFAULT_PERIOD) -> list[IndexDailyRow]:
    """지수 일봉 이력. KR=네이버(체결일 정확·CI 안전), US=yfinance."""
    is_naver = index_code in NAVER_INDEX_SYMBOLS
    pages = _NAVER_PAGES.get(period, 1) if is_naver else 1
    series = index_series(index_code, period=period, pages=pages)
    if not series:
        logger.warning("%s: index history empty", index_code)
        return []
    # source는 실제 취득 소스를 적는다 — KR을 네이버로 바꾸고도 'yfinance'로 남으면
    # 나중에 출처를 추적할 수 없다(PM 검수에서 실제로 오판을 유발).
    source = "naver" if is_naver else "yfinance"
    rows = [IndexDailyRow(index_code=index_code, asof=d, close=c, source=source) for d, c in series]
    logger.info("%s: index history %d rows", index_code, len(rows))
    return rows


def find_missing_business_days(
    rows: list[IndexDailyRow],
    max_gap_days: int = MAX_EXPECTED_BUSINESS_GAP,
) -> list[dict]:
    if len(rows) < 2:
        return []

    ordered = sorted(rows, key=lambda r: r.asof)
    gaps: list[dict] = []
    for prev, cur in zip(ordered, ordered[1:]):
        business_days = pd.bdate_range(prev.asof, cur.asof)
        missing = max(0, len(business_days) - 2)  # 양끝점 제외
        if missing >= max_gap_days:
            gaps.append(
                {
                    "index_code": cur.index_code,
                    "start": prev.asof.isoformat(),
                    "end": cur.asof.isoformat(),
                    "missing_business_days": missing,
                }
            )
    return gaps


def run_index_backfill(conn, period: str = DEFAULT_PERIOD) -> dict:
    inserted = 0
    gaps: list[dict] = []
    errors: list[dict] = []

    for index_code in BENCHMARK_INDEXES:
        try:
            rows = fetch_index_history(index_code, period=period)
            if not rows:
                continue
            upsert_index_daily(conn, rows)
            conn.commit()
            inserted += len(rows)
            found = find_missing_business_days(rows)
            if found:
                gaps.extend(found)
                logger.warning("%s: detected %d continuity gaps", index_code, len(found))
        except Exception as exc:
            conn.rollback()
            logger.error("index history failed %s: %s", index_code, exc, exc_info=True)
            errors.append(
                {
                    "index_code": index_code,
                    "error": str(exc),
                    "ts": datetime.utcnow().isoformat(),
                }
            )

    return {"indexes": list(BENCHMARK_INDEXES), "rows": inserted, "gaps": gaps, "errors": errors}


def _load_secrets_if_needed() -> None:
    if os.environ.get("DB_PASSWORD"):
        return
    try:
        import tomllib
        from pathlib import Path

        p = Path(__file__).resolve().parent.parent / ".streamlit" / "secrets.toml"
        if p.exists():
            with open(p, "rb") as f:
                secrets = tomllib.load(f)
            for key in ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME"):
                if key in secrets and not os.environ.get(key):
                    os.environ[key] = str(secrets[key])
    except Exception:
        return


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    _load_secrets_if_needed()
    period = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PERIOD
    with get_conn() as conn:
        result = run_index_backfill(conn, period=period)
    print(
        f"index_daily 백필 완료: rows={result['rows']} "
        f"gaps={len(result['gaps'])} errors={len(result['errors'])}"
    )
