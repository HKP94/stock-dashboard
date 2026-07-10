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
def _reset():
    eg.reset_circuit_breaker()
    yield
    eg.reset_circuit_breaker()


def test_billing_is_not_transient():
    exc = RuntimeError(BILLING_MSG)
    assert eg._is_billing_depleted(exc) is True
    assert eg._is_transient(exc) is False  # 429지만 재시도 대상 아님


def test_generic_429_still_transient():
    exc = RuntimeError("429 RESOURCE_EXHAUSTED quota exceeded, try again")
    assert eg._is_billing_depleted(exc) is False
    assert eg._is_transient(exc) is True


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
