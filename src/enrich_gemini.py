"""
enrich_gemini.py — Gemini 호출 래퍼 (뉴스 요약 + 시황 종합)

역할:
  1. enrich_news_batch      : news_raw (새 기사) → Gemini 요약 → news_analysis upsert
  2. enrich_market_summary  : market_daily + 감성 집계 → Gemini 시황 → summary_md 업데이트

환경변수:
  GEMINI_API_KEY
  GEMINI_BULK_MODEL   기본값 "gemini-2.5-flash-lite"  종목별 뉴스 요약 (대량·저렴)
  GEMINI_SYNTH_MODEL  기본값 "gemini-3.5-flash"       시황 종합 1회 (상위 티어)

프롬프트 템플릿: prompt/GEMINI_PROMPT.md §A (뉴스), §B (시황)

⚠️ 투자 자문 아님 / 원금 손실 가능
   Gemini 출력은 정보·참고용이며 매수/매도 신호가 아닙니다.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime
from typing import Optional

import psycopg
from pydantic import ValidationError

from src.db import (
    get_conn,
    log_run_finish,
    log_run_start,
    upsert_market_daily,
    upsert_news_analysis,
)
from src.schemas import (
    MarketDailyRow,
    MarketSummaryOutput,
    NewsAnalysisRow,
    NewsSummaryOutput,
)

logger = logging.getLogger(__name__)

# ── 상수 ─────────────────────────────────────────────────────────
GEMINI_BULK_MODEL_DEFAULT: str = "gemini-2.5-flash-lite"
GEMINI_SYNTH_MODEL_DEFAULT: str = "gemini-3.5-flash"
MAX_NEWS_PER_TICKER: int = 15
BODY_CAP: int = 200        # 뉴스 본문 최대 글자 (토큰 절약)
API_SLEEP: float = 1.5     # API 호출 간 sleep (레이트리밋 방지)

_SOURCE_TAGS: dict[str, str] = {
    "yahoo": "[야후/핵심팩트]",
    "naver": "[네이버/시장트렌드]",
}


# ──────────────────────────────────────────────────────────────
# Gemini 클라이언트
# ──────────────────────────────────────────────────────────────

def _get_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY 환경변수가 설정되지 않았습니다.")
    return key


def _get_bulk_model() -> str:
    return os.environ.get("GEMINI_BULK_MODEL", GEMINI_BULK_MODEL_DEFAULT)


def _get_synth_model() -> str:
    return os.environ.get("GEMINI_SYNTH_MODEL", GEMINI_SYNTH_MODEL_DEFAULT)


def _get_gemini_client():
    """google-genai 클라이언트 반환. 키는 환경변수에서만."""
    from google import genai  # 지연 임포트 (테스트 환경 미설치 대응)
    return genai.Client(api_key=_get_api_key())


def _call_gemini(client, model: str, prompt: str) -> str:
    """
    Gemini API 단건 호출 (response_mime_type=application/json 강제).
    테스트에서 patch("src.enrich_gemini._call_gemini")로 대체한다.
    """
    from google.genai import types
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    return response.text


# ──────────────────────────────────────────────────────────────
# 파싱·검증 헬퍼 (테스트 단위로 노출)
# ──────────────────────────────────────────────────────────────

def _parse_news_output(text: str) -> NewsSummaryOutput:
    """JSON 텍스트 → NewsSummaryOutput pydantic 검증. 실패 시 예외."""
    data = json.loads(text)
    return NewsSummaryOutput.model_validate(data)


def _neutral_news_fallback() -> NewsSummaryOutput:
    """Gemini 2회 실패 시 저장할 중립 기본값 (PRD §A 코드 측 처리 기준)."""
    return NewsSummaryOutput(
        sentiment="중립",
        sentiment_score=0.0,
        key_points=["분석 실패"],
        summary_md="분석 실패",
        confidence="하",
        based_on="recent",
    )


def _parse_market_output(text: str) -> MarketSummaryOutput:
    """JSON 텍스트 → MarketSummaryOutput pydantic 검증. 실패 시 예외."""
    data = json.loads(text)
    return MarketSummaryOutput.model_validate(data)


# ──────────────────────────────────────────────────────────────
# Gemini 호출 + 검증 + 재시도
# ──────────────────────────────────────────────────────────────

def _call_gemini_for_news(
    client,
    model: str,
    prompt: str,
    ticker: str,
) -> NewsSummaryOutput:
    """
    Gemini 뉴스 요약 호출.
    검증 실패 시 1회 재시도. 2회 모두 실패 시 중립 기본값 반환.
    """
    for attempt in range(2):
        try:
            text = _call_gemini(client, model, prompt)
            return _parse_news_output(text)
        except Exception as exc:
            if attempt == 0:
                logger.warning("%s: 뉴스 요약 파싱 실패 (재시도): %s", ticker, exc)
                time.sleep(API_SLEEP)
            else:
                logger.error("%s: 뉴스 요약 2회 실패 — 중립값 저장: %s", ticker, exc)
    return _neutral_news_fallback()


def _call_gemini_for_market(
    client,
    model: str,
    prompt: str,
) -> Optional[MarketSummaryOutput]:
    """
    Gemini 시황 종합 호출.
    검증 실패 시 1회 재시도. 2회 모두 실패 시 None 반환.
    """
    for attempt in range(2):
        try:
            text = _call_gemini(client, model, prompt)
            return _parse_market_output(text)
        except Exception as exc:
            if attempt == 0:
                logger.warning("시황 종합 파싱 실패 (재시도): %s", exc)
                time.sleep(API_SLEEP)
            else:
                logger.error("시황 종합 2회 실패 — 스킵: %s", exc)
    return None


# ──────────────────────────────────────────────────────────────
# 프롬프트 빌더 (prompt/GEMINI_PROMPT.md 템플릿)
# ──────────────────────────────────────────────────────────────

def _build_news_prompt(
    ticker: str,
    company_name: str,
    news_items: list[dict],
) -> str:
    """§A 뉴스 요약 프롬프트. 본문은 BODY_CAP자로 캡."""
    lines: list[str] = []
    for item in news_items:
        tag = _SOURCE_TAGS.get(item.get("source", ""), "[기타]")
        pub_dt = item.get("published_at")
        date_str = pub_dt.strftime("%Y-%m-%d") if pub_dt else "날짜미상"
        title = item.get("title", "")
        body = (item.get("body") or "")[:BODY_CAP]
        lines.append(f"{tag} {date_str} | {title} - {body}")

    news_text = "\n".join(lines)
    n = len(news_items)

    return (
        f"너는 월스트리트 수석 주식 애널리스트다. "
        f"아래 [{company_name}({ticker})] 관련 뉴스 {n}건을 모두 읽고 "
        f"시장 심리와 주가에 영향을 줄 핵심을 분석하라. 분석 기준: 최근 뉴스 기반.\n\n"
        "입력 데이터 태그:\n"
        "- [야후/핵심팩트]: 주가에 직접 영향을 주는 주요 언론 핵심 뉴스. 가장 큰 가중치.\n"
        "- [네이버/시장트렌드]: 시장 참여자들의 전반적 이슈·심리 흐름.\n\n"
        "규칙:\n"
        "- 가장 최근 날짜 뉴스에 더 큰 가중치를 둬라.\n"
        "- 주가에 핵심 영향을 주는 항목은 catalysts에 날짜·중요도와 함께 분리하라.\n"
        "- 매수/매도 의견이나 목표가를 만들지 마라. 사실과 심리 해석만.\n\n"
        "아래 JSON 스키마로만, 순수 JSON으로 답하라(코드펜스·설명 금지):\n"
        '{"sentiment":"긍정|중립|부정","sentiment_score":-1.0~1.0,'
        '"key_points":["불릿3~6개"],'
        '"catalysts":[{"date":"YYYY-MM-DD","headline":"요약","impact":"긍정|부정","importance":"상|중|하"}],'
        '"risks":["하방리스크0~4개"],'
        '"summary_md":"- 불릿\\n- 불릿 형태 종합","confidence":"상|중|하","based_on":"recent|fallback_old"}\n\n'
        f"[분석할 뉴스 리스트]\n{news_text}"
    )


def _build_market_prompt(
    market_metrics: dict,
    sentiment_rollup: dict,
) -> str:
    """§B 시황 종합 프롬프트."""
    market_json = json.dumps(market_metrics, ensure_ascii=False)
    sentiment_json = json.dumps(sentiment_rollup, ensure_ascii=False)

    return (
        "너는 글로벌 매크로 스트래티지스트다. "
        "아래 당일 시장 지표와 관심종목 감성 집계를 바탕으로 오늘 시장 상황을 간결하게 종합하라.\n\n"
        f"지수/지표: {market_json}\n"
        f"관심종목 감성 집계: {sentiment_json}\n\n"
        "규칙:\n"
        "- 특정 종목 매매 권유 금지. 시장 레짐·드라이버·체크포인트만.\n"
        "- 데이터에 근거하라. 방향성 위주로 간결하게.\n\n"
        "아래 JSON 스키마로만, 순수 JSON으로 답하라:\n"
        '{"regime":"위험선호|중립|위험회피","headline":"40자내외 한줄요약",'
        '"drivers":["요인2~4개"],"kr_us_note":"한미온도차1~2문장",'
        '"watch_today":["체크포인트2~4개"],"summary_md":"- 불릿3~5줄"}'
    )


# ──────────────────────────────────────────────────────────────
# DB 조회 헬퍼 (enrich_gemini 전용 쿼리)
# ──────────────────────────────────────────────────────────────

def _tickers_needing_enrichment(
    conn: psycopg.Connection,
    asof: date,
) -> list[str]:
    """오늘 fetched_at 기준 새 뉴스가 있고, 아직 news_analysis 없는 ticker 목록."""
    sql = """
        SELECT DISTINCT nr.ticker
        FROM news_raw nr
        WHERE nr.fetched_at::date = %s
        AND NOT EXISTS (
            SELECT 1 FROM news_analysis na
            WHERE na.ticker = nr.ticker AND na.asof = %s
        )
        ORDER BY nr.ticker
    """
    with conn.cursor() as cur:
        cur.execute(sql, (asof, asof))
        return [row["ticker"] for row in cur.fetchall()]


def _get_ticker_news(
    conn: psycopg.Connection,
    ticker: str,
    asof: date,
) -> list[dict]:
    """ticker의 오늘 뉴스 최대 MAX_NEWS_PER_TICKER건 (최신순)."""
    sql = """
        SELECT title, body, published_at, source
        FROM news_raw
        WHERE ticker = %s AND fetched_at::date = %s
        ORDER BY published_at DESC NULLS LAST
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (ticker, asof, MAX_NEWS_PER_TICKER))
        return [dict(row) for row in cur.fetchall()]


