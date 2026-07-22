"""
compute_portfolio.py — portfolio_holdings × prices_daily → portfolio / portfolio_snapshot

PR-2 (F1): 수동 입력된 portfolio_holdings와 prices_daily 최신가를 결합해
종목별 평가금액·손익을 계산하고 DB에 upsert한다.

- portfolio(ticker, asof) upsert: 종목별 당일 평가
- portfolio_snapshot(asof) upsert: 전체 합산 스냅샷

자동 주문 없음.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Optional

import psycopg

from src.db import get_conn
from src.freshness import today_kst

logger = logging.getLogger(__name__)


def _get_latest_price(ticker: str, conn: psycopg.Connection) -> Optional[float]:
    """prices_daily에서 가장 최근 종가를 반환 (최대 7일 이내)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT close FROM prices_daily
            WHERE ticker = %s AND close IS NOT NULL
            ORDER BY date DESC LIMIT 1
            """,
            (ticker,),
        )
        row = cur.fetchone()
    return float(row["close"]) if row else None


def _load_holdings(conn: psycopg.Connection) -> list[dict]:
    """portfolio_holdings 전체 반환 (qty > 0 인 활성 포지션)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ticker, qty, avg_price, currency FROM portfolio_holdings WHERE qty > 0 ORDER BY ticker"
        )
        return [dict(r) for r in cur.fetchall()]


