"""
export_dashboard_data.py — DB → dashboard-web/src/data.json (1회용 또는 자동 실행)

data.jsx의 window.ATLAS_DATA 구조와 정확히 일치하는 JSON을 생성한다:
  today, updated, rulesCount
  market.overall / market.kr / market.us / market.indices
  regimes (팩터 가중치)
  stocks[] (composites + factors + price + rsi + flags + 뉴스요약 + 퀀트)
  news[] (뉴스 피드)
  factorMeta (불변 상수)
  research (빈 기본값 — 리서치 노트는 UI 편집 전용)

실행:
  python -m src.export_dashboard_data
  또는: python src/export_dashboard_data.py

DB 접속: .streamlit/secrets.toml(DB_* 키) → .env(DATABASE_URL은 무시, DB_* 우선)
시크릿 자체는 로그·출력에 절대 포함하지 않는다.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from src.display_signals import compute_display_signals
from src.compute_quant import _market_benchmark  # 신규-A1: 종목 벤치마크 라벨용

# 신규-A1: 베타 벤치마크 코드 → 표시 라벨
_BETA_BENCHMARK_LABEL = {"^KS11": "코스피", "^KQ11": "코스닥", "^GSPC": "S&P500"}
from src.ingest_drivers import DRIVER_CATALOG
from src.strategies import RETROSPECTIVE_STRATEGIES, STRATEGY_BY_NAME, TRUE_STRATEGIES

logger = logging.getLogger(__name__)

# dashboard-web/src/data.json 출력 경로 (이 파일 기준으로 상대 경로)
_THIS = Path(__file__).resolve().parent.parent  # stock-dashboard/
_OUT = _THIS / "dashboard-web" / "src" / "data.json"


# ── 팩터 메타 (불변) ──────────────────────────────────────────────────
FACTOR_META = {
    "m": {"key": "momentum", "ko": "모멘텀", "group": "timing"},
    "v": {"key": "value", "ko": "가치", "group": "mispricing"},
    "q": {"key": "quality", "ko": "퀄리티", "group": "mispricing"},
    "g": {"key": "growth", "ko": "성장", "group": "mispricing"},
    "s": {"key": "sentiment", "ko": "감성", "group": "timing"},
}

CONTEXT_TYPE_LABEL = {
    "news_summary": "뉴스 요약",
    "report": "리포트",
    "driver": "핵심 동인",
    "macro": "거시",
}

REGIMES = {
    "bull":    {"label": "강세",  "color": "acc",  "w": {"m": 45, "v": 20, "q": 20, "g": 10, "s": 5}},
    "neutral": {"label": "중립",  "color": "warn", "w": {"m": 35, "v": 25, "q": 25, "g": 10, "s": 5}},
    "bear":    {"label": "약세",  "color": "bad",  "w": {"m": 10, "v": 35, "q": 45, "g":  5, "s": 5}},
}

# ── helpers ───────────────────────────────────────────────────────────
def _f(v) -> float | None:
    """None·NaN·Decimal → float or None."""
    if v is None:
        return None
    try:
        r = float(v)
        return None if math.isnan(r) or math.isinf(r) else r
    except (TypeError, ValueError):
        return None


def _infer_refresh_context(generated_at: datetime, price_asof_by_market: dict[str, str] | None) -> dict[str, str]:
    price_asof_by_market = price_asof_by_market or {}
    kr = price_asof_by_market.get("KR")
    us = price_asof_by_market.get("US")

    if kr and us:
        mode = "kr_close" if kr > us else "us_close"
    else:
        mode = "kr_close" if 12 <= generated_at.hour < 23 else "us_close"

    if mode == "kr_close":
        return {
            "mode": mode,
            "label": "한국 종가 기준 (18시 갱신)",
            "note": "KR 가격·뉴스는 당일 기준으로 최신이며, US 가격은 전날 종가 기준입니다.",
        }
    return {
        "mode": mode,
        "label": "미국 종가 기준 (06시 갱신)",
        "note": "미국 시장 종가 반영 전체 갱신본입니다. KR과 US 가격·뉴스가 일일 기본 주기로 정렬됩니다.",
    }


# PR-1(진단): 폴백 요약은 단일 출처(enrich_gemini)로 판정 — '분석 실패'/'일시 보류' 비노출.
from src.enrich_gemini import is_fallback_summary as _is_fallback_summary


# PR-1: 스크리너 '장기 보유 = 안전마진' 복합 기준 (PRD §F4-스크리너)
# F-Score 단일 7+ 필터가 구조적으로 비어(실질 만점 7) 단일필터 폐기 → 가치·퀄리티·재무건전성 가중합.
SAFETY_WEIGHTS = {"value": 0.40, "quality": 0.35, "soundness": 0.25}
FSCORE_MAX_EFF = 7   # 신호 7·8(발행주식수·매출총이익률) 미수집 → 실질 만점 7
SAFETY_FLOOR = 55    # 장기보유 후보 최소 안전마진(미만이면 후보 제외)


def _soundness_score(fscore, roe, debt_ratio) -> float:
    """재무건전성 0~100. F-Score 있으면 우선(fscore/7*100), 없으면 ROE·부채비율로 대체."""
    if fscore is not None:
        return max(0.0, min(100.0, fscore / FSCORE_MAX_EFF * 100.0))
    # 대체: ROE(높을수록↑, 20%→100) + 부채비율(낮을수록↑, 0%→100·200%→0) 평균
    sub = []
    if roe is not None:
        sub.append(max(0.0, min(100.0, (roe / 0.20) * 100.0)))
    if debt_ratio is not None:
        sub.append(max(0.0, min(100.0, 100.0 - (debt_ratio / 200.0) * 100.0)))
    return round(sum(sub) / len(sub), 1) if sub else 50.0


def _safety_margin(value_f, quality_f, fscore, roe, debt_ratio):
    """안전마진 점수(0~100)와 구성요소. value/quality는 팩터점수(0~100, 높을수록 저평가/우량)."""
    v = float(value_f) if value_f is not None else 50.0
    q = float(quality_f) if quality_f is not None else 50.0
    s = _soundness_score(fscore, roe, debt_ratio)
    score = SAFETY_WEIGHTS["value"] * v + SAFETY_WEIGHTS["quality"] * q + SAFETY_WEIGHTS["soundness"] * s
    return round(score, 1), {"v": round(v), "q": round(q), "s": round(s)}


def _safety_reason(per, pbr, roe, debt_ratio, fscore) -> str:
    """'왜 장기보유 후보인가' 근거 1줄 — 충족 항목만 자연어로."""
    bits = []
    if per is not None and per > 0 and per < 15: bits.append(f"저PER {per:.1f}")
    if pbr is not None and pbr > 0 and pbr < 1.5: bits.append(f"저PBR {pbr:.2f}")
    if roe is not None and roe >= 0.15: bits.append(f"고ROE {roe*100:.0f}%")
    if debt_ratio is not None and debt_ratio < 100: bits.append(f"저부채 {debt_ratio:.0f}%")
    if fscore is not None and fscore >= 6: bits.append(f"F-Score {fscore}")
    if not bits:
        return "가치·퀄리티·재무건전성 종합 상위"
    return " · ".join(bits) + " 기반 안전마진 우위"


# E-1: 트레이딩 관점 신호 임계값 (결정론, LLM 미사용)
_TRADING_RSI_LOW  = 35
_TRADING_RSI_HIGH = 65
_TRADING_BB_LOW   = 0.2
_TRADING_BB_HIGH  = 0.8


def _format_investor_flow(row: dict | None, market: str) -> dict | None:
    """E-2: investor_flow DB 행 → export JSON 형식.
    KR만 유효 데이터 반환, US는 명시적 None (구조적 부재).
    §F7: T+0 과거 데이터, 룩어헤드 없음."""
    if market != "KR":
        return None
    if row is None:
        return None

    def _f(v) -> float | None:
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    return {
        "foreignNet3d":      _f(row.get("foreign_3d_sum")),
        "institutionNet3d":  _f(row.get("institution_3d_sum")),
        "foreignSignal":     row.get("foreign_signal"),
        "institutionSignal": row.get("institution_signal"),
        "combinedSignal":    row.get("combined_signal"),
        "asof":              str(row.get("date", "")),
    }


def _compute_trading_signal(
    rsi14: float | None,
    bb_pct: float | None,
    macd_hist: float | None,
    vol_ratio20: float | None,
    stoch_k: float | None = None,
    trading_signal_db: str | None = None,
    trading_signal_score_db: int | None = None,
) -> dict:
    """4팩터(MACD/볼린저/RSI/스토캐스틱) 트레이딩 신호.
    DB 저장값이 있으면 우선 사용(결정론 일관성 + 신규-F 적중률 추적 토대).
    반환: {label, score, basis, volNote}
    """
    # DB 저장값 우선 (compute_indicators에서 이미 계산·저장)
    if trading_signal_db is not None:
        label = trading_signal_db
        score = trading_signal_score_db or 0
    else:
        score = 0
        if macd_hist is not None:
            score += 1 if macd_hist > 0 else (-1 if macd_hist < 0 else 0)
        if bb_pct is not None:
            score += 1 if bb_pct < _TRADING_BB_LOW else (-1 if bb_pct > _TRADING_BB_HIGH else 0)
        if rsi14 is not None:
            score += 1 if rsi14 < _TRADING_RSI_LOW else (-1 if rsi14 > _TRADING_RSI_HIGH else 0)
        if stoch_k is not None:
            score += 1 if stoch_k < 20 else (-1 if stoch_k > 80 else 0)
        label = "단기매수우호" if score >= 2 else ("단기회피" if score <= -2 else "중립")

    # basis는 항상 현재 지표 값으로 재구성 (표시용)
    basis: list[dict] = []
    if macd_hist is not None and macd_hist != 0:
        basis.append({"source": "MACD", "value": "양(0선 위)" if macd_hist > 0 else "음(0선 아래)"})
    if bb_pct is not None and (bb_pct < _TRADING_BB_LOW or bb_pct > _TRADING_BB_HIGH):
        basis.append({"source": "BB%B", "value": f"{bb_pct:.2f}({'하단' if bb_pct < _TRADING_BB_LOW else '상단'} 접근)"})
    if rsi14 is not None and (rsi14 < _TRADING_RSI_LOW or rsi14 > _TRADING_RSI_HIGH):
        basis.append({"source": "RSI", "value": f"{rsi14:.0f}({'과매도' if rsi14 < _TRADING_RSI_LOW else '과매수'})"})
    if stoch_k is not None and (stoch_k < 20 or stoch_k > 80):
        basis.append({"source": "Stoch", "value": f"{stoch_k:.0f}({'과매도' if stoch_k < 20 else '과매수'})"})

    vol_note = None
    if vol_ratio20 is not None and vol_ratio20 >= 2.0:
        vol_note = f"거래량 평균 대비 {vol_ratio20:.1f}배 급증"

    return {"label": label, "score": score, "basis": basis, "volNote": vol_note}


def _rule_based_insight(close, chg, rsi, comp, sent, has_data) -> str:
    """실제 뉴스 요약이 없을 때 보여줄 '규칙기반 한 줄 인사이트'(수치+해석).
    '분석 실패' 원문 대신 결정론적 한 줄을 항상 채운다."""
    if not has_data or close is None:
        return "데이터 수집 중 — 가격·지표가 채워지면 분석이 표시됩니다."
    parts: list[str] = []
    if chg is not None:
        d = "상승" if chg > 0 else ("하락" if chg < 0 else "보합")
        parts.append(f"전일대비 {chg:+.1f}%({d})")
    if rsi is not None:
        zone = "과열권" if rsi >= 70 else ("침체권" if rsi <= 30 else "중립권")
        parts.append(f"RSI {rsi:.0f}({zone})")
    if comp is not None:
        tier = "상위" if comp >= 60 else ("하위" if comp < 40 else "중간")
        parts.append(f"퀀트 종합 {comp:.0f}({tier})")
    head = " · ".join(parts) if parts else "주요 지표 집계 중"
    return f"뉴스 요약 준비 중 — 현재 {head}, 뉴스 심리 '{sent}'. 원문 기사와 지표를 참고하세요."


def _load_secrets() -> None:
    """DB_* 환경변수를 .streamlit/secrets.toml에서 채운다 (이미 env에 있으면 유지)."""
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        import tomli as tomllib  # pip install tomli

    secrets_path = _THIS / ".streamlit" / "secrets.toml"
    if not secrets_path.exists():
        return
    with open(secrets_path, "rb") as f:
        s = tomllib.load(f)
    for k in ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME"):
        if k in s and not os.environ.get(k):
            os.environ[k] = str(s[k])


# ── 시장 레짐 판정 ────────────────────────────────────────────────────
def _detect_regime(conn) -> dict:
    """
    market_daily 최신 레코드로 단순 레짐 판정:
      bull   = KOSPI > kospi_sma200 AND SP500 > sp_sma200 AND VIX < 20
      bear   = (KOSPI < kospi_sma200 OR SP500 < sp_sma200) AND VIX > 25
      neutral = otherwise
    반환: {"overall": "neutral", "kr_basis": str, "us_basis": str}
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT asof, kospi, kosdaq, sp500, nasdaq, vix, usdkrw
        FROM market_daily
        ORDER BY asof DESC LIMIT 30
    """)
    rows = cur.fetchall()
    if not rows:
        return {"overall": "neutral", "kr_basis": "시장 데이터 없음", "us_basis": "시장 데이터 없음"}

    latest = rows[0]
    asof      = latest["asof"]
    kospi     = _f(latest["kospi"])
    sp500     = _f(latest["sp500"])
    vix       = _f(latest["vix"])
    usdkrw    = _f(latest["usdkrw"])

    # 이동평균(200일≈취득 가능 최대값)
    kospi_vals = [_f(r["kospi"]) for r in rows if _f(r["kospi"]) is not None]
    sp_vals    = [_f(r["sp500"]) for r in rows if _f(r["sp500"]) is not None]
    kospi_ma   = sum(kospi_vals) / len(kospi_vals) if kospi_vals else None
    sp_ma      = sum(sp_vals) / len(sp_vals) if sp_vals else None

    above_kospi = (kospi > kospi_ma) if (kospi and kospi_ma) else None
    above_sp    = (sp500 > sp_ma)    if (sp500 and sp_ma) else None
    vix_ok      = (vix < 20)         if vix else None
    vix_high    = (vix > 25)         if vix else None

    if above_kospi and above_sp and vix_ok:
        overall = "bull"
    elif (above_kospi is False or above_sp is False) and vix_high:
        overall = "bear"
    else:
        overall = "neutral"

    kr_above = "위" if above_kospi else ("아래" if above_kospi is False else "—")
    sp_above = "위" if above_sp   else ("아래" if above_sp   is False else "—")
    vix_str  = f"{vix:.1f}" if vix else "—"
    kw_str   = f"{usdkrw:.0f}" if usdkrw else "—"

    kr_basis = f"KOSPI 이동평균 {kr_above}, USD/KRW {kw_str} → {REGIMES[overall]['label']} 레짐, 모멘텀 가중 {REGIMES[overall]['w']['m']}%"
    us_basis = f"S&P500 이동평균 {sp_above}, VIX {vix_str}({'안정' if vix_ok else '주의' if vix else '—'}) → {REGIMES[overall]['label']} 레짐, 모멘텀 가중 {REGIMES[overall]['w']['m']}%"

    return {"overall": overall, "kr_basis": kr_basis, "us_basis": us_basis, "asof": str(asof)}


# ── market_daily 마켓 섹션 구성 ────────────────────────────────────────
def _build_market(conn, regime_info: dict) -> dict:
    cur = conn.cursor()
    cur.execute("""
        SELECT asof, kospi, kosdaq, sp500, nasdaq, vix, usdkrw, ust10y,
               summary_md, summary_kr_md, summary_us_md, payload
        FROM market_daily ORDER BY asof DESC LIMIT 10
    """)
    rows = cur.fetchall()
    if not rows:
        return {"overall": regime_info["overall"], "indices": [], "kr": {}, "us": {}}

    latest = rows[0]
    payload = latest["payload"] if isinstance(latest["payload"], dict) else {}
    changes = payload.get("changes", {}) or {}

    def prev_distinct(field: str, cur_val: float | None) -> float | None:
        """최신값과 '의미있게' 다른 첫 이전 행의 값(주말 carry-over 회피).
        상대 오차 1e-5(0.001%) 이내는 동일값(carry-over)으로 보고 건너뛴다."""
        if cur_val is None:
            return None
        for r in rows[1:]:
            v = _f(r[field])
            if v is None:
                continue
            denom = abs(cur_val) or 1.0
            if abs(v - cur_val) / denom > 1e-5:
                return v
        return None

    def chg_for(field: str, cur_val: float | None) -> float | None:
        """PR-4: ingest가 저장한 payload.changes를 우선 사용, 없으면 prev_distinct 폴백."""
        c = changes.get(field)
        if c is not None:
            try:
                return round(float(c), 2)
            except (TypeError, ValueError):
                pass
        b = prev_distinct(field, cur_val)
        if cur_val is None or b is None or b == 0:
            return None
        return round((cur_val - b) / b * 100, 2)

    def fmt_num(v, dec=2):
        v = _f(v)
        if v is None:
            return "—"
        return f"{v:,.{dec}f}"

    ko  = _f(latest["kospi"]);  kq = _f(latest["kosdaq"])
    sp  = _f(latest["sp500"]);  nq = _f(latest["nasdaq"])
    vx  = _f(latest["vix"]);    kw = _f(latest["usdkrw"]);  t10 = _f(latest["ust10y"])
    summary_md    = latest["summary_md"] or ""
    summary_kr_md = latest["summary_kr_md"] or ""
    summary_us_md = latest["summary_us_md"] or ""

    indices = [
        {"k": "KOSPI",   "v": fmt_num(ko, 2), "chg": chg_for("kospi", ko),   "mk": "KR"},
        {"k": "KOSDAQ",  "v": fmt_num(kq, 2), "chg": chg_for("kosdaq", kq),  "mk": "KR"},
        {"k": "S&P 500", "v": fmt_num(sp, 2), "chg": chg_for("sp500", sp),   "mk": "US"},
        {"k": "NASDAQ",  "v": fmt_num(nq, 2), "chg": chg_for("nasdaq", nq),  "mk": "US"},
        {"k": "VIX",     "v": fmt_num(vx, 2), "chg": chg_for("vix", vx),     "mk": "US", "inv": True},
        {"k": "USD/KRW", "v": fmt_num(kw, 2), "chg": chg_for("usdkrw", kw),  "mk": "KR", "inv": True},
    ]

    overall = regime_info["overall"]

    def _bullets(md: str, fallback: str) -> str:
        bl = [l.lstrip("- ").strip() for l in md.split("\n") if l.strip().startswith("-")]
        return (" ".join(bl[:2]) if bl else md[:200]) or fallback

    # PR-3: 폴백(시황 미생성)도 '수치 + 간단 해석' 한 줄이 나오도록 규칙 기반 인사이트 생성
    def _kr_fallback() -> str:
        ck, cq = chg_for("kospi", ko), chg_for("kosdaq", kq)
        cw = chg_for("usdkrw", kw)
        if ck is not None and cq is not None:
            tone = "동반 상승해 위험선호가 우위" if ck > 0 and cq > 0 else \
                   "동반 하락해 위험회피 심리" if ck < 0 and cq < 0 else "혼조세"
            fx = f" 환율은 {'상승해 외국인 수급에 부담' if (cw or 0) > 0 else '하락해 수급에 우호적'}" if cw is not None else ""
            return f"KOSPI {ck:+.2f}%·KOSDAQ {cq:+.2f}% {tone}.{fx} (시황 자동요약 생성 전 폴백)"
        return f"최근 KOSPI {fmt_num(ko, 0)}, KOSDAQ {fmt_num(kq, 0)}, USD/KRW {fmt_num(kw, 0)}. (시황 폴백)"

    def _us_fallback() -> str:
        cs, cn = chg_for("sp500", sp), chg_for("nasdaq", nq)
        if cs is not None and cn is not None:
            tone = "동반 상승해 위험선호 우위" if cs > 0 and cn > 0 else \
                   "동반 하락해 경계 심리" if cs < 0 and cn < 0 else "혼조세"
            vix_note = f" VIX {fmt_num(vx,1)}로 {'변동성 안정' if (vx or 99) < 20 else '변동성 경계'}" if vx else ""
            return f"S&P500 {cs:+.2f}%·NASDAQ {cn:+.2f}% {tone}.{vix_note} (시황 자동요약 생성 전 폴백)"
        return f"S&P500 {fmt_num(sp, 0)}, NASDAQ {fmt_num(nq, 0)}, VIX {fmt_num(vx, 1)}. (시황 폴백)"

    kr = {
        "regime": "neutral",
        "idx": [{"k": "KOSPI",  "v": fmt_num(ko, 2), "chg": chg_for("kospi", ko)},
                {"k": "KOSDAQ", "v": fmt_num(kq, 2), "chg": chg_for("kosdaq", kq)}],
        "gauges": [{"label": "KOSPI RSI(14)", "v": 50, "unit": "", "tone": "neutral"}],
        "summary": _bullets(summary_kr_md, _kr_fallback()),
        "summaryMd": summary_kr_md,            # PR-4: 한국 전용
        "regimeBasis": regime_info.get("kr_basis", ""),
    }
    us = {
        "regime": overall if overall == "bull" else "neutral",
        "idx": [{"k": "S&P 500", "v": fmt_num(sp, 2), "chg": chg_for("sp500", sp)},
                {"k": "NASDAQ",  "v": fmt_num(nq, 2), "chg": chg_for("nasdaq", nq)}],
        "gauges": [{"label": "VIX (변동성)", "v": round(vx, 1) if vx else 0, "unit": "", "tone": "ok" if vx and vx < 20 else "warn", "inv": True}],
        "summary": _bullets(summary_us_md, _us_fallback()),
        "summaryMd": summary_us_md,            # PR-4: 미국 전용
        "regimeBasis": regime_info.get("us_basis", ""),
    }

    cur.execute("""
        SELECT summary_date, kr_summary, us_summary, global_summary
        FROM market_news_summary
        ORDER BY summary_date DESC, created_at DESC
        LIMIT 1
    """)
    digest = cur.fetchone()
    news_summary = {
        "asof": str(digest["summary_date"]) if digest else None,
        "krSummary": (digest["kr_summary"] or "") if digest else "",
        "usSummary": (digest["us_summary"] or "") if digest else "",
        "globalSummary": (digest["global_summary"] or "") if digest else "",
    }

    macro = _load_macro(conn)

    return {"overall": overall, "indices": indices, "kr": kr, "us": us,
            "summaryMd": summary_md, "newsSummary": news_summary, "macro": macro}


def _build_macro_payload(rows: list[dict], summary_row: dict | None) -> dict:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        casted = dict(row)
        casted["value"] = _f(casted.get("value"))
        grouped.setdefault(casted["indicator_code"], []).append(casted)
    for items in grouped.values():
        items.sort(key=lambda item: item["asof"], reverse=True)

    def _delta(items: list[dict], days: int, window: int = 35) -> float | None:
        if len(items) < 2 or items[0].get("value") is None:
            return None
        latest = items[0]
        for prev in items[1:]:
            gap = (latest["asof"] - prev["asof"]).days
            if gap >= days and gap <= window:
                return round(float(latest["value"]) - float(prev["value"]), 4)
        return None

    ordered: list[dict] = []
    for code, items in grouped.items():
        latest = items[0]
        ordered.append({
            "code": code,
            "name": latest["indicator_name"],
            "region": latest["region"],
            "asof": str(latest["asof"]),
            "value": latest["value"],
            "unit": latest["unit"],
            "source": latest["source"],
            "deltaDay": _delta(items, 1, 8),
            "deltaMonth": _delta(items, 28, 62),
            "series": [{"date": str(item["asof"]), "value": item["value"]} for item in reversed(items[:24]) if item.get("value") is not None],
        })
    ordered.sort(key=lambda item: (item["region"], item["name"]))

    by_region = {"KR": [], "US": [], "GLOBAL": []}
    for item in ordered:
        by_region.setdefault(item["region"], []).append(item)

    summary = {
        "headline": summary_row["headline"] if summary_row else "",
        "support": summary_row["support_view"] if summary_row else "",
        "oppose": summary_row["oppose_view"] if summary_row else "",
        "watchPoints": list(summary_row.get("watch_points") or []) if summary_row else [],
        "summaryMd": summary_row["summary_md"] if summary_row else "",
    }

    return {
        "asof": str(summary_row["summary_date"]) if summary_row else (ordered[0]["asof"] if ordered else None),
        "summary": summary,
        "indicators": ordered,
        "regions": by_region,
    }


def _load_macro(conn) -> dict:
    cur = conn.cursor()
    cutoff = (date.today() - timedelta(days=400)).isoformat()
    cur.execute(
        """
        SELECT indicator_code, indicator_name, region, asof, value, unit, source
        FROM macro_indicators
        WHERE asof >= %s
        ORDER BY indicator_code, asof DESC
        """,
        (cutoff,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.execute(
        """
        SELECT summary_date, headline, support_view, oppose_view, watch_points, summary_md
        FROM macro_summary
        ORDER BY summary_date DESC, created_at DESC
        LIMIT 1
        """
    )
    summary_row = cur.fetchone()
    return _build_macro_payload(rows, dict(summary_row) if summary_row else None)


def _driver_implication(code: str, latest: dict, previous: dict | None) -> dict:
    meta = DRIVER_CATALOG.get(code)
    if not latest or latest.get("close") is None:
        return {"tone": "neutral", "text": "가격 프록시가 아직 없어 방향 해석을 보류합니다."}
    if not previous or previous.get("close") in (None, 0):
        return {"tone": "neutral", "text": "최근 추세 데이터가 부족해 방향성 해석을 보류합니다."}
    delta = round((float(latest["close"]) - float(previous["close"])) / float(previous["close"]) * 100, 2)
    if abs(delta) < 0.2 or not meta or meta.effect_sign == 0:
        return {"tone": "neutral", "text": "최근 변동이 크지 않아 영향도 판단은 중립으로 둡니다."}
    signed = delta * meta.effect_sign
    tone = "support" if signed > 0 else "oppose"
    direction = "상승" if delta > 0 else "하락"
    text = f"{meta.name}이(가) 최근 {abs(delta):.1f}% {direction}해 이 종목에는 {'우호적' if tone == 'support' else '부담'}일 수 있습니다."
    return {"tone": tone, "text": text}


def _build_driver_cards(driver_rows: list[dict], price_rows: dict[str, list[dict]]) -> list[dict]:
    cards: list[dict] = []
    for row in sorted(driver_rows, key=lambda item: (-int(item.get("weight") or 0), item["driver_name"])):
        code = row["driver_code"]
        series = sorted(price_rows.get(code, []), key=lambda item: item["asof"])
        latest = series[-1] if series else None
        previous = series[-2] if len(series) >= 2 else None
        delta_day = None
        if latest and previous and previous.get("close") not in (None, 0):
            delta_day = round((float(latest["close"]) - float(previous["close"])) / float(previous["close"]) * 100, 2)
        month_base = next((item for item in reversed(series[:-1]) if (latest["asof"] - item["asof"]).days >= 28), None) if latest else None
        delta_month = None
        if latest and month_base and month_base.get("close") not in (None, 0):
            delta_month = round((float(latest["close"]) - float(month_base["close"])) / float(month_base["close"]) * 100, 2)
        cards.append({
            "code": code,
            "name": row["driver_name"],
            "driverSource": row["driver_source"],
            "weight": int(row["weight"]),
            "origin": row["origin"],
            "badge": "추정" if row["origin"] == "auto" else "사용자",
            "rationale": row["rationale"],
            "asof": str(latest["asof"]) if latest else None,
            "price": _f(latest["close"]) if latest else None,
            "deltaDay": delta_day,
            "deltaMonth": delta_month,
            "series": [{"date": str(item["asof"]), "value": _f(item["close"])} for item in series[-24:]],
            "implication": _driver_implication(code, latest, month_base or previous),
        })
    return cards


def _load_driver_cards(conn, tickers: list[str]) -> dict[str, list[dict]]:
    if not tickers:
        return {}
    cur = conn.cursor()
    cur.execute(
        """
        SELECT ticker, driver_code, driver_name, driver_source, weight, origin, rationale
        FROM ticker_drivers
        WHERE ticker = ANY(%s)
        ORDER BY ticker, weight DESC, updated_at DESC
        """,
        (tickers,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    if not rows:
        return {}
    codes_by_source = {"shared_macro": set(), "shared_index": set(), "yfinance_proxy": set(), "proxy_none": set()}
    for row in rows:
        codes_by_source.setdefault(row["driver_source"], set()).add(row["driver_code"])

    price_rows: dict[str, list[dict]] = {}
    cutoff = (date.today() - timedelta(days=200)).isoformat()

    if codes_by_source["shared_macro"]:
        cur.execute(
            """
            SELECT indicator_code AS code, asof, value AS close
            FROM macro_indicators
            WHERE indicator_code = ANY(%s) AND asof >= %s
            ORDER BY indicator_code, asof ASC
            """,
            (list(codes_by_source["shared_macro"]), cutoff),
        )
        for row in cur.fetchall():
            price_rows.setdefault(row["code"], []).append({"asof": row["asof"], "close": _f(row["close"])})

    if codes_by_source["shared_index"]:
        cur.execute(
            """
            SELECT index_code AS code, asof, close
            FROM index_daily
            WHERE index_code = ANY(%s) AND asof >= %s
            ORDER BY index_code, asof ASC
            """,
            (list(codes_by_source["shared_index"]), cutoff),
        )
        for row in cur.fetchall():
            price_rows.setdefault(row["code"], []).append({"asof": row["asof"], "close": _f(row["close"])})

    if codes_by_source["yfinance_proxy"]:
        cur.execute(
            """
            SELECT driver_code AS code, asof, close
            FROM driver_prices
            WHERE driver_code = ANY(%s) AND asof >= %s
            ORDER BY driver_code, asof ASC
            """,
            (list(codes_by_source["yfinance_proxy"]), cutoff),
        )
        for row in cur.fetchall():
            price_rows.setdefault(row["code"], []).append({"asof": row["asof"], "close": _f(row["close"])})

    grouped: dict[str, list[dict]] = {}
    for ticker in tickers:
        grouped[ticker] = _build_driver_cards([row for row in rows if row["ticker"] == ticker], price_rows)
    return grouped


# ── 종목 가격·거래량 시계열 (6개월) ──────────────────────────────────
def _build_price_series(ticker: str, conn) -> tuple[list[float], list[float | None]]:
    """prices_daily에서 최근 130거래일 종가·거래량을 반환 (오래된 순).
    Returns: (close_series, volume_series)
    """
    cur = conn.cursor()
    cutoff = (date.today() - timedelta(days=200)).isoformat()
    cur.execute(
        "SELECT date, close, volume FROM prices_daily WHERE ticker=%s AND date>=%s AND close IS NOT NULL ORDER BY date ASC LIMIT 130",
        (ticker, cutoff),
    )
    rows = cur.fetchall()
    closes  = [_f(r["close"])  for r in rows if _f(r["close"]) is not None]
    volumes = [_f(r["volume"]) for r in rows if _f(r["close"]) is not None]
    return closes, volumes


def _sma(series: list[float], w: int) -> float | None:
    if len(series) < w:
        return None
    return round(sum(series[-w:]) / w, 2)


def _spark(series: list[float], n: int = 16) -> list[float]:
    """시리즈의 마지막 n개 값을 0~100 범위 스케일로 정규화해 스파크라인용으로 반환."""
    if not series:
        return [50] * n
    slc = series[-n:] if len(series) >= n else series
    mn, mx = min(slc), max(slc)
    rng = mx - mn or 1
    return [round((v - mn) / rng * 100) for v in slc]


# PR-3: 플래그 분류 패턴
_DATA_QUALITY_RE = re.compile(r"데이터 부족|사전필터 제외|발행주식수 데이터 없음|데이터 없음")

def _split_flags(flags: list[str]) -> tuple[list[str], list[str]]:
    """flags → (action_signals, data_quality_items)"""
    action, quality = [], []
    for f in flags:
        if _DATA_QUALITY_RE.search(f):
            quality.append(f)
        else:
            action.append(f)
    return action, quality


def _attach_display_signals(stocks: list[dict]) -> None:
    rows = [
        {
            "ticker": stock["t"],
            "composite": stock.get("comp"),
            "momentum": stock.get("f", {}).get("m"),
            "value": stock.get("f", {}).get("v"),
            "quality": stock.get("f", {}).get("q"),
            "growth": stock.get("f", {}).get("g"),
            "sentiment": stock.get("f", {}).get("s"),
        }
        for stock in stocks
    ]
    signals = compute_display_signals(rows)
    for stock in stocks:
        signal = signals.get(stock["t"])
        stock["signal"] = signal.model_dump() if signal else None


# ── PR-2: 포트폴리오 holdings 로드 ────────────────────────────────────
def _load_portfolio(conn) -> dict[str, dict]:
    """portfolio_holdings + 최신 portfolio 평가 결과 → {ticker: info}."""
    cur = conn.cursor()
    holdings: dict[str, dict] = {}
    cur.execute("SELECT ticker, qty, avg_price, currency FROM portfolio_holdings WHERE qty > 0")
    for r in cur.fetchall():
        holdings[r["ticker"]] = {"qty": _f(r["qty"]), "avg_price": _f(r["avg_price"]), "currency": r["currency"]}
    if not holdings:
        return {}
    # 최신 평가 결과
    cur.execute("""
        SELECT p.ticker, p.cur_price, p.eval_amount, p.pnl, p.pnl_pct
        FROM portfolio p
        WHERE p.asof = (SELECT max(asof) FROM portfolio p2 WHERE p2.ticker = p.ticker)
        AND p.ticker = ANY(%s)
    """, (list(holdings.keys()),))
    for r in cur.fetchall():
        tk = r["ticker"]
        if tk in holdings:
            holdings[tk].update({
                "cur_price":   _f(r["cur_price"]),
                "eval_amount": _f(r["eval_amount"]),
                "pnl":         _f(r["pnl"]),
                "pnl_pct":     _f(r["pnl_pct"]),
            })
    return holdings


def _load_portfolio_snapshot(conn) -> dict:
    """최신 portfolio_snapshot → KRW 환산 총계 + 통화별 분해 (PR-3)."""
    cur = conn.cursor()
    cur.execute("SELECT total_value, total_cost, total_pnl, payload FROM portfolio_snapshot ORDER BY asof DESC LIMIT 1")
    r = cur.fetchone()
    if not r:
        return {}
    payload = r["payload"] or {}
    return {
        "total_eval":    _f(r["total_value"]),   # KRW 환산 평가금액
        "total_cost":    _f(r["total_cost"]),    # KRW 환산 원가
        "total_pnl":     _f(r["total_pnl"]),     # KRW 환산 손익
        "total_pnl_pct": payload.get("pnl_pct"),
        "n_holdings":    payload.get("n_holdings"),
        "currency":      "KRW",
        "fx_rate":       payload.get("fx_rate"),
        "fx_missing":    payload.get("fx_missing", False),
        "by_currency":   payload.get("by_currency", {}),
        "cash_total":    payload.get("cash_total", 0),       # PR-2: 현금(KRW 환산)
        "asset_total":   payload.get("asset_total"),         # PR-2: 총자산(주식+현금)
        "cash_by_currency": payload.get("cash_by_currency", {}),
    }


# ── PR-7: 백테스트 / 회고 로드 ────────────────────────────────────────
def _load_backtest(conn) -> dict:
    """backtest_results → separated true/retrospective strategy payload."""
    cur = conn.cursor()
    cur.execute("""
        SELECT strategy, track, horizon, cum_return, cagr, mdd, sharpe, regime_returns, payload
        FROM backtest_results
        WHERE strategy IS NOT NULL AND track IS NOT NULL AND horizon IS NOT NULL
    """)
    rows = [dict(r) for r in cur.fetchall()]
    grouped: dict[str, dict[str, dict]] = {"true": {}, "retrospective": {}}
    retro_warning = ""
    retro_asof = None

    for row in rows:
        track = row["track"]
        if track not in grouped:
            continue
        payload = row["payload"] or {}
        name = row["strategy"]
        meta = STRATEGY_BY_NAME.get(name)
        strategy = grouped[track].setdefault(
            name,
            {
                "name": name,
                "label": payload.get("label") or (meta.label if meta else name),
                "description": payload.get("description") or (meta.description if meta else ""),
                "horizons": {},
            },
        )
        strategy["horizons"][row["horizon"]] = {
            "cumReturn": _f(row["cum_return"]),
            "cagr": _f(row["cagr"]),
            "mdd": _f(row["mdd"]),
            "sharpe": _f(row["sharpe"]),
            "regimeReturns": row["regime_returns"] or {},
            "equityCurve": payload.get("equity_curve", []),
            "benchmarks": payload.get("benchmarks", {}),
            "selectionExamples": payload.get("selection_examples", []),
            "selectedTickers": payload.get("selected_tickers", []),
            "warning": payload.get("warning", ""),
            "window": {"start": payload.get("window_start"), "end": payload.get("window_end")},
        }
        if track == "retrospective":
            retro_warning = payload.get("warning") or retro_warning
            retro_asof = payload.get("asof") or retro_asof

    true_order = {s.name: i for i, s in enumerate(TRUE_STRATEGIES)}
    retro_order = {s.name: i for i, s in enumerate(RETROSPECTIVE_STRATEGIES)}
    true_strategies = sorted(grouped["true"].values(), key=lambda s: true_order.get(s["name"], 99))
    retro_strategies = sorted(grouped["retrospective"].values(), key=lambda s: retro_order.get(s["name"], 99))

    return {
        "trueTrack": {"strategies": true_strategies},
        "retrospective": {"strategies": retro_strategies, "warning": retro_warning, "asof": retro_asof},
    }


_REGIME_GUIDANCE_LABEL = {"bull": "상승", "neutral": "횡보", "bear": "하락"}


def _build_strategy_guidance(backtest: dict, market: dict) -> dict | None:
    regime = (market or {}).get("overall")
    if regime not in _REGIME_GUIDANCE_LABEL:
        return None

    def _fmt(v: float | None) -> str:
        if v is None:
            return "—"
        sign = "+" if v >= 0 else ""
        return f"{sign}{v * 100:.1f}%"

    def _pick_best(strategies: list[dict], track: str) -> tuple[dict | None, float | None]:
        scored = []
        for s in strategies or []:
            for horizon in ("5y", "3y", "1y"):
                h = (s.get("horizons") or {}).get(horizon)
                if not h:
                    continue
                rr = (h.get("regimeReturns") or {}).get(regime)
                if rr is None:
                    continue
                scored.append((float(rr), {
                    "name": s.get("name"),
                    "label": s.get("label") or s.get("name"),
                    "track": track,
                    "horizon": horizon,
                    "regimeReturn": float(rr),
                }))
                break
        if not scored:
            return None, None
        scored.sort(key=lambda item: item[0], reverse=True)
        best = scored[0][1]
        next_score = scored[1][0] if len(scored) > 1 else None
        edge = (best["regimeReturn"] - next_score) if next_score is not None else None
        return best, edge

    best_true, edge_true = _pick_best((backtest.get("trueTrack") or {}).get("strategies") or [], "true")
    if not best_true:
        return None

    regime_ko = _REGIME_GUIDANCE_LABEL[regime]
    confidence = int(max(55, min(90, 55 + (abs(edge_true or 0) * 200))))
    best_true["confidence"] = confidence
    best_true["reason"] = (
        f"{regime_ko} 국면 {best_true['horizon']} 기준 {_fmt(best_true['regimeReturn'])} 성과로 "
        + (f"다음 전략 대비 {_fmt(edge_true)} 우위입니다." if edge_true is not None else "동일 비교군 중 상대우위입니다.")
    )

    best_retro, _ = _pick_best((backtest.get("retrospective") or {}).get("strategies") or [], "retrospective")
    reference = None
    if best_retro:
        reference = {
            **best_retro,
            "warning": (backtest.get("retrospective") or {}).get("warning") or "",
            "reason": f"참고용 회고에서는 {regime_ko} 국면 {best_retro['horizon']} 기준 {_fmt(best_retro['regimeReturn'])}였습니다.",
        }

    return {
        "regime": regime,
        "label": f"현재 국면 추천 전략 · {_REGIME_GUIDANCE_LABEL[regime]}",
        "primary": best_true,
        "reference": reference,
        "note": "표시 전용 제언입니다. 실제 주문 실행 경로는 없으며, true track 성과를 우선 참고하세요.",
    }


# ── PR-4(이번): stock_notes 로드 ─────────────────────────────────────
def _load_stock_notes(conn) -> dict[str, dict]:
    """stock_notes → {ticker: {horizon, attractiveness, thesis}}."""
    cur = conn.cursor()
    cur.execute("SELECT ticker, horizon, attractiveness, thesis FROM stock_notes")
    return {r["ticker"]: {"horizon": r["horizon"], "attractiveness": r["attractiveness"], "thesis": r["thesis"]} for r in cur.fetchall()}


def _group_note_history(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        ticker = row["ticker"]
        grouped.setdefault(ticker, []).append({
            "id": row["id"],
            "horizon": row["horizon"],
            "attractiveness": row["attractiveness"],
            "thesis": row["thesis"],
            "created_at": str(row["created_at"]),
        })
    return grouped


def _load_stock_note_history(conn) -> dict[str, list[dict]]:
    cur = conn.cursor()
    cur.execute(
        "SELECT id, ticker, horizon, attractiveness, thesis, created_at "
        "FROM stock_note_history ORDER BY ticker, created_at DESC, id DESC"
    )
    return _group_note_history([dict(row) for row in cur.fetchall()])


def _group_analyst_views_rows(rows: list[dict]) -> dict[str, dict[str, list[dict]]]:
    grouped: dict[str, dict[str, list[dict]]] = {}
    for row in rows:
        ticker = row["ticker"]
        stance = row["stance"]
        grouped.setdefault(ticker, {"bull": [], "bear": []})
        grouped[ticker][stance].append({
            "point": row["point"],
            "source": row["source"],
            "sourceUrl": row["source_url"],
            "asof": str(row["asof"]),
        })
    return grouped


def _group_analyst_consensus_history_rows(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        ticker = row["ticker"]
        grouped.setdefault(ticker, []).append({
            "asof": str(row["asof"]),
            "targetPrice": round(_f(row["target_price"])) if _f(row["target_price"]) is not None else None,
            "ratingLabel": row["rating_label"],
            "ratingScore": _f(row["rating_score"]),
            "epsFwd": round(_f(row["eps_fwd"]), 2) if _f(row["eps_fwd"]) is not None else None,
            "nAnalysts": int(row["n_analysts"]) if row["n_analysts"] is not None else None,
            "source": row["source"],
        })
    for ticker in grouped:
        grouped[ticker].sort(key=lambda item: item["asof"])
    return grouped


def _build_ai_decomposition_summary(entry: dict | None) -> dict | None:
    if not entry:
        return None
    labels = {
        item["horizon"]: item["attractivenessLabel"]
        for item in entry.get("horizons", [])
        if item.get("horizon") and item.get("attractivenessLabel")
    }
    return {
        "entryId": entry["id"],
        "labels": labels,
        "bullCount": len(entry.get("bull", [])),
        "bearCount": len(entry.get("bear", [])),
    }


def _group_action_advice_rows(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    ordered = sorted(
        rows,
        key=lambda row: (row["ticker"], str(row["asof"]), row.get("created_at") or ""),
        reverse=True,
    )
    for row in ordered:
        grouped.setdefault(row["ticker"], []).append({
            "ticker": row["ticker"],
            "asof": str(row["asof"]),
            "direction": row["direction"],
            "currentWeight": _f(row["current_weight"]),
            "targetWeightLow": _f(row["target_weight_low"]),
            "targetWeightHigh": _f(row["target_weight_high"]),
            "weightAction": row["weight_action"],
            "entryZone": row["entry_zone"],
            "exitZone": row["exit_zone"],
            "confidence": row["confidence"],
            "rationale": row["rationale"],
            "supportingFactors": row["supporting_factors"] or [],
            "opposingFactors": row["opposing_factors"] or [],
            "divergenceNote": row["divergence_note"],
            "model": row["model"],
            "createdAt": str(row["created_at"]) if row.get("created_at") is not None else None,
            # 신규-D: 보유성격 + 집중 리스크 관찰
            "holdCharacter": row.get("hold_character"),
            "holdCharacterSecondary": row.get("hold_character_secondary") or [],
            "holdCharacterBasis": row.get("hold_character_basis") or [],
            "concentrationNote": row.get("concentration_note"),
            # 신규-A2: 3축 종합 등급
            "grade": row.get("grade"),
            "gradeConfidence": row.get("grade_confidence"),
            "gradeBasis": row.get("grade_basis") or {},
        })
    return grouped


def _group_manual_research_rows(
    entry_rows: list[dict],
    horizon_rows: list[dict],
    point_rows: list[dict],
    consensus_rows: list[dict],
) -> dict[str, list[dict]]:
    horizons_by_entry: dict[int, list[dict]] = {}
    for row in horizon_rows:
        horizons_by_entry.setdefault(int(row["entry_id"]), []).append({
            "id": row["id"],
            "horizon": row["horizon"],
            "attractivenessLabel": row["attractiveness_label"],
            "rationale": row["rationale"],
            "isUserConfirmed": bool(row["is_user_confirmed"]),
            "createdAt": str(row["created_at"]),
            "updatedAt": str(row["updated_at"]),
        })
    for items in horizons_by_entry.values():
        order = {"short": 0, "mid": 1, "long": 2}
        items.sort(key=lambda item: order.get(item["horizon"], 99))

    points_by_entry: dict[int, dict[str, list[dict]]] = {}
    for row in point_rows:
        entry_id = int(row["entry_id"])
        stance = row["stance"]
        points_by_entry.setdefault(entry_id, {"bull": [], "bear": []})
        points_by_entry[entry_id][stance].append({
            "id": row["id"],
            "point": row["point"],
            "sourceLabel": row["source_label"],
            "sourceUrl": row["source_url"],
            "isUserConfirmed": bool(row["is_user_confirmed"]),
            "createdAt": str(row["created_at"]),
            "updatedAt": str(row["updated_at"]),
        })

    consensus_by_entry = {
        int(row["entry_id"]): {
            "targetPrice": round(_f(row["target_price"])) if _f(row["target_price"]) is not None else None,
            "ratingLabel": row["rating_label"],
            "ratingScore": _f(row["rating_score"]),
            "isUserConfirmed": bool(row["is_user_confirmed"]),
            "createdAt": str(row["created_at"]),
            "updatedAt": str(row["updated_at"]),
        }
        for row in consensus_rows
    }

    grouped: dict[str, list[dict]] = {}
    for row in entry_rows:
        ticker = row["ticker"]
        entry_id = int(row["id"])
        grouped.setdefault(ticker, []).append({
            "id": entry_id,
            "ticker": ticker,
            "rawText": row["raw_text"],
            "source": row["source"],
            "sourceUrl": row["source_url"],
            "inferredSource": row["inferred_source"],
            "createdAt": str(row["created_at"]),
            "updatedAt": str(row["updated_at"]),
            "horizons": horizons_by_entry.get(entry_id, []),
            "bull": points_by_entry.get(entry_id, {}).get("bull", []),
            "bear": points_by_entry.get(entry_id, {}).get("bear", []),
            "consensus": consensus_by_entry.get(entry_id),
        })
    return grouped


def _load_manual_research_history(conn, tickers: list[str], *, limit_per_ticker: int = 5) -> dict[str, list[dict]]:
    if not tickers:
        return {}
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, ticker, raw_text, source, source_url, inferred_source, created_at, updated_at
        FROM (
            SELECT id, ticker, raw_text, source, source_url, inferred_source, created_at, updated_at,
                   ROW_NUMBER() OVER (
                     PARTITION BY ticker
                     ORDER BY created_at DESC, id DESC
                   ) AS rn
            FROM manual_research_entries
            WHERE ticker = ANY(%s)
        ) t
        WHERE rn <= %s
        ORDER BY ticker, created_at DESC, id DESC
        """,
        (tickers, limit_per_ticker),
    )
    entry_rows = [dict(row) for row in cur.fetchall()]
    if not entry_rows:
        return {}
    entry_ids = [int(row["id"]) for row in entry_rows]
    cur.execute(
        """
        SELECT id, entry_id, horizon, attractiveness_label, rationale, is_user_confirmed, created_at, updated_at
        FROM manual_research_horizons
        WHERE entry_id = ANY(%s)
        ORDER BY entry_id, created_at DESC, id DESC
        """,
        (entry_ids,),
    )
    horizon_rows = [dict(row) for row in cur.fetchall()]
    cur.execute(
        """
        SELECT id, entry_id, stance, point, source_label, source_url, is_user_confirmed, created_at, updated_at
        FROM manual_research_points
        WHERE entry_id = ANY(%s)
        ORDER BY entry_id, stance, created_at DESC, id DESC
        """,
        (entry_ids,),
    )
    point_rows = [dict(row) for row in cur.fetchall()]
    cur.execute(
        """
        SELECT entry_id, target_price, rating_label, rating_score, is_user_confirmed, created_at, updated_at
        FROM manual_research_consensus
        WHERE entry_id = ANY(%s)
        """,
        (entry_ids,),
    )
    consensus_rows = [dict(row) for row in cur.fetchall()]
    return _group_manual_research_rows(entry_rows, horizon_rows, point_rows, consensus_rows)


