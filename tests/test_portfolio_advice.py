"""
tests/test_portfolio_advice.py — 포트폴리오 CoT 전략 조언 (mock)

DB·네트워크 없이: 절대원칙 주입, 단계 간 데이터 전달, 규칙기반 폴백 검증.
"""

from __future__ import annotations

import json
import re
from unittest.mock import patch

import pytest

from src import portfolio_advice as PA

BANNED = re.compile(r"매수하|매도하|사세요|파세요|팔아라|사라|비중을? ?(늘|줄)리|담으세요|덜어내")

CTX = {
    "holdings": [
        {"ticker": "AAA", "name": "에이", "market": "KR", "sector": "반도체", "currency": "KRW",
         "eval_krw": 5_000_000, "weight_pct": 50.0, "composite": 35.0,
         "factors": {"momentum": 40, "value": 60, "quality": 55, "growth": 50, "sentiment": 45},
         "rating": "Hold", "upside": -12.0, "flags": ["RSI 과열 (75.0)"]},
        {"ticker": "BBB", "name": "비", "market": "US", "sector": "IT", "currency": "USD",
         "eval_krw": 3_000_000, "weight_pct": 30.0, "composite": 70.0,
         "factors": {"momentum": 65, "value": 45, "quality": 72, "growth": 60, "sentiment": 55},
         "rating": "Buy", "upside": 15.0, "flags": []},
    ],
    "cash_krw": 2_000_000, "cash_weight_pct": 20.0, "cash_by_currency": {"KRW": 2_000_000},
    "asset_total_krw": 10_000_000, "regime": "bull",
    "regime_weights": {"momentum": 0.45, "value": 0.15, "quality": 0.15, "growth": 0.15, "sentiment": 0.10},
    "fx_rate": 1400.0,
}


# ── 절대 원칙 주입 ────────────────────────────────────────────────
class TestAbsoluteRulesInPrompts:
    def test_step1_has_rules(self):
        p = PA._prompt_step1(CTX)
        assert "투자 자문" in p and "매수/매도" in p and "관찰" in p

    def test_all_steps_have_rules(self):
        s1, s2, s3 = PA._rule_step1(CTX), PA._rule_step2(CTX), PA._rule_step3(CTX)
        prompts = [PA._prompt_step1(CTX), PA._prompt_step2(CTX, s1),
                   PA._prompt_step3(CTX, s2), PA._prompt_step4(CTX, s1, s2, s3)]
        for p in prompts:
            assert PA.ABSOLUTE_RULES in p


# ── 단계 간 데이터 전달 ───────────────────────────────────────────
class TestDataPassing:
    def test_step2_prompt_contains_step1(self):
        s1 = PA._rule_step1(CTX)
        p2 = PA._prompt_step2(CTX, s1)
        assert s1.concentration_note in p2 or s1.facts[0] in p2

    def test_step3_prompt_contains_step2(self):
        s1 = PA._rule_step1(CTX)
        s2 = PA._rule_step2(CTX, ) if False else PA._rule_step2(CTX)
        p3 = PA._prompt_step3(CTX, s2)
        assert s2.risks[0] in p3

    def test_step4_prompt_contains_all_prior(self):
        s1, s2, s3 = PA._rule_step1(CTX), PA._rule_step2(CTX), PA._rule_step3(CTX)
        p4 = PA._prompt_step4(CTX, s1, s2, s3)
        assert s1.concentration_note in p4 and s2.risks[0] in p4 and s3.tilt_note in p4


