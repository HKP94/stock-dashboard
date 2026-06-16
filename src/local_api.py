"""
local_api.py — ATLAS 로컬 쓰기 API (FastAPI, 127.0.0.1:8765 전용)

⚠️ 절대 규칙:
  - 127.0.0.1 에만 바인딩. 외부 노출 금지.
  - CORS: http://localhost:5173 만 허용.
  - 자동 주문/매매 없음. 메타데이터·메모 쓰기만.
  - 시크릿 하드코딩 금지. DB 접속은 환경변수 또는 .streamlit/secrets.toml.
  - 투자 자문 아님 / 원금 손실 가능.

실행:
  python -m src.local_api

엔드포인트:
  GET    /api/portfolio              - 보유종목 + 최신 평가 계산
  POST   /api/portfolio              - {ticker,qty,avg_price,currency} upsert
  DELETE /api/portfolio/{ticker}     - 보유 삭제 + is_holding=false
  GET    /api/notes/{ticker}         - stock_notes 1건 또는 null
  PUT    /api/notes/{ticker}         - {horizon,attractiveness,thesis} upsert
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ── 시크릿 로드 ──────────────────────────────────────────────────
def _load_secrets() -> None:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore

    secrets_path = Path(__file__).resolve().parent.parent / ".streamlit" / "secrets.toml"
    if not secrets_path.exists():
        return
    with open(secrets_path, "rb") as f:
        s = tomllib.load(f)
    for k in ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME"):
        if k in s and not os.environ.get(k):
            os.environ[k] = str(s[k])


_load_secrets()
from src.db import get_conn  # noqa: E402
from src.compute_portfolio import compute_portfolio  # noqa: E402

# data.json 경로 (포트폴리오 갱신 시 부분 재생성)
_DATA_JSON = Path(__file__).resolve().parent.parent / "dashboard-web" / "src" / "data.json"

# ── FastAPI 앱 ────────────────────────────────────────────────────
app = FastAPI(title="ATLAS Local API", docs_url="/docs")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type"],
)


# ── Pydantic 모델 ─────────────────────────────────────────────────
class PortfolioIn(BaseModel):
    ticker: str
    qty: float = Field(..., ge=0)
    avg_price: float = Field(..., ge=0)
    currency: str = "KRW"


class NoteIn(BaseModel):
    horizon: Optional[str] = None      # 'short' | 'long' | 'watch'
    attractiveness: Optional[int] = None  # 1~5
    thesis: Optional[str] = None


class CashIn(BaseModel):
    currency: str = "KRW"              # 'KRW' | 'USD'
    amount: float = Field(..., ge=0)


class WatchlistIn(BaseModel):
    ticker: str
    name: str
    market: str = "US"                 # 'US' | 'KR'
    sector: Optional[str] = None


class WatchlistPatch(BaseModel):
    active: bool


class ResearchIn(BaseModel):
    ticker: str
    item_type: str                     # 'youtube'|'article'|'report'|'quant'|'memo'
    title: str
    url: Optional[str] = None
    note: Optional[str] = None


# ── 헬퍼 ──────────────────────────────────────────────────────────
def _latest_price(ticker: str) -> Optional[float]:
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT close FROM prices_daily WHERE ticker=%s AND close IS NOT NULL ORDER BY date DESC LIMIT 1",
            (ticker,),
        )
        r = c.fetchone()
    return float(r["close"]) if r else None


def _patch_data_json_portfolio() -> None:
    """data.json의 portfolio 필드만 부분 갱신."""
    if not _DATA_JSON.exists():
        return
    try:
        with open(_DATA_JSON, encoding="utf-8") as f:
            data = json.load(f)

        with get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT total_value, total_cost, total_pnl, payload FROM portfolio_snapshot ORDER BY asof DESC LIMIT 1")
            r = c.fetchone()
            if r:
                payload = r["payload"] or {}
                data["portfolio"] = {
                    "total_eval":    float(r["total_value"]) if r["total_value"] else None,
                    "total_cost":    float(r["total_cost"])  if r["total_cost"]  else None,
                    "total_pnl":     float(r["total_pnl"])   if r["total_pnl"]   else None,
                    "total_pnl_pct": payload.get("pnl_pct"),
                    "n_holdings":    payload.get("n_holdings"),
                    "currency":      "KRW",
                    "fx_rate":       payload.get("fx_rate"),
                    "fx_missing":    payload.get("fx_missing", False),
                    "by_currency":   payload.get("by_currency", {}),
                    "cash_total":    payload.get("cash_total", 0),       # PR-2
                    "asset_total":   payload.get("asset_total"),         # PR-2
                    "cash_by_currency": payload.get("cash_by_currency", {}),
                }
            # holding 필드도 갱신
            c.execute("SELECT ticker, qty, avg_price, currency FROM portfolio_holdings WHERE qty > 0")
            holdings = {row["ticker"]: dict(row) for row in c.fetchall()}
            c.execute("SELECT p.ticker, p.cur_price, p.eval_amount, p.pnl, p.pnl_pct FROM portfolio p WHERE p.asof=(SELECT max(asof) FROM portfolio p2 WHERE p2.ticker=p.ticker)")
            eval_map = {row["ticker"]: dict(row) for row in c.fetchall()}

        for s in data.get("stocks", []):
            tk = s["t"]
            h = holdings.get(tk)
            ev = eval_map.get(tk)
            if h:
                s["hold"] = True
                s["holding"] = {
                    "qty":         float(h["qty"]),
                    "avg_price":   float(h["avg_price"]),
                    "cur_price":   float(ev["cur_price"]) if ev and ev.get("cur_price") else s.get("price"),
                    "eval_amount": float(ev["eval_amount"]) if ev and ev.get("eval_amount") else None,
                    "pnl":         float(ev["pnl"]) if ev and ev.get("pnl") else None,
                    "pnl_pct":     float(ev["pnl_pct"]) if ev and ev.get("pnl_pct") else None,
                    "currency":    h["currency"],
                }
            else:
                s["holding"] = None

        with open(_DATA_JSON, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        logger.info("data.json 포트폴리오 부분 갱신 완료")
    except Exception as exc:
        logger.warning("data.json 부분 갱신 실패: %s", exc)


def _patch_data_json_note(ticker: str, note_data: dict) -> None:
    """data.json의 해당 종목 notes 필드만 갱신."""
    if not _DATA_JSON.exists():
        return
    try:
        with open(_DATA_JSON, encoding="utf-8") as f:
            data = json.load(f)
        for s in data.get("stocks", []):
            if s["t"] == ticker:
                s["note"] = note_data
                break
        with open(_DATA_JSON, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    except Exception as exc:
        logger.warning("data.json note 갱신 실패: %s", exc)


def _fetch_research_items(ticker: str) -> list[dict]:
    """해당 종목 research_items를 export(_load_research_items)와 동일 형태로 반환."""
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, item_type, title, url, note, added_at FROM research_items WHERE ticker=%s ORDER BY added_at DESC",
            (ticker,),
        )
        return [{
            "id": r["id"], "type": r["item_type"], "title": r["title"],
            "url": r["url"] or "", "note": r["note"] or "", "addedAt": str(r["added_at"])[:10],
        } for r in c.fetchall()]


def _patch_data_json_research(ticker: str) -> None:
    """data.json의 해당 종목 researchItems만 재조회로 갱신(전체 재생성 회피)."""
    if not _DATA_JSON.exists():
        return
    try:
        items = _fetch_research_items(ticker)
        with open(_DATA_JSON, encoding="utf-8") as f:
            data = json.load(f)
        for s in data.get("stocks", []):
            if s["t"] == ticker:
                s["researchItems"] = items
                break
        with open(_DATA_JSON, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    except Exception as exc:
        logger.warning("data.json research 갱신 실패: %s", exc)


# ── 포트폴리오 엔드포인트 ────────────────────────────────────────

@app.get("/api/portfolio")
def get_portfolio():
    """보유종목 목록 + 최신 평가 계산."""
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT ticker, qty, avg_price, currency FROM portfolio_holdings WHERE qty > 0 ORDER BY ticker")
        holdings = [dict(r) for r in c.fetchall()]

    result = []
    for h in holdings:
        cur_price = _latest_price(h["ticker"])
        qty = float(h["qty"])
        avg = float(h["avg_price"])
        eval_amt = qty * cur_price if cur_price else None
        pnl = (eval_amt - qty * avg) if eval_amt is not None else None
        pnl_pct = (pnl / (qty * avg) * 100) if pnl is not None and avg > 0 else None
        result.append({
            "ticker":      h["ticker"],
            "qty":         qty,
            "avg_price":   avg,
            "currency":    h["currency"],
            "cur_price":   cur_price,
            "eval_amount": eval_amt,
            "pnl":         pnl,
            "pnl_pct":     round(pnl_pct, 2) if pnl_pct is not None else None,
        })
    return result


@app.post("/api/portfolio", status_code=201)
def upsert_portfolio(body: PortfolioIn):
    """보유종목 upsert → compute_portfolio → data.json 부분 갱신."""
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            """INSERT INTO portfolio_holdings (ticker, qty, avg_price, currency, updated_at)
               VALUES (%s,%s,%s,%s,now())
               ON CONFLICT (ticker) DO UPDATE SET
                 qty=EXCLUDED.qty, avg_price=EXCLUDED.avg_price,
                 currency=EXCLUDED.currency, updated_at=now()""",
            (body.ticker, body.qty, body.avg_price, body.currency),
        )
        c.execute("UPDATE watchlist SET is_holding=true WHERE ticker=%s", (body.ticker,))
        conn.commit()
        compute_portfolio(conn)
    _patch_data_json_portfolio()
    return {"ok": True, "ticker": body.ticker}


@app.delete("/api/portfolio/{ticker}", status_code=200)
def delete_portfolio(ticker: str):
    """보유종목 삭제 → is_holding=false → data.json 갱신."""
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM portfolio_holdings WHERE ticker=%s", (ticker,))
        c.execute("UPDATE watchlist SET is_holding=false WHERE ticker=%s", (ticker,))
        conn.commit()
        compute_portfolio(conn)
    _patch_data_json_portfolio()
    return {"ok": True, "ticker": ticker}


# ── 현금 엔드포인트 (PR-2) ───────────────────────────────────────

@app.get("/api/cash")
def get_cash():
    """통화별 현금 목록."""
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT currency, amount FROM portfolio_cash ORDER BY currency")
        return [{"currency": r["currency"], "amount": float(r["amount"])} for r in c.fetchall()]


@app.put("/api/cash", status_code=200)
def upsert_cash(body: CashIn):
    """통화별 현금 upsert(amount=0이면 행 삭제) → compute_portfolio → data.json 갱신."""
    ccy = body.currency.upper()
    with get_conn() as conn:
        c = conn.cursor()
        if body.amount == 0:
            c.execute("DELETE FROM portfolio_cash WHERE currency=%s", (ccy,))
        else:
            c.execute(
                """INSERT INTO portfolio_cash (currency, amount, updated_at)
                   VALUES (%s,%s,now())
                   ON CONFLICT (currency) DO UPDATE SET amount=EXCLUDED.amount, updated_at=now()""",
                (ccy, body.amount),
            )
        conn.commit()
        compute_portfolio(conn)
    _patch_data_json_portfolio()
    return {"ok": True, "currency": ccy, "amount": body.amount}


# ── 투자 판단 메모 엔드포인트 ────────────────────────────────────

@app.get("/api/notes/{ticker}")
def get_note(ticker: str):
    """stock_notes 1건 반환. 없으면 null."""
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT ticker, horizon, attractiveness, thesis, updated_at FROM stock_notes WHERE ticker=%s", (ticker,))
        r = c.fetchone()
    if not r:
        return None
    return {
        "ticker":        r["ticker"],
        "horizon":       r["horizon"],
        "attractiveness": r["attractiveness"],
        "thesis":        r["thesis"],
        "updated_at":    str(r["updated_at"]),
    }


@app.put("/api/notes/{ticker}", status_code=200)
def upsert_note(ticker: str, body: NoteIn):
    """투자 판단 메모 upsert → data.json 해당 종목 note 필드 갱신."""
    if body.horizon and body.horizon not in ("short", "long", "watch"):
        raise HTTPException(400, "horizon must be short|long|watch")
    if body.attractiveness is not None and not (1 <= body.attractiveness <= 5):
        raise HTTPException(400, "attractiveness must be 1~5")

    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            """INSERT INTO stock_notes (ticker, horizon, attractiveness, thesis, updated_at)
               VALUES (%s,%s,%s,%s,now())
               ON CONFLICT (ticker) DO UPDATE SET
                 horizon=EXCLUDED.horizon,
                 attractiveness=EXCLUDED.attractiveness,
                 thesis=EXCLUDED.thesis,
                 updated_at=now()""",
            (ticker, body.horizon, body.attractiveness, body.thesis),
        )
        conn.commit()

    note_data = {"horizon": body.horizon, "attractiveness": body.attractiveness, "thesis": body.thesis}
    _patch_data_json_note(ticker, note_data)
    return {"ok": True, "ticker": ticker}


# ── 리서치 항목 엔드포인트 (PR-2) ───────────────────────────────────

_RESEARCH_TYPES = ("youtube", "article", "report", "quant", "memo")


@app.get("/api/research/{ticker}")
def get_research(ticker: str):
    """해당 종목 research_items 목록."""
    return _fetch_research_items(ticker)


@app.post("/api/research", status_code=201)
def add_research(body: ResearchIn):
    """리서치 항목 추가 → data.json 해당 종목 researchItems 갱신."""
    if body.item_type not in _RESEARCH_TYPES:
        raise HTTPException(400, f"item_type must be one of {_RESEARCH_TYPES}")
    if not body.title.strip():
        raise HTTPException(400, "title required")
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            """INSERT INTO research_items (ticker, item_type, title, url, note)
               VALUES (%s,%s,%s,%s,%s) RETURNING id""",
            (body.ticker, body.item_type, body.title.strip(), body.url, body.note),
        )
        new_id = c.fetchone()["id"]
        conn.commit()
    _patch_data_json_research(body.ticker)
    return {"ok": True, "id": new_id, "ticker": body.ticker}


@app.delete("/api/research/{item_id}", status_code=200)
def delete_research(item_id: int):
    """리서치 항목 삭제 → 해당 종목 researchItems 갱신."""
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM research_items WHERE id=%s RETURNING ticker", (item_id,))
        row = c.fetchone()
        conn.commit()
    if not row:
        raise HTTPException(404, "research item not found")
    _patch_data_json_research(row["ticker"])
    return {"ok": True, "id": item_id, "ticker": row["ticker"]}


# ── 관심종목(watchlist) 관리 엔드포인트 (PR-3) ──────────────────

def _regenerate_data_json() -> None:
    """data.json 전체 재생성(신규 종목이 랭킹에 등장하도록)."""
    try:
        from src.export_dashboard_data import build_data
        data = build_data()
        if _DATA_JSON.parent.exists():
            with open(_DATA_JSON, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            logger.info("data.json 전체 재생성 완료")
    except Exception as exc:
        logger.warning("data.json 재생성 실패: %s", exc)


def _backfill_and_export(ticker: str, market: str) -> None:
    """백그라운드: 단일 종목 백필 → data.json 재생성."""
    try:
        from src.backfill import backfill_single
        backfill_single(ticker, market)
    except Exception as exc:
        logger.warning("백그라운드 백필 실패 %s: %s", ticker, exc)
    _regenerate_data_json()


@app.get("/api/watchlist")
def get_watchlist():
    """관심종목 전체(active 포함). 각 종목의 가격 데이터 유무(hasData)도 표시."""
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT w.ticker, w.name, w.market, w.sector, w.is_holding, w.active,
                   EXISTS(SELECT 1 FROM prices_daily p WHERE p.ticker=w.ticker) AS has_data
            FROM watchlist w ORDER BY w.active DESC, w.market, w.ticker
        """)
        return [dict(r) for r in c.fetchall()]


