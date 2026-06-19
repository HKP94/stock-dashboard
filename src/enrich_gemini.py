"""
enrich_gemini.py — Gemini 호출 래퍼 (뉴스 요약 + 시황 종합)

역할:
  1. enrich_news_batch      : news_raw (새 기사) → Gemini 요약 → news_analysis upsert
  2. enrich_market_summary  : market_daily + 감성 집계 → Gemini 시황 → summary_md 업데이트

환경변수:
  GEMINI_API_KEY
  GEMINI_BULK_MODEL   기본값 "gemini-2.5-flash-lite"  종목별 뉴스 요약 (대량·저렴)
  GEMINI_SYNTH_MODEL  기본값 "gemini-2.5-flash"       시황 종합 1회 (상위 티어, 2.5-flash 계열)

프롬프트 템플릿: prompt/GEMINI_PROMPT.md §A (뉴스), §B (시황)

Gemini는 코드가 계산한 표시 신호를 새로 만들지 않습니다.
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
    replace_ticker_context,
    upsert_market_daily,
    upsert_market_news_summary,
    upsert_news_analysis,
)
from src.schemas import (
    MarketDailyRow,
    MarketNewsDigestOutput,
    MarketNewsSummaryRow,
    MarketSummaryOutput,
    NewsAnalysisRow,
    NewsSummaryOutput,
    TickerContextRow,
)

logger = logging.getLogger(__name__)

# ── 상수 ─────────────────────────────────────────────────────────
GEMINI_BULK_MODEL_DEFAULT: str = "gemini-2.5-flash-lite"
# 시황 종합(1회/일)·상위 티어. 2.5-flash 계열로 통일(실호출 검증 2026-06-17). 무효 모델명이면 전량 실패.
GEMINI_SYNTH_MODEL_DEFAULT: str = "gemini-2.5-flash"
MAX_NEWS_PER_TICKER: int = 15
BODY_CAP: int = 200        # 뉴스 본문 최대 글자 (토큰 절약)
API_SLEEP: float = 1.5     # API 호출 간 sleep (레이트리밋 방지)

# PR-1(진단): 네트워크/일시오류(429·503·타임아웃) 지수 백오프 재시도. 파싱/스키마 실패와 구분.
TRANSIENT_RETRIES: int = 3        # _call_gemini 일시오류 재시도 횟수 (CLAUDE.md §3)
TRANSIENT_BACKOFF_BASE: float = 2.0   # 백오프 기준(초): 2, 4, 8 ...
_TRANSIENT_MARKERS: tuple[str, ...] = (
    "429", "503", "500", "resource_exhausted", "rate limit", "ratelimit",
    "quota", "unavailable", "overloaded", "deadline", "timeout", "timed out",
    "internal error", "try again",
)

# PR-1(진단): 폴백(요약 생성 실패) 식별 마커. 구버전("분석 실패")·신버전("일시 보류") 모두 포함.
# export가 이 마커를 화면에 노출하지 않도록 공용으로 사용한다.
FALLBACK_MARKERS: tuple[str, ...] = ("분석 실패", "일시 보류", "자동 요약을 일시")


def is_fallback_summary(summary_md: Optional[str], based_on: Optional[str] = None) -> bool:
    """요약이 '생성 실패 폴백'인지 판정. based_on='fallback_old'(신표식) 또는 마커 문자열로."""
    if based_on == "fallback_old":
        return True
    if not summary_md:
        return True
    return any(m in summary_md for m in FALLBACK_MARKERS)


_SOURCE_TAGS: dict[str, str] = {
    "yahoo": "[야후/핵심팩트]",
    "naver": "[네이버/시장트렌드]",
}


def _ensure_env() -> None:
    """PR-1(진단): .env를 환경변수로 로드(이미 있으면 유지). 로컬 실행 시 GEMINI_API_KEY 누락 방지.
    (src 어디에도 load_dotenv가 없어 로컬 enrich가 키 UNSET으로 통째 실패하던 문제 수정.)"""
    try:
        from dotenv import load_dotenv
        load_dotenv(override=False)
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────
# Gemini 클라이언트
# ──────────────────────────────────────────────────────────────

def _get_api_key() -> str:
    _ensure_env()  # PR-1: .env 로드(로컬)
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


def _is_transient(exc: Exception) -> bool:
    """일시적(재시도 가치 있는) 오류인지 — 429/503/타임아웃/쿼터 등."""
    msg = str(exc).lower()
    return any(m in msg for m in _TRANSIENT_MARKERS)


def _call_gemini_with_backoff(client, model: str, prompt: str) -> str:
    """PR-1(진단): _call_gemini를 지수 백오프로 감싼다.
    429/503/타임아웃 등 '일시오류'만 재시도(최대 TRANSIENT_RETRIES). 그 외(잘못된 요청 등)는 즉시 전파.
    이게 종목별 폴백 사고(production ~60%)를 줄이는 핵심 — 단건 일시오류를 흡수.
    파싱/스키마 실패는 여기서 다루지 않는다(상위 _call_gemini_for_*가 별도 재시도)."""
    last: Optional[Exception] = None
    for attempt in range(TRANSIENT_RETRIES):
        try:
            return _call_gemini(client, model, prompt)
        except Exception as exc:
            last = exc
            if not _is_transient(exc) or attempt == TRANSIENT_RETRIES - 1:
                raise
            wait = TRANSIENT_BACKOFF_BASE * (2 ** attempt)
            logger.warning("Gemini 일시오류(%s) — %.0fs 후 재시도 %d/%d",
                           str(exc)[:80], wait, attempt + 2, TRANSIENT_RETRIES)
            time.sleep(wait)
    assert last is not None
    raise last


# ──────────────────────────────────────────────────────────────
# 파싱·검증 헬퍼 (테스트 단위로 노출)
# ──────────────────────────────────────────────────────────────

def _parse_news_output(text: str) -> NewsSummaryOutput:
    """JSON 텍스트 → NewsSummaryOutput pydantic 검증. 실패 시 예외."""
    data = json.loads(text)
    return NewsSummaryOutput.model_validate(data)


def _neutral_news_fallback() -> NewsSummaryOutput:
    """Gemini 2회 실패 시 저장할 중립 기본값. PR-3: '빈약한 실패' 대신 안내 문구.
    PR-1(진단): based_on='fallback_old'로 표식 → enrich가 runs.errors에 기록하고,
    export가 화면에 노출하지 않으며, 다음 실행 때 재시도 대상으로 선별된다."""
    return NewsSummaryOutput(
        sentiment="중립",
        sentiment_score=0.0,
        key_points=["뉴스 자동 요약을 일시적으로 생성하지 못함 — 원문 뉴스/지표를 참고하세요."],
        summary_md="- 뉴스 자동 요약 일시 보류(생성 실패). 종목상세의 원문 뉴스와 가격·지표를 참고하세요.",
        confidence="하",
        based_on="fallback_old",
    )


def _parse_market_output(text: str) -> MarketSummaryOutput:
    """JSON 텍스트 → MarketSummaryOutput pydantic 검증. 실패 시 예외."""
    data = json.loads(text)
    return MarketSummaryOutput.model_validate(data)


def _parse_market_news_digest_output(text: str) -> MarketNewsDigestOutput:
    data = json.loads(text)
    return MarketNewsDigestOutput.model_validate(data)


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
            text = _call_gemini_with_backoff(client, model, prompt)
            return _parse_news_output(text)
        except Exception as exc:
            if attempt == 0:
                logger.warning("%s: 뉴스 요약 파싱/호출 실패 (재시도): %s", ticker, exc)
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
            text = _call_gemini_with_backoff(client, model, prompt)
            return _parse_market_output(text)
        except Exception as exc:
            if attempt == 0:
                logger.warning("시황 종합 파싱/호출 실패 (재시도): %s", exc)
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
        "★ 핵심 원칙 — '정보 나열'이 아니라 '인사이트':\n"
        "- 각 key_point는 [핵심 사실] + [그것이 왜 중요한가/주가·심리에 주는 의미] 형태로 1줄 인사이트를 담아라.\n"
        "  예: '실적 가이던스 상향(사실) → 시장 컨센서스를 웃돌아 단기 모멘텀 강화로 해석(의미)'.\n"
        "- summary_md 첫 줄은 '오늘 이 종목 뉴스의 한 줄 결론(의미 중심)'으로 시작하라.\n\n"
        "규칙:\n"
        "- 가장 최근 날짜 뉴스에 더 큰 가중치를 둬라.\n"
        "- 부정·리스크 뉴스도 중요하게 평가하라. 악재·우려·하락 요인을 호재보다 낮게 다루지 마라.\n"
        "- 주가에 핵심 영향을 주는 항목은 catalysts에 날짜·중요도와 함께 분리하라.\n"
        "- 코드가 제공하는 표시 신호를 새로 만들지 마라. 뉴스 사실과 심리 해석만 작성하라.\n"
        "- 과도한 강조 표시(*, **)는 쓰지 마라. 꼭 필요한 강조가 아니면 평문으로 써라.\n\n"
        "아래 JSON 스키마로만, 순수 JSON으로 답하라(코드펜스·설명 금지):\n"
        '{"sentiment":"긍정|중립|부정","sentiment_score":-1.0~1.0,'
        '"key_points":["[사실]→[의미] 형태 불릿3~6개"],'
        '"catalysts":[{"date":"YYYY-MM-DD","headline":"요약","impact":"긍정|부정","importance":"상|중|하"}],'
        '"risks":["하방리스크0~4개"],'
        '"summary_md":"- 한 줄 결론(의미)\\n- [사실]→[의미] 불릿","confidence":"상|중|하","based_on":"recent|fallback_old"}\n\n'
        f"[분석할 뉴스 리스트]\n{news_text}"
    )


def _build_market_prompt(
    market_metrics: dict,
    sentiment_rollup: dict,
) -> str:
    """§B 시황 종합 프롬프트."""
    # default=str: Decimal 등 비직렬화 타입이 새어들어도 죽지 않게
    market_json = json.dumps(market_metrics, ensure_ascii=False, default=str)
    sentiment_json = json.dumps(sentiment_rollup, ensure_ascii=False, default=str)

    return (
        "너는 글로벌 매크로 스트래티지스트다. "
        "아래 당일 시장 지표와 관심종목 감성 집계를 바탕으로 오늘 시장 상황을 간결하게 종합하라.\n\n"
        f"지수/지표: {market_json}\n"
        f"관심종목 감성 집계: {sentiment_json}\n\n"
        "규칙:\n"
        "- 특정 종목 주문 실행 지시 금지. 시장 국면·동인·체크포인트만 작성하라.\n"
        "- 데이터에 근거하라. 방향성 위주로 간결하게.\n"
        "- 과도한 강조 표시(*, **)는 쓰지 마라. 꼭 필요한 강조가 아니면 평문으로 써라.\n\n"
        "아래 JSON 스키마로만, 순수 JSON으로 답하라:\n"
        '{"regime":"위험선호|중립|위험회피","headline":"40자내외 한줄요약",'
        '"drivers":["요인2~4개"],"kr_us_note":"한미온도차1~2문장",'
        '"watch_today":["체크포인트2~4개"],"summary_md":"- 불릿3~5줄"}'
    )


def _build_region_market_prompt(
    region: str,            # "한국" | "미국"
    metrics: dict,          # 해당 시장 지표만
    news_items: list[dict], # 해당 시장 뉴스
) -> str:
    """PR-4: 시장별(KR/US) 전용 시황 프롬프트. 입력 데이터를 시장별로 분리해 서로 다른 근거를 강제."""
    metrics_json = json.dumps(metrics, ensure_ascii=False, default=str)
    news_lines = []
    for it in news_items[:12]:
        pub = it.get("published_at")
        d = pub.strftime("%Y-%m-%d") if pub else "날짜미상"
        title = (it.get("title") or "")[:120]
        news_lines.append(f"- {d} | {title}")
    news_text = "\n".join(news_lines) if news_lines else "(관련 뉴스 없음)"

    return (
        f"너는 {region} 시장 전담 매크로 스트래티지스트다. "
        f"아래 '{region} 시장 전용' 지표와 뉴스만 근거로 오늘 {region} 증시를 해석하라.\n"
        f"다른 시장({'미국' if region=='한국' else '한국'}) 언급은 최소화하고, 반드시 아래 데이터에 근거하라.\n\n"
        f"[{region} 시장 지표 (전일대비 등락 포함)]\n{metrics_json}\n\n"
        f"[{region} 시장 뉴스]\n{news_text}\n\n"
        "★ 핵심 원칙 — '수치 나열'이 아니라 '인사이트'를 써라:\n"
        "- 단순히 'KOSPI 8124, 환율 1518' 처럼 숫자를 읊지 마라.\n"
        "- 각 불릿은 [수치/사실] → [그래서 무엇을 의미하는가] 구조로. 즉 '왜 중요한가'를 해석하라.\n"
        "- summary_md 3~5줄에 반드시 ① 오늘 시장 국면 해석 ② 주목할 리스크 또는 기회 ③ 관심종목군(섹터)에 주는 시사점을 담아라.\n\n"
        "규칙:\n"
        "- 데이터에 없는 종목 신호를 만들지 말고 관찰·해석만 서술하라.\n"
        "- 과도한 강조 표시(*, **)는 쓰지 마라. 꼭 필요한 강조가 아니면 평문으로 써라.\n"
        f"- 반드시 {region} 시장 고유의 근거(지수 등락·환율/금리·뉴스)를 인용하라.\n\n"
        "아래 JSON 스키마로만, 순수 JSON으로 답하라:\n"
        '{"regime":"위험선호|중립|위험회피","headline":"40자내외 한줄 인사이트(수치+의미)",'
        '"drivers":["오늘 시장을 움직인 요인 2~4개(해석 포함)"],"kr_us_note":"이 시장 국면 해석 1~2문장",'
        '"watch_today":["향후 체크포인트 2~4개"],'
        '"summary_md":"- [수치/사실] → [의미] 형태 불릿 3~5줄(국면해석·리스크/기회·섹터 시사점 포함)"}'
    )


def _build_market_news_digest_prompt(grouped_news: dict[str, list[dict]]) -> str:
    def _section(name: str, items: list[dict]) -> str:
        lines = []
        for item in items[:10]:
            pub = item.get("published_at")
            d = pub.strftime("%Y-%m-%d") if hasattr(pub, "strftime") else "날짜미상"
            lines.append(f"- {d} | {item.get('source')} | {(item.get('title') or '')[:140]}")
        return f"[{name}]\n" + ("\n".join(lines) if lines else "- 관련 기사 없음")

    sections = "\n\n".join([
        _section("KR", grouped_news.get("KR", [])),
        _section("US", grouped_news.get("US", [])),
        _section("GLOBAL", grouped_news.get("GLOBAL", [])),
    ])
    return (
        "너는 글로벌 시장 뉴스 데스크 편집장이다. 아래 시장 뉴스 원문 묶음을 읽고 "
        "한국 시장, 미국 시장, 글로벌 거시를 각각 2~4문장으로 요약하라.\n"
        "- 수치/사실과 의미를 함께 써라.\n"
        "- 주문·종목 매수/매도 지시는 금지한다.\n"
        "- 과도한 강조 표시(*, **)는 쓰지 마라. 꼭 필요한 강조가 아니면 평문으로 써라.\n"
        "- 같은 사건이 여러 기사에 반복되면 한 번만 압축하라.\n\n"
        "아래 JSON으로만 답하라:\n"
        '{"kr_summary":"한국 시장 요약","us_summary":"미국 시장 요약","global_summary":"글로벌 거시 요약"}\n\n'
        f"{sections}"
    )


# ──────────────────────────────────────────────────────────────
# PR-2: 종목별 중요 뉴스 큐레이션 (2단계, 모델 분리)
#   STEP A 선별/스코어링 = Flash-Lite(저렴), STEP B 인사이트 = 2.5 Flash(상위)
#   비용 가드: 입력 뉴스 건수 캡 + STEP B는 임계값 통과분만.
# ──────────────────────────────────────────────────────────────

from pydantic import BaseModel, Field  # noqa: E402

CURATION_THRESHOLD: int = 60          # impact_score 임계값(이상만 인사이트 대상)
CURATION_MAX_NEWS: int = 12           # STEP A 입력 뉴스 캡(비용 가드)
CURATION_TOP_K: int = 6               # 종목당 큐레이션 최대 보존 건수
_CATEGORIES = ("실적", "가이던스", "M&A·계약", "규제·정책", "애널리스트변경", "제품·기술", "거시", "기타")
_DIRECTIONS = ("호재", "악재", "중립")


class CurationScoreItem(BaseModel):
    idx: int
    impact_score: int = Field(ge=0, le=100)
    category: str
    direction: str


class CurationScoreOutput(BaseModel):
    items: list[CurationScoreItem] = Field(default_factory=list)


class CuratedInsightItem(BaseModel):
    idx: int
    insight: str


class CurationInsightOutput(BaseModel):
    insights: list[CuratedInsightItem] = Field(default_factory=list)


def _build_curation_score_prompt(company_name: str, ticker: str, news_items: list[dict]) -> str:
    """STEP A: 종목 뉴스에 impact_score·category·direction 부여(저렴 모델)."""
    lines = []
    for i, it in enumerate(news_items):
        pub = it.get("published_at")
        d = pub.strftime("%Y-%m-%d") if pub else "날짜미상"
        title = (it.get("title") or "")[:120]
        body = (it.get("body") or "")[:120]
        lines.append(f"[{i}] {d} | {title} — {body}")
    news_text = "\n".join(lines)
    return (
        f"너는 [{company_name}({ticker})] 담당 애널리스트의 뉴스 선별 보조다. "
        "아래 뉴스 각각이 이 종목 주가·심리에 줄 '영향도'를 평가하라.\n\n"
        "★ 중요도 기준(반드시 적용):\n"
        "- 고영향(70~100): 실적 발표, 가이던스 변경, M&A·대형 계약·수주, 규제·정책·소송, "
        "애널리스트 투자의견/목표가 변경.\n"
        "- 중영향(40~69): 제품·기술 발표, 파트너십, 거시(금리·환율) 직접 연관.\n"
        "- 저영향(0~39): 단순 시황 반복, 홍보·보도자료, 중복·일반론, 주가 등락 단순 보도.\n\n"
        "- 부정·리스크 뉴스도 중요하게 평가하라. 악재·우려·하락 관련 기사라도 실제 하방 리스크가 크면 높은 점수를 부여하라.\n"
        "각 뉴스에 impact_score(0~100), category, direction(호재|악재|중립)을 매겨라.\n"
        f"category는 다음 중 하나: {'|'.join(_CATEGORIES)}\n\n"
        "JSON으로만 답하라(설명·코드펜스 금지):\n"
        '{"items":[{"idx":0,"impact_score":0-100,"category":"...","direction":"호재|악재|중립"}]}\n\n'
        f"[뉴스 목록]\n{news_text}"
    )


def _build_curation_insight_prompt(company_name: str, ticker: str, passing: list[dict]) -> str:
    """STEP B: 임계값 통과 뉴스에 '핵심 사실 + 왜 중요한가' 한 줄 인사이트(상위 모델)."""
    lines = []
    for it in passing:
        pub = it.get("published_at")
        d = pub.strftime("%Y-%m-%d") if pub else "날짜미상"
        lines.append(f"[{it['idx']}] ({it['category']}/{it['direction']}) {d} | {(it.get('title') or '')[:140]} — {(it.get('body') or '')[:160]}")
    news_text = "\n".join(lines)
    return (
        f"너는 월스트리트 수석 애널리스트다. 아래 [{company_name}({ticker})]의 '중요 뉴스'만 골라낸 목록에 대해, "
        "각 뉴스의 '핵심 사실 + 그것이 이 종목에 주는 의미(왜 중요한가)'를 한 줄 인사이트로 작성하라.\n"
        "- 사실과 해석을 한 문장으로(예: '실적 가이던스 상향 → 컨센서스 상회로 단기 모멘텀 강화로 해석').\n"
        "- 표시 신호를 새로 만들거나 목표가를 생성하지 말고 관찰·해석만 작성하라.\n\n"
        "JSON으로만: {\"insights\":[{\"idx\":0,\"insight\":\"한 줄 인사이트\"}]}\n\n"
        f"[중요 뉴스]\n{news_text}"
    )


def _parse_curation_scores(text: str) -> CurationScoreOutput:
    return CurationScoreOutput.model_validate(json.loads(text))


def _parse_curation_insights(text: str) -> CurationInsightOutput:
    return CurationInsightOutput.model_validate(json.loads(text))


def curate_ticker_news(client, ticker: str, company_name: str, news_items: list[dict]) -> list[dict]:
    """종목 중요 뉴스 큐레이션(STEP A 스코어링 → 임계값 필터 → STEP B 인사이트).
    실패/빈 결과는 [] 반환(빈 큐레이션도 정상). 비용 가드: 입력 캡 + 통과분만 인사이트."""
    items = news_items[:CURATION_MAX_NEWS]
    if not items:
        return []

    # STEP A: 스코어링 (Flash-Lite)
    scores: dict[int, CurationScoreItem] = {}
    for attempt in range(2):
        try:
            text = _call_gemini_with_backoff(client, _get_bulk_model(), _build_curation_score_prompt(company_name, ticker, items))
            out = _parse_curation_scores(text)
            scores = {s.idx: s for s in out.items if 0 <= s.idx < len(items)}
            break
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s: 큐레이션 STEP A 실패(%d): %s", ticker, attempt, str(exc)[:80])
            if attempt == 0:
                time.sleep(API_SLEEP)
    if not scores:
        return []

    # 임계값 통과분
    passing = []
    for idx, sc in scores.items():
        if sc.impact_score >= CURATION_THRESHOLD:
            it = items[idx]
            passing.append({"idx": idx, "title": it.get("title"), "body": it.get("body"),
                            "url": it.get("url"), "source": it.get("source"),
                            "published_at": it.get("published_at"),
                            "category": sc.category, "direction": sc.direction,
                            "impact_score": sc.impact_score})
    if not passing:
        return []  # 주목할 만한 중요 뉴스 없음(정상)
    passing.sort(key=lambda x: -x["impact_score"])
    passing = passing[:CURATION_TOP_K]

    # STEP B: 인사이트 (2.5 Flash) — 통과분만
    insight_map: dict[int, str] = {}
    try:
        text = _call_gemini_with_backoff(client, _get_synth_model(), _build_curation_insight_prompt(company_name, ticker, passing))
        ins = _parse_curation_insights(text)
        insight_map = {i.idx: i.insight for i in ins.insights}
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s: 큐레이션 STEP B 실패(인사이트 생략): %s", ticker, str(exc)[:80])

    curated = []
    for p in passing:
        pub = p.get("published_at")
        curated.append({
            "title": (p.get("title") or "")[:160],
            "url": p.get("url") or "",
            "source": p.get("source") or "",
            "published_at": pub.strftime("%Y-%m-%d %H:%M") if hasattr(pub, "strftime") else (str(pub)[:16] if pub else ""),
            "category": p["category"], "direction": p["direction"],
            "impact_score": p["impact_score"],
            "insight": insight_map.get(p["idx"], ""),
        })
    logger.info("%s: 큐레이션 %d건(통과 %d/%d)", ticker, len(curated), len(passing), len(items))
    return curated


# ──────────────────────────────────────────────────────────────
# DB 조회 헬퍼 (enrich_gemini 전용 쿼리)
# ──────────────────────────────────────────────────────────────

def _tickers_needing_enrichment(
    conn: psycopg.Connection,
    asof: date,
) -> list[str]:
    """오늘 fetched_at 기준 새 뉴스가 있고, 아직 '성공' news_analysis가 없는 ticker 목록.
    PR-4: watchlist 종목만(=_MARKET_* pseudo-ticker 제외).
    PR-1(진단): 오늘 행이 '폴백'(생성 실패)이면 재시도 대상에 포함 — 낡은 '분석 실패'가 굳지 않게."""
    markers = "(" + " OR ".join(["na.summary_md LIKE %s"] * len(FALLBACK_MARKERS)) + ")"
    sql = f"""
        SELECT DISTINCT nr.ticker
        FROM news_raw nr
        WHERE nr.fetched_at::date = %s
        AND nr.ticker IN (SELECT ticker FROM watchlist)
        AND NOT EXISTS (
            SELECT 1 FROM news_analysis na
            WHERE na.ticker = nr.ticker AND na.asof = %s
            AND na.based_on <> 'fallback_old'
            AND NOT {markers}
        )
        ORDER BY nr.ticker
    """
    params = [asof, asof] + [f"%{m}%" for m in FALLBACK_MARKERS]
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [row["ticker"] for row in cur.fetchall()]


def _get_ticker_news(
    conn: psycopg.Connection,
    ticker: str,
    asof: date,
) -> list[dict]:
    """ticker의 오늘 뉴스 최대 MAX_NEWS_PER_TICKER건 (최신순)."""
    sql = """
        SELECT title, body, published_at, source, url
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