def _load_market_manual_views(conn, *, limit: int = 5) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, asof, scope, raw_text, bull_scenario, bear_scenario, source, source_url, created_at, updated_at
        FROM market_view_manual
        ORDER BY asof DESC, created_at DESC, id DESC
        LIMIT %s
        """,
        (limit,),
    )
    return [{
        "id": int(row["id"]),
        "asof": str(row["asof"]),
        "scope": row["scope"],
        "rawText": row["raw_text"],
        "bullScenario": row["bull_scenario"],
        "bearScenario": row["bear_scenario"],
        "source": row["source"],
        "sourceUrl": row["source_url"],
        "createdAt": str(row["created_at"]),
        "updatedAt": str(row["updated_at"]),
    } for row in cur.fetchall()]


def _load_action_advice_history(conn, tickers: list[str], *, limit_per_ticker: int = 5) -> dict[str, list[dict]]:
    if not tickers:
        return {}
    cur = conn.cursor()
    cur.execute(
        """
        SELECT ticker, asof, direction, current_weight, target_weight_low, target_weight_high,
               weight_action, entry_zone, exit_zone, confidence, rationale,
               supporting_factors, opposing_factors, divergence_note, model, created_at,
               hold_character, hold_character_secondary, hold_character_basis, concentration_note,
               grade, grade_confidence, grade_basis
        FROM (
            SELECT ticker, asof, direction, current_weight, target_weight_low, target_weight_high,
                   weight_action, entry_zone, exit_zone, confidence, rationale,
                   supporting_factors, opposing_factors, divergence_note, model, created_at,
                   hold_character, hold_character_secondary, hold_character_basis, concentration_note,
                   grade, grade_confidence, grade_basis,
                   ROW_NUMBER() OVER (
                     PARTITION BY ticker
                     ORDER BY asof DESC, created_at DESC
                   ) AS rn
            FROM stock_action_advice
            WHERE ticker = ANY(%s)
        ) t
        WHERE rn <= %s
        ORDER BY ticker, asof DESC, created_at DESC
        """,
        (tickers, limit_per_ticker),
    )
    return _group_action_advice_rows([dict(row) for row in cur.fetchall()])


def _load_analyst_consensus_history(conn, tickers: list[str], *, limit_per_ticker: int = 12) -> dict[str, list[dict]]:
    if not tickers:
        return {}
    cur = conn.cursor()
    cur.execute(
        """
        SELECT ticker, asof, target_price, rating_label, rating_score, eps_fwd, n_analysts, source
        FROM (
            SELECT ticker, asof, target_price, rating_label, rating_score, eps_fwd, n_analysts, source,
                   ROW_NUMBER() OVER (
                     PARTITION BY ticker
                     ORDER BY asof DESC, created_at DESC
                   ) AS rn
            FROM analyst
            WHERE ticker = ANY(%s)
        ) t
        WHERE rn <= %s
        ORDER BY ticker, asof ASC
        """,
        (tickers, limit_per_ticker),
    )
    return _group_analyst_consensus_history_rows([dict(row) for row in cur.fetchall()])


def _load_analyst_views(conn, tickers: list[str]) -> dict[str, dict[str, list[dict]]]:
    if not tickers:
        return {}
    cur = conn.cursor()
    cur.execute(
        """
        SELECT ticker, stance, point, source, source_url, asof
        FROM (
            SELECT ticker, stance, point, source, source_url, asof,
                   ROW_NUMBER() OVER (
                     PARTITION BY ticker, stance
                     ORDER BY asof DESC, created_at DESC
                   ) AS rn
            FROM analyst_views
            WHERE ticker = ANY(%s)
        ) t
        WHERE rn <= 5
        ORDER BY ticker, stance, asof DESC
        """,
        (tickers,),
    )
    return _group_analyst_views_rows([dict(row) for row in cur.fetchall()])


# ── PR-4: 리서치 항목 로드 ────────────────────────────────────────────
def _load_research_items(conn) -> dict[str, list[dict]]:
    """research_items → {ticker: [item...]}."""
    cur = conn.cursor()
    cur.execute("SELECT id, ticker, item_type, title, url, note, added_at FROM research_items ORDER BY ticker, added_at DESC")
    result: dict[str, list] = {}
    for r in cur.fetchall():
        tk = r["ticker"]
        result.setdefault(tk, []).append({
            "id":        r["id"],
            "type":      r["item_type"],
            "title":     r["title"],
            "url":       r["url"] or "",
            "note":      r["note"] or "",
            "addedAt":   str(r["added_at"])[:10],
        })
    return result


def _group_ticker_context_rows(
    rows: list[dict],
    *,
    today: date | None = None,
    max_days: int = 30,
) -> dict[str, list[dict]]:
    today = today or date.today()
    cutoff = today - timedelta(days=max_days)
    grouped: dict[str, list[dict]] = {}

    for row in rows:
        ticker = row["ticker"]
        valid_from = row["valid_from"]
        valid_until = row.get("valid_until")

        if isinstance(valid_from, str):
            valid_from = date.fromisoformat(valid_from[:10])
        if isinstance(valid_until, str) and valid_until:
            valid_until = date.fromisoformat(valid_until[:10])

        if valid_from < cutoff:
            continue
        if valid_until and valid_until < today:
            continue

        grouped.setdefault(ticker, []).append({
            "id": row["id"],
            "type": row["context_type"],
            "typeLabel": CONTEXT_TYPE_LABEL.get(row["context_type"], row["context_type"]),
            "content": row["content"],
            "source": row["source"],
            "validFrom": valid_from.isoformat(),
            "validUntil": valid_until.isoformat() if valid_until else None,
            "createdAt": str(row["created_at"]),
        })

    return grouped


def _load_ticker_context_recent(
    conn,
    tickers: list[str],
    *,
    today: date | None = None,
    max_days: int = 30,
) -> dict[str, list[dict]]:
    if not tickers:
        return {}
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, ticker, context_type, content, source, valid_from, valid_until, created_at
        FROM ticker_context
        WHERE ticker = ANY(%s)
        ORDER BY ticker, valid_from DESC, created_at DESC, id DESC
        """,
        (tickers,),
    )
    rows = [dict(row) for row in cur.fetchall()]
    return _group_ticker_context_rows(rows, today=today, max_days=max_days)


