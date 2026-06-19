"""
schemas.py — PRD §5.2/§5.3 계약 pydantic v2 모델

모든 모듈의 입출력 타입 기준. DB 행(Row*) + 뷰 레코드(StockDailyRecord) +
LLM I/O (NewsSummaryOutput, MarketSummaryOutput).

규칙:
- 결측은 Optional[T] = None. 문자열 'N/A' 금지.
- Literal로 허용 값 열거 → 계약 벗어난 값은 ValidationError.
- 행 모델은 DB upsert 입력 그대로 쓸 수 있게 snake_case + 컬럼명 일치.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ──────────────────────────────────────────────────────────────
# DB 행 모델 (§5.1 테이블과 1:1 대응)
# ──────────────────────────────────────────────────────────────

class WatchlistRow(BaseModel):
    ticker: str
    name: str
    market: Literal["US", "KR"]
    sector: Optional[str] = None
    is_holding: bool = False
    active: bool = True


class PriceDailyRow(BaseModel):
    ticker: str
    date: date
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[int] = None
    source: str


class IndicatorDailyRow(BaseModel):
    ticker: str
    date: date
    sma20: Optional[float] = None
    sma50: Optional[float] = None
    sma200: Optional[float] = None
    rsi14: Optional[float] = None
    disparity20: Optional[float] = None
    slope50: Optional[float] = None
    slope200: Optional[float] = None
    is_aligned: Optional[bool] = None


class FundamentalsRow(BaseModel):
    ticker: str
    period_type: Literal["annual", "quarter"]
    period_end: date
    revenue: Optional[float] = None
    op_income: Optional[float] = None
    op_margin: Optional[float] = None
    net_income: Optional[float] = None
    ocf: Optional[float] = None   # 영업현금흐름 (PR-2)
    fcf: Optional[float] = None   # 잉여현금흐름 = OCF + CapEx (PR-2)
    source: str


class ValuationRow(BaseModel):
    ticker: str
    asof: date
    per_t: Optional[float] = None
    per_f: Optional[float] = None
    pbr: Optional[float] = None
    ev_ebitda: Optional[float] = None
    roe: Optional[float] = None
    roa: Optional[float] = None
    debt_ratio: Optional[float] = None
    rev_growth: Optional[float] = None


class AnalystRow(BaseModel):
    ticker: str
    asof: date
    rating: Optional[str] = None
    target_price: Optional[float] = None
    upside: Optional[float] = None
    n_analysts: Optional[int] = None


class NewsRawRow(BaseModel):
    ticker: str
    source: str
    published_at: Optional[datetime] = None  # DB TIMESTAMPTZ nullable 반영
    title: str
    body: Optional[str] = None
    url: str
    url_hash: str = Field(default="")

    @model_validator(mode="after")
    def _fill_url_hash(self) -> "NewsRawRow":
        if not self.url_hash:
            self.url_hash = hashlib.sha256(self.url.encode()).hexdigest()
        return self


class NewsAnalysisRow(BaseModel):
    ticker: str
    asof: date
    sentiment: Literal["긍정", "중립", "부정"]
    sentiment_score: float
    summary_md: str
    payload: dict[str, Any]
    n_articles: int
    model: str
    based_on: Literal["recent", "fallback_old"]
    curated: list[dict] = Field(default_factory=list)  # 중요뉴스 큐레이션 결과


class MarketNewsRow(BaseModel):
    source: str
    title: str
    url: str
    published_at: Optional[datetime] = None
    url_hash: str = Field(default="")

    @model_validator(mode="after")
    def _fill_url_hash(self) -> "MarketNewsRow":
        if not self.url_hash:
            self.url_hash = hashlib.sha256(self.url.encode()).hexdigest()
        return self


class MarketNewsSummaryRow(BaseModel):
    summary_date: date
    kr_summary: str
    us_summary: str
    global_summary: str


class QuantScoresRow(BaseModel):
    ticker: str
    asof: date
    momentum: Optional[float] = None
    value: Optional[float] = None
    quality: Optional[float] = None
    growth: Optional[float] = None
    sentiment: Optional[float] = None
    composite: Optional[float] = None
    fscore: Optional[int] = None  # Piotroski F-Score(0~9, 실질 0~7) — 스크리너 안전마진 입력
    flags: list[str] = Field(default_factory=list)


class PortfolioRow(BaseModel):
    ticker: str
    qty: float
    avg_price: float
    cur_price: Optional[float] = None
    eval_amount: Optional[float] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    asof: datetime


class PortfolioSnapshotRow(BaseModel):
    asof: datetime
    total_value: Optional[float] = None
    total_cost: Optional[float] = None
    total_pnl: Optional[float] = None
    cash: Optional[float] = None
    payload: dict[str, Any] = Field(default_factory=dict)


class MarketDailyRow(BaseModel):
    asof: date
    kospi: Optional[float] = None
    kosdaq: Optional[float] = None
    sp500: Optional[float] = None
    nasdaq: Optional[float] = None
    vix: Optional[float] = None
    usdkrw: Optional[float] = None
    ust10y: Optional[float] = None
    summary_md: Optional[str] = None
    summary_kr_md: Optional[str] = None  # PR-4: 한국 시장 전용 시황
    summary_us_md: Optional[str] = None  # PR-4: 미국 시장 전용 시황
    payload: dict[str, Any] = Field(default_factory=dict)


class RunRow(BaseModel):
    kind: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    status: Literal["running", "success", "partial", "failed"]
    errors: list[dict[str, Any]] = Field(default_factory=list)


# ──────────────────────────────────────────────────────────────
# §5.2 종목 일일 레코드 (Hermes·시트 소비용 조립 뷰)
# ──────────────────────────────────────────────────────────────

class PriceView(BaseModel):
    close: Optional[float] = None
    chg_pct: Optional[float] = None
    rsi14: Optional[float] = None
    disparity20: Optional[float] = None
    is_aligned: Optional[bool] = None


class FundamentalsView(BaseModel):
    rev_yoy: Optional[float] = None
    op_margin: Optional[float] = None
    last_q_rev_b: Optional[float] = None


class ValuationView(BaseModel):
    per_f: Optional[float] = None
    pbr: Optional[float] = None
    roe: Optional[float] = None


class AnalystView(BaseModel):
    rating: Optional[str] = None
    target: Optional[float] = None
    upside: Optional[float] = None


class NewsView(BaseModel):
    sentiment: Optional[Literal["긍정", "중립", "부정"]] = None
    score: Optional[float] = None
    summary_md: Optional[str] = None
    based_on: Optional[Literal["recent", "fallback_old"]] = None


class TradeSignal(BaseModel):
    label: Literal["매수", "관망", "축소"]
    percentile: float = Field(ge=0, le=100)
    reason: str = Field(min_length=1)
    confidence: int = Field(ge=50, le=100)


class QuantView(BaseModel):
    composite: Optional[float] = None
    momentum: Optional[float] = None
    value: Optional[float] = None
    quality: Optional[float] = None
    growth: Optional[float] = None
    sentiment: Optional[float] = None
    flags: list[str] = Field(default_factory=list)
    signal: Optional[TradeSignal] = None


class StockDailyRecord(BaseModel):
    """PRD §5.2 — assemble.py가 조립하고 Hermes/시트가 소비하는 종목 일일 레코드."""

    ticker: str
    name: str
    market: Literal["US", "KR"]
    price: PriceView = Field(default_factory=PriceView)
    fundamentals: FundamentalsView = Field(default_factory=FundamentalsView)
    valuation: ValuationView = Field(default_factory=ValuationView)
    analyst: AnalystView = Field(default_factory=AnalystView)
    news: NewsView = Field(default_factory=NewsView)
    quant: QuantView = Field(default_factory=QuantView)
    is_holding: bool = False

# ──────────────────────────────────────────────────────────────
# §5.3-A LLM 출력 — 종목 뉴스 요약 (Gemini, 종목당)
# ──────────────────────────────────────────────────────────────

class CatalystItem(BaseModel):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    headline: str
    impact: Literal["긍정", "부정"]
    importance: Literal["상", "중", "하"]


class NewsSummaryOutput(BaseModel):
    """PRD §5.3-A — Gemini 종목 뉴스 요약 출력 스키마."""

    sentiment: Literal["긍정", "중립", "부정"]
    sentiment_score: float = Field(ge=-1.0, le=1.0)
    key_points: list[str]
    catalysts: list[CatalystItem] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    summary_md: str
    confidence: Literal["상", "중", "하"]
    based_on: Literal["recent", "fallback_old"]

    @field_validator("key_points")
    @classmethod
    def _key_points_not_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("key_points must have at least one item")
        return v


# ──────────────────────────────────────────────────────────────
# §5.3-B LLM 출력 — 일일 시황 종합 (Gemini, 1회/일)
# ──────────────────────────────────────────────────────────────

class MarketSummaryOutput(BaseModel):
    """PRD §5.3-B — Gemini 일일 시황 종합 출력 스키마."""

    regime: Literal["위험선호", "중립", "위험회피"]
    headline: str
    drivers: list[str]
    kr_us_note: str
    watch_today: list[str]
    summary_md: str

    @field_validator("drivers", "watch_today")
    @classmethod
    def _list_not_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("field must have at least one item")
        return v


class MarketNewsDigestOutput(BaseModel):
    kr_summary: str
    us_summary: str
    global_summary: str