def _get_market_news(
    conn: psycopg.Connection,
    pseudo_ticker: str,
    limit: int = 12,
) -> list[dict]:
    """PR-4: _MARKET_KR/_MARKET_US 시장 뉴스 최근 limit건 (최신순)."""
    sql = """
        SELECT title, body, published_at
        FROM news_raw
        WHERE ticker = %s
        ORDER BY published_at DESC NULLS LAST, fetched_at DESC
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (pseudo_ticker, limit))
        return [dict(row) for row in cur.fetchall()]


def _get_market_news_digest_rows(conn: psycopg.Connection, limit: int = 12) -> dict[str, list[dict]]:
    sql = """
        SELECT source, title, published_at
        FROM market_news
        ORDER BY published_at DESC NULLS LAST, created_at DESC
        LIMIT %s
    """
    grouped = {"KR": [], "US": [], "GLOBAL": []}
    with conn.cursor() as cur:
        cur.execute(sql, (limit * 3,))
        for row in cur.fetchall():
            source = row["source"] or ""
            bucket = "GLOBAL"
            if source.endswith("_kr"):
                bucket = "KR"
            elif source.endswith("_us"):
                bucket = "US"
            grouped[bucket].append(dict(row))
    return {k: v[:limit] for k, v in grouped.items()}


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

            # PR-1(진단): 폴백이면 runs.errors에 사유 기록 — 종전엔 폴백이 조용히 묻혀
            # production 실패율(~60%)을 추적할 수 없었다.
            is_fallback = is_fallback_summary(output.summary_md, output.based_on)
            if is_fallback:
                errors.append({
                    "ticker": ticker,
                    "step": "enrich_news_fallback",
                    "error": "Gemini 요약 생성 실패 — 중립 폴백 저장(로그의 직전 오류 참조)",
                    "ts": datetime.utcnow().isoformat(),
                })

            # PR-2: 중요 뉴스 큐레이션(2단계). 요약이 폴백이면 스킵(LLM 불가 상태로 간주).
            curated: list[dict] = []
            if not is_fallback:
                try:
                    curated = curate_ticker_news(client, ticker, company_name, news_items)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("%s: 큐레이션 실패(비치명적): %s", ticker, str(exc)[:80])

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
                curated=curated,
            )
            upsert_news_analysis(conn, [analysis_row])
            replace_ticker_context(conn, TickerContextRow(
                ticker=ticker,
                context_type="news_summary",
                content=output.summary_md,
                source="gemini_news_analysis",
                valid_from=asof,
                valid_until=None,
            ))
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


def _tickers_with_stale_fallback(conn: psycopg.Connection) -> list[str]:
    """최신 news_analysis가 '폴백'(생성 실패)인 watchlist(active) 종목."""
    markers = "(" + " OR ".join(["summary_md LIKE %s"] * len(FALLBACK_MARKERS)) + ")"
    sql = f"""
        WITH latest AS (
            SELECT DISTINCT ON (ticker) ticker, summary_md, based_on
            FROM news_analysis ORDER BY ticker, asof DESC
        )
        SELECT l.ticker FROM latest l
        JOIN watchlist w USING (ticker)
        WHERE w.active = TRUE
        AND (l.based_on = 'fallback_old' OR {markers})
        ORDER BY l.ticker
    """
    with conn.cursor() as cur:
        cur.execute(sql, [f"%{m}%" for m in FALLBACK_MARKERS])
        return [r["ticker"] for r in cur.fetchall()]


def _get_recent_ticker_news(conn: psycopg.Connection, ticker: str) -> list[dict]:
    """ticker의 '가장 최근' 뉴스 최대 MAX_NEWS_PER_TICKER건 (날짜 무관)."""
    sql = """
        SELECT title, body, published_at, source
        FROM news_raw WHERE ticker = %s
        ORDER BY published_at DESC NULLS LAST, fetched_at DESC
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (ticker, MAX_NEWS_PER_TICKER))
        return [dict(row) for row in cur.fetchall()]