# ── 규칙기반 폴백 ─────────────────────────────────────────────────
class TestRuleFallback:
    def test_rule_step2_flags_concentration(self):
        s2 = PA._rule_step2(CTX)
        # AAA 50% 집중 → 집중도 리스크 관찰
        assert any("집중" in r for r in s2.risks)

    def test_rule_step2_flags_overheat_and_overvalued(self):
        s2 = PA._rule_step2(CTX)
        joined = " ".join(s2.risks)
        assert "과열" in joined        # RSI 과열 신호
        assert "고평가" in joined or "상승여력" in joined  # upside -12%

    def test_rule_based_no_banned_words(self):
        out = PA._rule_based(CTX)
        blob = json.dumps(out, ensure_ascii=False)
        assert not BANNED.search(blob), f"매매 지시 문구 검출: {BANNED.search(blob)}"

    def test_rule_based_structure(self):
        out = PA._rule_based(CTX)
        assert out["source"] == "rule"
        assert out["holdingsCount"] == 2
        for k in ("step1", "step2", "step3", "step4", "disclaimer", "cacheKey"):
            assert k in out
        assert "자문" in out["disclaimer"]


# ── analyze_portfolio: 키 유무에 따른 경로 ─────────────────────────
class TestAnalyzeOrchestration:
    def test_no_key_uses_rule(self):
        with patch.object(PA, "gather_context", return_value=CTX), \
             patch.object(PA, "_has_api_key", return_value=False), \
             patch.object(PA, "_load_cached", return_value=None), \
             patch.object(PA, "_save"):
            out = PA.analyze_portfolio(conn=None, force=True)
            assert out["source"] == "rule"

    def test_gemini_path_sequential_calls(self):
        # 각 STEP이 유효 JSON을 돌려주면 source=gemini, _llm_call 4회, 프롬프트에 직전 단계 포함
        s1_json = json.dumps({"facts": ["F1"], "concentration_note": "CONC", "allocation_note": "ALLOC", "cash_note": "CASH"})
        s2_json = json.dumps({"risks": ["R1"]})
        s3_json = json.dumps({"regime": "강세", "tilt_note": "TILT", "alignment_note": "ALIGN"})
        s4_json = json.dumps({"summary": "SUM", "questions": ["Q1"]})
        calls = []

        def fake_llm(client, model, prompt):
            calls.append(prompt)
            return [s1_json, s2_json, s3_json, s4_json][len(calls) - 1]

        with patch.object(PA, "gather_context", return_value=CTX), \
             patch.object(PA, "_has_api_key", return_value=True), \
             patch.object(PA, "_get_client", return_value=object()), \
             patch.object(PA, "_load_cached", return_value=None), \
             patch.object(PA, "_save"), \
             patch.object(PA, "_llm_call", side_effect=fake_llm):
            out = PA.analyze_portfolio(conn=None, force=True)
            assert out["source"] == "gemini"
            assert len(calls) == 4
            assert "CONC" in calls[1]          # STEP2 프롬프트에 STEP1 결과
            assert "R1" in calls[2]            # STEP3 프롬프트에 STEP2 결과
            assert "TILT" in calls[3]          # STEP4 프롬프트에 STEP3 결과
            assert out["step4"]["summary"] == "SUM"

    def test_step1_llm_fail_shortcircuits_to_rule(self):
        # STEP1이 None(파싱 실패) → 남은 단계 호출 없이 규칙기반
        calls = []

        def fail_llm(client, model, prompt):
            calls.append(prompt)
            return "not json"

        with patch.object(PA, "gather_context", return_value=CTX), \
             patch.object(PA, "_has_api_key", return_value=True), \
             patch.object(PA, "_get_client", return_value=object()), \
             patch.object(PA, "_load_cached", return_value=None), \
             patch.object(PA, "_save"), \
             patch.object(PA, "_llm_call", side_effect=fail_llm):
            out = PA.analyze_portfolio(conn=None, force=True)
            assert out["source"] == "rule"
            # STEP1만 시도(_call_step 내부 2회) — 남은 STEP2~4는 호출 안 함
            assert len(calls) <= 2

    def test_empty_holdings(self):
        empty_ctx = {**CTX, "holdings": [], "cash_krw": 0, "cash_weight_pct": 0, "asset_total_krw": 0}
        with patch.object(PA, "gather_context", return_value=empty_ctx):
            out = PA.analyze_portfolio(conn=None, force=True)
            assert out.get("empty") is True and out["holdingsCount"] == 0
