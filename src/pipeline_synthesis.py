"""
pipeline_synthesis.py — 종합 파이프라인 실행기 (설계 §4.3, §9 4단계)

행위 보존: 기존 run_pipeline/news_refresh의 LLM 종합 단계 구현을 그대로 호출만 이전한다.
원천 수집, 지표·팩터·백테스트 계산, 주문 실행은 하지 않는다.

  python -m src.pipeline_synthesis --profile daily|refresh

daily   : 뉴스 요약 → 폴백 복구 → 애널리스트 논거 → 시황 → 시장 뉴스 요약 → 거시 요약 → 액션 제언
          (run_pipeline Step 7 + Step 10b 순서·범위 그대로)
refresh : 뉴스 요약 → 시황 → 시장 뉴스 요약만 (현재 18시 news_refresh 범위)

입력 테이블: news_raw, 기존 news_analysis, market_daily, market_news, macro_indicators,
            ticker_context, analyst, quant_scores, portfolio, portfolio_snapshot 등
출력 테이블: news_analysis, ticker_context, analyst_views, market_daily 요약 컬럼,
            market_news_summary, macro_summary, stock_action_advice

보존(설계 §3):
- market_daily 소유권: 종합은 enrich_market_summary가 요약 컬럼만 UPDATE하고 수집이 쓴
  숫자/`payload.changes`를 덮지 않는다. 이 모듈은 market_daily 숫자 writer(upsert_market_daily)를
  호출하지 않는다.
- 액션 제언 숫자(방향·비중·목표레인지·진입/이탈)는 결정론 build_action_frame이 만들고
  LLM(summarize_stock_action_advice)은 서술만 한다. 숫자 불변.
- Gemini timeout·배치 예산·예산 초과 이월 runs.errors 기록, 종목 단위 try/except 격리 보존.
- portfolio_advice는 이 경계 소유지만 daily/refresh 자동 프로필에서는 호출하지 않는다
  (현재처럼 사용자 요청/로컬 API 기반 유지).

# ponytail: 액션 제언 오케스트레이션은 run_pipeline._step_action_advice를 그대로 옮긴 것.
#           run_pipeline/news_refresh 중복본은 설계 §9 8단계(dead code 제거)까지 유지한다.
자동 주문 없음.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, datetime
from typing import Optional

import psycopg

from src import db, enrich_gemini, stock_action_advice
from src.pipeline_common import (
    PROFILE_DAILY,
    PROFILE_REFRESH,
    VALID_PROFILES,
    finalize_status,
    make_error,
)
from src.schemas import StockActionAdviceRow

logger = logging.getLogger(__name__)

RUN_KIND = "pipeline_synthesis"

# 단계 순서를 짧은 튜플 상수로 노출 (설계 §5)
DAILY_STEPS = (
    "enrich_news",
    "reenrich_fallback",
    "analyst_views",
    "enrich_market",
    "market_news_digest",
    "macro_summary",
    "action_advice",
)
REFRESH_STEPS = (
    "enrich_news",
    "enrich_market",
    "market_news_digest",
)


# ──────────────────────────────────────────────────────────────
# LLM 종합 단계 (run_pipeline._step_enrich_gemini / news_refresh와 동일 동작)
# ──────────────────────────────────────────────────────────────

def _step_enrich_news(conn: psycopg.Connection, errors: list, counts: dict) -> None:
    logger.info("종합: 뉴스 요약")
    try:
        enriched, news_errs = enrich_gemini.enrich_news_batch(conn)
        conn.commit()
        errors.extend(news_errs)
        counts["news_analysis"] = counts.get("news_analysis", 0) + (enriched or 0)
    except Exception as exc:
        conn.rollback()
        logger.error("뉴스 요약 실패: %s", exc, exc_info=True)
        errors.append(make_error("enrich_news", exc))


def _step_reenrich_fallback(conn: psycopg.Connection, errors: list, counts: dict) -> None:
    logger.info("종합: 폴백 복구")
    try:
        fixed, fix_errs = enrich_gemini.reenrich_stale_fallbacks(conn)
        conn.commit()
        errors.extend(fix_errs)
        counts["reenrich_fallback"] = counts.get("reenrich_fallback", 0) + (fixed or 0)
    except Exception as exc:
        conn.rollback()
        logger.error("폴백 복구 실패: %s", exc, exc_info=True)
        errors.append(make_error("reenrich_fallback", exc))


def _step_analyst_views(conn: psycopg.Connection, errors: list, counts: dict) -> None:
    logger.info("종합: 애널리스트 논거")
    try:
        extracted, analyst_errs = enrich_gemini.extract_analyst_views_batch(conn)
        conn.commit()
        errors.extend(analyst_errs)
        counts["analyst_views"] = counts.get("analyst_views", 0) + (extracted or 0)
    except Exception as exc:
        conn.rollback()
        logger.error("애널리스트 논거 실패: %s", exc, exc_info=True)
        errors.append(make_error("analyst_views", exc))


def _step_market_summary(conn: psycopg.Connection, errors: list, counts: dict) -> None:
    logger.info("종합: 시황")
    try:
        ok = enrich_gemini.enrich_market_summary(conn)
        conn.commit()
        if ok:
            counts["market_summary"] = counts.get("market_summary", 0) + 1
    except Exception as exc:
        conn.rollback()
        logger.error("시황 종합 실패: %s", exc, exc_info=True)
        errors.append(make_error("enrich_market", exc))


def _step_market_news_digest(conn: psycopg.Connection, errors: list, counts: dict) -> None:
    logger.info("종합: 시장 뉴스 요약")
    try:
        digest_ok = enrich_gemini.summarize_market_news_digest(conn)
        conn.commit()
        if digest_ok:
            counts["market_news_summary"] = counts.get("market_news_summary", 0) + 1
    except Exception as exc:
        conn.rollback()
        logger.error("시장 뉴스 요약 실패: %s", exc, exc_info=True)
        errors.append(make_error("market_news_digest", exc))


def _step_macro_summary(conn: psycopg.Connection, errors: list, counts: dict) -> None:
    logger.info("종합: 거시 환경 요약")
    try:
        macro_ok = enrich_gemini.summarize_macro_environment(conn)
        conn.commit()
        if macro_ok:
            counts["macro_summary"] = counts.get("macro_summary", 0) + 1
    except Exception as exc:
        conn.rollback()
        logger.error("거시 요약 실패: %s", exc, exc_info=True)
        errors.append(make_error("macro_summary", exc))


# ──────────────────────────────────────────────────────────────
# 액션 제언 (run_pipeline._step_action_advice와 동일 동작)
# ──────────────────────────────────────────────────────────────

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


def _step_action_advice(conn: psycopg.Connection, errors: list, counts: dict) -> None:
    logger.info("종합: 종목 액션 제언")
    from src.export_dashboard_data import build_data

    started_at = time.monotonic()
    try:
        targets = _select_action_advice_targets(conn)
        if not targets:
            logger.info("액션 제언 스킵: 대상 종목 없음")
            return
        data = build_data()
        stocks_by_ticker = {stock["t"]: stock for stock in data.get("stocks", [])}
        regime = data.get("market", {}).get("overall", "neutral")
        portfolio_snapshot = data.get("portfolio", {}) or {}
        today = date.today()
        processed = 0
        for ticker in targets:
            if not enrich_gemini._within_budget(started_at, enrich_gemini.GEMINI_BATCH_BUDGET_SECONDS):
                errors.append({
                    "step": "action_advice_budget",
                    "error": "budget exceeded; rolled over remaining tickers",
                    "ts": datetime.now().isoformat(),
                })
                logger.warning("액션 제언 예산 초과: 남은 종목 다음 실행으로 이월")
                break
            stock = stocks_by_ticker.get(ticker)
            if not stock:
                continue
            try:
                frame = stock_action_advice.build_action_frame(stock, portfolio_snapshot, regime)
                narrative = enrich_gemini.summarize_stock_action_advice(frame)
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
                    rationale=(narrative.rationale if narrative else f"{frame['direction']} 제안 — 현재 비중 {frame['current_weight']}%, 목표 {frame['target_weight_low']}~{frame['target_weight_high']}%"),
                    supporting_factors=(narrative.supportingFactors if narrative and narrative.supportingFactors else frame["supporting_factors"]),
                    opposing_factors=(narrative.opposingFactors if narrative and narrative.opposingFactors else frame["opposing_factors"]),
                    divergence_note=(narrative.divergenceNote if narrative and narrative.divergenceNote is not None else frame["divergence_note"]),
                    model=(enrich_gemini._get_manual_research_model() if narrative else "deterministic-fallback"),
                )
                db.upsert_stock_action_advice(conn, row)
                conn.commit()
                processed += 1
            except Exception as exc:
                conn.rollback()
                errors.append(make_error(f"action_advice:{ticker}", exc))
                logger.warning("%s: 액션 제언 실패 — %s", ticker, exc)
        counts["stock_action_advice"] = counts.get("stock_action_advice", 0) + processed
        logger.info("액션 제언 완료: 대상 %d종목 처리", len(targets))
    except Exception as exc:
        conn.rollback()
        logger.error("액션 제언 실패: %s", exc, exc_info=True)
        errors.append(make_error("action_advice", exc))


# ──────────────────────────────────────────────────────────────
# 진입점
# ──────────────────────────────────────────────────────────────

def run(profile: str, asof: Optional[date] = None) -> dict:
    """종합 파이프라인 실행. 반환: {status, errors, counts}."""
    if profile not in VALID_PROFILES:
        raise ValueError(f"unknown profile: {profile!r} (allowed: {VALID_PROFILES})")
    asof = asof or date.today()
    errors: list[dict] = []
    counts: dict = {}
    status = "success"

    with db.get_conn() as conn:
        run_id = db.log_run_start(conn, RUN_KIND)
        logger.info("=== pipeline_synthesis 시작 profile=%s asof=%s run_id=%d ===", profile, asof, run_id)
        try:
            # 종합 단계는 종목 선택을 각 단계 내부에서 한다(legacy Step 7/10b와 동일).
            if profile == PROFILE_DAILY:
                _step_enrich_news(conn, errors, counts)
                _step_reenrich_fallback(conn, errors, counts)
                _step_analyst_views(conn, errors, counts)
                _step_market_summary(conn, errors, counts)
                _step_market_news_digest(conn, errors, counts)
                _step_macro_summary(conn, errors, counts)
                _step_action_advice(conn, errors, counts)
            else:  # PROFILE_REFRESH — 폴백복구·논거·거시요약·액션제언 제외
                _step_enrich_news(conn, errors, counts)
                _step_market_summary(conn, errors, counts)
                _step_market_news_digest(conn, errors, counts)

            status = finalize_status(errors)
        except Exception as exc:
            logger.error("pipeline_synthesis 치명적 오류: %s", exc, exc_info=True)
            errors.append(make_error("pipeline_fatal", exc))
            status = finalize_status(errors, fatal=True)

        db.log_run_finish(conn, run_id, status=status, errors=errors)
        logger.info("=== pipeline_synthesis 완료 status=%s errors=%d counts=%s ===", status, len(errors), counts)

    return {"status": status, "errors": errors, "counts": counts}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="ATLAS 종합 파이프라인")
    parser.add_argument("--profile", required=True, help="daily | refresh")
    args = parser.parse_args(argv)

    if args.profile not in VALID_PROFILES:
        print(f"invalid profile: {args.profile!r} (allowed: {', '.join(VALID_PROFILES)})", file=sys.stderr)
        return 2

    result = run(args.profile)
    return 0 if result["status"] in ("success", "partial") else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    sys.exit(main())