def _get_company_name(conn: psycopg.Connection, ticker: str) -> str:
    """watchlist에서 회사명 조회. 없으면 ticker 반환."""
    sql = "SELECT name FROM watchlist WHERE ticker = %s"
    with conn.cursor() as cur:
        cur.execute(sql, (ticker,))
        row = cur.fetchone()
        return row["name"] if row else ticker


def _get_market_daily_row(
    conn: psycopg.Connection,
    asof: date,
) -> Optional[dict]:
    """오늘 market_daily 레코드. 없으면 None."""
    sql = "SELECT * FROM market_daily WHERE asof = %s"
    with conn.cursor() as cur:
        cur.execute(sql, (asof,))
        row = cur.fetchone()
        return dict(row) if row else None


def _get_sentiment_rollup(
    conn: psycopg.Connection,
    asof: date,
) -> dict:
    """오늘 news_analysis 감성 분포. 예: {"긍정": 5, "중립": 3, "부정": 2}"""
    sql = """
        SELECT sentiment, COUNT(*) AS cnt
        FROM news_analysis
        WHERE asof = %s
        GROUP BY sentiment
    """
    with conn.cursor() as cur:
        cur.execute(sql, (asof,))
        return {row["sentiment"]: int(row["cnt"]) for row in cur.fetchall()}


