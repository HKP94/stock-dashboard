"""
compute_market_score.py — Wave 5-B 시장 매력도 점수(결정론)

"지금 투자 적합한 환경인가·어느 방향인가"를 지역(KR/US)별 0~100 점수 + 방향 + 신뢰도로 평가.
- 점수 코어는 전부 결정론(지수 추세·변동성·매크로·시장폭). 뉴스 심리는 LLM 해설 전용(여기 미사용).
- 시장→종목은 신규-A1 베타 경로로만(이 모듈은 시장 점수만 산출, composite 미변경).
- 정확도 가드: 컴포넌트 정합성·divergence 점검. 강하게 충돌하면 신뢰도 '하' + **점수도 50쪽으로 수축**.
- §F7: 지수=가격 기반 진짜 계산, 매크로=발표 시점(asof≤평가일)만(룩어헤드 금지).

분석 파이프라인(pipeline_analysis) 소관. 외부 수집·LLM 호출 없음.
"""

from __future__ import annotations

import logging
import os
import statistics
from datetime import date
from typing import Optional

import pandas as pd
import psycopg

from src.compute_quant import _fetch_index_closes
from src.schemas import MarketScoreRow

logger = logging.getLogger(__name__)

# ── 가중·임계 (config 상수, env 덮어쓰기) ──────────────────────────
MS_WEIGHTS = {"trend": 0.40, "vol": 0.25, "macro": 0.25, "breadth": 0.10}
MS_DIR_BULL = float(os.getenv("MARKET_SCORE_DIR_BULL", "60"))
MS_DIR_BEAR = float(os.getenv("MARKET_SCORE_DIR_BEAR", "40"))
MS_MIN_COMPONENTS = int(os.getenv("MARKET_SCORE_MIN_COMPONENTS", "3"))
# divergence(강한 충돌) 시 점수를 중립(50)으로 끌어당기는 강도 0~1(보수적 기본 0.6).
MS_SHRINK = float(os.getenv("MARKET_SCORE_SHRINK", "0.6"))
# 서브스코어 분산이 이 값 이상이고 부호가 섞이면 '강한 충돌'로 본다.
MS_CONFLICT_DISPERSION = float(os.getenv("MARKET_SCORE_CONFLICT_DISPERSION", "0.6"))

_BENCH = {"KR": "^KS11", "US": "^GSPC"}
_NEUTRAL = 50.0


def _num(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _trend_subscore(bench_df: pd.DataFrame) -> Optional[float]:
    """지수 추세: 종가 vs SMA200 + 최근 기울기. 진짜 계산(가격 기반)."""
    if bench_df is None or bench_df.empty or len(bench_df) < 30:
        return None
    closes = pd.to_numeric(bench_df["close"], errors="coerce").dropna()
    if len(closes) < 30:
        return None
    last = float(closes.iloc[-1])
    sma = float(closes.tail(200).mean())   # 가용분(≤200)
    if sma == 0:
        return None
    gap = last / sma - 1.0                  # +면 추세 위
    window = closes.tail(20)
    slope = (float(window.iloc[-1]) / float(window.iloc[0]) - 1.0) if float(window.iloc[0]) else 0.0
    # 갭 ±10% → ±1, 기울기 ±10% → ±1, 평균
    return _clip(0.5 * _clip(gap / 0.10) + 0.5 * _clip(slope / 0.10))


def _vol_subscore(vix: Optional[float]) -> Optional[float]:
    """변동성(VIX): <18 우호(+), 18~25 중립, >25 비우호(−). 선형."""
    if vix is None:
        return None
    if vix <= 18:
        return _clip((18 - vix) / 8)        # 18→0, 10→+1
    if vix >= 25:
        return _clip(-(vix - 25) / 10)      # 25→0, 35→−1
    return -_clip((vix - 18) / 7)           # 18~25 → 0~−1 완만


def _macro_subscore(macro: dict, region: str) -> Optional[float]:
    """매크로: 금리·10년물·달러 방향(보수적). 완화/약달러 → +, 긴축/강달러 → −.
    각 지표 Δ(latest−prev) 부호의 평균. §9 미해결(세부 매핑 보정 대상)."""
    signals: list[float] = []

    def _delta_sign(code: str, favorable_when_falling: bool = True) -> Optional[float]:
        pair = macro.get(code)
        if not pair or pair[0] is None or pair[1] is None:
            return None
        d = pair[0] - pair[1]
        if d == 0:
            return 0.0
        falling = d < 0
        good = falling if favorable_when_falling else (not falling)
        return 1.0 if good else -1.0

    rate_code = "FEDFUNDS" if region == "US" else "KR_BASE_RATE"
    for s in (_delta_sign(rate_code), _delta_sign("DGS10") if region == "US" else None, _delta_sign("DXY")):
        if s is not None:
            signals.append(s)
    if not signals:
        return None
    return _clip(sum(signals) / len(signals))


def _breadth_subscore(conn: psycopg.Connection, region: str) -> Optional[float]:
    """시장 폭: 활성 종목 정배열율(indicators_daily 최신). ≥55% +, ≤30% −."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT i.is_aligned
            FROM watchlist w
            JOIN LATERAL (
                SELECT is_aligned FROM indicators_daily d
                WHERE d.ticker = w.ticker ORDER BY d.date DESC LIMIT 1
            ) i ON TRUE
            WHERE w.active = TRUE AND w.market = %s
            """,
            (region,),
        )
        vals = [r["is_aligned"] for r in cur.fetchall() if r["is_aligned"] is not None]
    if len(vals) < 3:
        return None
    rate = sum(1 for v in vals if v) / len(vals)
    if rate >= 0.55:
        return _clip((rate - 0.55) / 0.35 + 0.3)   # 55%→+0.3, 90%→+1
    if rate <= 0.30:
        return _clip(-((0.30 - rate) / 0.30) - 0.3)
    return 0.0


