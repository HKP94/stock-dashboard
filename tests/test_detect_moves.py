"""detect_moves(신규-G) 단위 테스트 — 감지 게이트·지수대비 태그·귀인 4분류.

DB 없이: 순수 함수 _classify + 모듈 헬퍼 몽키패치로 detect_for_ticker 검증.
결정론·§F7(트레일링 σ)·§2(방향 불일치 뉴스는 원인 미인정).
"""
from datetime import date, timedelta

import pytest

from src import detect_moves as dm

ASOF = date(2026, 7, 10)


# ── _classify: 4분류 축 ───────────────────────────────────────────
def _curated(cat, direction, impact, insight="근거"):
    return {"title": f"{cat} 뉴스", "url": "http://x", "category": cat,
            "direction": direction, "impact_score": impact, "insight": insight}


def test_classify_value_event():
    news = {"curated": [_curated("실적", "호재", 85)], "based_on": "recent", "n_articles": 5, "sentiment": "긍정"}
    r = dm._classify(news, None, "급등")
    assert r["attribution_class"] == dm.CLASS_VALUE
    assert r["explained"] is True and r["sources"]


def test_classify_info_fundamental():
    news = {"curated": [_curated("제품·기술", "호재", 80)], "based_on": "recent", "n_articles": 3}
    r = dm._classify(news, None, "급등")
    assert r["attribution_class"] == dm.CLASS_INFO


def test_classify_flow_driven():
    flow = {"combined_signal": "수급_강세", "foreign_net": 1e10, "institution_net": 2e9}
    r = dm._classify(None, flow, "급등")
    assert r["attribution_class"] == dm.CLASS_FLOW
    assert r["explained"] is True


def test_classify_sentiment_soft():
    news = {"curated": [], "based_on": "recent", "n_articles": 4, "sentiment": "부정"}
    r = dm._classify(news, None, "급락")
    assert r["attribution_class"] == dm.CLASS_FLOW


def test_classify_unknown_when_no_signal():
    news = {"curated": [], "based_on": "fallback_old", "n_articles": 0, "sentiment": "중립"}
    r = dm._classify(news, {"combined_signal": "수급_혼조"}, "급등")
    assert r["attribution_class"] == dm.CLASS_UNKNOWN
    assert r["explained"] is False


def test_classify_direction_mismatch_not_attributed():
    # 호재 고영향 뉴스지만 급락 → 인과 위조 금지, 뉴스 원인 미인정(수급·심리 없으면 이유 불명)
    news = {"curated": [_curated("M&A·계약", "호재", 90)], "based_on": "recent", "n_articles": 5, "sentiment": "긍정"}
    r = dm._classify(news, None, "급락")
    assert r["attribution_class"] == dm.CLASS_UNKNOWN


def test_classify_neutral_news_allowed():
    news = {"curated": [_curated("규제·정책", "중립", 75)], "based_on": "recent", "n_articles": 3}
    r = dm._classify(news, None, "급락")
    assert r["attribution_class"] == dm.CLASS_VALUE  # 중립은 방향 무해 → 인정


def test_classify_pending_when_summary_failed_but_articles_exist():
    # Gemini 요약 실패(fallback_old)지만 n_articles>0 → '요약 대기'(이유 불명 아님)
    news = {"curated": [], "based_on": "fallback_old", "n_articles": 12, "sentiment": "중립"}
    r = dm._classify(news, {"combined_signal": "수급_혼조"}, "급등")
    assert r["attribution_class"] == dm.CLASS_PENDING
    assert r["explained"] is True


def test_classify_pending_via_raw_titles_when_no_analysis():
    # news_analysis 자체가 없어도 원문 뉴스 제목이 있으면 '요약 대기'
    raw = [{"title": "대형 수주 계약 체결", "url": "http://x"}]
    r = dm._classify(None, None, "급등", raw_titles=raw)
    assert r["attribution_class"] == dm.CLASS_PENDING
    assert any(s.get("title") == "대형 수주 계약 체결" for s in r["sources"])


