"""
ingest_investor_flow.py — KR 투자자별 수급 수집 (E-2)

수집 대상: KR 종목만 (US는 구조적 부재 → None 처리).
API: pykrx.stock.get_market_trading_value_by_date (일별 순매수)
신호: 외국인/기관 최근 3거래일 순매수 합계 기준 결정론 라벨 → DB asof별 저장(신규-F 추적).

절대 규칙:
  - KRX_ID/KRX_PW 환경변수로만(코드·로그·DB 평문 금지)
  - 결정론 신호는 LLM 없이 Python으로
  - 종목 단위 격리 (실패 시 해당 종목 skip, 전체 중단 금지)
  - pykrx 호출은 _bounded 타임아웃 래퍼 통과
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from typing import Optional

from src.ingest_kr import KRX_HTTP_TIMEOUT_S, _bounded, _clean_ticker
from src.schemas import InvestorFlowRow
from src.freshness import today_kst

logger = logging.getLogger(__name__)

# ── 상수 (코드 상단 추출, 하드코딩 금지) ─────────────────────────
# 순매수 0원 기준: 양수=매수우호, 음수=매도우세, 0=중립
# 절댓값이 작은 미미한 신호를 걸러내려면 양수값으로 조정 가능
INVESTOR_SIGNAL_THRESHOLD: float = float(os.getenv("INVESTOR_SIGNAL_THRESHOLD", "0"))
INVESTOR_LOOKBACK_DAYS: int = int(os.getenv("INVESTOR_LOOKBACK_DAYS", "10"))  # 캘린더 기준


# ── 신호 계산 (결정론, LLM 없음) ─────────────────────────────────

def _derive_investor_signal(net_3d: float | None) -> str:
    """3거래일 합계 순매수 → 라벨 (매수우호/중립/매도우세)."""
    if net_3d is None:
        return "중립"
    if net_3d > INVESTOR_SIGNAL_THRESHOLD:
        return "매수우호"
    if net_3d < -INVESTOR_SIGNAL_THRESHOLD:
        return "매도우세"
    return "중립"


def _derive_combined_signal(foreign_signal: str, institution_signal: str) -> str:
    """외국인+기관 방향 조합 → 복합 수급 라벨."""
    f_buy = foreign_signal == "매수우호"
    i_buy = institution_signal == "매수우호"
    f_sell = foreign_signal == "매도우세"
    i_sell = institution_signal == "매도우세"
    if f_buy and i_buy:
        return "수급_강세"
    if f_sell and i_sell:
        return "수급_약세"
    if (f_buy and i_sell) or (f_sell and i_buy):
        return "수급_혼조"
    return "중립"


# ── KRX 세션 관리 ─────────────────────────────────────────────────

def _ensure_krx_session() -> bool:
    """KRX 세션 초기화(KRX_ID/KRX_PW 환경변수 우선). 반환: 로그인 성공 여부."""
    try:
        from pykrx.website.comm.auth import (
            build_krx_session,
            get_auth_session,
            set_auth_session,
        )
    except ImportError:
        logger.warning("pykrx.website.comm.auth 임포트 실패 — 익명 조회 시도")
        return False

    existing = get_auth_session()
    if existing and existing.is_valid():
        logger.debug("KRX 세션 유효 (재사용)")
        return True

    login_id = os.getenv("KRX_ID")
    login_pw = os.getenv("KRX_PW")
    if not (login_id and login_pw):
        logger.warning("KRX_ID/KRX_PW 미설정 — 익명 조회 시도 (일부 데이터 제한 가능)")
        return False

    # 시크릿 비노출: ID는 로그에 남기지 않음
    session = build_krx_session(login_id, login_pw)
    if session and session.is_authenticated:
        set_auth_session(session)
        logger.info("KRX 세션 로그인 성공 (1시간 유효)")
        return True
    else:
        logger.warning("KRX 세션 로그인 실패 — 익명 조회 시도")
        return False


# ── 수집 ──────────────────────────────────────────────────────────

def fetch_investor_flow(
    ticker: str,
    lookback_days: int = INVESTOR_LOOKBACK_DAYS,
) -> list[InvestorFlowRow]:
    """KR 종목 일별 투자자 순매수 수집 → InvestorFlowRow 리스트.

    - pykrx.get_market_trading_value_by_date(on='순매수') 사용
    - 각 날짜 행에 3거래일 합계 기반 신호를 계산해서 함께 저장
    - 빈 DF나 타임아웃 시 빈 리스트 반환 (호출부 격리)
    """
    from pykrx import stock as pykrx_stock

    code = _clean_ticker(ticker)
    today = today_kst()
    fromdate = (today - timedelta(days=lookback_days)).strftime("%Y%m%d")
    todate = today.strftime("%Y%m%d")

    df = _bounded(
        f"pykrx.investor_flow:{code}",
        lambda: pykrx_stock.get_market_trading_value_by_date(
            fromdate, todate, code, on="순매수"
        ),
        KRX_HTTP_TIMEOUT_S,
    )

    if df is None or df.empty:
        logger.warning("%s: investor_flow 빈 응답", ticker)
        return []

    dates_sorted = sorted(df.index)
    rows: list[InvestorFlowRow] = []

    for i, dt in enumerate(dates_sorted):
        row_data = df.loc[dt]

        def _col(name: str) -> float:
            try:
                v = row_data.get(name, 0)
                return float(v) if v is not None else 0.0
            except (TypeError, ValueError):
                return 0.0

        f_net = _col("외국인합계")
        ins_net = _col("기관합계")
        ind_net = _col("개인")

        # 3거래일 합계 (이 날 포함 최근 3일)
        window = dates_sorted[max(0, i - 2): i + 1]

        def _window_sum(col: str) -> float:
            total = 0.0
            for d in window:
                try:
                    v = df.loc[d].get(col, 0)
                    total += float(v) if v is not None else 0.0
                except (TypeError, ValueError):
                    pass
            return total

        f_3d = _window_sum("외국인합계")
        ins_3d = _window_sum("기관합계")

        foreign_sig = _derive_investor_signal(f_3d)
        institution_sig = _derive_investor_signal(ins_3d)
        combined_sig = _derive_combined_signal(foreign_sig, institution_sig)

        rows.append(InvestorFlowRow(
            ticker=ticker,
            date=dt.date(),
            foreign_net=f_net or None,
            institution_net=ins_net or None,
            individual_net=ind_net or None,
            foreign_3d_sum=f_3d,
            institution_3d_sum=ins_3d,
            foreign_signal=foreign_sig,
            institution_signal=institution_sig,
            combined_signal=combined_sig,
        ))

    logger.info("%s: investor_flow %d rows", ticker, len(rows))
    return rows


# ── 파이프라인 진입점 ─────────────────────────────────────────────

def run_investor_flow_ingest(
    conn,
    tickers_kr: list[str],
) -> dict:
    """KR 종목 수급 수집 실행기 — pipeline_ingest에서 호출.

    - KRX 세션 초기화(재로그인 포함)
    - 종목별 격리: 실패 시 skip + errors 기록, 전체 중단 금지
    - 단계별 commit (Supabase pooler 연결 끊김 방지)
    """
    from src.db import upsert_investor_flow

    _ensure_krx_session()

    counts = {"rows": 0, "tickers": 0}
    errors: list[dict] = []

    for ticker in tickers_kr:
        try:
            rows = fetch_investor_flow(ticker)
            if rows:
                upsert_investor_flow(conn, rows)
                conn.commit()
                counts["rows"] += len(rows)
                counts["tickers"] += 1
                logger.info("%s: investor_flow %d rows 저장", ticker, len(rows))
        except Exception as exc:
            conn.rollback()
            logger.error("%s: investor_flow 수집/저장 실패 — %s", ticker, exc, exc_info=True)
            errors.append({"ticker": ticker, "error": str(exc)})

    logger.info(
        "investor_flow 완료: %d종목 %d행, 실패 %d건",
        counts["tickers"], counts["rows"], len(errors),
    )
    return {"counts": counts, "errors": errors}
