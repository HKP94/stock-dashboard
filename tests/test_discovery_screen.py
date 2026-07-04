"""발굴 스크린 결정론 스코어링 테스트(네트워크·DB 없음)."""
from src.discovery_screen import _pos, _percentiles, score_market


def test_pos_rejects_nonpositive():
    assert _pos(12.5) == 12.5
    assert _pos(0) is None       # 적자 PER=0 → 무효(저PER 오판 방지)
    assert _pos(-3) is None
    assert _pos(None) is None


def test_percentiles_higher_better():
    p = _percentiles([("a", 10), ("b", 20), ("c", 30)])
    assert p["a"] == 0.0 and p["c"] == 100.0 and p["b"] == 50.0


def test_percentiles_lower_better_inverts():
    # 저PER=고가치: 가장 낮은 10이 100
    p = _percentiles([("a", 10), ("b", 20), ("c", 30)], lower_better=True)
    assert p["a"] == 100.0 and p["c"] == 0.0


def test_percentiles_missing_excluded_single_neutral():
    p = _percentiles([("a", 5), ("b", None)])
    assert p == {"a": 50.0}          # 유효 1개 → 중립 50, None 제외


def test_score_market_completeness_guard():
    # r1: 3축 완비 → long_term_score 산출. r2: value(per/pbr)만 → 1축 → None.
    rows = [
        {"ticker": "FULL", "metrics": {"per": 10, "pbr": 1.0, "roe": 0.3, "growth": 0.2, "ret1y": 50}},
        {"ticker": "VALONLY", "metrics": {"per": 8, "pbr": 0.8, "roe": None, "growth": None, "ret1y": 10}},
    ]
    score_market(rows)
    full = next(r for r in rows if r["ticker"] == "FULL")
    valonly = next(r for r in rows if r["ticker"] == "VALONLY")
    assert full["long_term_score"] is not None       # 3축 → 유효
    assert valonly["long_term_score"] is None         # value 1축만 → None(인플레 차단)
    assert valonly["value"] is not None               # value 자체는 계산됨
    # 모멘텀점수 = 가격 모멘텀 percentile(단일 축, 프록시) — 둘 다 존재
    assert full["momentum_score"] is not None and valonly["momentum_score"] is not None
    assert full["metrics"]["n_long_axes"] == 3 and valonly["metrics"]["n_long_axes"] == 1
