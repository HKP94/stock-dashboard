"""detect_moves.py — 급등·급락 감지 + 뉴스 귀인 (신규-G, 관찰 레이어).

설계(PM 승인): 감지 코어 = **변동성조정 z + 지수대비 태그**.
  · 감지: z = 일간수익률 r / (종목 트레일링 60일 일간수익률 σ). |z|≥Z_THRESHOLD AND |r|≥MIN_ABS.
          (절대 floor로 초저변동주 미세이동 차단, σ로 고변동주 정상이동 제외)
  · 태그: excess = r − β·r_index (β=quant_scores.beta·없으면 1). idiosyncratic(자체이동, 귀인 필요)
          vs market_driven(지수 동반, 강조↓) — 광범위 상승/하락일 오탐 억제.

귀인/분류(결정론, 새 LLM 대량호출 0 — §8): 당일 news_analysis(curated impact·category, sentiment)와
  investor_flow(수급)를 재활용해 4축 분류: 가치이벤트 / 정보·펀더멘털 / 정서·수급 / **이유 불명**.
  "이유 불명"(자체 이동인데 설명 뉴스·수급 미포착) = 정보 선반영 가능성 = 리스크 신호로 부각.

불변: §2 관찰·서술만(매매 지시 금지·지시어 없음), §F7 오늘 시점만(소급 백필 없음),
      자동수집 무결성(prices_daily·news_analysis·investor_flow 읽기 전용). 저장은 move_anomalies.

실행: python -m src.detect_moves  (파이프라인 종합 단계 + local_refresh가 호출)
"""

from __future__ import annotations

import json
import logging
import statistics
from datetime import date, timedelta
from typing import Optional

import psycopg

from src.compute_quant import _market_benchmark

logger = logging.getLogger(__name__)

# ── 임계·상수 (튜닝 가능) ────────────────────────────────────────
# 감지 = 절대 규모 leg OR 변동성조정 z leg. 이 유니버스는 일간 σ가 4~7%로 극단적이라(고변동
# 성장/전력기기주), 순수 z만으론 효성 −7.3%(z≈−1.5)조차 못 잡는다 — 사용자의 "크게 움직였다"는
# 절대 기준이므로 절대 leg가 필수. z는 "이 종목 기준 이례적(unusual)"을 구분하는 맥락 신호로 유지
# (저변동주의 이례적 이동도 포착). §F7 룩어헤드 없음(σ는 오늘 제외 트레일링).
VOL_WINDOW: int = 60          # 변동성 σ 산출 창(트레일링 일간수익률 표본, 오늘 제외)
VOL_MIN_OBS: int = 20         # σ 최소 표본(미만이면 z 정규화 생략, 절대 leg만)
Z_MAIN: float = 2.5           # 변동성조정 이례 임계(|z|) — 저변동주 이례적 이동 포착
ABS_STRONG: float = 0.06      # 절대 규모 leg(6%) — 사용자가 인지하는 '큰 움직임'
MIN_ABS_FLOOR: float = 0.04   # z leg의 최소 절대 수익률(초저변동주 미세이동 노이즈 차단)
IDIO_EXCESS_MIN: float = 0.03 # 지수대비 초과가 이 이상이면 idiosyncratic(자체 이동)
HIGH_IMPACT: int = 60         # curated 고영향 임계(CURATION_THRESHOLD와 정합)
RECENCY_DAYS: int = 4         # 종목 최신 종가가 오늘−N일보다 오래면 스킵(소급/상폐 방지)

# curated category(enrich_gemini._CATEGORIES) → 4축 분류 매핑
_VALUE_EVENT_CATS = frozenset({"실적", "가이던스", "M&A·계약", "규제·정책"})
_INFO_FUND_CATS = frozenset({"애널리스트변경", "제품·기술", "거시"})

CLASS_VALUE = "가치이벤트"
CLASS_INFO = "정보·펀더멘털"
CLASS_FLOW = "정서·수급"
CLASS_PENDING = "뉴스 있음(요약 대기)"  # 원문 뉴스는 있으나 요약 미생성(Gemini 실패) — 이유 불명과 구분
CLASS_UNKNOWN = "이유 불명"


