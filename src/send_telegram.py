"""
send_telegram.py — 텔레그램 아침 브리핑 발송

HERMES_PROMPT.md §2 템플릿을 Python f-string으로 채워 텔레그램으로 발송.
Gemini/Hermes 없이 동작 (Phase 3 후반에 Hermes로 업그레이드 예정).

환경변수:
  TELEGRAM_BOT_TOKEN  텔레그램 봇 토큰
  TELEGRAM_CHAT_ID    발송 채팅 ID (사용자 또는 그룹)

텔레그램 4096자 제한 → 초과 시 앞부분 우선, 뒤 자르기.

"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime
from typing import Optional

import requests

import psycopg

from src.assemble import assemble_daily
from src.db import get_conn
from src.schemas import StockDailyRecord

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
MAX_LEN = 4096
_WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

# ──────────────────────────────────────────────────────────────
# DB 조회 헬퍼
# ──────────────────────────────────────────────────────────────

def _q_market_today(conn: psycopg.Connection, asof: date) -> Optional[dict]:
    """market_daily 오늘 레코드 (payload 포함)."""
    sql = "SELECT * FROM market_daily WHERE asof = %s"
    with conn.cursor() as cur:
        cur.execute(sql, (asof,))
        row = cur.fetchone()
        return dict(row) if row else None


# ──────────────────────────────────────────────────────────────
# 브리핑 포맷터
# ──────────────────────────────────────────────────────────────

def _safe(v, fmt=".1f", unit="") -> str:
    """None-safe 숫자 포맷."""
    if v is None:
        return "—"
    try:
        return f"{float(v):{fmt}}{unit}"
    except (TypeError, ValueError):
        return str(v)


def _market_section(market: Optional[dict]) -> str:
    """🌎 시장 섹션."""
    if not market:
        return "🌎 시장 데이터 없음\n"

    payload: dict = {}
    raw = market.get("payload") or {}
    if isinstance(raw, str):
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            payload = {}
    else:
        payload = raw

    regime = payload.get("regime", "—")
    headline = payload.get("headline") or ""
    drivers: list[str] = payload.get("drivers") or []
    watch: list[str] = payload.get("watch_today") or []

    lines = [f"🌎 시장  [{regime}]"]
    if headline:
        lines.append(headline)
    for d in drivers[:2]:
        lines.append(f"• {d}")
    for w in watch[:2]:
        lines.append(f"• 오늘 체크: {w}")

    # 요약 없으면 지표 fallback
    if not headline and not drivers:
        parts = []
        if market.get("kospi"):
            parts.append(f"KOSPI {_safe(market['kospi'], '.0f')}")
        if market.get("sp500"):
            parts.append(f"S&P500 {_safe(market['sp500'], '.0f')}")
        if market.get("vix"):
            parts.append(f"VIX {_safe(market['vix'])}")
        if market.get("usdkrw"):
            parts.append(f"USD/KRW {_safe(market['usdkrw'], '.0f')}")
        if parts:
            lines.append("  ".join(parts))

    return "\n".join(lines)


def _quant_section(records: list[StockDailyRecord]) -> str:
    """🏆 관심종목 퀀트 섹션 (composite 기준 상위 3 / 하위 2)."""
    scored = [r for r in records if r.quant.composite is not None]
    if not scored:
        return "🏆 퀀트 점수 데이터 없음"

    scored.sort(key=lambda r: r.quant.composite, reverse=True)
    top = scored[:3]
    bottom = scored[-2:] if len(scored) > 3 else []

    lines = ["🏆 관심종목 퀀트 (composite)"]
    lines.append("상위: " + "  ".join(f"{r.name} {r.quant.composite:.0f}" for r in top))
    if bottom:
        lines.append("주의: " + "  ".join(f"{r.name} {r.quant.composite:.0f}" for r in bottom))

    return "\n".join(lines)


def _flags_section(records: list[StockDailyRecord]) -> str:
    """🚩 오늘의 플래그 섹션."""
    flag_lines = []
    for r in records:
        for flag in (r.quant.flags or []):
            # 사전필터·데이터부족 같은 시스템 flag는 제외
            if any(skip in flag for skip in ("사전필터", "데이터 부족", "발행주식수")):
                continue
            flag_lines.append(f"• {r.name}({r.ticker}) {flag}")

    lines = ["🚩 오늘의 플래그"]
    if flag_lines:
        lines.extend(flag_lines[:8])  # 최대 8개
    else:
        lines.append("특이 알림 없음")
    return "\n".join(lines)


def _news_section(records: list[StockDailyRecord]) -> str:
    """📰 주목 뉴스 섹션 (최대 3건)."""
    news_items = [
        r for r in records
        if r.news.sentiment and r.news.summary_md
    ]
    # 긍정/부정 우선, 중립 후순
    news_items.sort(key=lambda r: abs(r.news.score or 0), reverse=True)

    lines = ["📰 주목 뉴스 (심리)"]
    for r in news_items[:3]:
        sent = r.news.sentiment or "—"
        first_line = (r.news.summary_md or "").split("\n")[0].lstrip("- ").strip()
        lines.append(f"• [{sent}] {r.name}: {first_line[:60]}")

    if len(lines) == 1:
        lines.append("뉴스 데이터 없음")
    return "\n".join(lines)


def format_brief(
    records: list[StockDailyRecord],
    market: Optional[dict] = None,
    asof: Optional[date] = None,
) -> str:
    """
    HERMES_PROMPT §2 템플릿을 채워 텔레그램 메시지 문자열 반환.
    4096자 초과 시 뒤부터 자름.
    """
    asof = asof or date.today()
    wd = _WEEKDAYS[asof.weekday()]
    header = f"📊 ATLAS 아침 브리핑 · {asof.strftime('%Y-%m-%d')} ({wd})\n"

    sections = [
        header,
        _market_section(market),
        "",
        _quant_section(records),
        "",
        _flags_section(records),
        "",
        _news_section(records),
    ]

    text = "\n".join(sections)
    if len(text) > MAX_LEN:
        text = text[:MAX_LEN - 2] + "…"

    return text


# ──────────────────────────────────────────────────────────────
# 텔레그램 발송
# ──────────────────────────────────────────────────────────────

def telegram_enabled() -> bool:
    """
    텔레그램 발송 활성 여부. 기본 비활성(보류).
    살리려면 환경변수 TELEGRAM_ENABLED=true + TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID 설정,
    그리고 .github/workflows/auto_run.yml의 '텔레그램 브리핑 발송' step 주석 해제.
    """
    return os.environ.get("TELEGRAM_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


def _get_env(key: str) -> str:
    v = os.environ.get(key)
    if not v:
        raise RuntimeError(f"{key} 환경변수가 설정되지 않았습니다.")
    return v


def send_telegram(text: str) -> bool:
    """
    텔레그램 메시지 발송.
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 환경변수 필요.
    성공 시 True, 실패 시 False (예외 삼키지 않음).
    """
    token = _get_env("TELEGRAM_BOT_TOKEN")
    chat_id = _get_env("TELEGRAM_CHAT_ID")

    url = TELEGRAM_API.format(token=token)
    payload = {"chat_id": chat_id, "text": text}

    resp = requests.post(url, json=payload, timeout=15)
    if resp.status_code == 200:
        logger.info("텔레그램 발송 완료 (%d자)", len(text))
        return True
    else:
        logger.error("텔레그램 발송 실패: %s %s", resp.status_code, resp.text[:200])
        return False


# ──────────────────────────────────────────────────────────────
# 진입점
# ──────────────────────────────────────────────────────────────

def run_send(conn: psycopg.Connection, asof: Optional[date] = None) -> bool:
    """
    DB에서 오늘자 데이터를 읽어 브리핑을 생성하고 텔레그램으로 발송.
    성공 시 True. (PR-1) TELEGRAM_ENABLED=false(기본)면 발송하지 않고 no-op 성공 반환.
    """
    if not telegram_enabled():
        logger.info("텔레그램 보류(비활성) — TELEGRAM_ENABLED 미설정. 발송 스킵.")
        return True

    asof = asof or date.today()
    records = assemble_daily(conn, asof=asof)
    market = _q_market_today(conn, asof)

    text = format_brief(records, market=market, asof=asof)
    logger.info("브리핑 생성 완료: %d자, %d종목", len(text), len(records))

    return send_telegram(text)


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info("=== 텔레그램 브리핑 발송 시작 ===")

    with get_conn() as conn:
        ok = run_send(conn)
        if ok:
            logger.info("발송 완료")
        else:
            logger.error("발송 실패")
            sys.exit(1)
