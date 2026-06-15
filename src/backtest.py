"""
backtest.py — 멀티전략 비교 (진짜 백테스트 + 회고)

⚠️ 핵심 원칙 (PRD §F7): 두 개념을 절대 혼동하지 않는다.
  1) compute_momentum_backtest — **진짜 백테스트(true_backtest)**
     각 과거 시점 t에서 't까지의 가격 데이터만'으로 모멘텀을 계산·선정한다.
     미래 정보(look-ahead)가 없으므로 실제 운용 가능한 전략 성과 추정.
  2) compute_retrospective — **회고(retrospective)**
     valuation/analyst가 '오늘' 스냅샷 1건뿐이라 과거 재현 불가 → 오늘 선정한 상위 종목의
     과거 수익률을 '되돌아보는' 것. **선정시점편향(look-ahead/survivorship)** 이 있어
     백테스트가 아니다. 화면에서 반드시 '참고용 · 백테스트 아님'으로 구분 표기.

모멘텀 공식(PRD §F4): 0.10·Z(1M) + 0.20·Z(3M) + 0.30·Z(6M) + 0.40·Z(12-1M),
12-1M = 최근 1개월 skip(단기 되돌림 제거). compute_quant._zscore 재사용.

⚠️ 투자 자문 아님 / 원금 손실 가능. 과거 성과는 미래를 보장하지 않는다.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd
import psycopg

from src.compute_quant import _zscore
from src.db import get_conn, log_run_finish, log_run_start

logger = logging.getLogger(__name__)

# 리밸런싱·룩백 파라미터 (영업일)
LOOKBACK_MIN = 252         # 백테스트 시작에 필요한 최소 데이터(12M)
REBALANCE_STEP = 21        # 약 1개월마다 리밸런싱
TOP_N_DEFAULT = 8
PERIODS_PER_YEAR = 12      # 월별 리밸런싱 → 연 12회

# 회고 룩백 (영업일)
RETRO_WINDOWS = {"ret1m": 21, "ret3m": 63, "ret6m": 126, "ret12m": 252}
RETRO_TOP_N = 5
RETRO_FACTORS = ["momentum", "value", "quality", "growth", "composite"]


# ──────────────────────────────────────────────────────────────
# 데이터 로드
# ──────────────────────────────────────────────────────────────

def _load_watchlist(conn) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute("SELECT ticker, name FROM watchlist WHERE active = TRUE ORDER BY ticker")
        return {r["ticker"]: r["name"] for r in cur.fetchall()}


def _load_price_matrix(conn, tickers: list[str]) -> pd.DataFrame:
    """
    prices_daily → date×ticker 종가 매트릭스.
    KR/US 거래 캘린더가 달라 결측이 생기므로 union 날짜축 + 전일값 ffill로 정렬한다.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ticker, date, close FROM prices_daily WHERE ticker = ANY(%s) AND close IS NOT NULL ORDER BY date",
            (tickers,),
        )
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(r) for r in rows])
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    mat = df.pivot_table(index="date", columns="ticker", values="close", aggfunc="last")
    mat = mat.sort_index().ffill()
    return mat


# ──────────────────────────────────────────────────────────────
# 모멘텀 점수 (시점 t까지의 데이터만 사용)
# ──────────────────────────────────────────────────────────────

def _log_ret(arr: np.ndarray, i_from: int, i_to: int) -> Optional[float]:
    if i_from < 0 or i_to < 0 or i_from >= len(arr) or i_to >= len(arr):
        return None
    a, b = arr[i_from], arr[i_to]
    if a is None or b is None or not (a > 0 and b > 0):
        return None
    return float(np.log(b / a))


def _momentum_components(prices: np.ndarray, t: int) -> Optional[dict]:
    """index t(포함)까지의 가격으로 1M/3M/6M/12-1M 로그수익률. 데이터 부족 시 None."""
    if t < 21 or np.isnan(prices[t]):
        return None
    return {
        "m_1m":  _log_ret(prices, max(0, t - 21), t),
        "m_3m":  _log_ret(prices, max(0, t - 63), max(0, t - 5)),
        "m_6m":  _log_ret(prices, max(0, t - 126), max(0, t - 21)),
        "m_12m": _log_ret(prices, max(0, t - 252), max(0, t - 21)),
    }


