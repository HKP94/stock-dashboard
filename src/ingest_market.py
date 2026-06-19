"""
ingest_market.py — 글로벌 시장 지표 수집 → market_daily

심볼 → 필드:
  ^KS11  → kospi      ^KQ11 → kosdaq
  ^GSPC  → sp500      ^IXIC → nasdaq
  ^VIX   → vix        KRW=X → usdkrw
  ^TNX   → ust10y

소스: yfinance (period="5d", 최신 종가 사용)

절대 규칙:
  - 심볼 단위 격리 — 한 심볼 실패가 전체 막으면 안 됨
  - summary_md / payload 는 None / {} — Phase 2에서 Gemini가 채움
  - 자동 주문·매매 코드 없음
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

import yfinance as yf
from tenacity import (
    before_sleep_log,
    retry,
    stop_after_attempt,
    wait_exponential,
)

from src.schemas import MarketDailyRow

logger = logging.getLogger(__name__)

# ── 심볼 → MarketDailyRow 필드 매핑 ─────────────────────────────
MARKET_SYMBOLS: dict[str, str] = {
    "^KS11": "kospi",
    "^KQ11": "kosdaq",
    "^GSPC": "sp500",
    "^IXIC": "nasdaq",
    "^VIX":  "vix",
    "KRW=X": "usdkrw",
    "^TNX":  "ust10y",
}


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _fetch_close_and_change(symbol: str) -> tuple[Optional[float], Optional[float]]:
    """
    yfinance로 심볼의 최신 종가 + 전일(직전 거래일) 대비 등락률(%)을 반환.
    PR-4: 거래일 기준 실제 직전 종가와 비교 → 주말 carry-over로 인한 0.00% 버그 방지.
    데이터 없으면 (None, None).
    """
    df = yf.Ticker(symbol).history(period="1mo")
    if df.empty:
        return None, None
    closes = df["Close"].dropna()
    if closes.empty:
        return None, None
    last = float(closes.iloc[-1])
    change = None
    if len(closes) >= 2:
        prev = float(closes.iloc[-2])
        if prev != 0:
            change = round((last - prev) / prev * 100, 2)
    return last, change


def fetch_market_daily(asof: Optional[date] = None) -> MarketDailyRow:
    """
    7개 시장 심볼 수집 → MarketDailyRow.
    심볼 단위 격리: 실패한 심볼의 필드만 None, 나머지는 정상 반환.
    PR-4: payload.changes={field: pct}에 전일대비 등락률 저장(거래일 기준).
    summary_*_md 는 None (Gemini Phase 2에서 채움).
    """
    asof = asof or date.today()
    fields: dict[str, Optional[float]] = {v: None for v in MARKET_SYMBOLS.values()}
    changes: dict[str, float] = {}

    for symbol, field in MARKET_SYMBOLS.items():
        try:
            val, chg = _fetch_close_and_change(symbol)
            fields[field] = val
            if chg is not None:
                changes[field] = chg
            logger.info("시장 %s (%s) = %s (chg=%s%%)", symbol, field, val, chg)
        except Exception as exc:
            logger.warning("시장 심볼 %s 수집 실패 (필드=%s): %s", symbol, field, exc)
            # 해당 필드는 None 유지 — 다른 심볼에 영향 없음

    row = MarketDailyRow(
        asof=asof,
        kospi=fields["kospi"],
        kosdaq=fields["kosdaq"],
        sp500=fields["sp500"],
        nasdaq=fields["nasdaq"],
        vix=fields["vix"],
        usdkrw=fields["usdkrw"],
        ust10y=fields["ust10y"],
        summary_md=None,
        payload={"changes": changes},
    )
    logger.info(
        "market_daily asof=%s  kospi=%s sp500=%s vix=%s usdkrw=%s changes=%d개",
        asof, row.kospi, row.sp500, row.vix, row.usdkrw, len(changes),
    )
    return row


def run_market_ingest(asof: Optional[date] = None) -> dict:
    """
    시장 지표 수집 실행.
    반환: {"market": MarketDailyRow, "errors": [...]}
    """
    errors: list[dict] = []
    try:
        market = fetch_market_daily(asof=asof)
    except Exception as exc:
        logger.error("시장 지표 수집 전체 실패: %s", exc, exc_info=True)
        errors.append({
            "step": "market",
            "error": str(exc),
            "ts": datetime.utcnow().isoformat(),
        })
        market = MarketDailyRow(asof=asof or date.today())

    return {"market": market, "errors": errors}


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    logger.info("=== 스모크 테스트: market_daily ===")
    result = run_market_ingest()
    m = result["market"]

    print(f"\nasof: {m.asof}")
    print(f"  KOSPI   = {m.kospi}")
    print(f"  KOSDAQ  = {m.kosdaq}")
    print(f"  S&P500  = {m.sp500}")
    print(f"  NASDAQ  = {m.nasdaq}")
    print(f"  VIX     = {m.vix}")
    print(f"  USD/KRW = {m.usdkrw}")
    print(f"  US10Y   = {m.ust10y}")

    assert "N/A" not in str(m.model_dump()), "N/A 문자열 금지"

    collected = sum(1 for v in [m.kospi, m.kosdaq, m.sp500, m.nasdaq, m.vix, m.usdkrw, m.ust10y] if v is not None)
    print(f"\n수집 성공: {collected}/7 심볼")

    errs = result["errors"]
    if errs:
        print(f"에러: {errs}")
