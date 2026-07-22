#!/usr/bin/env python
"""PR-A 일회성 수복 — market_daily를 '소스 체결일' 기준으로 재구축.

배경: 구 ingest_market은 소스 종가만 받아 **실행일**에 찍었다. 게다가 CI cron이
21:00 UTC(=06:00 KST)라 `date.today()`가 KST 전날이었다. 그 결과
  - KR 지수가 통째로 한 거래일씩 밀리고(07-16 −6.37% 급락이 +6.24% 급등으로 부호 반전)
  - 휴장일에도 실행돼 직전 종가를 복제한 유령봉이 쌓이고(07-17 제헌절·주말)
  - 같은 지수인데 market_daily와 index_daily 값이 어긋났다.

현행 수집기는 행의 asof를 소스 체결일로 잡으므로, 이 스크립트는 같은 규칙으로
과거 구간을 재적재하고 규칙에 맞지 않는 잔재(비거래일 행·체결일 불일치)를 지운다.

dry-run이 기본. 실제 반영은 --apply.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

from src import db, ingest_market  # noqa: E402
from src.freshness import is_trading_day  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-07-01", help="수복 시작 asof")
    ap.add_argument("--apply", action="store_true", help="실제 DB 반영 (기본 dry-run)")
    args = ap.parse_args()
    since = date.fromisoformat(args.since)

    load_dotenv()

    # 소스 체결일별 정본 행 (현행 수집기와 완전히 같은 경로).
    fresh = {r.asof: r for r in ingest_market.fetch_market_rows() if r.asof >= since}
    print(f"소스 정본 {len(fresh)}행 ({min(fresh)} ~ {max(fresh)})" if fresh else "소스 비어 있음")

    deleted, fixed = [], []
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT asof, kospi, kosdaq, sp500 FROM market_daily WHERE asof >= %s ORDER BY asof",
                (since,),
            )
            existing = {r["asof"]: dict(r) for r in cur.fetchall()}

        # 1) 유령봉 삭제 — KR·US 둘 다 휴장인 날에 만들어진 행.
        for asof in sorted(existing):
            if not (is_trading_day(asof, "KR") or is_trading_day(asof, "US")):
                deleted.append(asof)
                print(f"  삭제(비거래일 유령봉) asof={asof} kospi={existing[asof]['kospi']}")
                if args.apply:
                    with conn.cursor() as cur:
                        cur.execute("DELETE FROM market_daily WHERE asof=%s", (asof,))

        # 2) 정본 재적재 — 값이 다르거나 없는 날만.
        for asof, row in sorted(fresh.items()):
            old = existing.get(asof)
            # 소스가 None인 필드는 비교에서 제외 — upsert가 COALESCE라 덮어쓰지 않는다
            # (예 07-03 미 독립기념일: US 봉이 없어 sp500=None, 기존값 보존이 정답).
            same = old and all(
                getattr(row, k) is None
                or (old[k] is not None and abs(float(old[k]) - getattr(row, k)) < 0.01)
                for k in ("kospi", "kosdaq", "sp500")
            )
            if same:
                continue
            fixed.append(asof)
            print(
                f"  정정 asof={asof} kospi {old['kospi'] if old else '(없음)'} → {row.kospi}"
                f" / sp500 {old['sp500'] if old else '(없음)'} → {row.sp500}"
            )
            if args.apply:
                db.upsert_market_daily(conn, row)

        # 2b) index_daily에는 있는데 market_daily에 행 자체가 없는 거래일 보충
        #     (구 수집기가 실행일 기준이라 결번이 생겼다). 값은 아래 3)이 채운다.
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT ix.asof FROM index_daily ix
                WHERE ix.asof >= %s
                  AND NOT EXISTS (SELECT 1 FROM market_daily m WHERE m.asof = ix.asof)
                ORDER BY 1
            """, (since,))
            missing = [r["asof"] for r in cur.fetchall()]
        for asof in missing:
            print(f"  결번 보충 asof={asof}")
            if args.apply:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO market_daily (asof, payload) VALUES (%s, '{}'::jsonb)"
                        " ON CONFLICT (asof) DO NOTHING", (asof,),
                    )

        # 3) 지수 컬럼을 index_daily와 일치시킨다.
        #    index_daily는 지수 종가의 정본이므로 market_daily의 지수 컬럼은 그 사본이어야 한다.
        #    - 시장이 휴장인 날 남아 있는 값 = 구버전이 복제한 유령값 → NULL
        #      (KR 07-17 제헌절 / US 06-19 Juneteenth·07-03 독립기념일이 실제로 이 경우였다)
        #    - 값이 없거나 다르면 index_daily 값으로 맞춘다
        synced = 0
        for index_code, col, market in (
            ("^KS11", "kospi", "KR"), ("^KQ11", "kosdaq", "KR"),
            ("^GSPC", "sp500", "US"), ("^IXIC", "nasdaq", "US"),
        ):
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT m.asof, m.{col} AS cur_val, ix.close AS idx_val
                    FROM market_daily m
                    LEFT JOIN index_daily ix ON ix.asof = m.asof AND ix.index_code = %s
                    WHERE m.asof >= %s
                      AND (m.{col} IS DISTINCT FROM ix.close)
                    ORDER BY m.asof
                """, (index_code, since))
                diffs = [dict(r) for r in cur.fetchall()]

            for d in diffs:
                if d["asof"] in deleted:
                    continue
                new = d["idx_val"]
                if new is None and is_trading_day(d["asof"], market):
                    continue  # 개장일인데 지수 이력이 아직 없음 — 지우지 않는다(백필 대기)
                tag = "휴장 유령값 제거" if new is None else "index_daily 동기화"
                print(f"  {tag} asof={d['asof']} {col}: {d['cur_val']} → {new}")
                synced += 1
                if args.apply:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"UPDATE market_daily SET {col}=%s,"
                            " payload = COALESCE(payload,'{}'::jsonb) || %s::jsonb WHERE asof=%s",
                            (new, json.dumps({"syncedFromIndexDaily": True}), d["asof"]),
                        )

        if args.apply:
            conn.commit()

    mode = "적용" if args.apply else "DRY-RUN(미반영)"
    print(f"\n{mode}: 삭제={len(deleted)} 정정={len(fixed)} 지수동기화={synced}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
