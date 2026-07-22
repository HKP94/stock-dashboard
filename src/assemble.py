"""
assemble.py — 종목 일일 레코드 조립 (PRD §5.2)

역할:
  DB에 적재된 오늘자 데이터를 종목별로 하나의 StockDailyRecord로 조립.
  Hermes 브리핑·텔레그램 발송이 이 출력을 직접 소비한다.

공개 API:
  assemble_daily(conn, asof=None) → list[StockDailyRecord]
  assemble_one(ticker, conn, asof=None) → StockDailyRecord | None

신호는 근거·신뢰도와 함께 표시되며 자동 주문을 실행하지 않습니다.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Optional

import psycopg

from src.db import get_conn, log_run_finish, log_run_start
from src.display_signals import compute_display_signals
from src.schemas import (
    AnalystView,
    FundamentalsView,
    NewsView,
    PriceView,
    QuantView,
    StockDailyRecord,
    ValuationView,
)
from src.freshness import today_kst

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# DB 조회 헬퍼 (각각 개별 패치 가능 → 테스트 격리)
# ──────────────────────────────────────────────────────────────

def _q_watchlist(conn: psycopg.Connection) -> list[dict]:
    """활성 종목 전체 목록."""
    sql = """
        SELECT ticker, name, market, sector, is_holding
        FROM watchlist
        WHERE active = TRUE
        ORDER BY ticker
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]


def _q_watchlist_one(ticker: str, conn: psycopg.Connection) -> Optional[dict]:
    """단일 종목 watchlist 행. 없거나 비활성이면 None."""
    sql = "SELECT ticker, name, market, sector, is_holding FROM watchlist WHERE ticker=%s AND active=TRUE"
    with conn.cursor() as cur:
        cur.execute(sql, (ticker,))
        row = cur.fetchone()
        return dict(row) if row else None


def _q_price_chg(ticker: str, conn: psycopg.Connection, asof: date) -> Optional[dict]:
    """당일 종가 + 전일 대비 등락률(%). 당일 가격 없으면 None."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT close FROM prices_daily WHERE ticker=%s AND date=%s",
            (ticker, asof),
        )
        today = cur.fetchone()

    if not today or today.get("close") is None:
        return None

    close = float(today["close"])

    with conn.cursor() as cur:
        cur.execute(
            "SELECT close FROM prices_daily WHERE ticker=%s AND date<%s ORDER BY date DESC LIMIT 1",
            (ticker, asof),
        )
        prev = cur.fetchone()

    prev_close = float(prev["close"]) if prev and prev.get("close") else None
    chg_pct = ((close - prev_close) / prev_close * 100) if prev_close and prev_close != 0 else None

    return {"close": close, "chg_pct": chg_pct}


def _q_indicators(ticker: str, conn: psycopg.Connection, asof: date) -> Optional[dict]:
    """당일 기술적 지표. 없으면 None."""
    sql = """
        SELECT rsi14, disparity20, is_aligned, slope50
        FROM indicators_daily
        WHERE ticker=%s AND date=%s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (ticker, asof))
        row = cur.fetchone()
        return dict(row) if row else None


