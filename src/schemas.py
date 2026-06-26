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
    rating_label: Optional[str] = None
    rating_score: Optional[float] = None
    target_price: Optional[float] = None
    upside: Optional[float] = None
    eps_fwd: Optional[float] = None
    n_analysts: Optional[int] = None
    source: str = "legacy"
    created_at: Optional[datetime] = None


class AnalystViewRow(BaseModel):
    ticker: str
    asof: date
    stance: Literal["bull", "bear"]
    point: str = Field(min_length=1)
    source: str
    source_url: str
    created_at: Optional[datetime] = None


class ManualResearchEntryRow(BaseModel):
    ticker: str
    raw_text: str = Field(min_length=1)
    source: Optional[str] = None
    source_url: Optional[str] = None
    inferred_source: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ManualResearchHorizonRow(BaseModel):
    entry_id: int
    horizon: Literal["short", "mid", "long"]
    attractiveness_label: Literal["매력적", "다소 매력적", "중립", "다소 비매력적", "비매력적"]
    rationale: str = Field(min_length=1)
    is_user_confirmed: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ManualResearchPointRow(BaseModel):
    entry_id: int
    stance: Literal["bull", "bear"]
    point: str = Field(min_length=1)
    source_label: Optional[str] = None
    source_url: Optional[str] = None
    is_user_confirmed: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ManualResearchConsensusRow(BaseModel):
    entry_id: int
    target_price: Optional[float] = None
    rating_label: Optional[str] = None
    rating_score: Optional[float] = None
    is_user_confirmed: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MarketViewManualRow(BaseModel):
    asof: date
    scope: Literal["market"] = "market"
    raw_text: str = Field(min_length=1)
    bull_scenario: Optional[str] = None
    bear_scenario: Optional[str] = None
    source: Optional[str] = None
    source_url: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class StockActionAdviceRow(BaseModel):
    ticker: str
    asof: date
    direction: Literal["매수", "비중확대", "유지", "비중축소", "매도"]
    current_weight: Optional[float] = None
    target_weight_low: Optional[float] = None
    target_weight_high: Optional[float] = None
    weight_action: Literal["늘림", "유지", "줄임"]
    entry_zone: Optional[str] = None
    exit_zone: Optional[str] = None
    confidence: Literal["상", "중", "하"]
    rationale: str = Field(min_length=1)
    supporting_factors: list[dict[str, Any]] = Field(default_factory=list)
    opposing_factors: list[dict[str, Any]] = Field(default_factory=list)
    divergence_note: Optional[str] = None
    model: Optional[str] = None
    created_at: Optional[datetime] = None
    # 신규-D: 보유성격 + 집중 리스크 관찰 (기존 비중 컬럼은 보존, 표시에서만 제외)
    hold_character: Optional[Literal["장기보유", "모멘텀", "단기", "정보부족"]] = None
    hold_character_secondary: list[str] = Field(default_factory=list)
    hold_character_basis: list[dict[str, Any]] = Field(default_factory=list)
    concentration_note: Optional[str] = None


class MarketScoreRow(BaseModel):
    """Wave 5-B: 시장 매력도 점수(시장 단위, asof 이력). 결정론 산출, LLM은 해설만."""
    asof: date
    region: Literal["KR", "US"]
    score: float                       # 0~100 (divergence 시 50쪽으로 수축)
    direction: Literal["강세", "중립", "약세"]
    confidence: Literal["상", "중", "하"]
    components: dict[str, Any] = Field(default_factory=dict)
    divergence_note: Optional[str] = None
    created_at: Optional[datetime] = None


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


class MacroIndicatorRow(BaseModel):
    indicator_code: str
    indicator_name: str
    region: Literal["US", "KR", "GLOBAL"]
    asof: date
    value: float
    unit: str
    source: str


class MacroSummaryRow(BaseModel):
    summary_date: date
    headline: str
    support_view: str
    oppose_view: str
    watch_points: list[str] = Field(default_factory=list)
    summary_md: str


