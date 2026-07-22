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
import time
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
    upsert_stock_action_advice,
    upsert_analyst,
    upsert_fundamentals,
    upsert_indicators_daily,
    upsert_market_daily,
    upsert_macro_indicators,
    upsert_price_daily,
    upsert_quant_scores,
    upsert_valuation,
)
from src.enrich_gemini import (
    GEMINI_BATCH_BUDGET_SECONDS,
    _get_action_advice_model,
    _within_budget,
    enrich_market_summary,
    enrich_news_batch,
    extract_analyst_views_batch,
    reenrich_stale_fallbacks,
    summarize_stock_action_advice,
    summarize_macro_environment,
    summarize_market_news_digest,
)
from src.ingest_kr import run_kr_ingest
from src.ingest_drivers import run_driver_price_ingest
from src.ingest_macro import run_macro_ingest
from src.ingest_market import run_market_ingest
from src.ingest_market_news import run_market_news_ingest
from src.ingest_news import run_news_ingest
from src.ingest_us import run_us_ingest
from src import pipeline_analysis, pipeline_ingest, pipeline_synthesis
from src.schemas import StockDailyRecord
from src.schemas import StockActionAdviceRow
from src.stock_action_advice import build_action_frame, finalize_concentration_note, grade_fallback_rationale
from src.freshness import today_kst

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────────────────────

