"""
dashboard/app.py — ATLAS 관심종목 대시보드 (Streamlit, 로컬 우선)

데이터 소스:
  - src.assemble.assemble_daily(conn)  → 종목 일일 레코드(§5.2, bulk라 빠름)
  - market_daily 테이블                → 시장 스트립
  - prices_daily 테이블                → 드릴다운 가격 차트
  - src.compute_quant.compute_regime    → 상단 레짐 배지

DB 접속: src.db 패턴 재사용 (DB_* 환경변수 또는 .streamlit/secrets.toml).
모든 출력은 정보·참고용. 투자 자문 표현 금지(점수·사실만).

실행: streamlit run dashboard/app.py

⚠️ 투자 자문 아님 / 원금 손실 가능
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta

import pandas as pd
import streamlit as st

# 리포 루트를 import 경로에 추가 (streamlit run dashboard/app.py 대응)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

DISCLAIMER = "본 화면은 정보·정량 분석 참고용이며 투자 자문이 아닙니다. 원금 손실이 발생할 수 있습니다."

_REGIME_BADGE = {
    "bull": ("🟢 강세 (bull)", "#1b5e20"),
    "neutral": ("🟡 중립 (neutral)", "#f9a825"),
    "bear": ("🔴 약세 (bear)", "#b71c1c"),
}


# ──────────────────────────────────────────────────────────────
# secrets → 환경변수 (src.db는 DB_* env에서만 읽음)
# ──────────────────────────────────────────────────────────────

def _load_secrets() -> None:
    """.streamlit/secrets.toml의 DB_* 키를 환경변수로 옮긴다(이미 env면 유지)."""
    try:
        for k in ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME"):
            if k in st.secrets and not os.environ.get(k):
                os.environ[k] = str(st.secrets[k])
    except Exception:
        pass  # secrets.toml 없으면 환경변수에 의존


_load_secrets()

# src 임포트는 secrets 로드 후 (db 접속 정보 필요 시점 대비)
from src.assemble import assemble_daily          # noqa: E402
from src.compute_quant import _fetch_market_history, compute_regime  # noqa: E402
from src.db import get_conn                       # noqa: E402


# ──────────────────────────────────────────────────────────────
# 캐시된 데이터 로더 (TTL 10분)
# ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=600)
def load_records(asof_iso: str) -> list[dict]:
    """assemble_daily 결과를 dict 리스트로(캐시 직렬화 가능)."""
    with get_conn() as conn:
        records = assemble_daily(conn, asof=date.fromisoformat(asof_iso))
    return [r.model_dump() for r in records]


@st.cache_data(ttl=600)
def load_market(asof_iso: str) -> dict | None:
    """market_daily 당일 레코드. 없으면 최신 레코드."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM market_daily WHERE asof = %s", (asof_iso,))
        row = cur.fetchone()
        if not row:
            cur.execute("SELECT * FROM market_daily ORDER BY asof DESC LIMIT 1")
            row = cur.fetchone()
        return dict(row) if row else None


@st.cache_data(ttl=600)
def load_price_history(ticker: str, days: int = 180) -> pd.DataFrame:
    """최근 days일 종가 (드릴다운 차트용)."""
    cutoff = date.today() - timedelta(days=days)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT date, close FROM prices_daily WHERE ticker = %s AND date >= %s ORDER BY date ASC",
            (ticker, cutoff),
        )
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame(columns=["date", "close"])
    df = pd.DataFrame([dict(r) for r in rows])
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = df["close"].astype(float)
    return df.set_index("date")


@st.cache_data(ttl=600)
def load_regime() -> str | None:
    """compute_quant 레짐 (yfinance 호출 → 캐시). 실패 시 None."""
    try:
        return compute_regime(_fetch_market_history())
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────
# 포맷 헬퍼
# ──────────────────────────────────────────────────────────────

def _fmt(v, nd=2, suffix="") -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):,.{nd}f}{suffix}"
    except (TypeError, ValueError):
        return str(v)


def _market_delta(payload: dict, key: str) -> str | None:
    """market_daily.payload에 전일대비(chg)가 있으면 표시, 없으면 None."""
    chg = (payload or {}).get(f"{key}_chg") if isinstance(payload, dict) else None
    return _fmt(chg, 2, "%") if chg is not None else None


