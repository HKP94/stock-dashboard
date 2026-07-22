"""
pipeline_analysis.py — 분석 파이프라인 실행기 (설계 §4.2, §9 3단계)

행위 보존: 기존 run_pipeline/news_refresh의 계산 단계 구현을 그대로 호출만 이전한다.
외부 수집, LLM 호출, 표시 JSON 생성은 하지 않는다.

  python -m src.pipeline_analysis --profile daily|refresh

daily   : 지표 → 퀀트 → 포트폴리오 → 백테스트 (run_pipeline 순서 그대로)
refresh : 지표 → 퀀트 → 시장점수 → 포트폴리오 (18시 KR 당일종가로 총자산 재계산, 백테스트만 제외)

입력 테이블: prices_daily, fundamentals, valuation, analyst, 기존 최신 news_analysis,
            market_daily, index_daily, portfolio_holdings, portfolio_cash
출력 테이블: indicators_daily, quant_scores, portfolio, portfolio_snapshot, backtest_results

비직관 의존성 보존(설계 §3): 퀀트는 "이전까지 저장된 최신 news_analysis"의 sentiment를
입력으로 쓴다. 같은 실행의 LLM 요약(종합 파이프라인)을 쓰지 않으므로 분석을 종합보다
먼저 실행하는 현재 순서를 유지한다. §F7 true/retrospective 분리와 DB NUMERIC float 경계 유지.

# ponytail: daily 지표는 per-ticker compute_indicators 루프, refresh 지표는
#           recompute_indicators_to_db — 현재 06시/18시 동작이 다르므로 그대로 보존한다.
#           run_pipeline/news_refresh의 중복본은 설계 §9 8단계까지 유지한다.
자동 주문 없음.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from typing import Optional

import pandas as pd
import psycopg

from src import compute_indicators, compute_portfolio, compute_quant, db
from src.pipeline_common import (
    PROFILE_DAILY,
    PROFILE_REFRESH,
    VALID_PROFILES,
    active_universe,
    finalize_status,
    make_error,
    split_kr_us,
)
from src.freshness import today_kst

logger = logging.getLogger(__name__)

RUN_KIND = "pipeline_analysis"

# 단계 순서를 짧은 튜플 상수로 노출 (설계 §5)
DAILY_STEPS = ("compute_indicators", "compute_quant", "market_score", "compute_portfolio", "backtest", "signal_track")
# refresh(18시)에도 compute_portfolio 포함 — 당일 KR 종가로 총자산 재계산(스테일 방지). backtest만 제외.
REFRESH_STEPS = ("compute_indicators", "compute_quant", "market_score", "compute_portfolio")


def _load_price_df(ticker: str, conn: psycopg.Connection) -> pd.DataFrame:
    """prices_daily 전체 → DatetimeIndex DataFrame (run_pipeline._load_price_df와 동일)."""
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


# ──────────────────────────────────────────────────────────────
# 계산 단계 (run_pipeline._step_* / news_refresh와 동일 동작)
# ──────────────────────────────────────────────────────────────

def _step_indicators_daily(conn: psycopg.Connection, all_tickers: list[str], errors: list, counts: dict) -> None:
    """daily 지표: 종목별 compute_indicators + 종목별 commit (run_pipeline._step_compute_indicators)."""
    logger.info("분석: 기술적 지표 (%d종목)", len(all_tickers))
    ok = fail = n_rows = 0
    for ticker in all_tickers:
        try:
            price_df = _load_price_df(ticker, conn)
            rows = compute_indicators.compute_indicators(ticker, price_df)
            if rows:
                db.upsert_indicators_daily(conn, rows)
                conn.commit()  # 종목별 커밋 → 한 종목 실패가 앞 종목 저장을 무효화하지 않음
                ok += 1
                n_rows += len(rows)
        except Exception as exc:
            conn.rollback()  # abort 회복 → 다음 종목 보호
            logger.warning("%s: 지표 계산/저장 실패 — %s", ticker, exc)
            errors.append(make_error(f"indicators:{ticker}", exc))
            fail += 1
    counts["indicators_daily"] = counts.get("indicators_daily", 0) + n_rows
    logger.info("분석 지표 완료: %d행 / %d성공 / %d실패", n_rows, ok, fail)


def _step_indicators_refresh(conn: psycopg.Connection, all_tickers: list[str], errors: list, counts: dict) -> None:
    """refresh 지표: recompute_indicators_to_db (news_refresh._refresh_prices_light 지표 부분)."""
    logger.info("분석: 기술적 지표 재계산 (%d종목)", len(all_tickers))
    try:
        n = compute_indicators.recompute_indicators_to_db(conn, all_tickers)
        counts["indicators_daily"] = counts.get("indicators_daily", 0) + n
    except Exception as exc:
        conn.rollback()
        logger.error("지표 재계산 실패: %s", exc, exc_info=True)
        errors.append(make_error("indicators", exc))


def _step_quant(conn: psycopg.Connection, all_tickers: list[str], errors: list, counts: dict) -> None:
    """퀀트 스코어 (run_pipeline._step_compute_quant / news_refresh 퀀트 — 동일 로직)."""
    logger.info("분석: 퀀트 스코어 (%d종목)", len(all_tickers))
    if not all_tickers:
        return
    try:
        rows = compute_quant.compute_quant_universe(all_tickers, conn)
        if rows:
            db.upsert_quant_scores(conn, rows)
            conn.commit()
            counts["quant_scores"] = counts.get("quant_scores", 0) + len(rows)
    except Exception as exc:
        conn.rollback()
        logger.error("퀀트 계산 실패: %s", exc, exc_info=True)
        errors.append(make_error("compute_quant", exc))


def _step_market_score(conn: psycopg.Connection, errors: list, counts: dict) -> None:
    """Wave 5-B: 시장 매력도 점수(KR/US) 결정론 산출·저장. 실패해도 파이프라인 계속."""
    logger.info("분석: 시장 매력도 점수")
    try:
        from src.compute_market_score import compute_market_scores
        rows = compute_market_scores(conn)
        if rows:
            db.upsert_market_score(conn, rows)
            conn.commit()
            counts["market_score"] = len(rows)
    except Exception as exc:
        conn.rollback()
        logger.warning("시장 매력도 점수 실패(비치명적): %s", exc)
        errors.append(make_error("market_score", exc))


def _step_portfolio(conn: psycopg.Connection, errors: list, counts: dict) -> None:
    """보유종목 평가 (run_pipeline._step_compute_portfolio). 실패해도 파이프라인 계속."""
    logger.info("분석: 보유종목 평가")
    try:
        result = compute_portfolio.compute_portfolio(conn)
        counts["portfolio"] = result.get("n", 0) if isinstance(result, dict) else 0
    except Exception as exc:
        conn.rollback()
        logger.warning("보유종목 평가 실패(비치명적): %s", exc)
        errors.append(make_error("compute_portfolio", exc))


def _step_backtest(conn: psycopg.Connection, errors: list, counts: dict) -> None:
    """멀티전략 백테스트 + 회고 (run_pipeline._step_backtest). 실패해도 파이프라인 계속."""
    logger.info("분석: 백테스트 + 회고")
    try:
        from src.backtest import run_backtest
        result = run_backtest(conn)
        counts["backtest"] = 1
        logger.info(
            "분석 백테스트 완료: true=%s retro=%s",
            result.get("true_backtest", {}).get("ok"),
            result.get("retrospective", {}).get("ok"),
        )
    except Exception as exc:
        conn.rollback()
        logger.warning("백테스트 실패(비치명적): %s", exc)
        errors.append(make_error("backtest", exc))


def _step_signal_track(conn: psycopg.Connection, errors: list, counts: dict) -> None:
    """신규-F: A2 등급 신호 적중률 추적. 실패해도 파이프라인 계속."""
    logger.info("분석: 신호 적중률 추적")
    try:
        from src.compute_signal_track import compute_signal_track
        result = compute_signal_track(conn)
        counts["signal_track_inserted"] = result["inserted"]
        counts["signal_track_updated"] = result["updated"]
        if result["errors"]:
            errors.extend([make_error(e["stage"], Exception(e["error"])) for e in result["errors"]])
    except Exception as exc:
        conn.rollback()
        logger.warning("신호 적중률 추적 실패(비치명적): %s", exc)
        errors.append(make_error("signal_track", exc))


# ──────────────────────────────────────────────────────────────
# 진입점
# ──────────────────────────────────────────────────────────────

def run(profile: str, asof: Optional[date] = None) -> dict:
    """분석 파이프라인 실행. 반환: {status, errors, counts}."""
    if profile not in VALID_PROFILES:
        raise ValueError(f"unknown profile: {profile!r} (allowed: {VALID_PROFILES})")
    asof = asof or today_kst()
    errors: list[dict] = []
    counts: dict = {}
    status = "success"

    with db.get_conn() as conn:
        run_id = db.log_run_start(conn, RUN_KIND)
        logger.info("=== pipeline_analysis 시작 profile=%s asof=%s run_id=%d ===", profile, asof, run_id)
        try:
            watchlist = active_universe(conn)
            _kr, _us, all_tickers = split_kr_us(watchlist)
            logger.info("유니버스: %d종목", len(all_tickers))

            if profile == PROFILE_DAILY:
                _step_indicators_daily(conn, all_tickers, errors, counts)
                _step_quant(conn, all_tickers, errors, counts)
                _step_market_score(conn, errors, counts)
                _step_portfolio(conn, errors, counts)
                _step_backtest(conn, errors, counts)
                _step_signal_track(conn, errors, counts)
            else:  # PROFILE_REFRESH — 백테스트 제외. 포트폴리오는 포함(18시 KR 당일종가 반영).
                _step_indicators_refresh(conn, all_tickers, errors, counts)
                _step_quant(conn, all_tickers, errors, counts)
                _step_market_score(conn, errors, counts)
                # 포트폴리오 스냅샷은 반드시 18시에도 재계산한다. 06시 auto_run은 KR 장 시작 전이라
                # 전일 종가로 평가하고, 18시 news_refresh가 당일 KR 종가를 넣는데 여기서 재계산하지
                # 않으면 총자산이 항상 ~1거래일 스테일로 남는다(KPH 계좌값 불일치의 근본원인). 경량·결정론.
                _step_portfolio(conn, errors, counts)

            status = finalize_status(errors)
        except Exception as exc:
            logger.error("pipeline_analysis 치명적 오류: %s", exc, exc_info=True)
            errors.append(make_error("pipeline_fatal", exc))
            status = finalize_status(errors, fatal=True)

        db.log_run_finish(conn, run_id, status=status, errors=errors)
        logger.info("=== pipeline_analysis 완료 status=%s errors=%d counts=%s ===", status, len(errors), counts)

    return {"status": status, "errors": errors, "counts": counts}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="ATLAS 분석 파이프라인")
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
