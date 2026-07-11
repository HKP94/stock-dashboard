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
import random
import signal
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
    upsert_analyst_views,
    upsert_market_daily,
    upsert_macro_summary,
    upsert_market_news_summary,
    upsert_news_analysis,
)
from src.schemas import (
    AnalystViewRow,
    AnalystViewsOutput,
    MarketDailyRow,
    MarketManualOutput,
    MarketNewsDigestOutput,
    MarketNewsSummaryRow,
    MarketSummaryOutput,
    MacroSummaryOutput,
    MacroSummaryRow,
    ManualResearchOutput,
    NewsAnalysisRow,
    NewsSummaryOutput,
    StockActionAdviceNarrativeOutput,
    TickerContextRow,
)

logger = logging.getLogger(__name__)

# ── 상수 ─────────────────────────────────────────────────────────
GEMINI_BULK_MODEL_DEFAULT: str = "gemini-2.5-flash-lite"
# 시황 종합(1회/일)·상위 티어. 2.5-flash 계열로 통일(실호출 검증 2026-06-17). 무효 모델명이면 전량 실패.
GEMINI_SYNTH_MODEL_DEFAULT: str = "gemini-2.5-flash"
GEMINI_MANUAL_RESEARCH_MODEL_DEFAULT: str = os.environ.get("GEMINI_MANUAL_RESEARCH_MODEL", "gemini-2.5-pro")
# 액션제언(매일 ~38종목) 모델. 비용 안정화 기간엔 flash 계열만(무료티어 자격). pro 복귀는
# 파이프라인 안정 확인 후 PM 승인 하에 ACTION_ADVICE_MODEL=gemini-2.5-pro 한 값으로. (CLAUDE.md §5)
ACTION_ADVICE_MODEL_DEFAULT: str = "gemini-2.5-flash"
MAX_NEWS_PER_TICKER: int = 15
BODY_CAP: int = 200        # 뉴스 본문 최대 글자 (토큰 절약)
API_SLEEP: float = 1.5     # API 호출 간 sleep (레이트리밋 방지)
GEMINI_HTTP_TIMEOUT_MS: int = int(os.environ.get("GEMINI_HTTP_TIMEOUT_MS", "45000"))
GEMINI_BATCH_BUDGET_SECONDS: float = float(os.environ.get("GEMINI_BATCH_BUDGET_SECONDS", "1800"))
# 액션제언 하드 백스톱(대기가 아닌 상한). http 타임아웃(45s) 위. flash(현재 기본, <10s)엔
# 트립되지 않고, pro 복귀 시 p95 17~20s도 커버. 20s는 정상 pro를 false timeout으로 트립시켜
# 재시도 이중과금을 유발했다(run #157). pro 복귀 대비 값 유지.
ACTION_ADVICE_LLM_TIMEOUT_SECONDS: int = int(os.environ.get("ACTION_ADVICE_LLM_TIMEOUT_SECONDS", "60"))

# PR-1(진단): 네트워크/일시오류(429·503·타임아웃) 지수 백오프 재시도. 파싱/스키마 실패와 구분.
TRANSIENT_RETRIES: int = 3        # _call_gemini 일시오류 재시도 횟수 (CLAUDE.md §3)
TRANSIENT_BACKOFF_BASE: float = 2.0   # 백오프 기준(초): 2, 4, 8 ...
# 지터: 동시 재시도 폭발(thundering herd) 방지. 실제 대기 = base*2^n + U(0, jitter).
TRANSIENT_BACKOFF_JITTER: float = float(os.environ.get("GEMINI_BACKOFF_JITTER", "1.0"))
# 서킷브레이커: _call_gemini_with_backoff 단위 '연속' 일시오류가 임계 이상이면 이후 호출은
# API를 때리지 않고 즉시 실패시켜 쿼터·시간 낭비를 차단(우아한 degrade). 성공 1회로 리셋,
# 쿨다운 경과 시 half-open(프로브 1회 허용). 파이프라인은 단명 프로세스라 다음 실행은 0에서 시작.
CIRCUIT_BREAKER_THRESHOLD: int = int(os.environ.get("GEMINI_CIRCUIT_BREAKER_THRESHOLD", "5"))
CIRCUIT_BREAKER_COOLDOWN_SECONDS: float = float(os.environ.get("GEMINI_CIRCUIT_BREAKER_COOLDOWN", "300"))
_consecutive_transient_failures: int = 0
_circuit_tripped_at: float = 0.0
# 빌링(선불 크레딧) 소진은 그 실행 내에서 회복 불가 → 첫 발생 시 halt로 이후 종목 API 스킵(시간·호출 보존).
# 재시도해도 무의미(429지만 transient 아님). last_error는 runs.errors 영속화용(진단 가시성).
_billing_halt: bool = False
_last_call_error: Optional[str] = None
# 빌링/크레딧 소진 식별 마커 — 무료티어 레이트리밋(RPM/RPD)과 반드시 구분해야 한다.
# 둘 다 429 RESOURCE_EXHAUSTED지만 빌링은 그 실행 내 재시도로 회복 불가(halt),
# 레이트리밋은 백오프·다음 주기로 회복 가능(transient). 그래서 마커는 '크레딧 소진' 문구만
# 엄격히(과거 'billing'/'balance'/'insufficient'는 레이트리밋 안내문 "…manage your billing"을
# 오분류해 무료티어를 통째 halt시킬 위험 → 제거). 크레딧 소진 메시지: "prepayment credits are depleted".
_BILLING_MARKERS: tuple[str, ...] = ("credits are depleted", "prepayment credit", "credit balance",
                                     "out of credit", "purchase more credit")
# 무료티어 RPM 스로틀 + RPD 예산 — 무료 한도(모델별 RPM/RPD) 내로 유지. 정확 한도는 AI Studio
# 대시보드에서만 확인 가능(공식 문서 비공개) → env로 조정. 429(레이트리밋)는 transient라 초과해도
# 백오프가 흡수하지만, 스로틀·예산이 애초에 초과를 줄여 실패·낭비를 최소화한다.
GEMINI_MIN_INTERVAL_SECONDS: float = float(os.environ.get("GEMINI_MIN_INTERVAL_SECONDS", "0"))
GEMINI_MAX_CALLS_PER_RUN: int = int(os.environ.get("GEMINI_MAX_CALLS_PER_RUN", "0"))  # 0=무제한
_last_api_call_ts: float = 0.0
_api_calls_this_run: int = 0

