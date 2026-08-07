"""SMA 배선 회귀 가드 (A-1).

export가 지표를 **저장값(indicators_daily)에서 읽는지** 강제한다.
과거엔 `_sma(ser, N)`으로 재계산했는데 `ser`가 `LIMIT 130`행이라 `sma200`이 구조적으로
항상 None이었고, 화면 SMA 칸이 영구히 '—'였다(DB엔 값이 멀쩡히 있었다).
atr14 사고(§8-1 "계산 코드가 있다 ≠ 값이 저장된다")와 동형이라 같은 방식으로 고정한다.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT / "src/export_dashboard_data.py"


def test_indicators_query_selects_sma_columns():
    """지표 로더 SQL이 sma20/50/200을 실어야 한다 — 안 실으면 값이 없다."""
    src = EXPORT.read_text(encoding="utf-8")
    # 중간에 다른 FROM이 끼지 않는 블록만 매칭(파일에 DISTINCT ON 쿼리가 여러 개다)
    m = re.search(r"SELECT DISTINCT ON \(ticker\)((?:(?!FROM).)*?)FROM indicators_daily", src, re.S)
    assert m, "indicators_daily 로더 쿼리를 찾지 못함"
    cols = m.group(1)
    for col in ("sma20", "sma50", "sma200"):
        assert col in cols, f"{col}이 indicators_daily SELECT에 없다"


def test_export_does_not_recompute_sma_from_truncated_series():
    """짧은 시리즈 재계산 경로(_sma 헬퍼)가 되살아나면 실패."""
    src = EXPORT.read_text(encoding="utf-8")
    assert "def _sma(" not in src, "재계산 헬퍼 _sma가 되살아났다(저장값을 읽어야 한다)"
    # 주석 언급은 허용하되 실제 호출은 금지
    calls = re.findall(r"^[^#\n]*[^_\w]_sma\(", src, re.M)
    assert not calls, f"_sma 호출이 남아 있다: {calls}"


def test_sma_fields_read_from_ind_map():
    """세 필드 모두 ind(저장값) 경유여야 한다."""
    src = EXPORT.read_text(encoding="utf-8")
    for col in ("sma20", "sma50", "sma200"):
        assert re.search(rf'{col}\s*=\s*_f\(ind\.get\("{col}"\)\)', src), f"{col} 배선 없음"


def test_frontend_labels_match_fields():
    """라벨과 실필드가 어긋나면 안 된다(과거: SMA 60↔sma50, SMA 120↔sma200)."""
    tabs = (ROOT / "dashboard-web/src/tabsA.jsx").read_text(encoding="utf-8")
    for label, field in (("SMA 20", "sma20"), ("SMA 50", "sma50"), ("SMA 200", "sma200")):
        assert f'["{label}", s.{field}]' in tabs, f"{label} ↔ s.{field} 정합 깨짐"