def reenrich_stale_fallbacks(
    conn: psycopg.Connection,
    asof: Optional[date] = None,
) -> tuple[int, list[dict]]:
    """PR-1(진단): 최신 분석이 '폴백'인 종목을, 보유한 '가장 최근 뉴스'로 다시 요약해
    오늘자(asof)에 실제 요약을 채운다. 파이프라인 미실행/증분 누락으로 굳은 '분석 실패'를 해소.

    Returns
    -------
    (fixed_count, errors)
    """
    asof = asof or date.today()
    client = _get_gemini_client()
    model = _get_bulk_model()
    errors: list[dict] = []
    fixed = 0

    tickers = _tickers_with_stale_fallback(conn)
    logger.info("폴백 재시도 대상: %d개 종목", len(tickers))

    for ticker in tickers:
        try:
            news_items = _get_recent_ticker_news(conn, ticker)
            if not news_items:
                logger.debug("%s: 재요약할 뉴스 없음 — 스킵", ticker)
                continue
            company_name = _get_company_name(conn, ticker)
            prompt = _build_news_prompt(ticker, company_name, news_items)
            output = _call_gemini_for_news(client, model, prompt, ticker)

            if is_fallback_summary(output.summary_md, output.based_on):
                errors.append({"ticker": ticker, "step": "reenrich_fallback",
                               "error": "재시도도 폴백", "ts": datetime.utcnow().isoformat()})
                continue  # 또 폴백이면 굳이 덮어쓰지 않음

            upsert_news_analysis(conn, [NewsAnalysisRow(
                ticker=ticker, asof=asof,
                sentiment=output.sentiment, sentiment_score=output.sentiment_score,
                summary_md=output.summary_md, payload=output.model_dump(),
                n_articles=len(news_items), model=model, based_on=output.based_on,
            )])
            replace_ticker_context(conn, TickerContextRow(
                ticker=ticker,
                context_type="news_summary",
                content=output.summary_md,
                source="gemini_news_analysis",
                valid_from=asof,
                valid_until=None,
            ))
            fixed += 1
            logger.info("%s: 폴백→실제 요약 복구 (sentiment=%s)", ticker, output.sentiment)
        except Exception as exc:
            logger.error("%s: 폴백 재시도 실패: %s", ticker, exc, exc_info=True)
            errors.append({"ticker": ticker, "step": "reenrich_fallback",
                           "error": str(exc), "ts": datetime.utcnow().isoformat()})
        time.sleep(API_SLEEP)

    logger.info("폴백 재시도 완료: %d종목 복구", fixed)
    return fixed, errors