def _momentum_scores_at(mat: pd.DataFrame, t: int) -> dict[str, float]:
    """시점 t에서 유니버스 모멘텀 점수(가중 Z-score). 데이터 없는 종목은 제외."""
    comps: dict[str, dict] = {}
    for tk in mat.columns:
        prices = mat[tk].values.astype(float)
        c = _momentum_components(prices, t)
        if c and all(c[k] is not None for k in ("m_1m", "m_3m", "m_6m", "m_12m")):
            comps[tk] = c
    if not comps:
        return {}
    z1m  = _zscore({tk: c["m_1m"]  for tk, c in comps.items()})
    z3m  = _zscore({tk: c["m_3m"]  for tk, c in comps.items()})
    z6m  = _zscore({tk: c["m_6m"]  for tk, c in comps.items()})
    z12m = _zscore({tk: c["m_12m"] for tk, c in comps.items()})
    return {
        tk: 0.10 * z1m[tk] + 0.20 * z3m[tk] + 0.30 * z6m[tk] + 0.40 * z12m[tk]
        for tk in comps
    }


# ──────────────────────────────────────────────────────────────
# 성과 지표
# ──────────────────────────────────────────────────────────────

def _metrics_from_equity(curve: list[dict]) -> dict:
    """equity curve [{date, value}] → cum_return, CAGR, MDD, vol, sharpe."""
    if len(curve) < 2:
        return {"cum_return": 0.0, "cagr": 0.0, "mdd": 0.0, "vol": 0.0, "sharpe": 0.0}
    vals = np.array([p["value"] for p in curve], dtype=float)
    cum_return = float(vals[-1] / vals[0] - 1)

    d0 = datetime.fromisoformat(curve[0]["date"]).date()
    d1 = datetime.fromisoformat(curve[-1]["date"]).date()
    years = max((d1 - d0).days / 365.25, 1e-9)
    cagr = float((vals[-1] / vals[0]) ** (1 / years) - 1) if vals[0] > 0 else 0.0

    # MDD
    peak = np.maximum.accumulate(vals)
    dd = (vals - peak) / peak
    mdd = float(dd.min())

    # 기간(월별) 수익률
    rets = vals[1:] / vals[:-1] - 1
    if len(rets) >= 2 and rets.std() > 0:
        vol = float(rets.std(ddof=1) * math.sqrt(PERIODS_PER_YEAR))
        sharpe = float(rets.mean() / rets.std(ddof=1) * math.sqrt(PERIODS_PER_YEAR))
    else:
        vol = 0.0
        sharpe = 0.0

    return {
        "cum_return": round(cum_return, 4),
        "cagr": round(cagr, 4),
        "mdd": round(mdd, 4),
        "vol": round(vol, 4),
        "sharpe": round(sharpe, 4),
    }


# ──────────────────────────────────────────────────────────────
# 1) 진짜 백테스트 (모멘텀 top_n + 벤치마크 2종)
# ──────────────────────────────────────────────────────────────

