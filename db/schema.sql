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
    ocf         NUMERIC,     -- 영업현금흐름 (PR-2 재무 추이)
    fcf         NUMERIC,     -- 잉여현금흐름 = OCF + CapEx(음수) (PR-2)
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
-- 시장 뉴스 원천 (W2-B)
-- =============================================================
CREATE TABLE IF NOT EXISTS market_news (
    id           BIGSERIAL   PRIMARY KEY,
    source       TEXT        NOT NULL,
    title        TEXT        NOT NULL,
    url          TEXT        NOT NULL,
    url_hash     TEXT        NOT NULL UNIQUE,
    published_at TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_market_news_published
    ON market_news (published_at DESC, created_at DESC);

CREATE TABLE IF NOT EXISTS market_news_summary (
    id             BIGSERIAL   PRIMARY KEY,
    summary_date   DATE        NOT NULL UNIQUE,
    kr_summary     TEXT        NOT NULL,
    us_summary     TEXT        NOT NULL,
    global_summary TEXT        NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS macro_indicators (
    indicator_code TEXT        NOT NULL,
    indicator_name TEXT        NOT NULL,
    region         TEXT        NOT NULL CHECK (region IN ('US', 'KR', 'GLOBAL')),
    asof           DATE        NOT NULL,
    value          NUMERIC     NOT NULL,
    unit           TEXT        NOT NULL,
    source         TEXT        NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (indicator_code, asof)
);

CREATE INDEX IF NOT EXISTS idx_macro_indicators_region_code_asof
    ON macro_indicators (region, indicator_code, asof DESC);

CREATE TABLE IF NOT EXISTS macro_summary (
    id            BIGSERIAL   PRIMARY KEY,
    summary_date  DATE        NOT NULL UNIQUE,
    headline      TEXT        NOT NULL,
    support_view  TEXT        NOT NULL,
    oppose_view   TEXT        NOT NULL,
    watch_points  JSONB       NOT NULL DEFAULT '[]',
    summary_md    TEXT        NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ticker_context (
    id           BIGSERIAL   PRIMARY KEY,
    ticker       TEXT        NOT NULL,
    context_type TEXT        NOT NULL CHECK (context_type IN ('news_summary', 'report', 'driver', 'macro')),
    content      TEXT        NOT NULL,
    source       TEXT        NOT NULL,
    valid_from   DATE        NOT NULL,
    valid_until  DATE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ticker_context_lookup
    ON ticker_context (ticker, context_type, valid_from DESC);

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
    curated         JSONB   NOT NULL DEFAULT '[]',  -- 중요뉴스 큐레이션(2단계): [{title,url,source,published_at,category,direction,impact_score,insight}]
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
    fscore    SMALLINT,   -- Piotroski F-Score(0~9, 실질 0~7) — 스크리너 '안전마진' 입력
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
    asof          DATE  PRIMARY KEY,
    kospi         NUMERIC,
    kosdaq        NUMERIC,
    sp500         NUMERIC,
    nasdaq        NUMERIC,
    vix           NUMERIC,
    usdkrw        NUMERIC,
    ust10y        NUMERIC,
    summary_md    TEXT,             -- (레거시) 통합 시황
    summary_kr_md TEXT,             -- PR-4: 한국 시장 전용 시황 (Gemini)
    summary_us_md TEXT,             -- PR-4: 미국 시장 전용 시황 (Gemini)
    payload       JSONB NOT NULL DEFAULT '{}'  -- payload.changes={field: pct} (전일대비 등락)
);
-- PR-4: 기존 테이블에 컬럼 추가 (재실행 안전)
ALTER TABLE market_daily ADD COLUMN IF NOT EXISTS summary_kr_md TEXT;
ALTER TABLE market_daily ADD COLUMN IF NOT EXISTS summary_us_md TEXT;

-- =============================================================
-- 장기 벤치마크 지수 이력 (W3-A — true backtest 비교용 5년 일봉)
-- latest snapshot용 market_daily와 분리해 시계열 연속성/비교 기준을 보존한다.
-- =============================================================
CREATE TABLE IF NOT EXISTS index_daily (
    index_code   TEXT        NOT NULL,
    asof         DATE        NOT NULL,
    close        NUMERIC     NOT NULL,
    source       TEXT        NOT NULL DEFAULT 'yfinance',
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (index_code, asof)
);

CREATE INDEX IF NOT EXISTS idx_index_daily_asof
    ON index_daily (asof DESC, index_code);

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

-- =============================================================
-- 보유종목 입력 (F1 — 수동 입력 기반 평가 계산용)
-- PR-2: portfolio_holdings × prices_daily → portfolio / portfolio_snapshot
-- =============================================================
CREATE TABLE IF NOT EXISTS portfolio_holdings (
    ticker      TEXT        PRIMARY KEY,
    qty         NUMERIC     NOT NULL CHECK (qty >= 0),
    avg_price   NUMERIC     NOT NULL CHECK (avg_price >= 0),
    currency    TEXT        NOT NULL DEFAULT 'KRW',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- PR-2: 통화별 현금 (총자산 = 보유종목 평가액 + 현금, KRW 환산)
CREATE TABLE IF NOT EXISTS portfolio_cash (
    currency    TEXT        PRIMARY KEY,
    amount      NUMERIC     NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =============================================================
-- 리서치 항목 (F6 — 유튜브·기사·리포트·퀀트·메모 수동 입력)
-- PR-4
-- =============================================================
CREATE TABLE IF NOT EXISTS research_items (
    id          BIGSERIAL   PRIMARY KEY,
    ticker      TEXT        NOT NULL,
    item_type   TEXT        NOT NULL CHECK (item_type IN ('youtube', 'article', 'report', 'quant', 'memo')),
    title       TEXT        NOT NULL,
    url         TEXT,
    note        TEXT,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_research_items_ticker ON research_items (ticker, added_at DESC);

-- =============================================================
-- 투자 판단 메모 (F6 — 수동 입력, 종목별 1행)
-- PR-3: 로컬 API PUT /api/notes/{ticker}
-- =============================================================
CREATE TABLE IF NOT EXISTS stock_notes (
    ticker          TEXT        PRIMARY KEY,
    horizon         TEXT        CHECK (horizon IN ('short', 'long', 'watch')),
    attractiveness  INT         CHECK (attractiveness BETWEEN 1 AND 5),
    thesis          TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS stock_note_history (
    id              BIGSERIAL   PRIMARY KEY,
    ticker          TEXT        NOT NULL,
    horizon         TEXT        CHECK (horizon IN ('short', 'long', 'watch')),
    attractiveness  INT         CHECK (attractiveness BETWEEN 1 AND 5),
    thesis          TEXT        NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_stock_note_history_ticker
    ON stock_note_history (ticker, created_at DESC, id DESC);

-- =============================================================
-- 포트폴리오 전략 조언 (CoT 결과 캐시) — cache_key = 보유·현금·레짐 시그니처
-- 보유 변경 시 cache_key가 달라져 stale 판정.
-- =============================================================
CREATE TABLE IF NOT EXISTS portfolio_advice (
    cache_key    TEXT        PRIMARY KEY,
    payload      JSONB       NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =============================================================
-- 백테스트 / 회고 결과 (PR-5)
-- metric_type: 'true_backtest'(과거 시점 데이터만, 미래정보 없음)
--            | 'retrospective'(오늘 스냅샷 기반 회고 — 선정시점편향 주의, 백테스트 아님)
-- =============================================================
CREATE TABLE IF NOT EXISTS backtest_results (
    id            BIGSERIAL   PRIMARY KEY,
    strategy_name TEXT        NOT NULL,
    metric_type   TEXT        NOT NULL CHECK (metric_type IN ('true_backtest', 'retrospective')),
    computed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    window_start  DATE,
    window_end    DATE,
    cum_return    NUMERIC,
    cagr          NUMERIC,
    mdd           NUMERIC,
    vol           NUMERIC,
    sharpe        NUMERIC,
    payload       JSONB       NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_backtest_strategy ON backtest_results (strategy_name, computed_at DESC);
ALTER TABLE backtest_results ADD COLUMN IF NOT EXISTS strategy TEXT;
ALTER TABLE backtest_results ADD COLUMN IF NOT EXISTS track TEXT CHECK (track IN ('true', 'retrospective'));
ALTER TABLE backtest_results ADD COLUMN IF NOT EXISTS horizon TEXT CHECK (horizon IN ('1y', '3y', '5y'));
ALTER TABLE backtest_results ADD COLUMN IF NOT EXISTS regime_returns JSONB NOT NULL DEFAULT '{}';
CREATE UNIQUE INDEX IF NOT EXISTS uq_backtest_results_strategy_track_horizon
    ON backtest_results (strategy, track, horizon)
    WHERE strategy IS NOT NULL AND track IS NOT NULL AND horizon IS NOT NULL;
