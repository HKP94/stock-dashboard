"""
db.py — Postgres 연결·upsert 헬퍼·실행 로그

접속 정보는 환경변수 DATABASE_URL 에서만 읽는다.
외부에서 시크릿을 인자로 받거나 하드코딩하지 않는다.

사용 예:
    from src.db import get_conn, upsert_price_daily, log_run
    with get_conn() as conn:
        upsert_price_daily(conn, rows)
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime
from typing import Generator

import psycopg
from psycopg.rows import dict_row

from src.schemas import (
    AnalystRow,
    FundamentalsRow,
    IndicatorDailyRow,
    MarketDailyRow,
    NewsAnalysisRow,
    NewsRawRow,
    PortfolioRow,
    PortfolioSnapshotRow,
    PriceDailyRow,
    QuantScoresRow,
    RunRow,
    ValuationRow,
    WatchlistRow,
)

logger = logging.getLogger(__name__)


def _get_dsn() -> str:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL 환경변수가 설정되지 않았습니다.")
    return dsn


@contextmanager
def get_conn() -> Generator[psycopg.Connection, None, None]:
    """자동 커밋·롤백 컨텍스트 매니저."""
    with psycopg.connect(_get_dsn(), row_factory=dict_row) as conn:
        yield conn


# ──────────────────────────────────────────────────────────────
# 내부 헬퍼
# ──────────────────────────────────────────────────────────────

def _to_json(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _execute_upsert(
    conn: psycopg.Connection,
    sql: str,
    params: tuple,
) -> None:
    with conn.cursor() as cur:
        cur.execute(sql, params)


# ──────────────────────────────────────────────────────────────
# upsert 헬퍼 (§5.1 테이블별)
# ──────────────────────────────────────────────────────────────

def upsert_watchlist(conn: psycopg.Connection, rows: list[WatchlistRow]) -> None:
    sql = """
        INSERT INTO watchlist (ticker, name, market, sector, is_holding, active)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (ticker) DO UPDATE SET
            name       = EXCLUDED.name,
            market     = EXCLUDED.market,
            sector     = EXCLUDED.sector,
            is_holding = EXCLUDED.is_holding,
            active     = EXCLUDED.active
    """
    with conn.cursor() as cur:
        cur.executemany(
            sql,
            [(r.ticker, r.name, r.market, r.sector, r.is_holding, r.active) for r in rows],
        )
    logger.debug("upsert_watchlist: %d rows", len(rows))


def upsert_price_daily(conn: psycopg.Connection, rows: list[PriceDailyRow]) -> None:
    sql = """
        INSERT INTO prices_daily (ticker, date, open, high, low, close, volume, source)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (ticker, date) DO UPDATE SET
            open   = EXCLUDED.open,
            high   = EXCLUDED.high,
            low    = EXCLUDED.low,
            close  = EXCLUDED.close,
            volume = EXCLUDED.volume,
            source = EXCLUDED.source,
            fetched_at = now()
    """
    with conn.cursor() as cur:
        cur.executemany(
            sql,
            [(r.ticker, r.date, r.open, r.high, r.low, r.close, r.volume, r.source) for r in rows],
        )
    logger.debug("upsert_price_daily: %d rows", len(rows))


def upsert_indicators_daily(conn: psycopg.Connection, rows: list[IndicatorDailyRow]) -> None:
    sql = """
        INSERT INTO indicators_daily
            (ticker, date, sma20, sma50, sma200, rsi14, disparity20, slope50, slope200, is_aligned)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (ticker, date) DO UPDATE SET
            sma20       = EXCLUDED.sma20,
            sma50       = EXCLUDED.sma50,
            sma200      = EXCLUDED.sma200,
            rsi14       = EXCLUDED.rsi14,
            disparity20 = EXCLUDED.disparity20,
            slope50     = EXCLUDED.slope50,
            slope200    = EXCLUDED.slope200,
            is_aligned  = EXCLUDED.is_aligned
    """
    with conn.cursor() as cur:
        cur.executemany(
            sql,
            [
                (
                    r.ticker, r.date, r.sma20, r.sma50, r.sma200,
                    r.rsi14, r.disparity20, r.slope50, r.slope200, r.is_aligned,
                )
                for r in rows
            ],
        )
    logger.debug("upsert_indicators_daily: %d rows", len(rows))


def upsert_fundamentals(conn: psycopg.Connection, rows: list[FundamentalsRow]) -> None:
    sql = """
        INSERT INTO fundamentals
            (ticker, period_type, period_end, revenue, op_income, op_margin, net_income, source)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (ticker, period_type, period_end) DO UPDATE SET
            revenue    = EXCLUDED.revenue,
            op_income  = EXCLUDED.op_income,
            op_margin  = EXCLUDED.op_margin,
            net_income = EXCLUDED.net_income,
            source     = EXCLUDED.source
    """
    with conn.cursor() as cur:
        cur.executemany(
            sql,
            [
                (r.ticker, r.period_type, r.period_end, r.revenue, r.op_income, r.op_margin, r.net_income, r.source)
                for r in rows
            ],
        )
    logger.debug("upsert_fundamentals: %d rows", len(rows))


def upsert_valuation(conn: psycopg.Connection, rows: list[ValuationRow]) -> None:
    sql = """
        INSERT INTO valuation
            (ticker, asof, per_t, per_f, pbr, ev_ebitda, roe, roa, debt_ratio, rev_growth)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (ticker, asof) DO UPDATE SET
            per_t      = EXCLUDED.per_t,
            per_f      = EXCLUDED.per_f,
            pbr        = EXCLUDED.pbr,
            ev_ebitda  = EXCLUDED.ev_ebitda,
            roe        = EXCLUDED.roe,
            roa        = EXCLUDED.roa,
            debt_ratio = EXCLUDED.debt_ratio,
            rev_growth = EXCLUDED.rev_growth
    """
    with conn.cursor() as cur:
        cur.executemany(
            sql,
            [
                (r.ticker, r.asof, r.per_t, r.per_f, r.pbr, r.ev_ebitda, r.roe, r.roa, r.debt_ratio, r.rev_growth)
                for r in rows
            ],
        )
    logger.debug("upsert_valuation: %d rows", len(rows))


def upsert_analyst(conn: psycopg.Connection, rows: list[AnalystRow]) -> None:
    sql = """
        INSERT INTO analyst (ticker, asof, rating, target_price, upside, n_analysts)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (ticker, asof) DO UPDATE SET
            rating       = EXCLUDED.rating,
            target_price = EXCLUDED.target_price,
            upside       = EXCLUDED.upside,
            n_analysts   = EXCLUDED.n_analysts
    """
    with conn.cursor() as cur:
        cur.executemany(
            sql,
            [(r.ticker, r.asof, r.rating, r.target_price, r.upside, r.n_analysts) for r in rows],
        )
    logger.debug("upsert_analyst: %d rows", len(rows))


def insert_news_raw(conn: psycopg.Connection, rows: list[NewsRawRow]) -> int:
    """url_hash 충돌 시 무시(dedupe). 실제 삽입된 행 수 반환."""
    sql = """
        INSERT INTO news_raw (ticker, source, published_at, title, body, url, url_hash)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (url_hash) DO NOTHING
    """
    inserted = 0
    with conn.cursor() as cur:
        for r in rows:
            cur.execute(
                sql,
                (r.ticker, r.source, r.published_at, r.title, r.body, r.url, r.url_hash),
            )
            inserted += cur.rowcount
    logger.debug("insert_news_raw: %d new / %d total", inserted, len(rows))
    return inserted


def upsert_news_analysis(conn: psycopg.Connection, rows: list[NewsAnalysisRow]) -> None:
    sql = """
        INSERT INTO news_analysis
            (ticker, asof, sentiment, sentiment_score, summary_md, payload, n_articles, model, based_on)
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
        ON CONFLICT (ticker, asof) DO UPDATE SET
            sentiment       = EXCLUDED.sentiment,
            sentiment_score = EXCLUDED.sentiment_score,
            summary_md      = EXCLUDED.summary_md,
            payload         = EXCLUDED.payload,
            n_articles      = EXCLUDED.n_articles,
            model           = EXCLUDED.model,
            based_on        = EXCLUDED.based_on
    """
    with conn.cursor() as cur:
        cur.executemany(
            sql,
            [
                (
                    r.ticker, r.asof, r.sentiment, r.sentiment_score, r.summary_md,
                    _to_json(r.payload), r.n_articles, r.model, r.based_on,
                )
                for r in rows
            ],
        )
    logger.debug("upsert_news_analysis: %d rows", len(rows))


def upsert_quant_scores(conn: psycopg.Connection, rows: list[QuantScoresRow]) -> None:
    sql = """
        INSERT INTO quant_scores
            (ticker, asof, momentum, value, quality, growth, sentiment, composite, flags)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (ticker, asof) DO UPDATE SET
            momentum  = EXCLUDED.momentum,
            value     = EXCLUDED.value,
            quality   = EXCLUDED.quality,
            growth    = EXCLUDED.growth,
            sentiment = EXCLUDED.sentiment,
            composite = EXCLUDED.composite,
            flags     = EXCLUDED.flags
    """
    with conn.cursor() as cur:
        cur.executemany(
            sql,
            [
                (
                    r.ticker, r.asof, r.momentum, r.value, r.quality,
                    r.growth, r.sentiment, r.composite, _to_json(r.flags),
                )
                for r in rows
            ],
        )
    logger.debug("upsert_quant_scores: %d rows", len(rows))


def upsert_portfolio(conn: psycopg.Connection, rows: list[PortfolioRow]) -> None:
    sql = """
        INSERT INTO portfolio
            (ticker, qty, avg_price, cur_price, eval_amount, pnl, pnl_pct, asof)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (ticker, asof) DO UPDATE SET
            qty         = EXCLUDED.qty,
            avg_price   = EXCLUDED.avg_price,
            cur_price   = EXCLUDED.cur_price,
            eval_amount = EXCLUDED.eval_amount,
            pnl         = EXCLUDED.pnl,
            pnl_pct     = EXCLUDED.pnl_pct
    """
    with conn.cursor() as cur:
        cur.executemany(
            sql,
            [
                (r.ticker, r.qty, r.avg_price, r.cur_price, r.eval_amount, r.pnl, r.pnl_pct, r.asof)
                for r in rows
            ],
        )
    logger.debug("upsert_portfolio: %d rows", len(rows))


def upsert_portfolio_snapshot(conn: psycopg.Connection, row: PortfolioSnapshotRow) -> None:
    sql = """
        INSERT INTO portfolio_snapshot
            (asof, total_value, total_cost, total_pnl, cash, payload)
        VALUES (%s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (asof) DO UPDATE SET
            total_value = EXCLUDED.total_value,
            total_cost  = EXCLUDED.total_cost,
            total_pnl   = EXCLUDED.total_pnl,
            cash        = EXCLUDED.cash,
            payload     = EXCLUDED.payload
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (row.asof, row.total_value, row.total_cost, row.total_pnl, row.cash, _to_json(row.payload)),
        )
    logger.debug("upsert_portfolio_snapshot: asof=%s", row.asof)


