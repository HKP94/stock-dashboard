"""
backfill.py — 가격 이력 2년치 일괄 적재 + 지표 재계산 (1회성 스크립트)

문제: prices_daily에 종목당 며칠치만 있어 모멘텀(252일)·SMA200·퀀트 점수가
      대부분 "데이터 부족". 과거 2년치를 한 번에 채워 정상 계산이 가능하게 한다.

흐름:
  1. watchlist active 종목 로드
  2. KR(.KS): pykrx 2년치 / US: yfinance 2년치 → prices_daily upsert
     (ingest_kr.fetch_kr_prices / ingest_us.fetch_us_prices 재사용)
  3. 종목 단위 try/except 격리, runs 테이블 기록
  4. 적재 후 compute_indicators 전체 종목 재계산 → indicators_daily

실행: python -m src.backfill   (한 번만 돌리는 스크립트)

⚠️ 투자 자문 아님 / 원금 손실 가능
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Optional

import pandas as pd
import psycopg

from src.compute_indicators import compute_indicators
from src.db import (
    get_conn,
    log_run_finish,
    log_run_start,
    upsert_indicators_daily,
    upsert_price_daily,
)
from src.ingest_kr import fetch_kr_prices
from src.ingest_us import fetch_us_prices

logger = logging.getLogger(__name__)

# ── 상수 ─────────────────────────────────────────────────────
KR_SLEEP_SEC: float = 1.0   # pykrx 레이트리밋 회피용 종목 간 대기
US_SLEEP_SEC: float = 0.3   # yfinance 과도 호출 방지


def _is_kr(ticker: str, market: Optional[str] = None) -> bool:
    if market:
        return market.upper() == "KR"
    return ticker.upper().endswith((".KS", ".KQ"))


def _get_active_tickers(conn: psycopg.Connection) -> list[dict]:
    """watchlist active 종목 (ticker, market) 목록."""
    sql = "SELECT ticker, market FROM watchlist WHERE active = TRUE ORDER BY ticker"
    with conn.cursor() as cur:
        cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]


def _load_price_df(ticker: str, conn: psycopg.Connection) -> pd.DataFrame:
    """prices_daily 전체 → DatetimeIndex DataFrame (compute_indicators 입력용)."""
    sql = "SELECT date, close, volume FROM prices_daily WHERE ticker = %s ORDER BY date ASC"
    with conn.cursor() as cur:
        cur.execute(sql, (ticker,))
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame(columns=["close", "volume"])
    df = pd.DataFrame([dict(r) for r in rows])
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")


def _err(step: str, ticker: str, exc: Exception) -> dict:
    return {
        "step": step,
        "ticker": ticker,
        "error": str(exc),
        "ts": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────────────────────
# 1단계: 가격 2년치 적재
# ──────────────────────────────────────────────────────────────

def backfill_prices(
    conn: psycopg.Connection,
    tickers: list[dict],
    errors: list[dict],
) -> int:
    """
    종목별 2년치 OHLCV 수집 → prices_daily upsert.
    종목 단위 try/except. 성공 종목 수 반환.
    """
    ok = 0
    for entry in tickers:
        ticker = entry["ticker"]
        market = entry.get("market")
        try:
            if _is_kr(ticker, market):
                rows = fetch_kr_prices(ticker)   # 기본 lookback 730일(2년)
                sleep_sec = KR_SLEEP_SEC
            else:
                rows = fetch_us_prices(ticker)   # 기본 period="2y"
                sleep_sec = US_SLEEP_SEC

            if rows:
                upsert_price_daily(conn, rows)
                ok += 1
                logger.info("%s: %d행 적재", ticker, len(rows))
            else:
                logger.warning("%s: 가격 0행 — 스킵", ticker)
        except Exception as exc:
            logger.error("%s: 가격 백필 실패 — %s", ticker, exc, exc_info=True)
            errors.append(_err("backfill_price", ticker, exc))
            sleep_sec = KR_SLEEP_SEC if _is_kr(ticker, market) else US_SLEEP_SEC

        time.sleep(sleep_sec)  # 레이트리밋 회피
    return ok


# ──────────────────────────────────────────────────────────────
# 2단계: 지표 재계산
# ──────────────────────────────────────────────────────────────

def recompute_indicators(
    conn: psycopg.Connection,
    tickers: list[dict],
    errors: list[dict],
) -> int:
    """적재된 가격으로 전체 종목 지표 재계산 → indicators_daily upsert. 성공 종목 수 반환."""
    ok = 0
    for entry in tickers:
        ticker = entry["ticker"]
        try:
            price_df = _load_price_df(ticker, conn)
            rows = compute_indicators(ticker, price_df)
            if rows:
                upsert_indicators_daily(conn, rows)
                ok += 1
                logger.info("%s: 지표 %d행 재계산", ticker, len(rows))
            else:
                logger.warning("%s: 지표 계산 0행 (데이터 부족) — 스킵", ticker)
        except Exception as exc:
            logger.error("%s: 지표 재계산 실패 — %s", ticker, exc, exc_info=True)
            errors.append(_err("recompute_indicators", ticker, exc))
    return ok


# ──────────────────────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────────────────────

def run_backfill() -> dict:
    """
    전체 백필 실행. runs 테이블에 기록.
    반환: {"priced": int, "indicated": int, "errors": list}
    """
    errors: list[dict] = []
    priced = 0
    indicated = 0
    status = "success"

    with get_conn() as conn:
        run_id = log_run_start(conn, "backfill")
        logger.info("=== 백필 시작 run_id=%d ===", run_id)

        try:
            tickers = _get_active_tickers(conn)
            logger.info("유니버스 %d종목", len(tickers))

            priced = backfill_prices(conn, tickers, errors)
            logger.info("가격 백필 완료: %d/%d 종목", priced, len(tickers))

            indicated = recompute_indicators(conn, tickers, errors)
            logger.info("지표 재계산 완료: %d/%d 종목", indicated, len(tickers))

        except Exception as exc:
            logger.error("백필 치명적 오류: %s", exc, exc_info=True)
            errors.append(_err("backfill_fatal", "-", exc))
            status = "failed"

        if errors and status != "failed":
            status = "partial"

        log_run_finish(conn, run_id, status=status, errors=errors)
        logger.info("=== 백필 완료 status=%s errors=%d ===", status, len(errors))

    return {"priced": priced, "indicated": indicated, "errors": errors}


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    result = run_backfill()
    logger.info(
        "백필 결과: 가격 %d종목 / 지표 %d종목 / 에러 %d건",
        result["priced"], result["indicated"], len(result["errors"]),
    )
    print("\n⚠️ 투자 자문 아님 / 원금 손실 가능", file=sys.stderr)
