"""
ingest_macro.py — 거시 지표 수집 → macro_indicators

수집 범위:
  - 미국(FRED): 기준금리(FEDFUNDS), 10년물(DGS10), CPI(CPIAUCSL), 실업률(UNRATE)
  - 한국(ECOS): 기준금리, CPI
  - 글로벌 시세(yfinance): VIX, DXY, USDKRW, WTI

규칙:
  - FRED/ECOS 키는 요청에만 사용하고 DB/로그/저장 데이터에 남기지 않는다.
  - 소스별 try/except 격리 — 일부 실패가 전체 실행을 멈추지 않는다.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal, Optional

import requests
import yfinance as yf
from dotenv import load_dotenv

from src.external_timeout import run_with_timeout
from src.schemas import MacroIndicatorRow

logger = logging.getLogger(__name__)
YFINANCE_TIMEOUT_SECONDS: float = 20.0


@dataclass(frozen=True)
class MacroSpec:
    indicator_code: str
    indicator_name: str
    region: Literal["US", "KR", "GLOBAL"]
    unit: str
    source: str
    fred_series: str | None = None
    symbol: str | None = None
    ecos_stat_code: str | None = None
    ecos_cycle: str = "M"
    ecos_item_codes: tuple[str, ...] = ()


US_FRED_SPECS: tuple[MacroSpec, ...] = (
    MacroSpec("FEDFUNDS", "미국 기준금리", "US", "%", "fred", fred_series="FEDFUNDS"),
    MacroSpec("DGS10", "미국 10년물 금리", "US", "%", "fred", fred_series="DGS10"),
    MacroSpec("CPIAUCSL", "미국 CPI", "US", "지수", "fred", fred_series="CPIAUCSL"),
    MacroSpec("UNRATE", "미국 실업률", "US", "%", "fred", fred_series="UNRATE"),
)

KR_ECOS_SPECS: tuple[MacroSpec, ...] = (
    MacroSpec(
        "KR_BASE_RATE",
        "한국 기준금리",
        "KR",
        "%",
        "ecos",
        ecos_stat_code="722Y001",
        ecos_cycle="M",
        ecos_item_codes=("0101000",),
    ),
    MacroSpec(
        "KR_CPI",
        "한국 CPI",
        "KR",
        "지수",
        "ecos",
        ecos_stat_code="901Y009",
        ecos_cycle="M",
        ecos_item_codes=("0",),
    ),
)

GLOBAL_MARKET_SPECS: tuple[MacroSpec, ...] = (
    MacroSpec("VIX", "VIX", "GLOBAL", "pt", "yfinance", symbol="^VIX"),
    MacroSpec("DXY", "달러인덱스", "GLOBAL", "pt", "yfinance", symbol="DX-Y.NYB"),
    MacroSpec("USDKRW", "원달러 환율", "GLOBAL", "KRW", "yfinance", symbol="KRW=X"),
    MacroSpec("WTI", "WTI 유가", "GLOBAL", "USD", "yfinance", symbol="CL=F"),
)


def _ensure_env() -> None:
    load_dotenv(override=False)


def _fred_key() -> Optional[str]:
    _ensure_env()
    return os.environ.get("FRED_API_KEY")


def _ecos_key() -> Optional[str]:
    _ensure_env()
    return os.environ.get("ECOS_API_KEY")


def _parse_date(value) -> date:
    if isinstance(value, date):
        return value
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime().date()
    if isinstance(value, datetime):
        return value.date()
    return datetime.fromisoformat(str(value)[:10]).date()


def _sanitize_error_message(message: str) -> str:
    safe = message
    for secret in (_fred_key(), _ecos_key()):
        if secret:
            safe = safe.replace(secret, "[redacted]")
    return safe


def _fetch_fred_macro_rows(spec: MacroSpec, start: date, end: date) -> list[MacroIndicatorRow]:
    key = _fred_key()
    if not key or not spec.fred_series:
        return []
    response = requests.get(
        "https://api.stlouisfed.org/fred/series/observations",
        params={
            "series_id": spec.fred_series,
            "api_key": key,
            "file_type": "json",
            "observation_start": start.isoformat(),
            "observation_end": end.isoformat(),
            "sort_order": "asc",
        },
        timeout=20,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"FRED request failed: HTTP {response.status_code}")
    payload = response.json()
    rows: list[MacroIndicatorRow] = []
    for obs in payload.get("observations") or []:
        value = obs.get("value")
        if value in (None, ".", ""):
            continue
        rows.append(
            MacroIndicatorRow(
                indicator_code=spec.indicator_code,
                indicator_name=spec.indicator_name,
                region=spec.region,
                asof=_parse_date(obs.get("date")),
                value=float(value),
                unit=spec.unit,
                source="fred",
            )
        )
    logger.info("%s: FRED %d건", spec.indicator_code, len(rows))
    return rows


def _fetch_ecos_macro_rows(spec: MacroSpec, start: date, end: date) -> list[MacroIndicatorRow]:
    key = _ecos_key()
    if not key or not spec.ecos_stat_code or not spec.ecos_item_codes:
        return []
    item_path = "/".join(spec.ecos_item_codes)
    request_url = (
        f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/1000/"
        f"{spec.ecos_stat_code}/{spec.ecos_cycle}/{start:%Y%m}/{end:%Y%m}/{item_path}"
    )
    response = requests.get(request_url, timeout=20)
    if response.status_code >= 400:
        raise RuntimeError(f"ECOS request failed: HTTP {response.status_code}")
    payload = response.json()
    rows_json = (
        payload.get("StatisticSearch", {}).get("row")
        or payload.get("StatisticSearch", {}).get("list")
        or []
    )
    rows: list[MacroIndicatorRow] = []
    for item in rows_json:
        time_value = str(item.get("TIME") or "")
        data_value = item.get("DATA_VALUE")
        if not time_value or data_value in (None, ""):
            continue
        asof = _parse_date(f"{time_value[:4]}-{time_value[4:6]}-01")
        rows.append(
            MacroIndicatorRow(
                indicator_code=spec.indicator_code,
                indicator_name=spec.indicator_name,
                region=spec.region,
                asof=asof,
                value=float(data_value),
                unit=spec.unit,
                source="ecos",
            )
        )
    logger.info("%s: ECOS %d건", spec.indicator_code, len(rows))
    return rows


def _fetch_market_macro_rows(spec: MacroSpec, period: str = "6mo") -> list[MacroIndicatorRow]:
    if not spec.symbol:
        return []
    history = run_with_timeout(YFINANCE_TIMEOUT_SECONDS, lambda: yf.Ticker(spec.symbol).history(period=period))
    if history.empty or "Close" not in history:
        return []
    rows: list[MacroIndicatorRow] = []
    for idx, value in history["Close"].dropna().items():
        rows.append(
            MacroIndicatorRow(
                indicator_code=spec.indicator_code,
                indicator_name=spec.indicator_name,
                region=spec.region,
                asof=_parse_date(idx),
                value=float(value),
                unit=spec.unit,
                source="yfinance",
            )
        )
    logger.info("%s: yfinance %d건", spec.indicator_code, len(rows))
    return rows


def run_macro_ingest(
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> dict:
    start = start or (date.today() - timedelta(days=370))
    end = end or date.today()
    rows: list[MacroIndicatorRow] = []
    errors: list[dict] = []

    for spec in US_FRED_SPECS:
        try:
            rows.extend(_fetch_fred_macro_rows(spec, start=start, end=end))
        except Exception as exc:  # noqa: BLE001
            message = _sanitize_error_message(str(exc))
            logger.warning("%s 수집 실패: %s", spec.indicator_code, message)
            errors.append({"step": "macro_ingest", "source": spec.source, "indicator": spec.indicator_code, "error": message, "ts": datetime.now(UTC).isoformat()})

    for spec in KR_ECOS_SPECS:
        try:
            rows.extend(_fetch_ecos_macro_rows(spec, start=start, end=end))
        except Exception as exc:  # noqa: BLE001
            message = _sanitize_error_message(str(exc))
            logger.warning("%s 수집 실패: %s", spec.indicator_code, message)
            errors.append({"step": "macro_ingest", "source": spec.source, "indicator": spec.indicator_code, "error": message, "ts": datetime.now(UTC).isoformat()})

    for spec in GLOBAL_MARKET_SPECS:
        try:
            rows.extend(_fetch_market_macro_rows(spec))
        except Exception as exc:  # noqa: BLE001
            message = _sanitize_error_message(str(exc))
            logger.warning("%s 수집 실패: %s", spec.indicator_code, message)
            errors.append({"step": "macro_ingest", "source": spec.source, "indicator": spec.indicator_code, "error": message, "ts": datetime.now(UTC).isoformat()})

    return {"rows": rows, "errors": errors}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    result = run_macro_ingest()
    print(f"rows={len(result['rows'])} errors={len(result['errors'])}")
