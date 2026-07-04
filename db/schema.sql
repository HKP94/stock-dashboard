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
-- 밸류에이션 교차검증 게이트 (H-1)
-- KR 저장 PBR/PER(네이버) vs KRX 공식 대조. flagged=편차 임계 초과("밸류 의심").
-- valuation 원본 불변. 로컬 실행(KRX 로그인, CI 차단). DDL: migrations/h1_valuation_xcheck.sql
-- =============================================================
CREATE TABLE IF NOT EXISTS valuation_xcheck (
    ticker     TEXT        NOT NULL,
    asof       DATE        NOT NULL,
    src_pbr    NUMERIC,
    src_per    NUMERIC,
    ref_pbr    NUMERIC,
    ref_per    NUMERIC,
    pbr_dev    NUMERIC,
    per_dev    NUMERIC,
    flagged    BOOLEAN     NOT NULL DEFAULT FALSE,
    reason     TEXT,
    ref_source TEXT        NOT NULL DEFAULT 'krx',
    checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, asof)
);

CREATE INDEX IF NOT EXISTS idx_valuation_xcheck_asof    ON valuation_xcheck (asof DESC);
CREATE INDEX IF NOT EXISTS idx_valuation_xcheck_flagged ON valuation_xcheck (flagged) WHERE flagged;

-- =============================================================
-- 애널리스트 컨센서스
-- =============================================================
CREATE TABLE IF NOT EXISTS analyst (
    ticker        TEXT    NOT NULL,
    asof          DATE    NOT NULL,
    rating        TEXT,
    rating_label  TEXT,
    rating_score  NUMERIC,
    target_price  NUMERIC,
    upside        NUMERIC,
    eps_fwd       NUMERIC,
    n_analysts    INT,
    source        TEXT    NOT NULL DEFAULT 'legacy',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, asof)
);

CREATE TABLE IF NOT EXISTS analyst_views (
    ticker      TEXT        NOT NULL,
    asof        DATE        NOT NULL,
    stance      TEXT        NOT NULL CHECK (stance IN ('bull', 'bear')),
    point       TEXT        NOT NULL,
    source      TEXT        NOT NULL,
    source_url  TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (ticker, asof, stance, point, source, source_url)
);

CREATE INDEX IF NOT EXISTS idx_analyst_views_lookup
    ON analyst_views (ticker, stance, asof DESC, created_at DESC);

