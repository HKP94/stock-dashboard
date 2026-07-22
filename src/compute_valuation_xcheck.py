"""밸류에이션 교차검증 게이트 (Part 3).

KR 종목의 저장 PBR/PER(네이버 원천, valuation 테이블)를 **KRX 공식 펀더멘털**(pykrx)과
대조해 편차가 임계를 넘으면 flag한다. 목적은 틀린 밸류가 판단·2렌즈·컨센 괴리로 조용히
전파되는 것을 차단하는 것.

왜 KRX인가: 진단 결과 FnGuide 스크래이프가 완전히 깨져(항상 삼성전자 기본 페이지 반환)
2출처가 될 수 없다. KRX는 거래소 권위 원천이고 이미 의존성(pykrx)이며 로컬(한국 IP)에서
동작한다. **KRX 로그인은 CI에서 차단**되므로 이 게이트는 로컬 실행 전용이다(investor_flow와 동일).
CI에서 돌면 KRX 조회가 비어 no-op(0건 검사)으로 graceful 스킵된다.

§F7: 오늘 스냅샷만 저장(과거 소급 생성 금지). 결정론(LLM 없음).
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from typing import Optional

from src.db import get_conn, upsert_valuation_xcheck
from src.freshness import today_kst

logger = logging.getLogger(__name__)

# 편차 임계. src·ref 둘 다 있고 ref>0일 때만 비교.
# 실측(2026-07-03, KR 21종목): 네이버 #_pbr/#_per와 KRX 공식은 같은 날에도 EPS/BPS 산출
# 관례차로 PBR 5~12%·PER 한 자릿수~10%대 편차가 흔한 정상 노이즈다. 임계를 낮게 잡으면
# 절반이 flag돼 신호가 죽는다. 실제 스크랩 오류(스테일 가격·잘못된 주식수)는 수십~수백%
# 이탈이므로, 노이즈 밴드 위(PBR 15%·PER 35%)만 flag해 "진짜 괴리"만 남긴다. env로 조정 가능.
XCHECK_PBR_THRESHOLD: float = float(os.getenv("VAL_XCHECK_PBR_THRESHOLD", "0.15"))
XCHECK_PER_THRESHOLD: float = float(os.getenv("VAL_XCHECK_PER_THRESHOLD", "0.35"))


def _fnum(x) -> Optional[float]:
    """None/0/음수/NaN 방어. 유효 양수만 float로."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v or v <= 0:  # NaN 또는 비양수
        return None
    return v


def crosscheck(
    src_pbr, src_per, ref_pbr, ref_per,
    pbr_threshold: float = XCHECK_PBR_THRESHOLD,
    per_threshold: float = XCHECK_PER_THRESHOLD,
) -> dict:
    """저장값 vs 대조값 편차 계산 + flag 판정(순수 함수).

    편차 = |src-ref|/ref. pbr·per 독립 판정, 어느 하나라도 임계 초과면 flagged.
    비교 불가(둘 중 하나 결측/비양수)면 해당 지표 dev=None(사유에 미포함).
    """
    sp, spx, rp, rpx = _fnum(src_pbr), _fnum(src_per), _fnum(ref_pbr), _fnum(ref_per)

    def _dev(s, r):
        return abs(s - r) / r if (s is not None and r is not None) else None

    pbr_dev = _dev(sp, rp)
    per_dev = _dev(spx, rpx)

    reasons: list[str] = []
    if pbr_dev is not None and pbr_dev > pbr_threshold:
        reasons.append(f"PBR 저장 {sp:.2f} vs KRX {rp:.2f} (편차 {pbr_dev * 100:.0f}%)")
    if per_dev is not None and per_dev > per_threshold:
        reasons.append(f"PER 저장 {spx:.2f} vs KRX {rpx:.2f} (편차 {per_dev * 100:.0f}%)")

    flagged = bool(reasons)
    if flagged:
        reason = "밸류 의심 — " + " · ".join(reasons)
    elif pbr_dev is None and per_dev is None:
        reason = "KRX 대조값 없음(검증 불가)"
    else:
        reason = None

    return {
        "src_pbr": sp, "src_per": spx, "ref_pbr": rp, "ref_per": rpx,
        "pbr_dev": pbr_dev, "per_dev": per_dev,
        "flagged": flagged, "reason": reason,
    }


