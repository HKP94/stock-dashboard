from __future__ import annotations


def _row(ticker: str, composite: float | None, **factors: float) -> dict:
    return {
        "ticker": ticker,
        "composite": composite,
        "momentum": factors.get("momentum"),
        "value": factors.get("value"),
        "quality": factors.get("quality"),
        "growth": factors.get("growth"),
        "sentiment": factors.get("sentiment"),
    }


def test_top_middle_bottom_labels_include_reason_and_confidence() -> None:
    from src.display_signals import compute_display_signals

    signals = compute_display_signals([
        _row("A", 90, momentum=80),
        _row("B", 60, quality=75),
        _row("C", 10, value=70),
    ])

    assert signals["A"].label == "매수"
    assert signals["B"].label == "관망"
    assert signals["C"].label == "축소"
    for signal in signals.values():
        assert signal is not None
        assert "백분위" in signal.reason
        assert 50 <= signal.confidence <= 100


def test_equal_composites_receive_equal_percentiles() -> None:
    from src.display_signals import compute_display_signals

    signals = compute_display_signals([_row("A", 70), _row("B", 70), _row("C", 20)])
    assert signals["A"].percentile == signals["B"].percentile


def test_missing_composite_has_no_signal() -> None:
    from src.display_signals import compute_display_signals

    assert compute_display_signals([_row("A", None)])["A"] is None


def test_single_valid_stock_is_watch_with_high_midpoint_confidence() -> None:
    from src.display_signals import compute_display_signals

    signal = compute_display_signals([_row("A", 50, growth=60)])["A"]
    assert signal.label == "관망"
    assert signal.percentile == 50.0
    assert signal.confidence == 100
