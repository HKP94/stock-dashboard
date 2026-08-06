"""
collect_kb_portfolio.py — KB증권 OpenAPI 잔고 → portfolio_holdings / portfolio_cash

수동 입력을 대체한다. **KB 응답이 진실원본**이므로 upsert만이 아니라 "KB에 없는 보유행 제거"
까지 한다(매도 반영). 실행당 조회 3콜 안팎(rate limit 미공개라 최소 호출):
  1) SSQM2952 잔고현황(체결기준) — 국내 보유 전종목(Record1)
  2) SPQM2226 해외주식계좌잔고평가 — 해외 보유(Record2) + 통화별 예수금(Record1)
  3) SSQM0004 예수금내역        — KRW 예수금

안전장치(불변):
  - 조회 전용. 주문·정정·취소 API는 kb_client 화이트리스트가 물리 차단한다.
  - **보유 0건이면 삭제 스킵 + WARNING** — API 오류/장애로 빈 응답이 와도 DB가 전멸하지 않는다.
  - 티커 매핑 실패(미해결)가 있으면 삭제를 건너뛴다 — 못 읽은 종목을 '매도'로 오인하지 않게.
  - --dry-run: DB 무변경, KB응답 vs 현행 portfolio_holdings diff만 출력.

실행:  python -m src.collect_kb_portfolio --dry-run
"""

from __future__ import annotations

import argparse
import logging
from typing import Optional

import psycopg

from src import kb_client

logger = logging.getLogger(__name__)

DOMESTIC_API = "ssqm2952"
OVERSEAS_API = "spqm2226"
CASH_API = "ssqm0004"

# SIQM4900/SSQM2952의 종목세부유형코드 → ATLAS 티커 접미사.
# 실측(2026-08-06): 11=상장주식(코스피) 12=코스닥주식 10=코넥스시장.
# 이 코드가 SSQM2952 Record1에 이미 들어 있어 KOSPI/KOSDAQ 판별에 추가 호출이 필요 없다.
_SUFFIX_BY_DTL_TYPE: dict[str, str] = {"11": ".KS", "12": ".KQ"}

# 해외는 심볼 그대로 쓰므로 ATLAS 포맷(접미사 없음)과 맞는 통화만 수용한다.
_USD_MARKERS: tuple[str, ...] = ("USD", "달러")


# ── 파싱 헬퍼 ────────────────────────────────────────────────────────────────
def _num(value: object) -> float:
    """KB의 zero-padded 고정길이 문자열 → float. 공백/비수치는 0.0."""
    try:
        return float(str(value).strip() or 0)
    except (TypeError, ValueError):
        return 0.0


def _domestic_code(is_cd: object) -> str:
    """국내 종목코드 정규화 → 6자리. 'A005930'·'KR7005930003'·'005930' 모두 수용."""
    raw = str(is_cd or "").strip().upper()
    if raw.startswith("KR") and len(raw) >= 9:
        return raw[3:9]
    digits = "".join(ch for ch in raw if ch.isdigit())
    return digits[:6] if len(digits) >= 6 else digits


def _qty(whole: float, frac: float, val_amt: float, price: float) -> float:
    """
    보유수량 = 정수분(hld_q) + 소수점분(hld_q_p6).

    ponytail: KB가 계좌/상품에 따라 p6에 '소수점분'이 아닌 '전체수량'을 담는 경우가 있어,
    같은 응답의 평가금액÷현재가로 교차검증해 합산/대체 중 맞는 쪽을 고른다(이중계상 방지).
    가격·평가금액이 0이면 합산으로 폴백.
    """
    candidates = [whole + frac, frac, whole]
    if price > 0 and val_amt > 0:
        ref = val_amt / price
        return min(candidates, key=lambda q: abs(q - ref))
    return whole + frac