# ──────────────────────────────────────────────────────────────
# 공개 API 1: 종목별 뉴스 요약 (증분)
# ──────────────────────────────────────────────────────────────

def enrich_news_batch(
    conn: psycopg.Connection,
    asof: Optional[date] = None,
) -> tuple[int, list[dict]]:
    """
    새 뉴스가 있는 종목에 대해 Gemini 요약 실행.
    이미 오늘 news_analysis가 있는 종목은 스킵 (증분 처리).

    Returns
    -------
    (enriched_count, errors)
    """
    asof = asof or date.today()
    client = _get_gemini_client()
    model = _get_bulk_model()
    errors: list[dict] = []
    enriched = 0

    tickers = _tickers_needing_enrichment(conn, asof)
    logger.info("뉴스 요약 대상: %d개 종목 (asof=%s)", len(tickers), asof)

    for ticker in tickers:
        try:
            news_items = _get_ticker_news(conn, ticker, asof)
            if not news_items:
                logger.debug("%s: 뉴스 없음 — 스킵", ticker)
                continue

            company_name = _get_company_name(conn, ticker)
            prompt = _build_news_prompt(ticker, company_name, news_items)

            output = _call_gemini_for_news(client, model, prompt, ticker)

            analysis_row = NewsAnalysisRow(
                ticker=ticker,
                asof=asof,
                sentiment=output.sentiment,
                sentiment_score=output.sentiment_score,
                summary_md=output.summary_md,
                payload=output.model_dump(),
                n_articles=len(news_items),
                model=model,
                based_on=output.based_on,
            )
            upsert_news_analysis(conn, [analysis_row])
            enriched += 1
            logger.info("%s: 요약 완료 (sentiment=%s)", ticker, output.sentiment)

        except Exception as exc:
            logger.error("%s: 뉴스 요약 전체 실패: %s", ticker, exc, exc_info=True)
            errors.append({
                "ticker": ticker,
                "step": "enrich_news",
                "error": str(exc),
                "ts": datetime.utcnow().isoformat(),
            })

        time.sleep(API_SLEEP)  # 레이트리밋 방지

    logger.info("뉴스 요약 완료: %d/%d 종목", enriched, len(tickers))
    return enriched, errors


