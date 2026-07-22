"""
backfill.py — 가격 이력 누락/부족 종목 자동 탐지 + 백필 (1회용/운영)

PR-1: 관심종목이 늘 때마다 신규 종목의 가격 이력이 비어 대시보드에 ₩0/공백으로 뜨는 문제.
전체 재수집 대신 '누락분만' 백필한다.

순서:
  1. 점검: watchlist active vs prices_daily → 가격이 없거나 부족(MIN_ROWS 미만)하거나
           오래된(STALE_DAYS 초과) 종목 자동 탐지.
  2. 백필: 해당 종목만 2년치 가격 수집 (KR=pykrx, US=yfinance) → upsert.
     true backtest 준비 점검 시 `--5y`로 5년치까지 확장 가능.
  3. 재계산: 영향받은 종목 indicators_daily → quant_scores 재계산.
           (퀀트는 유니버스 상대 점수라 전체 재계산이 정확 → 전체 종목 대상)

실행:
  python -m src.backfill            # 누락분 탐지 후 백필+재계산
  python -m src.backfill --check    # 점검만(읽기 전용, 백필 안 함)
  python -m src.backfill --5y       # true backtest 준비용 5년 가격 점검/백필

자동 주문 없음.
"""

from __future__ import annotations

import logging
import sys
from datetime import date, datetime, timedelta

import psycopg

from src.compute_indicators import recompute_indicators_to_db
from src.db import (
    get_conn,
    log_run_finish,
    log_run_start,
    upsert_price_daily,
    upsert_quant_scores,
)
from src.compute_quant import compute_quant_universe
from src.schemas import PriceDailyRow
from src.freshness import today_kst

logger = logging.getLogger(__name__)

MIN_ROWS: int = 200       # SMA200·모멘텀 12M에 필요한 최소 가격 행 수
STALE_DAYS: int = 7       # 최신 가격이 이 일수보다 오래되면 백필 대상
TRADING_DAYS_PER_YEAR_FLOOR: int = 240  # 5년 백테스트 준비도 점검용 완화 기준


def _required_rows(min_rows: int, required_years: int | None) -> int:
    if not required_years:
        return min_rows
    return max(min_rows, required_years * TRADING_DAYS_PER_YEAR_FLOOR)


def detect_gap_tickers(
    conn: psycopg.Connection,
    min_rows: int = MIN_ROWS,
    stale_days: int = STALE_DAYS,
    required_years: int | None = None,
) -> list[dict]:
    """
    가격 이력이 없거나/부족하거나/오래된 active 종목 목록.
    반환: [{ticker, market, name, reason, rows, last_date}]
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT w.ticker, w.market, w.name,
                   COALESCE(p.n, 0)        AS rows,
                   p.last_date             AS last_date
            FROM watchlist w
            LEFT JOIN (
                SELECT ticker, count(*) AS n, max(date) AS last_date
                FROM prices_daily WHERE close IS NOT NULL GROUP BY ticker
            ) p USING (ticker)
            WHERE w.active = TRUE
            ORDER BY rows ASC, w.ticker
        """)
        rows = [dict(r) for r in cur.fetchall()]

    today = today_kst()
    min_required = _required_rows(min_rows, required_years)
    gaps: list[dict] = []
    for r in rows:
        n = int(r["rows"] or 0)
        last = r["last_date"]
        reason = None
        if n == 0:
            reason = "가격 없음"
        elif n < min_required:
            if required_years:
                reason = f"가격 부족({required_years}년 백테스트 준비 미달: {n}행<{min_required})"
            else:
                reason = f"가격 부족({n}행<{min_required})"
        elif last is not None and (today - last).days > stale_days:
            reason = f"오래됨(last={last})"
        if reason:
            gaps.append({
                "ticker": r["ticker"], "market": r["market"], "name": r["name"],
                "reason": reason, "rows": n, "last_date": str(last) if last else None,
            })
    return gaps


def _backfill_one(ticker: str, market: str, years: int = 2) -> list[PriceDailyRow]:
    """단일 종목 N년치 가격 수집."""
    if market == "KR":
        from src.ingest_kr import fetch_kr_prices
        rows = fetch_kr_prices(ticker, lookback_days=years * 366)
    else:
        from src.ingest_us import fetch_us_prices
        rows = fetch_us_prices(ticker, period=f"{years}y")
    return rows