# ── 수집 ────────────────────────────────────────────────────────────────────
def fetch_raw() -> dict:
    """KB 조회 3콜. 반환은 각 API의 dataBody 그대로(파싱은 build_rows가 담당)."""
    domestic = kb_client.call(DOMESTIC_API, {"excg_mktpr_ccd": "A"})
    # std_crncy_f=1(외화기준) → 단가·현재가가 원통화(USD) 그대로 온다(ATLAS holdings 규약과 동일).
    overseas = kb_client.call(
        OVERSEAS_API, {"std_crncy_f": "1", "exch_r_aplc_f": "2", "fee_clsf": "0"}
    )
    cash = kb_client.call(CASH_API, {})
    return {"domestic": domestic, "overseas": overseas, "cash": cash}


def build_rows(raw: dict, known: dict[str, str]) -> tuple[list[dict], dict[str, float], list[str]]:
    """
    KB 원응답 → (holdings rows, {currency: cash}, unresolved 메모).

    known = {6자리코드: ATLAS 티커} (watchlist + 기존 보유). 매핑은 known 우선,
    없으면 종목세부유형코드로 .KS/.KQ 판정, 그래도 모르면 unresolved로 남긴다.
    """
    holdings: list[dict] = []
    unresolved: list[str] = []

    # 국내
    for rec in raw["domestic"].get("Record1") or []:
        code = _domestic_code(rec.get("is_cd"))
        name = str(rec.get("is_nm") or "").strip()
        qty = _qty(
            _num(rec.get("hld_q")),
            _num(rec.get("hld_q_p6")),
            _num(rec.get("val_amt")),
            _num(rec.get("now_prc")),
        )
        if qty <= 0:
            continue
        ticker = known.get(code) or _resolve_domestic(code, rec)
        if not ticker:
            unresolved.append(f"국내 {code} {name}: 시장(KOSPI/KOSDAQ) 판별 불가")
            continue
        holdings.append(
            {
                "ticker": ticker,
                "qty": qty,
                "avg_price": _num(rec.get("byng_avr_prc")),
                "currency": "KRW",
                "name": name,
            }
        )

    # 해외
    for rec in raw["overseas"].get("Record2") or []:
        symbol = str(rec.get("is_cd") or "").strip().upper()
        name = str(rec.get("is_nm") or "").strip()
        ccy = str(rec.get("crncy_clsf_nm") or "").strip().upper()
        qty = _num(rec.get("frgn_hld_q_p6"))
        if qty <= 0:
            continue
        if not any(m in ccy for m in _USD_MARKERS):
            # ponytail: ATLAS 티커 포맷은 US 무접미사만 지원 — USD 외 시장은 수동 처리로 남긴다.
            unresolved.append(f"해외 {symbol} {name}: 미지원 통화({ccy or '미상'})")
            continue
        holdings.append(
            {
                "ticker": symbol,
                "qty": qty,
                "avg_price": _num(rec.get("byng_avr_prc_p4")),
                "currency": "USD",
                "name": name,
            }
        )

    # 현금 — KRW=예수금내역 D+2(실제 인출 가능 시점 기준), USD=해외 통화별 예수금
    cash_body = raw["cash"]
    krw = _num(cash_body.get("nxt2_dy_tfnd")) or _num(cash_body.get("tdy_tfnd_amt"))
    usd = 0.0
    for rec in raw["overseas"].get("Record1") or []:
        ccy = str(rec.get("crncy_clsf_nm") or "").strip().upper()
        if any(m in ccy for m in _USD_MARKERS):
            usd += _num(rec.get("tfnd"))
    return holdings, {"KRW": krw, "USD": usd}, unresolved


def _resolve_domestic(code: str, rec: dict) -> Optional[str]:
    """watchlist 미등록 국내 종목의 시장 판별. Record1의 종목세부유형코드로 해결(추가 호출 없음)."""
    suffix = _SUFFIX_BY_DTL_TYPE.get(str(rec.get("is_dtl_typ_cd") or "").strip())
    if suffix:
        return f"{code}{suffix}"
    # 잔고 응답에 세부유형이 없으면 종목기본정보 1콜로 확인(조회 전용).
    try:
        info = kb_client.call("siqm4900", {"stnd_is_cd": code})
    except kb_client.KBApiError as exc:
        logger.warning("SIQM4900 조회 실패 %s: %s", code, exc)
        return None
    suffix = _SUFFIX_BY_DTL_TYPE.get(str(info.get("is_dtl_typ_cd") or "").strip())
    return f"{code}{suffix}" if suffix else None


