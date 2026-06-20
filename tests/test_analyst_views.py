from __future__ import annotations

import json
from datetime import date

from src.enrich_gemini import _build_analyst_view_rows, _parse_analyst_views_output
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