def test_classify_unknown_only_when_truly_no_news():
    # 요약도 없고 n_articles=0이고 원문 제목도 없음 → 진짜 이유 불명
    news = {"curated": [], "based_on": "fallback_old", "n_articles": 0, "sentiment": "중립"}
    r = dm._classify(news, {"combined_signal": "수급_혼조"}, "급등", raw_titles=[])
    assert r["attribution_class"] == dm.CLASS_UNKNOWN
    assert r["explained"] is False


# ── detect_for_ticker: 감지 게이트·태그 ────────────────────────────
def _prices_from_returns(rets, start=1000.0):
    """일간수익률 리스트 → (date, close) 오름차순. 마지막 원소가 오늘 이동."""
    closes = [start]
    for r in rets:
        closes.append(closes[-1] * (1 + r))
    d0 = ASOF - timedelta(days=len(closes) - 1)
    return [(d0 + timedelta(days=i), c) for i, c in enumerate(closes)]


def _patch(monkeypatch, prices, r_idx=0.0, beta=1.0, news=None, flow=None, raw=None):
    monkeypatch.setattr(dm, "_load_recent_prices", lambda c, t, lim, asof: [p for p in prices if p[0] <= asof])
    monkeypatch.setattr(dm, "_index_return", lambda c, code, d: r_idx)
    monkeypatch.setattr(dm, "_latest_beta", lambda c, t: beta)
    monkeypatch.setattr(dm, "_load_news", lambda c, t, d: news)
    monkeypatch.setattr(dm, "_load_flow", lambda c, t, d: flow)
    monkeypatch.setattr(dm, "_load_raw_news", lambda c, t, d, limit=3: raw or [])


def test_gate_absolute_leg_high_vol(monkeypatch):
    # 고변동주(σ 큼): 마지막 +7% (z 낮아도 절대 leg로 감지)
    rets = [0.05 if i % 2 else -0.05 for i in range(60)] + [0.07]
    _patch(monkeypatch, _prices_from_returns(rets), r_idx=0.0)
    r = dm.detect_for_ticker(None, "X.KS", "KR", ASOF)
    assert r is not None and r["direction"] == "급등"
    assert abs(r["z_score"]) < dm.Z_MAIN and r["unusual"] is False  # 절대 leg


def test_gate_zscore_leg_low_vol(monkeypatch):
    # 저변동주(σ 작음): 마지막 +4.5% (절대 6% 미만이나 z 이례적)
    rets = [0.002 * (1 if i % 2 else -1) for i in range(60)] + [0.045]
    _patch(monkeypatch, _prices_from_returns(rets), r_idx=0.0)
    r = dm.detect_for_ticker(None, "X.KS", "KR", ASOF)
    assert r is not None and r["unusual"] is True


def test_gate_below_threshold_none(monkeypatch):
    rets = [0.002 * (1 if i % 2 else -1) for i in range(60)] + [0.03]  # 3% < floor 4%
    _patch(monkeypatch, _prices_from_returns(rets), r_idx=0.0)
    assert dm.detect_for_ticker(None, "X.KS", "KR", ASOF) is None


def test_idiosyncratic_vs_market_driven(monkeypatch):
    rets = [0.05 if i % 2 else -0.05 for i in range(60)] + [0.08]
    # 지수도 크게 동반 상승(β·idx가 이동 대부분 설명) → market_driven
    _patch(monkeypatch, _prices_from_returns(rets), r_idx=0.08, beta=1.0)
    r = dm.detect_for_ticker(None, "X.KS", "KR", ASOF)
    assert r["idiosyncratic"] is False
    # 지수 잔잔 → 자체 이동
    _patch(monkeypatch, _prices_from_returns(rets), r_idx=0.0, beta=1.0)
    r2 = dm.detect_for_ticker(None, "X.KS", "KR", ASOF)
    assert r2["idiosyncratic"] is True


def test_recency_guard_skips_stale(monkeypatch):
    rets = [0.05 if i % 2 else -0.05 for i in range(60)] + [0.08]
    prices = _prices_from_returns(rets)
    # 최신 종가를 오래 전으로: asof를 훨씬 뒤로 두면 recency 초과
    late = ASOF + timedelta(days=dm.RECENCY_DAYS + 5)
    _patch(monkeypatch, prices, r_idx=0.0)
    assert dm.detect_for_ticker(None, "X.KS", "KR", late) is None
