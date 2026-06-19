"""
watchlist_admin.py — SQL 없이 watchlist 테이블 관리하는 Streamlit 관리 도구.

실행: streamlit run dashboard/watchlist_admin.py
React 메인 대시보드와 별개로, 필요할 때만 실행한다.
시크릿: .streamlit/secrets.toml (DB_* 키) 또는 환경변수 DB_*.

절대규칙: 자동 주문 없음, 시크릿 하드코딩 없음, 읽기·메타데이터 변경만 허용.
"""
import os
import sys

import streamlit as st

# 프로젝트 루트를 sys.path에 추가 (src 임포트 위해)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _load_db_secrets() -> None:
    """DB_* 환경변수를 secrets.toml에서 채운다."""
    try:
        for k in ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME"):
            if k in st.secrets and not os.environ.get(k):
                os.environ[k] = str(st.secrets[k])
    except Exception:
        pass


_load_db_secrets()
from src.db import get_conn  # noqa: E402 (secrets 로드 후)

# ── 헬퍼 ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=30)
def _load_watchlist() -> list[dict]:
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT ticker, name, market, sector, is_holding, active FROM watchlist ORDER BY market, ticker")
        return [dict(r) for r in c.fetchall()]


def _reload():
    _load_watchlist.clear()
    st.rerun()


# ── 레이아웃 ──────────────────────────────────────────────────────────
st.set_page_config(page_title="ATLAS Watchlist 관리", layout="wide")
st.title("ATLAS — Watchlist 관리 도구")
st.caption("이 도구는 관심종목 메타데이터만 변경하며 주문을 실행하지 않습니다.")

rows = _load_watchlist()

# ── 현재 watchlist 테이블 ─────────────────────────────────────────────
st.subheader(f"현재 관심종목 ({len(rows)}개)")

col_h, col_t, col_h2 = st.columns([3, 1, 1])
with col_t:
    filter_market = st.selectbox("시장", ["전체", "KR", "US"], label_visibility="collapsed")
with col_h2:
    filter_active = st.selectbox("상태", ["전체", "활성", "비활성"], label_visibility="collapsed")

filtered = rows
if filter_market != "전체":
    filtered = [r for r in filtered if r["market"] == filter_market]
if filter_active == "활성":
    filtered = [r for r in filtered if r["active"]]
elif filter_active == "비활성":
    filtered = [r for r in filtered if not r["active"]]

for r in filtered:
    c1, c2, c3, c4, c5, c6 = st.columns([2, 2, 1, 2, 1, 1])
    with c1:
        st.write(f"**{r['ticker']}**")
    with c2:
        st.write(r["name"] or "—")
    with c3:
        st.write(r["market"])
    with c4:
        st.write(r["sector"] or "—")
    with c5:
        # is_holding 토글
        new_hold = st.toggle("보유", value=bool(r["is_holding"]), key=f"hold_{r['ticker']}")
        if new_hold != bool(r["is_holding"]):
            with get_conn() as conn:
                conn.cursor().execute("UPDATE watchlist SET is_holding=%s WHERE ticker=%s", (new_hold, r["ticker"]))
                conn.commit()
            _reload()
    with c6:
        # active 토글 (삭제 대신)
        new_active = st.toggle("활성", value=bool(r["active"]), key=f"active_{r['ticker']}")
        if new_active != bool(r["active"]):
            with get_conn() as conn:
                conn.cursor().execute("UPDATE watchlist SET active=%s WHERE ticker=%s", (new_active, r["ticker"]))
                conn.commit()
            _reload()

st.divider()

