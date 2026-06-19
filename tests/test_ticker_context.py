from __future__ import annotations

from datetime import date

from src.export_dashboard_data import _group_ticker_context_rows


def test_group_ticker_context_rows_keeps_recent_active_items_newest_first() -> None:
    rows = [
        {
            "id": 3,
            "ticker": "AAPL",
            "context_type": "report",
            "content": "리포트 메모",
            "source": "manual",
            "valid_from": date(2026, 6, 19),
            "valid_until": None,
            "created_at": "2026-06-19T09:00:00",
        },
        {
            "id": 2,
            "ticker": "AAPL",
            "context_type": "news_summary",
            "content": "최근 뉴스 요약",
            "source": "gemini_news_analysis",
            "valid_from": date(2026, 6, 18),
            "valid_until": None,
            "created_at": "2026-06-18T09:00:00",
        },
    ]

    grouped = _group_ticker_context_rows(rows, today=date(2026, 6, 19))

    assert [item["id"] for item in grouped["AAPL"]] == [3, 2]
    assert grouped["AAPL"][0]["typeLabel"] == "리포트"
    assert grouped["AAPL"][1]["typeLabel"] == "뉴스 요약"


def test_group_ticker_context_rows_excludes_expired_and_older_than_30_days() -> None:
    rows = [
        {
            "id": 1,
            "ticker": "AAPL",
            "context_type": "news_summary",
            "content": "만료된 항목",
            "source": "gemini_news_analysis",
            "valid_from": date(2026, 6, 1),
            "valid_until": date(2026, 6, 18),
            "created_at": "2026-06-18T09:00:00",
        },
        {
            "id": 2,
            "ticker": "AAPL",
            "context_type": "macro",
            "content": "너무 오래된 항목",
            "source": "manual",
            "valid_from": date(2026, 5, 10),
            "valid_until": None,
            "created_at": "2026-05-10T09:00:00",
        },
        {
            "id": 3,
            "ticker": "AAPL",
            "context_type": "driver",
            "content": "유효한 최근 항목",
            "source": "manual",
            "valid_from": date(2026, 6, 19),
            "valid_until": None,
            "created_at": "2026-06-19T09:00:00",
        },
    ]

    grouped = _group_ticker_context_rows(rows, today=date(2026, 6, 19))

    assert [item["id"] for item in grouped["AAPL"]] == [3]
