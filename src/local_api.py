"""
local_api.py — ATLAS 로컬 쓰기 API (FastAPI, 127.0.0.1:8765 전용)

⚠️ 절대 규칙:
  - 127.0.0.1 에만 바인딩. 외부 노출 금지.
  - CORS: http://localhost:5173 만 허용.
  - 자동 주문/매매 없음. 메타데이터·메모 쓰기만.
  - 시크릿 하드코딩 금지. DB 접속은 환경변수 또는 .streamlit/secrets.toml.

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

import hashlib
import json
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, model_validator

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
from src.db import insert_manual_research_entry, insert_market_view_manual, replace_manual_research_ai_rows  # noqa: E402
from src.enrich_gemini import (  # noqa: E402
    _build_manual_research_prompt,
    _build_market_manual_prompt,
    _call_gemini_with_backoff,
    _get_gemini_client,
    _get_manual_research_model,
    _parse_manual_research_output,
    _parse_market_manual_output,
)
from src.ingest_drivers import auto_map_ticker_drivers  # noqa: E402
from src.schemas import (  # noqa: E402
    ManualResearchConsensusRow,
    ManualResearchEntryRow,
    ManualResearchHorizonRow,
    ManualResearchPointRow,
    MarketViewManualRow,
)

# data.json 경로 (포트폴리오 갱신 시 부분 재생성)
_DATA_JSON = Path(__file__).resolve().parent.parent / "dashboard-web" / "src" / "data.json"

# ── FastAPI 앱 ────────────────────────────────────────────────────
app = FastAPI(title="ATLAS Local API", docs_url="/docs")

app.add_middleware(
    CORSMiddleware,
    # localhost·127.0.0.1 둘 다 허용(KPH가 어느 쪽으로 열든 폴링 되게). 여전히 로컬 전용.
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    # PATCH 누락 시 watchlist active 토글 프리플라이트(OPTIONS)가 400으로 막혀 토글 무반응 → PATCH·OPTIONS 포함
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@app.get("/api/data")
def get_data():
    """현재 `data.json` 파일 내용을 그대로 반환 — 열린 대시보드가 주기 폴링해 새 데이터를 자동
    반영하게 한다(수동 새로고침 불필요). 파일은 local_refresh(하루 2회 export)가 갱신한다.
    127.0.0.1 전용·읽기 전용(자동수집 데이터 미변경)."""
    if not _DATA_JSON.exists():
        return JSONResponse({"error": "data.json 없음"}, status_code=404)
    return FileResponse(_DATA_JSON, media_type="application/json")


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
    active: Optional[bool] = None
    sector: Optional[str] = None

    @model_validator(mode="after")
    def require_change(self) -> "WatchlistPatch":
        if not ({"active", "sector"} & self.model_fields_set):
            raise ValueError("active or sector is required")
        return self


class WatchlistCorrectIn(BaseModel):
    """티커/국가 오타 정정 입력. 정정은 '잘못된 종목 비활성 + 올바른 종목 추가'로 처리한다
    (티커는 사실상 모든 테이블의 키라 단순 UPDATE 시 데이터 정합성이 깨지므로 제거+추가)."""
    ticker: str                       # 새(올바른) 티커
    market: str                       # 'KR' | 'US'
    name: Optional[str] = None        # 없으면 기존 종목명 승계
    sector: Optional[str] = None      # 없으면 기존 섹터 승계


class ResearchIn(BaseModel):
    ticker: str
    item_type: str                     # 'youtube'|'article'|'report'|'quant'|'memo'
    title: str
    url: Optional[str] = None
    note: Optional[str] = None


class DriverIn(BaseModel):
    ticker: str
    driver_code: str
    driver_name: str
    driver_source: str
    weight: int = Field(..., ge=1, le=5)
    rationale: str = ""
    origin: str = "user"


class DriverPatch(BaseModel):
    weight: Optional[int] = Field(default=None, ge=1, le=5)
    rationale: Optional[str] = None

    @model_validator(mode="after")
    def require_change(self) -> "DriverPatch":
        if not ({"weight", "rationale"} & self.model_fields_set):
            raise ValueError("weight or rationale is required")
        return self


class ManualResearchIn(BaseModel):
    ticker: str
    raw_text: str = Field(..., min_length=1)
    source: Optional[str] = None
    source_url: Optional[str] = None


class ManualResearchPatch(BaseModel):
    raw_text: Optional[str] = None
    source: Optional[str] = None
    source_url: Optional[str] = None
    inferred_source: Optional[str] = None

    @model_validator(mode="after")
    def require_change(self) -> "ManualResearchPatch":
        if not ({"raw_text", "source", "source_url", "inferred_source"} & self.model_fields_set):
            raise ValueError("raw_text, source, source_url, or inferred_source is required")
        return self


class MarketManualIn(BaseModel):
    asof: str
    raw_text: str = Field(..., min_length=1)
    source: Optional[str] = None
    source_url: Optional[str] = None


class MarketManualPatch(BaseModel):
    raw_text: Optional[str] = None
    source: Optional[str] = None
    source_url: Optional[str] = None
    bull_scenario: Optional[str] = None
    bear_scenario: Optional[str] = None

    @model_validator(mode="after")
    def require_change(self) -> "MarketManualPatch":
        if not ({"raw_text", "source", "source_url", "bull_scenario", "bear_scenario"} & self.model_fields_set):
            raise ValueError("raw_text, source, source_url, bull_scenario, or bear_scenario is required")
        return self


class ManualResearchHorizonPatch(BaseModel):
    attractiveness_label: Optional[str] = None
    rationale: Optional[str] = None

    @model_validator(mode="after")
    def require_change(self) -> "ManualResearchHorizonPatch":
        if not ({"attractiveness_label", "rationale"} & self.model_fields_set):
            raise ValueError("attractiveness_label or rationale is required")
        return self


class ManualResearchPointIn(BaseModel):
    stance: str
    point: str = Field(..., min_length=1)
    source_label: Optional[str] = None
    source_url: Optional[str] = None


class ManualResearchPointPatch(BaseModel):
    stance: Optional[str] = None
    point: Optional[str] = None
    source_label: Optional[str] = None
    source_url: Optional[str] = None

    @model_validator(mode="after")
    def require_change(self) -> "ManualResearchPointPatch":
        if not ({"stance", "point", "source_label", "source_url"} & self.model_fields_set):
            raise ValueError("stance, point, source_label, or source_url is required")
        return self


class ManualResearchConsensusPatch(BaseModel):
    target_price: Optional[float] = None
    rating_label: Optional[str] = None
    rating_score: Optional[float] = None

    @model_validator(mode="after")
    def require_change(self) -> "ManualResearchConsensusPatch":
        if not ({"target_price", "rating_label", "rating_score"} & self.model_fields_set):
            raise ValueError("target_price, rating_label, or rating_score is required")
        return self


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


def _as_float(value: object) -> Optional[float]:
    return float(value) if value is not None else None


def _portfolio_snapshot_payload(row: dict) -> dict:
    payload = row.get("payload") or {}
    return {
        "total_eval": _as_float(row.get("total_value")),
        "total_cost": _as_float(row.get("total_cost")),
        "total_pnl": _as_float(row.get("total_pnl")),
        "total_pnl_pct": _as_float(payload.get("pnl_pct")),
        "n_holdings": payload.get("n_holdings"),
        "currency": "KRW",
        "fx_rate": _as_float(payload.get("fx_rate")),
        "fx_missing": payload.get("fx_missing", False),
        "by_currency": payload.get("by_currency", {}),
        "cash_total": _as_float(payload.get("cash_total")) or 0.0,
        "asset_total": _as_float(payload.get("asset_total")),
        "cash_by_currency": payload.get("cash_by_currency", {}),
    }


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
                data["portfolio"] = _portfolio_snapshot_payload(dict(r))
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


def _patch_data_json_note(ticker: str, note_data: dict | None) -> None:
    """data.json의 해당 종목 note/noteHistory 필드 갱신. note_data=None이면 삭제 상태로 클리어."""
    if not _DATA_JSON.exists():
        return
    try:
        with open(_DATA_JSON, encoding="utf-8") as f:
            data = json.load(f)
        for s in data.get("stocks", []):
            if s["t"] == ticker:
                s["note"] = note_data
                s["noteHistory"] = [] if note_data is None else _fetch_note_history(ticker)
                break
        with open(_DATA_JSON, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    except Exception as exc:
        logger.warning("data.json note 갱신 실패: %s", exc)


def _fetch_note_history(ticker: str) -> list[dict]:
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, horizon, attractiveness, thesis, created_at "
            "FROM stock_note_history WHERE ticker=%s AND active=TRUE ORDER BY created_at DESC, id DESC",
            (ticker,),
        )
        return [
            {
                "id": row["id"],
                "horizon": row["horizon"],
                "attractiveness": row["attractiveness"],
                "thesis": row["thesis"],
                "created_at": str(row["created_at"]),
            }
            for row in cursor.fetchall()
        ]


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


def _raw_text_meta(text: str) -> dict[str, object]:
    normalized = text.strip()
    return {
        "length": len(normalized),
        "sha256_12": hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12],
    }


def _manual_research_summary(entry: dict | None) -> dict | None:
    if not entry:
        return None
    labels = {item["horizon"]: item["attractivenessLabel"] for item in entry.get("horizons") or []}
    return {
        "entryId": entry["id"],
        "labels": labels,
        "bullCount": len(entry.get("bull") or []),
        "bearCount": len(entry.get("bear") or []),
    }


def _fetch_watchlist_meta(ticker: str) -> tuple[str | None, str | None]:
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name, market FROM watchlist WHERE ticker=%s", (ticker,))
        row = cursor.fetchone()
    if not row:
        return None, None
    return row["name"], row["market"]


def _call_manual_research_decomposition(*, ticker: str, raw_text: str, source: str | None, source_url: str | None):
    company_name, _market = _fetch_watchlist_meta(ticker)
    if not company_name:
        raise HTTPException(404, "ticker not found")
    prompt = _build_manual_research_prompt(
        ticker=ticker,
        company_name=company_name,
        raw_text=raw_text,
        source=source,
        source_url=source_url,
    )
    client = _get_gemini_client()
    text = _call_gemini_with_backoff(client, _get_manual_research_model(), prompt)
    return _parse_manual_research_output(text)


def _call_market_manual_decomposition(*, raw_text: str, source: str | None, source_url: str | None, asof: str):
    prompt = _build_market_manual_prompt(
        raw_text=raw_text,
        source=source,
        source_url=source_url,
        asof=asof,
    )
    client = _get_gemini_client()
    text = _call_gemini_with_backoff(client, _get_manual_research_model(), prompt)
    return _parse_market_manual_output(text)


def _replace_manual_research_entry_ai(conn, entry_id: int, parsed) -> None:
    horizons = [
        ManualResearchHorizonRow(
            entry_id=entry_id,
            horizon=item.horizon,
            attractiveness_label=item.attractivenessLabel,
            rationale=item.rationale,
            is_user_confirmed=False,
        )
        for item in parsed.horizons
    ]
    points = [
        ManualResearchPointRow(
            entry_id=entry_id,
            stance="bull",
            point=item.point,
            source_label=item.sourceLabel,
            source_url=item.sourceUrl,
            is_user_confirmed=False,
        )
        for item in parsed.bull_points
    ] + [
        ManualResearchPointRow(
            entry_id=entry_id,
            stance="bear",
            point=item.point,
            source_label=item.sourceLabel,
            source_url=item.sourceUrl,
            is_user_confirmed=False,
        )
        for item in parsed.bear_points
    ]
    consensus = None
    if parsed.consensus:
        consensus = ManualResearchConsensusRow(
            entry_id=entry_id,
            target_price=parsed.consensus.targetPrice,
            rating_label=parsed.consensus.ratingLabel,
            rating_score=parsed.consensus.ratingScore,
            is_user_confirmed=False,
        )
    replace_manual_research_ai_rows(conn, entry_id, horizons=horizons, points=points, consensus=consensus)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE manual_research_entries SET inferred_source=%s, updated_at=now() WHERE id=%s",
        (parsed.inferredSource, entry_id),
    )
    conn.commit()


def _fetch_manual_research_payload(ticker: str) -> dict:
    from src.export_dashboard_data import _load_manual_research_history

    with get_conn() as conn:
        entries = _load_manual_research_history(conn, [ticker], limit_per_ticker=10).get(ticker, [])
    latest = entries[0] if entries else None
    return {
        "ticker": ticker,
        "latest": latest,
        "history": entries,
        "summary": _manual_research_summary(latest),
    }


def _fetch_market_manual_payload() -> dict:
    from src.export_dashboard_data import _load_market_manual_views

    with get_conn() as conn:
        items = _load_market_manual_views(conn, limit=10)
    return {
        "latest": items[0] if items else None,
        "history": items,
    }


def _patch_manual_research_entry(conn, entry_id: int, body: ManualResearchPatch) -> dict:
    fields = body.model_fields_set
    raw_text = body.raw_text.strip() if body.raw_text is not None else None
    source = (body.source or "").strip() or None if "source" in fields else None
    source_url = (body.source_url or "").strip() or None if "source_url" in fields else None
    inferred_source = (body.inferred_source or "").strip() or None if "inferred_source" in fields else None
    needs_redecomposition = "raw_text" in fields
    cursor = conn.cursor()
    try:
        sets: list[str] = []
        params: list[object] = []
        if "raw_text" in fields:
            sets.append("raw_text=%s")
            params.append(raw_text)
        if "source" in fields:
            sets.append("source=%s")
            params.append(source)
        if "source_url" in fields:
            sets.append("source_url=%s")
            params.append(source_url)
        if "inferred_source" in fields:
            sets.append("inferred_source=%s")
            params.append(inferred_source)
        params.append(entry_id)
        cursor.execute(
            f"UPDATE manual_research_entries SET {', '.join(sets)}, updated_at=now() WHERE id=%s",
            tuple(params),
        )
        if cursor.rowcount == 0:
            raise HTTPException(404, "manual research entry not found")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    if needs_redecomposition and raw_text is not None:
        meta = _raw_text_meta(raw_text)
        logger.info("manual_research raw_text updated entry_id=%s len=%s sha=%s", entry_id, meta["length"], meta["sha256_12"])
    return {
        "raw_text": raw_text if "raw_text" in fields else None,
        "source": source,
        "source_url": source_url,
        "inferred_source": inferred_source,
        "needs_redecomposition": needs_redecomposition,
    }


def _patch_manual_research_horizon(conn, entry_id: int, horizon: str, body: ManualResearchHorizonPatch) -> dict:
    if horizon not in {"short", "mid", "long"}:
        raise HTTPException(400, "horizon must be short|mid|long")
    fields = body.model_fields_set
    sets: list[str] = ["is_user_confirmed=TRUE", "updated_at=now()"]
    params: list[object] = []
    changed: dict[str, object] = {}
    if "attractiveness_label" in fields:
        sets.append("attractiveness_label=%s")
        params.append(body.attractiveness_label)
        changed["attractiveness_label"] = body.attractiveness_label
    if "rationale" in fields:
        rationale = (body.rationale or "").strip()
        sets.append("rationale=%s")
        params.append(rationale)
        changed["rationale"] = rationale
    params.extend([entry_id, horizon])
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"UPDATE manual_research_horizons SET {', '.join(sets)} WHERE entry_id=%s AND horizon=%s",
            tuple(params),
        )
        if cursor.rowcount == 0:
            raise HTTPException(404, "manual research horizon not found")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return changed


def _patch_manual_research_point(conn, point_id: int, body: ManualResearchPointPatch) -> dict:
    fields = body.model_fields_set
    sets: list[str] = ["is_user_confirmed=TRUE", "updated_at=now()"]
    params: list[object] = []
    changed: dict[str, object] = {}
    if "stance" in fields:
        if body.stance not in {"bull", "bear"}:
            raise HTTPException(400, "stance must be bull|bear")
        sets.append("stance=%s")
        params.append(body.stance)
        changed["stance"] = body.stance
    if "point" in fields:
        point = (body.point or "").strip()
        if not point:
            raise HTTPException(400, "point required")
        sets.append("point=%s")
        params.append(point)
        changed["point"] = point
    if "source_label" in fields:
        source_label = (body.source_label or "").strip() or None
        sets.append("source_label=%s")
        params.append(source_label)
        changed["source_label"] = source_label
    if "source_url" in fields:
        source_url = (body.source_url or "").strip() or None
        sets.append("source_url=%s")
        params.append(source_url)
        changed["source_url"] = source_url
    params.append(point_id)
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"UPDATE manual_research_points SET {', '.join(sets)} WHERE id=%s RETURNING entry_id",
            tuple(params),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(404, "manual research point not found")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    changed["entry_id"] = int(row["entry_id"])
    return changed


def _upsert_manual_research_consensus(conn, entry_id: int, body: ManualResearchConsensusPatch) -> dict:
    fields = body.model_fields_set
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO manual_research_consensus (entry_id, target_price, rating_label, rating_score, is_user_confirmed, created_at, updated_at)
            VALUES (%s,%s,%s,%s,TRUE,now(),now())
            ON CONFLICT (entry_id) DO UPDATE SET
                target_price = COALESCE(EXCLUDED.target_price, manual_research_consensus.target_price),
                rating_label = COALESCE(EXCLUDED.rating_label, manual_research_consensus.rating_label),
                rating_score = COALESCE(EXCLUDED.rating_score, manual_research_consensus.rating_score),
                is_user_confirmed = TRUE,
                updated_at = now()
            """,
            (
                entry_id,
                body.target_price if "target_price" in fields else None,
                body.rating_label if "rating_label" in fields else None,
                body.rating_score if "rating_score" in fields else None,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {
        "target_price": body.target_price if "target_price" in fields else None,
        "rating_label": body.rating_label if "rating_label" in fields else None,
        "rating_score": body.rating_score if "rating_score" in fields else None,
    }


def _insert_manual_research_point(conn, entry_id: int, body: ManualResearchPointIn) -> int:
    if body.stance not in {"bull", "bear"}:
        raise HTTPException(400, "stance must be bull|bear")
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO manual_research_points
                (entry_id, stance, point, source_label, source_url, is_user_confirmed, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,TRUE,now(),now())
            RETURNING id
            """,
            (
                entry_id,
                body.stance,
                body.point.strip(),
                (body.source_label or "").strip() or None,
                (body.source_url or "").strip() or None,
            ),
        )
        row_id = int(cursor.fetchone()["id"])
        conn.commit()
        return row_id
    except Exception:
        conn.rollback()
        raise


def _patch_market_manual_row(conn, row_id: int, body: MarketManualPatch) -> dict:
    fields = body.model_fields_set
    sets: list[str] = ["updated_at=now()"]
    params: list[object] = []
    changed: dict[str, object] = {}
    if "raw_text" in fields:
        raw_text = (body.raw_text or "").strip()
        sets.append("raw_text=%s")
        params.append(raw_text)
        changed["raw_text"] = raw_text
    if "source" in fields:
        source = (body.source or "").strip() or None
        sets.append("source=%s")
        params.append(source)
        changed["source"] = source
    if "source_url" in fields:
        source_url = (body.source_url or "").strip() or None
        sets.append("source_url=%s")
        params.append(source_url)
        changed["source_url"] = source_url
    if "bull_scenario" in fields:
        bull_scenario = (body.bull_scenario or "").strip() or None
        sets.append("bull_scenario=%s")
        params.append(bull_scenario)
        changed["bull_scenario"] = bull_scenario
    if "bear_scenario" in fields:
        bear_scenario = (body.bear_scenario or "").strip() or None
        sets.append("bear_scenario=%s")
        params.append(bear_scenario)
        changed["bear_scenario"] = bear_scenario
    params.append(row_id)
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"UPDATE market_view_manual SET {', '.join(sets)} WHERE id=%s",
            tuple(params),
        )
        if cursor.rowcount == 0:
            raise HTTPException(404, "market manual not found")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    if "raw_text" in changed:
        meta = _raw_text_meta(changed["raw_text"])
        logger.info("market_manual raw_text updated id=%s len=%s sha=%s", row_id, meta["length"], meta["sha256_12"])
    return changed


def _fetch_driver_items(ticker: str) -> list[dict]:
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT ticker, driver_code, driver_name, driver_source, weight, origin, rationale "
            "FROM ticker_drivers WHERE ticker=%s ORDER BY weight DESC, updated_at DESC",
            (ticker,),
        )
        return [
            {
                "ticker": r["ticker"],
                "driver_code": r["driver_code"],
                "driver_name": r["driver_name"],
                "driver_source": r["driver_source"],
                "weight": int(r["weight"]),
                "origin": r["origin"],
                "rationale": r["rationale"],
            }
            for r in c.fetchall()
        ]


def _patch_data_json_drivers(ticker: str) -> None:
    if not _DATA_JSON.exists():
        return
    try:
        from src.export_dashboard_data import _load_driver_cards

        with open(_DATA_JSON, encoding="utf-8") as f:
            data = json.load(f)
        with get_conn() as conn:
            driver_cards = _load_driver_cards(conn, [ticker]).get(ticker, [])
        for s in data.get("stocks", []):
            if s["t"] == ticker:
                s["drivers"] = driver_cards
                break
        with open(_DATA_JSON, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    except Exception as exc:
        logger.warning("data.json drivers 갱신 실패: %s", exc)


def _patch_driver_row(conn, ticker: str, driver_code: str, body: DriverPatch) -> dict:
    sets: list[str] = []
    params: list[object] = []
    changed: dict[str, object] = {}
    if "weight" in body.model_fields_set:
        sets.append("weight=%s")
        params.append(body.weight)
        changed["weight"] = body.weight
    if "rationale" in body.model_fields_set:
        rationale = (body.rationale or "").strip()
        sets.append("rationale=%s")
        params.append(rationale)
        changed["rationale"] = rationale
    params.extend([ticker, driver_code])
    cursor = conn.cursor()
    cursor.execute(
        f"UPDATE ticker_drivers SET {', '.join(sets)}, origin='user', updated_at=now() WHERE ticker=%s AND driver_code=%s",
        tuple(params),
    )
    conn.commit()
    return changed


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


@app.get("/api/portfolio/summary")
def get_portfolio_summary():
    """오버뷰와 포트폴리오가 공유하는 최신 KRW 환산 합계."""
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT total_value, total_cost, total_pnl, payload "
            "FROM portfolio_snapshot ORDER BY asof DESC LIMIT 1"
        )
        row = c.fetchone()
    return _portfolio_snapshot_payload(dict(row)) if row else None


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
        return {"ticker": ticker, "horizon": None, "attractiveness": None, "thesis": "", "history": _fetch_note_history(ticker)}
    result = {
        "ticker":        r["ticker"],
        "horizon":       r["horizon"],
        "attractiveness": r["attractiveness"],
        "thesis":        r["thesis"],
        "updated_at":    str(r["updated_at"]),
    }
    result["history"] = _fetch_note_history(ticker)
    return result


def _append_note(conn, ticker: str, body: NoteIn) -> dict:
    thesis = (body.thesis or "").strip()
    if not thesis:
        raise HTTPException(400, "thesis required")
    if body.horizon and body.horizon not in ("short", "long", "watch"):
        raise HTTPException(400, "horizon must be short|long|watch")
    if body.attractiveness is not None and not (1 <= body.attractiveness <= 5):
        raise HTTPException(400, "attractiveness must be 1~5")
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO stock_note_history (ticker, horizon, attractiveness, thesis) VALUES (%s,%s,%s,%s)",
            (ticker, body.horizon, body.attractiveness, thesis),
        )
        cursor.execute(
            """INSERT INTO stock_notes (ticker, horizon, attractiveness, thesis, updated_at)
               VALUES (%s,%s,%s,%s,now())
               ON CONFLICT (ticker) DO UPDATE SET horizon=EXCLUDED.horizon,
                 attractiveness=EXCLUDED.attractiveness, thesis=EXCLUDED.thesis, updated_at=now()""",
            (ticker, body.horizon, body.attractiveness, thesis),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"horizon": body.horizon, "attractiveness": body.attractiveness, "thesis": thesis}


@app.post("/api/notes/{ticker}", status_code=201)
def append_note(ticker: str, body: NoteIn):
    """새 판단을 이력에 추가하고 최신 3축 판단도 함께 갱신."""
    with get_conn() as conn:
        note_data = _append_note(conn, ticker, body)
    _patch_data_json_note(ticker, note_data)
    return {"ok": True, "ticker": ticker, "note": note_data, "history": _fetch_note_history(ticker)}


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


@app.delete("/api/notes/{ticker}", status_code=200)
def delete_note(ticker: str):
    """내 판단 삭제.
    - stock_notes: 행 물리 삭제 (최신 상태 테이블 — 없음이 삭제 상태)
    - stock_note_history: active=FALSE 로 비활성화 (이력 보존 원칙)
    - data.json: note=null, noteHistory=[] 로 클리어
    """
    with get_conn() as conn:
        c = conn.cursor()
        try:
            c.execute("DELETE FROM stock_notes WHERE ticker=%s", (ticker,))
            c.execute("UPDATE stock_note_history SET active=FALSE WHERE ticker=%s", (ticker,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    _patch_data_json_note(ticker, None)
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


@app.get("/api/drivers/{ticker}")
def get_drivers(ticker: str):
    return _fetch_driver_items(ticker)


@app.post("/api/drivers", status_code=201)
def add_driver(body: DriverIn):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO ticker_drivers
                (ticker, driver_code, driver_name, driver_source, weight, origin, rationale, updated_at)
            VALUES (%s,%s,%s,%s,%s,'user',%s,now())
            ON CONFLICT (ticker, driver_code) DO UPDATE SET
                driver_name=EXCLUDED.driver_name,
                driver_source=EXCLUDED.driver_source,
                weight=EXCLUDED.weight,
                origin='user',
                rationale=EXCLUDED.rationale,
                updated_at=now()
            """,
            (body.ticker, body.driver_code, body.driver_name.strip(), body.driver_source, body.weight, (body.rationale or "").strip()),
        )
        conn.commit()
    _patch_data_json_drivers(body.ticker)
    return {"ok": True, "ticker": body.ticker, "driver_code": body.driver_code}


