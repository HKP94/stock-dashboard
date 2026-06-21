from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from src.local_api import (
    ManualResearchConsensusPatch,
    ManualResearchHorizonPatch,
    ManualResearchPointPatch,
    _manual_research_summary,
    _patch_manual_research_horizon,
    _patch_manual_research_point,
    _upsert_manual_research_consensus,
)


def _conn(rowcount=1, fetchone=None):
    conn = MagicMock()
    cursor = MagicMock()
    cursor.rowcount = rowcount
    cursor.fetchone.return_value = fetchone
    conn.cursor.return_value = cursor
    return conn, cursor


def test_manual_research_summary_is_thin_and_non_aggregated():
    entry = {
        "id": 11,
        "horizons": [
            {"horizon": "short", "attractivenessLabel": "다소 매력적"},
            {"horizon": "mid", "attractivenessLabel": "중립"},
            {"horizon": "long", "attractivenessLabel": "비매력적"},
        ],
        "bull": [{"point": "수주 확대"}],
        "bear": [{"point": "마진 압박"}, {"point": "밸류 부담"}],
    }
    summary = _manual_research_summary(entry)
    assert summary == {
        "entryId": 11,
        "labels": {"short": "다소 매력적", "mid": "중립", "long": "비매력적"},
        "bullCount": 1,
        "bearCount": 2,
    }
    assert "score" not in summary


def test_patch_manual_research_horizon_marks_user_confirmed():
    conn, cursor = _conn()
    changed = _patch_manual_research_horizon(
        conn,
        9,
        "mid",
        ManualResearchHorizonPatch(attractiveness_label="중립", rationale="실적 가시성 제한"),
    )
    assert changed == {"attractiveness_label": "중립", "rationale": "실적 가시성 제한"}
    executed = cursor.execute.call_args.args[0]
    params = cursor.execute.call_args.args[1]
    assert "is_user_confirmed=TRUE" in executed
    assert params[-2:] == (9, "mid")
    conn.commit.assert_called_once()


def test_patch_manual_research_point_validates_stance_and_marks_confirmed():
    conn, cursor = _conn(fetchone={"entry_id": 7})
    changed = _patch_manual_research_point(conn, 4, ManualResearchPointPatch(stance="bear", point="수요 둔화"))
    assert changed["stance"] == "bear"
    assert changed["point"] == "수요 둔화"
    assert changed["entry_id"] == 7
    sql = cursor.execute.call_args.args[0]
    assert "is_user_confirmed=TRUE" in sql
    conn.commit.assert_called_once()


def test_patch_manual_research_point_rejects_bad_stance():
    conn, _cursor = _conn(fetchone={"entry_id": 7})
    with pytest.raises(HTTPException):
        _patch_manual_research_point(conn, 4, ManualResearchPointPatch(stance="sideways"))


def test_upsert_manual_research_consensus_marks_user_confirmed():
    conn, cursor = _conn()
    changed = _upsert_manual_research_consensus(
        conn,
        5,
        ManualResearchConsensusPatch(target_price=123000, rating_label="매수"),
    )
    assert changed == {"target_price": 123000.0, "rating_label": "매수", "rating_score": None}
    sql = cursor.execute.call_args.args[0]
    assert "is_user_confirmed = TRUE" in sql
    conn.commit.assert_called_once()
