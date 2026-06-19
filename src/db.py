"""
db.py — Postgres 연결·upsert 헬퍼·실행 로그

접속 정보는 개별 환경변수(DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME)에서만 읽는다.
비밀번호(DB_PASSWORD)는 하드코딩하지 않으며, 외부에서 시크릿을 인자로 받지 않는다.
Supabase Transaction Pooler 사용 시 prepare_threshold=None 필수.

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
from psycopg.types.numeric import FloatLoader, NumericBinaryLoader

from src.schemas import (
    AnalystRow,
    FundamentalsRow,
    IndexDailyRow,
    IndicatorDailyRow,
    MarketDailyRow,
    MarketNewsRow,
    MarketNewsSummaryRow,
    MacroIndicatorRow,
    MacroSummaryRow,
    NewsAnalysisRow,
    NewsRawRow,
    PortfolioRow,
    PortfolioSnapshotRow,
    PriceDailyRow,
    QuantScoresRow,
    RunRow,
    TickerContextRow,
    ValuationRow,
    WatchlistRow,
)

logger = logging.getLogger(__name__)


# 접속 기본값 (비밀번호 제외). 시크릿이 아니므로 기본값 허용.
_DB_DEFAULTS = {
    "DB_HOST": "aws-1-ap-northeast-2.pooler.supabase.com",
    "DB_PORT": "6543",
    "DB_USER": "postgres",
    "DB_NAME": "postgres",
}


def _get_conn_kwargs() -> dict:
    """개별 환경변수에서 psycopg.connect 인자를 구성한다. DB_PASSWORD는 필수(기본값 없음)."""
    password = os.environ.get("DB_PASSWORD")
    if not password:
        raise RuntimeError("DB_PASSWORD 환경변수가 설정되지 않았습니다.")
    return {
        "host": os.environ.get("DB_HOST", _DB_DEFAULTS["DB_HOST"]),
        "port": int(os.environ.get("DB_PORT", _DB_DEFAULTS["DB_PORT"])),
        "user": os.environ.get("DB_USER", _DB_DEFAULTS["DB_USER"]),
        "password": password,
        "dbname": os.environ.get("DB_NAME", _DB_DEFAULTS["DB_NAME"]),
    }


class _NumericBinaryFloatLoader(NumericBinaryLoader):
    """NUMERIC 바이너리 결과(기본 Decimal)를 float로 변환."""

    def load(self, data):  # type: ignore[override]
        return float(super().load(data))


def _register_float_loaders(conn: psycopg.Connection) -> None:
    """
    NUMERIC/DECIMAL 컬럼을 decimal.Decimal이 아니라 Python float로 반환하도록 등록.

    psycopg3는 NUMERIC을 기본 Decimal로 로드하는데, Decimal이 float·np.log·나눗셈에
    섞이면 compute_indicators/compute_quant가 TypeError로 죽는다(indicators_daily=0,
    quant_scores=0의 근본 원인). 텍스트(format 0)·바이너리(format 1) 양쪽 로더를 덮어
    모든 읽기에서 float로 통일한다.
    """
    conn.adapters.register_loader("numeric", FloatLoader)                # text
    conn.adapters.register_loader("numeric", _NumericBinaryFloatLoader)  # binary


@contextmanager
def get_conn() -> Generator[psycopg.Connection, None, None]:
    """자동 커밋·롤백 컨텍스트 매니저.

    Supabase Transaction Pooler는 서버측 prepared statement를 지원하지 않으므로
    prepare_threshold=None 으로 비활성화한다.
    NUMERIC 컬럼은 float로 반환되도록 로더를 등록한다(Decimal 혼용 금지).
    """
    with psycopg.connect(
        **_get_conn_kwargs(),
        row_factory=dict_row,
        prepare_threshold=None,
    ) as conn:
        _register_float_loaders(conn)
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


def upsert_index_daily(conn: psycopg.Connection, rows: list[IndexDailyRow]) -> None:
    sql = """
        INSERT INTO index_daily (index_code, asof, close, source)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (index_code, asof) DO UPDATE SET
            close      = EXCLUDED.close,
            source     = EXCLUDED.source,
            fetched_at = now()
    """
    with conn.cursor() as cur:
        cur.executemany(
            sql,
            [(r.index_code, r.asof, r.close, r.source) for r in rows],
        )
    logger.debug("upsert_index_daily: %d rows", len(rows))


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
            (ticker, period_type, period_end, revenue, op_income, op_margin, net_income, ocf, fcf, source)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (ticker, period_type, period_end) DO UPDATE SET
            revenue    = EXCLUDED.revenue,
            op_income  = EXCLUDED.op_income,
            op_margin  = EXCLUDED.op_margin,
            net_income = EXCLUDED.net_income,
            ocf        = EXCLUDED.ocf,
            fcf        = EXCLUDED.fcf,
            source     = EXCLUDED.source
    """
    with conn.cursor() as cur:
        cur.executemany(
            sql,
            [
                (r.ticker, r.period_type, r.period_end, r.revenue, r.op_income, r.op_margin, r.net_income, r.ocf, r.fcf, r.source)
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


def insert_market_news(conn: psycopg.Connection, rows: list[MarketNewsRow]) -> int:
    """url_hash 충돌 시 무시(dedupe). 실제 삽입된 행 수 반환."""
    sql = """
        INSERT INTO market_news (source, title, url, url_hash, published_at)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (url_hash) DO NOTHING
    """
    inserted = 0
    with conn.cursor() as cur:
        for r in rows:
            cur.execute(sql, (r.source, r.title, r.url, r.url_hash, r.published_at))
            inserted += cur.rowcount
    logger.debug("insert_market_news: %d new / %d total", inserted, len(rows))
    return inserted


def upsert_news_analysis(conn: psycopg.Connection, rows: list[NewsAnalysisRow]) -> None:
    sql = """
        INSERT INTO news_analysis
            (ticker, asof, sentiment, sentiment_score, summary_md, payload, n_articles, model, based_on, curated)
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s::jsonb)
        ON CONFLICT (ticker, asof) DO UPDATE SET
            sentiment       = EXCLUDED.sentiment,
            sentiment_score = EXCLUDED.sentiment_score,
            summary_md      = EXCLUDED.summary_md,
            payload         = EXCLUDED.payload,
            n_articles      = EXCLUDED.n_articles,
            model           = EXCLUDED.model,
            based_on        = EXCLUDED.based_on,
            -- 빈 큐레이션([])으로 덮어쓰지 않음(요약-only/폴백 재시도가 기존 큐레이션 보존)
            curated         = CASE WHEN EXCLUDED.curated = '[]'::jsonb
                                   THEN news_analysis.curated ELSE EXCLUDED.curated END
    """
    with conn.cursor() as cur:
        cur.executemany(
            sql,
            [
                (
                    r.ticker, r.asof, r.sentiment, r.sentiment_score, r.summary_md,
                    _to_json(r.payload), r.n_articles, r.model, r.based_on, _to_json(r.curated),
                )
                for r in rows
            ],
        )
    logger.debug("upsert_news_analysis: %d rows", len(rows))


def upsert_quant_scores(conn: psycopg.Connection, rows: list[QuantScoresRow]) -> None:
    sql = """
        INSERT INTO quant_scores
            (ticker, asof, momentum, value, quality, growth, sentiment, composite, fscore, flags)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (ticker, asof) DO UPDATE SET
            momentum  = EXCLUDED.momentum,
            value     = EXCLUDED.value,
            quality   = EXCLUDED.quality,
            growth    = EXCLUDED.growth,
            sentiment = EXCLUDED.sentiment,
            composite = EXCLUDED.composite,
            fscore    = EXCLUDED.fscore,
            flags     = EXCLUDED.flags
    """
    with conn.cursor() as cur:
        cur.executemany(
            sql,
            [
                (
                    r.ticker, r.asof, r.momentum, r.value, r.quality,
                    r.growth, r.sentiment, r.composite, r.fscore, _to_json(r.flags),
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
    # PR-4: summary_kr_md/summary_us_md는 COALESCE로 기존 값 보존(시황 단계가 별도로 채우므로
    # 지표 수집(ingest_market)이 시황을 NULL로 덮어쓰지 않게 한다).
    sql = """
        INSERT INTO market_daily
            (asof, kospi, kosdaq, sp500, nasdaq, vix, usdkrw, ust10y,
             summary_md, summary_kr_md, summary_us_md, payload)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (asof) DO UPDATE SET
            kospi         = EXCLUDED.kospi,
            kosdaq        = EXCLUDED.kosdaq,
            sp500         = EXCLUDED.sp500,
            nasdaq        = EXCLUDED.nasdaq,
            vix           = EXCLUDED.vix,
            usdkrw        = EXCLUDED.usdkrw,
            ust10y        = EXCLUDED.ust10y,
            summary_md    = COALESCE(EXCLUDED.summary_md,    market_daily.summary_md),
            summary_kr_md = COALESCE(EXCLUDED.summary_kr_md, market_daily.summary_kr_md),
            summary_us_md = COALESCE(EXCLUDED.summary_us_md, market_daily.summary_us_md),
            payload       = EXCLUDED.payload
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                row.asof, row.kospi, row.kosdaq, row.sp500, row.nasdaq,
                row.vix, row.usdkrw, row.ust10y,
                row.summary_md, row.summary_kr_md, row.summary_us_md, _to_json(row.payload),
            ),
        )
    logger.debug("upsert_market_daily: asof=%s", row.asof)


def upsert_market_news_summary(conn: psycopg.Connection, row: MarketNewsSummaryRow) -> None:
    sql = """
        INSERT INTO market_news_summary (summary_date, kr_summary, us_summary, global_summary)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (summary_date) DO UPDATE SET
            kr_summary     = EXCLUDED.kr_summary,
            us_summary     = EXCLUDED.us_summary,
            global_summary = EXCLUDED.global_summary
    """
    with conn.cursor() as cur:
        cur.execute(sql, (row.summary_date, row.kr_summary, row.us_summary, row.global_summary))
    logger.debug("upsert_market_news_summary: summary_date=%s", row.summary_date)


def upsert_macro_indicators(conn: psycopg.Connection, rows: list[MacroIndicatorRow]) -> None:
    sql = """
        INSERT INTO macro_indicators
            (indicator_code, indicator_name, region, asof, value, unit, source)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (indicator_code, asof) DO UPDATE SET
            indicator_name = EXCLUDED.indicator_name,
            region         = EXCLUDED.region,
            value          = EXCLUDED.value,
            unit           = EXCLUDED.unit,
            source         = EXCLUDED.source
    """
    with conn.cursor() as cur:
        cur.executemany(
            sql,
            [(r.indicator_code, r.indicator_name, r.region, r.asof, r.value, r.unit, r.source) for r in rows],
        )
    logger.debug("upsert_macro_indicators: %d rows", len(rows))


def upsert_macro_summary(conn: psycopg.Connection, row: MacroSummaryRow) -> None:
    sql = """
        INSERT INTO macro_summary
            (summary_date, headline, support_view, oppose_view, watch_points, summary_md)
        VALUES (%s, %s, %s, %s, %s::jsonb, %s)
        ON CONFLICT (summary_date) DO UPDATE SET
            headline     = EXCLUDED.headline,
            support_view = EXCLUDED.support_view,
            oppose_view  = EXCLUDED.oppose_view,
            watch_points = EXCLUDED.watch_points,
            summary_md   = EXCLUDED.summary_md
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                row.summary_date,
                row.headline,
                row.support_view,
                row.oppose_view,
                _to_json(row.watch_points),
                row.summary_md,
            ),
        )
    logger.debug("upsert_macro_summary: summary_date=%s", row.summary_date)


def replace_ticker_context(conn: psycopg.Connection, row: TickerContextRow) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM ticker_context
            WHERE ticker = %s AND context_type = %s AND source = %s AND valid_from = %s
            """,
            (row.ticker, row.context_type, row.source, row.valid_from),
        )
        cur.execute(
            """
            INSERT INTO ticker_context (ticker, context_type, content, source, valid_from, valid_until)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (row.ticker, row.context_type, row.content, row.source, row.valid_from, row.valid_until),
        )
    logger.debug("replace_ticker_context: %s %s %s", row.ticker, row.context_type, row.valid_from)


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
