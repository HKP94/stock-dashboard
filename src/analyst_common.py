from __future__ import annotations

from typing import Optional


_BUY_MARKERS = ("strong buy", "buy", "매수", "outperform", "overweight")
_NEUTRAL_MARKERS = ("hold", "neutral", "중립", "market perform", "equal weight")
_SELL_MARKERS = ("sell", "underperform", "underweight", "reduce", "매도", "축소")


def normalize_rating_label_score(raw: Optional[str]) -> tuple[Optional[str], Optional[float]]:
    if not raw:
        return None, None
    text = str(raw).strip().lower()
    if any(marker in text for marker in _BUY_MARKERS):
        return "매수", 1.0
    if any(marker in text for marker in _SELL_MARKERS):
        return "매도", -1.0
    if any(marker in text for marker in _NEUTRAL_MARKERS):
        return "중립", 0.0
    return str(raw).strip(), None
