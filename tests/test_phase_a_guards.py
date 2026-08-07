"""Phase A 중대 3건 회귀 가드 (A①·A②·A③).

전부 표시·판단 경로의 결함이었고, 공통점은 "값은 맞는데 그 값을 믿을 자격을 안 따진 것"이다.
"""
from __future__ import annotations

import re
from pathlib import Path

from src.stock_action_advice import derive_grade

ROOT = Path(__file__).resolve().parents[1]


# ── A①: 모멘텀 픽 추세 게이트 ────────────────────────────────────────────────
class TestMomentumPickGate:
    """#90 추세게이트가 4상한에만 붙어 있어 '모멘텀 픽'은 붕괴 종목을 1위로 올렸다.
    실측(2026-08-08): 상위 9개 중 7개가 broken(효성 100·고점比 -38%가 1위)."""

    SRC = ROOT / "dashboard-web/src/tabsB.jsx"

    def test_pick_sorts_broken_last(self):
        src = self.SRC.read_text(encoding="utf-8")
        m = re.search(r"const momentum = \[\.\.\.D\.stocks\]([\s\S]{0,220}?)\.slice\(0, 9\)", src)
        assert m, "모멘텀 픽 정렬식을 찾지 못함"
        expr = m.group(1)
        assert "isBroken(a) - isBroken(b)" in expr, "붕괴 종목 강등이 정렬에 없다"
        assert "b.f.m - a.f.m" in expr, "모멘텀 내림차순 기준이 사라졌다"

    def test_pick_shows_trend_badge(self):
        src = self.SRC.read_text(encoding="utf-8")
        pick = src[src.index("모멘텀 픽"): src.index("모멘텀 픽") + 2400]
        assert "MomoTrendBadge" in pick, "픽 표에 추세 배지가 없다 — 강등만 하고 이유를 안 보여주면 안 된다"

    def test_factor_value_untouched(self):
        """§2 레이어 분리: 게이트는 픽 레이어에만. 팩터 값 자체를 깎으면 안 된다."""
        src = self.SRC.read_text(encoding="utf-8")
        assert not re.search(r"f\.m\s*[*\-]\s*0?\.\d", src), "팩터 값에 감점을 먹이고 있다"


# ── A②·A③: 등급 산정의 신뢰 자격 ────────────────────────────────────────────
def _stock(**kw):
    base = {"comp": 69.0, "up": 128.6, "note": {}, "flags": [], "consensusStale": None}
    base.update(kw)
    return base


class TestFallbackCompositeGrade:
    """사전필터 탈락(fallback) 종합점수로 '매수·신뢰도 상'이 뜨던 문제(하이닉스 등 5종목)."""

    def test_fallback_blocks_strong_quant(self):
        plain = derive_grade(_stock())
        fb = derive_grade(_stock(flags=["사전필터 제외", "fallback"]))
        assert plain[0] == "매수" and plain[1] == "상"
        assert fb[0] == "관망", fb          # 강 승격 차단 → 축이 하나만 강 → 관망
        assert fb[2]["axes"]["quant"] == "중"
        assert fb[2]["fallbackAdjust"]["applied"] is True

    def test_axis_not_dropped(self):
        """★제외가 아니라 강등이다 — 축을 지우면 정보를 버리고 '관망·하'로 뭉개진다."""
        fb = derive_grade(_stock(flags=["fallback"]))
        assert fb[2]["axes"]["quant"] is not None
        assert fb[2]["present"] >= 2

    def test_weak_quant_unaffected(self):
        """비대칭 — 약한 축은 건드리지 않는다(하방 민감 유지)."""
        weak = derive_grade(_stock(comp=20.0, up=2.0, flags=["fallback"]))
        assert weak[0] == "축소"
        assert weak[2]["fallbackAdjust"] is None

    def test_normal_stock_unchanged(self):
        """fallback이 아닌 종목은 완전 불변(회귀 0)."""
        assert derive_grade(_stock()) == derive_grade(_stock(flags=["목표가 근접 (4.2%)"]))


class TestStaleConsensusGrade:
    """목표가가 오래 안 바뀐 채 괴리만 극단이면 '강한 상승여력'이 아니라 갱신 안 된 값이다."""

    def test_stale_blocks_strong_consensus(self):
        fresh = derive_grade(_stock(comp=50.0, up=76.5))
        stale = derive_grade(_stock(comp=50.0, up=76.5, consensusStale={"stale": True}))
        assert fresh[2]["axes"]["consensus"] == "강"
        assert stale[2]["axes"]["consensus"] == "중"
        assert stale[2]["staleConsensusAdjust"]["applied"] is True

    def test_not_stale_unchanged(self):
        a = derive_grade(_stock(comp=50.0, up=76.5))
        b = derive_grade(_stock(comp=50.0, up=76.5, consensusStale={"stale": False}))
        assert a == b


class TestConsensusStaleDetection:
    """export의 정체 판정 — 미갱신과 극단 괴리를 **둘 다** 충족할 때만 표식."""

    def test_requires_both_conditions(self):
        from src.export_dashboard_data import _consensus_stale

        info = {"samples": 28, "uniqTargets": 1, "since": "2026-06-24", "last": "2026-08-07"}
        assert _consensus_stale(info, 76.5)["stale"] is True
        assert _consensus_stale(info, 3.0) is None      # 미갱신이나 괴리 정상 → 표식 안 함
        assert _consensus_stale(None, 200.0) is None    # 괴리 극단이나 갱신되고 있음

    def test_negative_extreme_also_flagged(self):
        from src.export_dashboard_data import _consensus_stale

        info = {"samples": 28, "uniqTargets": 1, "since": "2026-06-24", "last": "2026-08-07"}
        assert _consensus_stale(info, -80.0)["stale"] is True
