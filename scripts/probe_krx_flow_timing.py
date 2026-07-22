#!/usr/bin/env python
"""KRX 투자자 수급 **확정 공개시각 실측** (PR-B 항목5 선행).

왜 필요한가: 저녁 수집 슬롯을 22:30 → 17~18시로 당기려면 그 시각의 값이 **확정치**여야
한다. 너무 앞당겨 잠정치를 적재하면 스케줄 지연 문제보다 나쁘다(틀린 수급이 이상움직임
귀인·판단까지 오염). "장 마감 후 대략 몇 시"라는 통념은 근거가 아니므로 실제로 잰다.

방법: 같은 거래일의 값을 여러 시각에 반복 샘플링해 JSONL로 남긴다. 값이 더 이상 변하지
않는 최초 시각이 곧 **확정 시각**이다. 하루치로는 우연을 배제할 수 없어 2~3거래일 권장.

사용:
  # launchd/cron으로 여러 시각에 호출(권장) 또는 수동 반복
  python scripts/probe_krx_flow_timing.py            # 1회 샘플 → 로그 append
  python scripts/probe_krx_flow_timing.py --report   # 수집된 로그 분석(수렴 시각 산출)

로그: ~/atlas_logs/krx_flow_timing.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

KST = ZoneInfo("Asia/Seoul")
LOG = Path.home() / "atlas_logs" / "krx_flow_timing.jsonl"

# 대표 종목 몇 개만 — 공개 시각은 종목별로 다르지 않으므로 표본을 넓힐 이유가 없다.
PROBE_TICKERS = ("005930", "000660", "035420")


def sample() -> dict:
    from pykrx import stock

    now = datetime.now(KST)
    target = now.date()
    start = (target - timedelta(days=5)).strftime("%Y%m%d")
    end = target.strftime("%Y%m%d")

    values: dict[str, dict] = {}
    for code in PROBE_TICKERS:
        try:
            df = stock.get_market_trading_value_by_date(start, end, code)
            if df.empty:
                values[code] = {"error": "empty"}
                continue
            last_date = df.index[-1]
            row = df.iloc[-1]
            values[code] = {
                "barDate": str(last_date)[:10],
                "foreign": float(row.get("외국인합계", 0)),
                "institution": float(row.get("기관합계", 0)),
                "individual": float(row.get("개인", 0)),
            }
        except Exception as exc:  # 종목 단위 격리
            values[code] = {"error": str(exc)[:120]}

    return {
        "probedAt": now.isoformat(timespec="seconds"),
        "probeDate": target.isoformat(),
        "probeHourKst": now.hour + now.minute / 60,
        "values": values,
    }


def report() -> int:
    if not LOG.exists():
        print(f"로그 없음: {LOG}\n먼저 여러 시각에 샘플을 모아라(--report는 분석 전용).")
        return 1

    entries = [json.loads(l) for l in LOG.read_text().splitlines() if l.strip()]
    # (봉 날짜) → [(관측시각, 값묶음)] — 봉 날짜별로 값이 언제 굳는지 본다.
    by_bar: dict[str, list] = defaultdict(list)
    for e in entries:
        for code, v in e["values"].items():
            if "barDate" not in v:
                continue
            by_bar[v["barDate"]].append((e["probedAt"], e["probeHourKst"], code, v))

    print(f"샘플 {len(entries)}회, 봉 날짜 {len(by_bar)}종\n")
    for bar_date in sorted(by_bar):
        obs = sorted(by_bar[bar_date], key=lambda x: x[0])
        final = {}
        for _, _, code, v in obs:
            final[code] = (v["foreign"], v["institution"], v["individual"])

        converged_at = None
        for probed_at, hour, code, v in obs:
            cur = (v["foreign"], v["institution"], v["individual"])
            if cur != final.get(code):
                converged_at = None  # 아직 변동 중 — 이후 관측에서 다시 잡는다
            elif converged_at is None:
                converged_at = (probed_at, hour)

        print(f"■ 봉 {bar_date}: 관측 {len(obs)}건")
        for probed_at, hour, code, v in obs:
            cur = (v["foreign"], v["institution"], v["individual"])
            mark = "=최종" if cur == final.get(code) else "≠최종(잠정)"
            print(f"    {probed_at} ({hour:.1f}시) {code} 외국인={v['foreign']:>16,.0f} {mark}")
        if converged_at:
            print(f"    → 최초 수렴 관측: {converged_at[0]} ({converged_at[1]:.1f}시 KST)")
        print()

    print("판정 기준: 어떤 시각 이후 값이 더 이상 바뀌지 않으면 그 시각이 확정 시각.")
    print("주의: 관측 간격보다 정밀할 수 없다. 17~18시 슬롯을 노린다면 16·17·18·19시를 촘촘히 재라.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="수집 로그 분석(수렴 시각 산출)")
    args = ap.parse_args()

    load_dotenv()
    if args.report:
        return report()

    entry = sample()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"샘플 기록 {entry['probedAt']} → {LOG}")
    for code, v in entry["values"].items():
        if "barDate" in v:
            print(f"  {code} 봉={v['barDate']} 외국인={v['foreign']:,.0f} 기관={v['institution']:,.0f}")
        else:
            print(f"  {code} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