# ── 종목 news 피드 (PR-2: news_raw 원문 + URL 포함) ───────────────────
def _build_news_feed(conn, watchlist_map: dict, sentiment_by_ticker: dict) -> list[dict]:
    """
    news_raw 원문 기사 → 뉴스 피드(원문 제목·URL·출처·시각).
    종목 감성(sentiment_by_ticker)으로 색상 태깅. watchlist 종목만(=_MARKET_* 제외).
    """
    cur = conn.cursor()
    wl_tickers = list(watchlist_map.keys())
    cur.execute("""
        SELECT ticker, title, url, source, published_at
        FROM news_raw
        WHERE ticker = ANY(%s) AND published_at IS NOT NULL
        ORDER BY published_at DESC
        LIMIT 120
    """, (wl_tickers,))
    rows = cur.fetchall()
    feed = []
    for r in rows:
        tk = r["ticker"]
        sent = sentiment_by_ticker.get(tk, "중립")
        feed.append({
            "t": tk,
            "sent": sent,
            "time": str(r["published_at"])[:16].replace("T", " "),
            "src": r["source"] or "뉴스",
            "high": (r["title"] or "")[:120],
            "body": "",
            "url": r["url"] or "",          # PR-2: 원문 링크
            "hot": sent == "긍정",
        })
    return feed


