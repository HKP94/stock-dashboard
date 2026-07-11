"""Gemini 빌링(선불 크레딧) 소진 fast-fail + 오류 영속화 (요약복구 진단).

07-05~ 전 종목 요약 실패의 근본원인 = 429 "prepayment credits are depleted"(빌링).
빌링 소진은 그 실행 내 회복 불가이므로 ① 재시도하지 않고(transient 아님) ② 첫 발생 후
이후 호출을 halt로 스킵(시간·호출 보존) ③ 실제 오류를 상위가 runs.errors에 영속화한다.
"""
from unittest.mock import patch

import pytest

from src import enrich_gemini as eg


BILLING_MSG = ("429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': "
               "'Your prepayment credits are depleted. Please go to AI Studio ...', "
               "'status': 'RESOURCE_EXHAUSTED'}}")


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    # 이 모듈은 단일키 백오프/빌링 동작을 검증한다 — 앰비언트 .env의 다중키 풀이
    # 로테이션을 일으키지 않도록 단일키로 고정(로테이션은 test_enrich_keypool.py에서 검증).
    monkeypatch.setenv("GEMINI_API_KEYS", "unit-test-key")
    eg.reset_run_budget()
    eg.reset_circuit_breaker()
    yield
    eg._key_pool = []
    eg.reset_circuit_breaker()


def test_billing_is_not_transient():
    exc = RuntimeError(BILLING_MSG)
    assert eg._is_billing_depleted(exc) is True
    assert eg._is_transient(exc) is False  # 429지만 재시도 대상 아님


def test_generic_429_still_transient():
    exc = RuntimeError("429 RESOURCE_EXHAUSTED quota exceeded, try again")
    assert eg._is_billing_depleted(exc) is False
    assert eg._is_transient(exc) is True


def test_free_tier_rate_limit_is_transient_not_billing():
    # 무료티어 RPM/RPD 초과 429 — 안내문에 'billing' 단어가 있어도 halt 아님(백오프 재시도)
    exc = RuntimeError("429 RESOURCE_EXHAUSTED. You've exceeded the rate limit. "
                       "Please check your plan and billing details. Please retry in 12s.")
    assert eg._is_billing_depleted(exc) is False   # 'billing' 단어에 오분류 안 됨
    assert eg._is_transient(exc) is True            # 레이트리밋은 재시도 대상


def test_rate_limit_retries_then_recovers(monkeypatch):
    # 레이트리밋 429 1회 후 성공 → halt 없이 재시도로 회복
    monkeypatch.setattr(eg, "TRANSIENT_BACKOFF_BASE", 0.0)
    monkeypatch.setattr(eg, "TRANSIENT_BACKOFF_JITTER", 0.0)
    seq = [RuntimeError("429 RESOURCE_EXHAUSTED rate limit, retry"), '{"ok": true}']

    def _flaky(_c, _m, _p):
        v = seq.pop(0)
        if isinstance(v, Exception):
            raise v
        return v

    with patch.object(eg, "_call_gemini", _flaky):
        out = eg._call_gemini_with_backoff(None, "m", "p")
    assert out == '{"ok": true}'
    assert eg._billing_halt is False


def test_billing_fast_fail_no_retry_and_halts():
    calls = {"n": 0}

    def _raise_billing(_c, _m, _p):
        calls["n"] += 1
        raise RuntimeError(BILLING_MSG)

    with patch.object(eg, "_call_gemini", _raise_billing):
        with pytest.raises(Exception):
            eg._call_gemini_with_backoff(None, "gemini-2.5-flash-lite", "p")
    # 재시도 없이 1회만(빌링은 transient 아님)
    assert calls["n"] == 1
    # 두 번째 호출은 halt로 API를 아예 안 때린다
    with patch.object(eg, "_call_gemini", _raise_billing):
        with pytest.raises(RuntimeError, match="billing halt"):
            eg._call_gemini_with_backoff(None, "gemini-2.5-flash-lite", "p2")
    assert calls["n"] == 1  # 증가 없음(스킵)
    assert "depleted" in (eg.get_last_call_error() or "")


def test_success_resets_billing_halt():
    def _ok(_c, _m, _p):
        return '{"ok": true}'
    with patch.object(eg, "_call_gemini", _ok):
        out = eg._call_gemini_with_backoff(None, "m", "p")
    assert out == '{"ok": true}'
    assert eg.get_last_call_error() is None


def test_rpm_throttle_spaces_calls(monkeypatch):
    # GEMINI_MIN_INTERVAL_SECONDS 간격만큼 sleep 하는지(실제 대기 대신 sleep 호출 인자 확인)
    eg.reset_run_budget()
    monkeypatch.setattr(eg, "GEMINI_MIN_INTERVAL_SECONDS", 4.0)
    slept = []
    monkeypatch.setattr(eg.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(eg, "_call_gemini", lambda _c, _m, _p: "{}")
    # 첫 호출은 스로틀 없음(last_ts=0), 두 번째는 간격 유지 시도
    eg._call_gemini_with_backoff(None, "m", "p")
    eg._call_gemini_with_backoff(None, "m", "p")
    # 두 번째 호출에서 sleep이 호출됐고(간격 미달), 값은 (0,4] 범위
    assert slept, "RPM 스로틀이 sleep을 호출하지 않음"
    assert all(0 < s <= 4.0 for s in slept)


def test_rpd_budget_counter_increments(monkeypatch):
    eg.reset_run_budget()
    monkeypatch.setattr(eg, "GEMINI_MIN_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(eg, "_call_gemini", lambda _c, _m, _p: "{}")
    for _ in range(3):
        eg._call_gemini_with_backoff(None, "m", "p")
    assert eg._api_calls_this_run == 3
    assert eg._run_budget_exhausted() is False
    monkeypatch.setattr(eg, "GEMINI_MAX_CALLS_PER_RUN", 3)
    assert eg._run_budget_exhausted() is True  # 3 >= 3


def test_reset_run_budget_clears_counter():
    eg._api_calls_this_run = 99
    eg.reset_run_budget()
    assert eg._api_calls_this_run == 0
