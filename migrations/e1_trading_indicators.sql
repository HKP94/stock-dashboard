-- E-1: 트레이딩 지표 컬럼 추가 (indicators_daily)
-- MACD(12,26,9) / 볼린저(20,2) / 스토캐스틱(14,3) / ATR(14) / 거래량비율
ALTER TABLE indicators_daily
  ADD COLUMN IF NOT EXISTS macd_line   NUMERIC,
  ADD COLUMN IF NOT EXISTS macd_signal NUMERIC,
  ADD COLUMN IF NOT EXISTS macd_hist   NUMERIC,
  ADD COLUMN IF NOT EXISTS bb_upper    NUMERIC,
  ADD COLUMN IF NOT EXISTS bb_lower    NUMERIC,
  ADD COLUMN IF NOT EXISTS bb_pct      NUMERIC,
  ADD COLUMN IF NOT EXISTS stoch_k     NUMERIC,
  ADD COLUMN IF NOT EXISTS stoch_d     NUMERIC,
  ADD COLUMN IF NOT EXISTS vol_ratio20 NUMERIC,
  ADD COLUMN IF NOT EXISTS atr14       NUMERIC;

-- trading_signal 저장 컬럼 추가 (E-1 신규-F 적중률 추적 토대)
ALTER TABLE indicators_daily
  ADD COLUMN IF NOT EXISTS trading_signal VARCHAR(20),
  ADD COLUMN IF NOT EXISTS trading_signal_score SMALLINT;