def _q_fundamentals(ticker: str, conn: psycopg.Connection) -> dict:
    """
    rev_yoy (연간 매출 YoY), op_margin (최근 연간), last_q_rev_b (최근 분기 매출 billion).
    데이터 없으면 모두 None.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT revenue, op_margin FROM fundamentals WHERE ticker=%s AND period_type='annual' ORDER BY period_end DESC LIMIT 2",
            (ticker,),
        )
        ann = [dict(r) for r in cur.fetchall()]

    with conn.cursor() as cur:
        cur.execute(
            "SELECT revenue FROM fundamentals WHERE ticker=%s AND period_type='quarter' ORDER BY period_end DESC LIMIT 1",
            (ticker,),
        )
        qtr = cur.fetchone()

    rev_yoy: Optional[float] = None
    op_margin: Optional[float] = None
    last_q_rev_b: Optional[float] = None

    if ann:
        op_margin = ann[0].get("op_margin")
        if len(ann) >= 2:
            r0 = ann[0].get("revenue")
            r1 = ann[1].get("revenue")
            if r0 is not None and r1 and r1 != 0:
                rev_yoy = (r0 - r1) / abs(r1)

    if qtr and qtr.get("revenue"):
        last_q_rev_b = float(qtr["revenue"]) / 1e9

    return {"rev_yoy": rev_yoy, "op_margin": op_margin, "last_q_rev_b": last_q_rev_b}


def _q_valuation(ticker: str, conn: psycopg.Connection) -> Optional[dict]:
    """가장 최근 밸류에이션 스냅샷. 없으면 None."""
    sql = "SELECT per_t, per_f, pbr, ev_ebitda, roe, roa, debt_ratio, rev_growth FROM valuation WHERE ticker=%s ORDER BY asof DESC LIMIT 1"
    with conn.cursor() as cur:
        cur.execute(sql, (ticker,))
        row = cur.fetchone()
        return dict(row) if row else None


def _q_analyst(ticker: str, conn: psycopg.Connection) -> Optional[dict]:
    """가장 최근 애널리스트 컨센서스. 없으면 None."""
    sql = "SELECT rating, target_price, upside, source FROM analyst WHERE ticker=%s ORDER BY asof DESC LIMIT 1"
    with conn.cursor() as cur:
        cur.execute(sql, (ticker,))
        row = cur.fetchone()
        return dict(row) if row else None


def _q_news(ticker: str, conn: psycopg.Connection, asof: date) -> Optional[dict]:
    """당일 뉴스 분석 결과. 없으면 None."""
    sql = "SELECT sentiment, sentiment_score, summary_md, based_on FROM news_analysis WHERE ticker=%s AND asof=%s"
    with conn.cursor() as cur:
        cur.execute(sql, (ticker, asof))
        row = cur.fetchone()
        return dict(row) if row else None


def _q_quant(ticker: str, conn: psycopg.Connection, asof: date) -> Optional[dict]:
    """당일 퀀트 점수. 없으면 None."""
    sql = "SELECT momentum, value, quality, growth, sentiment, composite, flags FROM quant_scores WHERE ticker=%s AND asof=%s"
    with conn.cursor() as cur:
        cur.execute(sql, (ticker, asof))
        row = cur.fetchone()
        return dict(row) if row else None


# ──────────────────────────────────────────────────────────────
# Bulk 조회 헬퍼 (유니버스 전체를 테이블당 1쿼리로)
#   assemble_daily 전용. 연결 점유 시간을 분 → 초로 단축.
#   `ticker = ANY(%s)` 에 list를 넘기면 psycopg3가 Postgres 배열로 어댑트.
# ──────────────────────────────────────────────────────────────

def _bulk_prices(tickers: list[str], conn: psycopg.Connection, asof: date) -> dict[str, Optional[dict]]:
    """ticker → {close, chg_pct}. asof 당일 종가 없으면 None (단일 쿼리 버전과 동일 의미)."""
    out: dict[str, Optional[dict]] = {t: None for t in tickers}
    if not tickers:
        return out
    sql = """
        SELECT ticker, date, close
        FROM (
            SELECT ticker, date, close,
                   ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn
            FROM prices_daily
            WHERE ticker = ANY(%s) AND date <= %s
        ) t
        WHERE rn <= 2
        ORDER BY ticker, date DESC
    """
    by_ticker: dict[str, list[dict]] = {}
    with conn.cursor() as cur:
        cur.execute(sql, (tickers, asof))
        for r in cur.fetchall():
            by_ticker.setdefault(r["ticker"], []).append(dict(r))

    for t in tickers:
        rows = by_ticker.get(t, [])
        # rn=1 (가장 최근 ≤ asof)이 정확히 asof 당일이어야 종가 인정 (단일쿼리 _q_price_chg와 동일)
        if rows and rows[0]["date"] == asof and rows[0].get("close") is not None:
            close = float(rows[0]["close"])
            prev_close = (
                float(rows[1]["close"])
                if len(rows) > 1 and rows[1].get("close") is not None
                else None
            )
            chg_pct = ((close - prev_close) / prev_close * 100) if prev_close and prev_close != 0 else None
            out[t] = {"close": close, "chg_pct": chg_pct}
    return out


def _bulk_indicators(tickers: list[str], conn: psycopg.Connection, asof: date) -> dict[str, Optional[dict]]:
    """ticker → 당일 지표 dict. 없으면 None."""
    out: dict[str, Optional[dict]] = {t: None for t in tickers}
    if not tickers:
        return out
    sql = """
        SELECT ticker, rsi14, disparity20, is_aligned, slope50
        FROM indicators_daily
        WHERE ticker = ANY(%s) AND date = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (tickers, asof))
        for r in cur.fetchall():
            out[r["ticker"]] = dict(r)
    return out