class TickerDriverRow(BaseModel):
    ticker: str
    driver_code: str
    driver_name: str
    driver_source: str
    weight: int = Field(ge=1, le=5)
    origin: Literal["auto", "user"]
    rationale: str


class DriverPriceRow(BaseModel):
    driver_code: str
    asof: date
    close: float
    source: str


class IndexDailyRow(BaseModel):
    index_code: str
    asof: date
    close: float
    source: str = "yfinance"


class TickerContextRow(BaseModel):
    ticker: str
    context_type: Literal["news_summary", "report", "driver", "macro"]
    content: str
    source: str
    valid_from: date
    valid_until: Optional[date] = None


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
    # 신규-A1: 시장 민감도(자국 지수 대비). 퀀트 축 별도 팩터 — composite에 합산하지 않음.
    beta: Optional[float] = None
    market_corr: Optional[float] = None


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
    source: Optional[str] = None


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


class AnalystArgumentItem(BaseModel):
    point: str = Field(min_length=1)
    source: str = Field(min_length=1)
    source_url: str = Field(min_length=1)


class AnalystViewsOutput(BaseModel):
    bull: list[AnalystArgumentItem] = Field(default_factory=list)
    bear: list[AnalystArgumentItem] = Field(default_factory=list)


class ManualResearchArgumentItem(BaseModel):
    point: str = Field(min_length=1)
    sourceLabel: Optional[str] = None
    sourceUrl: Optional[str] = None


class ManualResearchHorizonOutput(BaseModel):
    horizon: Literal["short", "mid", "long"]
    attractivenessLabel: Literal["매력적", "다소 매력적", "중립", "다소 비매력적", "비매력적"]
    rationale: str = Field(min_length=1)


class ManualResearchConsensusOutput(BaseModel):
    targetPrice: Optional[float] = None
    ratingLabel: Optional[str] = None
    ratingScore: Optional[float] = None


class ManualResearchOutput(BaseModel):
    inferredSource: Optional[str] = None
    consensus: Optional[ManualResearchConsensusOutput] = None
    bull_points: list[ManualResearchArgumentItem] = Field(default_factory=list, alias="bullPoints")
    bear_points: list[ManualResearchArgumentItem] = Field(default_factory=list, alias="bearPoints")
    horizons: list[ManualResearchHorizonOutput] = Field(default_factory=list)

    model_config = {"populate_by_name": True}

    @field_validator("horizons")
    @classmethod
    def _validate_three_unique_horizons(cls, value: list[ManualResearchHorizonOutput]) -> list[ManualResearchHorizonOutput]:
        order = [item.horizon for item in value]
        if order != ["short", "mid", "long"]:
            raise ValueError("horizons must include short, mid, long in order")
        return value


class MarketManualOutput(BaseModel):
    bullScenario: str = Field(min_length=1)
    bearScenario: str = Field(min_length=1)


class StockActionAdviceNarrativeOutput(BaseModel):
    rationale: str = Field(min_length=1)
    divergenceNote: Optional[str] = None
    supportingFactors: list[dict[str, Any]] = Field(default_factory=list)
    opposingFactors: list[dict[str, Any]] = Field(default_factory=list)
    # 신규-D: 집중 리스크 관찰 노트의 '어휘만' 다듬은 버전(선택). 구조 재생성 금지 — 가드 통과 시에만 채택.
    concentrationNote: Optional[str] = None


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


class MacroSummaryOutput(BaseModel):
    headline: str
    support_view: str
    oppose_view: str
    watch_points: list[str] = Field(default_factory=list)
    summary_md: str


class DriverSuggestionItem(BaseModel):
    driver_code: str
    driver_name: str
    driver_source: str
    weight: int = Field(ge=1, le=5)
    rationale: str


class DriverSuggestionOutput(BaseModel):
    drivers: list[DriverSuggestionItem] = Field(default_factory=list)
