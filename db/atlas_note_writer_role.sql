-- atlas_note_writer — 판단 기록 전용 쓰기 role (물리적 2차 방어).
--
-- ⚠️ 이 파일은 migrations/ 가 아니다 — apply_migrations.py(CI glob)로 자동 실행하지 않는다.
--    CREATE ROLE 는 소유자/CREATEROLE 권한이 필요하고 비밀번호를 코드에 남기면 안 되므로,
--    **KPH(또는 소유자)가 Supabase SQL 에디터에서 1회 수동 실행**한다.
--    실행 후 반드시: ALTER ROLE atlas_note_writer PASSWORD '<대시보드에서 설정>';  (평문 커밋 금지)
--
-- 목적: 판단 기록 계열 테이블만 INSERT/UPDATE, 나머지(자동 수집)는 SELECT 전용.
--       DELETE 미부여 = append-only 물리 강제. prices_daily 등 수집 테이블 쓰기 시 DB가 거부.
--
-- 붙이는 법(§ 아키텍처 경보): 현 공식 Supabase MCP는 관리 토큰 기반이라 이 role 로 다운스코프 불가.
--   물리 방어가 실제로 걸리려면 **쓰기 경로를 별도 Postgres 접속문자열 MCP**(atlas_note_writer 자격 +
--   Transaction Pooler 6543)로 붙여야 한다. READ = 현 공식 MCP 유지, WRITE = 이 role 커넥터.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'atlas_note_writer') THEN
    CREATE ROLE atlas_note_writer LOGIN NOINHERIT PASSWORD 'CHANGE_ME_IN_DASHBOARD';
  END IF;
END $$;

GRANT USAGE ON SCHEMA public TO atlas_note_writer;

-- 읽기: 전 테이블 SELECT (자동 수집은 여기까지 — 쓰기 미부여)
GRANT SELECT ON ALL TABLES IN SCHEMA public TO atlas_note_writer;

-- 쓰기: 판단 기록 계열만 (DELETE 미부여 = append-only 강제)
GRANT INSERT, UPDATE ON
  judgment_notes, stock_notes, stock_note_history, research_items,
  manual_research_entries, manual_research_consensus,
  manual_research_horizons, manual_research_points, market_view_manual
TO atlas_note_writer;

-- 시퀀스 USAGE (serial/nextval 기본값 INSERT 위해)
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO atlas_note_writer;

-- 미래 테이블 기본 SELECT-only (신규 자동 수집 테이블 자동 보호)
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  GRANT SELECT ON TABLES TO atlas_note_writer;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO atlas_note_writer;