# ──────────────────────────────────────────────────────────────
# 공개 API 2: 시황 종합 (하루 1회)
# ──────────────────────────────────────────────────────────────

def enrich_market_summary(
    conn: psycopg.Connection,
    asof: Optional[date] = None,
) -> bool:
    """
    PR-4: 한국·미국 시장을 각각 별도 Gemini 호출로 종합 → summary_kr_md / summary_us_md.
    입력을 시장별로 분리(KR: KOSPI/KOSDAQ/KRW + _MARKET_KR 뉴스, US: SP500/NASDAQ/VIX/10Y + _MARKET_US 뉴스)
    해 서로 다른 근거를 강제한다. summary 컬럼만 UPDATE → payload.changes(전일대비 등락) 보존.

    Returns
    -------
    True: 1개 이상 시장 저장 성공 | False: 스킵(데이터 없음) 또는 전부 실패
    """
    asof = asof or date.today()

    market_row = _get_market_daily_row(conn, asof)
    if not market_row:
        logger.warning("market_daily %s 없음 — 시황 종합 스킵", asof)
        return False

    changes = (market_row.get("payload") or {}).get("changes", {}) if isinstance(market_row.get("payload"), dict) else {}

    client = _get_gemini_client()
    model = _get_synth_model()

    from src.ingest_news import MARKET_KR_TICKER, MARKET_US_TICKER

    # KR 입력
    kr_metrics = {
        "asof": str(asof),
        "KOSPI": market_row.get("kospi"), "KOSPI_chg%": changes.get("kospi"),
        "KOSDAQ": market_row.get("kosdaq"), "KOSDAQ_chg%": changes.get("kosdaq"),
        "USDKRW": market_row.get("usdkrw"), "USDKRW_chg%": changes.get("usdkrw"),
    }
    kr_news = _get_market_news(conn, MARKET_KR_TICKER)

    # US 입력
    us_metrics = {
        "asof": str(asof),
        "SP500": market_row.get("sp500"), "SP500_chg%": changes.get("sp500"),
        "NASDAQ": market_row.get("nasdaq"), "NASDAQ_chg%": changes.get("nasdaq"),
        "VIX": market_row.get("vix"), "VIX_chg%": changes.get("vix"),
        "UST10Y": market_row.get("ust10y"),
    }
    us_news = _get_market_news(conn, MARKET_US_TICKER)

    kr_out = _call_gemini_for_market(client, model, _build_region_market_prompt("한국", kr_metrics, kr_news))
    time.sleep(API_SLEEP)
    us_out = _call_gemini_for_market(client, model, _build_region_market_prompt("미국", us_metrics, us_news))

    summary_kr = kr_out.summary_md if kr_out else None
    summary_us = us_out.summary_md if us_out else None

    if summary_kr is None and summary_us is None:
        logger.error("시황 종합 실패(KR·US 모두) — 업데이트 스킵")
        return False

    # summary 컬럼만 UPDATE → payload(전일대비 등락) 보존
    combined = "\n".join(filter(None, [
        f"[한국]\n{summary_kr}" if summary_kr else None,
        f"[미국]\n{summary_us}" if summary_us else None,
    ]))
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE market_daily
            SET summary_kr_md = COALESCE(%s, summary_kr_md),
                summary_us_md = COALESCE(%s, summary_us_md),
                summary_md    = COALESCE(%s, summary_md)
            WHERE asof = %s
            """,
            (summary_kr, summary_us, combined or None, asof),
        )
    logger.info(
        "시황 종합 저장 완료 (KR=%s US=%s)",
        "✓" if summary_kr else "✗", "✓" if summary_us else "✗",
    )
    return True


def summarize_market_news_digest(
    conn: psycopg.Connection,
    asof: Optional[date] = None,
) -> bool:
    asof = asof or date.today()
    grouped_news = _get_market_news_digest_rows(conn)
    if not any(grouped_news.values()):
        logger.warning("market_news 없음 — 시장 뉴스 요약 스킵")
        return False

    client = _get_gemini_client()
    model = _get_synth_model()
    try:
        prompt = _build_market_news_digest_prompt(grouped_news)
        text = _call_gemini_with_backoff(client, model, prompt)
        output = _parse_market_news_digest_output(text)
    except Exception as exc:
        logger.error("시장 뉴스 요약 실패: %s", exc, exc_info=True)
        return False

    row = MarketNewsSummaryRow(
        summary_date=asof,
        kr_summary=output.kr_summary,
        us_summary=output.us_summary,
        global_summary=output.global_summary,
    )
    upsert_market_news_summary(conn, row)
    logger.info("시장 뉴스 요약 저장 완료 (%s)", asof)
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

            # PR-1(진단): 최신 분석이 폴백인 종목을 최근 뉴스로 복구(굳은 '분석 실패' 해소)
            fixed_cnt, fix_errs = reenrich_stale_fallbacks(conn)
            all_errors.extend(fix_errs)
            logger.info("폴백 복구: %d종목", fixed_cnt)

            market_ok = enrich_market_summary(conn)
            logger.info("시황 종합: %s", "완료" if market_ok else "스킵/실패")

            digest_ok = summarize_market_news_digest(conn)
            logger.info("시장 뉴스 요약: %s", "완료" if digest_ok else "스킵/실패")

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