def _bulk_fundamentals(tickers: list[str], conn: psycopg.Connection) -> dict[str, dict]:
    """ticker → {rev_yoy, op_margin, last_q_rev_b}. 단일쿼리 _q_fundamentals와 동일 로직."""
    out: dict[str, dict] = {t: {"rev_yoy": None, "op_margin": None, "last_q_rev_b": None} for t in tickers}
    if not tickers:
        return out
    sql = """
        SELECT ticker, period_type, period_end, revenue, op_margin
        FROM (
            SELECT ticker, period_type, period_end, revenue, op_margin,
                   ROW_NUMBER() OVER (PARTITION BY ticker, period_type ORDER BY period_end DESC) AS rn
            FROM fundamentals
            WHERE ticker = ANY(%s)
        ) t
        WHERE (period_type = 'annual' AND rn <= 2) OR (period_type = 'quarter' AND rn = 1)
        ORDER BY ticker, period_type, period_end DESC
    """
    ann: dict[str, list[dict]] = {}
    qtr: dict[str, dict] = {}
    with conn.cursor() as cur:
        cur.execute(sql, (tickers,))
        for r in cur.fetchall():
            if r["period_type"] == "annual":
                ann.setdefault(r["ticker"], []).append(dict(r))
            else:  # quarter — 첫 행이 최신
                qtr.setdefault(r["ticker"], dict(r))

    for t in tickers:
        a = ann.get(t, [])
        rev_yoy: Optional[float] = None
        op_margin: Optional[float] = None
        last_q_rev_b: Optional[float] = None
        if a:
            op_margin = a[0].get("op_margin")
            if len(a) >= 2:
                r0 = a[0].get("revenue")
                r1 = a[1].get("revenue")
                if r0 is not None and r1 and r1 != 0:
                    rev_yoy = (r0 - r1) / abs(r1)
        q = qtr.get(t)
        if q and q.get("revenue"):
            last_q_rev_b = float(q["revenue"]) / 1e9
        out[t] = {"rev_yoy": rev_yoy, "op_margin": op_margin, "last_q_rev_b": last_q_rev_b}
    return out


def _bulk_valuation(tickers: list[str], conn: psycopg.Connection) -> dict[str, Optional[dict]]:
    """ticker → 최신 밸류에이션 dict. 없으면 None."""
    out: dict[str, Optional[dict]] = {t: None for t in tickers}
    if not tickers:
        return out
    sql = """
        SELECT ticker, per_t, per_f, pbr, ev_ebitda, roe, roa, debt_ratio, rev_growth
        FROM (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY asof DESC) AS rn
            FROM valuation
            WHERE ticker = ANY(%s)
        ) t
        WHERE rn = 1
    """
    with conn.cursor() as cur:
        cur.execute(sql, (tickers,))
        for r in cur.fetchall():
            out[r["ticker"]] = dict(r)
    return out


def _bulk_analyst(tickers: list[str], conn: psycopg.Connection) -> dict[str, Optional[dict]]:
    """ticker → 최신 애널리스트 컨센서스 dict. 없으면 None."""
    out: dict[str, Optional[dict]] = {t: None for t in tickers}
    if not tickers:
        return out
    sql = """
        SELECT ticker, rating, target_price, upside, source
        FROM (
            SELECT ticker, rating, target_price, upside, source,
                   ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY asof DESC) AS rn
            FROM analyst
            WHERE ticker = ANY(%s)
        ) t
        WHERE rn = 1
    """
    with conn.cursor() as cur:
        cur.execute(sql, (tickers,))
        for r in cur.fetchall():
            out[r["ticker"]] = dict(r)
    return out