# ──────────────────────────────────────────────────────────────
# 공개 API 2: 시황 종합 (하루 1회)
# ──────────────────────────────────────────────────────────────

def enrich_market_summary(
    conn: psycopg.Connection,
    asof: Optional[date] = None,
) -> bool:
    """
    오늘 market_daily + 감성 집계 → Gemini 시황 종합 → market_daily.summary_md 업데이트.

    Returns
    -------
    True: 저장 성공 | False: 스킵(데이터 없음) 또는 실패
    """
    asof = asof or date.today()

    market_row = _get_market_daily_row(conn, asof)
    if not market_row:
        logger.warning("market_daily %s 없음 — 시황 종합 스킵", asof)
        return False

    sentiment_rollup = _get_sentiment_rollup(conn, asof)

    market_metrics = {
        "asof": str(asof),
        "KOSPI": market_row.get("kospi"),
        "KOSDAQ": market_row.get("kosdaq"),
        "SP500": market_row.get("sp500"),
        "NASDAQ": market_row.get("nasdaq"),
        "VIX": market_row.get("vix"),
        "USDKRW": market_row.get("usdkrw"),
        "UST10Y": market_row.get("ust10y"),
    }

    client = _get_gemini_client()
    model = _get_synth_model()
    prompt = _build_market_prompt(market_metrics, sentiment_rollup)

    output = _call_gemini_for_market(client, model, prompt)
    if output is None:
        logger.error("시황 종합 실패 — market_daily 업데이트 스킵")
        return False

    updated = MarketDailyRow(
        asof=asof,
        kospi=market_row.get("kospi"),
        kosdaq=market_row.get("kosdaq"),
        sp500=market_row.get("sp500"),
        nasdaq=market_row.get("nasdaq"),
        vix=market_row.get("vix"),
        usdkrw=market_row.get("usdkrw"),
        ust10y=market_row.get("ust10y"),
        summary_md=output.summary_md,
        payload=output.model_dump(),
    )
    upsert_market_daily(conn, updated)
    logger.info("시황 종합 저장 완료 (regime=%s)", output.regime)
    return True


# ──────────────────────────────────────────────────────────────
# 실행 진입점 (python -m src.enrich_gemini)
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info("=== enrich_gemini 시작 ===")

    with get_conn() as conn:
        run_id = log_run_start(conn, "enrich_gemini")
        all_errors: list[dict] = []
        status = "success"

        try:
            enriched_cnt, news_errs = enrich_news_batch(conn)
            all_errors.extend(news_errs)
            logger.info("뉴스 요약: %d종목 완료", enriched_cnt)

            market_ok = enrich_market_summary(conn)
            logger.info("시황 종합: %s", "완료" if market_ok else "스킵/실패")

        except Exception as exc:
            logger.error("enrich_gemini 전체 오류: %s", exc, exc_info=True)
            all_errors.append({
                "step": "enrich_gemini_main",
                "error": str(exc),
                "ts": datetime.utcnow().isoformat(),
            })
            status = "failed"

        if all_errors and status != "failed":
            status = "partial"

        log_run_finish(conn, run_id, status=status, errors=all_errors)
        logger.info("=== enrich_gemini 완료 status=%s ===", status)

    print("\n⚠️ 투자 자문 아님 / 원금 손실 가능")
