-- I-1: 발굴 스크린 (Phase C — 관심종목 밖 유니버스 경량 스크리닝)
-- US=S&P500+나스닥100, KR=코스피200+코스닥150 (~870). 주간 1회 경량 스크린.
-- 뉴스·LLM·investor_flow 제외(§8 비용규율). KR은 로컬 전용(KRX CI 차단).
-- watchlist quant_scores와 분리(자동수집 무결성 보호). asof별 append 스냅샷(§F7).
-- 점수: 장기=quality0.35+value0.35+growth0.30(Phase B 상수 재사용),
--       모멘텀=가격 모멘텀만(뉴스 sentiment 없음 — 경량 프록시). percentile은 시장 내부.
CREATE TABLE IF NOT EXISTS discovery_screen (
    ticker           TEXT        NOT NULL,
    asof             DATE        NOT NULL,
    market           TEXT        NOT NULL CHECK (market IN ('US', 'KR')),
    name             TEXT,
    source_index     TEXT,                              -- sp500|nasdaq100|kospi200|kosdaq150(콤마 다중)
    in_watchlist     BOOLEAN     NOT NULL DEFAULT FALSE,
    value            NUMERIC,                           -- 0~100 시장 내부 백분위
    quality          NUMERIC,
    growth           NUMERIC,
    momentum         NUMERIC,
    long_term_score  NUMERIC,                           -- q0.35+v0.35+g0.30
    momentum_score   NUMERIC,                           -- 경량: 가격 모멘텀만
    metrics          JSONB       NOT NULL DEFAULT '{}',  -- raw PER/PBR/ROE/growth/return 원값(투명성)
    computed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, asof)
);

CREATE INDEX IF NOT EXISTS idx_discovery_screen_asof ON discovery_screen (asof DESC);
CREATE INDEX IF NOT EXISTS idx_discovery_long ON discovery_screen (asof, long_term_score DESC) WHERE NOT in_watchlist;
CREATE INDEX IF NOT EXISTS idx_discovery_momo ON discovery_screen (asof, momentum_score DESC) WHERE NOT in_watchlist;

COMMENT ON TABLE discovery_screen IS 'Phase C 발굴 스크린(관심종목 밖 대형주 경량 스코어). watchlist quant_scores와 분리. 뉴스·LLM 없음. 승격은 KPH 수동.';
