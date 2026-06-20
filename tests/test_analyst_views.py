from __future__ import annotations

import json
from datetime import date

from src.enrich_gemini import (
    _build_analyst_view_rows,
    _build_analyst_views_prompt,
    _merge_analyst_view_news_inputs,
    _parse_analyst_views_output,
)
from src.export_dashboard_data import _group_analyst_views_rows


VALID_ANALYST_VIEWS_JSON = json.dumps(
    {
        "bull": [
            {
                "point": "증권사는 메모리 업황 반등과 ASP 개선을 근거로 실적 상향을 봤다.",
                "source": "연합뉴스",
                "source_url": "https://example.com/bull",
            }
        ],
        "bear": [
            {
                "point": "일부 리포트 인용 기사에서는 단기 밸류 부담을 언급했다.",
                "source": "매일경제",
                "source_url": "https://example.com/bear",
            }
        ],
    },
    ensure_ascii=False,
)


def test_parse_analyst_views_output_accepts_bull_and_bear_lists():
    out = _parse_analyst_views_output(VALID_ANALYST_VIEWS_JSON)

    assert out.bull[0].source_url == "https://example.com/bull"
    assert out.bear[0].source == "매일경제"


def test_parse_analyst_views_output_drops_items_with_blank_url_instead_of_failing_whole_payload():
    out = _parse_analyst_views_output(
        json.dumps(
            {
                "bull": [
                    {"point": "유효한 강세 논거", "source": "연합뉴스", "source_url": "https://example.com/bull"},
                    {"point": "URL 없는 강세 논거", "source": "연합뉴스", "source_url": ""},
                ],
                "bear": [
                    {"point": "유효한 약세 논거", "source": "매경", "source_url": "https://example.com/bear"},
                    {"point": "URL 없는 약세 논거", "source": "매경", "source_url": ""},
                ],
            },
            ensure_ascii=False,
        )
    )

    assert [item.point for item in out.bull] == ["유효한 강세 논거"]
    assert [item.point for item in out.bear] == ["유효한 약세 논거"]


def test_build_analyst_view_rows_preserves_stance_and_source_url():
    parsed = _parse_analyst_views_output(VALID_ANALYST_VIEWS_JSON)

    rows = _build_analyst_view_rows(
        ticker="000660.KS",
        asof=date(2026, 6, 20),
        payload=parsed,
        news_items=[
            {"url": "https://example.com/bull", "source": "연합뉴스"},
            {"url": "https://example.com/bear", "source": "매일경제"},
        ],
    )

    assert [(row.stance, row.source_url) for row in rows] == [
        ("bull", "https://example.com/bull"),
        ("bear", "https://example.com/bear"),
    ]
    assert [row.source for row in rows] == ["연합뉴스", "매일경제"]


def test_build_analyst_view_rows_drops_placeholder_or_unknown_urls():
    parsed = _parse_analyst_views_output(
        json.dumps(
            {
                "bull": [
                    {"point": "실제 기사 근거", "source": "임의", "source_url": "https://example.com/bull"},
                    {"point": "플레이스홀더", "source": "임의", "source_url": "https://..."},
                ],
                "bear": [
                    {"point": "컨텍스트만 근거", "source": "gemini_news_analysis", "source_url": "gemini_news_analysis"},
                ],
            },
            ensure_ascii=False,
        )
    )

    rows = _build_analyst_view_rows(
        ticker="AAPL",
        asof=date(2026, 6, 20),
        payload=parsed,
        news_items=[{"url": "https://example.com/bull", "source": "Reuters"}],
    )

    assert len(rows) == 1
    assert rows[0].point == "실제 기사 근거"
    assert rows[0].source == "Reuters"


def test_group_analyst_views_rows_splits_bull_and_bear_by_ticker():
    grouped = _group_analyst_views_rows(
        [
            {
                "ticker": "ALB",
                "stance": "bull",
                "point": "리튬 가격 안정화 수혜",
                "source": "Reuters",
                "source_url": "https://example.com/1",
                "asof": date(2026, 6, 20),
            },
            {
                "ticker": "ALB",
                "stance": "bear",
                "point": "단기 재고 부담",
                "source": "Barrons",
                "source_url": "https://example.com/2",
                "asof": date(2026, 6, 19),
            },
        ]
    )

    assert grouped["ALB"]["bull"][0]["sourceUrl"] == "https://example.com/1"
    assert grouped["ALB"]["bear"][0]["point"] == "단기 재고 부담"


def test_merge_analyst_view_news_inputs_forces_negative_risk_articles_in():
    analyst_items = [
        {"url": f"https://example.com/a{i}", "title": f"긍정 기사 {i}", "source": "naver"}
        for i in range(10)
    ]
    risk_items = [
        {"url": "https://example.com/risk1", "title": "부정 기사 1", "source": "google_news"},
        {"url": "https://example.com/risk2", "title": "부정 기사 2", "source": "google_news"},
    ]

    merged = _merge_analyst_view_news_inputs(analyst_items, risk_items, limit=10)

    urls = [item["url"] for item in merged]
    assert "https://example.com/risk1" in urls
    assert "https://example.com/risk2" in urls
    assert len(merged) == 10


def test_merge_analyst_view_news_inputs_deduplicates_urls():
    analyst_items = [
        {"url": "https://example.com/shared", "title": "애널 기사", "source": "naver"},
        {"url": "https://example.com/a2", "title": "애널 기사2", "source": "naver"},
    ]
    risk_items = [
        {"url": "https://example.com/shared", "title": "공유 리스크 기사", "source": "google_news"},
        {"url": "https://example.com/r2", "title": "리스크 기사", "source": "google_news"},
    ]

    merged = _merge_analyst_view_news_inputs(analyst_items, risk_items, limit=6)

    assert [item["url"] for item in merged].count("https://example.com/shared") == 1
    assert "https://example.com/r2" in [item["url"] for item in merged]


def test_analyst_views_prompt_explicitly_splits_same_article_bull_and_bear():
    prompt = _build_analyst_views_prompt(
        "005930.KS",
        "삼성전자",
        [{"published_at": None, "title": "기사", "body": "본문", "source": "naver", "url": "https://example.com"}],
        [],
    )

    assert "같은 기사 안에도 강세 요인과 약세/우려 요인이 함께 있으면 각각 bull·bear로 분리" in prompt
    assert "약세·리스크·우려·밸류에이션 부담·경쟁심화 등은 bear로 명확히 분류" in prompt