def _load_recent_prices(conn: psycopg.Connection, ticker: str, limit: int,
                        asof: date) -> list[tuple[date, float]]:
    """종목 최근 종가 (asof 이하, 날짜 오름차순). §F7: asof 이후 종가 미사용. NUMERIC→float 방어."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT date, close FROM prices_daily WHERE ticker=%s AND close IS NOT NULL AND date<=%s "
            "ORDER BY date DESC LIMIT %s",
            (ticker, asof, limit),
        )
        rows = cur.fetchall()
    out = [(r["date"], float(r["close"])) for r in rows if r["close"] is not None]
    out.reverse()  # 오름차순
    return out


def _index_return(conn: psycopg.Connection, index_code: str, asof: date) -> Optional[float]:
    """지수 index_code의 asof 당일 수익률(전 거래일 대비). 없으면 None."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT asof, close FROM index_daily WHERE index_code=%s AND asof<=%s AND close IS NOT NULL "
            "ORDER BY asof DESC LIMIT 2",
            (index_code, asof),
        )
        rows = cur.fetchall()
    if len(rows) < 2:
        return None
    cur_c, prev_c = float(rows[0]["close"]), float(rows[1]["close"])
    if prev_c <= 0:
        return None
    return cur_c / prev_c - 1.0


def _latest_beta(conn: psycopg.Connection, ticker: str) -> Optional[float]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT beta FROM quant_scores WHERE ticker=%s AND beta IS NOT NULL ORDER BY asof DESC LIMIT 1",
            (ticker,),
        )
        row = cur.fetchone()
    return float(row["beta"]) if row and row["beta"] is not None else None


def _load_news(conn: psycopg.Connection, ticker: str, asof: date) -> Optional[dict]:
    """당일 news_analysis 1행(sentiment·summary·curated·based_on·n_articles)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT sentiment, sentiment_score, summary_md, curated, based_on, n_articles "
            "FROM news_analysis WHERE ticker=%s AND asof=%s",
            (ticker, asof),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def _load_flow(conn: psycopg.Connection, ticker: str, asof: date) -> Optional[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT foreign_net, institution_net, individual_net, combined_signal "
            "FROM investor_flow WHERE ticker=%s AND date=%s",
            (ticker, asof),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def _load_raw_news(conn: psycopg.Connection, ticker: str, asof: date, limit: int = 3) -> list[dict]:
    """원문 뉴스 제목(요약 실패 시 폴백 참조용). 이동일 전후 ±1일 기사, 최신순.
    Gemini 요약이 실패해도 '뉴스가 있었다'는 사실은 news_raw로 확인 가능(요약≠수집)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT title, url, published_at FROM news_raw "
            "WHERE ticker=%s AND published_at::date BETWEEN %s AND %s "
            "ORDER BY published_at DESC LIMIT %s",
            (ticker, asof - timedelta(days=1), asof + timedelta(days=1), limit),
        )
        return [dict(r) for r in cur.fetchall()]


