"""섹터-상대 팩터(추가 렌즈) 결정론 테스트 — 크로스섹터 왜곡 해소."""
from src.export_dashboard_data import _norm_sector, _attach_sector_relative, SECTOR_MIN_PEERS


def test_norm_sector_normalizes_messy_values():
    assert _norm_sector("insurance") == "Financials"
    assert _norm_sector("Fiance") == "Financials"        # 오타
    assert _norm_sector("Financials") == "Financials"
    assert _norm_sector("Semiconductors") == "Semiconductors"
    assert _norm_sector("Technology") == "InfoTech"
    assert _norm_sector("Bioindustry") == "Healthcare"
    assert _norm_sector("Petrochemistry") == "Energy/Chem"
    assert _norm_sector("bond") == "Other"               # 불명
    assert _norm_sector(None) == "Other"


def _mk(t, sec, q):
    return {"t": t, "name": t, "sec": sec, "f": {"m": 50, "v": 50, "q": q, "g": 50}}


def test_sector_relative_ranks_within_group_not_global():
    # 금융 5종(고value 클러스터) + 테크 5종. 각 그룹 내 백분위로 재순위.
    stocks = [_mk(f"FIN{i}", "Financials", q) for i, q in enumerate([10, 20, 30, 40, 90])]
    stocks += [_mk(f"TEC{i}", "Semiconductors", q) for i, q in enumerate([60, 70, 80, 88, 95])]
    _attach_sector_relative(stocks)
    fin = {s["t"]: s for s in stocks if s["sectorRel"]["group"] == "Financials"}
    # FIN4(글로벌 q=90)는 금융 내 최고 → 섹터내 q=100. FIN0(10)은 최저 → 0.
    assert fin["FIN4"]["sectorRel"]["q"] == 100.0
    assert fin["FIN0"]["sectorRel"]["q"] == 0.0
    # 글로벌 값은 불변(추가 렌즈)
    assert fin["FIN4"]["f"]["q"] == 90
    # 테크 그룹도 그룹 내 순위(글로벌 60이 테크 내 최저 → 0)
    tec = {s["t"]: s for s in stocks if s["sectorRel"]["group"] == "Semiconductors"}
    assert tec["TEC0"]["sectorRel"]["q"] == 0.0 and tec["TEC4"]["sectorRel"]["q"] == 100.0
    assert all(s["sectorRel"]["fallback"] is False for s in stocks)


def test_thin_sector_falls_back_to_global():
    stocks = [_mk("H1", "Healthcare", 30), _mk("H2", "Healthcare", 70)]  # n=2 < MIN_PEERS
    stocks += [_mk(f"F{i}", "Financials", 50) for i in range(SECTOR_MIN_PEERS)]  # eligible 채움
    _attach_sector_relative(stocks)
    h1 = next(s for s in stocks if s["t"] == "H1")
    assert h1["sectorRel"]["fallback"] is True
    assert h1["sectorRel"]["q"] == h1["f"]["q"] == 30      # 폴백=글로벌 값


def test_unknown_sector_falls_back():
    stocks = [_mk("X", "bond", 44)] + [_mk(f"F{i}", "Financials", 50) for i in range(SECTOR_MIN_PEERS)]
    _attach_sector_relative(stocks)
    x = next(s for s in stocks if s["t"] == "X")
    assert x["sectorRel"]["group"] == "Other" and x["sectorRel"]["fallback"] is True
    assert x["sectorRel"]["q"] == 44
