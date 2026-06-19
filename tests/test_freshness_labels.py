from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.export_dashboard_data import _infer_refresh_context


def test_infer_refresh_context_marks_kr_close_when_kr_date_is_newer() -> None:
    info = _infer_refresh_context(
        datetime(2026, 6, 19, 18, 5),
        {"KR": "2026-06-19", "US": "2026-06-18"},
    )

    assert info["mode"] == "kr_close"
    assert info["label"] == "한국 종가 기준 (18시 갱신)"
    assert "US 가격은 전날 종가" in info["note"]


def test_infer_refresh_context_marks_us_close_when_dates_match() -> None:
    info = _infer_refresh_context(
        datetime(2026, 6, 20, 6, 10),
        {"KR": "2026-06-19", "US": "2026-06-19"},
    )

    assert info["mode"] == "us_close"
    assert info["label"] == "미국 종가 기준 (06시 갱신)"


def test_workflows_keep_06_and_18_kst_cron_slots() -> None:
    auto_run = Path(".github/workflows/auto_run.yml").read_text(encoding="utf-8")
    news_refresh = Path(".github/workflows/news_refresh.yml").read_text(encoding="utf-8")

    assert "0 21 * * *" in auto_run
    assert "0 9 * * *" in news_refresh