# 무료티어 키 풀 로테이션(요약복구): 여러 무료 키를 풀로 돌려, 한 키가 RPD/레이트리밋 또는
# 빌링으로 소진되면 다음 키로 넘겨 요약을 이어간다. 계산 로직 불변 — LLM 백엔드(키) 교체일 뿐.
# 소스: GEMINI_API_KEYS(쉼표 다중) 우선 → GEMINI_API_KEY(단일 하위호환). 진입점 7곳 무변경.
_key_pool: list[str] = []             # 로드된 키(순서 보존, lazy)
_active_key_idx: int = 0              # 현재 활성 키 인덱스
_exhausted_keys: set[int] = set()     # 소진(레이트리밋 지속/빌링) 키 인덱스 — 실행당 누적, run 시작에 리셋
_clients_by_idx: dict[int, object] = {}  # 키별 client lazy 캐시
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

def _load_api_keys() -> list[str]:
    """GEMINI_API_KEYS(쉼표 다중) 우선 → GEMINI_API_KEY(단일 하위호환).
    공백 trim·빈값/중복 제거·순서 보존. 키 값은 로그·에러에 노출 금지(_mask_key로만)."""
    _ensure_env()  # PR-1: .env 로드(로컬)
    raw = os.environ.get("GEMINI_API_KEYS") or os.environ.get("GEMINI_API_KEY") or ""
    keys: list[str] = []
    for part in raw.split(","):
        k = part.strip()
        if k and k not in keys:
            keys.append(k)
    return keys


def _ensure_pool() -> None:
    """키 풀 lazy 로드(비어 있으면 env에서). run 시작(reset_run_budget)에 명시 리로드."""
    global _key_pool
    if not _key_pool:
        _key_pool = _load_api_keys()


def _mask_key(key: str) -> str:
    """진단 로그용 마스킹 — 끝 4자리만."""
    return f"...{key[-4:]}" if len(key) >= 4 else "****"


def _active_key() -> str:
    _ensure_pool()
    if not _key_pool:
        raise RuntimeError("GEMINI_API_KEYS/GEMINI_API_KEY 환경변수가 설정되지 않았습니다.")
    return _key_pool[_active_key_idx]


def _advance_key() -> bool:
    """활성 키를 다음 미소진 키로 이동. 성공 True, 남은 키 없으면(전키 소진) False."""
    global _active_key_idx
    _ensure_pool()
    n = len(_key_pool)
    for step in range(1, n + 1):
        cand = (_active_key_idx + step) % n
        if cand not in _exhausted_keys:
            _active_key_idx = cand
            return True
    return False


def _client_for_idx(idx: int):
    """키 인덱스별 google-genai client(lazy 캐시)."""
    from google import genai  # 지연 임포트 (테스트 환경 미설치 대응)
    from google.genai import types
    client = _clients_by_idx.get(idx)
    if client is None:
        client = genai.Client(
            api_key=_key_pool[idx],
            http_options=types.HttpOptions(timeout=GEMINI_HTTP_TIMEOUT_MS),
        )
        _clients_by_idx[idx] = client
    return client


def _get_api_key() -> str:
    """하위호환: 현재 활성 키 반환."""
    return _active_key()


def _get_bulk_model() -> str:
    return os.environ.get("GEMINI_BULK_MODEL", GEMINI_BULK_MODEL_DEFAULT)


def _get_synth_model() -> str:
    return os.environ.get("GEMINI_SYNTH_MODEL", GEMINI_SYNTH_MODEL_DEFAULT)


def _get_manual_research_model() -> str:
    return os.environ.get("GEMINI_MANUAL_RESEARCH_MODEL", GEMINI_MANUAL_RESEARCH_MODEL_DEFAULT)


def _get_action_advice_model() -> str:
    """액션제언 전용 모델. 기본 flash(비용 안정화). pro 복귀는 ACTION_ADVICE_MODEL 값 하나로."""
    return os.environ.get("ACTION_ADVICE_MODEL", ACTION_ADVICE_MODEL_DEFAULT)


def _get_gemini_client():
    """현재 활성 키의 google-genai client(키별 lazy 캐시). 키는 풀(env)에서만."""
    _active_key()  # 풀 보장 + 미설정 검증
    return _client_for_idx(_active_key_idx)


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


def _is_billing_depleted(exc: Exception) -> bool:
    """선불 크레딧 소진/빌링 오류인지 — 429지만 그 실행 내 재시도로 회복 불가(하드 실패)."""
    msg = str(exc).lower()
    return any(m in msg for m in _BILLING_MARKERS)


def _is_transient(exc: Exception) -> bool:
    """일시적(재시도 가치 있는) 오류인지 — 429/503/타임아웃/쿼터 등. 단, 빌링 소진은 제외(하드 실패)."""
    if _is_billing_depleted(exc):
        return False
    msg = str(exc).lower()
    return any(m in msg for m in _TRANSIENT_MARKERS)


def get_last_call_error() -> Optional[str]:
    """마지막 Gemini 호출 실패 메시지(runs.errors 영속화·진단 가시성용)."""
    return _last_call_error


def reset_circuit_breaker() -> None:
    """서킷 상태 초기화. 새 배치 시작·테스트에서 명시 호출. 성공 시에도 호출되므로
    per-run 호출 카운터(RPD 예산)는 여기서 리셋하지 않는다(reset_run_budget으로 분리)."""
    global _consecutive_transient_failures, _circuit_tripped_at, _billing_halt, _last_call_error
    _consecutive_transient_failures = 0
    _circuit_tripped_at = 0.0
    _billing_halt = False
    _last_call_error = None


def reset_run_budget() -> None:
    """per-run 호출 카운터·스로틀 타임스탬프 초기화 + 키 풀 리로드/소진 리셋.
    새 파이프라인 실행 시작 시 호출. 풀 소진 플래그를 여기서 리셋하는 이유:
    reset_circuit_breaker는 '성공 1회'마다도 호출되므로(백오프 성공 경로) 거기서 소진을
    리셋하면 이미 RPD 소진된 키가 매 성공마다 되살아나 핑퐁이 된다 → 풀 리셋은 run 시작 전용."""
    global _api_calls_this_run, _last_api_call_ts, _key_pool, _active_key_idx
    _api_calls_this_run = 0
    _last_api_call_ts = 0.0
    _key_pool = _load_api_keys()   # env 재반영(새 키 추가/교체 픽업)
    _active_key_idx = 0
    _exhausted_keys.clear()
    _clients_by_idx.clear()