# ── 종목 추가 폼 ──────────────────────────────────────────────────────
st.subheader("종목 추가")
with st.form("add_stock"):
    a1, a2, a3, a4 = st.columns(4)
    with a1:
        new_ticker = st.text_input("Ticker", placeholder="e.g. AAPL or 005930.KS")
    with a2:
        new_name = st.text_input("종목명", placeholder="e.g. 애플")
    with a3:
        new_market = st.selectbox("시장", ["US", "KR"])
    with a4:
        new_sector = st.text_input("섹터", placeholder="e.g. 반도체")
    submitted = st.form_submit_button("추가")
    if submitted:
        if not new_ticker or not new_name:
            st.error("ticker와 종목명은 필수입니다.")
        elif any(r["ticker"] == new_ticker.strip() for r in rows):
            st.warning(f"{new_ticker} 이미 존재합니다.")
        else:
            with get_conn() as conn:
                conn.cursor().execute(
                    "INSERT INTO watchlist (ticker, name, market, sector, is_holding, active) VALUES (%s,%s,%s,%s,false,true)",
                    (new_ticker.strip(), new_name.strip(), new_market, new_sector.strip() or None),
                )
                conn.commit()
            st.success(f"{new_ticker} 추가됨")
            _reload()

st.divider()
st.caption("비활성화 토글은 종목을 삭제하지 않고 active=false로 설정해 이력을 보존합니다.")

# 보유종목 관리는 src/local_api.py (FastAPI POST/DELETE /api/portfolio) 로 이전됨.
# 실행: python -m src.local_api

# ══ 리서치 항목 관리 ══════════════════════════════════════════════════════
st.divider()
st.subheader("리서치 항목 관리")
st.caption("유튜브·기사·리포트·퀀트분석·메모를 종목별로 저장합니다.")


@st.cache_data(ttl=30)
def _load_research_items_db() -> list[dict]:
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, ticker, item_type, title, url, note, added_at FROM research_items ORDER BY ticker, added_at DESC"
        )
        return [dict(r) for r in c.fetchall()]


def _reload_research():
    _load_research_items_db.clear()
    st.rerun()


r_items = _load_research_items_db()

# 종목 선택 필터
r_tickers = sorted({r["ticker"] for r in r_items}) if r_items else []
ri_filter = st.selectbox("종목 선택 (리서치 보기)", ["전체"] + r_tickers)
ri_show = r_items if ri_filter == "전체" else [r for r in r_items if r["ticker"] == ri_filter]

for ri in ri_show:
    rc1, rc2, rc3, rc4 = st.columns([1, 1, 3, 1])
    with rc1:
        st.write(f"**{ri['ticker']}**")
    with rc2:
        st.write(f"`{ri['item_type']}`")
    with rc3:
        if ri["url"]:
            st.markdown(f"[{ri['title']}]({ri['url']})")
        else:
            st.write(ri["title"])
        if ri["note"]:
            st.caption(ri["note"][:100])
    with rc4:
        if st.button("삭제", key=f"ri_del_{ri['id']}"):
            with get_conn() as conn:
                conn.cursor().execute("DELETE FROM research_items WHERE id=%s", (ri["id"],))
                conn.commit()
            _reload_research()

st.write("")
with st.form("add_research_item"):
    st.write("**항목 추가**")
    ri1, ri2 = st.columns(2)
    with ri1:
        ri_ticker = st.selectbox("종목", [r["ticker"] for r in rows])
        ri_type = st.selectbox("유형", ["youtube", "article", "report", "quant", "memo"])
    with ri2:
        ri_title = st.text_input("제목")
        ri_url = st.text_input("URL (메모는 선택)")
    ri_note = st.text_area("노트", height=80)
    ri_submitted = st.form_submit_button("저장")
    if ri_submitted:
        if not ri_title:
            st.error("제목은 필수입니다.")
        else:
            with get_conn() as conn:
                conn.cursor().execute(
                    "INSERT INTO research_items (ticker, item_type, title, url, note) VALUES (%s,%s,%s,%s,%s)",
                    (ri_ticker, ri_type, ri_title, ri_url or None, ri_note or None),
                )
                conn.commit()
            st.success(f"저장됨: [{ri_type}] {ri_title}")
            _reload_research()
