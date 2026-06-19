from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from src.ingest_macro import (
    MacroSpec,
    _fetch_fred_macro_rows,
    _fetch_market_macro_rows,
    _fetch_ecos_macro_rows,
    run_macro_ingest,
)


def test_fetch_fred_macro_rows_never_persists_api_key(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "secret-key")

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "observations": [
            {"date": "2026-06-01", "value": "4.25"},
            {"date": "2026-05-01", "value": "4.20"},
        ]
    }

    spec = MacroSpec(
        indicator_code="FEDFUNDS",
        indicator_name="미국 기준금리",
        region="US",
        unit="%",
        source="fred",
        fred_series="FEDFUNDS",
    )

    with patch("src.ingest_macro.requests.get", return_value=response):
        rows = _fetch_fred_macro_rows(spec, start=date(2026, 5, 1), end=date(2026, 6, 30))

    assert len(rows) == 2
    assert all("secret-key" not in row.source for row in rows)
    assert {row.value for row in rows} == {4.25, 4.2}


def test_fetch_ecos_macro_rows_skips_without_key(monkeypatch):
    monkeypatch.delenv("ECOS_API_KEY", raising=False)
    spec = MacroSpec(
        indicator_code="KR_BASE_RATE",
        indicator_name="한국 기준금리",
        region="KR",
        unit="%",
        source="ecos",
        ecos_stat_code="722Y001",
        ecos_cycle="M",
        ecos_item_codes=("0101000",),
    )
    assert _fetch_ecos_macro_rows(spec, start=date(2026, 1, 1), end=date(2026, 6, 30)) == []


def test_fetch_market_macro_rows_extracts_history():
    class _Series:
        def dropna(self):
            return self

        def items(self):
            return iter([
                (datetime.fromisoformat("2026-06-17T00:00:00"), 18.0),
                (datetime.fromisoformat("2026-06-18T00:00:00"), 19.5),
            ])

    class _History:
        empty = False

        def __contains__(self, key):
            return key == "Close"

        def __getitem__(self, key):
            assert key == "Close"
            return _Series()

    ticker = MagicMock()
    ticker.history.return_value = _History()

    spec = MacroSpec(
        indicator_code="VIX",
        indicator_name="VIX",
        region="GLOBAL",
        unit="pt",
        source="yfinance",
        symbol="^VIX",
    )

    with patch("src.ingest_macro.yf.Ticker", return_value=ticker):
        rows = _fetch_market_macro_rows(spec)

    assert [row.value for row in rows] == [18.0, 19.5]


def test_run_macro_ingest_isolates_source_failures():
    def fred_side_effect(spec, start, end):
        if spec.indicator_code == "FEDFUNDS":
            return [MagicMock()]
        if spec.indicator_code == "DGS10":
            raise Exception("boom")
        return []

    with patch("src.ingest_macro._fetch_fred_macro_rows", side_effect=fred_side_effect), \
         patch("src.ingest_macro._fetch_ecos_macro_rows", return_value=[]), \
         patch("src.ingest_macro._fetch_market_macro_rows", return_value=[]):
        result = run_macro_ingest()

    assert "rows" in result and "errors" in result
    assert len(result["errors"]) >= 1