def _build_article_map(conn, watchlist_map: dict, limit_per: int = 8) -> dict[str, list[dict]]:
    """종목별 최근 원문 기사(제목·URL·출처·시각) limit_per건. 종목상세 '원문 뉴스'용."""
    cur = conn.cursor()
    wl_tickers = list(watchlist_map.keys())
    cur.execute("""
        SELECT ticker, title, url, source, published_at,
               ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY published_at DESC NULLS LAST) AS rn
        FROM news_raw
        WHERE ticker = ANY(%s)
    """, (wl_tickers,))
    out: dict[str, list] = {}
    for r in cur.fetchall():
        if r["rn"] > limit_per:
            continue
        out.setdefault(r["ticker"], []).append({
            "title": (r["title"] or "")[:140],
            "url": r["url"] or "",
            "src": r["source"] or "뉴스",
            "time": str(r["published_at"])[:16].replace("T", " ") if r["published_at"] else "",
        })
    return out


def _build_news_timeline(conn, limit_per: int = 5) -> dict[str, list[dict]]:
    """종목별 최근 news_analysis limit_per건(날짜·감성·1줄). 종목상세 분석 타임라인용."""
    cur = conn.cursor()
    # PR-1(진단): 폴백 행은 타임라인에서 제외 → '분석 실패' 줄이 쌓이지 않게.
    cur.execute("""
        SELECT ticker, asof, sentiment, sentiment_score, summary_md, based_on,
               ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY asof DESC) AS rn
        FROM news_analysis
        WHERE based_on <> 'fallback_old'
          AND summary_md NOT LIKE '%분석 실패%'
          AND summary_md NOT LIKE '%일시 보류%'
    """)
    out: dict[str, list] = {}
    for r in cur.fetchall():
        if r["rn"] > limit_per:
            continue
        raw = (r["summary_md"] or "").strip()
        first = next((l.lstrip("- ").strip() for l in raw.split("\n") if l.strip().startswith("-")), raw[:90])
        out.setdefault(r["ticker"], []).append({
            "asof": str(r["asof"]),
            "sent": r["sentiment"] or "중립",
            "score": round(float(r["sentiment_score"]) * 100) if r["sentiment_score"] is not None else 50,
            "line": first[:120],
        })
    return out