def _run_budget_exhausted() -> bool:
    """이번 실행의 Gemini 호출 수가 RPD 예산을 넘었는지. 0이면 무제한.
    RPD(무료티어)는 키(프로젝트)별 한도이므로 키 N개면 실질 한도도 N배다 → 예산을
    키 수만큼 스케일해 풀 전체 처리량을 활용한다(소진은 429 로테이션이 실시간 처리하고,
    이 예산은 429 전에 미리 멈추는 소프트 캡일 뿐)."""
    limit = GEMINI_MAX_CALLS_PER_RUN * max(1, len(_key_pool))
    return GEMINI_MAX_CALLS_PER_RUN > 0 and _api_calls_this_run >= limit


def _throttle() -> None:
    """RPM 스로틀 — 직전 실제 API 호출과 최소 간격(GEMINI_MIN_INTERVAL_SECONDS) 유지.
    무료티어 RPM 초과(429)를 애초에 줄인다(0이면 비활성)."""
    global _last_api_call_ts
    if GEMINI_MIN_INTERVAL_SECONDS <= 0:
        return
    elapsed = time.monotonic() - _last_api_call_ts
    wait = GEMINI_MIN_INTERVAL_SECONDS - elapsed
    if _last_api_call_ts > 0 and wait > 0:
        time.sleep(wait)


def _circuit_open() -> bool:
    """연속 일시오류가 임계 이상이고 쿨다운이 안 지났으면 True(호출 차단)."""
    if _consecutive_transient_failures < CIRCUIT_BREAKER_THRESHOLD:
        return False
    # 쿨다운 경과 → half-open: 프로브 1회 통과시킴
    return (time.monotonic() - _circuit_tripped_at) < CIRCUIT_BREAKER_COOLDOWN_SECONDS


def _record_transient_failure() -> None:
    global _consecutive_transient_failures, _circuit_tripped_at
    _consecutive_transient_failures += 1
    if _consecutive_transient_failures >= CIRCUIT_BREAKER_THRESHOLD:
        _circuit_tripped_at = time.monotonic()


def _call_gemini_with_backoff(client, model: str, prompt: str) -> str:
    """PR-1(진단): _call_gemini를 지수 백오프+지터+서킷브레이커로 감싼다.
    429/503/타임아웃 등 '일시오류'만 재시도(최대 TRANSIENT_RETRIES). 그 외(잘못된 요청 등)는 즉시 전파.
    이게 종목별 폴백 사고(production ~60%)를 줄이는 핵심 — 단건 일시오류를 흡수.
    파싱/스키마 실패는 여기서 다루지 않는다(상위 _call_gemini_for_*가 별도 재시도).
    서킷 오픈 시 API를 때리지 않고 즉시 예외 → 상위가 폴백으로 우아하게 degrade(쿼터·시간 보존).
    키 풀(GEMINI_API_KEYS)이 다중이면, 활성 키가 RPD/레이트리밋 지속 or 빌링으로 소진될 때
    그 키를 소진 마킹하고 다음 미소진 키로 advance(client 스왑)해 그 호출을 새 키로 재시도한다.
    모든 키가 소진됐을 때만 기존 halt(빌링)/서킷(레이트리밋) degrade로 떨어진다."""
    global _billing_halt, _last_call_error, _last_api_call_ts, _api_calls_this_run
    # 빌링 소진(전키)은 그 실행 내 회복 불가 → 첫 발생 후 이후 종목은 API를 아예 스킵(시간·호출 보존).
    if _billing_halt:
        raise RuntimeError(f"Gemini billing halt — 크레딧 소진으로 호출 스킵({_last_call_error or 'billing depleted'})")
    if _circuit_open():
        raise RuntimeError(
            f"Gemini 서킷 오픈(연속 일시오류 {_consecutive_transient_failures}회) — API 호출 스킵(폴백 degrade)"
        )
    _ensure_pool()
    # 다중 키면 활성 키 client를 쓴다(진입점이 넘긴 client는 로테이션 후 스테일일 수 있음).
    # 단일/미설정 풀은 넘어온 client를 그대로(레거시·테스트 경로 불변 — client 강제 생성 안 함).
    active = _get_gemini_client() if len(_key_pool) >= 2 else client
    while True:  # 키 로테이션 루프 (전키 소진 시 탈출)
        last: Optional[Exception] = None
        for attempt in range(TRANSIENT_RETRIES):
            try:
                _throttle()                       # 무료티어 RPM 스로틀(직전 호출과 최소 간격)
                _last_api_call_ts = time.monotonic()
                _api_calls_this_run += 1          # RPD 예산 카운트(실제 API 호출만)
                result = _call_gemini(active, model, prompt)
                reset_circuit_breaker()  # 성공 → 연속 카운터·서킷·빌링 halt 리셋
                return result
            except Exception as exc:
                last = exc
                _last_call_error = str(exc)[:300]  # 진단 가시성(runs.errors 영속화)
                is_billing = _is_billing_depleted(exc)
                if is_billing:
                    break  # 빌링은 재시도 무의미 — 이 키 소진 처리로
                if not _is_transient(exc):
                    raise  # 비일시(파싱/요청오류)는 서킷·로테이션과 무관 — 즉시 전파, 카운터 불변
                if attempt == TRANSIENT_RETRIES - 1:
                    break  # 레이트리밋 재시도 소진 — 이 키 소진 처리로
                wait = TRANSIENT_BACKOFF_BASE * (2 ** attempt) + random.uniform(0, TRANSIENT_BACKOFF_JITTER)
                logger.warning("Gemini 일시오류(%s) — %.1fs 후 재시도 %d/%d",
                               str(exc)[:80], wait, attempt + 2, TRANSIENT_RETRIES)
                time.sleep(wait)
        # 현재 키 소진(빌링 or 레이트리밋 지속) → 다음 미소진 키로 로테이션 시도(다중 키일 때만).
        assert last is not None
        if len(_key_pool) >= 2:
            idx = _active_key_idx
            _exhausted_keys.add(idx)
            reason = "billing" if is_billing else "rate"
            # last_error에 어느 키가 왜 죽었는지 남긴다(키 값은 마스킹 — 끝 4자리만).
            _last_call_error = f"key {_mask_key(_key_pool[idx])} ({reason}) 소진: {str(last)[:200]}"
            if _advance_key():
                active = _get_gemini_client()
                logger.warning("Gemini 키 로테이션 → %s (이전 키 %s 소진)",
                               _mask_key(_active_key()), reason)
                continue  # 새 키로 이 호출 재시도
        # 전키 소진(또는 단일/미설정 키) → 기존 degrade
        if is_billing:
            _billing_halt = True  # 이후 종목 API 스킵
            logger.error("Gemini 빌링 소진(선불 크레딧, 전키) — 이후 호출 halt: %s", str(last)[:160])
        else:
            _record_transient_failure()  # 레이트리밋 재시도 소진 → 서킷 카운트
        raise last