# ── DB ──────────────────────────────────────────────────────────────────────
def _known_tickers(conn: psycopg.Connection) -> dict[str, str]:
    """{6자리코드: ATLAS 티커} — watchlist + 현재 보유(이미 확정된 포맷을 우선 재사용)."""
    out: dict[str, str] = {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ticker FROM watchlist WHERE ticker LIKE '%.KS' OR ticker LIKE '%.KQ' "
            "UNION SELECT ticker FROM portfolio_holdings WHERE ticker LIKE '%.K%'"
        )
        for row in cur.fetchall():
            code = row["ticker"].split(".")[0]
            if len(code) == 6:
                out[code] = row["ticker"]
    return out


def _current_holdings(conn: psycopg.Connection) -> dict[str, dict]:
    with conn.cursor() as cur:
        cur.execute("SELECT ticker, qty, avg_price, currency FROM portfolio_holdings")
        return {r["ticker"]: {k: float(v) if k in ("qty", "avg_price") else v
                              for k, v in dict(r).items()} for r in cur.fetchall()}


def _current_cash(conn: psycopg.Connection) -> dict[str, float]:
    with conn.cursor() as cur:
        cur.execute("SELECT currency, amount FROM portfolio_cash")
        return {r["currency"]: float(r["amount"]) for r in cur.fetchall()}


def _diff(current: dict[str, dict], incoming: list[dict]) -> dict[str, list]:
    """현행 DB vs KB 응답 → {added, changed, removed}."""
    by_ticker = {h["ticker"]: h for h in incoming}
    added, changed = [], []
    for tk, new in by_ticker.items():
        old = current.get(tk)
        if old is None:
            added.append(new)
        elif abs(old["qty"] - new["qty"]) > 1e-6 or abs(old["avg_price"] - new["avg_price"]) > 0.5:
            changed.append({"ticker": tk, "old": old, "new": new})
    removed = [{"ticker": tk, **old} for tk, old in current.items() if tk not in by_ticker]
    return {"added": added, "changed": changed, "removed": removed}


