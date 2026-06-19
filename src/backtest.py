"""
backtest.py — 전략 라이브러리 기반 true / retrospective 분리 백테스트

§F7 원칙:
  - true track: 과거 시점까지의 가격 데이터만 사용
  - retrospective track: 최신 스냅샷 상위 종목을 고정 바스켓으로 회고
  - 두 트랙은 저장/표시에서 절대 섞지 않는다
"""

from __future__ import annotations

import json
import logging
import math
from datetime import date, datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from src.compute_quant import _zscore, compute_regime
from src.db import get_conn, log_run_finish, log_run_start
from src.strategies import (
    RETROSPECTIVE_STRATEGIES,
    TRUE_STRATEGIES,
    StrategyDefinition,
)

logger = logging.getLogger(__name__)

LOOKBACK_MIN = 252
REBALANCE_STEP = 21
TOP_N_DEFAULT = 8
LOW_VOL_LOOKBACK = 63
PERIODS_PER_YEAR = 12
RETRO_TOP_N = 5
HORIZON_YEARS = {"1y": 1, "3y": 3, "5y": 5}
BENCHMARK_ORDER = ["^KS11", "^GSPC", "^IXIC"]
RETRO_WINDOWS = {"ret1m": 21, "ret3m": 63, "ret6m": 126, "ret12m": 252}


def _load_watchlist(conn) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute("SELECT ticker, name FROM watchlist WHERE active = TRUE ORDER BY ticker")
        return {r["ticker"]: r["name"] for r in cur.fetchall()}