def _within_budget(started_at: float, budget_seconds: float = GEMINI_BATCH_BUDGET_SECONDS) -> bool:
    return (time.monotonic() - started_at) < budget_seconds


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


def _parse_macro_summary_output(text: str) -> MacroSummaryOutput:
    data = json.loads(text)
    return MacroSummaryOutput.model_validate(data)


def _parse_analyst_views_output(text: str) -> AnalystViewsOutput:
    data = json.loads(text)
    for stance in ("bull", "bear"):
        items = data.get(stance) or []
        if not isinstance(items, list):
            data[stance] = []
            continue
        cleaned = []
        for item in items:
            if not isinstance(item, dict):
                continue
            point = str(item.get("point") or "").strip()
            source = str(item.get("source") or "").strip()
            source_url = str(item.get("source_url") or "").strip()
            if not (point and source and source_url):
                continue
            cleaned.append({
                "point": point,
                "source": source,
                "source_url": source_url,
            })
        data[stance] = cleaned
    return AnalystViewsOutput.model_validate(data)


def _parse_manual_research_output(text: str) -> ManualResearchOutput:
    data = json.loads(text)
    for key in ("bullPoints", "bearPoints"):
        items = data.get(key) or []
        if not isinstance(items, list):
            data[key] = []
            continue
        cleaned = []
        for item in items:
            if not isinstance(item, dict):
                continue
            point = str(item.get("point") or "").strip()
            if not point:
                continue
            cleaned.append({
                "point": point,
                "sourceLabel": str(item.get("sourceLabel") or "").strip() or None,
                "sourceUrl": str(item.get("sourceUrl") or "").strip() or None,
            })
        data[key] = cleaned
    return ManualResearchOutput.model_validate(data)


def _parse_market_manual_output(text: str) -> MarketManualOutput:
    data = json.loads(text)
    return MarketManualOutput.model_validate(data)


def _parse_stock_action_advice_output(text: str) -> StockActionAdviceNarrativeOutput:
    data = json.loads(text)
    return StockActionAdviceNarrativeOutput.model_validate(data)


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


def summarize_stock_action_advice(context: dict) -> StockActionAdviceNarrativeOutput | None:
    previous = None
    try:
        def _handle_timeout(_signum, _frame):
            raise TimeoutError("action advice llm hard timeout")

        previous = signal.getsignal(signal.SIGALRM)
        signal.signal(signal.SIGALRM, _handle_timeout)
        signal.alarm(ACTION_ADVICE_LLM_TIMEOUT_SECONDS)
        client = _get_gemini_client()
        text = _call_gemini_with_backoff(client, _get_action_advice_model(), _build_stock_action_advice_prompt(context))
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
        return _parse_stock_action_advice_output(text)
    except Exception as exc:
        try:
            signal.alarm(0)
            if previous is not None:
                signal.signal(signal.SIGALRM, previous)
        except Exception:
            pass
        logger.warning("%s action advice narrative fallback: %s", context.get("ticker", "unknown"), str(exc)[:120])
        return None


def _call_gemini_for_analyst_views(
    client,
    model: str,
    prompt: str,
    ticker: str,
) -> AnalystViewsOutput:
    for attempt in range(2):
        try:
            text = _call_gemini_with_backoff(client, model, prompt)
            return _parse_analyst_views_output(text)
        except Exception as exc:
            if attempt == 0:
                logger.warning("%s: 애널리스트 논거 파싱/호출 실패 (재시도): %s", ticker, exc)
                time.sleep(API_SLEEP)
            else:
                logger.error("%s: 애널리스트 논거 2회 실패 — 빈 결과 저장: %s", ticker, exc)
    return AnalystViewsOutput()


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
        "- catalysts의 impact는 방향이 뚜렷하지 않으면 억지로 긍정/부정으로 몰지 말고 '중립'을 써도 된다.\n"
        "- 코드가 제공하는 표시 신호를 새로 만들지 마라. 뉴스 사실과 심리 해석만 작성하라.\n"
        "- 과도한 강조 표시(*, **)는 쓰지 마라. 꼭 필요한 강조가 아니면 평문으로 써라.\n\n"
        "아래 JSON 스키마로만, 순수 JSON으로 답하라(코드펜스·설명 금지):\n"
        '{"sentiment":"긍정|중립|부정","sentiment_score":-1.0~1.0,'
        '"key_points":["[사실]→[의미] 형태 불릿3~6개"],'
        '"catalysts":[{"date":"YYYY-MM-DD","headline":"요약","impact":"긍정|중립|부정","importance":"상|중|하"}],'
        '"risks":["하방리스크0~4개"],'
        '"summary_md":"- 한 줄 결론(의미)\\n- [사실]→[의미] 불릿","confidence":"상|중|하","based_on":"recent|fallback_old"}\n\n'
        f"[분석할 뉴스 리스트]\n{news_text}"
    )


