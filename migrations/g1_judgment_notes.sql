-- G-1: 판단 기록 인프라 (judgment_notes)
-- 대화에서 확정된 투자 판단의 append-only 기록. 세션 간 컨텍스트 승계용.
-- stock_notes(덮어쓰기 최신값)·stock_note_history(ticker 필수 이력)와 목적이 달라 신규 분리.
--   · axis 는 태깅용(3축 합산 금지). stance 는 자유 라벨(ENUM 금지 — 매매지시로 굳지 않게).
--   · UPDATE 로 과거를 덮지 말 것: 새 판단은 새 행 INSERT + 이전 행 superseded_by 갱신.
--   · DELETE 는 전용 role(atlas_note_writer)에 미부여 → append-only 물리 강제(§F7 소급 위조 방지).
CREATE TABLE IF NOT EXISTS judgment_notes (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ticker         text,                              -- NULL = 시장 전체 판단
  created_at     timestamptz NOT NULL DEFAULT now(),-- §F7
  author         text NOT NULL DEFAULT 'claude_pm', -- claude_pm | kph
  axis           text,                              -- quant|consensus|my_judgment|observation (태깅, 합산 아님)
  stance         text,                              -- 자유 라벨(관망/관심/주의). ENUM 금지
  thesis         text NOT NULL,
  rationale      text,                              -- 근거(데이터/축 괴리)
  confidence     text,                              -- 하/중/상 자유
  source_session text,
  superseded_by  bigint REFERENCES judgment_notes(id),
  CONSTRAINT judgment_notes_axis_chk
    CHECK (axis IS NULL OR axis IN ('quant','consensus','my_judgment','observation'))
);

CREATE INDEX IF NOT EXISTS idx_judgment_notes_ticker     ON judgment_notes(ticker);
CREATE INDEX IF NOT EXISTS idx_judgment_notes_created_at ON judgment_notes(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_judgment_notes_live       ON judgment_notes(ticker) WHERE superseded_by IS NULL;

-- COMMENT ON (MCP 스키마 탐색이 읽음)
COMMENT ON TABLE  judgment_notes                IS '대화에서 확정된 투자 판단의 append-only 기록. 세션 간 컨텍스트 승계. UPDATE로 과거 덮지 말 것 — 새 판단은 새 행 + 이전 행 superseded_by 갱신.';
COMMENT ON COLUMN judgment_notes.ticker         IS '종목 티커. NULL = 시장 전체 판단.';
COMMENT ON COLUMN judgment_notes.created_at     IS '판단 시점(§F7 소급 위조 방지).';
COMMENT ON COLUMN judgment_notes.author         IS '판단 주체: claude_pm | kph.';
COMMENT ON COLUMN judgment_notes.axis           IS '연결 축(태깅용, 합산 아님): quant | consensus | my_judgment | observation.';
COMMENT ON COLUMN judgment_notes.stance         IS '자유 텍스트 라벨(관망/관심/주의 등). ENUM 금지 — 매매지시로 굳지 않게.';
COMMENT ON COLUMN judgment_notes.thesis         IS '판단 요지.';
COMMENT ON COLUMN judgment_notes.rationale      IS '근거: 어떤 데이터/축 괴리에 기반했는지.';
COMMENT ON COLUMN judgment_notes.confidence     IS '확신도(하/중/상 등 자유). NULL 허용.';
COMMENT ON COLUMN judgment_notes.source_session IS '어느 대화에서 나온 판단인지 메모.';
COMMENT ON COLUMN judgment_notes.superseded_by  IS '이 판단을 대체한 새 판단의 id. 삭제 대신 이력 보존.';

CREATE OR REPLACE VIEW v_current_judgment AS   -- 라이브 판단 전체(다축·시장전체 보존)
  SELECT * FROM judgment_notes WHERE superseded_by IS NULL;

CREATE OR REPLACE VIEW v_latest_judgment AS    -- 종목별 최신 라이브 1건
  SELECT DISTINCT ON (ticker) * FROM judgment_notes
  WHERE superseded_by IS NULL ORDER BY ticker, created_at DESC;