def _build_financials(conn, annual_n: int = 6, quarter_n: int = 8) -> dict[str, dict]:
    """PR-2: 종목별 재무 시계열(매출·영업이익·순이익·영업이익률·OCF·FCF).
    종목상세 '재무 추이' 카드용. annual/quarter 분리, 오래된→최근 순."""
    cur = conn.cursor()
    cur.execute("""
        SELECT ticker, period_type, period_end, revenue, op_income, op_margin, net_income, ocf, fcf
        FROM fundamentals
        ORDER BY ticker, period_type, period_end
    """)
    tmp: dict[str, dict[str, list]] = {}
    for r in cur.fetchall():
        pt = r["period_type"]
        rev = _f(r["revenue"])
        op = _f(r["op_income"])
        item = {
            "period": str(r["period_end"]),
            "rev": rev,
            "op": op,
            "ni": _f(r["net_income"]),
            "opm": round(_f(r["op_margin"]) * 100, 1) if _f(r["op_margin"]) is not None else None,
            "ocf": _f(r["ocf"]),
            "fcf": _f(r["fcf"]),
        }
        tmp.setdefault(r["ticker"], {"annual": [], "quarter": []})[pt].append(item)
    out: dict[str, dict] = {}
    for tk, d in tmp.items():
        ann = [x for x in d["annual"] if x["rev"] is not None][-annual_n:]
        qtr = [x for x in d["quarter"] if x["rev"] is not None][-quarter_n:]
        # 최근 추세 방향(연간 매출·영업이익 마지막 2개 비교)
        def _trend(series, key):
            vals = [x[key] for x in series if x[key] is not None]
            if len(vals) < 2 or vals[-2] in (None, 0):
                return None
            return round((vals[-1] - vals[-2]) / abs(vals[-2]) * 100, 1)
        out[tk] = {
            "annual": ann,
            "quarter": qtr,
            "revTrend": _trend(ann, "rev"),
            "opTrend": _trend(ann, "op"),
            "hasData": bool(ann or qtr),
        }
    return out


