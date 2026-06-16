"""
tests/test_enrich_gemini.py — enrich_gemini 단위 테스트

네트워크·DB·Gemini API 없이 검증.
_call_gemini를 unittest.mock으로 대체해 pydantic 검증 로직·재시도 로직만 확인.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from src.enrich_gemini import (
    BODY_CAP,
    TRANSIENT_RETRIES,
    _build_market_prompt,
    _build_news_prompt,
    _call_gemini_for_market,
    _call_gemini_for_news,
    _call_gemini_with_backoff,
    _is_transient,
    _neutral_news_fallback,
    _parse_market_output,
    _parse_news_output,
    is_fallback_summary,
)

# ──────────────────────────────────────────────────────────────
# 픽스처 (유효한 JSON 페이로드)
# ──────────────────────────────────────────────────────────────

VALID_NEWS_PAYLOAD: dict = {
    "sentiment": "긍정",
    "sentiment_score": 0.5,
    "key_points": ["포인트1", "포인트2"],
    "catalysts": [],
    "risks": [],
    "summary_md": "- 요약1\n- 요약2",
    "confidence": "상",
    "based_on": "recent",
}

VALID_MARKET_PAYLOAD: dict = {
    "regime": "위험선호",
    "headline": "오늘 시장 한 줄 요약",
    "drivers": ["드라이버1", "드라이버2"],
    "kr_us_note": "한미 온도차 코멘트",
    "watch_today": ["체크포인트1"],
    "summary_md": "- 시장 불릿1\n- 시장 불릿2",
}

VALID_NEWS_JSON: str = json.dumps(VALID_NEWS_PAYLOAD, ensure_ascii=False)
VALID_MARKET_JSON: str = json.dumps(VALID_MARKET_PAYLOAD, ensure_ascii=False)

SAMPLE_NEWS_ITEMS: list[dict] = [
    {"title": "애플 실적 발표", "body": "내용 요약", "published_at": None, "source": "yahoo"},
    {"title": "아이폰 수요 강세", "body": None, "published_at": None, "source": "naver"},
]


# ──────────────────────────────────────────────────────────────
# _parse_news_output 단위 테스트
# ──────────────────────────────────────────────────────────────

class TestParseNewsOutput:
    def test_valid_json_returns_model(self):
        result = _parse_news_output(VALID_NEWS_JSON)
        assert result.sentiment == "긍정"
        assert result.sentiment_score == 0.5
        assert result.confidence == "상"
        assert result.based_on == "recent"

    def test_invalid_json_raises_decode_error(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_news_output("전혀 JSON이 아님")

    def test_missing_sentiment_raises_validation_error(self):
        missing = {**VALID_NEWS_PAYLOAD}
        del missing["sentiment"]
        with pytest.raises(ValidationError):
            _parse_news_output(json.dumps(missing))

    def test_invalid_sentiment_literal_raises(self):
        bad = {**VALID_NEWS_PAYLOAD, "sentiment": "보통"}
        with pytest.raises(ValidationError):
            _parse_news_output(json.dumps(bad))

    def test_empty_key_points_raises(self):
        bad = {**VALID_NEWS_PAYLOAD, "key_points": []}
        with pytest.raises(ValidationError):
            _parse_news_output(json.dumps(bad))

    def test_sentiment_score_above_1_raises(self):
        bad = {**VALID_NEWS_PAYLOAD, "sentiment_score": 1.5}
        with pytest.raises(ValidationError):
            _parse_news_output(json.dumps(bad))

    def test_sentiment_score_below_minus1_raises(self):
        bad = {**VALID_NEWS_PAYLOAD, "sentiment_score": -1.5}
        with pytest.raises(ValidationError):
            _parse_news_output(json.dumps(bad))

    def test_invalid_based_on_raises(self):
        bad = {**VALID_NEWS_PAYLOAD, "based_on": "unknown"}
        with pytest.raises(ValidationError):
            _parse_news_output(json.dumps(bad))

    def test_invalid_confidence_raises(self):
        bad = {**VALID_NEWS_PAYLOAD, "confidence": "최상"}
        with pytest.raises(ValidationError):
            _parse_news_output(json.dumps(bad))

    def test_catalysts_with_invalid_date_format_raises(self):
        bad = {**VALID_NEWS_PAYLOAD, "catalysts": [
            {"date": "2024/06/08", "headline": "h", "impact": "긍정", "importance": "상"}
        ]}
        with pytest.raises(ValidationError):
            _parse_news_output(json.dumps(bad))


# ──────────────────────────────────────────────────────────────
# _neutral_news_fallback 단위 테스트
# ──────────────────────────────────────────────────────────────

class TestNeutralFallback:
    def test_returns_neutral_sentiment(self):
        result = _neutral_news_fallback()
        assert result.sentiment == "중립"

    def test_score_is_zero(self):
        result = _neutral_news_fallback()
        assert result.sentiment_score == 0.0

    def test_confidence_is_low(self):
        result = _neutral_news_fallback()
        assert result.confidence == "하"

    def test_summary_indicates_failure(self):
        # PR-3: '분석 실패'(빈약) 대신 안내 문구 — 보류/참고 안내를 포함
        result = _neutral_news_fallback()
        assert "보류" in result.summary_md or "참고" in result.summary_md

    def test_key_points_not_empty(self):
        result = _neutral_news_fallback()
        assert len(result.key_points) >= 1

    def test_returns_new_instance_each_call(self):
        a = _neutral_news_fallback()
        b = _neutral_news_fallback()
        assert a is not b  # 독립 인스턴스

    def test_is_valid_news_summary_output(self):
        from src.schemas import NewsSummaryOutput
        result = _neutral_news_fallback()
        assert isinstance(result, NewsSummaryOutput)

    def test_marked_as_fallback_old(self):
        # PR-1(진단): 폴백은 based_on='fallback_old'로 표식 → export 비노출/재시도 선별
        result = _neutral_news_fallback()
        assert result.based_on == "fallback_old"
        assert is_fallback_summary(result.summary_md, result.based_on)


# ──────────────────────────────────────────────────────────────
# PR-1(진단): is_fallback_summary / 일시오류 지수 백오프
# ──────────────────────────────────────────────────────────────

class TestIsFallbackSummary:
    def test_old_marker(self):
        assert is_fallback_summary("분석 실패") is True

    def test_new_marker(self):
        assert is_fallback_summary("- 뉴스 자동 요약 일시 보류(생성 실패).") is True

    def test_based_on_signal(self):
        assert is_fallback_summary("정상 요약 본문", "fallback_old") is True

    def test_empty_is_fallback(self):
        assert is_fallback_summary("") is True
        assert is_fallback_summary(None) is True

    def test_real_summary_not_fallback(self):
        assert is_fallback_summary("- 실적 가이던스 상향 → 모멘텀 강화", "recent") is False


class TestTransientBackoff:
    def test_is_transient_detects_429(self):
        assert _is_transient(Exception("429 RESOURCE_EXHAUSTED")) is True
        assert _is_transient(Exception("503 UNAVAILABLE, model overloaded")) is True

    def test_is_transient_false_for_bad_request(self):
        assert _is_transient(Exception("400 INVALID_ARGUMENT")) is False

    def test_retries_then_succeeds_on_transient(self):
        with patch("src.enrich_gemini._call_gemini") as mock_call, patch("time.sleep"):
            mock_call.side_effect = [Exception("429 quota"), Exception("503 overloaded"), "OK"]
            assert _call_gemini_with_backoff(MagicMock(), "m", "p") == "OK"
            assert mock_call.call_count == 3

    def test_non_transient_raises_immediately(self):
        with patch("src.enrich_gemini._call_gemini") as mock_call, patch("time.sleep"):
            mock_call.side_effect = [Exception("400 bad request")]
            with pytest.raises(Exception):
                _call_gemini_with_backoff(MagicMock(), "m", "p")
            assert mock_call.call_count == 1

    def test_gives_up_after_max_retries(self):
        with patch("src.enrich_gemini._call_gemini") as mock_call, patch("time.sleep"):
            mock_call.side_effect = [Exception("429")] * TRANSIENT_RETRIES
            with pytest.raises(Exception):
                _call_gemini_with_backoff(MagicMock(), "m", "p")
            assert mock_call.call_count == TRANSIENT_RETRIES


# ──────────────────────────────────────────────────────────────
# _parse_market_output 단위 테스트
# ──────────────────────────────────────────────────────────────

class TestParseMarketOutput:
    def test_valid_json_returns_model(self):
        result = _parse_market_output(VALID_MARKET_JSON)
        assert result.regime == "위험선호"
        assert result.headline == "오늘 시장 한 줄 요약"
        assert len(result.drivers) >= 1

    def test_invalid_json_raises_decode_error(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_market_output("{bad json")

    def test_invalid_regime_literal_raises(self):
        bad = {**VALID_MARKET_PAYLOAD, "regime": "위험중립중간"}
        with pytest.raises(ValidationError):
            _parse_market_output(json.dumps(bad))

    def test_empty_drivers_raises(self):
        bad = {**VALID_MARKET_PAYLOAD, "drivers": []}
        with pytest.raises(ValidationError):
            _parse_market_output(json.dumps(bad))

    def test_empty_watch_today_raises(self):
        bad = {**VALID_MARKET_PAYLOAD, "watch_today": []}
        with pytest.raises(ValidationError):
            _parse_market_output(json.dumps(bad))

    def test_missing_headline_raises(self):
        missing = {**VALID_MARKET_PAYLOAD}
        del missing["headline"]
        with pytest.raises(ValidationError):
            _parse_market_output(json.dumps(missing))


# ──────────────────────────────────────────────────────────────
# _call_gemini_for_news 재시도 로직 테스트 (mock)
# ──────────────────────────────────────────────────────────────

def _news_side_effects(*payloads) -> list:
    """dict → JSON 문자열 변환. 문자열은 그대로."""
    return [json.dumps(p, ensure_ascii=False) if isinstance(p, dict) else p
            for p in payloads]


class TestCallGeminiForNews:
    def test_success_on_first_attempt(self):
        with patch("src.enrich_gemini._call_gemini") as mock_call, \
             patch("time.sleep"):
            mock_call.side_effect = _news_side_effects(VALID_NEWS_PAYLOAD)
            result = _call_gemini_for_news(MagicMock(), "model", "prompt", "AAPL")
            assert result.sentiment == "긍정"
            assert mock_call.call_count == 1

    def test_success_on_retry_after_json_error(self):
        with patch("src.enrich_gemini._call_gemini") as mock_call, \
             patch("time.sleep"):
            mock_call.side_effect = _news_side_effects("not json at all", VALID_NEWS_PAYLOAD)
            result = _call_gemini_for_news(MagicMock(), "model", "prompt", "AAPL")
            assert result.sentiment == "긍정"
            assert mock_call.call_count == 2

    def test_success_on_retry_after_validation_error(self):
        bad = {**VALID_NEWS_PAYLOAD, "sentiment": "invalid_value"}
        with patch("src.enrich_gemini._call_gemini") as mock_call, \
             patch("time.sleep"):
            mock_call.side_effect = _news_side_effects(bad, VALID_NEWS_PAYLOAD)
            result = _call_gemini_for_news(MagicMock(), "model", "prompt", "AAPL")
            assert result.sentiment == "긍정"
            assert mock_call.call_count == 2

    def test_neutral_fallback_on_double_json_failure(self):
        with patch("src.enrich_gemini._call_gemini") as mock_call, \
             patch("time.sleep"):
            mock_call.side_effect = _news_side_effects("bad json 1", "bad json 2")
            result = _call_gemini_for_news(MagicMock(), "model", "prompt", "TEST")
            assert result.sentiment == "중립"
            assert result.confidence == "하"
            assert mock_call.call_count == 2

    def test_neutral_fallback_on_double_validation_failure(self):
        bad = {**VALID_NEWS_PAYLOAD, "sentiment": "invalid"}
        with patch("src.enrich_gemini._call_gemini") as mock_call, \
             patch("time.sleep"):
            mock_call.side_effect = _news_side_effects(bad, bad)
            result = _call_gemini_for_news(MagicMock(), "model", "prompt", "TEST")
            assert result.sentiment == "중립"
            assert mock_call.call_count == 2

    def test_sleep_called_between_retry(self):
        with patch("src.enrich_gemini._call_gemini") as mock_call, \
             patch("time.sleep") as mock_sleep:
            mock_call.side_effect = _news_side_effects("bad json", VALID_NEWS_PAYLOAD)
            _call_gemini_for_news(MagicMock(), "model", "prompt", "TEST")
            mock_sleep.assert_called()

    def test_no_extra_call_on_success(self):
        """첫 번째 성공이면 두 번째 호출 없음."""
        with patch("src.enrich_gemini._call_gemini") as mock_call, \
             patch("time.sleep"):
            mock_call.side_effect = _news_side_effects(VALID_NEWS_PAYLOAD)
            _call_gemini_for_news(MagicMock(), "model", "prompt", "AAPL")
            assert mock_call.call_count == 1


# ──────────────────────────────────────────────────────────────
# _call_gemini_for_market 재시도 로직 테스트 (mock)
# ──────────────────────────────────────────────────────────────

def _market_side_effects(*payloads) -> list:
    return [json.dumps(p, ensure_ascii=False) if isinstance(p, dict) else p
            for p in payloads]


class TestCallGeminiForMarket:
    def test_success_on_first_attempt(self):
        with patch("src.enrich_gemini._call_gemini") as mock_call, \
             patch("time.sleep"):
            mock_call.side_effect = _market_side_effects(VALID_MARKET_PAYLOAD)
            result = _call_gemini_for_market(MagicMock(), "model", "prompt")
            assert result is not None
            assert result.regime == "위험선호"
            assert mock_call.call_count == 1

    def test_success_on_retry(self):
        with patch("src.enrich_gemini._call_gemini") as mock_call, \
             patch("time.sleep"):
            mock_call.side_effect = _market_side_effects("bad json", VALID_MARKET_PAYLOAD)
            result = _call_gemini_for_market(MagicMock(), "model", "prompt")
            assert result is not None
            assert mock_call.call_count == 2

    def test_returns_none_on_double_failure(self):
        with patch("src.enrich_gemini._call_gemini") as mock_call, \
             patch("time.sleep"):
            mock_call.side_effect = _market_side_effects("bad 1", "bad 2")
            result = _call_gemini_for_market(MagicMock(), "model", "prompt")
            assert result is None
            assert mock_call.call_count == 2

    def test_returns_none_on_double_validation_error(self):
        bad = {**VALID_MARKET_PAYLOAD, "regime": "invalid_regime"}
        with patch("src.enrich_gemini._call_gemini") as mock_call, \
             patch("time.sleep"):
            mock_call.side_effect = _market_side_effects(bad, bad)
            result = _call_gemini_for_market(MagicMock(), "model", "prompt")
            assert result is None

    def test_sleep_called_on_retry(self):
        with patch("src.enrich_gemini._call_gemini") as mock_call, \
             patch("time.sleep") as mock_sleep:
            mock_call.side_effect = _market_side_effects("bad", VALID_MARKET_PAYLOAD)
            _call_gemini_for_market(MagicMock(), "model", "prompt")
            mock_sleep.assert_called()


# ──────────────────────────────────────────────────────────────
# 프롬프트 빌더 테스트
# ──────────────────────────────────────────────────────────────

class TestBuildNewsPrompt:
    def test_contains_ticker(self):
        prompt = _build_news_prompt("AAPL", "애플", SAMPLE_NEWS_ITEMS)
        assert "AAPL" in prompt

    def test_contains_company_name(self):
        prompt = _build_news_prompt("AAPL", "애플", SAMPLE_NEWS_ITEMS)
        assert "애플" in prompt

    def test_contains_news_count(self):
        prompt = _build_news_prompt("AAPL", "애플", SAMPLE_NEWS_ITEMS)
        assert str(len(SAMPLE_NEWS_ITEMS)) in prompt

    def test_body_capped(self):
        long_body = "X" * (BODY_CAP + 100)
        items = [{"title": "제목", "body": long_body, "published_at": None, "source": "yahoo"}]
        prompt = _build_news_prompt("AAPL", "애플", items)
        assert "X" * (BODY_CAP + 1) not in prompt

    def test_none_body_handled(self):
        items = [{"title": "제목", "body": None, "published_at": None, "source": "yahoo"}]
        prompt = _build_news_prompt("AAPL", "애플", items)
        assert "제목" in prompt  # None body는 빈 문자열로 처리

    def test_yahoo_source_tagged(self):
        items = [{"title": "t", "body": "b", "published_at": None, "source": "yahoo"}]
        prompt = _build_news_prompt("AAPL", "애플", items)
        assert "[야후/핵심팩트]" in prompt

    def test_naver_source_tagged(self):
        items = [{"title": "t", "body": "b", "published_at": None, "source": "naver"}]
        prompt = _build_news_prompt("AAPL", "애플", items)
        assert "[네이버/시장트렌드]" in prompt

    def test_no_buy_sell_recommendation(self):
        prompt = _build_news_prompt("AAPL", "애플", SAMPLE_NEWS_ITEMS)
        assert "매수/매도 의견이나 목표가를 만들지 마라" in prompt


class TestBuildMarketPrompt:
    def test_contains_market_data(self):
        metrics = {"SP500": 5000.0, "KOSPI": 2700.0}
        prompt = _build_market_prompt(metrics, {})
        assert "SP500" in prompt
        assert "5000" in prompt

    def test_contains_sentiment_rollup(self):
        rollup = {"긍정": 10, "중립": 5}
        prompt = _build_market_prompt({}, rollup)
        assert "긍정" in prompt
        assert "10" in prompt

    def test_no_stock_recommendation(self):
        prompt = _build_market_prompt({}, {})
        assert "매매 권유 금지" in prompt