def _krx_code(ticker: str) -> str:
    """'010120.KS' -> '010120'."""
    return ticker.split(".")[0]


def fetch_krx_fundamentals(
    kr_tickers: list[str], max_lookback: int = 7
) -> tuple[Optional[date], dict[str, dict]]:
    """KRX 공식 PBR/PER를 최근 거래일 기준으로 조회.

    주말/휴장이면 0을 반환하므로, 대상 종목이 유효 양수 PBR를 가진 최근일까지 최대
    max_lookback일 되돌아간다. 반환: (기준일, {code: {'pbr','per'}}). 실패 시 (None, {}).
    """
    from pykrx import stock  # 지연 임포트(pykrx 미설치·CI 스킵 대비)

    codes = {_krx_code(t) for t in kr_tickers}
    d = today_kst()
    for _ in range(max_lookback):
        ds = d.strftime("%Y%m%d")
        try:
            df = stock.get_market_fundamental(ds, market="ALL")
        except Exception as exc:  # noqa: BLE001 — KRX 로그인 실패(CI) 등은 graceful 스킵
            logger.warning("KRX 펀더멘털 조회 실패(%s): %s", ds, exc)
            return None, {}
        if df is not None and len(df):
            hit = {c: {"pbr": _fnum(df.loc[c].PBR), "per": _fnum(df.loc[c].PER)}
                   for c in codes if c in df.index}
            if any(v["pbr"] is not None for v in hit.values()):
                return d, hit
        d -= timedelta(days=1)
    logger.warning("KRX 펀더멘털: 최근 %d일 내 유효 데이터 없음", max_lookback)
    return None, {}


def run_valuation_xcheck(conn, kr_tickers: list[str]) -> dict:
    """KR 종목 저장 밸류 vs KRX 대조 → valuation_xcheck upsert. 요약 dict 반환."""
    if not kr_tickers:
        return {"n_checked": 0, "n_flagged": 0, "asof": None}

    ref_date, krx = fetch_krx_fundamentals(kr_tickers)
    if ref_date is None:
        logger.info("valuation_xcheck: KRX 대조값 없음 — 스킵(CI 등)")
        return {"n_checked": 0, "n_flagged": 0, "asof": None}

    # 저장(네이버) 밸류: 종목별 최신
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT ON (ticker) ticker, per_t, pbr FROM valuation "
            "WHERE ticker = ANY(%s) ORDER BY ticker, asof DESC",
            (list(kr_tickers),),
        )
        stored = {r["ticker"]: r for r in cur.fetchall()}

    rows: list[dict] = []
    for tk in kr_tickers:
        s = stored.get(tk)
        if s is None:
            continue  # 저장값 없으면 검증 대상 아님
        ref = krx.get(_krx_code(tk), {})
        res = crosscheck(s["pbr"], s["per_t"], ref.get("pbr"), ref.get("per"))
        # 검증할 게 아무것도 없으면(저장·대조 모두 결측) 스냅샷 남기지 않음
        if res["pbr_dev"] is None and res["per_dev"] is None and not res["flagged"]:
            continue
        rows.append({"ticker": tk, "asof": ref_date, "ref_source": "krx", **res})

    if rows:
        upsert_valuation_xcheck(conn, rows)
        conn.commit()

    n_flagged = sum(1 for r in rows if r["flagged"])
    for r in rows:
        if r["flagged"]:
            logger.warning("%s %s", r["ticker"], r["reason"])
    logger.info("valuation_xcheck: %d 검사 / %d flag (기준일 %s)", len(rows), n_flagged, ref_date)
    return {"n_checked": len(rows), "n_flagged": n_flagged, "asof": ref_date.isoformat()}


def main() -> int:
    """로컬 실행 진입점: 활성 KR 유니버스 교차검증. `python -m src.compute_valuation_xcheck`."""
    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    from src.pipeline_common import active_universe, split_kr_us

    with get_conn() as conn:
        kr, _us, _all = split_kr_us(active_universe(conn))
        res = run_valuation_xcheck(conn, kr)
    logger.info("완료: %s", res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