# ── PR-1: 오늘의 요약 밴드 (규칙 기반 합성) ──────────────────────────
_POS_FLAG_KEYS = ("골든크로스", "RSI 침체")   # 추세 전환·과매도 반등 신호(목표가근접은 부호 모호 → 제외)
_CAUTION_FLAG_KEYS = ("RSI 과열", "데드크로스", "급락", "이격도 과열")
_REGIME_KO = {"bull": "위험선호", "neutral": "중립", "bear": "위험회피"}


def _first_flag(flags: list[str], keys: tuple) -> Optional[str]:
    for f in flags or []:
        if any(k in f for k in keys):
            return f
    return None


def _short_line(text: str, n: int = 90) -> str:
    """문장 한 줄로 — 소수점에서 안 끊기게 '. '(마침표+공백) 기준 첫 문장 또는 n자."""
    if not text:
        return ""
    t = text.strip().lstrip("- ").strip()
    for sep in (". ", "다. ", "요. "):
        if sep in t:
            return t.split(sep)[0].strip() + ("" if sep == ". " else sep.strip())
    return t[:n]


def _build_daily_brief(stocks: list[dict], market: dict) -> dict:
    """오버뷰 최상단 30초 스캔용 합성 요약. 전부 '관찰/정보' 서술(매수매도 단정 금지)."""
    live = [s for s in stocks if s.get("hasData") and s.get("comp") is not None]

    # 3) 3축 괴리(먼저 계산 → 주목에서 제외해 섹션 메시지 분리): 퀀트↔컨센서스 큰 엇갈림
    diverge_raw = []
    for s in live:
        comp, up = s.get("comp"), s.get("up")
        if up is None:
            continue
        if comp >= 60 and up < 5:
            diverge_raw.append((abs(comp - 50) + abs(up), {"t": s["t"], "name": s["name"],
                "why": f"퀀트 높음(종합 {comp}) ↔ 컨센서스 낮음(상승여력 {up}%) — 확인 필요"}))
        elif comp < 40 and up >= 20:
            diverge_raw.append((abs(comp - 50) + abs(up), {"t": s["t"], "name": s["name"],
                "why": f"퀀트 낮음(종합 {comp}) ↔ 컨센서스 높음(상승여력 {up}%) — 확인 필요"}))
    diverge_raw.sort(key=lambda x: -x[0])
    diverge = [d for _, d in diverge_raw[:2]]
    diverge_tk = {d["t"] for d in diverge}

    # 1) 주목: composite 상위(괴리 종목 제외) + (있으면) 신선 신호.
    hi_cand = sorted([s for s in live if s["t"] not in diverge_tk], key=lambda s: -(s.get("comp") or 0))
    highlights = []
    for s in hi_cand[:3]:
        flag = _first_flag(s.get("flagsAction", []), _POS_FLAG_KEYS)
        why = f"퀀트 종합 {s.get('comp')}(상위)" + (f" · {flag}" if flag else "")
        highlights.append({"t": s["t"], "name": s["name"], "comp": s.get("comp"), "why": why})

    # 2) 주의: 위험 플래그(과열·데드크로스·급락) 또는 컨센서스 대비 고평가(상승여력 큰 음수)
    cautions = []
    for s in live:
        cflag = _first_flag(s.get("flagsAction", []), _CAUTION_FLAG_KEYS)
        up = s.get("up")
        if cflag:
            cautions.append({"t": s["t"], "name": s["name"], "why": cflag})
        elif up is not None and up <= -10:
            cautions.append({"t": s["t"], "name": s["name"], "why": f"컨센서스 목표가 하회(상승여력 {up}%)"})
    # 위험 강도 순(과열/데드크로스/급락 먼저)
    cautions.sort(key=lambda c: 0 if any(k in c["why"] for k in ("과열", "데드크로스", "급락")) else 1)
    cautions = cautions[:3]

    # 4) 시장 한 줄: KR/US 레짐 + 시황 요약(Gemini 생성분 재사용, 없으면 규칙 폴백)
    overall = market.get("overall", "neutral")
    kr_sum = (market.get("kr", {}) or {}).get("summary", "")
    us_sum = (market.get("us", {}) or {}).get("summary", "")
    market_line = f"시장 레짐 {_REGIME_KO.get(overall, overall)}"
    krline = _short_line(kr_sum)
    usline = _short_line(us_sum)

    return {
        "highlights": highlights,
        "cautions": cautions,
        "diverge": diverge,
        "marketLine": market_line,
        "krLine": krline,
        "usLine": usline,
        "regime": overall,
    }


def _market_beta_note(score: Optional[float], direction: Optional[str], beta: Optional[float]) -> Optional[str]:
    """Wave 5-B: 시장 점수 → 종목 베타 경로 '관찰'(사실+영향, 매매 단정 금지). composite 미변경."""
    s = _f(score)
    b = _f(beta)
    if s is None or b is None or not direction:
        return None
    if direction == "약세" and b >= 1.2:
        return f"시장 {round(s)}점(약세) · 베타 {b} — 시장 약세 국면에서 낙폭이 시장보다 클 수 있습니다(관찰)."
    if direction == "강세" and b >= 1.2:
        return f"시장 {round(s)}점(강세) · 베타 {b} — 시장 강세 국면에서 탄력이 시장보다 클 수 있습니다."
    if b <= 0.7:
        return f"시장 {round(s)}점({direction}) · 베타 {b} — 시장 변동에 상대적으로 둔감한 편입니다."
    return None


def _attach_market_score(conn, market: dict, stocks: list[dict]) -> None:
    """Wave 5-B: market_score(지역별 최신)를 market.kr/us에 부착 + 종목 베타 경로 관찰 합성."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT ON (region) region, asof, score, direction, confidence, components, divergence_note
        FROM market_score ORDER BY region, asof DESC
        """
    )
    by_region: dict[str, dict] = {}
    for r in cur.fetchall():
        by_region[r["region"]] = {
            "asof": str(r["asof"]), "score": _f(r["score"]), "direction": r["direction"],
            "confidence": r["confidence"], "divergenceNote": r["divergence_note"],
            "components": r["components"] or {},
        }
    for mk_key in ("KR", "US"):
        ms = by_region.get(mk_key)
        if ms and mk_key.lower() in market and isinstance(market[mk_key.lower()], dict):
            market[mk_key.lower()]["marketScore"] = ms
    for s in stocks:
        ms = by_region.get(s.get("mk"))
        if ms:
            s["marketBetaNote"] = _market_beta_note(ms.get("score"), ms.get("direction"), s.get("beta"))
            # 신규-A2: 등급의 시장·베타 보정(퀀트 축 경로)에서 읽는다.
            s["marketScoreDirection"] = ms.get("direction")
            s["marketScoreVal"] = ms.get("score")


def _attach_market_attractiveness(market: dict, stocks: list[dict]) -> None:
    """PR-2: KR/US 진입 환경(우호/중립/비우호) + 근거. 레짐·시장폭(정배열율)·변동성 종합.
    단일 점수 강요 금지 — 환경 평가 + 근거 서술."""
    def _for(mk_key: str, regime: str, vix: Optional[float]) -> dict:
        peers = [s for s in stocks if s.get("mk") == mk_key and s.get("hasData")]
        n = len(peers)
        aligned = sum(1 for s in peers if s.get("align"))
        breadth = round(aligned / n * 100) if n else None    # 정배열 비율 = 시장폭 프록시
        pos = sum(1 for s in peers if (s.get("chg") or 0) > 0)
        up_rate = round(pos / n * 100) if n else None        # 당일 상승 종목 비율

        score = 0
        if regime == "bull": score += 1
        elif regime == "bear": score -= 1
        if breadth is not None:
            score += 1 if breadth >= 55 else (-1 if breadth <= 30 else 0)
        if vix is not None:
            score += 1 if vix < 18 else (-1 if vix > 25 else 0)

        env = "우호" if score >= 1 else ("비우호" if score <= -1 else "중립")
        basis_bits = [f"레짐 {_REGIME_KO.get(regime, regime)}"]
        if breadth is not None: basis_bits.append(f"정배열 {breadth}%")
        if up_rate is not None: basis_bits.append(f"당일상승 {up_rate}%")
        if vix is not None: basis_bits.append(f"VIX {vix:.0f}")
        return {"env": env, "breadth": breadth, "upRate": up_rate,
                "basis": " · ".join(basis_bits),
                "note": f"현재 진입 환경은 '{env}'로 관찰됩니다({' · '.join(basis_bits)}). 환경 평가일 뿐 매매 신호가 아닙니다."}

    # VIX 추출(indices에서)
    vix = None
    for ix in market.get("indices", []):
        if ix.get("k") == "VIX":
            try: vix = float(str(ix.get("v")).replace(",", ""))
            except (TypeError, ValueError): vix = None
    if "kr" in market and isinstance(market["kr"], dict):
        market["kr"]["attractiveness"] = _for("KR", market["kr"].get("regime", "neutral"), vix)
    if "us" in market and isinstance(market["us"], dict):
        market["us"]["attractiveness"] = _for("US", market["us"].get("regime", "neutral"), vix)


