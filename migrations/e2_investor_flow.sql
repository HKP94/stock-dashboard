-- E-2: KR 투자자 수급 테이블
-- 멱등성: ADD COLUMN IF NOT EXISTS / CREATE TABLE IF NOT EXISTS

CREATE TABLE IF NOT EXISTS investor_flow (
    ticker              VARCHAR(20) NOT NULL,
    date                DATE        NOT NULL,
    foreign_net         NUMERIC,            -- 외국인합계 당일 순매수 (원)
    institution_net     NUMERIC,            -- 기관합계 당일 순매수 (원)
    individual_net      NUMERIC,            -- 개인 당일 순매수 (원)
    foreign_3d_sum      NUMERIC,            -- 외국인 최근 3거래일 합계 (신규-F 추적)
    institution_3d_sum  NUMERIC,            -- 기관 최근 3거래일 합계
    foreign_signal      VARCHAR(20),        -- 매수우호/중립/매도우세
    institution_signal  VARCHAR(20),        -- 매수우호/중립/매도우세
    combined_signal     VARCHAR(20),        -- 수급_강세/수급_약세/수급_혼조/중립
    PRIMARY KEY (ticker, date)
);

CREATE INDEX IF NOT EXISTS investor_flow_ticker_date
    ON investor_flow (ticker, date DESC);