@app.post("/api/watchlist", status_code=201)
def add_watchlist(body: WatchlistIn, background: BackgroundTasks):
    """관심종목 추가 → 백그라운드로 해당 종목만 백필(가격+지표+퀀트) → data.json 재생성."""
    ticker = body.ticker.strip()
    market = body.market.upper()
    if market not in ("US", "KR"):
        raise HTTPException(400, "market must be US or KR")
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT 1 FROM watchlist WHERE ticker=%s", (ticker,))
        if c.fetchone():
            # 이미 있으면 active=true로 되살림
            c.execute("UPDATE watchlist SET active=true WHERE ticker=%s", (ticker,))
            conn.commit()
            existed = True
        else:
            c.execute(
                """INSERT INTO watchlist (ticker, name, market, sector, is_holding, active, added_at)
                   VALUES (%s,%s,%s,%s,false,true,now())""",
                (ticker, body.name.strip(), market, (body.sector or "").strip() or None),
            )
            conn.commit()
            existed = False
    background.add_task(_backfill_and_export, ticker, market)
    return {"ok": True, "ticker": ticker, "status": "collecting", "existed": existed}


@app.patch("/api/watchlist/{ticker}", status_code=200)
def patch_watchlist(ticker: str, body: WatchlistPatch):
    """active 토글(관심 제외=active false, 데이터 보존). 변경 후 data.json 재생성."""
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("UPDATE watchlist SET active=%s WHERE ticker=%s", (body.active, ticker))
        if c.rowcount == 0:
            raise HTTPException(404, "ticker not found")
        conn.commit()
    _regenerate_data_json()
    return {"ok": True, "ticker": ticker, "active": body.active}


# ── 실행 ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    print("⚠️  투자 자문 아님 / 원금 손실 가능")
    print("ATLAS Local API — http://127.0.0.1:8765/docs")
    uvicorn.run("src.local_api:app", host="127.0.0.1", port=8765, reload=True)