def _load_price_matrix(conn, tickers: list[str]) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ticker, date, close
            FROM prices_daily
            WHERE ticker = ANY(%s) AND close IS NOT NULL
            ORDER BY date
            """,
            (tickers,),
        )
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(r) for r in rows])
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df.pivot_table(index="date", columns="ticker", values="close", aggfunc="last").sort_index().ffill()


def _load_index_matrix(conn) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT index_code, asof, close
            FROM index_daily
            WHERE index_code = ANY(%s)
            ORDER BY asof
            """,
            (BENCHMARK_ORDER,),
        )
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(r) for r in rows])
    df["asof"] = pd.to_datetime(df["asof"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df.pivot_table(index="asof", columns="index_code", values="close", aggfunc="last").sort_index().ffill()


def _load_regime_frame(conn) -> pd.DataFrame:
    index_mat = _load_index_matrix(conn)
    if index_mat.empty:
        return pd.DataFrame(columns=["kospi", "sp500", "vix"])
    df = pd.DataFrame(index=index_mat.index)
    if "^KS11" in index_mat.columns:
        df["kospi"] = pd.to_numeric(index_mat["^KS11"], errors="coerce")
    if "^GSPC" in index_mat.columns:
        df["sp500"] = pd.to_numeric(index_mat["^GSPC"], errors="coerce")

    with conn.cursor() as cur:
        cur.execute("SELECT asof, vix FROM market_daily WHERE vix IS NOT NULL ORDER BY asof")
        vix_rows = cur.fetchall()
    if vix_rows:
        vix_df = pd.DataFrame([dict(r) for r in vix_rows])
        vix_df["asof"] = pd.to_datetime(vix_df["asof"])
        vix_df["vix"] = pd.to_numeric(vix_df["vix"], errors="coerce")
        df = df.join(vix_df.set_index("asof")["vix"], how="left")
    if "vix" not in df.columns:
        df["vix"] = np.nan
    return df.sort_index().ffill()


def _latest_quant_asof(conn) -> Optional[date]:
    with conn.cursor() as cur:
        cur.execute("SELECT max(asof) AS a FROM quant_scores")
        row = cur.fetchone()
    return row["a"] if row and row["a"] else None


def _load_latest_quant_rows(conn) -> tuple[Optional[date], list[dict]]:
    asof = _latest_quant_asof(conn)
    if not asof:
        return None, []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ticker, momentum, value, quality, growth, composite
            FROM quant_scores
            WHERE asof = %s
            """,
            (asof,),
        )
        rows = [dict(r) for r in cur.fetchall()]
    return asof, rows


def _log_ret(arr: np.ndarray, i_from: int, i_to: int) -> Optional[float]:
    if i_from < 0 or i_to < 0 or i_from >= len(arr) or i_to >= len(arr):
        return None
    a, b = arr[i_from], arr[i_to]
    if a is None or b is None or not (a > 0 and b > 0):
        return None
    return float(np.log(b / a))


def _momentum_components(prices: np.ndarray, t: int) -> Optional[dict]:
    if t < 21 or np.isnan(prices[t]):
        return None
    return {
        "m_1m": _log_ret(prices, max(0, t - 21), t),
        "m_3m": _log_ret(prices, max(0, t - 63), max(0, t - 5)),
        "m_6m": _log_ret(prices, max(0, t - 126), max(0, t - 21)),
        "m_12m": _log_ret(prices, max(0, t - 252), max(0, t - 21)),
    }


def _momentum_scores_at(mat: pd.DataFrame, t: int) -> dict[str, float]:
    comps: dict[str, dict] = {}
    for ticker in mat.columns:
        prices = mat[ticker].values.astype(float)
        comp = _momentum_components(prices, t)
        if comp and all(comp[k] is not None for k in ("m_1m", "m_3m", "m_6m", "m_12m")):
            comps[ticker] = comp
    if not comps:
        return {}
    z1 = _zscore({tk: c["m_1m"] for tk, c in comps.items()})
    z3 = _zscore({tk: c["m_3m"] for tk, c in comps.items()})
    z6 = _zscore({tk: c["m_6m"] for tk, c in comps.items()})
    z12 = _zscore({tk: c["m_12m"] for tk, c in comps.items()})
    return {
        tk: 0.10 * z1[tk] + 0.20 * z3[tk] + 0.30 * z6[tk] + 0.40 * z12[tk]
        for tk in comps
    }


def _low_vol_scores_at(mat: pd.DataFrame, t: int) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ticker in mat.columns:
        series = mat[ticker].iloc[max(0, t - LOW_VOL_LOOKBACK): t + 1].dropna()
        if len(series) < 22:
            continue
        rets = series.pct_change().dropna()
        if len(rets) < 20:
            continue
        vol = float(rets.std(ddof=1))
        if not np.isnan(vol):
            scores[ticker] = -vol
    return scores


def _rebase_curve_from_series(series: pd.Series) -> list[dict]:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return []
    base = float(clean.iloc[0])
    if base <= 0:
        return []
    return [
        {"date": ts.date().isoformat(), "value": round(float(val / base * 100.0), 3)}
        for ts, val in clean.items()
    ]


def _metrics_from_equity(curve: list[dict]) -> dict:
    if len(curve) < 2:
        return {"cum_return": 0.0, "cagr": 0.0, "mdd": 0.0, "vol": 0.0, "sharpe": 0.0}
    vals = np.array([float(p["value"]) for p in curve], dtype=float)
    cum_return = float(vals[-1] / vals[0] - 1)

    d0 = datetime.fromisoformat(curve[0]["date"]).date()
    d1 = datetime.fromisoformat(curve[-1]["date"]).date()
    years = max((d1 - d0).days / 365.25, 1e-9)
    cagr = float((vals[-1] / vals[0]) ** (1 / years) - 1) if vals[0] > 0 else 0.0

    peak = np.maximum.accumulate(vals)
    dd = (vals - peak) / peak
    mdd = float(dd.min())

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


def _regime_returns_from_periods(periods: list[dict]) -> dict[str, float | None]:
    out: dict[str, float | None] = {"bull": None, "neutral": None, "bear": None}
    for regime in ("bull", "neutral", "bear"):
        acc = 1.0
        used = False
        for row in periods:
            if row["regime"] != regime:
                continue
            acc *= 1.0 + float(row["return"])
            used = True
        out[regime] = round(acc - 1.0, 4) if used else None
    return out


def _rebalancing_points(n_rows: int) -> list[int]:
    points = list(range(LOOKBACK_MIN, n_rows, REBALANCE_STEP))
    if points and points[-1] != n_rows - 1:
        points.append(n_rows - 1)
    return points


def _portfolio_period_return(mat: pd.DataFrame, tickers: list[str], i_from: int, i_to: int) -> float:
    rets = []
    for ticker in tickers:
        a = mat[ticker].iloc[i_from]
        b = mat[ticker].iloc[i_to]
        if a and b and a > 0 and not (math.isnan(a) or math.isnan(b)):
            rets.append(b / a - 1)
    return float(np.mean(rets)) if rets else 0.0


def _sample_index_series(index_mat: pd.DataFrame, dates: pd.Index) -> dict[str, pd.Series]:
    if index_mat.empty:
        return {}
    sampled: dict[str, pd.Series] = {}
    for code in BENCHMARK_ORDER:
        if code not in index_mat.columns:
            continue
        s = pd.to_numeric(index_mat[code], errors="coerce").reindex(dates).ffill().dropna()
        if len(s):
            sampled[code] = s
    return sampled


def _slice_series_by_years(series: pd.Series, years: int) -> pd.Series:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if len(clean) < 2:
        return clean
    end = clean.index[-1]
    start = end - pd.Timedelta(days=int(years * 365.25))
    sliced = clean[clean.index >= start]
    return sliced if len(sliced) >= 2 else clean


def _slice_periods_by_start(periods: list[dict], start_date: date) -> list[dict]:
    return [p for p in periods if p["end"] >= start_date]


def _select_top(scores: dict[str, float], top_n: int) -> list[str]:
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return [ticker for ticker, _ in ranked[:top_n]]


def _period_returns_for(mat: pd.DataFrame, ticker: str) -> dict:
    if ticker not in mat.columns:
        return {k: None for k in RETRO_WINDOWS}
    series = pd.to_numeric(mat[ticker], errors="coerce").dropna()
    if len(series) == 0:
        return {k: None for k in RETRO_WINDOWS}
    last = float(series.iloc[-1])
    out = {}
    for key, off in RETRO_WINDOWS.items():
        if len(series) > off:
            past = float(series.iloc[-1 - off])
            out[key] = round(last / past - 1, 4) if past > 0 else None
        else:
            out[key] = None
    return out


def _regime_by_date(regime_frame: pd.DataFrame, dates: pd.Index) -> dict[date, str]:
    if regime_frame.empty:
        return {ts.date(): "neutral" for ts in dates}
    out: dict[date, str] = {}
    for ts in dates:
        window = regime_frame.loc[:ts]
        out[ts.date()] = compute_regime(window)
    return out


def _simulate_rebalanced_strategy(
    mat: pd.DataFrame,
    selector,
    top_n: int,
    regime_lookup: dict[date, str],
) -> tuple[pd.Series, list[dict], list[dict]]:
    rebal = _rebalancing_points(len(mat))
    dates = mat.index
    value = 1.0
    wealth = [(dates[rebal[0]], value)]
    periods: list[dict] = []
    selection_examples: list[dict] = []

    for left, right in zip(rebal, rebal[1:]):
        selection = selector(mat, left, top_n)
        if not selection:
            selection = list(mat.columns)
        ret = _portfolio_period_return(mat, selection, left, right)
        value *= 1.0 + ret
        ts_left = dates[left].date()
        ts_right = dates[right].date()
        periods.append({"start": ts_left, "end": ts_right, "return": round(ret, 6), "regime": regime_lookup.get(ts_left, "neutral")})
        wealth.append((dates[right], value))
        selection_examples.append({"date": ts_left.isoformat(), "tickers": selection})

    wealth_series = pd.Series({ts: val for ts, val in wealth}).sort_index()
    return wealth_series, periods, selection_examples[-3:]


def _simulate_buy_hold(mat: pd.DataFrame, regime_lookup: dict[date, str]) -> tuple[pd.Series, list[dict]]:
    rebal = _rebalancing_points(len(mat))
    dates = mat.index
    base = mat.iloc[rebal[0]]
    wealth = [(dates[rebal[0]], 1.0)]
    periods: list[dict] = []

    for left, right in zip(rebal, rebal[1:]):
        left_norm = (mat.iloc[left] / base).replace([np.inf, -np.inf], np.nan).dropna()
        right_norm = (mat.iloc[right] / base).replace([np.inf, -np.inf], np.nan).dropna()
        prev_val = float(left_norm.mean()) if len(left_norm) else 1.0
        cur_val = float(right_norm.mean()) if len(right_norm) else prev_val
        ret = cur_val / prev_val - 1 if prev_val > 0 else 0.0
        ts_left = dates[left].date()
        ts_right = dates[right].date()
        periods.append({"start": ts_left, "end": ts_right, "return": round(float(ret), 6), "regime": regime_lookup.get(ts_left, "neutral")})
        wealth.append((dates[right], cur_val))

    return pd.Series({ts: val for ts, val in wealth}).sort_index(), periods


def _build_true_strategy_outputs(
    definition: StrategyDefinition,
    mat: pd.DataFrame,
    regime_lookup: dict[date, str],
    top_n: int,
) -> tuple[pd.Series, list[dict], dict]:
    if definition.name == "momentum_12_1":
        wealth, periods, selections = _simulate_rebalanced_strategy(
            mat, lambda m, t, n: _select_top(_momentum_scores_at(m, t), n), top_n, regime_lookup
        )
        return wealth, periods, {"selection_examples": selections}
    if definition.name == "low_vol":
        wealth, periods, selections = _simulate_rebalanced_strategy(
            mat, lambda m, t, n: _select_top(_low_vol_scores_at(m, t), n), top_n, regime_lookup
        )
        return wealth, periods, {"selection_examples": selections}
    wealth, periods = _simulate_buy_hold(mat, regime_lookup)
    return wealth, periods, {"selection_examples": []}


def _build_retrospective_output(
    definition: StrategyDefinition,
    mat: pd.DataFrame,
    watchlist: dict[str, str],
    regime_lookup: dict[date, str],
    quant_rows: list[dict],
    top_n: int,
) -> tuple[pd.Series, list[dict], dict]:
    factor_key = "composite" if definition.name == "multifactor" else definition.factor_key
    ranked = [(row["ticker"], row.get(factor_key)) for row in quant_rows if row.get(factor_key) is not None]
    ranked.sort(key=lambda item: float(item[1]), reverse=True)
    selected = [ticker for ticker, _ in ranked[:top_n]]
    if not selected:
        selected = list(mat.columns[:top_n])

    rebal = _rebalancing_points(len(mat))
    dates = mat.index
    value = 1.0
    wealth = [(dates[rebal[0]], value)]
    periods: list[dict] = []
    for left, right in zip(rebal, rebal[1:]):
        ret = _portfolio_period_return(mat, selected, left, right)
        value *= 1.0 + ret
        ts_left = dates[left].date()
        ts_right = dates[right].date()
        periods.append({"start": ts_left, "end": ts_right, "return": round(ret, 6), "regime": regime_lookup.get(ts_left, "neutral")})
        wealth.append((dates[right], value))

    payload = {
        "selected_tickers": [{"ticker": tk, "name": watchlist.get(tk, tk)} for tk in selected],
        "warning": "선택편향 경고: 최신 스냅샷 상위 종목을 과거 구간에 고정해 되돌아본 참고용 회고입니다.",
    }
    return pd.Series({ts: val for ts, val in wealth}).sort_index(), periods, payload


def _upsert_backtest_row(
    conn,
    definition: StrategyDefinition,
    horizon: str,
    metrics: dict,
    regime_returns: dict,
    payload: dict,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM backtest_results WHERE strategy = %s AND track = %s AND horizon = %s",
            (definition.name, definition.track, horizon),
        )
        cur.execute(
            """
            INSERT INTO backtest_results
                (strategy_name, metric_type, strategy, track, horizon,
                 window_start, window_end, cum_return, cagr, mdd, vol, sharpe,
                 regime_returns, payload)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
            """,
            (
                definition.name,
                "true_backtest" if definition.track == "true" else "retrospective",
                definition.name,
                definition.track,
                horizon,
                payload.get("window_start"),
                payload.get("window_end"),
                metrics.get("cum_return"),
                metrics.get("cagr"),
                metrics.get("mdd"),
                metrics.get("vol"),
                metrics.get("sharpe"),
                json.dumps(regime_returns, ensure_ascii=False),
                json.dumps(payload, ensure_ascii=False),
            ),
        )


def _persist_strategy_family(
    conn,
    definition: StrategyDefinition,
    wealth: pd.Series,
    periods: list[dict],
    sampled_benchmarks: dict[str, pd.Series],
    payload_extra: dict,
) -> dict:
    saved = {}
    for horizon, years in HORIZON_YEARS.items():
        wealth_slice = _slice_series_by_years(wealth, years)
        curve = _rebase_curve_from_series(wealth_slice)
        if len(curve) < 2:
            continue
        start_date = datetime.fromisoformat(curve[0]["date"]).date()
        metrics = _metrics_from_equity(curve)
        regime_returns = _regime_returns_from_periods(_slice_periods_by_start(periods, start_date))
        benchmarks = {
            code: _rebase_curve_from_series(_slice_series_by_years(series[series.index >= pd.Timestamp(start_date)], years))
            for code, series in sampled_benchmarks.items()
        }
        payload = {
            "label": definition.label,
            "description": definition.description,
            "equity_curve": curve,
            "benchmarks": benchmarks,
            "window_start": curve[0]["date"],
            "window_end": curve[-1]["date"],
            **payload_extra,
        }
        _upsert_backtest_row(conn, definition, horizon, metrics, regime_returns, payload)
        saved[horizon] = metrics
    return saved


def compute_true_backtests(conn, top_n: int = TOP_N_DEFAULT) -> dict:
    watchlist = _load_watchlist(conn)
    mat = _load_price_matrix(conn, list(watchlist.keys()))
    if mat.empty or len(mat) < LOOKBACK_MIN + REBALANCE_STEP:
        return {"ok": False, "reason": "insufficient_data"}

    regime_frame = _load_regime_frame(conn)
    regime_lookup = _regime_by_date(regime_frame, mat.index)
    index_series = _sample_index_series(_load_index_matrix(conn), mat.index[_rebalancing_points(len(mat))])

    saved = []
    for definition in TRUE_STRATEGIES:
        wealth, periods, payload_extra = _build_true_strategy_outputs(definition, mat, regime_lookup, top_n)
        horizons = _persist_strategy_family(conn, definition, wealth, periods, index_series, payload_extra)
        saved.append({"name": definition.name, "horizons": horizons})
    conn.commit()
    return {"ok": True, "strategies": saved}


def compute_momentum_backtest(conn, top_n: int = TOP_N_DEFAULT) -> dict:
    return compute_true_backtests(conn, top_n=top_n)


def compute_retrospective(conn, top_n: int = RETRO_TOP_N) -> dict:
    asof, quant_rows = _load_latest_quant_rows(conn)
    if not asof or not quant_rows:
        return {"ok": False, "reason": "no_quant"}
    watchlist = _load_watchlist(conn)
    mat = _load_price_matrix(conn, list(watchlist.keys()))
    if mat.empty or len(mat) < LOOKBACK_MIN + REBALANCE_STEP:
        return {"ok": False, "reason": "insufficient_data"}

    regime_frame = _load_regime_frame(conn)
    regime_lookup = _regime_by_date(regime_frame, mat.index)
    index_series = _sample_index_series(_load_index_matrix(conn), mat.index[_rebalancing_points(len(mat))])

    saved = []
    for definition in RETROSPECTIVE_STRATEGIES:
        wealth, periods, payload_extra = _build_retrospective_output(definition, mat, watchlist, regime_lookup, quant_rows, top_n)
        payload_extra["asof"] = str(asof)
        horizons = _persist_strategy_family(conn, definition, wealth, periods, index_series, payload_extra)
        saved.append({"name": definition.name, "horizons": horizons})
    conn.commit()
    return {"ok": True, "strategies": saved, "asof": str(asof)}


def run_backtest(conn) -> dict:
    true_track = compute_true_backtests(conn)
    retrospective = compute_retrospective(conn)
    return {"true": true_track, "retrospective": retrospective}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    with get_conn() as conn:
        run_id = log_run_start(conn, "backtest")
        errors: list[dict] = []
        status = "success"
        try:
            result = run_backtest(conn)
            logger.info("backtest result: %s", json.dumps(result, ensure_ascii=False, default=str)[:600])
        except Exception as exc:
            logger.error("backtest failed: %s", exc, exc_info=True)
            errors.append({"step": "backtest", "error": str(exc), "ts": datetime.utcnow().isoformat()})
            status = "failed"
        log_run_finish(conn, run_id, status=status, errors=errors)