@app.patch("/api/drivers/{ticker}/{driver_code}", status_code=200)
def patch_driver(ticker: str, driver_code: str, body: DriverPatch):
    with get_conn() as conn:
        changed = _patch_driver_row(conn, ticker, driver_code, body)
    _patch_data_json_drivers(ticker)
    return {"ok": True, "ticker": ticker, "driver_code": driver_code, "changed": changed}


@app.delete("/api/drivers/{ticker}/{driver_code}", status_code=200)
def delete_driver(ticker: str, driver_code: str):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM ticker_drivers WHERE ticker=%s AND driver_code=%s", (ticker, driver_code))
        conn.commit()
    _patch_data_json_drivers(ticker)
    return {"ok": True, "ticker": ticker, "driver_code": driver_code}


@app.post("/api/drivers/{ticker}/auto-map", status_code=200)
def auto_map_driver(ticker: str):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT name, sector, market FROM watchlist WHERE ticker=%s", (ticker,))
        row = c.fetchone()
        if not row:
            raise HTTPException(404, "ticker not found")
        mapped = auto_map_ticker_drivers(conn, ticker, name=row["name"], sector=row["sector"] or "", market=row["market"] or "US")
        conn.commit()
    _patch_data_json_drivers(ticker)
    return {"ok": True, "ticker": ticker, "count": len(mapped)}


