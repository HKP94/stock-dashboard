"""
tests/test_daily_brief.py — 오버뷰 요약 밴드 + 시장 매력도 (PR-1/PR-2)

순수 함수만 검증(DB·네트워크 없음).
"""

from __future__ import annotations

from src.export_dashboard_data import (
    _attach_market_attractiveness,
    _build_daily_brief,
    _short_line,
)


def _stock(t, name, comp, mk="US", up=None, flags=None, align=False, chg=1.0):
    return {"t": t, "name": name, "comp": comp, "mk": mk, "up": up,
            "flagsAction": flags or [], "align": align, "chg": chg, "hasData": True}


MARKET = {"overall": "bull",
          "indices": [{"k": "VIX", "v": "16.0"}],
          "kr": {"regime": "neutral", "summary": "KOSPI 4.6% 상승. 외국인 순매수."},
          "us": {"regime": "bull", "summary": "S&P500 강세. 연준 완화 기대."}}


class TestShortLine:
    def test_no_decimal_break(self):
        # 소수점에서 끊기지 않아야 한다
        assert _short_line("KOSPI 4.63% 상승. 다음 문장.") == "KOSPI 4.63% 상승"

    def test_empty(self):
        assert _short_line("") == ""

    def test_strips_bullet(self):
        assert _short_line("- 강세 흐름. 추가").startswith("강세")


class TestDailyBrief:
    def test_highlights_top_composite(self):
        stocks = [_stock("A", "에이", 80), _stock("B", "비", 70), _stock("C", "씨", 60), _stock("D", "디", 50)]
        b = _build_daily_brief(stocks, MARKET)
        names = [h["name"] for h in b["highlights"]]
        assert names == ["에이", "비", "씨"]  # 상위 3, composite 내림차순

    def test_no_single_combined_score(self):
        # 밴드는 축을 합산한 단일 점수를 만들지 않는다(키 부재 확인)
        b = _build_daily_brief([_stock("A", "에이", 80)], MARKET)
        assert "score" not in b and "total" not in b

    def test_caution_on_overheat_flag(self):
        stocks = [_stock("A", "에이", 80, flags=["RSI 과열 (78.0)"])]
        b = _build_daily_brief(stocks, MARKET)
        assert any("과열" in c["why"] for c in b["cautions"])

    def test_caution_on_consensus_overvalued(self):
        stocks = [_stock("A", "에이", 80, up=-15.0)]
        b = _build_daily_brief(stocks, MARKET)
        assert any("하회" in c["why"] for c in b["cautions"])

    def test_divergence_quant_high_consensus_low(self):
        stocks = [_stock("A", "에이", 70, up=0.2)]
        b = _build_daily_brief(stocks, MARKET)
        assert len(b["diverge"]) == 1 and "확인 필요" in b["diverge"][0]["why"]

    def test_diverge_excluded_from_highlights(self):
        stocks = [_stock("A", "에이", 70, up=0.2), _stock("B", "비", 65, up=30.0)]
        b = _build_daily_brief(stocks, MARKET)
        hi = {h["t"] for h in b["highlights"]}
        dv = {d["t"] for d in b["diverge"]}
        assert hi.isdisjoint(dv)  # 겹치지 않음

    def test_disclaimer_boilerplate_absent(self):
        b = _build_daily_brief([_stock("A", "에이", 80)], MARKET)
        assert "disclaimer" not in b


class TestMarketAttractiveness:
    def test_attaches_env_to_kr_us(self):
        m = {k: (dict(v) if isinstance(v, dict) else v) for k, v in MARKET.items()}
        stocks = [_stock("A", "에이", 70, mk="US", align=True, chg=1.0),
                  _stock("K", "케이", 60, mk="KR", align=True, chg=1.0)]
        _attach_market_attractiveness(m, stocks)
        assert m["kr"]["attractiveness"]["env"] in ("우호", "중립", "비우호")
        assert m["us"]["attractiveness"]["env"] in ("우호", "중립", "비우호")
        assert "VIX" in m["us"]["attractiveness"]["basis"]

    def test_bull_low_vix_high_breadth_favorable(self):
        m = {k: (dict(v) if isinstance(v, dict) else v) for k, v in MARKET.items()}
        stocks = [_stock(f"U{i}", f"u{i}", 70, mk="US", align=True, chg=1.0) for i in range(10)]
        _attach_market_attractiveness(m, stocks)
        # bull 레짐 + 정배열 100% + VIX 16 → 우호
        assert m["us"]["attractiveness"]["env"] == "우호"
