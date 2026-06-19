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
    for ticker, market in wl:
        try:
            rows = fetch_kr_prices(ticker) if market == "KR" else fetch_us_prices(ticker)
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

    logger.info("경량 가격 갱신: prices %d / indicators %d / quant %d", n_price, n_ind, n_quant)
    return {"price_rows": n_price, "indicators": n_ind, "quant": n_quant, "errors": errors}


def run_news_refresh() -> dict:
    errors: list[dict] = []
    status = "success"
    new_news = enriched = 0

    price_info = {}
    with get_conn() as conn:
        run_id = log_run_start(conn, "news_refresh")
        logger.info("=== news_refresh 시작 run_id=%d ===", run_id)

        # 0) PR-1: 경량 가격 갱신 (18:00 KST에도 가격이 빠르게 들어오도록)
        try:
            price_info = _refresh_prices_light(conn)
            errors.extend(price_info.get("errors", []))
        except Exception as exc:
            conn.rollback()
            logger.error("경량 가격 갱신 실패: %s", exc, exc_info=True)
            errors.append({"step": "price_refresh", "error": str(exc), "ts": datetime.utcnow().isoformat()})

        # 1) 뉴스 수집
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT ticker, name FROM watchlist WHERE active=TRUE")
                names = {r["ticker"]: r["name"] for r in cur.fetchall()}
            tickers = list(names.keys())
            result = run_news_ingest(tickers, company_names=names)
            for rows in result.get("news", {}).values():
                if rows:
                    new_news += insert_news_raw(conn, rows)
            conn.commit()
            errors.extend(result.get("errors", []))
            logger.info("뉴스 수집: 신규 %d건", new_news)
        except Exception as exc:
            conn.rollback()
            logger.error("뉴스 수집 실패: %s", exc, exc_info=True)
            errors.append({"step": "ingest_news", "error": str(exc), "ts": datetime.utcnow().isoformat()})

        try:
            market_result = run_market_news_ingest()
            inserted_market = insert_market_news(conn, market_result.get("rows", []))
            conn.commit()
            errors.extend(market_result.get("errors", []))
            logger.info("시장 뉴스 수집: 신규 %d건", inserted_market)
        except Exception as exc:
            conn.rollback()
            logger.error("시장 뉴스 수집 실패: %s", exc, exc_info=True)
            errors.append({"step": "ingest_market_news", "error": str(exc), "ts": datetime.utcnow().isoformat()})

        # 2) Gemini 요약 + 시황
        try:
            enriched, errs = enrich_news_batch(conn)
            conn.commit()
            errors.extend(errs)
        except Exception as exc:
            conn.rollback()
            logger.error("뉴스 요약 실패: %s", exc, exc_info=True)
            errors.append({"step": "enrich_news", "error": str(exc), "ts": datetime.utcnow().isoformat()})
        try:
            enrich_market_summary(conn)
            conn.commit()
        except Exception as exc:
            conn.rollback()
            logger.warning("시황 종합 실패(비치명적): %s", exc)
            errors.append({"step": "enrich_market", "error": str(exc), "ts": datetime.utcnow().isoformat()})
        try:
            summarize_market_news_digest(conn)
            conn.commit()
        except Exception as exc:
            conn.rollback()
            logger.warning("시장 뉴스 요약 실패(비치명적): %s", exc)
            errors.append({"step": "market_news_digest", "error": str(exc), "ts": datetime.utcnow().isoformat()})

        if errors and status != "failed":
            status = "partial"
        log_run_finish(conn, run_id, status=status, errors=errors)
        logger.info("=== news_refresh 완료 status=%s 신규=%d 요약=%d ===", status, new_news, enriched)

    # 3) export (best-effort — DB 외부 산출물)
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

    return {"new_news": new_news, "enriched": enriched,
            "prices": price_info.get("price_rows", 0), "errors": errors}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    r = run_news_refresh()
    print(f"\n신규 뉴스 {r['new_news']}건 / 요약 {r['enriched']}종목 / 에러 {len(r['errors'])}")
