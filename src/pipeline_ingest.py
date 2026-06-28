"""
pipeline_ingest.py — 수집 파이프라인 실행기 (설계 §4.1, §9 2단계)

행위 보존: 기존 run_pipeline/news_refresh의 수집 단계 구현을 그대로 호출만 이전한다.
지표·점수 계산, LLM 호출, export는 하지 않는다.

  python -m src.pipeline_ingest --profile daily|refresh

daily   : 시장·거시·드라이버 가격·KR/US 가격/재무/밸류/컨센서스·종목/시장 뉴스
refresh : 전 종목 경량 가격(prices만)·종목 뉴스·시장 뉴스

출력 테이블: market_daily, macro_indicators, driver_prices, prices_daily,
            fundamentals, valuation, analyst, news_raw, market_news

# ponytail: daily 단계 함수는 run_pipeline._step_* 구현을 그대로 옮긴 것.
#           run_pipeline 쪽 중복본은 설계 §9 8단계(dead code 제거)까지 유지한다.
시크릿은 소유 모듈이 환경변수에서만 읽는다. 자동 주문 없음.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from datetime import date
from typing import Optional

import psycopg

from src import db
from src import ingest_drivers, ingest_investor_flow, ingest_kr, ingest_macro, ingest_market, ingest_market_news, ingest_news, ingest_us
from src.pipeline_common import (
    PROFILE_DAILY,
    PROFILE_REFRESH,
    VALID_PROFILES,
    active_universe,
    finalize_status,
    make_error,
    split_kr_us,
)

logger = logging.getLogger(__name__)

RUN_KIND = "pipeline_ingest"

# 단계 순서를 짧은 튜플 상수로 노출 (설계 §5)
DAILY_STEPS = (
    "market",
    "macro",
    "driver_prices",
    "ingest_kr",
    "ingest_us",
    "ingest_news",
    "ingest_market_news",
    "investor_flow",        # E-2: KR 투자자 수급 (KR만)
)
REFRESH_STEPS = (
    "price_refresh",
    "ingest_news",
    "ingest_market_news",
)


# ──────────────────────────────────────────────────────────────
# 수집 단계 (run_pipeline._step_* / news_refresh와 동일 동작)
# ──────────────────────────────────────────────────────────────

def _ingest_market(conn: psycopg.Connection, errors: list, counts: dict) -> None:
    logger.info("수집: 시장 지표")
    try:
        result = ingest_market.run_market_ingest()
        market_row = result.get("market")
        if market_row:
            db.upsert_market_daily(conn, market_row)
            conn.commit()
            counts["market_daily"] = counts.get("market_daily", 0) + 1
        errors.extend(result.get("errors", []))
    except Exception as exc:
        conn.rollback()
        logger.error("시장 수집 실패: %s", exc, exc_info=True)
        errors.append(make_error("market", exc))


def _ingest_macro(conn: psycopg.Connection, errors: list, counts: dict) -> None:
    logger.info("수집: 거시 지표")
    try:
        result = ingest_macro.run_macro_ingest()
        rows = result.get("rows", [])
        if rows:
            db.upsert_macro_indicators(conn, rows)
            conn.commit()
            counts["macro_indicators"] = counts.get("macro_indicators", 0) + len(rows)
        errors.extend(result.get("errors", []))
    except Exception as exc:
        conn.rollback()
        logger.error("거시 수집 실패: %s", exc, exc_info=True)
        errors.append(make_error("macro", exc))


def _ingest_driver_prices(conn: psycopg.Connection, errors: list, counts: dict) -> None:
    logger.info("수집: 드라이버 프록시 가격")
    try:
        result = ingest_drivers.run_driver_price_ingest(conn)
        conn.commit()
        rows = result.get("rows", [])
        counts["driver_prices"] = counts.get("driver_prices", 0) + len(rows)
        errors.extend(result.get("errors", []))
    except Exception as exc:
        conn.rollback()
        logger.error("드라이버 가격 수집 실패: %s", exc, exc_info=True)
        errors.append(make_error("driver_prices", exc))


def _ingest_kr(conn: psycopg.Connection, kr_tickers: list[str], errors: list, counts: dict) -> None:
    logger.info("수집: KR (%d종목)", len(kr_tickers))
    if not kr_tickers:
        return
    try:
        result = ingest_kr.run_kr_ingest(kr_tickers)
        _store_security_ingest(conn, result, counts)
        conn.commit()
        errors.extend(result.get("errors", []))
    except Exception as exc:
        conn.rollback()
        logger.error("KR 수집 실패: %s", exc, exc_info=True)
        errors.append(make_error("ingest_kr", exc))


def _ingest_us(conn: psycopg.Connection, us_tickers: list[str], errors: list, counts: dict) -> None:
    logger.info("수집: US (%d종목)", len(us_tickers))
    if not us_tickers:
        return
    try:
        result = ingest_us.run_us_ingest(us_tickers)
        _store_security_ingest(conn, result, counts)
        conn.commit()
        errors.extend(result.get("errors", []))
    except Exception as exc:
        conn.rollback()
        logger.error("US 수집 실패: %s", exc, exc_info=True)
        errors.append(make_error("ingest_us", exc))


def _store_security_ingest(conn: psycopg.Connection, result: dict, counts: dict) -> None:
    """KR/US 수집 결과를 동일 방식으로 적재 (run_pipeline _step_ingest_kr/us와 동일)."""
    for price_rows in result.get("prices", {}).values():
        if price_rows:
            db.upsert_price_daily(conn, price_rows)
            counts["prices_daily"] = counts.get("prices_daily", 0) + len(price_rows)
    for fund_rows in result.get("fundamentals", {}).values():
        if fund_rows:
            db.upsert_fundamentals(conn, fund_rows)
            counts["fundamentals"] = counts.get("fundamentals", 0) + len(fund_rows)
    for val_row in result.get("valuations", {}).values():
        if val_row:
            db.upsert_valuation(conn, [val_row])
            counts["valuation"] = counts.get("valuation", 0) + 1
    for ana_row in result.get("analysts", {}).values():
        if ana_row:
            db.upsert_analyst(conn, [ana_row])
            counts["analyst"] = counts.get("analyst", 0) + 1


def _ingest_news(conn: psycopg.Connection, all_tickers: list[str], errors: list, counts: dict) -> None:
    logger.info("수집: 종목 뉴스 (%d종목)", len(all_tickers))
    if not all_tickers:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT ticker, name FROM watchlist")
            company_names = {r["ticker"]: r["name"] for r in cur.fetchall()}
        result = ingest_news.run_news_ingest(all_tickers, company_names=company_names)
        new_total = 0
        for news_rows in result.get("news", {}).values():
            if news_rows:
                new_total += db.insert_news_raw(conn, news_rows)
        conn.commit()
        counts["news_raw"] = counts.get("news_raw", 0) + new_total
        errors.extend(result.get("errors", []))
    except Exception as exc:
        conn.rollback()
        logger.error("종목 뉴스 수집 실패: %s", exc, exc_info=True)
        errors.append(make_error("ingest_news", exc))


def _ingest_market_news(conn: psycopg.Connection, errors: list, counts: dict) -> None:
    logger.info("수집: 시장 뉴스")
    try:
        result = ingest_market_news.run_market_news_ingest()
        inserted = db.insert_market_news(conn, result.get("rows", []))
        conn.commit()
        counts["market_news"] = counts.get("market_news", 0) + inserted
        errors.extend(result.get("errors", []))
    except Exception as exc:
        conn.rollback()
        logger.error("시장 뉴스 수집 실패: %s", exc, exc_info=True)
        errors.append(make_error("ingest_market_news", exc))


def _ingest_investor_flow(
    conn: psycopg.Connection, kr_tickers: list[str], errors: list, counts: dict
) -> None:
    """E-2: KR 종목 투자자 수급 수집 + 신호 저장."""
    logger.info("수집: KR 투자자 수급 (%d종목)", len(kr_tickers))
    try:
        result = ingest_investor_flow.run_investor_flow_ingest(conn, kr_tickers)
        c = result.get("counts", {})
        counts["investor_flow"] = counts.get("investor_flow", 0) + c.get("rows", 0)
        errors.extend(result.get("errors", []))
    except Exception as exc:
        conn.rollback()
        logger.error("investor_flow 수집 실패: %s", exc, exc_info=True)
        errors.append(make_error("investor_flow", exc))


def _ingest_refresh_prices(conn: psycopg.Connection, watchlist: list[dict], errors: list, counts: dict) -> None:
    """refresh 경량 가격: news_refresh._refresh_prices_light의 가격 부분만 (지표·퀀트 제외)."""
    logger.info("수집: 경량 가격 (%d종목)", len(watchlist))
    n_price = 0
    for w in watchlist:
        ticker, market = w["ticker"], w["market"]
        try:
            rows = ingest_kr.fetch_kr_prices(ticker) if market == "KR" else ingest_us.fetch_us_prices(ticker)
            if rows:
                db.upsert_price_daily(conn, rows)
                conn.commit()
                n_price += len(rows)
        except Exception as exc:
            conn.rollback()
            logger.warning("가격 갱신 실패 %s: %s", ticker, exc)
            err = make_error("price", exc)
            err["ticker"] = ticker
            errors.append(err)
    counts["prices_daily"] = counts.get("prices_daily", 0) + n_price


# ──────────────────────────────────────────────────────────────
# 진입점
# ──────────────────────────────────────────────────────────────

def run(profile: str, asof: Optional[date] = None) -> dict:
    """수집 파이프라인 실행. 반환: {status, errors, counts}."""
    if profile not in VALID_PROFILES:
        raise ValueError(f"unknown profile: {profile!r} (allowed: {VALID_PROFILES})")
    asof = asof or date.today()
    errors: list[dict] = []
    counts: dict = {}
    status = "success"

    with db.get_conn() as conn:
        run_id = db.log_run_start(conn, RUN_KIND)
        logger.info("=== pipeline_ingest 시작 profile=%s asof=%s run_id=%d ===", profile, asof, run_id)
        try:
            watchlist = active_universe(conn)
            kr_tickers, us_tickers, all_tickers = split_kr_us(watchlist)
            logger.info("유니버스: KR=%d US=%d 합계=%d", len(kr_tickers), len(us_tickers), len(all_tickers))

            if profile == PROFILE_DAILY:
                _ingest_market(conn, errors, counts)
                _ingest_macro(conn, errors, counts)
                _ingest_driver_prices(conn, errors, counts)
                _ingest_kr(conn, kr_tickers, errors, counts)
                _ingest_us(conn, us_tickers, errors, counts)
                _ingest_news(conn, all_tickers, errors, counts)
                _ingest_market_news(conn, errors, counts)
                _ingest_investor_flow(conn, kr_tickers, errors, counts)  # E-2
            else:  # PROFILE_REFRESH
                _ingest_refresh_prices(conn, watchlist, errors, counts)
                _ingest_news(conn, all_tickers, errors, counts)
                _ingest_market_news(conn, errors, counts)

            status = finalize_status(errors)
        except Exception as exc:
            logger.error("pipeline_ingest 치명적 오류: %s", exc, exc_info=True)
            errors.append(make_error("pipeline_fatal", exc))
            status = finalize_status(errors, fatal=True)

        db.log_run_finish(conn, run_id, status=status, errors=errors)
        logger.info("=== pipeline_ingest 완료 status=%s errors=%d counts=%s ===", status, len(errors), counts)

    return {"status": status, "errors": errors, "counts": counts}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="ATLAS 수집 파이프라인")
    parser.add_argument("--profile", required=True, help="daily | refresh")
    args = parser.parse_args(argv)

    if args.profile not in VALID_PROFILES:
        print(f"invalid profile: {args.profile!r} (allowed: {', '.join(VALID_PROFILES)})", file=sys.stderr)
        return 2

    result = run(args.profile)
    return 0 if result["status"] in ("success", "partial") else 1


def _residual_nondaemon_threads() -> list[str]:
    """메인 스레드를 제외한, 아직 살아있는 비-데몬 스레드 이름 목록.

    비-데몬 스레드가 남아 있으면 `sys.exit()`가 join 대기로 막혀 프로세스가 종료되지 못한다
    (06시 split 90분 timeout 사고의 메커니즘). __main__에서 진단 로그 + 강제 종료에 사용.
    """
    main_thread = threading.main_thread()
    return [
        t.name
        for t in threading.enumerate()
        if t is not main_thread and t.is_alive() and not t.daemon
    ]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    _code = main()
    # P0 안전망: run()에서 DB commit/flush는 모두 끝난 상태. 외부 라이브러리가 비-데몬 스레드를
    # 남겨 sys.exit()가 막히는 일을 막기 위해, 잔류 스레드를 진단 로그로 남기고 강제 종료한다.
    _residual = _residual_nondaemon_threads()
    if _residual:
        logger.warning("잔류 비-데몬 스레드 %d개 — 강제 종료로 프로세스 행 방지: %s", len(_residual), _residual)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_code)