def _build_analyst_views_prompt(
    ticker: str,
    company_name: str,
    news_items: list[dict],
    context_items: list[dict],
) -> str:
    lines: list[str] = []
    for item in news_items[:12]:
        pub_dt = item.get("published_at")
        date_str = pub_dt.strftime("%Y-%m-%d") if pub_dt else "날짜미상"
        title = item.get("title", "")
        body = (item.get("body") or "")[:BODY_CAP]
        source = item.get("source") or "unknown"
        url = item.get("url") or ""
        lines.append(f"- {date_str} | {source} | {url}\n  제목: {title}\n  본문: {body}")

    context_text = "\n".join(
        f"- {item.get('valid_from')} | {item.get('source')} | {item.get('content')}"
        for item in context_items[:4]
    ) or "(보조 컨텍스트 없음)"
    news_text = "\n".join(lines) if lines else "(관련 뉴스 없음)"

    return (
        f"너는 증권사 코멘트만 근거로 강세/약세 논거를 구조화하는 리서치 어시스턴트다. "
        f"[{company_name}({ticker})] 관련 기사와 보조 컨텍스트를 읽고, 기사에 실제로 인용된 애널리스트/증권사 의견만 추출하라.\n\n"
        "규칙:\n"
        "- 기사나 보조 컨텍스트에 없는 주장 창작 금지.\n"
        "- 매수/매도 지시나 목표주가 창작 금지. 왜 강세/약세인지의 논거만 적는다.\n"
        "- 각 논거는 반드시 입력 기사 URL 하나에 연결돼야 한다.\n"
        "- 기사에 애널리스트/증권사 인용이 없으면 빈 배열을 반환한다.\n"
        "- bull=강세 논거, bear=약세 논거로 분리한다.\n\n"
        "- 같은 기사 안에도 강세 요인과 약세/우려 요인이 함께 있으면 각각 bull·bear로 분리하라.\n"
        "- 약세·리스크·우려·밸류에이션 부담·경쟁심화 등은 bear로 명확히 분류하라.\n"
        "- 수요 둔화·재고 부담·과열 경고처럼 하방 우려를 키우는 문장도 bear에 포함하라.\n"
        "- 균형을 맞추기 위해 가짜 bear를 만들지 마라. 실제 기사 근거가 없으면 비워 둔다.\n\n"
        "출력은 순수 JSON만 허용:\n"
        '{"bull":[{"point":"논거 1개","source":"매체명","source_url":"https://..."}],'
        '"bear":[{"point":"논거 1개","source":"매체명","source_url":"https://..."}]}\n\n'
        f"[기사]\n{news_text}\n\n"
        f"[보조 컨텍스트]\n{context_text}"
    )


def _build_manual_research_prompt(
    ticker: str,
    company_name: str,
    raw_text: str,
    source: str | None = None,
    source_url: str | None = None,
) -> str:
    source_line = f"- 사용자 메모 출처: {source}" if source else "- 사용자 메모 출처: 미입력"
    url_line = f"- 사용자 URL: {source_url}" if source_url else "- 사용자 URL: 미입력"
    return (
        f"너는 외부 리서치 자료를 구조화하는 시니어 애널리스트 어시스턴트다. "
        f"[{company_name}({ticker})] 관련 자유 텍스트를 읽고, 텍스트에 실제로 등장한 근거만 추출하라.\n\n"
        "핵심 규칙:\n"
        "- 원문에 없는 목표가·투자의견·논거를 만들지 마라.\n"
        "- 강세와 약세가 함께 있으면 bull/bear로 분리하라.\n"
        "- 단기(0~3개월), 중기(3~12개월), 장기(1년+)를 모두 채우되 숫자 점수는 금지하고 label+rationale만 출력하라.\n"
        "- 매수/매도 지시 문장 금지. 관찰형 설명만 허용.\n"
        "- sourceUrl이 원문에 없으면 null 허용.\n\n"
        "label은 정확히 다음 중 하나만 사용: 매력적, 다소 매력적, 중립, 다소 비매력적, 비매력적\n\n"
        "출력은 순수 JSON만 허용:\n"
        "{"
        "\"inferredSource\": \"추정 출처명 또는 null\","
        "\"consensus\": {\"targetPrice\": 0, \"ratingLabel\": \"매수|중립|매도\", \"ratingScore\": 1|0|-1} 또는 null,"
        "\"bullPoints\": [{\"point\": \"논거\", \"sourceLabel\": \"출처명\", \"sourceUrl\": \"https://... 또는 null\"}],"
        "\"bearPoints\": [{\"point\": \"논거\", \"sourceLabel\": \"출처명\", \"sourceUrl\": \"https://... 또는 null\"}],"
        "\"horizons\": ["
        "{\"horizon\": \"short\", \"attractivenessLabel\": \"다소 매력적\", \"rationale\": \"근거\"},"
        "{\"horizon\": \"mid\", \"attractivenessLabel\": \"중립\", \"rationale\": \"근거\"},"
        "{\"horizon\": \"long\", \"attractivenessLabel\": \"비매력적\", \"rationale\": \"근거\"}"
        "]"
        "}\n\n"
        f"{source_line}\n{url_line}\n\n"
        f"[원문]\n{raw_text}"
    )


def _build_market_manual_prompt(
    raw_text: str,
    source: str | None = None,
    source_url: str | None = None,
    asof: str | None = None,
) -> str:
    source_line = f"- 사용자 메모 출처: {source}" if source else "- 사용자 메모 출처: 미입력"
    url_line = f"- 사용자 URL: {source_url}" if source_url else "- 사용자 URL: 미입력"
    asof_line = f"- 기준일: {asof}" if asof else "- 기준일: 미입력"
    return (
        "너는 시장 코멘트를 양면 시나리오로 정리하는 매크로 전략 보조자다.\n"
        "아래 자유 텍스트를 읽고 강세 시나리오와 약세 시나리오를 각각 한 단락으로 정리하라.\n\n"
        "규칙:\n"
        "- 원문에 없는 낙관/비관 논거 창작 금지.\n"
        "- 매매 지시 금지.\n"
        "- 강세/약세를 모두 채우되, 원문 근거가 약하면 그렇게 명시하라.\n\n"
        "출력은 순수 JSON만 허용:\n"
        "{\"bullScenario\": \"...\", \"bearScenario\": \"...\"}\n\n"
        f"{source_line}\n{url_line}\n{asof_line}\n\n"
        f"[원문]\n{raw_text}"
    )


