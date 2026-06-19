"""
ingest_drivers.py — 종목별 핵심 동인 자동 매핑 + 프록시 가격 수집

원칙:
  - 사용자(origin='user') 매핑은 자동 매핑이 덮어쓰지 않는다.
  - 공용 데이터(WTI, USDKRW 등)는 macro_indicators/index_daily를 재사용한다.
  - 전용 프록시만 driver_prices에 적재한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import logging
import os
from typing import Callable, Optional

import yfinance as yf
from dotenv import load_dotenv

from src.db import delete_stale_auto_ticker_drivers, upsert_driver_prices, upsert_ticker_drivers
from src.enrich_gemini import _call_gemini_with_backoff, _get_gemini_client, _get_synth_model
from src.schemas import DriverPriceRow, DriverSuggestionOutput, TickerDriverRow

logger = logging.getLogger(__name__)


def _ensure_env() -> None:
    load_dotenv(override=False)


@dataclass(frozen=True)
class DriverCatalogItem:
    code: str
    name: str
    driver_source: str
    symbol: str | None = None
    shared_code: str | None = None
    effect_sign: int = 1


@dataclass(frozen=True)
class DriverCandidate:
    ticker: str
    driver_code: str
    driver_name: str
    driver_source: str
    weight: int
    origin: str
    rationale: str


DRIVER_CATALOG: dict[str, DriverCatalogItem] = {
    "SOXX": DriverCatalogItem("SOXX", "반도체 ETF", "yfinance_proxy", symbol="SOXX", effect_sign=1),
    "LIT": DriverCatalogItem("LIT", "리튬 ETF", "yfinance_proxy", symbol="LIT", effect_sign=1),
    "WTI": DriverCatalogItem("WTI", "WTI 유가", "shared_macro", shared_code="WTI", effect_sign=1),
    "USDKRW": DriverCatalogItem("USDKRW", "원달러 환율", "shared_macro", shared_code="USDKRW", effect_sign=1),
    "DXY": DriverCatalogItem("DXY", "달러인덱스", "shared_macro", shared_code="DXY", effect_sign=-1),
    "VIX": DriverCatalogItem("VIX", "VIX", "shared_macro", shared_code="VIX", effect_sign=-1),
    "DISPLAY_PROXY_NONE": DriverCatalogItem("DISPLAY_PROXY_NONE", "디스플레이 프록시 없음", "proxy_none", effect_sign=0),
}


SUPPORTED_DRIVER_TEXT = "\n".join(
    f"- {item.code}: {item.name} ({item.driver_source})"
    for item in DRIVER_CATALOG.values()
)


def _merge_driver_candidates(existing: list[dict], suggested: list[DriverCandidate]) -> list[TickerDriverRow]:
    keep: dict[str, TickerDriverRow] = {}
    for row in existing:
        if row.get("origin") == "user":
            keep[row["driver_code"]] = TickerDriverRow.model_validate(row)
    for cand in suggested:
        if cand.driver_code in keep:
            continue
        keep[cand.driver_code] = TickerDriverRow(
            ticker=cand.ticker,
            driver_code=cand.driver_code,
            driver_name=cand.driver_name,
            driver_source=cand.driver_source,
            weight=cand.weight,
            origin="auto",
            rationale=cand.rationale,
        )
    return list(keep.values())


def _fallback_driver_candidates(ticker: str, name: str, sector: str, market: str) -> list[DriverCandidate]:
    text = f"{ticker} {name} {sector} {market}".lower()
    out: list[DriverCandidate] = []
    if any(key in text for key in ("삼성전자", "sk하이닉스", "hynix", "semiconductor", "반도체", "memory", "nvda", "amd", "micron")):
        out.append(DriverCandidate(ticker, "SOXX", "반도체 ETF", "yfinance_proxy", 5, "auto", "반도체 업황과 가격 민감도가 높아 상장 프록시로 추정"))
    if any(key in text for key in ("albemarle", "리튬", "lithium", "sqm")):
        out.append(DriverCandidate(ticker, "LIT", "리튬 ETF", "yfinance_proxy", 5, "auto", "리튬 가격 민감 업종으로 추정"))
    if any(key in text for key in ("display", "디스플레이", "lg디스플레이", "lcd")):
        out.append(DriverCandidate(ticker, "DISPLAY_PROXY_NONE", "디스플레이 프록시 없음", "proxy_none", 4, "auto", "무료로 안정적으로 재현 가능한 프록시가 없어 사용자 검수가 필요"))
    if any(key in text for key in ("정유", "oil", "energy", "엑슨", "chevron", "s-oil")):
        out.append(DriverCandidate(ticker, "WTI", "WTI 유가", "shared_macro", 5, "auto", "에너지 가격이 실적 민감도에 직접 연결되는 업종으로 추정"))
    if market == "KR" and any(key in text for key in ("삼성전자", "sk하이닉스", "현대", "기아", "export", "수출")):
        out.append(DriverCandidate(ticker, "USDKRW", "원달러 환율", "shared_macro", 3, "auto", "원화 약세/강세가 수출주 체감 수익성에 영향을 줄 수 있어 보조 동인으로 추정"))
    return out[:3]


def _build_driver_prompt(ticker: str, name: str, sector: str, market: str) -> str:
    return (
        f"너는 주식 종목의 핵심 가격 동인을 추정하는 애널리스트다. [{name}({ticker})] / 시장={market} / 섹터={sector}에 대해 "
        "아래 지원되는 드라이버 후보 중 1~3개만 고르라.\n"
        "- 이 결과는 추정이며 단정하지 말고, 사용자가 검수·수정할 전제다.\n"
        "- 무료 프록시가 없는 경우 DISPLAY_PROXY_NONE을 써라.\n"
        "- 매수/매도 지시 금지.\n\n"
        f"[지원 드라이버]\n{SUPPORTED_DRIVER_TEXT}\n\n"
        "JSON으로만 답하라:\n"
        '{"drivers":[{"driver_code":"SOXX","driver_name":"반도체 ETF","driver_source":"yfinance_proxy|shared_macro|proxy_none","weight":1-5,"rationale":"왜 이 동인인지 1문장"}]}'
    )


def _suggest_driver_candidates(ticker: str, name: str, sector: str, market: str) -> list[DriverCandidate]:
    _ensure_env()
    if not os.environ.get("GEMINI_API_KEY"):
        return _fallback_driver_candidates(ticker, name, sector, market)
    try:
        client = _get_gemini_client()
        text = _call_gemini_with_backoff(client, _get_synth_model(), _build_driver_prompt(ticker, name, sector, market))
        out = DriverSuggestionOutput.model_validate_json(text)
        rows: list[DriverCandidate] = []
        for item in out.drivers[:3]:
            meta = DRIVER_CATALOG.get(item.driver_code)
            if not meta:
                continue
            rows.append(
                DriverCandidate(
                    ticker=ticker,
                    driver_code=item.driver_code,
                    driver_name=meta.name,
                    driver_source=meta.driver_source,
                    weight=item.weight,
                    origin="auto",
                    rationale=item.rationale,
                )
            )
        return rows or _fallback_driver_candidates(ticker, name, sector, market)
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s driver auto-map fallback: %s", ticker, str(exc)[:120])
        return _fallback_driver_candidates(ticker, name, sector, market)


def auto_map_ticker_drivers(conn, ticker: str, *, name: str, sector: str, market: str) -> list[TickerDriverRow]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ticker, driver_code, driver_name, driver_source, weight, origin, rationale FROM ticker_drivers WHERE ticker=%s",
            (ticker,),
        )
        existing = [dict(r) for r in cur.fetchall()]
    suggested = _suggest_driver_candidates(ticker, name, sector or "", market or "US")
    merged = _merge_driver_candidates(existing, suggested)
    auto_codes = [row.driver_code for row in merged if row.origin == "auto"]
    delete_stale_auto_ticker_drivers(conn, ticker, auto_codes)
    upsert_ticker_drivers(conn, merged)
    return merged


def _fetch_history(symbol: str, period: str = "6mo") -> list[tuple[date, float]]:
    history = yf.Ticker(symbol).history(period=period)
    if history.empty or "Close" not in history:
        return []
    return [(idx.date(), float(value)) for idx, value in history["Close"].dropna().items()]


def collect_driver_price_rows(
    driver_rows: list[dict],
    fetch_history: Optional[Callable[[str], list[tuple[date, float]]]] = None,
) -> list[DriverPriceRow]:
    fetch_history = fetch_history or _fetch_history
    rows: list[DriverPriceRow] = []
    seen_codes: set[str] = set()
    for item in driver_rows:
        code = item["driver_code"]
        if code in seen_codes:
            continue
        seen_codes.add(code)
        meta = DRIVER_CATALOG.get(code)
        if not meta or meta.driver_source in {"shared_macro", "shared_index", "proxy_none"} or not meta.symbol:
            continue
        for asof, close in fetch_history(meta.symbol):
            rows.append(DriverPriceRow(driver_code=code, asof=asof, close=close, source="yfinance"))
    return rows


def run_driver_price_ingest(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT ticker, driver_code, driver_name, driver_source, weight, origin, rationale FROM ticker_drivers")
        mappings = [dict(r) for r in cur.fetchall()]
    rows = collect_driver_price_rows(mappings)
    if rows:
        upsert_driver_prices(conn, rows)
    return {"rows": rows, "errors": []}

