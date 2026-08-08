# Wave 4-C Ticker Drivers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add ticker-specific driver mapping, reusable driver proxy prices, manual CRUD, and stock-detail driver cards without duplicating shared market data.

**Architecture:** Persist user/auto driver mappings in `ticker_drivers`, store only driver-specific proxy series in `driver_prices`, and reuse `macro_indicators`/`index_daily` for shared series such as WTI. Export joins driver mappings to the best available price source and the stock detail tab renders support/oppose toned cards plus local editing controls.

**Tech Stack:** Python 3.12, psycopg, FastAPI, React+Vite, Gemini 2.5 Flash, yfinance.

## Global Constraints

- 시크릿 DB/로그/url 저장 금지.
- 드라이버 자동 매핑은 추정일 뿐, 사용자 수정 우선(origin='user' 보호).
- 중복 가격 수집 금지(macro_indicators/index_daily 재사용).
- export는 종목별 최신 조회만 (글로벌 max(asof) 금지).
- 매력도 3축 합산 금지, 자동 주문 실행 금지.
- 드라이버 함의는 support/oppose 톤, 매매 단정 금지.
- CORS allow_methods에 PATCH·DELETE·OPTIONS 필수.
- DB NUMERIC은 읽기 경계에서 float 변환.
- 단계별 커밋/롤백.

---

### Task 1: Contracts and failing tests
- [ ] Add failing tests for driver row grouping, local API CRUD, and dotenv loading in `ingest_macro.py`.
- [ ] Add schema models for `TickerDriverRow`, `DriverPriceRow`, `DriverSuggestionOutput`.

### Task 2: Persistence and ingestion
- [ ] Add `ticker_drivers` and `driver_prices` tables plus DB helpers.
- [ ] Implement `src/ingest_drivers.py` for proxy price collection with shared-source reuse rules.
- [ ] Add `load_dotenv()` support to `src/ingest_macro.py`.

### Task 3: Auto mapping and API
- [ ] Add Gemini prompt/parser plus on-demand auto mapping writer that preserves `origin='user'` rows.
- [ ] Extend `src/local_api.py` with driver CRUD and auto-map endpoints plus data.json patch helper.

### Task 4: Export and UI
- [ ] Export stock-level driver cards with series, source badges, and support/oppose implication text.
- [ ] Render stock detail “핵심 동인” card with add/edit/delete controls.

### Task 5: Verification, merge, schema apply, smoke
- [ ] Run targeted pytest, dashboard tests, and build.
- [ ] Push PR, merge, sync main, apply schema, run driver/macro smoke, and report counts.
