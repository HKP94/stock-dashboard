-- E-3: stock_note_history 에 active 컬럼 추가
-- 내 판단 삭제 시 물리 삭제 대신 active=false 로 비활성화(데이터 보존 원칙).
-- stock_notes(최신 상태)는 DELETE로 처리하고, 이력만 소프트 삭제.

ALTER TABLE stock_note_history
    ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE;

CREATE INDEX IF NOT EXISTS idx_stock_note_history_active
    ON stock_note_history (ticker, active, created_at DESC, id DESC);