# ── 수동 AI 분해 엔드포인트 (Wave 4-D-3) ─────────────────────────

@app.get("/api/manual-research/{ticker}")
def get_manual_research(ticker: str):
    return _fetch_manual_research_payload(ticker)


@app.post("/api/manual-research", status_code=201)
def add_manual_research(body: ManualResearchIn):
    raw_text = body.raw_text.strip()
    if not raw_text:
        raise HTTPException(400, "raw_text required")
    meta = _raw_text_meta(raw_text)
    logger.info("manual_research submit ticker=%s len=%s sha=%s", body.ticker, meta["length"], meta["sha256_12"])
    try:
        parsed = _call_manual_research_decomposition(
            ticker=body.ticker,
            raw_text=raw_text,
            source=(body.source or "").strip() or None,
            source_url=(body.source_url or "").strip() or None,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("manual research decomposition failed ticker=%s: %s", body.ticker, str(exc)[:160])
        raise HTTPException(502, "manual research decomposition failed")

    with get_conn() as conn:
        try:
            entry_id = insert_manual_research_entry(
                conn,
                ManualResearchEntryRow(
                    ticker=body.ticker,
                    raw_text=raw_text,
                    source=(body.source or "").strip() or None,
                    source_url=(body.source_url or "").strip() or None,
                    inferred_source=parsed.inferredSource,
                ),
            )
            conn.commit()
            _replace_manual_research_entry_ai(conn, entry_id, parsed)
        except Exception:
            conn.rollback()
            raise

    _regenerate_data_json()
    payload = _fetch_manual_research_payload(body.ticker)
    return {"ok": True, "entry_id": entry_id, **payload}


@app.patch("/api/manual-research/{entry_id}", status_code=200)
def patch_manual_research(entry_id: int, body: ManualResearchPatch):
    with get_conn() as conn:
        changed = _patch_manual_research_entry(conn, entry_id, body)
        if changed["needs_redecomposition"] and changed["raw_text"] is not None:
            cursor = conn.cursor()
            cursor.execute("SELECT ticker, raw_text, source, source_url FROM manual_research_entries WHERE id=%s", (entry_id,))
            row = cursor.fetchone()
            if not row:
                raise HTTPException(404, "manual research entry not found")
            try:
                parsed = _call_manual_research_decomposition(
                    ticker=row["ticker"],
                    raw_text=row["raw_text"],
                    source=row["source"],
                    source_url=row["source_url"],
                )
                _replace_manual_research_entry_ai(conn, entry_id, parsed)
            except Exception as exc:
                logger.warning("manual research redecomposition failed entry_id=%s: %s", entry_id, str(exc)[:160])
                raise HTTPException(502, "manual research redecomposition failed")
            ticker = row["ticker"]
        else:
            cursor = conn.cursor()
            cursor.execute("SELECT ticker FROM manual_research_entries WHERE id=%s", (entry_id,))
            row = cursor.fetchone()
            if not row:
                raise HTTPException(404, "manual research entry not found")
            ticker = row["ticker"]
    _regenerate_data_json()
    return {"ok": True, "entry_id": entry_id, "ticker": ticker, "changed": changed, **_fetch_manual_research_payload(ticker)}


@app.delete("/api/manual-research/{entry_id}", status_code=200)
def delete_manual_research(entry_id: int):
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM manual_research_entries WHERE id=%s RETURNING ticker", (entry_id,))
        row = cursor.fetchone()
        conn.commit()
    if not row:
        raise HTTPException(404, "manual research entry not found")
    _regenerate_data_json()
    return {"ok": True, "entry_id": entry_id, "ticker": row["ticker"], **_fetch_manual_research_payload(row["ticker"])}


@app.patch("/api/manual-research/{entry_id}/horizons/{horizon}", status_code=200)
def patch_manual_research_horizon(entry_id: int, horizon: str, body: ManualResearchHorizonPatch):
    with get_conn() as conn:
        changed = _patch_manual_research_horizon(conn, entry_id, horizon, body)
        cursor = conn.cursor()
        cursor.execute("SELECT ticker FROM manual_research_entries WHERE id=%s", (entry_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(404, "manual research entry not found")
        ticker = row["ticker"]
    _regenerate_data_json()
    return {"ok": True, "entry_id": entry_id, "horizon": horizon, "changed": changed, **_fetch_manual_research_payload(ticker)}


@app.post("/api/manual-research/{entry_id}/points", status_code=201)
def add_manual_research_point(entry_id: int, body: ManualResearchPointIn):
    with get_conn() as conn:
        point_id = _insert_manual_research_point(conn, entry_id, body)
        cursor = conn.cursor()
        cursor.execute("SELECT ticker FROM manual_research_entries WHERE id=%s", (entry_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(404, "manual research entry not found")
        ticker = row["ticker"]
    _regenerate_data_json()
    return {"ok": True, "entry_id": entry_id, "point_id": point_id, **_fetch_manual_research_payload(ticker)}


@app.patch("/api/manual-research/points/{point_id}", status_code=200)
def patch_manual_research_point(point_id: int, body: ManualResearchPointPatch):
    with get_conn() as conn:
        changed = _patch_manual_research_point(conn, point_id, body)
        cursor = conn.cursor()
        cursor.execute("SELECT ticker FROM manual_research_entries WHERE id=%s", (changed["entry_id"],))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(404, "manual research entry not found")
        ticker = row["ticker"]
    _regenerate_data_json()
    return {"ok": True, "point_id": point_id, "changed": changed, **_fetch_manual_research_payload(ticker)}


@app.delete("/api/manual-research/points/{point_id}", status_code=200)
def delete_manual_research_point(point_id: int):
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            DELETE FROM manual_research_points
            WHERE id=%s
            RETURNING entry_id
            """,
            (point_id,),
        )
        row = cursor.fetchone()
        if not row:
            conn.rollback()
            raise HTTPException(404, "manual research point not found")
        cursor.execute("SELECT ticker FROM manual_research_entries WHERE id=%s", (row["entry_id"],))
        entry = cursor.fetchone()
        conn.commit()
    _regenerate_data_json()
    return {"ok": True, "point_id": point_id, **_fetch_manual_research_payload(entry["ticker"])}


@app.patch("/api/manual-research/{entry_id}/consensus", status_code=200)
def patch_manual_research_consensus(entry_id: int, body: ManualResearchConsensusPatch):
    with get_conn() as conn:
        changed = _upsert_manual_research_consensus(conn, entry_id, body)
        cursor = conn.cursor()
        cursor.execute("SELECT ticker FROM manual_research_entries WHERE id=%s", (entry_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(404, "manual research entry not found")
        ticker = row["ticker"]
    _regenerate_data_json()
    return {"ok": True, "entry_id": entry_id, "changed": changed, **_fetch_manual_research_payload(ticker)}


@app.get("/api/market-manual")
def get_market_manual():
    return _fetch_market_manual_payload()


@app.post("/api/market-manual", status_code=201)
def add_market_manual(body: MarketManualIn):
    raw_text = body.raw_text.strip()
    if not raw_text:
        raise HTTPException(400, "raw_text required")
    meta = _raw_text_meta(raw_text)
    logger.info("market_manual submit asof=%s len=%s sha=%s", body.asof, meta["length"], meta["sha256_12"])
    try:
        parsed = _call_market_manual_decomposition(
            raw_text=raw_text,
            source=(body.source or "").strip() or None,
            source_url=(body.source_url or "").strip() or None,
            asof=body.asof,
        )
    except Exception as exc:
        logger.warning("market manual decomposition failed asof=%s: %s", body.asof, str(exc)[:160])
        raise HTTPException(502, "market manual decomposition failed")
    with get_conn() as conn:
        row_id = insert_market_view_manual(
            conn,
            MarketViewManualRow(
                asof=date.fromisoformat(body.asof),
                raw_text=raw_text,
                bull_scenario=parsed.bullScenario,
                bear_scenario=parsed.bearScenario,
                source=(body.source or "").strip() or None,
                source_url=(body.source_url or "").strip() or None,
            ),
        )
        conn.commit()
    _regenerate_data_json()
    return {"ok": True, "id": row_id, **_fetch_market_manual_payload()}


@app.patch("/api/market-manual/{row_id}", status_code=200)
def patch_market_manual(row_id: int, body: MarketManualPatch):
    with get_conn() as conn:
        changed = _patch_market_manual_row(conn, row_id, body)
    _regenerate_data_json()
    return {"ok": True, "id": row_id, "changed": changed, **_fetch_market_manual_payload()}


@app.delete("/api/market-manual/{row_id}", status_code=200)
def delete_market_manual(row_id: int):
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM market_view_manual WHERE id=%s", (row_id,))
        if cursor.rowcount == 0:
            conn.rollback()
            raise HTTPException(404, "market manual not found")
        conn.commit()
    _regenerate_data_json()
    return {"ok": True, "id": row_id, **_fetch_market_manual_payload()}


# ── 포트폴리오 전략 조언 엔드포인트 (CoT) ──────────────────────────

def _patch_data_json_advice(advice: dict) -> None:
    """data.json의 portfolioAdvice 필드만 갱신."""
    if not _DATA_JSON.exists():
        return
    try:
        with open(_DATA_JSON, encoding="utf-8") as f:
            data = json.load(f)
        data["portfolioAdvice"] = advice
        with open(_DATA_JSON, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    except Exception as exc:
        logger.warning("data.json advice 갱신 실패: %s", exc)


@app.get("/api/portfolio/advice")
def get_portfolio_advice():
    """최근 전략 조언 + 보유 변경 시 stale 표시(없으면 null)."""
    from src.portfolio_advice import load_latest
    with get_conn() as conn:
        return load_latest(conn)


@app.post("/api/portfolio/advice", status_code=200)
def make_portfolio_advice():
    """전략 조언 재생성(CoT, force) → data.json 갱신 + 결과 반환."""
    from src.portfolio_advice import analyze_portfolio
    with get_conn() as conn:
        advice = analyze_portfolio(conn, force=True)
    _patch_data_json_advice(advice)
    return advice


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


def _patch_watchlist_row(conn, ticker: str, body: WatchlistPatch) -> dict:
    fields = body.model_fields_set
    sector = (body.sector or "").strip() or None if "sector" in fields else None
    cursor = conn.cursor()
    try:
        if fields == {"active"}:
            cursor.execute("UPDATE watchlist SET active=%s WHERE ticker=%s", (body.active, ticker))
        elif fields == {"sector"}:
            cursor.execute("UPDATE watchlist SET sector=%s WHERE ticker=%s", (sector, ticker))
        else:
            cursor.execute(
                "UPDATE watchlist SET active=%s, sector=%s WHERE ticker=%s",
                (body.active, sector, ticker),
            )
        if cursor.rowcount == 0:
            raise HTTPException(404, "ticker not found")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"active": body.active if "active" in fields else None, "sector": sector}


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
    """active 또는 sector 변경 후 data.json 재생성."""
    with get_conn() as conn:
        changed = _patch_watchlist_row(conn, ticker, body)
    _regenerate_data_json()
    return {"ok": True, "ticker": ticker, **changed}


@app.post("/api/watchlist/{old_ticker}/correct", status_code=200)
def correct_watchlist(old_ticker: str, body: WatchlistCorrectIn, background: BackgroundTasks):
    """티커/국가 오타 정정 = 잘못된 종목 비활성 + 올바른 종목 추가(한 트랜잭션).

    티커는 prices_daily·quant_scores·news_raw·stock_action_advice 등 거의 모든 테이블의 사실상
    키이므로 단순 UPDATE하면 잘못된 티커로 쌓인 데이터가 올바른 티커에 잘못 붙는다. 따라서
    제거(=비활성, 데이터 보존)+신규 추가로 처리한다. 새 종목은 백그라운드로 백필 후 화면 반영.
    기존(잘못된) 종목 데이터는 1차에서 물리 삭제하지 않고 watchlist 비활성만 한다(export는
    active만 조회하므로 화면에서 자연히 사라짐). 보유(portfolio_holdings)는 이전하지 않는다.
    """
    new_ticker = body.ticker.strip()
    if not new_ticker or any(ch.isspace() for ch in new_ticker):
        raise HTTPException(400, "티커는 공백 없이 입력하세요")
    market = body.market.upper()
    if market not in ("US", "KR"):
        raise HTTPException(400, "market must be US or KR")
    if new_ticker == old_ticker:
        raise HTTPException(400, "새 티커가 기존 티커와 동일합니다")

    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT name, sector FROM watchlist WHERE ticker=%s", (old_ticker,))
        old = c.fetchone()
        if not old:
            raise HTTPException(404, "기존 종목을 찾을 수 없습니다")
        c.execute("SELECT active FROM watchlist WHERE ticker=%s", (new_ticker,))
        existing = c.fetchone()
        if existing and existing["active"]:
            raise HTTPException(409, "이미 활성 관심종목에 있는 티커입니다")

        name = (body.name or old["name"] or new_ticker).strip()
        sector = ((body.sector if body.sector is not None else old["sector"]) or "").strip() or None
        try:
            # 1) 잘못된 티커 비활성(데이터 보존 — 물리 삭제 보류)
            c.execute("UPDATE watchlist SET active=false WHERE ticker=%s", (old_ticker,))
            # 2) 올바른 티커 추가(이미 있으면 되살림 + 메타 갱신)
            if existing:
                c.execute(
                    "UPDATE watchlist SET active=true, name=%s, market=%s, sector=%s WHERE ticker=%s",
                    (name, market, sector, new_ticker),
                )
            else:
                c.execute(
                    """INSERT INTO watchlist (ticker, name, market, sector, is_holding, active, added_at)
                       VALUES (%s,%s,%s,%s,false,true,now())""",
                    (new_ticker, name, market, sector),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    background.add_task(_backfill_and_export, new_ticker, market)
    return {"ok": True, "old_ticker": old_ticker, "ticker": new_ticker, "market": market, "status": "collecting"}


# ── 실행 ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    print("ATLAS Local API — http://127.0.0.1:8765/docs")
    uvicorn.run("src.local_api:app", host="127.0.0.1", port=8765, reload=True)
