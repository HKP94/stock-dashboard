from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db import replace_manual_research_ai_rows
from src.enrich_gemini import _parse_manual_research_output


class FakeCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple | list[tuple]]] = []

    def execute(self, sql: str, params: tuple) -> None:
        self.executed.append((" ".join(sql.split()), params))

    def executemany(self, sql: str, params_seq: list[tuple]) -> None:
        self.executed.append((" ".join(sql.split()), params_seq))

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class FakeConnection:
    def __init__(self) -> None:
        self.cur = FakeCursor()

    def cursor(self) -> FakeCursor:
        return self.cur


def test_parse_manual_research_output_returns_three_horizons_and_both_stances() -> None:
    payload = _parse_manual_research_output(json.dumps({
        "inferredSource": "메리츠증권",
        "consensus": {"targetPrice": 120000, "ratingLabel": "매수", "ratingScore": 1.0},
        "bullPoints": [{"point": "HBM 수요 확대", "sourceLabel": "메리츠증권", "sourceUrl": "https://example.com/bull"}],
        "bearPoints": [{"point": "단기 밸류 부담", "sourceLabel": "메리츠증권", "sourceUrl": "https://example.com/bear"}],
        "horizons": [
            {"horizon": "short", "attractivenessLabel": "다소 매력적", "rationale": "단기 실적 개선 기대"},
            {"horizon": "mid", "attractivenessLabel": "매력적", "rationale": "중기 제품 믹스 개선"},
            {"horizon": "long", "attractivenessLabel": "중립", "rationale": "장기 경쟁 심화 가능성"},
        ],
    }, ensure_ascii=False))

    assert [item.horizon for item in payload.horizons] == ["short", "mid", "long"]
    assert payload.bear_points[0].point == "단기 밸류 부담"
    assert payload.consensus is not None
    assert payload.consensus.targetPrice == 120000


def test_replace_manual_research_ai_rows_keeps_user_confirmed_records() -> None:
    conn = FakeConnection()
    replace_manual_research_ai_rows(conn, entry_id=9, horizons=[], points=[], consensus=None)

    assert conn.cur.executed[0][1] == (9,)
    assert "DELETE FROM manual_research_horizons WHERE entry_id=%s AND is_user_confirmed=FALSE" in conn.cur.executed[0][0]
    assert "DELETE FROM manual_research_points WHERE entry_id=%s AND is_user_confirmed=FALSE" in conn.cur.executed[1][0]
    assert "DELETE FROM manual_research_consensus WHERE entry_id=%s AND is_user_confirmed=FALSE" in conn.cur.executed[2][0]