def _bulk_news(tickers: list[str], conn: psycopg.Connection, asof: date) -> dict[str, Optional[dict]]:
    """ticker → 당일 뉴스 분석 dict. 없으면 None."""
    out: dict[str, Optional[dict]] = {t: None for t in tickers}
    if not tickers:
        return out
    sql = """
        SELECT ticker, sentiment, sentiment_score, summary_md, based_on
        FROM news_analysis
        WHERE ticker = ANY(%s) AND asof = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (tickers, asof))
        for r in cur.fetchall():
            out[r["ticker"]] = dict(r)
    return out


def _bulk_quant(tickers: list[str], conn: psycopg.Connection, asof: date) -> dict[str, Optional[dict]]:
    """ticker → 당일 퀀트 점수 dict. 없으면 None."""
    out: dict[str, Optional[dict]] = {t: None for t in tickers}
    if not tickers:
        return out
    sql = """
        SELECT ticker, momentum, value, quality, growth, sentiment, composite, flags
        FROM quant_scores
        WHERE ticker = ANY(%s) AND asof = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (tickers, asof))
        for r in cur.fetchall():
            out[r["ticker"]] = dict(r)
    return out


# ──────────────────────────────────────────────────────────────
# 레코드 조립 (순수 함수)
# ──────────────────────────────────────────────────────────────

def _build_record(
    wl: dict,
    price: Optional[dict],
    ind: Optional[dict],
    fund: dict,
    val: Optional[dict],
    ana: Optional[dict],
    news: Optional[dict],
    quant: Optional[dict],
) -> StockDailyRecord:
    """
    조회 결과 dict들을 StockDailyRecord로 조립.
    결측 필드는 None (문자열 'N/A' 금지).
    """
    # PriceView: 가격 + indicators 병합
    price_view = PriceView(
        close=price.get("close") if price else None,
        chg_pct=price.get("chg_pct") if price else None,
        rsi14=ind.get("rsi14") if ind else None,
        disparity20=ind.get("disparity20") if ind else None,
        is_aligned=ind.get("is_aligned") if ind else None,
    )

    # FundamentalsView
    fund_view = FundamentalsView(
        rev_yoy=fund.get("rev_yoy"),
        op_margin=fund.get("op_margin"),
        last_q_rev_b=fund.get("last_q_rev_b"),
    )

    # ValuationView (per_f 우선, 없으면 per_t)
    val_view = ValuationView(
        per_f=val.get("per_f") or val.get("per_t") if val else None,
        pbr=val.get("pbr") if val else None,
        roe=val.get("roe") if val else None,
    )

    # AnalystView (target_price → target 필드명 변환)
    ana_view = AnalystView(
        rating=ana.get("rating") if ana else None,
        target=ana.get("target_price") if ana else None,
        upside=ana.get("upside") if ana else None,
        source=ana.get("source") if ana else None,
    )

    # NewsView: sentiment Literal 검증 후 할당
    _SENTIMENT_ALLOWED = {"긍정", "중립", "부정"}
    news_sentiment = None
    news_based_on = None
    if news:
        s = news.get("sentiment")
        news_sentiment = s if s in _SENTIMENT_ALLOWED else None
        b = news.get("based_on")
        news_based_on = b if b in ("recent", "fallback_old") else None

    news_view = NewsView(
        sentiment=news_sentiment,
        score=news.get("sentiment_score") if news else None,
        summary_md=news.get("summary_md") if news else None,
        based_on=news_based_on,
    )

    # QuantView: flags는 JSONB → list[str]
    quant_flags: list[str] = []
    if quant:
        raw_flags = quant.get("flags") or []
        if isinstance(raw_flags, str):
            try:
                raw_flags = json.loads(raw_flags)
            except (json.JSONDecodeError, ValueError):
                raw_flags = []
        quant_flags = [str(f) for f in raw_flags if f is not None]

    quant_view = QuantView(
        composite=quant.get("composite") if quant else None,
        momentum=quant.get("momentum") if quant else None,
        value=quant.get("value") if quant else None,
        quality=quant.get("quality") if quant else None,
        growth=quant.get("growth") if quant else None,
        sentiment=quant.get("sentiment") if quant else None,
        flags=quant_flags,
    )

    return StockDailyRecord(
        ticker=wl["ticker"],
        name=wl["name"],
        market=wl["market"],
        price=price_view,
        fundamentals=fund_view,
        valuation=val_view,
        analyst=ana_view,
        news=news_view,
        quant=quant_view,
        is_holding=bool(wl.get("is_holding", False)),
    )


# ──────────────────────────────────────────────────────────────
# 공개 API
# ──────────────────────────────────────────────────────────────

