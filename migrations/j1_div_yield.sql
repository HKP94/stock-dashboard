-- J-1: 배당수익률(주주환원) — valuation에 div_yield 컬럼 추가.
-- US=yfinance dividendYield, KR=네이버 기업실적분석 시가배당률(둘 다 % 단위, CI-safe).
-- 팩터화(백분위 shareholder_yield)는 export 전용 계산(headline·composite 미변경 — PM 결정).
-- 무배당=0(최하위), 미수집=NULL(중립 제외).
ALTER TABLE valuation ADD COLUMN IF NOT EXISTS div_yield NUMERIC;