# ──────────────────────────────────────────────────────────────
# 메인 렌더
# ──────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(page_title="ATLAS 대시보드", page_icon="📊", layout="wide")

    asof = date.today()
    asof_iso = asof.isoformat()

    # ── 1. 상단 헤더 ──────────────────────────────────────────
    regime = load_regime()
    badge_text, badge_color = _REGIME_BADGE.get(regime, ("⚪ 레짐 미상", "#616161"))

    c1, c2 = st.columns([3, 2])
    with c1:
        st.title("📊 ATLAS")
        st.caption(f"관심종목 인텔리전스 · {asof_iso}")
    with c2:
        st.markdown(
            f"<div style='text-align:right; margin-top:18px;'>"
            f"<span style='background:{badge_color}; color:white; padding:6px 14px; "
            f"border-radius:14px; font-weight:600;'>레짐 {badge_text}</span></div>",
            unsafe_allow_html=True,
        )
    st.info(f"ℹ️ {DISCLAIMER}")

    # ── 2. 시장 스트립 ────────────────────────────────────────
    market = load_market(asof_iso)
    st.subheader("🌎 시장")
    if market:
        payload = market.get("payload") if isinstance(market.get("payload"), dict) else {}
        cards = [
            ("KOSPI", "kospi", 2), ("KOSDAQ", "kosdaq", 2),
            ("S&P500", "sp500", 2), ("NASDAQ", "nasdaq", 2),
            ("VIX", "vix", 2), ("USD/KRW", "usdkrw", 1),
        ]
        cols = st.columns(len(cards))
        for col, (label, key, nd) in zip(cols, cards):
            col.metric(label, _fmt(market.get(key), nd), _market_delta(payload, key))
    else:
        st.caption("market_daily 데이터 없음")

    # ── 3. 관심종목 표 ────────────────────────────────────────
    st.subheader("🏆 관심종목")
    records = load_records(asof_iso)
    if not records:
        st.warning("종목 데이터 없음 — 파이프라인/백필 실행 후 다시 확인하세요.")
        _footer()
        return

    df = _records_to_df(records)

    # 필터
    f1, f2 = st.columns([2, 2])
    with f1:
        markets = sorted(df["시장"].unique())
        sel_markets = st.multiselect("시장", markets, default=markets)
    with f2:
        only_holding = st.checkbox("보유 종목만", value=False)

    view = df[df["시장"].isin(sel_markets)]
    if only_holding:
        view = view[view["보유"] == "⭐"]
    view = view.sort_values("composite", ascending=False, na_position="last")

    try:
        table = _style_table(view)            # 색상 강조 (jinja2 필요)
    except Exception:
        table = view                          # Styler 불가 환경 → 평문 폴백
    st.dataframe(table, use_container_width=True, hide_index=True)
    st.caption("composite: ≥70 강함 / 55–69 보통 / <55 약함 / 필터제외=사전필터(F-Score·변동성) 대상")

    # ── 4. 드릴다운 ──────────────────────────────────────────
    st.subheader("🔎 종목 상세")
    ticker_options = view["티커"].tolist()
    if ticker_options:
        sel = st.selectbox("종목 선택", ticker_options, format_func=lambda t: _label_for(records, t))
        _drilldown(records, sel)

    _footer()


# ──────────────────────────────────────────────────────────────
# 표 빌드 / 스타일
# ──────────────────────────────────────────────────────────────

def _records_to_df(records: list[dict]) -> pd.DataFrame:
    rows = []
    for r in records:
        price = r.get("price", {})
        quant = r.get("quant", {})
        flags = quant.get("flags") or []
        rows.append({
            "보유": "⭐" if r.get("is_holding") else "",
            "종목명": r.get("name"),
            "티커": r.get("ticker"),
            "시장": r.get("market"),
            "현재가": price.get("close"),
            "등락%": price.get("chg_pct"),
            "composite": quant.get("composite"),
            "M": quant.get("momentum"),
            "V": quant.get("value"),
            "Q": quant.get("quality"),
            "G": quant.get("growth"),
            "S": quant.get("sentiment"),
            "RSI": price.get("rsi14"),
            "플래그": ", ".join(str(f) for f in flags) if flags else "",
        })
    return pd.DataFrame(rows)


