"""
tests/test_curation.py — 종목별 중요 뉴스 큐레이션 2단계 (mock)

DB·네트워크 없이: STEP A 스코어링 스키마, 임계값 필터, STEP B는 통과분만,
키 없음/실패 시 폴백([]).
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src import enrich_gemini as E

NEWS = [
    {"title": f"뉴스{i}", "body": f"본문{i}", "url": f"http://x/{i}",
     "source": "yahoo", "published_at": datetime(2026, 6, 17, 9, i % 60)}
    for i in range(8)
]


class TestScoreSchema:
    def test_valid(self):
        out = E._parse_curation_scores(json.dumps({"items": [
            {"idx": 0, "impact_score": 80, "category": "실적", "direction": "호재"}]}))
        assert out.items[0].impact_score == 80

    def test_impact_out_of_range_raises(self):
        with pytest.raises(ValidationError):
            E._parse_curation_scores(json.dumps({"items": [
                {"idx": 0, "impact_score": 150, "category": "실적", "direction": "호재"}]}))


def _scores(*pairs):
    """(idx, score) → STEP A JSON."""
    return json.dumps({"items": [
        {"idx": i, "impact_score": s, "category": "실적", "direction": "호재"} for i, s in pairs]})


def _insights(*idxs):
    return json.dumps({"insights": [{"idx": i, "insight": f"인사이트{i}"} for i in idxs]})


class TestCurationOrchestration:
    def test_threshold_filter_and_stepB_only_passing(self):
        # idx0=80(통과) idx1=40(탈락) idx2=65(통과) → STEP B는 2건만
        calls = []

        def fake(client, model, prompt):
            calls.append((model, prompt))
            if len(calls) == 1:           # STEP A
                return _scores((0, 80), (1, 40), (2, 65))
            return _insights(0, 2)        # STEP B

        with patch.object(E, "_call_gemini_with_backoff", side_effect=fake):
            out = E.curate_ticker_news(object(), "AAA", "에이", NEWS)
        assert len(out) == 2
        assert {c["impact_score"] for c in out} == {80, 65}
        # STEP B 프롬프트에 통과분만(idx0, idx2) 포함, 탈락(idx1) 없음
        stepb_prompt = calls[1][1]
        assert "[0]" in stepb_prompt and "[2]" in stepb_prompt and "[1]" not in stepb_prompt
        # 영향도 내림차순
        assert out[0]["impact_score"] >= out[1]["impact_score"]
        assert out[0]["insight"].startswith("인사이트")

    def test_no_passing_returns_empty_and_no_stepB(self):
        calls = []

        def fake(client, model, prompt):
            calls.append(model)
            return _scores((0, 30), (1, 20))   # 전부 임계값 미만

        with patch.object(E, "_call_gemini_with_backoff", side_effect=fake):
            out = E.curate_ticker_news(object(), "AAA", "에이", NEWS)
        assert out == []
        assert len(calls) == 1            # STEP B 호출 안 함

    def test_stepA_failure_returns_empty(self):
        with patch.object(E, "_call_gemini_with_backoff", side_effect=Exception("429")), \
             patch("time.sleep"):
            out = E.curate_ticker_news(object(), "AAA", "에이", NEWS)
        assert out == []

    def test_stepB_failure_keeps_news_without_insight(self):
        def fake(client, model, prompt):
            if model == E._get_bulk_model():
                return _scores((0, 90))
            raise Exception("STEP B down")

        with patch.object(E, "_call_gemini_with_backoff", side_effect=fake):
            out = E.curate_ticker_news(object(), "AAA", "에이", NEWS)
        assert len(out) == 1 and out[0]["insight"] == ""   # 인사이트 없이도 보존

    def test_input_capped(self):
        many = NEWS * 3  # 24건 → CURATION_MAX_NEWS(12)로 캡
        seen_idx = []

        def fake(client, model, prompt):
            if len(seen_idx) == 0:
                seen_idx.append(1)
                # 모든 입력 인덱스에 점수 — 캡 넘은 idx는 무시되어야
                return json.dumps({"items": [
                    {"idx": i, "impact_score": 70, "category": "실적", "direction": "호재"} for i in range(24)]})
            return _insights(*range(E.CURATION_TOP_K))

        with patch.object(E, "_call_gemini_with_backoff", side_effect=fake):
            out = E.curate_ticker_news(object(), "AAA", "에이", many)
        # 캡(12) 내 인덱스만 유효 → TOP_K로 제한
        assert len(out) <= E.CURATION_TOP_K

    def test_curated_item_fields(self):
        def fake(client, model, prompt):
            if model == E._get_bulk_model():
                return _scores((0, 88))
            return _insights(0)

        with patch.object(E, "_call_gemini_with_backoff", side_effect=fake):
            out = E.curate_ticker_news(object(), "AAA", "에이", NEWS)
        item = out[0]
        for k in ("title", "url", "source", "published_at", "category", "direction", "impact_score", "insight"):
            assert k in item
        assert item["direction"] in ("호재", "악재", "중립")
