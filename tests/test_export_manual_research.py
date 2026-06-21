from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.export_dashboard_data import _build_ai_decomposition_summary


def test_ai_decomposition_summary_stays_non_numeric() -> None:
    summary = _build_ai_decomposition_summary({
        "id": 7,
        "horizons": [
            {"horizon": "short", "attractivenessLabel": "다소 매력적"},
            {"horizon": "mid", "attractivenessLabel": "중립"},
            {"horizon": "long", "attractivenessLabel": "비매력적"},
        ],
        "bull": [{"point": "A"}],
        "bear": [{"point": "B"}, {"point": "C"}],
    })

    assert summary == {
        "entryId": 7,
        "labels": {"short": "다소 매력적", "mid": "중립", "long": "비매력적"},
        "bullCount": 1,
        "bearCount": 2,
    }