def _classify(news: Optional[dict], flow: Optional[dict], direction: str,
              raw_titles: Optional[list[dict]] = None) -> dict:
    """당일 뉴스·수급으로 분류 + 결정론 서술. 관찰만(지시어 없음).
    요약 실패(Gemini) 시에도 원문 뉴스가 있으면 '이유 불명'이 아니라 '요약 대기'로 구분한다."""
    sources: list[dict] = []

    # 1) 고영향 curated 뉴스 → 가치이벤트 / 정보·펀더멘털.
    #    **방향 정합 필수**: 이동 방향과 뉴스 방향(호재/악재)이 맞는 것만 원인으로 인정한다.
    #    상승을 악재뉴스로/하락을 호재뉴스로 붙이면 인과 위조(§2). 중립은 허용(방향 무해).
    #    정합 고영향 뉴스가 없으면 뉴스 귀인을 건너뛰고 수급/심리/이유불명으로 흐른다.
    if news and news.get("curated"):
        curated = news["curated"] if isinstance(news["curated"], list) else []
        want = "호재" if direction == "급등" else "악재"
        hi = [c for c in curated if isinstance(c, dict) and (c.get("impact_score") or 0) >= HIGH_IMPACT
              and c.get("direction") in (want, "중립")]
        hi.sort(key=lambda c: (c.get("direction") != want, -(c.get("impact_score") or 0)))
        if hi:
            top = hi[0]
            cat = top.get("category") or "기타"
            klass = CLASS_VALUE if cat in _VALUE_EVENT_CATS else CLASS_INFO
            for c in hi[:3]:
                sources.append({"type": "news", "title": c.get("title"), "url": c.get("url"),
                                "category": c.get("category"), "impact": c.get("impact_score"),
                                "direction": c.get("direction")})
            insight = (top.get("insight") or top.get("title") or "").strip()
            reason = f"{cat} 관련 뉴스(영향도 {top.get('impact_score')})" + (f" — {insight}" if insight else "")
            return {"attribution_class": klass, "explained": True, "reason": reason, "sources": sources}

    # 2) 수급 주도(강한 투자자 순매수/순매도가 방향과 정합) → 정서·수급
    if flow and flow.get("combined_signal") in ("수급_강세", "수급_약세"):
        sig = flow["combined_signal"]
        aligned = (sig == "수급_강세" and direction == "급등") or (sig == "수급_약세" and direction == "급락")
        if aligned:
            fn = float(flow.get("foreign_net") or 0)
            inn = float(flow.get("institution_net") or 0)
            sources.append({"type": "flow", "combined_signal": sig,
                            "foreign_net": fn, "institution_net": inn})
            reason = f"수급 주도 — 외국인 {fn:+,.0f}·기관 {inn:+,.0f} ({sig.replace('_', ' ')})"
            return {"attribution_class": CLASS_FLOW, "explained": True, "reason": reason, "sources": sources}

    # 3) 최신 뉴스 요약이 있고 심리가 방향과 정합 → 정서·수급(약한 귀인)
    if news and news.get("based_on") == "recent" and (news.get("n_articles") or 0) > 0:
        senti = news.get("sentiment")
        aligned = (senti == "긍정" and direction == "급등") or (senti == "부정" and direction == "급락")
        if aligned:
            sources.append({"type": "news_summary", "sentiment": senti,
                            "n_articles": news.get("n_articles")})
            reason = f"뉴스 심리 {senti}({news.get('n_articles')}건) 방향 정합 — 정서 주도로 관찰"
            return {"attribution_class": CLASS_FLOW, "explained": True, "reason": reason, "sources": sources}

    # 4) 요약이 '실패/부재'인데 원문 뉴스는 있음 → '요약 대기'(이유 불명과 구분).
    #    "요약 실패 ≠ 뉴스 없음". 단, 요약이 성공(recent)했는데 방향이 안 맞는 경우는 여기가 아니라
    #    이유 불명(요약은 있으나 그 뉴스로 설명 안 됨) — summary_unavailable일 때만 요약 대기.
    summary_unavailable = (not news) or news.get("based_on") != "recent"
    n_art = (news.get("n_articles") or 0) if news else 0
    titles = raw_titles or []
    if summary_unavailable and (n_art > 0 or titles):
        for t in titles[:3]:
            sources.append({"type": "news_raw", "title": t.get("title"), "url": t.get("url")})
        head = titles[0].get("title") if titles else None
        cnt = max(n_art, len(titles))
        reason = (f"원문 뉴스 {cnt}건 있으나 요약 미생성(자동 요약 일시 중단)"
                  + (f" — 예: {head}" if head else "") + ". 요약 복구 시 귀인 상세화.")
        return {"attribution_class": CLASS_PENDING, "explained": True, "reason": reason, "sources": sources}

    # 5) 원문 뉴스도 없음 → 진짜 이유 불명(리스크 신호)
    reason = "원문 뉴스·특이 수급 미포착 — 정보 선반영 가능성(관찰, 확인 필요)"
    return {"attribution_class": CLASS_UNKNOWN, "explained": False, "reason": reason, "sources": sources}