def compute_momentum_backtest(conn, top_n: int = TOP_N_DEFAULT) -> dict:
    """
    모멘텀 top_n 동일가중 전략 + 동일가중 벤치마크 + Buy&Hold 벤치마크.
    각 리밸런싱 시점에서 그 시점까지의 데이터만으로 모멘텀 선정(미래정보 없음).
    결과를 backtest_results(metric_type='true_backtest')에 upsert.
    """
    watchlist = _load_watchlist(conn)
    tickers = list(watchlist.keys())
    mat = _load_price_matrix(conn, tickers)
    if mat.empty or len(mat) < LOOKBACK_MIN + REBALANCE_STEP:
        logger.warning("백테스트: 데이터 부족 (rows=%d) — 스킵", len(mat))
        return {"ok": False, "reason": "insufficient_data"}

    dates = mat.index
    n = len(mat)
    # 리밸런싱 인덱스: 252부터 STEP 간격, 마지막까지
    rebal_idx = list(range(LOOKBACK_MIN, n, REBALANCE_STEP))
    if rebal_idx and rebal_idx[-1] != n - 1:
        rebal_idx.append(n - 1)  # 마지막 시점 포함(평가 종료)

    mom_curve = [{"date": dates[rebal_idx[0]].date().isoformat(), "value": 1.0}]
    eqw_curve = [{"date": dates[rebal_idx[0]].date().isoformat(), "value": 1.0}]
    bh_curve  = [{"date": dates[rebal_idx[0]].date().isoformat(), "value": 1.0}]

    mom_val, eqw_val = 1.0, 1.0
    # Buy&Hold: 최초 시점 동일가중, 정규화 가격의 평균
    bh_start = rebal_idx[0]
    bh_base = mat.iloc[bh_start]
    selections: list[dict] = []

    def period_return(sel: list[str], i_from: int, i_to: int) -> float:
        rets = []
        for tk in sel:
            a = mat[tk].iloc[i_from]
            b = mat[tk].iloc[i_to]
            if a and b and a > 0 and not (math.isnan(a) or math.isnan(b)):
                rets.append(b / a - 1)
        return float(np.mean(rets)) if rets else 0.0

    for k in range(len(rebal_idx) - 1):
        r, r2 = rebal_idx[k], rebal_idx[k + 1]

        # 모멘텀 선정 (시점 r까지 데이터만)
        scores = _momentum_scores_at(mat, r)
        if scores:
            top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_n]
            sel = [tk for tk, _ in top]
        else:
            sel = list(mat.columns)
        selections.append({"date": dates[r].date().isoformat(), "tickers": sel})

        # 보유 구간 수익률
        mom_val *= (1 + period_return(sel, r, r2))
        eqw_val *= (1 + period_return(list(mat.columns), r, r2))

        # Buy&Hold value at r2 = mean(P[r2]/P[bh_start])
        bh_norm = (mat.iloc[r2] / bh_base).replace([np.inf, -np.inf], np.nan).dropna()
        bh_val = float(bh_norm.mean()) if len(bh_norm) else 1.0

        d2 = dates[r2].date().isoformat()
        mom_curve.append({"date": d2, "value": round(mom_val, 6)})
        eqw_curve.append({"date": d2, "value": round(eqw_val, 6)})
        bh_curve.append({"date": d2, "value": round(bh_val, 6)})

    window_start = dates[rebal_idx[0]].date()
    window_end = dates[rebal_idx[-1]].date()
    months = round((window_end - window_start).days / 30.44, 1)

    strategies = [
        ("momentum_top8", mom_curve, {"top_n": top_n, "selections": selections[-3:]}),
        ("equal_weight_benchmark", eqw_curve, {"note": "전체 동일가중, 매 리밸런싱 재가중"}),
        ("buy_hold_benchmark", bh_curve, {"note": "최초 동일가중 매수 후 보유"}),
    ]

    saved = []
    for name, curve, extra in strategies:
        m = _metrics_from_equity(curve)
        payload = {"equity_curve": curve, "months": months, **extra}
        _upsert_backtest(conn, name, "true_backtest", window_start, window_end, m, payload)
        saved.append({"name": name, **m})
    conn.commit()
    logger.info("진짜 백테스트 저장: %d전략 (%s~%s, %s개월)", len(saved), window_start, window_end, months)
    return {"ok": True, "strategies": saved, "window": {"start": str(window_start), "end": str(window_end), "months": months}}


# ──────────────────────────────────────────────────────────────
# 2) 회고 (오늘 quant 상위 종목의 과거 수익률)
# ──────────────────────────────────────────────────────────────

def _latest_quant_asof(conn) -> Optional[date]:
    with conn.cursor() as cur:
        cur.execute("SELECT max(asof) AS a FROM quant_scores")
        r = cur.fetchone()
    return r["a"] if r and r["a"] else None


def _period_returns_for(mat: pd.DataFrame, ticker: str) -> dict:
    """ticker의 최근값 기준 1/3/6/12개월 가격수익률(영업일 오프셋)."""
    if ticker not in mat.columns:
        return {k: None for k in RETRO_WINDOWS}
    s = mat[ticker].dropna()
    if len(s) == 0:
        return {k: None for k in RETRO_WINDOWS}
    last = float(s.iloc[-1])
    out = {}
    for key, off in RETRO_WINDOWS.items():
        if len(s) > off:
            past = float(s.iloc[-1 - off])
            out[key] = round(last / past - 1, 4) if past > 0 else None
        else:
            out[key] = None
    return out


