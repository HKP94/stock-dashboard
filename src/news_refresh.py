"""
news_refresh.py — 가벼운 뉴스 리프레시 잡 (하루 2회 중 18:00 KST용)

PR-2: 전체 파이프라인(run_pipeline)과 별개로 '뉴스만' 자주 갱신한다.
  1. ingest_news   : watchlist + _MARKET_* 뉴스 수집 → news_raw (url_hash dedupe)
  2. enrich_gemini : 새 뉴스 종목 요약 + KR/US 분리 시황 (GEMINI_API_KEY 필요)
  3. export        : data.json 재생성 (best-effort)
가격/지표/퀀트 재계산은 생략(06:00 auto_run에서 수행).

실행: python -m src.news_refresh
⚠️ 투자 자문 아님 / 원금 손실 가능. 자동 주문 없음.
"""

from __future__ import annotations

import logging
from datetime import datetime

from src.db import get_conn, insert_news_raw, log_run_finish, log_run_start
from src.enrich_gemini import enrich_market_summary, enrich_news_batch
from src.ingest_news import run_news_ingest

logger = logging.getLogger(__name__)


def run_news_refresh() -> dict:
    errors: list[dict] = []
    status = "success"
    new_news = enriched = 0

    with get_conn() as conn:
        run_id = log_run_start(conn, "news_refresh")
        logger.info("=== news_refresh 시작 run_id=%d ===", run_id)

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

    return {"new_news": new_news, "enriched": enriched, "errors": errors}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    r = run_news_refresh()
    print(f"\n신규 뉴스 {r['new_news']}건 / 요약 {r['enriched']}종목 / 에러 {len(r['errors'])}")
    print("⚠️ 투자 자문 아님 / 원금 손실 가능")