def _get_usdkrw(conn: psycopg.Connection) -> Optional[float]:
    """market_daily 최신 USD/KRW 환율. 없으면 None."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT usdkrw FROM market_daily WHERE usdkrw IS NOT NULL ORDER BY asof DESC LIMIT 1"
        )
        row = cur.fetchone()
    return float(row["usdkrw"]) if row else None


def _load_cash(conn: psycopg.Connection) -> dict[str, float]:
    """PR-2: 통화별 현금 {currency: amount}. 0 초과만."""
    with conn.cursor() as cur:
        cur.execute("SELECT currency, amount FROM portfolio_cash WHERE amount > 0")
        return {r["currency"]: float(r["amount"]) for r in cur.fetchall()}


def compute_portfolio(conn: psycopg.Connection, asof: Optional[date] = None) -> dict:
    """
    portfolio_holdings × prices_daily 최신가 → portfolio + portfolio_snapshot upsert.

    PR-3: USD 보유종목은 평가/손익을 KRW로 환산해 합계(total_value/total_pnl, KRW 기준)를
    계산한다. 환율은 market_daily 최신 USD/KRW. 환율 없으면 USD 포지션은 KRW 합계에서
    제외하고 runs.errors 기록 대신 payload.fx_missing=true로 표시(호출부에서 격리).
    payload에 fx_rate와 통화별 분해(by_currency)를 저장.

    portfolio(종목별 행)는 원통화(qty×price) 그대로 저장 — 통화 정보는 holdings에 있음.

    Returns summary dict for logging.
    자동 주문 없음.
    """
    asof = asof or today_kst()
    asof_ts = datetime.combine(asof, datetime.min.time()).replace(tzinfo=timezone.utc)

    holdings = _load_holdings(conn)
    cash_map = _load_cash(conn)  # PR-2: 통화별 현금
    if not holdings and not cash_map:
        logger.info("compute_portfolio: 보유종목·현금 모두 없음 — 스킵")
        return {"n": 0, "total_eval_krw": 0.0, "total_pnl_krw": 0.0}

    fx = _get_usdkrw(conn)  # USD→KRW 환율 (없으면 None)

    # 통화별 합계(원통화 기준) + KRW 환산 총계
    by_ccy: dict[str, dict] = {}      # {"KRW": {"eval","cost"}, "USD": {...}}
    total_eval_krw = 0.0
    total_cost_krw = 0.0
    n_ok = 0
    fx_missing_usd = False

    def to_krw(amount: float, ccy: str) -> Optional[float]:
        if ccy == "KRW":
            return amount
        if ccy == "USD":
            return amount * fx if fx else None
        return amount  # 기타 통화는 환산 없이 그대로(보수적)

    with conn.cursor() as cur:
        for h in holdings:
            ticker = h["ticker"]
            qty = float(h["qty"])
            avg_price = float(h["avg_price"])
            ccy = (h.get("currency") or "KRW").upper()
            cur_price = _get_latest_price(ticker, conn)

            if cur_price is None:
                logger.warning("%s: 최신 가격 없음 — portfolio 행 스킵", ticker)
                continue

            eval_amount = qty * cur_price       # 원통화
            cost = qty * avg_price              # 원통화
            pnl = eval_amount - cost
            pnl_pct = (pnl / cost * 100) if cost > 0 else 0.0

            cur.execute(
                """
                INSERT INTO portfolio (ticker, qty, avg_price, cur_price, eval_amount, pnl, pnl_pct, asof)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker, asof) DO UPDATE SET
                    qty         = EXCLUDED.qty,
                    avg_price   = EXCLUDED.avg_price,
                    cur_price   = EXCLUDED.cur_price,
                    eval_amount = EXCLUDED.eval_amount,
                    pnl         = EXCLUDED.pnl,
                    pnl_pct     = EXCLUDED.pnl_pct
                """,
                (ticker, qty, avg_price, cur_price, eval_amount, pnl, pnl_pct, asof_ts),
            )

            # 통화별 분해 (원통화)
            c = by_ccy.setdefault(ccy, {"eval": 0.0, "cost": 0.0, "n": 0})
            c["eval"] += eval_amount
            c["cost"] += cost
            c["n"] += 1

            # KRW 환산 누적
            eval_krw = to_krw(eval_amount, ccy)
            cost_krw = to_krw(cost, ccy)
            if eval_krw is None or cost_krw is None:
                fx_missing_usd = True  # USD인데 환율 없음 → KRW 합계 제외
            else:
                total_eval_krw += eval_krw
                total_cost_krw += cost_krw
            n_ok += 1

        total_pnl_krw = total_eval_krw - total_cost_krw
        total_pnl_pct = (total_pnl_krw / total_cost_krw * 100) if total_cost_krw > 0 else 0.0

        # PR-2: 현금 KRW 환산 합계 + 총자산(주식 평가액 + 현금)
        cash_total_krw = 0.0
        for ccy, amt in cash_map.items():
            kc = to_krw(amt, ccy)
            if kc is None:
                fx_missing_usd = True
            else:
                cash_total_krw += kc
        asset_total_krw = total_eval_krw + cash_total_krw

        payload = {
            "pnl_pct": round(total_pnl_pct, 2),
            "n_holdings": n_ok,
            "fx_rate": fx,
            "fx_missing": fx_missing_usd,
            "currency": "KRW",
            "cash_total": round(cash_total_krw, 2),       # PR-2: 현금(KRW 환산)
            "asset_total": round(asset_total_krw, 2),     # PR-2: 총자산(주식+현금)
            "cash_by_currency": {c: round(a, 2) for c, a in cash_map.items()},
            "by_currency": {
                ccy: {
                    "eval": round(v["eval"], 2),
                    "cost": round(v["cost"], 2),
                    "pnl": round(v["eval"] - v["cost"], 2),
                    "n": v["n"],
                }
                for ccy, v in by_ccy.items()
            },
        }

        cur.execute(
            """
            INSERT INTO portfolio_snapshot (asof, total_value, total_cost, total_pnl, cash, payload)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (asof) DO UPDATE SET
                total_value = EXCLUDED.total_value,
                total_cost  = EXCLUDED.total_cost,
                total_pnl   = EXCLUDED.total_pnl,
                cash        = EXCLUDED.cash,
                payload     = EXCLUDED.payload
            """,
            (asof_ts, total_eval_krw, total_cost_krw, total_pnl_krw, round(cash_total_krw, 2),
             json.dumps(payload, ensure_ascii=False)),
        )

    conn.commit()
    logger.info(
        "compute_portfolio 완료: %d종목 KRW환산 평가=%.0f 손익=%.0f(%.2f%%) fx=%s (commit)",
        n_ok, total_eval_krw, total_pnl_krw, total_pnl_pct, fx,
    )
    if fx_missing_usd:
        logger.warning("USD/KRW 환율 없음 — USD 포지션이 KRW 총계에서 제외됨")
    return {
        "n": n_ok,
        "total_eval_krw": total_eval_krw,
        "cash_total_krw": cash_total_krw,
        "asset_total_krw": asset_total_krw,
        "total_pnl_krw": total_pnl_krw,
        "total_pnl_pct": total_pnl_pct,
        "fx_rate": fx,
        "fx_missing": fx_missing_usd,
    }
