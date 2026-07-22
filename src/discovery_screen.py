"""Phase C — 발굴 스크린(관심종목 밖 대형주 경량 스크리닝).

유니버스: US=S&P500+나스닥100, KR=코스피200+코스닥150(~870).
경량 원칙(§8): 뉴스·LLM(Gemini)·investor_flow **호출 금지**. 순수 스크래핑·계산만.
  KR: pykrx 벌크(get_market_fundamental=PER/PBR/EPS/BPS, get_market_price_change=1Y 등락률).
      ROE는 EPS/BPS 프록시, 성장은 1년전 EPS 대비 델타. **로컬 전용**(KRX CI 차단).
  US: yfinance(yf.download=가격 모멘텀, Ticker.info=PER/PBR/ROE/성장). 레이트리밋 완화(지터).
점수(Phase B 상수 재사용): 장기=quality0.35+value0.35+growth0.30, 모멘텀=**가격 모멘텀만**
  (뉴스 sentiment 없음 — 경량 프록시 라벨). percentile은 **시장 내부**(KR/US 회계·밸류 규범 상이).
§F7: 오늘 스냅샷. watchlist quant_scores와 분리(discovery_screen). 승격은 KPH 수동(자동 추가 금지).
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from io import StringIO
from typing import Optional

from src.db import get_conn, upsert_discovery_screen
# 장기점수 가중치·블렌드는 Phase B(#82)의 canonical 단일 소스에서 import(로컬 복사 제거).
# ※ discovery 모멘텀은 가격 프록시(뉴스 sentiment 없음)라 MOMO_SCORE_WEIGHTS는 쓰지 않는다.
from src.export_dashboard_data import LONG_SCORE_WEIGHTS, _blend
from src.freshness import today_kst

logger = logging.getLogger(__name__)

_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}
_WIKI = {
    "sp500": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "nasdaq100": "https://en.wikipedia.org/wiki/Nasdaq-100",
}
US_INFO_SLEEP = 0.15  # ponytail: 순차 .info 레이트리밋 완화(고정 지터). 폭주 시 상향.


# ── 유니버스 소싱 ──────────────────────────────────────────────────────
def _us_constituents() -> dict[str, list[str]]:
    """{ticker: [source_index...]} — S&P500 + 나스닥100(위키, requests). 실패 시 빈 dict."""
    import pandas as pd
    import requests

    out: dict[str, list[str]] = {}
    for idx, url in _WIKI.items():
        try:
            r = requests.get(url, headers=_UA, timeout=15)
            r.raise_for_status()
            tables = pd.read_html(StringIO(r.text))
        except Exception as exc:  # noqa: BLE001 — 위키 접근 실패는 스킵(주간 best-effort)
            logger.warning("US 구성종목(%s) 소싱 실패: %s", idx, str(exc)[:100])
            continue
        for tb in tables:
            cols = [str(c) for c in tb.columns]
            sym_col = next((c for c in cols if "Symbol" in c or "Ticker" in c), None)
            if sym_col:
                for sym in tb[sym_col].astype(str):
                    t = sym.strip().replace(".", "-").upper()  # BRK.B → BRK-B(yfinance)
                    if t and t != "NAN":
                        out.setdefault(t, [])
                        if idx not in out[t]:
                            out[t].append(idx)
                break
    return out


def _kr_constituents() -> dict[str, tuple[str, str]]:
    """{ticker(.KS/.KQ): (code, source_index)} — 코스피200·코스닥150(pykrx). 로컬 전용."""
    from pykrx import stock

    out: dict[str, tuple[str, str]] = {}
    for idx, code, suffix in [("kospi200", "1028", "KS"), ("kosdaq150", "2203", "KQ")]:
        try:
            for c in stock.get_index_portfolio_deposit_file(code):
                out[f"{c}.{suffix}"] = (c, idx)
        except Exception as exc:  # noqa: BLE001
            logger.warning("KR 구성종목(%s) 소싱 실패: %s", idx, str(exc)[:100])
    return out


# ── 벌크 지표 수집 ─────────────────────────────────────────────────────
def _fnum(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None  # NaN 제거


def _pos(x) -> Optional[float]:
    """양수만 유효(<=0 → None). PER/PBR/BPS는 0·음수가 '적자·무의미'라 밸류 랭킹에서 제외해야
    한다(pykrx는 적자 종목 PER=0으로 반환 → 저PER=고가치 오판 방지)."""
    v = _fnum(x)
    return v if (v is not None and v > 0) else None


def fetch_kr_metrics(cons: dict[str, tuple[str, str]], asof: date) -> list[dict]:
    """KR 벌크 지표(pykrx). raw PER/PBR/ROE프록시/성장/1Y수익률. 종목당 추가 호출 없음."""
    from pykrx import stock

    # 주말·휴장이면 단일일자 fundamental이 0을 반환하므로 최근 거래일로 해소(삼성 PER 유효 확인).
    def _last_trading_day(d: date) -> str:
        for _ in range(7):
            ds = d.strftime("%Y%m%d")
            try:
                df = stock.get_market_fundamental(ds, market="KOSPI")
                if df is not None and "005930" in df.index and _pos(df.loc["005930"].PER):
                    return ds
            except Exception:  # noqa: BLE001, S110
                pass
            d -= timedelta(days=1)
        return d.strftime("%Y%m%d")

    end = _last_trading_day(asof)
    start = _last_trading_day(asof - timedelta(days=365))
    logger.info("KR fundamental 기준일: now=%s prev=%s", end, start)
    fund_now, fund_prev, pchg = {}, {}, {}
    for market in ("KOSPI", "KOSDAQ"):
        try:
            fund_now[market] = stock.get_market_fundamental(end, market=market)
            fund_prev[market] = stock.get_market_fundamental(start, market=market)
            pchg[market] = stock.get_market_price_change(start, end, market=market)
        except Exception as exc:  # noqa: BLE001
            logger.warning("KR %s 벌크 조회 실패: %s", market, str(exc)[:100])

    def _board(code_suffix: str) -> str:
        return "KOSPI" if code_suffix == "KS" else "KOSDAQ"

    rows = []
    for ticker, (code, idx) in cons.items():
        board = _board(ticker.rsplit(".", 1)[-1])
        fn, fp, pc = fund_now.get(board), fund_prev.get(board), pchg.get(board)
        per = pbr = eps = bps = ret = eps_prev = None
        if fn is not None and code in fn.index:
            per, pbr = _pos(fn.loc[code].PER), _pos(fn.loc[code].PBR)  # 적자·무의미 PER/PBR 제외
            eps, bps = _fnum(fn.loc[code].EPS), _pos(fn.loc[code].BPS)  # EPS는 음수 허용(ROE)
        if fp is not None and code in fp.index:
            eps_prev = _fnum(fp.loc[code].EPS)
        name = None
        if pc is not None and code in pc.index:
            ret = _fnum(pc.loc[code]["등락률"])
            name = str(pc.loc[code]["종목명"])  # pykrx price_change가 종목명 제공(추가 콜 없음)
        roe = (eps / bps) if (eps and bps and bps != 0) else None  # ROE 프록시
        growth = ((eps / eps_prev - 1) if (eps and eps_prev and eps_prev > 0) else None)
        rows.append({
            "ticker": ticker, "market": "KR", "name": name, "source_index": idx,
            "metrics": {"per": per, "pbr": pbr, "roe": roe, "growth": growth, "ret1y": ret},
        })
    return rows


def fetch_us_metrics(cons: dict[str, list[str]]) -> list[dict]:
    """US 벌크 지표(yfinance). 가격 모멘텀=yf.download 1콜, 펀더=Ticker.info 종목당(지터)."""
    import yfinance as yf

    tickers = list(cons.keys())
    ret1y: dict[str, Optional[float]] = {}
    try:
        px = yf.download(tickers, period="1y", progress=False, auto_adjust=True)["Close"]
        for t in tickers:
            s = px[t].dropna() if t in px.columns else None
            if s is not None and len(s) > 20 and s.iloc[0]:
                ret1y[t] = float(s.iloc[-1] / s.iloc[0] - 1) * 100
    except Exception as exc:  # noqa: BLE001
        logger.warning("US 가격 벌크 실패: %s", str(exc)[:100])

    rows = []
    for t in tickers:
        per = pbr = roe = growth = None
        try:
            info = yf.Ticker(t).info
            per = _pos(info.get("trailingPE"))   # 음수 PE(적자) 제외
            pbr = _pos(info.get("priceToBook"))
            roe = _fnum(info.get("returnOnEquity"))  # ROE는 음수 허용(저품질)
            growth = _fnum(info.get("revenueGrowth"))
            if growth is None:
                growth = _fnum(info.get("earningsGrowth"))
            name = info.get("shortName")
        except Exception as exc:  # noqa: BLE001 — 종목 단위 격리(스킵)
            logger.debug("US %s info 실패: %s", t, str(exc)[:60])
            name = None
        rows.append({
            "ticker": t, "market": "US", "name": name, "source_index": ",".join(cons[t]),
            "metrics": {"per": per, "pbr": pbr, "roe": roe, "growth": growth, "ret1y": ret1y.get(t)},
        })
        time.sleep(US_INFO_SLEEP)
    return rows


# ── 스코어링(시장 내부 percentile → 장기·모멘텀 블렌드) ────────────────────
def _percentiles(pairs: list[tuple[str, Optional[float]]], lower_better: bool = False) -> dict[str, float]:
    """(ticker, raw) → {ticker: 0~100 백분위}. 결측 제외. 단일/부족은 중립 50."""
    valid = [(t, r) for t, r in pairs if r is not None]
    if len(valid) < 2:
        return {t: 50.0 for t, _ in valid}
    goodness = {t: (-r if lower_better else r) for t, r in valid}
    order = sorted(goodness, key=lambda t: goodness[t])  # 나쁨→좋음
    n = len(order)
    return {t: round(100 * i / (n - 1), 1) for i, t in enumerate(order)}


def score_market(rows: list[dict]) -> None:
    """시장 내부 percentile로 value/quality/growth/momentum + 장기·모멘텀점수 채움(in-place)."""
    def col(key):
        return [(r["ticker"], r["metrics"].get(key)) for r in rows]

    per_pct = _percentiles(col("per"), lower_better=True)   # 저PER=고가치
    pbr_pct = _percentiles(col("pbr"), lower_better=True)
    roe_pct = _percentiles(col("roe"))
    grw_pct = _percentiles(col("growth"))
    mom_pct = _percentiles(col("ret1y"))

    for r in rows:
        t = r["ticker"]
        # 가치 = 저PER·저PBR 백분위 평균(둘 중 있는 것만)
        vparts = [p.get(t) for p in (per_pct, pbr_pct) if p.get(t) is not None]
        value = round(sum(vparts) / len(vparts), 1) if vparts else None
        quality = roe_pct.get(t)
        growth = grw_pct.get(t)
        momentum = mom_pct.get(t)
        r["value"], r["quality"], r["growth"], r["momentum"] = value, quality, growth, momentum
        long_parts = [(quality, LONG_SCORE_WEIGHTS["quality"]),
                      (value, LONG_SCORE_WEIGHTS["value"]),
                      (growth, LONG_SCORE_WEIGHTS["growth"])]
        n_long = sum(1 for v, _ in long_parts if v is not None)
        # 완결성 가드: 장기점수는 **3축 중 2축+** 있어야 유효(value 한 축만으로 저PBR 종목이
        # 장기 상위에 오르는 인플레 방지). 경량 스크린의 결측이 잦아 필수.
        r["long_term_score"] = _blend(long_parts) if n_long >= 2 else None
        r["metrics"]["n_long_axes"] = n_long
        # 경량 모멘텀점수 = 가격 모멘텀 백분위(뉴스 sentiment 없음 — 프록시)
        r["momentum_score"] = momentum


def run_discovery_screen(conn, markets: tuple[str, ...] = ("US", "KR"), asof: Optional[date] = None) -> dict:
    """유니버스 소싱 → 벌크 지표 → 시장 내부 스코어 → discovery_screen upsert. 요약 반환."""
    asof = asof or today_kst()
    # watchlist 플래그용
    with conn.cursor() as cur:
        cur.execute("SELECT ticker FROM watchlist")
        wl = {r["ticker"] for r in cur.fetchall()}

    all_rows: list[dict] = []
    if "US" in markets:
        us_cons = _us_constituents()
        logger.info("US 구성종목 %d", len(us_cons))
        if us_cons:
            us_rows = fetch_us_metrics(us_cons)
            score_market(us_rows)
            all_rows += us_rows
    if "KR" in markets:
        kr_cons = _kr_constituents()
        logger.info("KR 구성종목 %d", len(kr_cons))
        if kr_cons:
            kr_rows = fetch_kr_metrics(kr_cons, asof)
            score_market(kr_rows)
            all_rows += kr_rows

    for r in all_rows:
        r["asof"] = asof
        r["in_watchlist"] = r["ticker"] in wl

    if all_rows:
        upsert_discovery_screen(conn, all_rows)
        conn.commit()

    n_disc = sum(1 for r in all_rows if not r["in_watchlist"])
    null_long = sum(1 for r in all_rows if r.get("long_term_score") is None)
    logger.info("discovery_screen: %d 적재(발굴 %d, in_watchlist %d), long_null %d",
                len(all_rows), n_disc, len(all_rows) - n_disc, null_long)
    return {"n": len(all_rows), "n_discovery": n_disc, "asof": asof.isoformat(), "long_null": null_long}


def main() -> int:
    """로컬 주간 실행 진입점: `python -m src.discovery_screen`. KR 포함(로컬만)."""
    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    with get_conn() as conn:
        res = run_discovery_screen(conn)
    logger.info("완료: %s", res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