def upsert_market_daily(conn: psycopg.Connection, row: MarketDailyRow) -> None:
    sql = """
        INSERT INTO market_daily
            (asof, kospi, kosdaq, sp500, nasdaq, vix, usdkrw, ust10y, summary_md, payload)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (asof) DO UPDATE SET
            kospi      = EXCLUDED.kospi,
            kosdaq     = EXCLUDED.kosdaq,
            sp500      = EXCLUDED.sp500,
            nasdaq     = EXCLUDED.nasdaq,
            vix        = EXCLUDED.vix,
            usdkrw     = EXCLUDED.usdkrw,
            ust10y     = EXCLUDED.ust10y,
            summary_md = EXCLUDED.summary_md,
            payload    = EXCLUDED.payload
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                row.asof, row.kospi, row.kosdaq, row.sp500, row.nasdaq,
                row.vix, row.usdkrw, row.ust10y, row.summary_md, _to_json(row.payload),
            ),
        )
    logger.debug("upsert_market_daily: asof=%s", row.asof)


# ──────────────────────────────────────────────────────────────
# 실행 로그 (runs 테이블)
# ──────────────────────────────────────────────────────────────

def log_run_start(conn: psycopg.Connection, kind: str) -> int:
    """runs 행을 삽입하고 run_id를 반환한다. 실행 도중 에러 기록에 사용."""
    sql = """
        INSERT INTO runs (kind, started_at, status)
        VALUES (%s, %s, 'running')
        RETURNING run_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (kind, datetime.utcnow()))
        row = cur.fetchone()
    assert row is not None
    run_id: int = row["run_id"]
    logger.info("run_start kind=%s run_id=%d", kind, run_id)
    return run_id


def log_run_finish(
    conn: psycopg.Connection,
    run_id: int,
    status: str,
    errors: list[dict] | None = None,
) -> None:
    """runs 행을 완료 상태로 업데이트한다."""
    sql = """
        UPDATE runs
        SET finished_at = %s,
            status      = %s,
            errors      = %s::jsonb
        WHERE run_id = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (datetime.utcnow(), status, _to_json(errors or []), run_id))
    logger.info("run_finish run_id=%d status=%s errors=%d", run_id, status, len(errors or []))


def log_run(
    conn: psycopg.Connection,
    row: RunRow,
) -> int:
    """완성된 RunRow를 한 번에 삽입한다. 단발성 호출용."""
    sql = """
        INSERT INTO runs (kind, started_at, finished_at, status, errors)
        VALUES (%s, %s, %s, %s, %s::jsonb)
        RETURNING run_id
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (row.kind, row.started_at, row.finished_at, row.status, _to_json(row.errors)),
        )
        result = cur.fetchone()
    assert result is not None
    run_id: int = result["run_id"]
    logger.info("log_run kind=%s status=%s run_id=%d", row.kind, row.status, run_id)
    return run_id
