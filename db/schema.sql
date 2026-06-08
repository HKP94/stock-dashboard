-- =============================================================
-- db/schema.sql — ATLAS Postgres 스키마 (PRD §5.1)
--
-- 실행: psql $DATABASE_URL -f db/schema.sql
-- 멱등성: IF NOT EXISTS + DO NOTHING 사용. 재실행 안전.
-- =============================================================

-- ── 확장 ─────────────────────────────────────────────────────
-- btree_gin: JSONB 컬럼 인덱스 최적화 (선택)
-- CREATE EXTENSION IF NOT EXISTS btree_gin;

-- =============================================================
-- 관심종목
-- =============================================================
CREATE TABLE IF NOT EXISTS watchlist (
    ticker      TEXT        PRIMARY KEY,
    name        TEXT        NOT NULL,
    market      TEXT        NOT NULL CHECK (market IN ('US', 'KR')),
    sector      TEXT,
    is_holding  BOOLEAN     NOT NULL DEFAULT FALSE,
    active      BOOLEAN     NOT NULL DEFAULT TRUE,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =============================================================
-- 일별 가격 (원천 OHLCV — 지표는 indicators_daily에 별도 저장)
-- =============================================================
CREATE TABLE IF NOT EXISTS prices_daily (
    ticker      TEXT        NOT NULL,
    date        DATE        NOT NULL,
    open        NUMERIC,
    high        NUMERIC,
    low         NUMERIC,
    close       NUMERIC,
    volume      BIGINT,
    source      TEXT        NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, date)
);

CREATE INDEX IF NOT EXISTS idx_prices_daily_ticker ON prices_daily (ticker);

-- =============================================================
-- 연산된 기술적 지표 (이력 누적, compute_indicators.py 출력)
-- =============================================================
CREATE TABLE IF NOT EXISTS indicators_daily (
    ticker      TEXT        NOT NULL,
    date        DATE        NOT NULL,
    sma20       NUMERIC,
    sma50       NUMERIC,
    sma200      NUMERIC,
    rsi14       NUMERIC,
    disparity20 NUMERIC,
    slope50     NUMERIC,
    slope200    NUMERIC,
    is_aligned  BOOLEAN,
    PRIMARY KEY (ticker, date)
);

-- =============================================================
-- 재무 (연간/분기)
-- =============================================================
CREATE TABLE IF NOT EXISTS fundamentals (
    ticker      TEXT        NOT NULL,
    period_type TEXT        NOT NULL CHECK (period_type IN ('annual', 'quarter')),
    period_end  DATE        NOT NULL,
    revenue     NUMERIC,
    op_income   NUMERIC,
    op_margin   NUMERIC,
    net_income  NUMERIC,
    source      TEXT        NOT NULL,
    PRIMARY KEY (ticker, period_type, period_end)
);

-- =============================================================
-- 밸류에이션 / 퀄리티 스냅샷
-- =============================================================
CREATE TABLE IF NOT EXISTS valuation (
    ticker      TEXT        NOT NULL,
    asof        DATE        NOT NULL,
    per_t       NUMERIC,
    per_f       NUMERIC,
    pbr         NUMERIC,
    ev_ebitda   NUMERIC,
    roe         NUMERIC,
    roa         NUMERIC,
    debt_ratio  NUMERIC,
    rev_growth  NUMERIC,
    PRIMARY KEY (ticker, asof)
);

-- =============================================================
-- 애널리스트 컨센서스
-- =============================================================
CREATE TABLE IF NOT EXISTS analyst (
    ticker        TEXT    NOT NULL,
    asof          DATE    NOT NULL,
    rating        TEXT,
    target_price  NUMERIC,
    upside        NUMERIC,
    n_analysts    INT,
    PRIMARY KEY (ticker, asof)
);

-- =============================================================
-- 뉴스 원천 (url_hash 로 dedupe)
-- =============================================================
CREATE TABLE IF NOT EXISTS news_raw (
    id           BIGSERIAL   PRIMARY KEY,
    ticker       TEXT        NOT NULL,
    source       TEXT        NOT NULL,
    published_at TIMESTAMPTZ NOT NULL,
    title        TEXT        NOT NULL,
    body         TEXT,
    url          TEXT        NOT NULL,
    url_hash     TEXT        NOT NULL UNIQUE,
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_news_raw_ticker_published
    ON news_raw (ticker, published_at DESC);

-- =============================================================
-- 뉴스 LLM 분석 결과 (enrich_gemini.py → §5.3-A 저장)
-- =============================================================
CREATE TABLE IF NOT EXISTS news_analysis (
    ticker          TEXT    NOT NULL,
    asof            DATE    NOT NULL,
    sentiment       TEXT    NOT NULL CHECK (sentiment IN ('긍정', '중립', '부정')),
    sentiment_score NUMERIC NOT NULL,
    summary_md      TEXT    NOT NULL,
    payload         JSONB   NOT NULL DEFAULT '{}',
    n_articles      INT     NOT NULL,
    model           TEXT    NOT NULL,
    based_on        TEXT    NOT NULL CHECK (based_on IN ('recent', 'fallback_old')),
    PRIMARY KEY (ticker, asof)
);

-- =============================================================
-- 퀀트 팩터 점수 (compute_quant.py → §F4)
-- =============================================================
CREATE TABLE IF NOT EXISTS quant_scores (
    ticker    TEXT    NOT NULL,
    asof      DATE    NOT NULL,
    momentum  NUMERIC,
    value     NUMERIC,
    quality   NUMERIC,
    growth    NUMERIC,
    sentiment NUMERIC,
    composite NUMERIC,
    flags     JSONB   NOT NULL DEFAULT '[]',
    PRIMARY KEY (ticker, asof)
);

-- =============================================================
-- 포트폴리오 (F1 — KIS 잔고 스냅샷)
-- =============================================================
CREATE TABLE IF NOT EXISTS portfolio (
    ticker      TEXT        NOT NULL,
    qty         NUMERIC     NOT NULL,
    avg_price   NUMERIC     NOT NULL,
    cur_price   NUMERIC,
    eval_amount NUMERIC,
    pnl         NUMERIC,
    pnl_pct     NUMERIC,
    asof        TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (ticker, asof)
);

CREATE TABLE IF NOT EXISTS portfolio_snapshot (
    asof        TIMESTAMPTZ PRIMARY KEY,
    total_value NUMERIC,
    total_cost  NUMERIC,
    total_pnl   NUMERIC,
    cash        NUMERIC,
    payload     JSONB NOT NULL DEFAULT '{}'
);

-- =============================================================
-- 시장 지표 (F3 — 지수/VIX/환율/금리 + Gemini 시황)
-- =============================================================
CREATE TABLE IF NOT EXISTS market_daily (
    asof       DATE  PRIMARY KEY,
    kospi      NUMERIC,
    kosdaq     NUMERIC,
    sp500      NUMERIC,
    nasdaq     NUMERIC,
    vix        NUMERIC,
    usdkrw     NUMERIC,
    ust10y     NUMERIC,
    summary_md TEXT,
    payload    JSONB NOT NULL DEFAULT '{}'
);

-- =============================================================
-- 실행 로그 (관측성 — 모든 파이프라인 실행 기록)
-- =============================================================
CREATE TABLE IF NOT EXISTS runs (
    run_id      BIGSERIAL   PRIMARY KEY,
    kind        TEXT        NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    status      TEXT        NOT NULL CHECK (status IN ('running', 'success', 'partial', 'failed')),
    errors      JSONB       NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_runs_kind_started ON runs (kind, started_at DESC);
