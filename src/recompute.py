"""
recompute.py — 기존 prices_daily 기준 지표·퀀트 재계산·저장 (1회용)

배경: prices_daily에는 2년치가 이미 있으나 indicators_daily / quant_scores가
      비어 있다(저장 경로 문제). 외부 시세 재수집 없이 DB 데이터만으로
      indicators_daily → quant_scores 순서로 재계산하고 저장한다.

순서:
  1. recompute_indicators_to_db(conn)  : prices_daily → indicators_daily (종목별 commit)
  2. recompute_quant_to_db(conn)       : compute_quant_universe → quant_scores (commit)

실행: python -m src.recompute

"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import psycopg

from src.compute_indicators import recompute_indicators_to_db
from src.compute_quant import compute_quant_universe
from src.db import get_conn, log_run_finish, log_run_start, upsert_quant_scores

logger = logging.getLogger(__name__)


def _active_tickers(conn: psycopg.Connection) -> list[str]:
    """watchlist active 종목. 없으면 prices_daily에 존재하는 종목으로 폴백."""
    with conn.cursor() as cur:
        cur.execute("SELECT ticker FROM watchlist WHERE active = TRUE ORDER BY ticker")
        rows = [r["ticker"] for r in cur.fetchall()]
    if rows:
        return rows
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT ticker FROM prices_daily ORDER BY ticker")
        return [r["ticker"] for r in cur.fetchall()]


def recompute_quant_to_db(conn: psycopg.Connection, tickers: list[str]) -> int:
    """compute_quant_universe → quant_scores upsert(+commit). 저장 행 수 반환."""
    rows = compute_quant_universe(tickers, conn)
    if rows:
        upsert_quant_scores(conn, rows)
        conn.commit()
    filtered = sum(1 for r in rows if r.composite is None)
    logger.info("quant_scores upsert %d행 (필터 제외 %d) (commit)", len(rows), filtered)
    return len(rows)


def run_recompute() -> dict:
    """indicators → quant 재계산. runs 기록. 반환 {indicators, quant, errors}."""
    errors: list[dict] = []
    n_ind = 0
    n_quant = 0
    status = "success"

    with get_conn() as conn:
        run_id = log_run_start(conn, "recompute")
        logger.info("=== recompute 시작 run_id=%d ===", run_id)

        tickers = _active_tickers(conn)
        logger.info("대상 종목 %d개", len(tickers))

        # 1) 지표
        try:
            n_ind = recompute_indicators_to_db(conn, tickers)
        except Exception as exc:
            conn.rollback()
            logger.error("indicators 재계산 실패: %s", exc, exc_info=True)
            errors.append({"step": "recompute_indicators", "error": str(exc),
                           "ts": datetime.utcnow().isoformat()})

        # 2) 퀀트 (지표가 일부라도 저장된 뒤 실행)
        try:
            n_quant = recompute_quant_to_db(conn, tickers)
        except Exception as exc:
            conn.rollback()
            logger.error("quant 재계산 실패: %s", exc, exc_info=True)
            errors.append({"step": "recompute_quant", "error": str(exc),
                           "ts": datetime.utcnow().isoformat()})

        if errors:
            status = "partial" if (n_ind or n_quant) else "failed"

        log_run_finish(conn, run_id, status=status, errors=errors)
        logger.info("=== recompute 완료 status=%s ===", status)

    return {"indicators": n_ind, "quant": n_quant, "errors": errors}


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    result = run_recompute()
    logger.info(
        "recompute 결과: indicators %d종목 / quant %d행 / 에러 %d건",
        result["indicators"], result["quant"], len(result["errors"]),
    )