def run(conn: psycopg.Connection, dry_run: bool = False) -> dict:
    """KB 잔고 조회 → portfolio_holdings/portfolio_cash 전량 스왑. dry_run이면 DB 무변경."""
    if not kb_client.kb_enabled():
        logger.warning("KB_APP_KEY/KB_APP_SECRET 미설정 — KB 잔고 자동화 스킵")
        return {"skipped": "no_credentials"}

    raw = fetch_raw()
    known = _known_tickers(conn)
    holdings, cash, unresolved = build_rows(raw, known)
    current = _current_holdings(conn)
    diff = _diff(current, holdings)

    report = {
        "n_holdings": len(holdings),
        "cash": cash,
        "unresolved": unresolved,
        "diff": diff,
        "dry_run": dry_run,
        "applied": False,
    }
    for note in unresolved:
        logger.warning("KB 잔고 미해결: %s", note)

    if dry_run:
        _print_diff(holdings, cash, _current_cash(conn), diff, unresolved)
        return report

    # 안전장치 1 — 보유 0건이면 아무것도 지우지 않는다(API 장애 시 전멸 방지).
    if not holdings:
        logger.warning(
            "KB 응답 보유 0건 — portfolio_holdings/cash 변경 스킵(API 오류 시 전멸 방지)"
        )
        report["skipped"] = "empty_response"
        return report

    with conn.cursor() as cur:
        for h in holdings:
            cur.execute(
                """
                INSERT INTO portfolio_holdings (ticker, qty, avg_price, currency, updated_at)
                VALUES (%s, %s, %s, %s, now())
                ON CONFLICT (ticker) DO UPDATE
                   SET qty = EXCLUDED.qty, avg_price = EXCLUDED.avg_price,
                       currency = EXCLUDED.currency, updated_at = now()
                """,
                (h["ticker"], h["qty"], h["avg_price"], h["currency"]),
            )
        # 안전장치 2 — 미해결 종목이 있으면 삭제를 건너뛴다(못 읽은 보유를 매도로 오인 방지).
        if unresolved:
            logger.warning("미해결 %d건 — 'KB에 없는 행 제거'는 이번 실행에서 스킵", len(unresolved))
        else:
            cur.execute(
                "DELETE FROM portfolio_holdings WHERE ticker <> ALL(%s)",
                ([h["ticker"] for h in holdings],),
            )
            report["removed"] = [d["ticker"] for d in diff["removed"]]
        for ccy, amount in cash.items():
            cur.execute(
                """
                INSERT INTO portfolio_cash (currency, amount, updated_at)
                VALUES (%s, %s, now())
                ON CONFLICT (currency) DO UPDATE
                   SET amount = EXCLUDED.amount, updated_at = now()
                """,
                (ccy, amount),
            )
    conn.commit()
    report["applied"] = True
    logger.info(
        "KB 잔고 반영: 보유 %d종목(추가 %d·변경 %d·제거 %d), 현금 KRW %.0f / USD %.2f",
        len(holdings), len(diff["added"]), len(diff["changed"]),
        0 if unresolved else len(diff["removed"]), cash["KRW"], cash["USD"],
    )
    return report


def _print_diff(holdings, cash, cur_cash, diff, unresolved) -> None:
    print(f"\n=== KB 잔고 (조회 결과 {len(holdings)}종목) ===")
    for h in sorted(holdings, key=lambda x: x["ticker"]):
        print(f"  {h['ticker']:<12} {h['qty']:>12,.6f} @ {h['avg_price']:>12,.2f} {h['currency']}  {h['name']}")
    print(f"  현금: KRW {cash['KRW']:,.0f} (현행 {cur_cash.get('KRW', 0):,.0f})"
          f" / USD {cash['USD']:,.2f} (현행 {cur_cash.get('USD', 0):,.2f})")

    print("\n=== 현행 portfolio_holdings 대비 diff ===")
    for h in diff["added"]:
        print(f"  + 추가   {h['ticker']:<12} {h['qty']:,.6f} @ {h['avg_price']:,.2f} {h['currency']}")
    for c in diff["changed"]:
        print(f"  ~ 변경   {c['ticker']:<12} {c['old']['qty']:,.6f}@{c['old']['avg_price']:,.2f}"
              f" → {c['new']['qty']:,.6f}@{c['new']['avg_price']:,.2f}")
    for h in diff["removed"]:
        print(f"  - 제거   {h['ticker']:<12} {h['qty']:,.6f} @ {h['avg_price']:,.2f} {h['currency']}  (KB 잔고에 없음=매도)")
    if not any(diff.values()):
        print("  (변경 없음)")

    if unresolved:
        print("\n=== 미해결(수동 확인 필요) ===")
        for note in unresolved:
            print(f"  ! {note}")
        print("  → 미해결이 있으면 실적용 시 '제거' 단계를 건너뜁니다.")
    if not holdings:
        print("\n⚠️  KB 보유 0건 — 실적용 시 DB를 변경하지 않습니다(전멸 방지).")
    print("\n[dry-run] DB는 변경하지 않았습니다.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="KB증권 잔고 → portfolio_holdings/cash 동기화")
    parser.add_argument("--dry-run", action="store_true", help="DB 무변경, diff만 출력")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    from dotenv import load_dotenv

    load_dotenv()
    from src.db import get_conn

    with get_conn() as conn:
        report = run(conn, dry_run=args.dry_run)
    return 0 if not report.get("skipped") or args.dry_run else 1


if __name__ == "__main__":
    raise SystemExit(main())
