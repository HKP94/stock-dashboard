"""
ingest_index_history.py — 장기 벤치마크 지수(5년) 백필

true backtest 비교용 벤치마크 시계열을 별도 테이블(index_daily)에 저장한다.
latest snapshot 성격의 market_daily와 분리해 §F7 분리 원칙을 지킨다.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf
from tenacity import before_sleep_log, retry, stop_after_attempt, wait_exponential

from src.db import get_conn, upsert_index_daily
from src.external_timeout import run_with_timeout
from src.schemas import IndexDailyRow

logger = logging.getLogger(__name__)

BENCHMARK_INDEXES: tuple[str, ...] = ("^KS11", "^GSPC", "^IXIC")
DEFAULT_PERIOD = "5y"
MAX_EXPECTED_BUSINESS_GAP = 5
YFINANCE_TIMEOUT_SECONDS = 20.0


def _safe_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
        return None if np.isnan(f) else f
    except (TypeError, ValueError):
        return None


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _yf_history(index_code: str, period: str) -> pd.DataFrame:
    return run_with_timeout(YFINANCE_TIMEOUT_SECONDS, lambda: yf.Ticker(index_code).history(period=period))


def fetch_index_history(index_code: str, period: str = DEFAULT_PERIOD) -> list[IndexDailyRow]:
    df = _yf_history(index_code, period)
    if df.empty:
        logger.warning("%s: index history empty", index_code)
        return []

    rows: list[IndexDailyRow] = []
    seen: set[date] = set()
    for idx, row in df.iterrows():
        asof = idx.date() if hasattr(idx, "date") else date.fromisoformat(str(idx)[:10])
        if asof in seen:
            continue
        close = _safe_float(row.get("Close"))
        if close is None:
            continue
        seen.add(asof)
        rows.append(IndexDailyRow(index_code=index_code, asof=asof, close=close))
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
