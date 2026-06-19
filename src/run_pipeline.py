"""
run_pipeline.py — ATLAS 일일 파이프라인 실행기

실행 순서 (각 단계 try/except 격리):
  1. ingest_market   → market_daily
  2. ingest_kr       → prices_daily + fundamentals (KR 종목)
  3. ingest_us       → prices_daily + fundamentals + valuation + analyst (US 종목)
  4. ingest_news     → news_raw
  5. compute_indicators → indicators_daily
  6. compute_quant   → quant_scores
  7. enrich_gemini   → news_analysis + market_daily.summary_md
  8. assemble        → StockDailyRecord 목록 반환 (send_telegram에서 사용)

전체 실행은 runs 테이블에 기록.
시크릿은 환경변수에서만. 자동 주문 없음.

자동 주문 없음.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

import pandas as pd
import psycopg

from src.assemble import assemble_daily
from src.compute_portfolio import compute_portfolio
from src.compute_indicators import compute_indicators
from src.compute_quant import compute_quant_universe
from src.db import (
    get_conn,
    insert_news_raw,
    insert_market_news,
    log_run_finish,
    log_run_start,
    upsert_analyst,
    upsert_fundamentals,
    upsert_indicators_daily,
    upsert_market_daily,
    upsert_price_daily,
    upsert_quant_scores,
    upsert_valuation,
)
from src.enrich_gemini import enrich_market_summary, enrich_news_batch, reenrich_stale_fallbacks, summarize_market_news_digest
from src.ingest_kr import run_kr_ingest
from src.ingest_market import run_market_ingest
from src.ingest_market_news import run_market_news_ingest
from src.ingest_news import run_news_ingest
from src.ingest_us import run_us_ingest
from src.schemas import StockDailyRecord

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────────────────────

def _get_active_tickers(conn: psycopg.Connection) -> list[dict]:
    """watchlist에서 active 종목 (ticker, market) 목록."""
    sql = "SELECT ticker, market FROM watchlist WHERE active = TRUE ORDER BY ticker"
    with conn.cursor() as cur:
        cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]


def _load_price_df(ticker: str, conn: psycopg.Connection) -> pd.DataFrame:
    """prices_daily 전체 → DatetimeIndex DataFrame (compute_indicators 입력용)."""
    sql = """
        SELECT date, close, volume
        FROM prices_daily
        WHERE ticker = %s
        ORDER BY date ASC
    """
    with conn.cursor() as cur:
        cur.execute(sql, (ticker,))
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame(columns=["close", "volume"])
    df = pd.DataFrame([dict(r) for r in rows])
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")


def _err(step: str, exc: Exception) -> dict:
    return {"step": step, "error": str(exc), "ts": datetime.utcnow().isoformat()}


# ──────────────────────────────────────────────────────────────
# 개별 단계 함수
# ──────────────────────────────────────────────────────────────

def _step_market(conn: psycopg.Connection, errors: list) -> None:
    logger.info("Step 1: 시장 지표 수집")
    try:
        result = run_market_ingest()
        market_row = result.get("market")
        if market_row:
            upsert_market_daily(conn, market_row)
            conn.commit()
            logger.info("Step 1 완료: market_daily upsert 1건 (commit)")
        errors.extend(result.get("errors", []))
    except Exception as exc:
        conn.rollback()  # abort된 트랜잭션 회복 → 다음 단계 보호
        logger.error("Step 1 실패: %s", exc, exc_info=True)
        errors.append(_err("market", exc))


def _step_ingest_kr(conn: psycopg.Connection, kr_tickers: list[str], errors: list) -> None:
    logger.info("Step 2: KR 수집 (%d종목)", len(kr_tickers))
    if not kr_tickers:
        return
    try:
        result = run_kr_ingest(kr_tickers)
        n_price = n_fund = n_val = n_ana = 0
        for price_rows in result.get("prices", {}).values():
            if price_rows:
                upsert_price_daily(conn, price_rows)
                n_price += len(price_rows)
        for fund_rows in result.get("fundamentals", {}).values():
            if fund_rows:
                upsert_fundamentals(conn, fund_rows)
                n_fund += len(fund_rows)
        # PR-2: KR 밸류에이션/컨센서스 (네이버+FnGuide) — US 경로와 대칭
        for val_row in result.get("valuations", {}).values():
            if val_row:
                upsert_valuation(conn, [val_row])
                n_val += 1
        for ana_row in result.get("analysts", {}).values():
            if ana_row:
                upsert_analyst(conn, [ana_row])
                n_ana += 1
        conn.commit()
        errors.extend(result.get("errors", []))
        logger.info(
            "Step 2 완료: prices %d / fundamentals %d / valuation %d / analyst %d upsert (commit)",
            n_price, n_fund, n_val, n_ana,
        )
    except Exception as exc:
        conn.rollback()
        logger.error("Step 2 실패: %s", exc, exc_info=True)
        errors.append(_err("ingest_kr", exc))


def _step_ingest_us(conn: psycopg.Connection, us_tickers: list[str], errors: list) -> None:
    logger.info("Step 3: US 수집 (%d종목)", len(us_tickers))
    if not us_tickers:
        return
    try:
        result = run_us_ingest(us_tickers)
        n_price = n_fund = n_val = n_ana = 0
        for price_rows in result.get("prices", {}).values():
            if price_rows:
                upsert_price_daily(conn, price_rows)
                n_price += len(price_rows)
        for fund_rows in result.get("fundamentals", {}).values():
            if fund_rows:
                upsert_fundamentals(conn, fund_rows)
                n_fund += len(fund_rows)
        for val_row in result.get("valuations", {}).values():
            if val_row:
                upsert_valuation(conn, [val_row])
                n_val += 1
        for ana_row in result.get("analysts", {}).values():
            if ana_row:
                upsert_analyst(conn, [ana_row])
                n_ana += 1
        conn.commit()
        errors.extend(result.get("errors", []))
        logger.info(
            "Step 3 완료: prices %d / fundamentals %d / valuation %d / analyst %d upsert (commit)",
            n_price, n_fund, n_val, n_ana,
        )
    except Exception as exc:
        conn.rollback()
        logger.error("Step 3 실패: %s", exc, exc_info=True)
        errors.append(_err("ingest_us", exc))


def _step_ingest_news(conn: psycopg.Connection, all_tickers: list[str], errors: list) -> None:
    logger.info("Step 4: 뉴스 수집 (%d종목)", len(all_tickers))
    if not all_tickers:
        return
    try:
        # PR-4: 회사명 맵(Google News 쿼리 품질) + 시장 뉴스(_MARKET_KR/_MARKET_US) 포함
        with conn.cursor() as cur:
            cur.execute("SELECT ticker, name FROM watchlist")
            company_names = {r["ticker"]: r["name"] for r in cur.fetchall()}
        result = run_news_ingest(all_tickers, company_names=company_names)
        new_total = 0
        for news_rows in result.get("news", {}).values():
            if news_rows:
                new_total += insert_news_raw(conn, news_rows)
        conn.commit()
        errors.extend(result.get("errors", []))
        logger.info("Step 4 완료: news_raw 신규 %d건 삽입 (commit)", new_total)
    except Exception as exc:
        conn.rollback()
        logger.error("Step 4 실패: %s", exc, exc_info=True)
        errors.append(_err("ingest_news", exc))


def _step_ingest_market_news(conn: psycopg.Connection, errors: list) -> None:
    logger.info("Step 4b: 시장 뉴스 수집")
    try:
        result = run_market_news_ingest()
        inserted = insert_market_news(conn, result.get("rows", []))
        conn.commit()
        errors.extend(result.get("errors", []))
        logger.info("Step 4b 완료: market_news 신규 %d건 삽입 (commit)", inserted)
    except Exception as exc:
        conn.rollback()
        logger.error("Step 4b 실패: %s", exc, exc_info=True)
        errors.append(_err("ingest_market_news", exc))


def _step_compute_indicators(conn: psycopg.Connection, all_tickers: list[str], errors: list) -> None:
    logger.info("Step 5: 기술적 지표 계산 (%d종목)", len(all_tickers))
    ok, fail, n_rows = 0, 0, 0
    for ticker in all_tickers:
        try:
            price_df = _load_price_df(ticker, conn)
            rows = compute_indicators(ticker, price_df)
            if rows:
                upsert_indicators_daily(conn, rows)
                conn.commit()  # 종목별 커밋 → 한 종목 실패가 앞 종목 저장을 무효화하지 않음
                ok += 1
                n_rows += len(rows)
        except Exception as exc:
            conn.rollback()  # abort 회복 → 다음 종목 보호
            logger.warning("%s: 지표 계산/저장 실패 — %s", ticker, exc)
            errors.append(_err(f"indicators:{ticker}", exc))
            fail += 1
    logger.info("Step 5 완료: indicators_daily upsert %d행 / %d종목 성공 / %d실패", n_rows, ok, fail)


def _step_compute_quant(conn: psycopg.Connection, all_tickers: list[str], errors: list) -> None:
    logger.info("Step 6: 퀀트 스코어 계산 (%d종목)", len(all_tickers))
    if not all_tickers:
        return
    try:
        rows = compute_quant_universe(all_tickers, conn)
        if rows:
            upsert_quant_scores(conn, rows)
            conn.commit()
        filtered = sum(1 for r in rows if r.composite is None)
        logger.info("Step 6 완료: quant_scores upsert %d행 (필터 제외 %d) (commit)", len(rows), filtered)
    except Exception as exc:
        conn.rollback()
        logger.error("Step 6 실패: %s", exc, exc_info=True)
        errors.append(_err("compute_quant", exc))


def _step_enrich_gemini(conn: psycopg.Connection, errors: list) -> None:
    logger.info("Step 7: Gemini 뉴스 요약 + 시황 종합")
    try:
        enriched, news_errs = enrich_news_batch(conn)
        conn.commit()
        errors.extend(news_errs)
        logger.info("Step 7a 완료: news_analysis upsert %d종목 (commit)", enriched)
    except Exception as exc:
        conn.rollback()
        logger.error("Step 7a(news_batch) 실패: %s", exc, exc_info=True)
        errors.append(_err("enrich_news", exc))

    # PR-1(진단): 최신 분석이 폴백인 종목을 최근 뉴스로 복구 — 굳은 '분석 실패' 자가치유
    try:
        fixed, fix_errs = reenrich_stale_fallbacks(conn)
        conn.commit()
        errors.extend(fix_errs)
        logger.info("Step 7a' 완료: 폴백 복구 %d종목 (commit)", fixed)
    except Exception as exc:
        conn.rollback()
        logger.error("Step 7a'(reenrich) 실패: %s", exc, exc_info=True)
        errors.append(_err("reenrich_fallback", exc))

    try:
        ok = enrich_market_summary(conn)
        conn.commit()
        logger.info("Step 7b 완료: 시황 종합 %s (commit)", "저장" if ok else "스킵")
    except Exception as exc:
        conn.rollback()
        logger.error("Step 7b(market_summary) 실패: %s", exc, exc_info=True)
        errors.append(_err("enrich_market", exc))

    try:
        digest_ok = summarize_market_news_digest(conn)
        conn.commit()
        logger.info("Step 7c 완료: 시장 뉴스 요약 %s (commit)", "저장" if digest_ok else "스킵")
    except Exception as exc:
        conn.rollback()
        logger.error("Step 7c(market_news_digest) 실패: %s", exc, exc_info=True)
        errors.append(_err("market_news_digest", exc))


def _step_compute_portfolio(conn: psycopg.Connection, errors: list) -> None:
    """Step 9: 보유종목 평가 (portfolio_holdings → portfolio + portfolio_snapshot). 실패해도 파이프라인 계속."""
    logger.info("Step 9: 보유종목 평가")
    try:
        result = compute_portfolio(conn)
        logger.info("Step 9 완료: %d종목 평가 완료", result["n"])
    except Exception as exc:
        conn.rollback()
        logger.warning("Step 9 실패(비치명적): %s", exc)
        errors.append(_err("compute_portfolio", exc))


def _step_backtest(conn: psycopg.Connection, errors: list) -> None:
    """Step 10: 멀티전략 백테스트 + 회고. 실패해도 파이프라인 계속."""
    logger.info("Step 10: 백테스트 + 회고")
    try:
        from src.backtest import run_backtest
        result = run_backtest(conn)
        logger.info("Step 10 완료: true=%s retro=%s",
                    result.get("true_backtest", {}).get("ok"),
                    result.get("retrospective", {}).get("ok"))
    except Exception as exc:
        conn.rollback()
        logger.warning("Step 10 실패(비치명적): %s", exc)
        errors.append(_err("backtest", exc))


def _step_assemble(conn: psycopg.Connection, errors: list) -> list[StockDailyRecord]:
    logger.info("Step 8: 레코드 조립")
    try:
        records = assemble_daily(conn)
        logger.info("Step 8 완료: %d 레코드", len(records))
        return records
    except Exception as exc:
        logger.error("Step 8 실패: %s", exc, exc_info=True)
        errors.append(_err("assemble", exc))
        return []


# ──────────────────────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────────────────────

def run_pipeline(asof: Optional[date] = None) -> list[StockDailyRecord]:
    """
    전체 파이프라인 실행.
    한 단계 실패해도 다음 단계 계속.
    runs 테이블에 실행 이력 기록.

    자동 주문 없음.
    """
    asof = asof or date.today()
    errors: list[dict] = []
    records: list[StockDailyRecord] = []
    status = "success"

    with get_conn() as conn:
        run_id = log_run_start(conn, "run_pipeline")
        logger.info("=== 파이프라인 시작 asof=%s run_id=%d ===", asof, run_id)

        try:
            # 유니버스 로드
            watchlist = _get_active_tickers(conn)
            kr_tickers = [w["ticker"] for w in watchlist if w["market"] == "KR"]
            us_tickers = [w["ticker"] for w in watchlist if w["market"] == "US"]
            all_tickers = [w["ticker"] for w in watchlist]
            logger.info("유니버스: KR=%d US=%d 합계=%d", len(kr_tickers), len(us_tickers), len(all_tickers))

            _step_market(conn, errors)
            _step_ingest_kr(conn, kr_tickers, errors)
            _step_ingest_us(conn, us_tickers, errors)
            _step_ingest_news(conn, all_tickers, errors)
            _step_ingest_market_news(conn, errors)
            _step_compute_indicators(conn, all_tickers, errors)
            _step_compute_quant(conn, all_tickers, errors)
            _step_enrich_gemini(conn, errors)
            _step_compute_portfolio(conn, errors)
            _step_backtest(conn, errors)
            records = _step_assemble(conn, errors)

        except Exception as exc:
            logger.error("파이프라인 치명적 오류: %s", exc, exc_info=True)
            errors.append(_err("pipeline_fatal", exc))
            status = "failed"

        if errors and status != "failed":
            status = "partial"

        log_run_finish(conn, run_id, status=status, errors=errors)
        logger.info("=== 파이프라인 완료 status=%s errors=%d ===", status, len(errors))

    return records


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    records = run_pipeline()
    logger.info("조립된 레코드: %d종목", len(records))
