# Wave 4-D-1 Analyst Consensus & Views Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend ATLAS backend so daily runs collect normalized analyst consensus plus evidence-backed bull/bear analyst views, then export both per ticker without breaking existing contracts.

**Architecture:** Reuse the existing `analyst` consensus path instead of creating a duplicate table, because the repo already ingests and exports analyst data through that route. Add one new `analyst_views` store for structured bull/bear evidence extracted from existing news/context through the Gemini wrapper that already enforces timeout and budget guards.

**Tech Stack:** Python 3.12, psycopg3, pydantic v2, pytest, Postgres schema SQL, existing Gemini wrapper in `src/enrich_gemini.py`

## Global Constraints

- 절대규칙(시크릿 금지·자동 주문 실행 금지·데이터 계약 준수) 준수
- 기존 컨센서스 경로 재사용, 중복 테이블·중복 수집 금지
- 논거는 실제 출처 근거만 저장하고 `source_url` 보존
- Gemini 호출은 기존 timeout·재시도·배치예산 규칙을 그대로 따른다
- export는 종목별 최신 조회만 사용하고 글로벌 `max(asof)`를 쓰지 않는다
- DB NUMERIC은 읽기 경계에서 float 변환
- DB 쓰기는 단계별 커밋/롤백
- PRD §11/변경이력·CLAUDE.md 갱신

---

### Task 1: 계약과 스키마 확장

**Files:**
- Modify: `src/schemas.py`
- Modify: `src/db.py`
- Modify: `db/schema.sql`
- Modify: `PRD.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: existing `AnalystRow`, `upsert_analyst`, `analyst` table
- Produces:
  - `AnalystRow` extended with `rating_label`, `rating_score`, `eps_fwd`, `source`, `created_at`
  - `AnalystViewRow`
  - `upsert_analyst_views(conn, rows: list[AnalystViewRow]) -> None`

- [ ] Add failing tests for the new row models and DB upsert payload shape
- [ ] Extend the canonical `analyst` store instead of creating a duplicate consensus table
- [ ] Add new `analyst_views` DDL with `(ticker, asof, stance, point, source, source_url)` uniqueness
- [ ] Update PRD/CLAUDE docs so the new contract is explicit

### Task 2: 컨센서스 정규화

**Files:**
- Modify: `src/ingest_kr.py`
- Modify: `src/ingest_us.py`
- Test: `tests/test_ingest_kr.py`
- Test: `tests/test_ingest_us.py` (create if needed)

**Interfaces:**
- Consumes: raw Naver/FnGuide/yfinance consensus fields
- Produces:
  - normalized `rating_label`
  - normalized `rating_score`
  - normalized `eps_fwd`
  - `source` on every `AnalystRow`

- [ ] Write failing tests for KR/US rating normalization and source tagging
- [ ] Implement the smallest normalization helpers needed for current free sources
- [ ] Preserve existing upside behavior for legacy consumers while adding the new fields

### Task 3: 애널리스트 논거 추출

**Files:**
- Modify: `src/enrich_gemini.py`
- Modify: `src/run_pipeline.py`
- Test: `tests/test_enrich_gemini.py`

**Interfaces:**
- Consumes: `news_raw`, `news_analysis`, `ticker_context`, Gemini wrapper
- Produces:
  - `extract_analyst_views_batch(conn) -> tuple[int, list[dict]]`
  - structured rows for `analyst_views`

- [ ] Add failing tests for parsing/extracting bull/bear rows with source URLs
- [ ] Implement a strict JSON schema for analyst-view extraction with no invented evidence
- [ ] Integrate the step into the daily pipeline after news enrichment with commit/rollback isolation

### Task 4: export 및 조립 레이어 보강

**Files:**
- Modify: `src/export_dashboard_data.py`
- Modify: `src/assemble.py` only if needed for contract consistency
- Test: `tests/test_export_safety.py`
- Test: `tests/test_assemble.py` only if assemble contract changes

**Interfaces:**
- Consumes: latest per-ticker `analyst` rows and grouped `analyst_views`
- Produces:
  - stock payload `consensus`
  - stock payload `analystViews = { bull: [], bear: [] }`

- [ ] Add failing tests proving per-ticker latest lookup and grouped bull/bear export
- [ ] Implement export fields without breaking current `tp/up/rating` compatibility
- [ ] Keep all latest-selection queries partitioned by ticker

### Task 5: 검증, 스모크, 머지 준비

**Files:**
- Modify only as required by test fixes

**Interfaces:**
- Consumes: updated backend code, docs, schema
- Produces: verified branch ready for schema apply and merge

- [ ] Run targeted pytest red/green cycles for each new behavior
- [ ] Run end-to-end smoke on the export path
- [ ] If credentials/network are available, apply schema and complete push/PR/merge; otherwise leave exact prepared state in the report
