"""KB 수급 통합(auto 폴백) 회귀 가드.

핵심 계약 3가지:
  1) 소스가 바뀌어도 하류가 보는 값·신호가 동일하다(스키마·3분류 무변경).
  2) auto = KB 우선 → 실패/0건이면 pykrx 폴백. pykrx 지정 시 KB를 아예 부르지 않는다.
  3) KB 관례차(×1e6·외국인=fgnr+ntv_fgnr·확정치만·미집계 placeholder 제외)가 적용된다.

전부 모킹 — 실호출·실DB 없음.
"""
from __future__ import annotations

from datetime import date

import pytest

from src import ingest_investor_flow as ifl
from src.kb_supply import parse_supply_records


def _kb_rec(dt: str, fgnr: int, ntv: int, ogn: int, indv: int, mtrl: str = "0") -> dict:
    """KB IVU10430 out 레코드(금액=백만원 문자열)."""
    return {"mtrl_clsf": mtrl, "dt": dt, "cls_prc": "70000",
            "fgnr": str(fgnr), "ntv_fgnr": str(ntv), "ogn": str(ogn), "indv": str(indv)}


class TestKbParsingConventions:
    def test_unit_and_foreign_definition(self):
        rows = parse_supply_records([_kb_rec("20260806", -1_693_585, 16_486, -422_181, 2_039_284)])
        r = rows[date(2026, 8, 6)]
        assert r["foreign"] == (-1_693_585 + 16_486) * 1_000_000   # ≡ pykrx 외국인합계
        assert r["institution"] == -422_181 * 1_000_000
        assert r["individual"] == 2_039_284 * 1_000_000

    def test_estimates_excluded(self):
        rows = parse_supply_records([_kb_rec("20260807", 1, 0, 1, -2, mtrl="1")])
        assert rows == {}

    def test_all_zero_placeholder_excluded(self):
        """KB는 미집계 당일 봉도 확정치 플래그로 0을 내려보낸다 — 적재 금지."""
        recs = [_kb_rec("20260806", 100, 0, -50, -50), _kb_rec("20260807", 0, 0, 0, 0)]
        assert set(parse_supply_records(recs)) == {date(2026, 8, 6)}

    def test_partial_zero_row_kept(self):
        """개별 투자자 0은 실제로 생긴다 — 세 값이 동시에 0일 때만 버린다."""
        rows = parse_supply_records([_kb_rec("20260806", 0, 0, 500, -500)])
        assert set(rows) == {date(2026, 8, 6)}


DAILY = {
    date(2026, 8, 4): (100.0, -40.0, -60.0),
    date(2026, 8, 5): (200.0, -50.0, -150.0),
    date(2026, 8, 6): (-300.0, 80.0, 220.0),
}


class TestBuildRowsSourceAgnostic:
    def test_signals_and_3d_sums(self):
        rows = ifl._build_rows("005930.KS", DAILY)
        assert [r.date for r in rows] == sorted(DAILY)
        last = rows[-1]
        assert last.foreign_3d_sum == pytest.approx(100 + 200 - 300)
        assert last.institution_3d_sum == pytest.approx(-40 - 50 + 80)
        assert last.foreign_signal == "중립"        # 합계 0
        assert last.institution_signal == "매도우세"  # 합계 -10

    def test_zero_stored_as_none(self):
        """기존 계약 유지 — 0은 None으로 저장(하류 무변경)."""
        rows = ifl._build_rows("X.KS", {date(2026, 8, 6): (0.0, 5.0, -5.0)})
        assert rows[0].foreign_net is None and rows[0].institution_net == 5.0

    def test_identical_rows_regardless_of_source(self, monkeypatch):
        """★같은 일별 값이면 KB 경로와 pykrx 경로의 산출물이 완전히 같아야 한다."""
        monkeypatch.setattr(ifl, "_fetch_kb", lambda *a: dict(DAILY))
        monkeypatch.setattr(ifl, "_fetch_pykrx", lambda *a: dict(DAILY))
        from src import kb_client
        monkeypatch.setattr(kb_client, "kb_enabled", lambda: True)

        via_kb = ifl.fetch_investor_flow("005930.KS", source="kb")
        via_pykrx = ifl.fetch_investor_flow("005930.KS", source="pykrx")
        assert [r.model_dump() for r in via_kb] == [r.model_dump() for r in via_pykrx]


class TestSourceSwitch:
    @pytest.fixture(autouse=True)
    def _stub(self, monkeypatch):
        self.calls = []
        from src import kb_client
        monkeypatch.setattr(kb_client, "kb_enabled", lambda: True)
        monkeypatch.setattr(ifl, "_fetch_kb",
                            lambda *a: (self.calls.append("kb"), dict(DAILY))[1])
        monkeypatch.setattr(ifl, "_fetch_pykrx",
                            lambda *a: (self.calls.append("pykrx"), dict(DAILY))[1])
        yield

    def test_auto_prefers_kb(self, monkeypatch):
        assert ifl.fetch_investor_flow("005930.KS", source="auto")
        assert self.calls == ["kb"]          # pykrx 미호출

    def test_auto_falls_back_when_kb_raises(self, monkeypatch):
        def boom(*a):
            self.calls.append("kb")
            raise RuntimeError("KB 500")
        monkeypatch.setattr(ifl, "_fetch_kb", boom)
        assert ifl.fetch_investor_flow("005930.KS", source="auto")
        assert self.calls == ["kb", "pykrx"]

    def test_auto_falls_back_when_kb_empty(self, monkeypatch):
        monkeypatch.setattr(ifl, "_fetch_kb", lambda *a: (self.calls.append("kb"), {})[1])
        assert ifl.fetch_investor_flow("005930.KS", source="auto")
        assert self.calls == ["kb", "pykrx"]

    def test_pykrx_mode_never_calls_kb(self):
        assert ifl.fetch_investor_flow("005930.KS", source="pykrx")
        assert self.calls == ["pykrx"]

    def test_kb_mode_never_falls_back(self, monkeypatch):
        """kb 고정이면 실패해도 pykrx로 새지 않는다(진단 가능하게)."""
        def boom(*a):
            self.calls.append("kb")
            raise RuntimeError("KB 500")
        monkeypatch.setattr(ifl, "_fetch_kb", boom)
        assert ifl.fetch_investor_flow("005930.KS", source="kb") == []
        assert self.calls == ["kb"]

    def test_auto_without_kb_keys_uses_pykrx(self, monkeypatch):
        from src import kb_client
        monkeypatch.setattr(kb_client, "kb_enabled", lambda: False)
        assert ifl.fetch_investor_flow("005930.KS", source="auto")
        assert self.calls == ["pykrx"]


def test_krx_login_not_called_on_kb_path(monkeypatch):
    """적시성: KB가 처리하면 KRX 로그인 왕복이 아예 없어야 한다."""
    from src import kb_client
    monkeypatch.setattr(kb_client, "kb_enabled", lambda: True)
    monkeypatch.setattr(ifl, "_fetch_kb", lambda *a: dict(DAILY))
    called = []
    monkeypatch.setattr(ifl, "_ensure_krx_session", lambda: called.append(1))
    ifl.fetch_investor_flow("005930.KS", source="auto")
    assert called == []
