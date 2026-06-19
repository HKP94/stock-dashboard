from __future__ import annotations

from datetime import date

from src.export_dashboard_data import _build_macro_payload


def test_build_macro_payload_keeps_latest_per_indicator():
    rows = [
        {"indicator_code": "FEDFUNDS", "indicator_name": "미국 기준금리", "region": "US", "asof": date(2026, 5, 1), "value": 4.0, "unit": "%", "source": "fred"},
        {"indicator_code": "FEDFUNDS", "indicator_name": "미국 기준금리", "region": "US", "asof": date(2026, 6, 1), "value": 4.25, "unit": "%", "source": "fred"},
        {"indicator_code": "VIX", "indicator_name": "VIX", "region": "GLOBAL", "asof": date(2026, 6, 18), "value": 19.5, "unit": "pt", "source": "yfinance"},
        {"indicator_code": "VIX", "indicator_name": "VIX", "region": "GLOBAL", "asof": date(2026, 6, 19), "value": 18.0, "unit": "pt", "source": "yfinance"},
    ]

    summary = {
        "summary_date": date(2026, 6, 19),
        "headline": "거시 환경 요약",
        "support_view": "완화 기대",
        "oppose_view": "인플레 경계",
        "watch_points": ["연준 발언"],
        "summary_md": "- 요약",
    }

    out = _build_macro_payload(rows, summary)

    assert out["asof"] == "2026-06-19"
    assert out["summary"]["headline"] == "거시 환경 요약"
    indicators = {item["code"]: item for item in out["indicators"]}
    assert indicators["FEDFUNDS"]["value"] == 4.25
    assert indicators["VIX"]["value"] == 18.0
    assert indicators["FEDFUNDS"]["deltaMonth"] == 0.25


def test_build_macro_payload_uses_latest_summary_even_when_series_dates_differ():
    rows = [
        {"indicator_code": "KR_CPI", "indicator_name": "한국 CPI", "region": "KR", "asof": date(2026, 5, 1), "value": 116.2, "unit": "지수", "source": "ecos"},
        {"indicator_code": "USDKRW", "indicator_name": "원달러 환율", "region": "GLOBAL", "asof": date(2026, 6, 19), "value": 1360.0, "unit": "KRW", "source": "yfinance"},
    ]
    summary = {
        "summary_date": date(2026, 6, 19),
        "headline": "상충 신호",
        "support_view": "금리 안정",
        "oppose_view": "환율 부담",
        "watch_points": [],
        "summary_md": "- 요약",
    }

    out = _build_macro_payload(rows, summary)

    assert out["summary"]["oppose"] == "환율 부담"
    assert out["regions"]["KR"][0]["code"] == "KR_CPI"