def compute_retrospective(conn) -> dict:
    """
    오늘 quant_scores에서 팩터별 상위 RETRO_TOP_N 종목 → 1/3/6/12개월 과거 수익률 + 벤치마크.
    ⚠️ 선정시점편향 — 백테스트 아님(retrospective).
    """
    asof = _latest_quant_asof(conn)
    if not asof:
        logger.warning("회고: quant_scores 없음 — 스킵")
        return {"ok": False, "reason": "no_quant"}

    watchlist = _load_watchlist(conn)
    mat = _load_price_matrix(conn, list(watchlist.keys()))
    if mat.empty:
        return {"ok": False, "reason": "no_prices"}

    # 벤치마크: 전체 동일가중 평균 수익률
    bench_each = [_period_returns_for(mat, tk) for tk in mat.columns]
    benchmark = {}
    for key in RETRO_WINDOWS:
        vals = [d[key] for d in bench_each if d[key] is not None]
        benchmark[key] = round(float(np.mean(vals)), 4) if vals else None

    with conn.cursor() as cur:
        cur.execute(
            "SELECT ticker, momentum, value, quality, growth, composite FROM quant_scores WHERE asof = %s",
            (asof,),
        )
        qrows = [dict(r) for r in cur.fetchall()]

    saved = []
    for factor in RETRO_FACTORS:
        # composite은 None(사전필터 제외) 제거
        candidates = [(r["ticker"], r[factor]) for r in qrows if r.get(factor) is not None]
        candidates.sort(key=lambda x: float(x[1]), reverse=True)
        top = candidates[:RETRO_TOP_N]

        top_list = []
        for tk, score in top:
            pr = _period_returns_for(mat, tk)
            top_list.append({
                "ticker": tk, "name": watchlist.get(tk, tk),
                "score": round(float(score), 1), **pr,
            })

        payload = {
            "factor": factor,
            "asof": str(asof),
            "top_tickers": top_list,
            "benchmark": benchmark,
            "warning": "선정시점편향 — 오늘 상위 종목의 과거 수익률(백테스트 아님)",
        }
        # 대표 수치: 상위 종목 평균 12개월 수익률
        r12s = [t["ret12m"] for t in top_list if t["ret12m"] is not None]
        cum = round(float(np.mean(r12s)), 4) if r12s else None
        _upsert_backtest(conn, f"retrospective_{factor}", "retrospective", None, None,
                         {"cum_return": cum, "cagr": None, "mdd": None, "vol": None, "sharpe": None},
                         payload)
        saved.append(factor)

    conn.commit()
    logger.info("회고 저장: %d팩터 (asof=%s)", len(saved), asof)
    return {"ok": True, "factors": saved, "asof": str(asof)}


# ──────────────────────────────────────────────────────────────
# upsert 헬퍼
# ──────────────────────────────────────────────────────────────

def _upsert_backtest(conn, name: str, metric_type: str,
                     w_start: Optional[date], w_end: Optional[date],
                     m: dict, payload: dict) -> None:
    """동일 strategy_name의 최신 1건만 유지(삭제 후 삽입)."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM backtest_results WHERE strategy_name = %s", (name,))
        cur.execute(
            """
            INSERT INTO backtest_results
                (strategy_name, metric_type, window_start, window_end,
                 cum_return, cagr, mdd, vol, sharpe, payload)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (name, metric_type, w_start, w_end,
             m.get("cum_return"), m.get("cagr"), m.get("mdd"), m.get("vol"), m.get("sharpe"),
             json.dumps(payload, ensure_ascii=False)),
        )


# ──────────────────────────────────────────────────────────────
# 실행
# ──────────────────────────────────────────────────────────────

def run_backtest(conn) -> dict:
    """백테스트 + 회고 실행(파이프라인/단독 공용)."""
    bt = compute_momentum_backtest(conn)
    retro = compute_retrospective(conn)
    return {"true_backtest": bt, "retrospective": retro}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    with get_conn() as conn:
        run_id = log_run_start(conn, "backtest")
        errors: list[dict] = []
        status = "success"
        try:
            result = run_backtest(conn)
            logger.info("백테스트 결과: %s", json.dumps(result, ensure_ascii=False, default=str)[:400])
        except Exception as exc:
            logger.error("백테스트 실패: %s", exc, exc_info=True)
            errors.append({"step": "backtest", "error": str(exc), "ts": datetime.utcnow().isoformat()})
            status = "failed"
        log_run_finish(conn, run_id, status=status, errors=errors)
    print("\n⚠️ 투자 자문 아님 / 원금 손실 가능. 과거 성과는 미래를 보장하지 않습니다.")