def detect_for_ticker(conn: psycopg.Connection, ticker: str, market: str,
                      asof: date) -> Optional[dict]:
    """단일 종목 감지·귀인(asof 세션 기준). 조건 미달이면 None. 종목 단위 격리(호출부 try/except)."""
    prices = _load_recent_prices(conn, ticker, VOL_WINDOW + 3, asof)
    if len(prices) < 2:
        return None
    move_date, close = prices[-1]
    prev_close = prices[-2][1]
    # §F7·소급 방지: asof 기준 최신 종가가 너무 오래됐으면(상폐/휴장 누적) 스킵
    if (asof - move_date).days > RECENCY_DAYS or prev_close <= 0:
        return None

    r = close / prev_close - 1.0
    # 트레일링 σ(오늘 제외 → 룩어헤드 없음): prices[:-1]로 일간수익률 계산. 표본 부족이면 z=None(절대 leg만).
    hist = [p[1] for p in prices[:-1]]
    rets = [hist[i] / hist[i - 1] - 1.0 for i in range(1, len(hist)) if hist[i - 1] > 0]
    rets = rets[-VOL_WINDOW:]
    z: Optional[float] = None
    if len(rets) >= VOL_MIN_OBS:
        sigma = statistics.pstdev(rets)
        if sigma > 0:
            z = r / sigma

    # 감지 게이트: 절대 규모 leg OR (이례적 z leg AND 최소 절대 floor)
    strong = abs(r) >= ABS_STRONG
    unusual = z is not None and abs(z) >= Z_MAIN and abs(r) >= MIN_ABS_FLOOR
    if not (strong or unusual):
        return None

    direction = "급등" if r > 0 else "급락"

    # 지수대비 excess → idiosyncratic 태그
    bench = _market_benchmark(ticker, market)
    r_idx = _index_return(conn, bench, move_date)
    beta = _latest_beta(conn, ticker)
    excess: Optional[float]
    if r_idx is None:
        excess = None
        idiosyncratic = True  # 지수 미확보 시 보수적으로 자체 이동 취급(귀인 시도)
    else:
        b = beta if beta is not None else 1.0
        excess = r - b * r_idx
        idiosyncratic = abs(excess) >= IDIO_EXCESS_MIN

    news = _load_news(conn, ticker, move_date)
    flow = _load_flow(conn, ticker, move_date) if market == "KR" else None
    # 요약 실패 시에도 원문 뉴스 참조: curated/요약이 비어 있을 때만 news_raw 제목을 로드(불필요 쿼리 회피).
    need_raw = not (news and news.get("based_on") == "recent" and news.get("curated"))
    raw_titles = _load_raw_news(conn, ticker, move_date) if need_raw else None
    attrib = _classify(news, flow, direction, raw_titles)

    return {
        "ticker": ticker,
        "asof": move_date,
        "ret_pct": round(r * 100, 2),
        "z_score": round(z, 2) if z is not None else None,
        "excess_pct": round(excess * 100, 2) if excess is not None else None,
        "direction": direction,
        "idiosyncratic": idiosyncratic,
        "unusual": bool(z is not None and abs(z) >= Z_MAIN),  # 이 종목 기준 이례적 변동폭
        "attribution_class": attrib["attribution_class"],
        "explained": attrib["explained"],
        "reason": attrib["reason"],
        "sources": attrib["sources"],
    }


def detect_move_anomalies(conn: psycopg.Connection, asof: Optional[date] = None) -> list[dict]:
    """활성 유니버스 전체 감지(asof 세션 기준). 종목 단위 격리."""
    asof = asof or date.today()
    with conn.cursor() as cur:
        cur.execute("SELECT ticker, market FROM watchlist WHERE active=TRUE ORDER BY ticker")
        universe = [(r["ticker"], r["market"]) for r in cur.fetchall()]

    out: list[dict] = []
    for ticker, market in universe:
        try:
            row = detect_for_ticker(conn, ticker, market, asof)
            if row:
                out.append(row)
        except Exception as exc:  # noqa: BLE001 — 종목 단위 격리
            logger.warning("이상움직임 감지 실패 %s: %s", ticker, exc)
    return out


def run(conn: psycopg.Connection, asof: Optional[date] = None) -> dict:
    """감지 → move_anomalies upsert. 반환 counts."""
    rows = detect_move_anomalies(conn, asof)
    n_unknown = 0
    with conn.cursor() as cur:
        for row in rows:
            if not row["explained"]:
                n_unknown += 1
            cur.execute(
                """
                INSERT INTO move_anomalies
                    (ticker, asof, ret_pct, z_score, excess_pct, direction,
                     idiosyncratic, attribution_class, explained, reason, sources)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (ticker, asof) DO UPDATE SET
                    ret_pct=EXCLUDED.ret_pct, z_score=EXCLUDED.z_score, excess_pct=EXCLUDED.excess_pct,
                    direction=EXCLUDED.direction, idiosyncratic=EXCLUDED.idiosyncratic,
                    attribution_class=EXCLUDED.attribution_class, explained=EXCLUDED.explained,
                    reason=EXCLUDED.reason, sources=EXCLUDED.sources
                """,
                (row["ticker"], row["asof"], row["ret_pct"], row["z_score"], row["excess_pct"],
                 row["direction"], row["idiosyncratic"], row["attribution_class"], row["explained"],
                 row["reason"], json.dumps(row["sources"], ensure_ascii=False)),
            )
    conn.commit()
    logger.info("이상움직임 감지: %d건(이유불명 %d) 저장", len(rows), n_unknown)
    return {"anomalies": len(rows), "unexplained": n_unknown}


def main() -> int:
    import os
    import sys

    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    if not os.getenv("DB_HOST"):
        try:
            from src.export_dashboard_data import _load_secrets
            _load_secrets()
        except Exception:
            pass
    from src.db import get_conn
    with get_conn() as conn:
        result = run(conn)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