def assemble_one(
    ticker: str,
    conn: psycopg.Connection,
    asof: Optional[date] = None,
) -> Optional[StockDailyRecord]:
    """
    단일 종목 레코드 조립.
    watchlist에 없거나 비활성이면 None 반환.
    Hermes Q&A 응답·스모크 테스트용.
    """
    asof = asof or today_kst()
    wl = _q_watchlist_one(ticker, conn)
    if not wl:
        logger.debug("%s: watchlist 없음 또는 비활성 — skip", ticker)
        return None

    return _build_record(
        wl=wl,
        price=_q_price_chg(ticker, conn, asof),
        ind=_q_indicators(ticker, conn, asof),
        fund=_q_fundamentals(ticker, conn),
        val=_q_valuation(ticker, conn),
        ana=_q_analyst(ticker, conn),
        news=_q_news(ticker, conn, asof),
        quant=_q_quant(ticker, conn, asof),
    )


def assemble_daily(
    conn: psycopg.Connection,
    asof: Optional[date] = None,
) -> list[StockDailyRecord]:
    """
    활성 유니버스 전체 레코드 조립.

    Bulk 전략: 종목별 루프 쿼리(N×8) 대신 테이블당 1쿼리(총 8쿼리)로 전체 유니버스를
    한 번에 읽고 Python에서 ticker 기준 조인. 연결 점유 시간을 분 → 초로 단축하여
    Supabase Pooler idle timeout(연결 끊김 → "the connection is closed") 회피.
    조립(_build_record)은 메모리상 dict로만 수행 — DB 미접근, 종목 단위 try/except 격리.

    반환값의 신호는 표시 전용이며 주문 실행 경로가 없습니다.
    """
    asof = asof or today_kst()
    watchlist = _q_watchlist(conn)
    tickers = [w["ticker"] for w in watchlist]
    logger.info("assemble_daily: asof=%s 유니버스 %d종목 (bulk)", asof, len(tickers))
    if not tickers:
        return []

    # ── 테이블별 bulk 조회 (연결은 여기서만 사용) ──────────────
    prices = _bulk_prices(tickers, conn, asof)
    indicators = _bulk_indicators(tickers, conn, asof)
    fundamentals = _bulk_fundamentals(tickers, conn)
    valuations = _bulk_valuation(tickers, conn)
    analysts = _bulk_analyst(tickers, conn)
    news = _bulk_news(tickers, conn, asof)
    quants = _bulk_quant(tickers, conn, asof)

    # ── 메모리상 조인 (DB 미접근) ─────────────────────────────
    results: list[StockDailyRecord] = []
    for wl in watchlist:
        ticker = wl["ticker"]
        try:
            record = _build_record(
                wl=wl,
                price=prices.get(ticker),
                ind=indicators.get(ticker),
                fund=fundamentals.get(ticker, {}),
                val=valuations.get(ticker),
                ana=analysts.get(ticker),
                news=news.get(ticker),
                quant=quants.get(ticker),
            )
            results.append(record)
        except Exception as exc:
            logger.error("%s: 조립 실패 — %s", ticker, exc, exc_info=True)
            # 실패 종목 스킵, 다음 종목 계속

    signal_rows = [
        {"ticker": record.ticker, **record.quant.model_dump(exclude={"signal"})}
        for record in results
    ]
    signals = compute_display_signals(signal_rows)
    for record in results:
        record.quant.signal = signals.get(record.ticker)

    logger.info("assemble_daily: %d/%d 종목 조립 완료", len(results), len(tickers))
    return results


# ──────────────────────────────────────────────────────────────
# 진입점 (드라이런 확인)
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info("=== assemble 드라이런 시작 ===")

    with get_conn() as conn:
        run_id = log_run_start(conn, "assemble_daily")
        errors: list[dict] = []
        status = "success"

        try:
            records = assemble_daily(conn)
            output = [r.model_dump() for r in records]
            print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
            logger.info("assemble_daily: %d 레코드 출력", len(records))
        except Exception as exc:
            logger.error("assemble 오류: %s", exc, exc_info=True)
            errors.append({"step": "assemble", "error": str(exc), "ts": datetime.utcnow().isoformat()})
            status = "failed"

        log_run_finish(conn, run_id, status=status, errors=errors)