def backfill_single(ticker: str, market: str) -> dict:
    """
    PR-3: 신규 종목 1개 즉시 백필 — 가격 2년치 + 지표 + (유니버스)퀀트 재계산.
    대시보드에서 종목 추가 직후 백그라운드로 호출. 자체 DB 연결 사용(스레드 안전).
    반환: {"ticker", "prices", "indicators", "quant", "ok"}
    """
    _load_secrets_if_needed()
    from src.compute_indicators import recompute_indicators_to_db
    from src.compute_quant import compute_quant_universe

    result = {"ticker": ticker, "prices": 0, "indicators": 0, "quant": 0, "ok": False}
    try:
        with get_conn() as conn:
            rows = _backfill_one(ticker, market)
            if rows:
                upsert_price_daily(conn, rows)
                conn.commit()
                result["prices"] = len(rows)
            try:
                result["indicators"] = recompute_indicators_to_db(conn, [ticker])
            except Exception as exc:
                conn.rollback()
                logger.warning("backfill_single 지표 실패 %s: %s", ticker, exc)
            # 퀀트는 유니버스 상대점수 → active 전체 재계산
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT ticker FROM watchlist WHERE active=TRUE ORDER BY ticker")
                    all_tickers = [r["ticker"] for r in cur.fetchall()]
                qrows = compute_quant_universe(all_tickers, conn)
                if qrows:
                    upsert_quant_scores(conn, qrows)
                    conn.commit()
                    result["quant"] = len(qrows)
            except Exception as exc:
                conn.rollback()
                logger.warning("backfill_single 퀀트 실패 %s: %s", ticker, exc)
            result["ok"] = result["prices"] > 0
        logger.info("backfill_single %s: prices=%d indicators=%d quant=%d",
                    ticker, result["prices"], result["indicators"], result["quant"])
    except Exception as exc:
        logger.error("backfill_single 실패 %s: %s", ticker, exc, exc_info=True)
    return result


def run_backfill(check_only: bool = False, required_years: int | None = None) -> dict:
    """누락 종목 탐지 → (check_only가 아니면) 백필 + 지표·퀀트 재계산."""
    errors: list[dict] = []
    with get_conn() as conn:
        run_id = log_run_start(conn, "backfill")
        status = "success"

        gaps = detect_gap_tickers(conn, required_years=required_years)
        logger.info("점검: 백필 필요 종목 %d개", len(gaps))
        for g in gaps:
            logger.info("  - %s (%s) %s | rows=%d last=%s",
                        g["ticker"], g["market"], g["reason"], g["rows"], g["last_date"])

        if check_only:
            log_run_finish(conn, run_id, status="success", errors=[])
            return {"gaps": gaps, "backfilled": 0, "check_only": True}

        # 1) 백필 (종목 단위 격리)
        backfilled = 0
        affected: list[str] = []
        for g in gaps:
            tk = g["ticker"]
            try:
                price_rows = _backfill_one(tk, g["market"], years=required_years or 2)
                if price_rows:
                    upsert_price_daily(conn, price_rows)
                    conn.commit()
                    backfilled += 1
                    affected.append(tk)
                    logger.info("백필 완료 %s: %d행", tk, len(price_rows))
                else:
                    logger.warning("백필 0행 %s", tk)
                    errors.append({"step": "backfill", "ticker": tk, "error": "0 rows", "ts": datetime.utcnow().isoformat()})
            except Exception as exc:
                conn.rollback()
                logger.error("백필 실패 %s: %s", tk, exc, exc_info=True)
                errors.append({"step": "backfill", "ticker": tk, "error": str(exc), "ts": datetime.utcnow().isoformat()})

        # 2) 재계산 — 지표는 영향 종목만, 퀀트는 유니버스 상대점수라 전체
        n_ind = n_quant = 0
        if affected:
            try:
                n_ind = recompute_indicators_to_db(conn, affected)
            except Exception as exc:
                conn.rollback()
                errors.append({"step": "indicators", "error": str(exc), "ts": datetime.utcnow().isoformat()})
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT ticker FROM watchlist WHERE active=TRUE ORDER BY ticker")
                    all_tickers = [r["ticker"] for r in cur.fetchall()]
                qrows = compute_quant_universe(all_tickers, conn)
                if qrows:
                    upsert_quant_scores(conn, qrows)
                    conn.commit()
                    n_quant = len(qrows)
            except Exception as exc:
                conn.rollback()
                errors.append({"step": "quant", "error": str(exc), "ts": datetime.utcnow().isoformat()})

        if errors:
            status = "partial" if backfilled else "failed"
        log_run_finish(conn, run_id, status=status, errors=errors)
        logger.info("백필 완료: %d종목 백필, indicators=%d quant=%d, 에러=%d",
                    backfilled, n_ind, n_quant, len(errors))
        return {"gaps": gaps, "backfilled": backfilled, "indicators": n_ind,
                "quant": n_quant, "errors": errors}


def _load_secrets_if_needed() -> None:
    """로컬 실행 편의: DB_* 미설정 시 .streamlit/secrets.toml에서 로드."""
    import os
    if os.environ.get("DB_PASSWORD"):
        return
    try:
        import tomllib
        from pathlib import Path
        p = Path(__file__).resolve().parent.parent / ".streamlit" / "secrets.toml"
        if p.exists():
            with open(p, "rb") as f:
                s = tomllib.load(f)
            for k in ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME"):
                if k in s and not os.environ.get(k):
                    os.environ[k] = str(s[k])
    except Exception:
        pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    _load_secrets_if_needed()
    check = "--check" in sys.argv
    required_years = 5 if "--5y" in sys.argv else None
    result = run_backfill(check_only=check, required_years=required_years)
    print(f"\n백필 필요 종목: {len(result['gaps'])}개")
    for g in result["gaps"]:
        print(f"  - {g['ticker']} ({g['market']}) {g['reason']}")
    if not check:
        print(f"백필 완료: {result['backfilled']}종목 / indicators={result.get('indicators')} quant={result.get('quant')}")
