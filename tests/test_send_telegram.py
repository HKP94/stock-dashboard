from __future__ import annotations

from datetime import date

from src.send_telegram import format_brief


def test_brief_omits_disclaimer_boilerplate() -> None:
    text = format_brief([], asof=date(2026, 6, 19))
    assert "투자 자문" not in text
    assert "원금 손실" not in text
