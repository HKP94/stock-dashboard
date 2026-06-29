-- F-1: 신호 적중률 추적 테이블 (신규-F)
-- A2 등급(매수/관망/축소)의 전향 자기검증 저장소.
-- signal_type으로 E1/E2/5-B 신호 확장 가능.
CREATE TABLE IF NOT EXISTS signal_grade_track (
    id            BIGSERIAL PRIMARY KEY,
    signal_type   TEXT        NOT NULL,          -- 'A2_grade' | 'E1_trading' | 'E2_investor' | '5B_market'
    ticker        TEXT        NOT NULL,          -- 종목 티커 (시장 신호면 'KR'/'US' pseudo)
    asof          DATE        NOT NULL,          -- 신호 생성일
    grade         TEXT        NOT NULL,          -- 원 신호 값 ('매수'/'관망'/'축소')
    grade_conf    TEXT,                          -- 신뢰도 (있으면)
    n_days        INTEGER     NOT NULL,          -- 5 | 20 | 60
    entry_date    DATE,                          -- 진입일 (asof 다음 거래일)
    entry_price   NUMERIC,                       -- 진입가 (종가)
    exit_date     DATE,                          -- 청산일 (entry_date + n_days 영업일)
    exit_price    NUMERIC,                       -- 청산가 (종가)
    bench_entry   NUMERIC,                       -- 벤치마크 진입가
    bench_exit    NUMERIC,                       -- 벤치마크 청산가
    raw_return    NUMERIC,                       -- exit/entry - 1
    bench_return  NUMERIC,                       -- 벤치마크 동기간 수익률
    excess_return NUMERIC,                       -- raw_return - bench_return
    hit_excess    BOOLEAN,                       -- excess_return 기준 적중 (pending이면 NULL)
    hit_raw       BOOLEAN,                       -- raw_return > 0 기준 적중 (pending이면 NULL)
    pending       BOOLEAN     NOT NULL DEFAULT TRUE,  -- N일 미경과면 TRUE
    computed_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (signal_type, ticker, asof, n_days)
);

CREATE INDEX IF NOT EXISTS idx_sgt_type_ticker ON signal_grade_track (signal_type, ticker);
CREATE INDEX IF NOT EXISTS idx_sgt_asof        ON signal_grade_track (asof);
CREATE INDEX IF NOT EXISTS idx_sgt_pending     ON signal_grade_track (signal_type, pending);