def _load_macro_latest_prev(conn: psycopg.Connection, asof: date) -> dict:
    """지표별 (latest, prev) 값. asof≤평가일만(§F7 룩어헤드 금지)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT indicator_code, asof, value FROM macro_indicators
            WHERE asof <= %s ORDER BY indicator_code, asof DESC
            """,
            (asof,),
        )
        rows = cur.fetchall()
    grouped: dict[str, list[float]] = {}
    for r in rows:
        grouped.setdefault(r["indicator_code"], []).append(_num(r["value"]))
    return {code: (vals[0], vals[1] if len(vals) > 1 else None) for code, vals in grouped.items()}


def compute_region_score(
    region: str,
    bench_df: pd.DataFrame,
    vix: Optional[float],
    macro: dict,
    conn: psycopg.Connection,
) -> MarketScoreRow:
    asof = date.today()
    subs = {
        "trend": _trend_subscore(bench_df),
        "vol": _vol_subscore(vix),
        "macro": _macro_subscore(macro, region),
        "breadth": _breadth_subscore(conn, region),
    }
    present = {k: v for k, v in subs.items() if v is not None}

    # 가중 평균(있는 컴포넌트만 재정규화) → 0~100
    if present:
        wsum = sum(MS_WEIGHTS[k] for k in present)
        weighted = sum(MS_WEIGHTS[k] * v for k, v in present.items()) / wsum if wsum else 0.0
    else:
        weighted = 0.0
    raw_score = _NEUTRAL + 25.0 * weighted

    # 정합성/divergence
    vals = list(present.values())
    dispersion = statistics.pstdev(vals) if len(vals) >= 2 else 0.0
    mixed = any(v > 0.05 for v in vals) and any(v < -0.05 for v in vals)
    strong_conflict = mixed and dispersion >= MS_CONFLICT_DISPERSION
    divergence_note = None

    score = raw_score
    if len(present) < MS_MIN_COMPONENTS:
        confidence = "하"
        divergence_note = f"유효 지표 {len(present)}개(<{MS_MIN_COMPONENTS}) — 데이터 부족으로 방향 확신 낮음"
        # 데이터 부족도 50쪽으로 보수적 수축
        score = _NEUTRAL + (raw_score - _NEUTRAL) * (1 - MS_SHRINK)
    elif strong_conflict:
        confidence = "하"
        # 재료가 강하게 엇갈리면 방향 확신 못 함 → 점수도 중립으로 수축(강한 점수+낮은 신뢰도 조합 회피)
        score = _NEUTRAL + (raw_score - _NEUTRAL) * (1 - MS_SHRINK)
        pos = [k for k, v in present.items() if v > 0.05]
        neg = [k for k, v in present.items() if v < -0.05]
        divergence_note = f"재료 충돌({'·'.join(pos)} 우호 vs {'·'.join(neg)} 부담) — 방향 확신 낮춤, 점수 중립 수축"
    elif mixed:
        confidence = "중"
    else:
        confidence = "상" if len(present) >= MS_MIN_COMPONENTS else "중"

    score = round(max(0.0, min(100.0, score)), 1)
    direction = "강세" if score >= MS_DIR_BULL else ("약세" if score <= MS_DIR_BEAR else "중립")

    components = {
        "subscores": {k: round(v, 3) for k, v in subs.items() if v is not None},
        "missing": [k for k, v in subs.items() if v is None],
        "weights": MS_WEIGHTS,
        "raw_score": round(raw_score, 1),
        "dispersion": round(dispersion, 3),
        "vix": vix,
        "benchmark": _BENCH[region],
    }
    return MarketScoreRow(
        asof=asof, region=region, score=score, direction=direction,
        confidence=confidence, components=components, divergence_note=divergence_note,
    )


def compute_market_scores(conn: psycopg.Connection, asof: Optional[date] = None) -> list[MarketScoreRow]:
    """KR·US 시장 매력도 점수 산출(결정론). index_daily·macro_indicators·정배열율 저장 데이터 사용."""
    asof = asof or date.today()
    macro = _load_macro_latest_prev(conn, asof)
    vix_pair = macro.get("VIX")
    vix = vix_pair[0] if vix_pair else None

    rows: list[MarketScoreRow] = []
    for region in ("KR", "US"):
        bench_df = _fetch_index_closes(conn, _BENCH[region], 220)
        rows.append(compute_region_score(region, bench_df, vix, macro, conn))
    logger.info("market_score: %s", [(r.region, r.score, r.direction, r.confidence) for r in rows])
    return rows
