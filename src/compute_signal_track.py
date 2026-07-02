"""
compute_signal_track.py — 신호 적중률 추적 (신규-F)

A2 등급(매수/관망/축소)의 전향 자기검증.
§F7: asof 이전 정보로 만든 등급을, asof 이후 prices_daily로만 검증.
결정론 계산: 네트워크·LLM 없음. prices_daily + index_daily JOIN만.

실행:
  python -m src.compute_signal_track            # A2_grade 전체(신규 삽입 + 미결 갱신)
  python -m src.compute_signal_track --backfill  # 과거 전체 일괄(초기 1회)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date
from typing import Optional

import pandas as pd
import psycopg
from scipy import stats as scipy_stats

from src import db

logger = logging.getLogger(__name__)

SIGNAL_TYPE_A2 = "A2_grade"
N_DAYS_DEFAULT: tuple[int, ...] = (5, 20, 60)

# ponytail: 관망 적중 판정 허용 구간(임의적 — 설계 §3.1). 환경변수로 override 가능.
GRADE_NEUTRAL_BAND = float(os.environ.get("GRADE_NEUTRAL_BAND", "0.10"))

_BENCH_DEFAULT = {"KR": "^KS11", "US": "^GSPC"}
_KOSDAQ_TICKERS: frozenset[str] = frozenset(
    t.strip() for t in os.environ.get("KOSDAQ_TICKERS", "").split(",") if t.strip()
)


# ── 순수 계산 (DB·네트워크 없음, 테스트 가능) ────────────────


def benchmark_for(ticker: str, market: str) -> str:
    if market == "KR" and ticker in _KOSDAQ_TICKERS:
        return "^KQ11"
    return _BENCH_DEFAULT.get(market, "^GSPC")


def hit_excess(grade: str, excess: float) -> Optional[bool]:
    """초과수익 기준 적중 판정."""
    if grade == "매수":
        return excess > 0
    if grade == "축소":
        return excess < 0
    if grade == "관망":
        return abs(excess) <= GRADE_NEUTRAL_BAND
    return None


def hit_raw(grade: str, raw: float) -> Optional[bool]:
    """절대수익 기준 적중 판정 (참고용)."""
    if grade == "매수":
        return raw > 0
    if grade == "축소":
        return raw < 0
    if grade == "관망":
        return abs(raw) <= GRADE_NEUTRAL_BAND
    return None


def resolve_entry_exit(
    prices: pd.DataFrame, asof: date, n: int
) -> dict:
    """
    진입가(asof 이후 첫 거래일)와 n 거래일 후 청산가를 찾는다.
    prices: close 컬럼, DatetimeIndex(date 기반).
    반환: {entry_date, entry_price, exit_date, exit_price, pending}.
    """
    result: dict = {
        "entry_date": None, "entry_price": None,
        "exit_date": None, "exit_price": None,
        "pending": True,
    }
    future = prices[prices.index > pd.Timestamp(asof)]
    if future.empty:
        return result
    result["entry_date"] = future.index[0].date()
    result["entry_price"] = float(future.iloc[0]["close"])

    # offset=n: entry=offset 0, +1일=offset 1, +n일=offset n
    if len(future) > n:
        result["exit_date"] = future.index[n].date()
        result["exit_price"] = float(future.iloc[n]["close"])
        result["pending"] = False
    return result


def compute_returns(
    entry_price: float, exit_price: float,
    bench_entry: Optional[float], bench_exit: Optional[float],
    grade: str,
) -> dict:
    """
    수익률·초과수익률·적중 여부를 계산한다.
    반환: {raw_return, bench_return, excess_return, hit_excess, hit_raw}.
    """
    raw = exit_price / entry_price - 1
    bench_ret = bench_exit / bench_entry - 1 if (bench_entry and bench_exit) else None
    excess = raw - bench_ret if bench_ret is not None else None
    return {
        "raw_return": raw,
        "bench_return": bench_ret,
        "excess_return": excess,
        "hit_excess": hit_excess(grade, excess) if excess is not None else None,
        "hit_raw": hit_raw(grade, raw),
    }


def spearman_ic(grades: list[str], excess_returns: list[float]) -> dict:
    """
    Spearman IC(등급→초과수익 상관). 매수=+1, 관망=0, 축소=−1.
    반환: {ic, p_value, n}.
    """
    grade_score = {"매수": 1, "관망": 0, "축소": -1}
    pairs = [(grade_score.get(g, 0), e) for g, e in zip(grades, excess_returns)]
    n = len(pairs)
    if n < 2:
        return {"ic": None, "p_value": None, "n": n}
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    result = scipy_stats.spearmanr(xs, ys)
    corr = float(result.statistic) if hasattr(result, "statistic") else float(result.correlation)
    return {"ic": round(corr, 3), "p_value": round(float(result.pvalue), 3), "n": n}


def n_warning(n: int) -> Optional[str]:
    """표본 크기 경고 문구."""
    if n < 10:
        return "표본 부족 — 참고 불가"
    if n < 30:
        return "표본 소규모 — 추세 참고만"
    return None


# ── DB 헬퍼 ──────────────────────────────────────────────────


def _load_prices(conn: psycopg.Connection, ticker: str, from_date: date) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT date, close FROM prices_daily WHERE ticker=%s AND date >= %s ORDER BY date",
            (ticker, from_date),
        )
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame({"close": []})
    df = pd.DataFrame([dict(r) for r in rows])
    df["close"] = df["close"].astype(float)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")


def _load_bench(conn: psycopg.Connection, bench_ticker: str, from_date: date) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(
            # index_daily 컬럼은 index_code/asof (prices_daily의 ticker/date와 다름).
            # asof AS date로 별칭해 아래 df 처리(df["date"])를 그대로 유지한다.
            "SELECT asof AS date, close FROM index_daily WHERE index_code=%s AND asof >= %s ORDER BY asof",
            (bench_ticker, from_date),
        )
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame({"close": []})
    df = pd.DataFrame([dict(r) for r in rows])
    df["close"] = df["close"].astype(float)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")


def _bench_prices_at(bench: pd.DataFrame, entry_date: Optional[date], exit_date: Optional[date]) -> tuple:
    """벤치마크 진입가·청산가를 ≥ 해당 날짜의 첫 거래일로 찾는다."""
    if bench.empty or entry_date is None:
        return None, None
    e_ts = pd.Timestamp(entry_date)
    entry_rows = bench[bench.index >= e_ts]
    bench_entry = float(entry_rows.iloc[0]["close"]) if not entry_rows.empty else None

    bench_exit = None
    if exit_date is not None and bench_entry is not None:
        x_ts = pd.Timestamp(exit_date)
        exit_rows = bench[bench.index >= x_ts]
        if not exit_rows.empty:
            bench_exit = float(exit_rows.iloc[0]["close"])
    return bench_entry, bench_exit


def _fetch_new_grades(conn: psycopg.Connection, signal_type: str, sentinel_n: int) -> list[dict]:
    """아직 signal_grade_track(sentinel_n)에 없는 (ticker, asof, grade) 조회."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT s.ticker, s.asof, s.grade, s.grade_confidence AS grade_conf, w.market
            FROM stock_action_advice s
            JOIN watchlist w ON w.ticker = s.ticker AND w.active = TRUE
            WHERE s.grade IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM signal_grade_track t
                  WHERE t.signal_type = %s
                    AND t.ticker      = s.ticker
                    AND t.asof        = s.asof
                    AND t.n_days      = %s
              )
            ORDER BY s.asof
        """, (signal_type, sentinel_n))
        return [dict(r) for r in cur.fetchall()]


def _build_row(
    signal_type: str, ticker: str, asof: date, grade: str,
    grade_conf: Optional[str], n: int,
    prices: pd.DataFrame, bench: pd.DataFrame,
) -> dict:
    p = resolve_entry_exit(prices, asof, n)
    bench_entry, bench_exit = _bench_prices_at(bench, p["entry_date"], p["exit_date"])

    rets: dict = {}
    if not p["pending"] and p["entry_price"] and p["exit_price"]:
        rets = compute_returns(p["entry_price"], p["exit_price"], bench_entry, bench_exit, grade)
    else:
        rets = {
            "raw_return": None, "bench_return": None,
            "excess_return": None, "hit_excess": None, "hit_raw": None,
        }

    return {
        "signal_type": signal_type,
        "ticker": ticker,
        "asof": asof,
        "grade": grade,
        "grade_conf": grade_conf,
        "n_days": n,
        "entry_date": p["entry_date"],
        "entry_price": p["entry_price"],
        "exit_date": p["exit_date"],
        "exit_price": p["exit_price"],
        "bench_entry": bench_entry,
        "bench_exit": bench_exit,
        **rets,
        "pending": p["pending"],
    }


# ── 메인 로직 ────────────────────────────────────────────────


def _insert_new(
    conn: psycopg.Connection,
    signal_type: str,
    n_days_list: tuple[int, ...],
    errors: list[dict],
) -> int:
    new_grades = _fetch_new_grades(conn, signal_type, sentinel_n=min(n_days_list))
    if not new_grades:
        return 0

    rows = []
    for g in new_grades:
        ticker, asof = g["ticker"], g["asof"]
        bench_t = benchmark_for(ticker, g["market"])
        try:
            prices = _load_prices(conn, ticker, asof)
            bench = _load_bench(conn, bench_t, asof)
            for n in n_days_list:
                rows.append(_build_row(
                    signal_type, ticker, asof, g["grade"], g["grade_conf"], n, prices, bench
                ))
        except Exception as exc:
            logger.warning("signal_track insert 실패 %s %s: %s", ticker, asof, exc)
            errors.append({"stage": f"signal_track:{ticker}:{asof}", "error": str(exc)})

    if rows:
        db.upsert_signal_grade_track(conn, rows)
        conn.commit()
    return len(rows)


def _resolve_pending(
    conn: psycopg.Connection,
    signal_type: str,
    errors: list[dict],
) -> int:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT t.id, t.ticker, t.asof, t.grade, t.grade_conf, t.n_days,
                   t.entry_date, t.entry_price, t.bench_entry, w.market
            FROM signal_grade_track t
            JOIN watchlist w ON w.ticker = t.ticker
            WHERE t.signal_type = %s AND t.pending = TRUE AND t.entry_date IS NOT NULL
        """, (signal_type,))
        pending = [dict(r) for r in cur.fetchall()]

    if not pending:
        return 0

    updated = 0
    for p in pending:
        try:
            entry_date = p["entry_date"]
            prices = _load_prices(conn, p["ticker"], entry_date)
            entry_ts = pd.Timestamp(entry_date)
            from_entry = prices[prices.index >= entry_ts]
            n = p["n_days"]
            if len(from_entry) <= n:
                continue  # N일 아직 미경과

            exit_price = float(from_entry.iloc[n]["close"])
            exit_date = from_entry.index[n].date()
            entry_price = float(p["entry_price"]) if p["entry_price"] else None
            if not entry_price:
                continue

            bench_t = benchmark_for(p["ticker"], p["market"])
            bench = _load_bench(conn, bench_t, entry_date)
            bench_entry = float(p["bench_entry"]) if p["bench_entry"] else None
            _, bench_exit = _bench_prices_at(bench, None, exit_date)
            # bench_entry는 이미 저장된 값 재사용

            rets = compute_returns(entry_price, exit_price, bench_entry, bench_exit, p["grade"])

            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE signal_grade_track SET
                        exit_date    = %s, exit_price    = %s,
                        bench_exit   = %s,
                        raw_return   = %s, bench_return  = %s,
                        excess_return= %s, hit_excess    = %s, hit_raw = %s,
                        pending      = FALSE, computed_at = NOW()
                    WHERE id = %s
                """, (
                    exit_date, exit_price, bench_exit,
                    rets["raw_return"], rets["bench_return"], rets["excess_return"],
                    rets["hit_excess"], rets["hit_raw"],
                    p["id"],
                ))
            conn.commit()
            updated += 1
        except Exception as exc:
            conn.rollback()
            logger.warning("signal_track pending 갱신 실패 id=%s: %s", p["id"], exc)
            errors.append({"stage": f"signal_track:pending:{p['id']}", "error": str(exc)})

    return updated


def compute_signal_track(
    conn: psycopg.Connection,
    signal_type: str = SIGNAL_TYPE_A2,
    n_days_list: tuple[int, ...] = N_DAYS_DEFAULT,
) -> dict:
    """
    신호 적중률 추적 메인 진입점.
    1) stock_action_advice의 신규 등급 삽입
    2) pending 행 갱신 (N일 경과 확인)
    반환: {inserted, updated, errors}.
    """
    errors: list[dict] = []
    n_inserted = _insert_new(conn, signal_type, n_days_list, errors)
    n_updated = _resolve_pending(conn, signal_type, errors)
    logger.info(
        "signal_track(%s): 신규=%d, 갱신=%d, 오류=%d",
        signal_type, n_inserted, n_updated, len(errors),
    )
    return {"inserted": n_inserted, "updated": n_updated, "errors": errors}


# ── 요약 (export용) ───────────────────────────────────────────


def compute_accuracy_summary(
    conn: psycopg.Connection,
    signal_type: str = SIGNAL_TYPE_A2,
) -> dict | None:
    """
    등급별 × n_days 적중률 요약. export_dashboard_data가 n_total>=30 가드 후 노출.
    n_total < 2이면 None 반환.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT grade, n_days,
                   COUNT(*)              FILTER (WHERE NOT pending)           AS n,
                   COUNT(*)              FILTER (WHERE pending)               AS n_pending,
                   AVG(excess_return)    FILTER (WHERE NOT pending)           AS mean_excess,
                   AVG(raw_return)       FILTER (WHERE NOT pending)           AS mean_raw,
                   STDDEV(excess_return) FILTER (WHERE NOT pending)           AS std_excess,
                   SUM(CASE WHEN hit_excess THEN 1 ELSE 0 END) FILTER (WHERE NOT pending) AS hits_excess,
                   SUM(CASE WHEN hit_raw    THEN 1 ELSE 0 END) FILTER (WHERE NOT pending) AS hits_raw
            FROM signal_grade_track
            WHERE signal_type = %s
            GROUP BY grade, n_days
            ORDER BY grade, n_days
        """, (signal_type,))
        agg_rows = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT grade, excess_return
            FROM signal_grade_track
            WHERE signal_type = %s AND NOT pending AND excess_return IS NOT NULL
        """, (signal_type,))
        ic_rows = [dict(r) for r in cur.fetchall()]

    if not ic_rows:
        return None

    ic_result = spearman_ic(
        [r["grade"] for r in ic_rows],
        [float(r["excess_return"]) for r in ic_rows],
    )
    n_total = ic_result["n"]

    by_grade_n: dict[str, dict[int, dict]] = {}
    for r in agg_rows:
        g, nd = r["grade"], int(r["n_days"])
        n_settled = int(r["n"] or 0)
        hits = int(r["hits_excess"] or 0)
        by_grade_n.setdefault(g, {})[nd] = {
            "n": n_settled,
            "nPending": int(r["n_pending"] or 0),
            "hitRate": round(hits / n_settled, 3) if n_settled > 0 else None,
            "meanExcess": round(float(r["mean_excess"]), 4) if r["mean_excess"] is not None else None,
            "meanRaw": round(float(r["mean_raw"]), 4) if r["mean_raw"] is not None else None,
            "stdExcess": round(float(r["std_excess"]), 4) if r["std_excess"] is not None else None,
        }

    return {
        "signalType": signal_type,
        "n": n_total,
        "nWarning": n_warning(n_total),
        "ic": ic_result["ic"],
        "pValue": ic_result["p_value"],
        "byGradeN": by_grade_n,
        "disclaimer": (
            "신호 성과는 전향검증 결과이며 실제 매매 수익률이 아닙니다. "
            "슬리피지·수수료·세금 미반영. 투자 자문 아님 / 원금 손실 가능."
        ),
    }


# ── CLI ──────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="신호 적중률 추적 (신규-F)")
    parser.add_argument("--signal", default=SIGNAL_TYPE_A2, help="신호 유형")
    parser.add_argument("--backfill", action="store_true", help="과거 전체 일괄 처리(초기 1회)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    with db.get_conn() as conn:
        result = compute_signal_track(conn, signal_type=args.signal)

    print(f"signal_track: 신규={result['inserted']}, 갱신={result['updated']}, 오류={len(result['errors'])}")
    if result["errors"]:
        for e in result["errors"]:
            print(f"  오류: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
