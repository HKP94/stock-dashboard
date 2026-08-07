-- R7: 실적 발표 일정·결과 캘린더
-- 멱등성: CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS
--
-- 목적 ① 임박 실적을 DB로 조회(수기 추적 제거) ② 발표 경과 종목만 좁게 재수집하는 T+1 트리거의 기준표.
-- §F7: scheduled_date는 미래 '일정'이라 룩어헤드가 아니다. 단 consensus_*·actual_eps를
--      과거 시점 점수·백테스트에 소급 반영하는 것은 금지(표시·트리거 전용).

CREATE TABLE IF NOT EXISTS earnings_calendar (
    ticker         TEXT        NOT NULL,
    fiscal_period  TEXT        NOT NULL,   -- '2026Q2' 형식(분기 종료 기준)
    scheduled_date DATE        NOT NULL,   -- 발표(예정)일. KR은 법정기한 추정치일 수 있음
    confirmed      BOOLEAN     NOT NULL DEFAULT FALSE,  -- true=소스가 확정 제공, false=추정
    reported       BOOLEAN     NOT NULL DEFAULT FALSE,  -- true=발표 완료(실적 수신)
    consensus_eps  NUMERIC,
    consensus_rev  NUMERIC,
    actual_eps     NUMERIC,                -- 발표 후 실제 EPS
    surprise_pct   NUMERIC,                -- (실제-컨센)/|컨센| ×100, 소스 제공값
    source         TEXT        NOT NULL,   -- 'yfinance' | 'dart'
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, fiscal_period)
);

CREATE INDEX IF NOT EXISTS earnings_calendar_scheduled
    ON earnings_calendar (scheduled_date DESC);

COMMENT ON TABLE earnings_calendar IS
    'R7: 종목별 실적 발표 일정·결과. US=yfinance earnings_dates, KR=DART 정기보고서 접수(사후 감지).';
COMMENT ON COLUMN earnings_calendar.confirmed IS
    'true=소스가 확정 발표일 제공(US). false=추정(KR 법정기한 등) — 화면에서 구분 표기.';
COMMENT ON COLUMN earnings_calendar.reported IS
    'true=발표 완료. T+1 재수집 트리거가 이 플래그와 fundamentals 적재 여부를 대조한다.';
