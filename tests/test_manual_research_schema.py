from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.schemas import ManualResearchHorizonRow


def test_manual_research_horizon_requires_label_not_numeric() -> None:
    row = ManualResearchHorizonRow(
        entry_id=1,
        horizon="short",
        attractiveness_label="매력적",
        rationale="실적 모멘텀이 3개월 내 개선될 가능성을 언급했다.",
    )

    assert row.attractiveness_label == "매력적"


def test_schema_declares_manual_research_tables() -> None:
    schema = Path("db/schema.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS manual_research_entries" in schema
    assert "CREATE TABLE IF NOT EXISTS manual_research_horizons" in schema
    assert "CREATE TABLE IF NOT EXISTS manual_research_points" in schema
    assert "CREATE TABLE IF NOT EXISTS manual_research_consensus" in schema
    assert "CREATE TABLE IF NOT EXISTS market_view_manual" in schema
