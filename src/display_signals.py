"""Deterministic, display-only stock signals. No order execution path."""

from __future__ import annotations

from typing import Optional

from src.schemas import TradeSignal


FACTOR_LABELS = {
    "momentum": "모멘텀",
    "value": "가치",
    "quality": "우량성",
    "growth": "성장",
    "sentiment": "심리",
}


def _confidence(label: str, percentile: float) -> int:
    if label == "매수":
        value = 50 + (percentile - 70) / 30 * 50
    elif label == "축소":
        value = 50 + (30 - percentile) / 30 * 50
    else:
        value = 50 + (20 - abs(percentile - 50)) / 20 * 50
    return round(max(50, min(100, value)))


def _reason(row: dict, percentile: float) -> str:
    if percentile >= 70:
        position = f"상위 {round(100 - percentile)}%"
    elif percentile <= 30:
        position = f"하위 {round(percentile)}%"
    else:
        position = "중간 구간"
    factors = [
        (name, float(row[key]))
        for key, name in FACTOR_LABELS.items()
        if row.get(key) is not None
    ]
    strongest = max(factors, key=lambda item: item[1]) if factors else None
    base = f"퀀트 종합 백분위 {round(percentile)}위({position})"
    return f"{base}, 강점 팩터는 {strongest[0]} {round(strongest[1])}점" if strongest else base


def compute_display_signals(rows: list[dict]) -> dict[str, Optional[TradeSignal]]:
    result: dict[str, Optional[TradeSignal]] = {row["ticker"]: None for row in rows}
    valid = [row for row in rows if row.get("composite") is not None]
    if not valid:
        return result

    ordered = sorted(valid, key=lambda row: float(row["composite"]))
    n = len(ordered)
    index = 0
    while index < n:
        end = index + 1
        score = float(ordered[index]["composite"])
        while end < n and float(ordered[end]["composite"]) == score:
            end += 1
        average_rank = ((index + 1) + end) / 2
        percentile = 50.0 if n == 1 else round((average_rank - 1) / (n - 1) * 100, 2)
        label = "매수" if percentile >= 70 else "축소" if percentile <= 30 else "관망"
        for row in ordered[index:end]:
            result[row["ticker"]] = TradeSignal(
                label=label,
                percentile=percentile,
                reason=_reason(row, percentile),
                confidence=_confidence(label, percentile),
            )
        index = end
    return result
