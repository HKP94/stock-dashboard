from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.local_api import MarketManualPatch


def test_market_manual_patch_requires_any_supported_field() -> None:
    with pytest.raises(ValidationError):
        MarketManualPatch()
