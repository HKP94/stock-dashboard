"""
news_refresh.py — 가벼운 갱신 잡 (하루 2회 중 18:00 KST용)

전체 파이프라인(run_pipeline, 06:00)과 별개로 가격·뉴스를 자주 갱신한다.
  0. (PR-1) 경량 가격 갱신 : prices_daily + indicators/quant 재계산
     (재무/밸류/컨센서스 .info 호출은 생략 — 빠르게. KR은 장마감 후라 당일 종가 확보)
  1. ingest_news   : watchlist + _MARKET_* 뉴스 수집 → news_raw (url_hash dedupe)
  2. enrich_gemini : 새 뉴스 종목 요약 + KR/US 분리 시황 (GEMINI_API_KEY 필요)
  3. export        : data.json 재생성 (best-effort)

타이밍: 06:00 KST=US 종가 직후(US 최신) + KR 전일, 18:00 KST=KR 당일 종가 + US 전일.
        → 두 잡으로 KR/US 모두 최신 거래일 가격 확보.

실행: python -m src.news_refresh
자동 주문 없음.
"""

from __future__ import annotations

import logging
from datetime import datetime

from src.db import get_conn, insert_market_news, insert_news_raw, log_run_finish, log_run_start, upsert_price_daily
from src.enrich_gemini import enrich_market_summary, enrich_news_batch, summarize_market_news_digest
from src.ingest_market_news import run_market_news_ingest
from src.ingest_news import run_news_ingest
from src import pipeline_analysis, pipeline_ingest, pipeline_synthesis

logger = logging.getLogger(__name__)


def _refresh_prices_light(conn) -> dict:
    """
    PR-1: 18:00 잡용 경량 가격 갱신 — prices_daily + indicators/quant 재계산만.
    재무/밸류/컨센서스(.info 호출)는 생략해 빠르게. KR은 장마감(15:30) 후라 당일 종가 확보.
    반환: {"price_rows": n, "indicators": n, "quant": n, "errors": [...]}
    """
    from src.ingest_kr import fetch_kr_prices
    from src.ingest_us import fetch_us_prices
    from src.compute_indicators import recompute_indicators_to_db
    from src.compute_quant import compute_quant_universe
    from src.db import upsert_quant_scores

    errors: list[dict] = []
    with conn.cursor() as cur:
        cur.execute("SELECT ticker, market FROM watchlist WHERE active=TRUE ORDER BY ticker")
        wl = [(r["ticker"], r["market"]) for r in cur.fetchall()]

    n_price = 0
    kr_latest = None
    for ticker, market in wl:
        try:
            if market == "KR":
                rows = fetch_kr_prices(ticker)
                if rows:
                    kr_latest = max(kr_latest, rows[-1].date) if kr_latest else rows[-1].date
            else:
                rows = fetch_us_prices(ticker)
            if rows:
                upsert_price_daily(conn, rows)
                conn.commit()
                n_price += len(rows)
        except Exception as exc:
            conn.rollback()
            logger.warning("가격 갱신 실패 %s: %s", ticker, exc)
            errors.append({"step": "price", "ticker": ticker, "error": str(exc), "ts": datetime.utcnow().isoformat()})

    n_ind = n_quant = 0
    tickers = [t for t, _ in wl]
    try:
        n_ind = recompute_indicators_to_db(conn, tickers)
    except Exception as exc:
        conn.rollback()
        errors.append({"step": "indicators", "error": str(exc), "ts": datetime.utcnow().isoformat()})
    try:
        qrows = compute_quant_universe(tickers, conn)
        if qrows:
            upsert_quant_scores(conn, qrows)
            conn.commit()
            n_quant = len(qrows)
    except Exception as exc:
        conn.rollback()
        errors.append({"step": "quant", "error": str(exc), "ts": datetime.utcnow().isoformat()})

    if kr_latest:
        logger.info("경량 가격 갱신(KR): 최종 적재 기준일 %s", kr_latest.isoformat())
    logger.info("경량 가격 갱신: prices %d / indicators %d / quant %d", n_price, n_ind, n_quant)
    return {"price_rows": n_price, "indicators": n_ind, "quant": n_quant, "errors": errors}


def run_news_refresh() -> dict:
    """
    18:00 KST 경량 갱신 호환 래퍼 (설계 §9-6) — 새 세 실행기를 refresh 순서로 호출한 뒤
    data.json을 재생성한다(현재 18시 export 동작 유지).

      pipeline_ingest.run('refresh')   : 경량 가격 + 종목/시장 뉴스
      pipeline_analysis.run('refresh') : 지표 + 퀀트 (분석→종합 순서 보존)
      pipeline_synthesis.run('refresh'): 뉴스 요약 + 시황 + 시장 뉴스 요약
      → export (best-effort)

    # ponytail: _refresh_prices_light는 실행기로 이전됐고 여기선 더 이상 호출하지 않는다.
    #           중복본은 설계 §9 8단계(dead code 제거)까지 유지한다.
    자동 주문 없음.
    """
    ing = pipeline_ingest.run("refresh")
    ana = pipeline_analysis.run("refresh")
    syn = pipeline_synthesis.run("refresh")

    errors = list(ing.get("errors", [])) + list(ana.get("errors", [])) + list(syn.get("errors", []))
    new_news = ing.get("counts", {}).get("news_raw", 0)
    enriched = syn.get("counts", {}).get("news_analysis", 0)
    prices = ing.get("counts", {}).get("prices_daily", 0)
    logger.info("=== news_refresh(호환 래퍼) 완료 신규=%d 요약=%d ===", new_news, enriched)

    # export (best-effort — DB 외부 산출물, 현재 18시 동작 유지)
    try:
        from src.export_dashboard_data import build_data
        import json
        from pathlib import Path
        data = build_data()
        out = Path(__file__).resolve().parent.parent / "dashboard-web" / "src" / "data.json"
        if out.parent.exists():
            with open(out, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            logger.info("data.json 재생성 완료")
    except Exception as exc:
        logger.warning("export 스킵(비치명적): %s", exc)

    return {"new_news": new_news, "enriched": enriched, "prices": prices, "errors": errors}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    r = run_news_refresh()
    print(f"\n신규 뉴스 {r['new_news']}건 / 요약 {r['enriched']}종목 / 에러 {len(r['errors'])}")