CREATE TABLE IF NOT EXISTS manual_research_entries (
    id              BIGSERIAL   PRIMARY KEY,
    ticker          TEXT        NOT NULL,
    raw_text        TEXT        NOT NULL,
    source          TEXT,
    source_url      TEXT,
    inferred_source TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_manual_research_entries_ticker
    ON manual_research_entries (ticker, created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS manual_research_horizons (
    id                    BIGSERIAL   PRIMARY KEY,
    entry_id              BIGINT      NOT NULL REFERENCES manual_research_entries(id) ON DELETE CASCADE,
    horizon               TEXT        NOT NULL CHECK (horizon IN ('short', 'mid', 'long')),
    attractiveness_label  TEXT        NOT NULL CHECK (attractiveness_label IN ('매력적', '다소 매력적', '중립', '다소 비매력적', '비매력적')),
    rationale             TEXT        NOT NULL,
    is_user_confirmed     BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (entry_id, horizon)
);

CREATE TABLE IF NOT EXISTS manual_research_points (
    id                BIGSERIAL   PRIMARY KEY,
    entry_id          BIGINT      NOT NULL REFERENCES manual_research_entries(id) ON DELETE CASCADE,
    stance            TEXT        NOT NULL CHECK (stance IN ('bull', 'bear')),
    point             TEXT        NOT NULL,
    source_label      TEXT,
    source_url        TEXT,
    is_user_confirmed BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_manual_research_points_entry
    ON manual_research_points (entry_id, stance, created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS manual_research_consensus (
    entry_id            BIGINT      PRIMARY KEY REFERENCES manual_research_entries(id) ON DELETE CASCADE,
    target_price        NUMERIC,
    rating_label        TEXT,
    rating_score        NUMERIC,
    is_user_confirmed   BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS market_view_manual (
    id            BIGSERIAL   PRIMARY KEY,
    asof          DATE        NOT NULL,
    scope         TEXT        NOT NULL DEFAULT 'market' CHECK (scope IN ('market')),
    raw_text      TEXT        NOT NULL,
    bull_scenario TEXT,
    bear_scenario TEXT,
    source        TEXT,
    source_url    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_market_view_manual_asof
    ON market_view_manual (asof DESC, created_at DESC, id DESC);

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

CREATE TABLE IF NOT EXISTS ticker_drivers (
    ticker        TEXT        NOT NULL,
    driver_code   TEXT        NOT NULL,
    driver_name   TEXT        NOT NULL,
    driver_source TEXT        NOT NULL,
    weight        SMALLINT    NOT NULL CHECK (weight BETWEEN 1 AND 5),
    origin        TEXT        NOT NULL CHECK (origin IN ('auto', 'user')),
    rationale     TEXT        NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, driver_code)
);

CREATE INDEX IF NOT EXISTS idx_ticker_drivers_ticker_origin
    ON ticker_drivers (ticker, origin, updated_at DESC);

CREATE TABLE IF NOT EXISTS driver_prices (
    driver_code   TEXT        NOT NULL,
    asof          DATE        NOT NULL,
    close         NUMERIC     NOT NULL,
    source        TEXT        NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (driver_code, asof)
);

CREATE INDEX IF NOT EXISTS idx_driver_prices_asof
    ON driver_prices (driver_code, asof DESC);

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
    beta        NUMERIC,  -- 신규-A1: 자국 지수 대비 베타(별도 시장민감도 팩터, composite 미합산)
    market_corr NUMERIC,  -- 신규-A1: 자국 지수 대비 상관계수
    PRIMARY KEY (ticker, asof)
);

-- 신규-A1 컬럼 추가(기존 DB 멱등 마이그레이션)
ALTER TABLE quant_scores ADD COLUMN IF NOT EXISTS beta        NUMERIC;
ALTER TABLE quant_scores ADD COLUMN IF NOT EXISTS market_corr NUMERIC;

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

CREATE TABLE IF NOT EXISTS stock_action_advice (
    ticker             TEXT        NOT NULL,
    asof               DATE        NOT NULL,
    direction          TEXT        NOT NULL CHECK (direction IN ('매수', '비중확대', '유지', '비중축소', '매도')),
    current_weight     NUMERIC,
    target_weight_low  NUMERIC,
    target_weight_high NUMERIC,
    weight_action      TEXT        NOT NULL CHECK (weight_action IN ('늘림', '유지', '줄임')),
    entry_zone         TEXT,
    exit_zone          TEXT,
    confidence         TEXT        NOT NULL CHECK (confidence IN ('상', '중', '하')),
    rationale          TEXT        NOT NULL,
    supporting_factors JSONB       NOT NULL DEFAULT '[]'::jsonb,
    opposing_factors   JSONB       NOT NULL DEFAULT '[]'::jsonb,
    divergence_note    TEXT,
    model              TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- 신규-D: 보유성격 + 집중 리스크 관찰 (비중 컬럼은 보존, 표시에서만 제외)
    hold_character           TEXT CHECK (hold_character IN ('장기보유', '모멘텀', '단기', '정보부족')),
    hold_character_secondary JSONB NOT NULL DEFAULT '[]'::jsonb,
    hold_character_basis     JSONB NOT NULL DEFAULT '[]'::jsonb,
    concentration_note       TEXT,
    -- 신규-A2: 매력도 3축 종합 등급(결론 레이어, composite 미합산)
    grade                    TEXT CHECK (grade IN ('매수', '관망', '축소')),
    grade_confidence         TEXT CHECK (grade_confidence IN ('상', '중', '하')),
    grade_basis              JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (ticker, asof)
);

-- 신규-D 컬럼 추가(기존 DB 멱등 마이그레이션 — 기존 컬럼·데이터 보존)
ALTER TABLE stock_action_advice ADD COLUMN IF NOT EXISTS hold_character TEXT;
ALTER TABLE stock_action_advice ADD COLUMN IF NOT EXISTS hold_character_secondary JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE stock_action_advice ADD COLUMN IF NOT EXISTS hold_character_basis JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE stock_action_advice ADD COLUMN IF NOT EXISTS concentration_note TEXT;
-- 신규-A2 컬럼 추가(멱등)
ALTER TABLE stock_action_advice ADD COLUMN IF NOT EXISTS grade TEXT;
ALTER TABLE stock_action_advice ADD COLUMN IF NOT EXISTS grade_confidence TEXT;
ALTER TABLE stock_action_advice ADD COLUMN IF NOT EXISTS grade_basis JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_stock_action_advice_lookup
    ON stock_action_advice (ticker, asof DESC, created_at DESC);

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
-- 판단 기록 (G-1 — 대화에서 확정된 판단의 append-only 로그, 세션 간 승계)
-- 전용 role atlas_note_writer 만 쓰기(DELETE 미부여). DDL: migrations/g1_judgment_notes.sql
-- role: db/atlas_note_writer_role.sql (수동 1회 실행)
-- =============================================================
CREATE TABLE IF NOT EXISTS judgment_notes (
    id             BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticker         TEXT,                               -- NULL = 시장 전체 판단
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(), -- §F7
    author         TEXT        NOT NULL DEFAULT 'claude_pm',  -- claude_pm | kph
    axis           TEXT,                               -- quant|consensus|my_judgment|observation (태깅, 합산 금지)
    stance         TEXT,                               -- 자유 라벨(관망/관심/주의). ENUM 금지
    thesis         TEXT        NOT NULL,
    rationale      TEXT,
    confidence     TEXT,                               -- 하/중/상 자유
    source_session TEXT,
    superseded_by  BIGINT      REFERENCES judgment_notes(id),
    CONSTRAINT judgment_notes_axis_chk
        CHECK (axis IS NULL OR axis IN ('quant', 'consensus', 'my_judgment', 'observation'))
);

CREATE INDEX IF NOT EXISTS idx_judgment_notes_ticker     ON judgment_notes (ticker);
CREATE INDEX IF NOT EXISTS idx_judgment_notes_created_at ON judgment_notes (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_judgment_notes_live       ON judgment_notes (ticker) WHERE superseded_by IS NULL;

CREATE OR REPLACE VIEW v_current_judgment AS   -- 라이브 판단 전체(다축·시장전체 보존)
    SELECT * FROM judgment_notes WHERE superseded_by IS NULL;

CREATE OR REPLACE VIEW v_latest_judgment AS    -- 종목별 최신 라이브 1건
    SELECT DISTINCT ON (ticker) * FROM judgment_notes
    WHERE superseded_by IS NULL ORDER BY ticker, created_at DESC;

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

-- =============================================================
-- 시장 매력도 점수 (Wave 5-B) — 시장 단위 asof 이력, 분석 소유
-- =============================================================
CREATE TABLE IF NOT EXISTS market_score (
    asof            DATE        NOT NULL,
    region          TEXT        NOT NULL CHECK (region IN ('KR', 'US')),
    score           NUMERIC     NOT NULL,   -- 0~100 (divergence 시 50쪽 수축)
    direction       TEXT        NOT NULL CHECK (direction IN ('강세', '중립', '약세')),
    confidence      TEXT        NOT NULL CHECK (confidence IN ('상', '중', '하')),
    components      JSONB       NOT NULL DEFAULT '{}'::jsonb,  -- 서브스코어·근거 분해
    divergence_note TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (asof, region)
);

CREATE INDEX IF NOT EXISTS idx_market_score_lookup
    ON market_score (region, asof DESC);
