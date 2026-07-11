"""Gemini 무료티어 키 풀 로테이션 — 한 키가 RPD/레이트리밋 또는 빌링으로 소진되면
다음 키로 넘겨 요약을 이어간다(유료 크레딧 소진 halt 우회). 계산 로직 불변, 백엔드(키) 교체.

_call_gemini는 기존 테스트처럼 patch로 mock. _client_for_idx도 patch해 실제 genai.Client 생성 회피.
"""
from unittest.mock import patch

import pytest

from src import enrich_gemini as eg


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    # 재시도 대기 제거(빠른 테스트)
    monkeypatch.setattr(eg, "TRANSIENT_BACKOFF_BASE", 0.0)
    monkeypatch.setattr(eg, "TRANSIENT_BACKOFF_JITTER", 0.0)
    monkeypatch.setattr(eg.time, "sleep", lambda *_a, **_k: None)
    eg.reset_circuit_breaker()
    yield
    # 풀 상태를 비워 다음 테스트가 env에서 새로 로드하게(모듈 전역 누수 차단)
    eg._key_pool = []
    eg._active_key_idx = 0
    eg._exhausted_keys.clear()
    eg._clients_by_idx.clear()
    eg.reset_circuit_breaker()


def _load_pool(monkeypatch, keys: str):
    """GEMINI_API_KEYS 설정 후 풀 리로드 + client 생성 스텁(idx→'client{idx}')."""
    monkeypatch.setenv("GEMINI_API_KEYS", keys)
    monkeypatch.setattr(eg, "_client_for_idx", lambda idx: f"client{idx}")
    eg.reset_run_budget()


# ── _load_api_keys 파싱 ────────────────────────────────────────

def test_load_keys_multi_trim_dedupe(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEYS", "  a , b ,, a ,c ")
    assert eg._load_api_keys() == ["a", "b", "c"]


def test_load_keys_single_fallback(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "solo")
    assert eg._load_api_keys() == ["solo"]


def test_load_keys_plural_takes_precedence(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEYS", "k1,k2")
    monkeypatch.setenv("GEMINI_API_KEY", "ignored")
    assert eg._load_api_keys() == ["k1", "k2"]


# ── 로테이션 ───────────────────────────────────────────────────

def test_rate_limit_exhaust_advances_to_next_key(monkeypatch):
    _load_pool(monkeypatch, "k0,k1,k2")

    def fake(client, _m, _p):
        if client == "client0":
            raise RuntimeError("429 RESOURCE_EXHAUSTED rate limit, retry")
        return '{"ok": true}'

    with patch.object(eg, "_call_gemini", fake):
        out = eg._call_gemini_with_backoff("ignored-param", "m", "p")
    assert out == '{"ok": true}'
    assert eg._active_key_idx == 1          # k0 소진 → k1로 advance
    assert 0 in eg._exhausted_keys
    assert eg._billing_halt is False


def test_billing_key_skipped_not_full_halt(monkeypatch):
    _load_pool(monkeypatch, "k0,k1")

    def fake(client, _m, _p):
        if client == "client0":
            raise RuntimeError("429 Your prepayment credits are depleted.")
        return '{"ok": true}'

    with patch.object(eg, "_call_gemini", fake):
        out = eg._call_gemini_with_backoff(None, "m", "p")
    assert out == '{"ok": true}'
    assert eg._active_key_idx == 1
    assert 0 in eg._exhausted_keys
    assert eg._billing_halt is False        # 그 키만 스킵 — 전체 halt 아님


def test_all_keys_billing_depleted_halts(monkeypatch):
    _load_pool(monkeypatch, "k0,k1,k2")

    def fake(_c, _m, _p):
        raise RuntimeError("Your prepayment credits are depleted.")

    with patch.object(eg, "_call_gemini", fake):
        with pytest.raises(RuntimeError):
            eg._call_gemini_with_backoff(None, "m", "p")
    assert eg._exhausted_keys == {0, 1, 2}
    assert eg._billing_halt is True         # 전키 소진에서만 halt


def test_all_keys_rate_limited_trips_circuit(monkeypatch):
    _load_pool(monkeypatch, "k0,k1")

    def fake(_c, _m, _p):
        raise RuntimeError("429 rate limit")

    with patch.object(eg, "_call_gemini", fake):
        with pytest.raises(RuntimeError, match="429"):
            eg._call_gemini_with_backoff(None, "m", "p")
    assert eg._exhausted_keys == {0, 1}
    assert eg._billing_halt is False
    assert eg._consecutive_transient_failures >= 1  # 전키 소진 → 서킷 카운트


def test_masked_key_in_last_error_no_leak(monkeypatch):
    _load_pool(monkeypatch, "supersecret-ABCD,alsosecret-WXYZ")

    def fake(_c, _m, _p):
        raise RuntimeError("429 rate limit")   # 전키 실패 → last_error 잔존

    with patch.object(eg, "_call_gemini", fake):
        with pytest.raises(RuntimeError):
            eg._call_gemini_with_backoff(None, "m", "p")
    err = eg.get_last_call_error() or ""
    assert "supersecret" not in err and "alsosecret" not in err   # 키 값 노출 금지
    assert "WXYZ" in err                     # 끝 4자리 마스킹만(마지막 소진 키)


# ── 하위호환(단일 키) ──────────────────────────────────────────

def test_single_key_no_rotation_success(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "solo")
    eg.reset_run_budget()
    with patch.object(eg, "_call_gemini", lambda _c, _m, _p: '{"ok": true}'):
        out = eg._call_gemini_with_backoff(None, "m", "p")
    assert out == '{"ok": true}'
    assert eg._active_key_idx == 0


def test_single_key_billing_halts(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "solo")
    eg.reset_run_budget()
    calls = {"n": 0}

    def fake(_c, _m, _p):
        calls["n"] += 1
        raise RuntimeError("Your prepayment credits are depleted.")

    with patch.object(eg, "_call_gemini", fake):
        with pytest.raises(RuntimeError):
            eg._call_gemini_with_backoff(None, "m", "p")
    assert calls["n"] == 1                   # 재시도 없이 1회(빌링)
    assert eg._billing_halt is True


# ── RPD 예산이 키 수만큼 스케일 ────────────────────────────────

def test_rpd_budget_scales_with_pool(monkeypatch):
    _load_pool(monkeypatch, "k0,k1")         # len 2
    monkeypatch.setattr(eg, "GEMINI_MAX_CALLS_PER_RUN", 3)
    eg._api_calls_this_run = 5
    assert eg._run_budget_exhausted() is False   # 5 < 3*2
    eg._api_calls_this_run = 6
    assert eg._run_budget_exhausted() is True    # 6 >= 3*2