def _style_table(view: pd.DataFrame):
    def _color_composite(v):
        if v is None or pd.isna(v):
            return "background-color:#424242; color:#bbb"
        if v >= 70:
            return "background-color:#1b5e20; color:white"
        if v >= 55:
            return "background-color:#f9a825; color:black"
        return "background-color:#424242; color:white"

    num_fmt = {
        "현재가": "{:,.2f}", "등락%": "{:+.2f}", "composite": "{:.0f}",
        "M": "{:.0f}", "V": "{:.0f}", "Q": "{:.0f}", "G": "{:.0f}", "S": "{:.0f}",
        "RSI": "{:.1f}",
    }
    styler = (
        view.style
        .map(_color_composite, subset=["composite"])
        .format(num_fmt, na_rep="—")
        .format({"composite": lambda v: "필터제외" if pd.isna(v) else f"{v:.0f}"})
    )
    return styler


def _label_for(records: list[dict], ticker: str) -> str:
    for r in records:
        if r.get("ticker") == ticker:
            return f"{r.get('name')} ({ticker})"
    return ticker


# ──────────────────────────────────────────────────────────────
# 드릴다운
# ──────────────────────────────────────────────────────────────

def _drilldown(records: list[dict], ticker: str) -> None:
    rec = next((r for r in records if r.get("ticker") == ticker), None)
    if not rec:
        st.caption("선택한 종목 데이터 없음")
        return

    price, fund, val = rec.get("price", {}), rec.get("fundamentals", {}), rec.get("valuation", {})
    ana, news, quant = rec.get("analyst", {}), rec.get("news", {}), rec.get("quant", {})

    left, right = st.columns([3, 2])

    # 가격 차트 + 재무/밸류/컨센서스
    with left:
        st.markdown(f"### {rec.get('name')} · {ticker}  ({rec.get('market')})")
        hist = load_price_history(ticker)
        if not hist.empty:
            st.line_chart(hist["close"], height=240)
        else:
            st.caption("가격 이력 없음")

        st.markdown("**밸류에이션 · 재무**")
        st.table(pd.DataFrame({
            "지표": ["현재가", "등락%", "Forward PER", "PBR", "ROE",
                    "매출 YoY", "영업이익률", "최근분기 매출($B)"],
            "값": [
                _fmt(price.get("close")), _fmt(price.get("chg_pct"), 2, "%"),
                _fmt(val.get("per_f")), _fmt(val.get("pbr")), _fmt(val.get("roe"), 3),
                _fmt(fund.get("rev_yoy"), 3), _fmt(fund.get("op_margin"), 3),
                _fmt(fund.get("last_q_rev_b")),
            ],
        }))

        st.markdown("**애널리스트 컨센서스**")
        st.table(pd.DataFrame({
            "항목": ["의견", "목표가", "상승여력"],
            "값": [ana.get("rating") or "—", _fmt(ana.get("target")), _fmt(ana.get("upside"), 3)],
        }))

    # 팩터 레이더 + 뉴스
    with right:
        st.markdown("**퀀트 팩터**")
        _factor_chart(quant)

        st.markdown("**뉴스 요약**")
        sent = news.get("sentiment")
        if sent:
            st.caption(f"감성: {sent} (score {_fmt(news.get('score'), 2)})")
        summary = news.get("summary_md")
        st.markdown(summary if summary else "_뉴스 분석 없음_")


def _factor_chart(quant: dict) -> None:
    factors = {"모멘텀": quant.get("momentum"), "가치": quant.get("value"),
               "퀄리티": quant.get("quality"), "성장": quant.get("growth"),
               "감성": quant.get("sentiment")}
    vals = {k: (v if v is not None else 0) for k, v in factors.items()}

    try:
        import plotly.graph_objects as go
        cats = list(vals.keys())
        data = list(vals.values())
        fig = go.Figure(go.Scatterpolar(r=data + [data[0]], theta=cats + [cats[0]], fill="toself"))
        fig.update_layout(
            polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
            showlegend=False, height=280, margin=dict(l=30, r=30, t=20, b=20),
        )
        st.plotly_chart(fig, use_container_width=True)
    except Exception:
        # plotly 미설치 시 막대 폴백
        st.bar_chart(pd.DataFrame({"점수": vals}))


def _footer() -> None:
    st.divider()
    st.caption(f"⚠️ {DISCLAIMER}")


if __name__ == "__main__":
    main()