def _load_price_df(ticker: str, conn: psycopg.Connection) -> pd.DataFrame:
    """prices_daily 전체 → DatetimeIndex DataFrame (compute_indicators 입력용)."""
    sql = """
        SELECT date, high, low, close, volume
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


def _prioritize_action_advice_targets(*, holdings: list[str], event_tickers: list[str], remaining: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for bucket in (holdings, event_tickers, remaining):
        for ticker in bucket:
            if ticker not in seen:
                seen.add(ticker)
                ordered.append(ticker)
    return ordered


def _select_action_advice_targets(conn: psycopg.Connection) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT ticker FROM portfolio_holdings WHERE qty > 0 ORDER BY ticker")
        holdings = [row["ticker"] for row in cur.fetchall()]
        cur.execute(
            """
            SELECT DISTINCT ticker
            FROM news_raw
            WHERE published_at >= now() - interval '2 day'
            ORDER BY ticker
            """
        )
        news_event_tickers = [row["ticker"] for row in cur.fetchall()]
        cur.execute(
            """
            SELECT ticker
            FROM watchlist
            WHERE active = TRUE
            ORDER BY ticker
            """
        )
        all_active = [row["ticker"] for row in cur.fetchall()]
    remaining = [ticker for ticker in all_active if ticker not in holdings and ticker not in news_event_tickers]
    return _prioritize_action_advice_targets(
        holdings=holdings,
        event_tickers=[ticker for ticker in news_event_tickers if ticker not in holdings],
        remaining=remaining,
    )


def _step_action_advice(conn: psycopg.Connection, errors: list) -> None:
    logger.info("Step 10b: 종목 액션 제언")
    from src.export_dashboard_data import build_data

    started_at = time.monotonic()
    try:
        targets = _select_action_advice_targets(conn)
        if not targets:
            logger.info("Step 10b 스킵: 대상 종목 없음")
            return
        data = build_data()
        stocks_by_ticker = {stock["t"]: stock for stock in data.get("stocks", [])}
        regime = data.get("market", {}).get("overall", "neutral")
        portfolio_snapshot = data.get("portfolio", {}) or {}
        today = today_kst()
        for ticker in targets:
            if not _within_budget(started_at, GEMINI_BATCH_BUDGET_SECONDS):
                errors.append({
                    "step": "action_advice_budget",
                    "error": "budget exceeded; rolled over remaining tickers",
                    "ts": datetime.now().isoformat(),
                })
                logger.warning("Step 10b 예산 초과: 남은 종목 다음 실행으로 이월")
                break
            stock = stocks_by_ticker.get(ticker)
            if not stock:
                continue
            try:
                frame = build_action_frame(stock, portfolio_snapshot, regime)
                narrative = summarize_stock_action_advice(frame)
                row = StockActionAdviceRow(
                    ticker=ticker,
                    asof=today,
                    direction=frame["direction"],
                    current_weight=frame["current_weight"],
                    target_weight_low=frame["target_weight_low"],
                    target_weight_high=frame["target_weight_high"],
                    weight_action=frame["weight_action"],
                    entry_zone=frame["entry_zone"],
                    exit_zone=frame["exit_zone"],
                    confidence=frame["confidence"],
                    rationale=(narrative.rationale if narrative else grade_fallback_rationale(frame)),
                    supporting_factors=(narrative.supportingFactors if narrative and narrative.supportingFactors else frame["supporting_factors"]),
                    opposing_factors=(narrative.opposingFactors if narrative and narrative.opposingFactors else frame["opposing_factors"]),
                    divergence_note=(narrative.divergenceNote if narrative and narrative.divergenceNote is not None else frame["divergence_note"]),
                    model=(_get_action_advice_model() if narrative else "deterministic-fallback"),
                    hold_character=frame["hold_character"],
                    hold_character_secondary=frame["hold_character_secondary"],
                    hold_character_basis=frame["hold_character_basis"],
                    concentration_note=finalize_concentration_note(
                        frame["concentration_note"],
                        (narrative.concentrationNote if narrative else None),
                        frame["current_weight"],
                    ),
                    grade=frame["grade"],
                    grade_confidence=frame["grade_confidence"],
                    grade_basis=frame["grade_basis"],
                )
                upsert_stock_action_advice(conn, row)
                conn.commit()
            except Exception as exc:
                conn.rollback()
                errors.append(_err(f"action_advice:{ticker}", exc))
                logger.warning("%s: 액션 제언 실패 — %s", ticker, exc)
        logger.info("Step 10b 완료: 액션 제언 대상 %d종목 처리", len(targets))
    except Exception as exc:
        conn.rollback()
        logger.error("Step 10b 실패: %s", exc, exc_info=True)
        errors.append(_err("action_advice", exc))


# ──────────────────────────────────────────────────────────────
# 개별 단계 함수
# ──────────────────────────────────────────────────────────────

def _step_market(conn: psycopg.Connection, errors: list) -> None:
    logger.info("Step 1: 시장 지표 수집")
    try:
        result = run_market_ingest()
        rows = result.get("markets", [])
        for market_row in rows:
            upsert_market_daily(conn, market_row)
        conn.commit()
        logger.info("Step 1 완료: market_daily upsert %d건 (commit)", len(rows))
        errors.extend(result.get("errors", []))
    except Exception as exc:
        conn.rollback()  # abort된 트랜잭션 회복 → 다음 단계 보호
        logger.error("Step 1 실패: %s", exc, exc_info=True)
        errors.append(_err("market", exc))


def _step_macro(conn: psycopg.Connection, errors: list) -> None:
    logger.info("Step 1b: 거시 지표 수집")
    try:
        result = run_macro_ingest()
        rows = result.get("rows", [])
        if rows:
            upsert_macro_indicators(conn, rows)
            conn.commit()
        errors.extend(result.get("errors", []))
        logger.info("Step 1b 완료: macro_indicators %d건 upsert (commit)", len(rows))
    except Exception as exc:
        conn.rollback()
        logger.error("Step 1b 실패: %s", exc, exc_info=True)
        errors.append(_err("macro", exc))


def _step_driver_prices(conn: psycopg.Connection, errors: list) -> None:
    logger.info("Step 1c: 드라이버 프록시 가격 수집")
    try:
        result = run_driver_price_ingest(conn)
        conn.commit()
        errors.extend(result.get("errors", []))
        logger.info("Step 1c 완료: driver_prices %d건 upsert (commit)", len(result.get("rows", [])))
    except Exception as exc:
        conn.rollback()
        logger.error("Step 1c 실패: %s", exc, exc_info=True)
        errors.append(_err("driver_prices", exc))


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
        extracted, analyst_errs = extract_analyst_views_batch(conn)
        conn.commit()
        errors.extend(analyst_errs)
        logger.info("Step 7a'' 완료: 애널리스트 논거 %d건 저장 (commit)", extracted)
    except Exception as exc:
        conn.rollback()
        logger.error("Step 7a''(analyst_views) 실패: %s", exc, exc_info=True)
        errors.append(_err("analyst_views", exc))

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

    try:
        macro_ok = summarize_macro_environment(conn)
        conn.commit()
        logger.info("Step 7d 완료: 거시 환경 요약 %s (commit)", "저장" if macro_ok else "스킵")
    except Exception as exc:
        conn.rollback()
        logger.error("Step 7d(macro_summary) 실패: %s", exc, exc_info=True)
        errors.append(_err("macro_summary", exc))


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
    일일 파이프라인 호환 래퍼 (설계 §9-6) — 새 세 실행기를 daily 순서로 호출한 뒤
    assemble_daily()로 06시 반환 계약(list[StockDailyRecord])을 만든다.

      pipeline_ingest.run('daily') → pipeline_analysis.run('daily')
      → pipeline_synthesis.run('daily') → assemble

    분석→종합 순서를 유지해 "퀀트가 이전 실행의 최신 news_analysis sentiment를 쓰는" 동작을 보존한다.
    각 실행기는 자기 conn·runs 행을 가진다(설계 §5). 액션 제언의 build_data 역의존은 5단계 보류로 유지.

    # ponytail: 개별 _step_* 함수와 _err/유니버스 헬퍼는 실행기로 이전됐고, 여기선 더 이상 호출하지
    #           않는다. 중복본은 설계 §9 8단계(dead code 제거)까지 유지한다.
    자동 주문 없음.
    """
    asof = asof or today_kst()
    logger.info("=== run_pipeline(호환 래퍼) 시작 asof=%s ===", asof)

    pipeline_ingest.run("daily", asof)
    pipeline_analysis.run("daily", asof)
    pipeline_synthesis.run("daily", asof)

    with get_conn() as conn:
        records = _step_assemble(conn, [])

    logger.info("=== run_pipeline 완료: %d 레코드 ===", len(records))
    return records


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    records = run_pipeline()
    logger.info("조립된 레코드: %d종목", len(records))
