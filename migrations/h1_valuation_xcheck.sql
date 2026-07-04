-- H-1: 밸류에이션 교차검증 게이트 (valuation_xcheck)
-- KR 종목의 저장 PBR/PER(네이버 원천)를 KRX 공식 펀더멘털과 대조해 편차를 flag.
-- 목적: 틀린 밸류가 판단·2렌즈·컨센 괴리로 조용히 전파되는 것 차단.
-- valuation 테이블은 건드리지 않는다(무결성 보호). 별도 일 단위 스냅샷(append-only, §F7 오늘만).
CREATE TABLE IF NOT EXISTS valuation_xcheck (
    ticker     TEXT        NOT NULL,
    asof       DATE        NOT NULL,          -- 대조 기준일(KRX 데이터 일자). 과거 소급 생성 금지.
    src_pbr    NUMERIC,                        -- 저장(네이버) PBR
    src_per    NUMERIC,                        -- 저장(네이버) PER(trailing)
    ref_pbr    NUMERIC,                        -- 대조 원천(KRX 공식) PBR
    ref_per    NUMERIC,                        -- 대조 원천(KRX 공식) PER
    pbr_dev    NUMERIC,                        -- |src-ref|/ref (없으면 NULL)
    per_dev    NUMERIC,
    flagged    BOOLEAN     NOT NULL DEFAULT FALSE,
    reason     TEXT,                           -- flag 사유(사람이 읽는 1줄)
    ref_source TEXT        NOT NULL DEFAULT 'krx',
    checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, asof)
);

CREATE INDEX IF NOT EXISTS idx_valuation_xcheck_asof    ON valuation_xcheck (asof DESC);
CREATE INDEX IF NOT EXISTS idx_valuation_xcheck_flagged ON valuation_xcheck (flagged) WHERE flagged;

COMMENT ON TABLE valuation_xcheck IS 'KR 밸류(네이버) vs KRX 공식 교차검증 스냅샷. flagged=편차 임계 초과. valuation 원본은 불변.';
