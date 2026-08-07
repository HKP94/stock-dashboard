"""
kb_supply_pilot.py — [KB API 2단계] IVU10430 수급 파일럿 (검증·리포트 전용)

목적: KB의 종목별 투자자 매매동향(IVU10430)이 현행 pykrx 수집(investor_flow)을
대체/보완할 수 있는지 판정할 근거를 만든다. **계좌 무관 API만 사용**한다.

★ 이 스크립트는 DB에 아무것도 쓰지 않는다(읽기만). 스키마 변경 없음. 통합은 별도 PR.

산출물:
  1) 비교표: KB(IVU10430) vs pykrx(라이브) vs 실DB(investor_flow) — 종목×일자별 외인/기관/개인
  2) 12분류 상세 충전 여부(증권·보험·투신·종금·은행·기금·사모·기타법인·국가·내외국인·프로그램·외국계)
  3) rate limit 실측: 호출 수·응답시간·429/차단 발생 여부·한도 관련 응답 헤더

호출 예산: 종목 5개 × 1콜(5거래일을 한 번에 조회) = 5콜. 대량 백필 금지.

실행:
  python scripts/kb_supply_pilot.py                 # 로컬 전체(KB+pykrx+DB 3자 대조)
  python scripts/kb_supply_pilot.py --kb-only       # CI용: KB 1콜만(pykrx·DB 접근 없음)
  python scripts/kb_supply_pilot.py --reachability  # CI용: 키 없이 네트워크 도달성만
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import kb_client  # noqa: E402
from src.kb_supply import (  # noqa: E402
    DETAIL_FIELDS,
    KB_UNIT_KRW,
    SUPPLY_API,
    _num,
    parse_supply_records,
)

# 파일럿 대상 — 보유(삼성전자·현대해상) + 관심(하이닉스·효성중공업) + 코스닥(미코).
PILOT_TICKERS: list[tuple[str, str]] = [
    ("005930.KS", "삼성전자"),
    ("001450.KS", "현대해상"),
    ("000660.KS", "SK하이닉스"),
    ("298040.KS", "효성중공업"),
    ("059090.KQ", "미코"),
]
PILOT_DAYS = 5           # 최근 5거래일
LOOKBACK_CALENDAR = 12   # 5거래일을 덮는 캘린더 여유

# 백만원 반올림 때문에 원 단위 환산 시 종목·일자당 최대 ~1백만원 잔차가 남는다(구조적).
ROUNDING_TOLERANCE_KRW: float = 1_000_000.0


_metrics: dict = {"calls": 0, "elapsed": [], "errors": [], "rate_limited": 0, "headers": {}}



def fetch_kb_supply(code: str, start: date, end: date) -> list[dict]:
    """IVU10430 1콜 → 일자별 out 레코드. 금액·순매수·확정치 기준."""
    started = time.monotonic()
    body = kb_client.call(
        SUPPLY_API,
        {
            "excg_clsf": "1",        # KRX (pykrx와 동일 시장 기준으로 맞춘다)
            "is_cd": code,
            "strt_dt": start.strftime("%Y%m%d"),
            "end_dt": end.strftime("%Y%m%d"),
            "amt_q_clsf": "1",       # 1:금액
            "trd_clsf": "1",         # 1:순매수
            "acml_clsf": "0",        # 0:누적안함(일별)
        },
    )
    _metrics["calls"] += 1
    _metrics["elapsed"].append(round(time.monotonic() - started, 3))
    _record_limit_headers()
    return body.get("out") or []


# rate limit 힌트를 줄 만한 응답 헤더만 골라 기록(값 자체에 시크릿 없음).
_LIMIT_HEADER_HINTS = ("ratelimit", "rate-limit", "retry-after", "x-quota", "throttle")


def _record_limit_headers() -> None:
    headers = kb_client.LAST_RESPONSE.get("headers") or {}
    for key, value in headers.items():
        if any(hint in key.lower() for hint in _LIMIT_HEADER_HINTS):
            _metrics["headers"][key] = value
    if kb_client.LAST_RESPONSE.get("status") == 429:
        _metrics["rate_limited"] += 1



# ── 대조 소스 ────────────────────────────────────────────────────────────────
def fetch_pykrx(code: str, start: date, end: date) -> dict[str, dict]:
    """pykrx 라이브(현행 수집과 같은 함수) → {YYYYMMDD: {...}}. 실패 시 빈 dict."""
    from src.ingest_kr import KRX_HTTP_TIMEOUT_S, _bounded

    from pykrx import stock as pykrx_stock

    df = _bounded(
        f"pykrx.pilot:{code}",
        lambda: pykrx_stock.get_market_trading_value_by_date(
            start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), code, on="순매수"
        ),
        KRX_HTTP_TIMEOUT_S,
    )
    if df is None or df.empty:
        return {}
    return {
        dt.date(): {
            "foreign": float(df.loc[dt].get("외국인합계", 0) or 0),
            "institution": float(df.loc[dt].get("기관합계", 0) or 0),
            "individual": float(df.loc[dt].get("개인", 0) or 0),
        }
        for dt in df.index
    }


def fetch_db(conn, ticker: str, start: date, end: date) -> dict[str, dict]:
    """실DB investor_flow → {YYYYMMDD: {...}}. 읽기 전용."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT date, foreign_net, institution_net, individual_net
              FROM investor_flow
             WHERE ticker = %s AND date BETWEEN %s AND %s
             ORDER BY date
            """,
            (ticker, start, end),
        )
        return {
            r["date"]: {
                "foreign": float(r["foreign_net"] or 0),
                "institution": float(r["institution_net"] or 0),
                "individual": float(r["individual_net"] or 0),
            }
            for r in cur.fetchall()
        }


# ── 리포트 ───────────────────────────────────────────────────────────────────
def _fmt(value: float | None) -> str:
    return f"{value:,.0f}" if value is not None else "—"


def _verdict(kb: float | None, ref: float | None) -> str:
    """KB(원 환산) vs 기준값 — 백만원 반올림 잔차 이내면 일치."""
    if kb is None or ref is None:
        return "—"
    diff = kb - ref
    if abs(diff) <= ROUNDING_TOLERANCE_KRW:
        return f"일치(±{abs(diff):,.0f})"
    return f"★불일치({diff:+,.0f})"


def compare(ticker: str, name: str, code: str, start: date, end: date, conn) -> dict:
    """종목 1개 3자 대조 → 결과 dict + 표 출력."""
    result: dict = {"ticker": ticker, "name": name, "rows": [], "error": None}
    try:
        kb = parse_supply_records(fetch_kb_supply(code, start, end))
    except Exception as exc:
        _metrics["errors"].append(f"{ticker}: {exc}")
        result["error"] = str(exc)
        print(f"\n### {ticker} {name} — KB 호출 실패: {exc}")
        return result

    pykrx_rows = fetch_pykrx(code, start, end) if conn is not None else {}
    db_rows = fetch_db(conn, ticker, start, end) if conn is not None else {}

    print(f"\n### {ticker} {name}  (KB {len(kb)}일 / pykrx {len(pykrx_rows)}일 / DB {len(db_rows)}일)")
    dates = sorted(set(kb) | set(pykrx_rows) | set(db_rows), reverse=True)[:PILOT_DAYS]
    if not dates:
        print("  (대조할 일자 없음)")
        return result

    print(f"  {'일자':<10}{'투자자':<7}{'KB(원 환산)':>20}{'pykrx(라이브)':>20}{'DB(investor_flow)':>20}   KB vs DB")
    for dt in sorted(dates):
        for key, label in (("foreign", "외국인"), ("institution", "기관"), ("individual", "개인")):
            k = kb.get(dt, {}).get(key)
            p = pykrx_rows.get(dt, {}).get(key)
            d = db_rows.get(dt, {}).get(key)
            verdict = _verdict(k, d)
            result["rows"].append({"date": dt, "investor": label, "kb": k, "pykrx": p,
                                   "db": d, "verdict": verdict})
            if verdict.startswith("★"):
                result["mismatches"] = result.get("mismatches", 0) + 1
            print(f"  {str(dt):<12}{label:<7}{_fmt(k):>20}{_fmt(p):>20}{_fmt(d):>20}   {verdict}")

    # 외국인 정의 차이 노출 — KB fgnr 단독은 pykrx 외국인합계와 다르다.
    latest = max(kb) if kb else None
    if latest and latest in db_rows:
        narrow, wide = kb[latest]["foreign_narrow"], kb[latest]["foreign"]
        print(f"  외국인 정의({latest}): KB fgnr 단독 {_fmt(narrow)} → {_verdict(narrow, db_rows[latest]['foreign'])}"
              f" / fgnr+내외국인 {_fmt(wide)} → {_verdict(wide, db_rows[latest]['foreign'])}")

    # 12분류 상세 충전 여부(가장 최근 일자 기준)
    if latest:
        details = kb[latest]["details"]
        filled = [ko for ko, v in details.items() if v != 0]
        result["details_latest"] = {"date": latest, "filled": filled, "all": details}
        print(f"  12분류 상세({latest}): 값 있는 항목 {len(filled)}/{len(DETAIL_FIELDS)} → "
              f"{', '.join(filled) if filled else '(전부 0)'}")
        detail_sum = sum(details[k] for k in ("증권", "보험", "투신", "종금", "은행", "기금", "사모펀드"))
        print(f"    기관합계 {_fmt(kb[latest]['institution'])} vs 상세 7항목 합 {_fmt(detail_sum)}"
              f" → {_verdict(detail_sum, kb[latest]['institution'])}")
    return result


def probe_reachability() -> int:
    """
    키 없이 KB 서버 도달성만 확인 — **CI IP 차단 가설의 핵심 판별**.

    KRX는 CI(미국 데이터센터 IP)를 지오/방화벽 차단해 로그인이 빈 응답으로 죽는다.
    KB가 같은 성질이면 여기서 연결 자체가 실패한다. 반대로 KB가 앱서버 응답
    (더미 앱키에 대한 500 E021 "앱키로 앱정보 추출 중 오류")을 주면 **네트워크 경로는 열려 있다**는
    뜻이다. 시크릿 없이 판별되므로 Secret 등록 전에도 실행할 수 있다.
    """
    import requests

    url = f"{kb_client.BASE_URL}/oauth2/token"
    payload = {"dataHeader": {},
               "dataBody": {"grantType": "client_credentials",
                            "appKey": "0" * 36, "appSecret": "0" * 32}}
    print(f"[CI probe] 네트워크 도달성 시험(키 없음) → {url}")
    started = time.monotonic()
    try:
        resp = requests.post(url, json=payload, timeout=20)
    except requests.RequestException as exc:
        print(f"✗ 연결 실패({type(exc).__name__}) — KRX와 동일한 IP/지오 차단 의심")
        print(json.dumps({"reachable": False, "error": type(exc).__name__}, ensure_ascii=False))
        return 1
    elapsed = time.monotonic() - started
    head = {}
    try:
        head = (resp.json() or {}).get("dataHeader") or {}
    except ValueError:
        pass
    print(f"✓ 도달 가능: HTTP {resp.status_code}, {elapsed:.2f}s")
    print(f"  KB 응답: processCode={head.get('processCode')} msg={head.get('processMessage')}")
    print("  (더미 앱키이므로 인증 실패가 정상 — 요점은 '응답이 온다'는 것)")
    print(json.dumps({"reachable": True, "status": resp.status_code,
                      "process_code": head.get("processCode"),
                      "elapsed_s": round(elapsed, 2)}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="KB IVU10430 수급 파일럿(검증 전용, DB 쓰기 없음)")
    parser.add_argument("--kb-only", action="store_true",
                        help="CI용: KB 1콜만 시험(pykrx·DB 접근 없음)")
    parser.add_argument("--reachability", action="store_true",
                        help="CI용: 키 없이 네트워크 도달성만 시험(지오/IP 차단 판별)")
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    if args.reachability:
        return probe_reachability()

    if not kb_client.kb_enabled():
        print("✗ KB_APP_KEY/KB_APP_SECRET 미설정")
        return 1

    end = date.today()
    start = end - timedelta(days=LOOKBACK_CALENDAR)

    if args.kb_only:
        # CI 호출 가능성 시험 — 1콜, 계좌 무관, 값 자체는 출력하지 않고 형태만 확인.
        print(f"[CI probe] IVU10430 1콜 시험 ({start}~{end})")
        started = time.monotonic()
        try:
            records = fetch_kb_supply("005930", start, end)
        except Exception as exc:
            print(f"✗ 실패: {exc}")
            print(json.dumps({"ok": False, "error": str(exc)[:300]}, ensure_ascii=False))
            return 1
        elapsed = time.monotonic() - started
        rows = parse_supply_records(records)
        print(f"✓ 성공: {len(records)}레코드(확정치 {len(rows)}일), {elapsed:.2f}s")
        print(json.dumps({"ok": True, "records": len(records), "confirmed_days": len(rows),
                          "elapsed_s": round(elapsed, 2)}, ensure_ascii=False))
        return 0

    from src.db import get_conn

    print(f"=== KB IVU10430 수급 파일럿 — 조회기간 {start} ~ {end} (최근 {PILOT_DAYS}거래일 대조) ===")
    print("※ 검증 전용 — DB에 쓰지 않습니다.")
    results = []
    with get_conn() as conn:
        for ticker, name in PILOT_TICKERS:
            results.append(compare(ticker, name, ticker.split(".")[0], start, end, conn))

    print("\n=== rate limit 실측 ===")
    elapsed = _metrics["elapsed"]
    print(f"  총 호출: {_metrics['calls']}콜 (+토큰 1콜)")
    if elapsed:
        print(f"  응답시간: 최소 {min(elapsed):.2f}s / 중앙 {sorted(elapsed)[len(elapsed)//2]:.2f}s"
              f" / 최대 {max(elapsed):.2f}s")
    print(f"  429/차단: {_metrics['rate_limited']}건")
    print(f"  한도 관련 응답 헤더: {_metrics['headers'] or '(없음 — KB가 한도 정보를 헤더로 주지 않음)'}")
    for err in _metrics["errors"]:
        print(f"  실패: {err}")

    ok = sum(1 for r in results if not r["error"])
    compared = sum(len(r["rows"]) for r in results)
    mism = sum(r.get("mismatches", 0) for r in results)
    print(f"\n=== 요약 ===")
    print(f"  KB 조회 성공: {ok}/{len(results)} 종목")
    print(f"  대조 셀: {compared}건 중 불일치 {mism}건"
          f" (허용 잔차 ±{ROUNDING_TOLERANCE_KRW:,.0f}원 = 백만원 반올림)")
    print(f"  관례차 1 — 단위: KB=백만원, pykrx/DB=원 (×{KB_UNIT_KRW:,} 환산 필요)")
    print(f"  관례차 2 — 외국인: KB fgnr ≠ pykrx 외국인합계. fgnr + ntv_fgnr(내외국인)로 맞춰야 정합")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
