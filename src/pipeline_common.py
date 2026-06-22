"""
pipeline_common.py — 파이프라인 분리용 최소 공유 헬퍼 (설계 §5)

여기에는 두 종류만 둔다.
  1. 활성 유니버스 조회 + KR/US 분리
  2. 오류 dict 생성 + 실행 상태(success|partial|failed) 확정

DI 컨테이너·추상 base pipeline·step registry class는 만들지 않는다.
단계 순서는 각 실행기의 짧은 튜플 상수로 보이게 둔다.
"""

from __future__ import annotations

from datetime import datetime, timezone

import psycopg

# 허용 프로필 — 코드 상수 두 개뿐 (설계 §6)
PROFILE_DAILY = "daily"
PROFILE_REFRESH = "refresh"
VALID_PROFILES = (PROFILE_DAILY, PROFILE_REFRESH)


def active_universe(conn: psycopg.Connection) -> list[dict]:
    """watchlist active 종목 (ticker, market) 목록 — run_pipeline과 동일 SQL."""
    sql = "SELECT ticker, market FROM watchlist WHERE active = TRUE ORDER BY ticker"
    with conn.cursor() as cur:
        cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]


def split_kr_us(watchlist: list[dict]) -> tuple[list[str], list[str], list[str]]:
    """유니버스 → (kr_tickers, us_tickers, all_tickers)."""
    kr = [w["ticker"] for w in watchlist if w["market"] == "KR"]
    us = [w["ticker"] for w in watchlist if w["market"] == "US"]
    all_ = [w["ticker"] for w in watchlist]
    return kr, us, all_


def make_error(step: str, exc: Exception) -> dict:
    """run_pipeline._err와 동일 형식의 오류 dict."""
    return {"step": step, "error": str(exc), "ts": datetime.now(timezone.utc).isoformat()}


def finalize_status(errors: list, *, fatal: bool = False) -> str:
    """실행 상태 확정: 치명적이면 failed, 오류만 있으면 partial, 아니면 success."""
    if fatal:
        return "failed"
    if errors:
        return "partial"
    return "success"