# ── 메인 ─────────────────────────────────────────────────────────────
def build_data() -> dict:
    _load_secrets()

    # src.db를 직접 임포트 (secrets 로드 후)
    from src.db import get_conn

    with get_conn() as conn:
        # watchlist
        cur = conn.cursor()
        # PR-3: active=TRUE만 (비활성 종목은 랭킹/대시보드에서 제외, 데이터는 보존)
        cur.execute("SELECT ticker, name, market, sector, is_holding FROM watchlist WHERE active = TRUE ORDER BY ticker")
        wl_rows = cur.fetchall()
        watchlist_map = {r["ticker"]: dict(r) for r in wl_rows}
        tickers = list(watchlist_map.keys())

        # regime & market
        regime_info = _detect_regime(conn)
        market = _build_market(conn, regime_info)

        # today의 indicators/quant/valuation/analyst/news
        asof = date.today()
        # 가장 최신 데이터 날짜 탐색 (주말·공휴일 보정)
        for delta in range(7):
            check = (asof - timedelta(days=delta)).isoformat()
            cur.execute("SELECT count(*) as n FROM indicators_daily WHERE date=%s", (check,))
            if cur.fetchone()["n"] > 0:
                asof = date.fromisoformat(check)
                break

        # PR-1: asof 불일치(신규 종목이 다른 날짜에만 데이터 보유)에 견고하도록
        # indicators/quant/price를 '종목별 최신'으로 조회한다(특정 날짜 고정 X).
        cur.execute("""
            SELECT DISTINCT ON (ticker)
                ticker, date, rsi14, disparity20, is_aligned,
                macd_line, macd_signal, macd_hist, bb_upper, bb_lower, bb_pct,
                stoch_k, stoch_d, vol_ratio20, atr14,
                trading_signal, trading_signal_score
            FROM indicators_daily ORDER BY ticker, date DESC
        """)
        ind_map = {r["ticker"]: dict(r) for r in cur.fetchall()}

        # E-2: investor_flow — KR 종목별 최신 (DISTINCT ON, 날짜 고정 금지)
        cur.execute("""
            SELECT DISTINCT ON (ticker)
                ticker, date, foreign_net, institution_net, individual_net,
                foreign_3d_sum, institution_3d_sum,
                foreign_signal, institution_signal, combined_signal
            FROM investor_flow ORDER BY ticker, date DESC
        """)
        investor_flow_map = {r["ticker"]: dict(r) for r in cur.fetchall()}

        # prices_daily: 종목별 최신 close + 직전 거래일 대비 등락
        cur.execute("""
            SELECT ticker, close, chg_pct FROM (
                SELECT ticker, date, close,
                       ROUND(CAST(
                           (close - LAG(close) OVER (PARTITION BY ticker ORDER BY date))
                           / NULLIF(LAG(close) OVER (PARTITION BY ticker ORDER BY date), 0) * 100
                       AS numeric), 2) AS chg_pct,
                       ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn
                FROM prices_daily WHERE close IS NOT NULL
            ) t WHERE rn = 1
        """)
        for r in cur.fetchall():
            tk2 = r["ticker"]
            if tk2 not in ind_map:
                ind_map[tk2] = {}
            ind_map[tk2]["close"] = _f(r["close"])
            ind_map[tk2]["chg_pct"] = _f(r["chg_pct"])

        cur.execute("""
            SELECT DISTINCT ON (ticker) ticker, momentum, value, quality, growth, sentiment, composite, fscore, flags, beta, market_corr
            FROM quant_scores ORDER BY ticker, asof DESC
        """)
        quant_map = {r["ticker"]: dict(r) for r in cur.fetchall()}

        # PR-0: 종목별 최신 valuation/analyst (글로벌 max(asof) 사용 시 KR/US 수집일이
        # 달라 한쪽이 통째로 누락되는 버그 — indicators/quant와 동일하게 DISTINCT ON으로 수정).
        cur.execute("""
            SELECT DISTINCT ON (ticker) ticker, per_f, per_t, pbr, roe, debt_ratio
            FROM valuation ORDER BY ticker, asof DESC
        """)
        val_map = {r["ticker"]: dict(r) for r in cur.fetchall()}

        cur.execute("""
            SELECT DISTINCT ON (ticker) ticker, rating, rating_label, rating_score, target_price, upside, eps_fwd, n_analysts, source, asof
            FROM analyst ORDER BY ticker, asof DESC
        """)
        ana_map = {r["ticker"]: dict(r) for r in cur.fetchall()}

        # PR-1: 증분 처리로 오늘자 news_analysis가 없는 종목도 빈 카드가 되지 않도록
        # 종목별 "가장 최근 1건"을 조회한다(asof 날짜도 함께 반환).
        # PR-1(진단): 폴백('분석 실패'/'일시 보류')보다 '실제 요약'을 우선한다.
        # 더 최신이 폴백이어도, 과거의 실제 요약이 있으면 그쪽을 노출(낡은 실제 > 새 실패).
        cur.execute("""
            SELECT DISTINCT ON (ticker) ticker, asof, sentiment, sentiment_score, summary_md, based_on, curated
            FROM news_analysis
            ORDER BY ticker,
              (CASE WHEN based_on = 'fallback_old'
                     OR summary_md LIKE '%분석 실패%'
                     OR summary_md LIKE '%일시 보류%' THEN 1 ELSE 0 END),
              asof DESC
        """)
        news_map = {r["ticker"]: dict(r) for r in cur.fetchall()}
        # PR-2: 큐레이션은 '가장 최근에 큐레이션이 있는 행'에서 가져온다(최신 행이 비어도 직전 보존분 사용)
        cur.execute("""
            SELECT DISTINCT ON (ticker) ticker, curated
            FROM news_analysis
            WHERE curated <> '[]'::jsonb
            ORDER BY ticker, asof DESC
        """)
        curated_map = {r["ticker"]: r["curated"] for r in cur.fetchall()}

        cur.execute("""
            SELECT ticker, revenue, op_income, op_margin FROM fundamentals
            WHERE period_type='annual'
            AND period_end=(SELECT max(period_end) FROM fundamentals f2 WHERE f2.ticker=fundamentals.ticker AND f2.period_type='annual')
        """)
        fund_map = {r["ticker"]: dict(r) for r in cur.fetchall()}

        # 섹터 내 composite 백분위 순위 계산
        sector_comp: dict[str, list[tuple[str, float]]] = {}
        for tk in tickers:
            q = quant_map.get(tk, {})
            comp = _f(q.get("composite"))
            sec = watchlist_map[tk].get("sector") or "기타"
            sector_comp.setdefault(sec, [])
            if comp is not None:
                sector_comp[sec].append((tk, comp))
        for sec in sector_comp:
            sector_comp[sec].sort(key=lambda x: x[1], reverse=True)

        def sector_rank(ticker: str) -> tuple[int, int]:
            sec = watchlist_map[ticker].get("sector") or "기타"
            peers = sector_comp.get(sec, [])
            total = len(watchlist_map)  # 전체 종목 수 (data.jsx 스타일)
            for i, (tk, _) in enumerate(peers):
                if tk == ticker:
                    return i + 1, total
            return len(peers) + 1, total

        # 주가·거래량 시계열
        series_map: dict[str, tuple[list[float], list]] = {}
        for tk in tickers:
            series_map[tk] = _build_price_series(tk, conn)

        # PR-2: 보유종목 평가
        holdings_map = _load_portfolio(conn)
        portfolio_snapshot = _load_portfolio_snapshot(conn)
        # 포트폴리오 전략 조언(CoT) 최근 캐시 — 없으면 None. 호출은 하지 않음(읽기만).
        try:
            from src.portfolio_advice import load_latest as _load_advice
            portfolio_advice = _load_advice(conn)
        except Exception:
            portfolio_advice = None

        # PR-4: 리서치 항목
        research_items_map = _load_research_items(conn)
        analyst_views_map = _load_analyst_views(conn, tickers)
        analyst_consensus_history_map = _load_analyst_consensus_history(conn, tickers)
        manual_research_history_map = _load_manual_research_history(conn, tickers)
        action_advice_history_map = _load_action_advice_history(conn, tickers)
        market_manual_views = _load_market_manual_views(conn)

        # PR-4(이번): stock_notes
        notes_map = _load_stock_notes(conn)
        note_history_map = _load_stock_note_history(conn)
        ticker_context_map = _load_ticker_context_recent(conn, tickers)
        driver_cards_map = _load_driver_cards(conn, tickers)

        # PR-7: 백테스트 / 회고
        backtest_data = _load_backtest(conn)

        # 뉴스 피드 (PR-2: news_raw 원문 + URL) + 종목별 기사·분석 타임라인
        sentiment_by_ticker = {tk: (news_map.get(tk, {}).get("sentiment") or "중립") for tk in tickers}
        news_feed = _build_news_feed(conn, watchlist_map, sentiment_by_ticker)
        article_map = _build_article_map(conn, watchlist_map)       # 종목별 최근 원문 기사
        timeline_map = _build_news_timeline(conn)                   # 종목별 최근 5건 분석
        financials_map = _build_financials(conn)                    # PR-2: 종목별 재무 시계열

        # ── stocks 배열 구성 ──────────────────────────────────
        stocks = []
        for tk in tickers:
            wl   = watchlist_map[tk]
            ind  = ind_map.get(tk, {})
            q    = quant_map.get(tk, {})
            val  = val_map.get(tk, {})
            ana  = ana_map.get(tk, {})
            news = news_map.get(tk, {})
            fund = fund_map.get(tk, {})
            ser, vol_ser = series_map.get(tk, ([], []))
            # PR-2: 보유 정보
            hold_info = holdings_map.get(tk)
            rk, total_stocks = sector_rank(tk)

            close = _f(ind.get("close"))
            # PR-1: 가격 이력이 없는 종목은 '데이터 수집 중'으로 명확히 표시(₩0를 가짜 가격처럼 X)
            has_data = bool(ser) and close is not None
            chg   = _f(ind.get("chg_pct"))
            rsi   = _f(ind.get("rsi14"))
            disp  = _f(ind.get("disparity20"))
            align = ind.get("is_aligned")

            comp  = _f(q.get("composite"))
            mom   = _f(q.get("momentum")) or 50.0
            value = _f(q.get("value"))    or 50.0
            qual  = _f(q.get("quality"))  or 50.0
            grow  = _f(q.get("growth"))   or 50.0
            sent_f = _f(q.get("sentiment")) or 50.0

            raw_flags = q.get("flags") or []
            if isinstance(raw_flags, str):
                import ast
                try:
                    raw_flags = ast.literal_eval(raw_flags)
                except Exception:
                    raw_flags = []
            # PR-3: 플래그 분류
            flags_action, flags_quality = _split_flags(raw_flags)

            # 재무
            per  = _f(val.get("per_f")) or _f(val.get("per_t"))  # PR-0: KR은 per_t 폴백
            pbr  = _f(val.get("pbr"))
            roe  = _f(val.get("roe"))
            debt = _f(val.get("debt_ratio"))
            rev  = _f(fund.get("op_margin"))
            # PR-1: F-Score를 quant_scores에서 실제로 읽는다(과거 None 하드코딩 버그 수정)
            fscore = q.get("fscore")
            fscore = int(fscore) if fscore is not None else None
            # PR-1: 안전마진 복합점수(가치+퀄리티+재무건전성) — 장기보유 후보 선정 기준
            safety, safety_parts = _safety_margin(value, qual, fscore, roe, debt)
            safety_reason = _safety_reason(per, pbr, roe, debt, fscore)

            # 애널리스트
            tp     = _f(ana.get("target_price"))
            upside = _f(ana.get("upside"))
            rating = ana.get("rating")
            rating_label = ana.get("rating_label") or rating
            rating_score = _f(ana.get("rating_score"))
            eps_fwd = _f(ana.get("eps_fwd"))
            n_analysts = ana.get("n_analysts")
            analyst_source = ana.get("source")
            analyst_asof = str(ana.get("asof")) if ana.get("asof") else None

            # 뉴스 sentiment (PR-1: 종목별 최근 1건, asof 포함)
            n_sent = news.get("sentiment") or "중립"
            n_score = _f(news.get("sentiment_score")) or 0.5
            news_asof = str(news.get("asof")) if news.get("asof") else None
            summary_raw = news.get("summary_md") or ""
            # PR-1(진단): 폴백('분석 실패'/'일시 보류')은 화면에 절대 노출하지 않는다.
            # 실제 요약이 없으면 규칙기반 한 줄 인사이트(수치+해석)로 대체.
            if _is_fallback_summary(summary_raw, news.get("based_on")):
                summary_raw = ""
                news_asof = None
            sum_bullets = [l.lstrip("- ").strip() for l in summary_raw.split("\n") if l.strip().startswith("-")][:3]
            if not sum_bullets and summary_raw:
                sum_bullets = [summary_raw[:100]]
            if not sum_bullets:
                sum_bullets = [_rule_based_insight(close, chg, rsi, comp, n_sent, has_data)]

            # PR-6: 팩터별 '중립 폴백(데이터 없음→50)' 여부 — quant 플래그로 판별
            factor_fallback = {"m": False, "v": False, "q": False, "g": False, "s": False}
            for f in raw_flags:
                if not ("데이터 부족" in f or "사전필터" in f or "발행주식수" in f):
                    continue
                if any(k in f for k in ("PER", "밸류", "가치", "PBR")): factor_fallback["v"] = True
                if any(k in f for k in ("F-Score", "ROE", "퀄리티", "부채")): factor_fallback["q"] = True
                if "모멘텀" in f: factor_fallback["m"] = True
                if any(k in f for k in ("성장", "매출", "Growth")): factor_fallback["g"] = True
                if any(k in f for k in ("감성", "뉴스", "Sentiment")): factor_fallback["s"] = True

            # PR-4: SMA 시계열 계산
            sma20  = _sma(ser, 20)
            sma50  = _sma(ser, 50)   # SMA60 대신 sma50 컬럼명 유지
            sma200 = _sma(ser, 200)

            def _sma_series(s: list[float], w: int) -> list[float | None]:
                return [
                    round(sum(s[max(0, i - w + 1):i + 1]) / min(i + 1, w), 2)
                    if i >= w - 1 else None
                    for i in range(len(s))
                ]

            sma60_series  = _sma_series(ser, 60)   # PR-4
            sma120_series = _sma_series(ser, 120)  # PR-4
            disparity = round((close / sma20 * 100), 1) if close and sma20 else disp

            comp_hist = _spark([comp or 50] * 20, 16)
            mom_hist  = _spark([mom] * 20, 16)
            slope = round(((ser[-1] - ser[-20]) / ser[-20] * 100), 1) if len(ser) >= 20 and ser[-20] else 0.0

            mk = wl.get("market") or "US"
            stocks.append({
                "t":    tk,
                "name": wl.get("name") or tk,
                "mk":   mk,
                "sec":  wl.get("sector") or "기타",
                "hold": bool(wl.get("is_holding")),
                "hasData": has_data,                # PR-1: 데이터 충족 여부
                "price": close if has_data else None,   # 가격 없으면 null (₩0 표시 금지)
                "chg":  chg,
                "cur":  "₩" if mk == "KR" else "$",
                "comp": round(comp) if comp is not None else None,
                "f": {
                    "m": round(mom),
                    "v": round(value),
                    "q": round(qual),
                    "g": round(grow),
                    "s": round(sent_f),
                },
                # 신규-A1: 시장 민감도(퀀트 축 별도 팩터, composite 미합산). None=미산출.
                "beta":       _f(q.get("beta")),
                "marketCorr": _f(q.get("market_corr")),
                "betaBenchmark": _BETA_BENCHMARK_LABEL.get(_market_benchmark(tk, mk)),
                "rsi":    round(rsi, 1) if rsi is not None else None,
                "align":  bool(align) if align is not None else False,
                "flags":        raw_flags,         # 하위호환
                "flagsAction":  flags_action,      # PR-3
                "flagsQuality": flags_quality,     # PR-3
                "factorFallback": factor_fallback, # PR-6: 팩터별 중립폴백(데이터없음) 여부
                "rank":   [rk, total_stocks],
                "per":    round(per, 1) if per else None,
                "pbr":    round(pbr, 2) if pbr else None,
                "roe":    round(roe * 100, 1) if roe is not None else None,  # PR-0: 비율→% 표시(US/KR 모두 ratio 저장)
                "rev":    round(rev * 100, 1) if rev else None,
                "fscore": fscore,
                "safety":       round(safety),           # PR-1: 안전마진 복합점수(0~100)
                "safetyParts":  safety_parts,            # {v,q,s} 구성요소
                "safetyReason": safety_reason,           # 왜 장기보유 후보인가 1줄
                "tp":     round(tp) if tp else None,
                # analyst.upside는 분수(0.378)로 저장 — 표시·임계(컨센서스 축 20/5%, 상승여력 %)는
                # 전부 퍼센트 기준이므로 ×100로 변환(이전 round(upside,1)은 0.378→0.4로 분수를 그대로
                # 흘려 컨센서스 축이 구조적으로 항상 '낮음'이 되던 버그 — 신규-A2 등급이 매수를 못 내던 원인).
                "up":     round(upside * 100, 1) if upside else None,
                "rating": rating,
                "consensus": {
                    "targetPrice": round(tp) if tp else None,
                    "ratingLabel": rating_label,
                    "ratingScore": rating_score,
                    "epsFwd": round(eps_fwd, 2) if eps_fwd is not None else None,
                    "nAnalysts": int(n_analysts) if n_analysts is not None else None,
                    "source": analyst_source,
                    "asof": analyst_asof,
                } if any(v is not None for v in (tp, rating_label, rating_score, eps_fwd, n_analysts, analyst_source)) else None,
                "consensusHistory": analyst_consensus_history_map.get(tk, []),
                "analystViews": analyst_views_map.get(tk, {"bull": [], "bear": []}),
                "manualResearchLatest": (manual_research_history_map.get(tk) or [None])[0],
                "manualResearchHistory": manual_research_history_map.get(tk, []),
                "aiDecompositionSummary": _build_ai_decomposition_summary((manual_research_history_map.get(tk) or [None])[0]),
                "actionAdviceLatest": (action_advice_history_map.get(tk) or [None])[0],
                "actionAdviceHistory": action_advice_history_map.get(tk, []),
                # 신규-A2: 3축 종합 등급(스크리너 발굴·정렬용 — 최신 액션 제언에서 끌어옴)
                "grade": ((action_advice_history_map.get(tk) or [None])[0] or {}).get("grade"),
                "gradeConfidence": ((action_advice_history_map.get(tk) or [None])[0] or {}).get("gradeConfidence"),
                "sent":   n_sent,
                "sscore": round(n_score * 100) if n_score else 50,
                "sum":    sum_bullets,
                "newsAsof": news_asof,             # PR-1: 뉴스 분석 기준일
                "articles": article_map.get(tk, []),       # PR-2: 원문 기사 + URL
                "newsTimeline": timeline_map.get(tk, []),  # PR-2: 최근 5건 분석 타임라인
                "curatedNews": curated_map.get(tk, []),    # PR-2: 중요 뉴스 큐레이션
                "newsCuratedCount": len(curated_map.get(tk, [])),
                "cat":    [],
                "series":       ser or [],
                "volumeSeries": vol_ser or [],     # PR-4
                "sma20":     sma20,
                "sma50":     sma50,
                "sma200":    sma200,
                "sma60Series":  sma60_series,
                "sma120Series": sma120_series,
                "disparity": disparity,
                "compHist":  comp_hist,
                "momHist":   mom_hist,
                "slope":     slope,
                # PR-2: 보유 정보 (없으면 null)
                "holding": {
                    "qty":         hold_info.get("qty"),
                    "avg_price":   hold_info.get("avg_price"),
                    "cur_price":   hold_info.get("cur_price") or close,
                    "eval_amount": hold_info.get("eval_amount"),
                    "pnl":         hold_info.get("pnl"),
                    "pnl_pct":     hold_info.get("pnl_pct"),
                    "currency":    hold_info.get("currency", "KRW"),
                } if hold_info else None,
                # PR-2: 재무 시계열(매출·영업이익·순이익·OCF·FCF + 추세)
                "financials": financials_map.get(tk, {"annual": [], "quarter": [], "hasData": False}),
                # PR-4: 리서치 항목
                "researchItems": research_items_map.get(tk, []),
                # PR-4(이번): 투자 판단 메모
                "note": notes_map.get(tk),
                "noteHistory": note_history_map.get(tk, []),
                # Wave 2-C: 최근 30일 누적 인사이트
                "insightHistory": ticker_context_map.get(tk, []),
                "drivers": driver_cards_map.get(tk, []),
                # E-2: 투자자 수급 신호 (E-1 기술신호와 별도 레이어 — KR만, US=None)
                # §F7: T+0 과거 데이터, 룩어헤드 없음. 단기 신호 단정 금지.
                "investorFlow": _format_investor_flow(investor_flow_map.get(tk), mk),
                # E-1: 트레이딩 관점 (투자 등급과 별도 레이어 — 덮어쓰지 않음)
                # DB 저장값(trading_signal) 우선 → 신규-F 적중률 추적과 동일한 기준
                "tradingSignal": _compute_trading_signal(
                    rsi14=_f(ind.get("rsi14")),
                    bb_pct=_f(ind.get("bb_pct")),
                    macd_hist=_f(ind.get("macd_hist")),
                    vol_ratio20=_f(ind.get("vol_ratio20")),
                    stoch_k=_f(ind.get("stoch_k")),
                    trading_signal_db=ind.get("trading_signal"),
                    trading_signal_score_db=ind.get("trading_signal_score"),
                ),
                "tradingIndicators": {
                    "macdLine":   _f(ind.get("macd_line")),
                    "macdSignal": _f(ind.get("macd_signal")),
                    "macdHist":   _f(ind.get("macd_hist")),
                    "bbUpper":    _f(ind.get("bb_upper")),
                    "bbLower":    _f(ind.get("bb_lower")),
                    "bbPct":      _f(ind.get("bb_pct")),
                    "stochK":     _f(ind.get("stoch_k")),
                    "stochD":     _f(ind.get("stoch_d")),
                    "volRatio20": _f(ind.get("vol_ratio20")),
                    "atr14":      _f(ind.get("atr14")),
                },
            })

        _attach_display_signals(stocks)

        # PR-3: 액션 신호만 카운트
        rules_count = sum(len(s["flagsAction"]) for s in stocks)

        # PR-1: 실제 가격 기준일(데이터 신선도) — 시장별 최신 거래일
        cur.execute("""
            SELECT w.market, max(p.date) AS d
            FROM prices_daily p JOIN watchlist w USING(ticker)
            WHERE w.active GROUP BY w.market
        """)
        price_asof = {r["market"]: str(r["d"]) for r in cur.fetchall() if r["d"]}
        price_asof_latest = max(price_asof.values()) if price_asof else None

        # PR-2: 전체 중요 뉴스 피드(뉴스 탭 '중요도순') — 종목별 큐레이션 평탄화 + 영향도 내림차순
        curated_feed = []
        for tk_c, items_c in curated_map.items():
            if tk_c not in watchlist_map:
                continue
            for c in (items_c or []):
                curated_feed.append({**c, "t": tk_c,
                                     "name": watchlist_map[tk_c].get("name") or tk_c,
                                     "mk": watchlist_map[tk_c].get("market") or "US"})
        curated_feed.sort(key=lambda x: -(x.get("impact_score") or 0))
        curated_feed = curated_feed[:60]

        # PR-1: 오늘의 요약 밴드(규칙 기반 합성 — 키 없어도 동작, 시장 한 줄은 Gemini 시황 재사용)
        daily_brief = _build_daily_brief(stocks, market)
        # PR-2: 시장 매력도(진입 환경) — kr/us에 부착
        _attach_market_attractiveness(market, stocks)
        # Wave 5-B: 시장 매력도 점수·방향 + 종목 베타 경로 관찰
        _attach_market_score(conn, market, stocks)
        strategy_guidance = _build_strategy_guidance(backtest_data, market)

        # 신규-F: 신호 적중률 요약 (n>=30이어야 notnull, 그 전엔 None — 데이터 축적 대기)
        signal_accuracy = None
        try:
            from src.compute_signal_track import compute_accuracy_summary, SIGNAL_TYPE_A2
            summary = compute_accuracy_summary(conn, SIGNAL_TYPE_A2)
            if summary and summary.get("n", 0) >= 30:
                signal_accuracy = summary
        except Exception as _exc:
            logger.warning("signalAccuracy 요약 실패(비치명적): %s", _exc)

        now = datetime.now()
        refresh_context = _infer_refresh_context(now, price_asof)
        market["refreshContext"] = refresh_context
        market["manualViewLatest"] = market_manual_views[0] if market_manual_views else None
        market["manualViewHistory"] = market_manual_views
        data = {
            "today":      now.strftime("%Y년 %-m월 %-d일 (%a)").replace("Mon","월").replace("Tue","화").replace("Wed","수").replace("Thu","목").replace("Fri","금").replace("Sat","토").replace("Sun","일"),
            "updated":    now.strftime("%H:%M") + " KST",
            # PR-3: 데이터 신선도 가드 — 생성 시각(파싱용 ISO + 표시용 라벨). 프론트가 현재시각과 비교해 경고.
            "generatedAt":      now.strftime("%Y-%m-%dT%H:%M"),      # 로컬(KST) naive ISO
            "generatedAtLabel": now.strftime("%Y-%m-%d %H:%M") + " KST",
            "refreshContext": refresh_context,
            "priceAsof":  price_asof_latest,   # PR-1: 가격 기준일(최신 거래일)
            "priceAsofByMarket": price_asof,   # {"KR": "...", "US": "..."}
            "rulesCount": rules_count,
            "market":     market,
            "regimes":    REGIMES,
            "factorMeta": FACTOR_META,
            "stocks":     stocks,
            "dailyBrief": daily_brief,           # PR-1: 오늘의 요약 밴드
            "news":       news_feed,
            "curatedFeed": curated_feed,         # PR-2: 중요 뉴스(영향도순) — 뉴스 탭 정렬옵션
            "portfolio":  portfolio_snapshot,   # PR-2: 전체 포트폴리오 요약
            "portfolioAdvice": portfolio_advice,  # 전략 조언(CoT) 최근 캐시(+stale)
            "backtest":   backtest_data,        # PR-7: 백테스트 + 회고
            "strategyGuidance": strategy_guidance,
            "signalAccuracy": signal_accuracy,   # 신규-F: n>=30 이전엔 null
            "research":   {
                "files": {}, "notes": {},
                "tags": ["매수후보", "관망", "리스크주의", "장기보유", "분할매수", "비중축소"],
                "activeTags": {},
            },
        }
        return data


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logger.info("export_dashboard_data 시작")
    data = build_data()
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(_OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    logger.info("data.json 생성 완료: %s (%d종목)", _OUT, len(data["stocks"]))
    print(f"✓ data.json 생성: {_OUT}")
    print(f"  종목 {len(data['stocks'])}개 · 뉴스 {len(data['news'])}건 · 레짐 {data['market']['overall']}")


if __name__ == "__main__":
    main()