def _build_stock_action_advice_prompt(context: dict) -> str:
    return (
        "너는 종목 액션 제언의 해설을 담당하는 시니어 전략가다.\n"
        "중요 규칙:\n"
        "- 새로운 숫자나 가격대를 만들지 마라.\n"
        "- 비중 low/high, 현재 비중, 진입/이탈 구간 숫자는 입력으로 받은 값만 사용하라.\n"
        "- 입력에 없는 숫자를 추가하거나 수정하지 마라.\n"
        "- 재료가 갈리면 갈리는 그대로 설명하라.\n"
        "- 자동 주문/즉시 집행처럼 들리는 표현은 금지한다.\n"
        "- 입력의 hold_character(보유성격: 장기보유/모멘텀/단기)는 코드가 정한 값이다. 바꾸지 말고, "
        "왜 그 성격인지 rationale에서 hold_character_basis 근거로 설명만 하라.\n"
        "- 입력의 grade(매수/관망/축소)·grade_confidence·grade_basis는 코드가 3축 정렬 패턴으로 정한 값이다. "
        "새 등급·점수를 만들거나 바꾸지 말고, rationale에서 grade_basis.axes(퀀트·컨센서스·내 판단의 강/중/약)가 "
        "어떻게 정렬·충돌해서 그 등급이 됐는지 해설만 하라. '사라/팔아라' 매매 단정은 금지하되 등급은 그대로 인용하라.\n\n"
        "집중 리스크 관찰(concentrationNote) 규칙 — 입력 concentration_note가 있을 때만:\n"
        "- 어휘만 자연스럽게 다듬어라. 문장 구조·숫자를 새로 만들지 마라.\n"
        "- 사실+영향만 서술하라(관찰). 가치판단·지시 금지.\n"
        "- 금지어: 줄이/축소/매도/낮추/과도/과하/부담/적정/권장/권고/바람직/추천 등. "
        "'비중을 줄이세요/부담스럽다/적정 비중' 같은 표현 절대 금지.\n"
        "- 입력 concentration_note가 없으면 concentrationNote는 null.\n\n"
        "출력은 순수 JSON만 허용:\n"
        "{"
        "\"rationale\":\"왜 이런 방향·보유성격인지 설명\","
        "\"divergenceNote\":\"재료 충돌 설명 또는 null\","
        "\"supportingFactors\":[{\"source\":\"재료명\",\"value\":\"지지 이유\"}],"
        "\"opposingFactors\":[{\"source\":\"재료명\",\"value\":\"반대 이유\"}],"
        "\"concentrationNote\":\"집중 리스크 관찰을 어휘만 다듬은 문장 또는 null\""
        "}\n\n"
        f"[입력 컨텍스트]\n{json.dumps(context, ensure_ascii=False)}"
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
        "- MarketScore(점수·방향·신뢰도)는 코드가 계산한 값이다. 점수를 새로 만들거나 바꾸지 말고, 그 방향이 왜 그런지 지표로 설명만 하라. 매매 단정(사라/팔아라) 금지.\n"
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


def _build_macro_summary_prompt(snapshot: dict) -> str:
    snapshot_json = json.dumps(snapshot, ensure_ascii=False, default=str)
    return (
        "너는 글로벌 매크로 스트래티지스트다. 아래 최신 거시 지표와 직전 대비 변화를 읽고 "
        "현재 거시 환경을 양면으로 해석하라.\n"
        "- support_view: 위험자산에 우호적인 해석 1~2문장\n"
        "- oppose_view: 위험자산에 부담이 되는 해석 1~2문장\n"
        "- watch_points: 앞으로 확인할 거시 체크포인트 2~4개\n"
        "- 매수/매도 지시 금지, 관찰·해석까지만.\n"
        "- 금리·물가·고용·변동성·환율의 상충 신호를 과도하게 단정하지 마라.\n"
        "- 과도한 강조 표시(*, **)는 쓰지 마라. 꼭 필요한 강조가 아니면 평문으로 써라.\n\n"
        f"[거시 스냅샷]\n{snapshot_json}\n\n"
        "아래 JSON으로만 답하라:\n"
        '{"headline":"40자 내외 요약","support_view":"우호 해석","oppose_view":"부담 해석","watch_points":["체크포인트"],"summary_md":"- 핵심 요약 3~5줄"}'
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
    # 무료티어 예산 대비 우선순위: 보유(is_holding) → 활성 관심 → 나머지. 예산 초과로 중단돼도
    # 중요 종목(보유·관심)이 먼저 요약되고, 후순위는 다음 주기로 이월(RPD 가드와 함께).
    sql = f"""
        SELECT nr.ticker
        FROM (SELECT DISTINCT ticker FROM news_raw WHERE fetched_at::date = %s) nr
        JOIN watchlist w ON w.ticker = nr.ticker
        WHERE NOT EXISTS (
            SELECT 1 FROM news_analysis na
            WHERE na.ticker = nr.ticker AND na.asof = %s
            AND na.based_on <> 'fallback_old'
            AND NOT {markers}
        )
        ORDER BY w.is_holding DESC, w.active DESC, nr.ticker
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


def _get_macro_indicator_snapshot(conn: psycopg.Connection, asof: date, lookback_days: int = 400) -> dict:
    cutoff = asof.fromordinal(asof.toordinal() - lookback_days)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT indicator_code, indicator_name, region, asof, value, unit, source
            FROM macro_indicators
            WHERE asof >= %s AND asof <= %s
            ORDER BY indicator_code, asof DESC
            """,
            (cutoff, asof),
        )
        rows = [dict(row) for row in cur.fetchall()]

    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["indicator_code"], []).append(row)

    snapshot = {"asof": str(asof), "indicators": []}
    for code, items in grouped.items():
        latest = items[0]
        prev = items[1] if len(items) > 1 else None
        prev_month = next((item for item in items[1:] if (latest["asof"] - item["asof"]).days >= 28), None)
        snapshot["indicators"].append({
            "code": code,
            "name": latest["indicator_name"],
            "region": latest["region"],
            "value": float(latest["value"]),
            "unit": latest["unit"],
            "asof": str(latest["asof"]),
            "delta_prev": round(float(latest["value"]) - float(prev["value"]), 4) if prev else None,
            "delta_month": round(float(latest["value"]) - float(prev_month["value"]), 4) if prev_month else None,
        })
    return snapshot


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
    reset_run_budget()  # 새 실행 — per-run 호출 카운터·스로틀 초기화
    client = _get_gemini_client()
    model = _get_bulk_model()
    errors: list[dict] = []
    enriched = 0
    started_at = time.monotonic()

    tickers = _tickers_needing_enrichment(conn, asof)  # 보유·관심 우선 정렬
    logger.info(
        "뉴스 요약 대상: %d개 종목 (asof=%s, 최대 Gemini 호출 상한≈%d, 시간 예산=%.0fs, RPD 예산=%s, RPM 간격=%.1fs)",
        len(tickers), asof, len(tickers) * 3, GEMINI_BATCH_BUDGET_SECONDS,
        GEMINI_MAX_CALLS_PER_RUN or "무제한", GEMINI_MIN_INTERVAL_SECONDS,
    )

    for ticker in tickers:
        if not _within_budget(started_at):
            logger.warning("뉴스 요약 예산 초과로 중단: enriched=%d attempted<=%d budget=%.0fs", enriched, len(tickers), GEMINI_BATCH_BUDGET_SECONDS)
            errors.append({
                "ticker": ticker,
                "step": "enrich_news_budget",
                "error": f"Gemini 뉴스 요약 시간 예산 초과({GEMINI_BATCH_BUDGET_SECONDS:.0f}s) — 나머지 종목은 다음 실행으로 이월",
                "ts": datetime.utcnow().isoformat(),
            })
            break
        if _run_budget_exhausted():
            logger.warning("뉴스 요약 RPD 예산 초과로 중단: enriched=%d calls=%d cap=%d", enriched, _api_calls_this_run, GEMINI_MAX_CALLS_PER_RUN)
            errors.append({
                "ticker": ticker,
                "step": "enrich_news_rpd_budget",
                "error": f"Gemini 호출 예산 초과(RPD {GEMINI_MAX_CALLS_PER_RUN}/run) — 보유·관심 우선 처리 후 나머지는 다음 주기로 이월",
                "ts": datetime.utcnow().isoformat(),
            })
            break
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
                # PR(요약복구 진단): 실제 API 오류를 runs.errors에 영속화(종전엔 "로그 참조"만 저장돼
                # 매번 실호출로 재진단해야 했다). 빌링 소진 등 근본원인이 DB에서 바로 보이게.
                api_err = get_last_call_error()
                errors.append({
                    "ticker": ticker,
                    "step": "enrich_news_fallback",
                    "error": "Gemini 요약 생성 실패 — 중립 폴백 저장"
                             + (f" · API: {api_err}" if api_err else " (로그의 직전 오류 참조)"),
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
        SELECT title, body, published_at, source, url
        FROM news_raw WHERE ticker = %s
        ORDER BY published_at DESC NULLS LAST, fetched_at DESC
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (ticker, MAX_NEWS_PER_TICKER))
        return [dict(row) for row in cur.fetchall()]


def _tickers_needing_analyst_views(conn: psycopg.Connection, asof: date) -> list[str]:
    sql = """
        SELECT DISTINCT nr.ticker
        FROM news_raw nr
        JOIN watchlist w ON w.ticker = nr.ticker
        WHERE w.active = TRUE
          AND nr.published_at::date <= %s
          AND nr.published_at::date >= %s - INTERVAL '7 days'
          AND (
                nr.title ~* '(애널리스트|증권사|리포트|목표가|투자의견|recommendation|analyst|brokerage|target price)'
             OR COALESCE(nr.body, '') ~* '(애널리스트|증권사|리포트|목표가|투자의견|recommendation|analyst|brokerage|target price)'
          )
        ORDER BY nr.ticker
    """
    with conn.cursor() as cur:
        cur.execute(sql, (asof, asof))
        return [row["ticker"] for row in cur.fetchall()]


def _get_recent_analyst_news(conn: psycopg.Connection, ticker: str, asof: date) -> list[dict]:
    sql = """
        SELECT title, body, published_at, source, url
        FROM news_raw
        WHERE ticker = %s
          AND published_at::date <= %s
          AND published_at::date >= %s - INTERVAL '14 days'
          AND (
                title ~* '(애널리스트|증권사|리포트|목표가|투자의견|recommendation|analyst|brokerage|target price)'
             OR COALESCE(body, '') ~* '(애널리스트|증권사|리포트|목표가|투자의견|recommendation|analyst|brokerage|target price)'
          )
        ORDER BY published_at DESC NULLS LAST, fetched_at DESC
        LIMIT 12
    """
    with conn.cursor() as cur:
        cur.execute(sql, (ticker, asof, asof))
        return [dict(row) for row in cur.fetchall()]


def _get_recent_risk_analyst_news(conn: psycopg.Connection, ticker: str, asof: date) -> list[dict]:
    sql = """
        SELECT DISTINCT ON (url) title, body, published_at, source, url
        FROM news_raw
        WHERE ticker = %s
          AND published_at::date <= %s
          AND published_at::date >= %s - INTERVAL '14 days'
          AND (
                url IN (
                    SELECT DISTINCT item->>'url'
                    FROM news_analysis na,
                         LATERAL jsonb_array_elements(na.curated) AS item
                    WHERE na.ticker = %s
                      AND na.asof <= %s
                      AND na.asof >= %s - INTERVAL '14 days'
                      AND item->>'direction' = '악재'
                      AND COALESCE(item->>'url', '') <> ''
                )
             OR title ~* '(우려|리스크|악재|부담|하락|둔화|과열|고평가|밸류에이션|경쟁심화|경쟁 심화|재고 부담|수요 둔화|압박|부진|warning|risk|bearish|overvalued|competition|slowdown|inventory)'
             OR COALESCE(body, '') ~* '(우려|리스크|악재|부담|하락|둔화|과열|고평가|밸류에이션|경쟁심화|경쟁 심화|재고 부담|수요 둔화|압박|부진|warning|risk|bearish|overvalued|competition|slowdown|inventory)'
          )
        ORDER BY url, published_at DESC NULLS LAST, fetched_at DESC
        LIMIT 8
    """
    with conn.cursor() as cur:
        cur.execute(sql, (ticker, asof, asof, ticker, asof, asof))
        return [dict(row) for row in cur.fetchall()]


def _merge_analyst_view_news_inputs(
    analyst_items: list[dict],
    risk_items: list[dict],
    *,
    limit: int = 12,
) -> list[dict]:
    analyst_queue = list(analyst_items)
    risk_queue = list(risk_items)
    merged: list[dict] = []
    seen_urls: set[str] = set()

    target_risk = min(len(risk_queue), max(1, limit // 2)) if risk_queue else 0
    risk_used = 0

    while len(merged) < limit and (analyst_queue or risk_queue):
        pick_risk = risk_queue and (
            risk_used < target_risk and (len(merged) % 2 == 0 or not analyst_queue)
        )
        queue = risk_queue if pick_risk else analyst_queue or risk_queue
        item = queue.pop(0)
        url = (item.get("url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        merged.append(item)
        if queue is risk_queue:
            risk_used += 1

    return merged


def _get_ticker_context_items(conn: psycopg.Connection, ticker: str, asof: date) -> list[dict]:
    sql = """
        SELECT content, source, valid_from
        FROM ticker_context
        WHERE ticker = %s
          AND valid_from <= %s
        ORDER BY valid_from DESC, created_at DESC
        LIMIT 4
    """
    with conn.cursor() as cur:
        cur.execute(sql, (ticker, asof))
        return [dict(row) for row in cur.fetchall()]


def _build_analyst_view_rows(
    ticker: str,
    asof: date,
    payload: AnalystViewsOutput,
    news_items: list[dict] | None = None,
) -> list[AnalystViewRow]:
    allowed_sources_by_url = {
        (item.get("url") or "").strip(): (item.get("source") or "").strip()
        for item in (news_items or [])
        if (item.get("url") or "").strip()
    }
    rows: list[AnalystViewRow] = []
    for stance, items in (("bull", payload.bull), ("bear", payload.bear)):
        for item in items:
            source_url = item.source_url.strip()
            source = allowed_sources_by_url.get(source_url)
            if not source:
                continue
            rows.append(
                AnalystViewRow(
                    ticker=ticker,
                    asof=asof,
                    stance=stance,
                    point=item.point,
                    source=source,
                    source_url=source_url,
                )
            )
    return rows


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
    started_at = time.monotonic()

    tickers = _tickers_with_stale_fallback(conn)
    logger.info("폴백 재시도 대상: %d개 종목", len(tickers))

    for ticker in tickers:
        if not _within_budget(started_at):
            errors.append({"ticker": ticker, "step": "reenrich_budget",
                           "error": f"Gemini 재요약 시간 예산 초과({GEMINI_BATCH_BUDGET_SECONDS:.0f}s)",
                           "ts": datetime.utcnow().isoformat()})
            break
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


def extract_analyst_views_batch(
    conn: psycopg.Connection,
    asof: Optional[date] = None,
) -> tuple[int, list[dict]]:
    """최근 애널리스트/증권사 인용 뉴스에서 bull/bear 논거를 추출해 analyst_views에 저장."""
    asof = asof or date.today()
    client = _get_gemini_client()
    model = _get_bulk_model()
    errors: list[dict] = []
    saved = 0
    started_at = time.monotonic()

    tickers = _tickers_needing_analyst_views(conn, asof)
    logger.info("애널리스트 논거 추출 대상: %d개 종목", len(tickers))

    for ticker in tickers:
        if not _within_budget(started_at):
            errors.append({
                "ticker": ticker,
                "step": "analyst_views_budget",
                "error": f"Gemini 애널리스트 논거 추출 시간 예산 초과({GEMINI_BATCH_BUDGET_SECONDS:.0f}s)",
                "ts": datetime.utcnow().isoformat(),
            })
            break
        try:
            analyst_news_items = _get_recent_analyst_news(conn, ticker, asof)
            risk_news_items = _get_recent_risk_analyst_news(conn, ticker, asof)
            news_items = _merge_analyst_view_news_inputs(
                analyst_news_items,
                risk_news_items,
                limit=12,
            )
            if not news_items:
                continue
            company_name = _get_company_name(conn, ticker)
            context_items = _get_ticker_context_items(conn, ticker, asof)
            prompt = _build_analyst_views_prompt(ticker, company_name, news_items, context_items)
            payload = _call_gemini_for_analyst_views(client, model, prompt, ticker)
            rows = _build_analyst_view_rows(ticker, asof, payload, news_items=news_items)
            if rows:
                upsert_analyst_views(conn, rows)
                saved += len(rows)
        except Exception as exc:
            logger.error("%s: 애널리스트 논거 추출 실패: %s", ticker, exc, exc_info=True)
            errors.append({
                "ticker": ticker,
                "step": "analyst_views",
                "error": str(exc),
                "ts": datetime.utcnow().isoformat(),
            })
        time.sleep(API_SLEEP)

    logger.info("애널리스트 논거 추출 완료: %d건 저장", saved)
    return saved, errors


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

    # Wave 5-B: 시장 매력도 점수(결정론)를 해설 입력으로 주입. LLM은 점수·방향을 만들지 않고 설명만 한다.
    def _market_score_for(region: str) -> Optional[dict]:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT score, direction, confidence, divergence_note FROM market_score "
                "WHERE region=%s ORDER BY asof DESC LIMIT 1",
                (region,),
            )
            r = cur.fetchone()
        if not r:
            return None
        return {"score": float(r["score"]), "direction": r["direction"],
                "confidence": r["confidence"], "divergence_note": r["divergence_note"]}

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
        "MarketScore": _market_score_for("KR"),  # 코드가 만든 점수·방향(해설만, 생성 금지)
    }
    kr_news = _get_market_news(conn, MARKET_KR_TICKER)

    # US 입력
    us_metrics = {
        "asof": str(asof),
        "SP500": market_row.get("sp500"), "SP500_chg%": changes.get("sp500"),
        "NASDAQ": market_row.get("nasdaq"), "NASDAQ_chg%": changes.get("nasdaq"),
        "VIX": market_row.get("vix"), "VIX_chg%": changes.get("vix"),
        "UST10Y": market_row.get("ust10y"),
        "MarketScore": _market_score_for("US"),  # 코드가 만든 점수·방향(해설만, 생성 금지)
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


def summarize_macro_environment(
    conn: psycopg.Connection,
    asof: Optional[date] = None,
) -> bool:
    asof = asof or date.today()
    snapshot = _get_macro_indicator_snapshot(conn, asof)
    if not snapshot.get("indicators"):
        logger.warning("macro_indicators 없음 — 거시 요약 스킵")
        return False

    client = _get_gemini_client()
    model = _get_synth_model()
    try:
        prompt = _build_macro_summary_prompt(snapshot)
        text = _call_gemini_with_backoff(client, model, prompt)
        output = _parse_macro_summary_output(text)
    except Exception as exc:
        logger.error("거시 요약 실패: %s", exc, exc_info=True)
        return False

    row = MacroSummaryRow(
        summary_date=asof,
        headline=output.headline,
        support_view=output.support_view,
        oppose_view=output.oppose_view,
        watch_points=output.watch_points,
        summary_md=output.summary_md,
    )
    upsert_macro_summary(conn, row)
    logger.info("거시 요약 저장 완료 (%s)", asof)
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

            macro_ok = summarize_macro_environment(conn)
            logger.info("거시 환경 요약: %s", "완료" if macro_ok else "스킵/실패")

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
