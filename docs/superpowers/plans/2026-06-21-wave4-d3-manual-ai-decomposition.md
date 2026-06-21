# Wave 4-D-3 Manual AI Decomposition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 종목/시장 자유 텍스트 수동 입력을 Gemini로 분해해 저장하고, 기존 자동 수집·내 판단과 분리된 `AI 분해 분석` 레이어로 표시한다.

**Architecture:** 수동 입력은 부모(`manual_research_entries`)와 자식(`manual_research_horizons`, `manual_research_points`, `manual_research_consensus`) 구조로 분리 저장하고, 시장 입력은 `market_view_manual`에 별도 저장한다. raw_text 재분해는 AI 생성분만 갱신하고 `is_user_confirmed=true` 항목은 보호한다. export는 최신 1건 + 이력을 분리 제공하고, UI는 리서치/종목상세/시장전망 탭에서 `내 판단`, `AI 분해 분석`, `자동 수집`을 나란히 노출한다.

**Tech Stack:** Python 3.12, FastAPI, psycopg3, pydantic v2, React 19 + Vite, Node test runner, pytest, Gemini JSON schema parsing.

## Global Constraints

- 시크릿 금지, 자동 주문 실행 금지, 데이터 계약 준수.
- `stock_notes` / `stock_note_history`는 건드리지 않는다.
- `manual_research_horizons.attractiveness`는 숫자 점수 금지, `label + rationale`만 저장.
- raw_text 변경 시 재분해 허용, 단 `is_user_confirmed=false` 행만 DELETE 후 재삽입하고 `true` 행은 보호.
- `UNIQUE(entry_id, horizon)` 충돌 시 사용자 확정값 우선.
- `aiDecompositionSummary`는 최신 entry id, 단/중/장 label, 논거 개수 정도의 얇은 파생만 포함하고 단일 점수 합산 금지.
- 상위 모델은 수동 분해에만 사용, 대량 뉴스 선별은 Flash-Lite 유지.
- origin='user' 성격 자료는 자동 재생성이 덮어쓰지 못한다.
- export는 종목별 최신 조회만 사용, 글로벌 `max(asof)` 금지.
- CORS `allow_methods`에 PATCH/DELETE/OPTIONS 포함.
- DB NUMERIC은 읽기 경계에서 float 변환.
- DB 쓰기는 단계별 commit/rollback.
- raw_text 전체는 DB 저장만 허용, 로그에는 길이/해시만 남긴다.
- PRD §11/변경이력과 CLAUDE.md를 마지막에 갱신한다.

---

### Task 1: DDL, schemas, DB helpers for manual AI decomposition

**Files:**
- Modify: `db/schema.sql`
- Modify: `src/schemas.py`
- Modify: `src/db.py`
- Test: `tests/test_manual_research_schema.py`

**Interfaces:**
- Consumes: existing `get_conn`, psycopg upsert patterns, existing schema conventions.
- Produces:
  - `ManualResearchEntryRow`
  - `ManualResearchHorizonRow`
  - `ManualResearchPointRow`
  - `ManualResearchConsensusRow`
  - `MarketViewManualRow`
  - DB helpers: `insert_manual_research_entry(...)`, `replace_manual_research_ai_rows(...)`, `update_manual_research_horizon(...)`, `update_manual_research_point(...)`, `upsert_manual_research_consensus(...)`, `insert_market_view_manual(...)`

- [ ] **Step 1: Write the failing test**

```python
from src.schemas import ManualResearchEntryRow, ManualResearchHorizonRow, ManualResearchPointRow


def test_manual_research_horizon_requires_label_not_numeric() -> None:
    row = ManualResearchHorizonRow(
        entry_id=1,
        horizon="short",
        attractiveness_label="매력적",
        rationale="실적 모멘텀이 3개월 내 개선될 가능성을 언급했다.",
    )

    assert row.attractiveness_label == "매력적"
```

```python
from pathlib import Path


def test_schema_declares_manual_research_tables() -> None:
    schema = Path("db/schema.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS manual_research_entries" in schema
    assert "CREATE TABLE IF NOT EXISTS manual_research_horizons" in schema
    assert "CREATE TABLE IF NOT EXISTS manual_research_points" in schema
    assert "CREATE TABLE IF NOT EXISTS manual_research_consensus" in schema
    assert "CREATE TABLE IF NOT EXISTS market_view_manual" in schema
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_manual_research_schema.py`
Expected: FAIL with missing row models and/or missing DDL table definitions.

- [ ] **Step 3: Write minimal implementation**

```python
class ManualResearchEntryRow(BaseModel):
    ticker: str
    raw_text: str
    source: Optional[str] = None
    source_url: Optional[str] = None
    inferred_source: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ManualResearchHorizonRow(BaseModel):
    entry_id: int
    horizon: Literal["short", "mid", "long"]
    attractiveness_label: Literal["매력적", "다소 매력적", "중립", "다소 비매력적", "비매력적"]
    rationale: str
    is_user_confirmed: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
```

```sql
CREATE TABLE IF NOT EXISTS manual_research_entries (
  id BIGSERIAL PRIMARY KEY,
  ticker TEXT NOT NULL,
  raw_text TEXT NOT NULL,
  source TEXT,
  source_url TEXT,
  inferred_source TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/test_manual_research_schema.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add db/schema.sql src/schemas.py src/db.py tests/test_manual_research_schema.py
git commit -m "feat: add manual research storage schema"
```

### Task 2: Gemini manual decomposition parser and overwrite-protection logic

**Files:**
- Modify: `src/enrich_gemini.py`
- Modify: `src/schemas.py`
- Modify: `src/db.py`
- Test: `tests/test_manual_research_decomposition.py`

**Interfaces:**
- Consumes: `ManualResearch*Row` models from Task 1, Gemini timeout/budget helpers, existing JSON parsing conventions.
- Produces:
  - `_build_manual_research_prompt(...) -> str`
  - `_parse_manual_research_output(text: str) -> ManualResearchOutput`
  - `_replace_ai_generated_manual_rows(conn, entry_id, payload) -> None`
  - `_build_market_manual_prompt(...) -> str`
  - `_parse_market_manual_output(text: str) -> MarketManualOutput`

- [ ] **Step 1: Write the failing test**

```python
import json

from src.enrich_gemini import _parse_manual_research_output


def test_parse_manual_research_output_returns_three_horizons_and_both_stances() -> None:
    payload = _parse_manual_research_output(json.dumps({
        "inferredSource": "메리츠증권",
        "consensus": {"targetPrice": 120000, "ratingLabel": "매수", "ratingScore": 1.0},
        "bullPoints": [{"point": "HBM 수요 확대", "sourceLabel": "메리츠증권", "sourceUrl": "https://example.com/bull"}],
        "bearPoints": [{"point": "단기 밸류 부담", "sourceLabel": "메리츠증권", "sourceUrl": "https://example.com/bear"}],
        "horizons": [
            {"horizon": "short", "attractivenessLabel": "다소 매력적", "rationale": "단기 실적 개선 기대"},
            {"horizon": "mid", "attractivenessLabel": "매력적", "rationale": "중기 제품 믹스 개선"},
            {"horizon": "long", "attractivenessLabel": "중립", "rationale": "장기 경쟁 심화 가능성"},
        ],
    }, ensure_ascii=False))

    assert [item.horizon for item in payload.horizons] == ["short", "mid", "long"]
    assert payload.bear_points[0].point == "단기 밸류 부담"
```

```python
from src.db import replace_manual_research_ai_rows


def test_replace_manual_research_ai_rows_keeps_user_confirmed_records() -> None:
    # fake conn/cursor asserts DELETE filters is_user_confirmed = FALSE
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_manual_research_decomposition.py`
Expected: FAIL because parser/protection helpers do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
class ManualResearchHorizonOut(BaseModel):
    horizon: Literal["short", "mid", "long"]
    attractivenessLabel: Literal["매력적", "다소 매력적", "중립", "다소 비매력적", "비매력적"]
    rationale: str
```

```python
def _replace_ai_generated_manual_rows(conn, entry_id: int, payload: ManualResearchOutput) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM manual_research_horizons WHERE entry_id=%s AND is_user_confirmed=FALSE",
            (entry_id,),
        )
        cur.execute(
            "DELETE FROM manual_research_points WHERE entry_id=%s AND is_user_confirmed=FALSE",
            (entry_id,),
        )
    # reinsert AI generated rows only for non-user-confirmed slots
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/test_manual_research_decomposition.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/enrich_gemini.py src/schemas.py src/db.py tests/test_manual_research_decomposition.py
git commit -m "feat: add manual research decomposition parser"
```

### Task 3: local_api CRUD for manual research and market manual views

**Files:**
- Modify: `src/local_api.py`
- Modify: `src/db.py`
- Test: `tests/test_local_api_manual_research.py`
- Test: `tests/test_local_api_manual_market.py`
- Test: `tests/test_local_api_cors.py`

**Interfaces:**
- Consumes: Task 1 row models, Task 2 parser/write helpers.
- Produces:
  - `ManualResearchIn`, `ManualResearchPatch`, `MarketManualIn`, `MarketManualPatch`
  - `POST /api/manual-research`
  - `GET /api/manual-research/{ticker}`
  - `PATCH /api/manual-research/{entry_id}`
  - `DELETE /api/manual-research/{entry_id}`
  - `POST /api/manual-market-view`
  - `GET /api/manual-market-view`
  - `PATCH /api/manual-market-view/{id}`
  - `DELETE /api/manual-market-view/{id}`

- [ ] **Step 1: Write the failing test**

```python
from src.local_api import ManualResearchPatch


def test_manual_research_patch_requires_any_supported_field() -> None:
    ManualResearchPatch()
```

```python
def test_manual_research_patch_raw_text_marks_redecomposition_path() -> None:
    from src.local_api import _patch_manual_research_entry
    # fake conn asserts raw_text update + AI-only rows refresh path
    ...
```

```python
def test_local_api_cors_allows_patch_delete_options() -> None:
    from src.local_api import app
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_local_api_manual_research.py tests/test_local_api_manual_market.py tests/test_local_api_cors.py`
Expected: FAIL because new models/routes/helpers are missing.

- [ ] **Step 3: Write minimal implementation**

```python
class ManualResearchIn(BaseModel):
    ticker: str
    raw_text: str
    source: Optional[str] = None
    source_url: Optional[str] = None
```

```python
@app.post("/api/manual-research")
def create_manual_research(payload: ManualResearchIn):
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/test_local_api_manual_research.py tests/test_local_api_manual_market.py tests/test_local_api_cors.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/local_api.py src/db.py tests/test_local_api_manual_research.py tests/test_local_api_manual_market.py tests/test_local_api_cors.py
git commit -m "feat: add manual research local api"
```

### Task 4: export latest/history manual AI decomposition payloads

**Files:**
- Modify: `src/export_dashboard_data.py`
- Test: `tests/test_export_manual_research.py`

**Interfaces:**
- Consumes: manual research tables, market_view_manual tables, latest-per-ticker export conventions.
- Produces:
  - `_load_manual_research_latest(...)`
  - `_load_manual_research_history(...)`
  - `_load_market_manual_views(...)`
  - stock payload fields: `manualResearchLatest`, `manualResearchHistory`, `aiDecompositionSummary`
  - market payload fields: `manualViewLatest`, `manualViewHistory`

- [ ] **Step 1: Write the failing test**

```python
from src.export_dashboard_data import _build_ai_decomposition_summary


def test_ai_decomposition_summary_stays_non_numeric() -> None:
    summary = _build_ai_decomposition_summary({
        "id": 7,
        "horizons": [
            {"horizon": "short", "attractivenessLabel": "다소 매력적"},
            {"horizon": "mid", "attractivenessLabel": "중립"},
            {"horizon": "long", "attractivenessLabel": "비매력적"},
        ],
        "bull": [{"point": "A"}],
        "bear": [{"point": "B"}, {"point": "C"}],
    })

    assert summary == {
        "entryId": 7,
        "labels": {"short": "다소 매력적", "mid": "중립", "long": "비매력적"},
        "bullCount": 1,
        "bearCount": 2,
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_export_manual_research.py`
Expected: FAIL because export helpers/fields are absent.

- [ ] **Step 3: Write minimal implementation**

```python
def _build_ai_decomposition_summary(entry: dict | None) -> dict | None:
    if not entry:
        return None
    labels = {item["horizon"]: item["attractivenessLabel"] for item in entry.get("horizons", [])}
    return {
        "entryId": entry["id"],
        "labels": labels,
        "bullCount": len(entry.get("bull", [])),
        "bearCount": len(entry.get("bear", [])),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/test_export_manual_research.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/export_dashboard_data.py tests/test_export_manual_research.py
git commit -m "feat: export manual ai decomposition data"
```

### Task 5: Research tab UI for manual input and latest/history cards

**Files:**
- Modify: `dashboard-web/src/display.js`
- Modify: `dashboard-web/src/tabsB.jsx`
- Test: `dashboard-web/tests/manual_research.test.js`

**Interfaces:**
- Consumes: export payload fields from Task 4, local API endpoints from Task 3.
- Produces:
  - textarea + source/source_url input
  - submit handler for manual analysis
  - latest AI decomposition card
  - raw text toggle, history toggle
  - empty state strings

- [ ] **Step 1: Write the failing test**

```javascript
import test from 'node:test';
import assert from 'node:assert/strict';
import { buildAiDecompositionBadges } from '../src/display.js';

test('manual research summary builds horizon labels without numeric score', () => {
  assert.deepEqual(buildAiDecompositionBadges({
    labels: { short: '다소 매력적', mid: '중립', long: '비매력적' },
    bullCount: 2,
    bearCount: 1,
  }), ['단기 · 다소 매력적', '중기 · 중립', '장기 · 비매력적']);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- --test-reporter=spec`
Expected: FAIL because display helper/UI references do not exist.

- [ ] **Step 3: Write minimal implementation**

```javascript
export function buildAiDecompositionBadges(summary) {
  if (!summary?.labels) return [];
  return [
    ['short', '단기'],
    ['mid', '중기'],
    ['long', '장기'],
  ].filter(([key]) => summary.labels[key]).map(([key, label]) => `${label} · ${summary.labels[key]}`);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- --test-reporter=spec`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dashboard-web/src/display.js dashboard-web/src/tabsB.jsx dashboard-web/tests/manual_research.test.js
git commit -m "feat: add manual research analyst view ui"
```

### Task 6: Stock detail and market tab integration

**Files:**
- Modify: `dashboard-web/src/tabsA.jsx`
- Modify: `dashboard-web/src/tabsB.jsx`
- Test: `dashboard-web/tests/manual_research.test.js`

**Interfaces:**
- Consumes: Task 4 payload fields, Task 5 UI helpers.
- Produces:
  - stock detail three-source parallel section
  - market manual input / latest-history display

- [ ] **Step 1: Write the failing test**

```javascript
import { readFileSync } from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

test('stock detail shows three distinct source sections', () => {
  const source = readFileSync(new URL('../src/tabsA.jsx', import.meta.url), 'utf8');
  assert.match(source, /내 판단/);
  assert.match(source, /AI 분해 분석/);
  assert.match(source, /자동 수집 근거/);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- --test-reporter=spec`
Expected: FAIL because integration section text/components are missing.

- [ ] **Step 3: Write minimal implementation**

```jsx
<Panel title="세 출처 비교" sub="합산 없이 나란히 보기">
  ...
</Panel>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- --test-reporter=spec`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dashboard-web/src/tabsA.jsx dashboard-web/src/tabsB.jsx dashboard-web/tests/manual_research.test.js
git commit -m "feat: integrate manual ai decomposition across tabs"
```

### Task 7: Smoke verification, docs sync, and final export validation

**Files:**
- Modify: `PRD.md`
- Modify: `CLAUDE.md`
- Possibly modify: `dashboard-web/src/data.json` (if local smoke regenerates export)
- Test: existing and new tests from prior tasks

**Interfaces:**
- Consumes: all prior tasks.
- Produces:
  - updated PRD §11 / changelog
  - updated CLAUDE.md rules for Wave 4-D-3
  - smoke evidence for one real analyst-style text input

- [ ] **Step 1: Write the smoke verification script or command target**

```python
# tests or scratch verification helper that:
# 1. inserts one real analyst-style text
# 2. runs decomposition
# 3. prints extracted target/rating, bull/bear counts, horizon labels/rationales
# 4. confirms logs only show length/hash
```

- [ ] **Step 2: Run full verification**

Run: `python -m pytest -q tests/test_manual_research_schema.py tests/test_manual_research_decomposition.py tests/test_local_api_manual_research.py tests/test_local_api_manual_market.py tests/test_export_manual_research.py`
Expected: PASS

Run: `cd dashboard-web && npm test -- --test-reporter=spec && npm run build`
Expected: PASS and build succeeds.

- [ ] **Step 3: Run smoke with one analyst-style text**

Run: project-specific local smoke command using `.env` and local API / decomposition path.
Expected: output includes:
- extracted target price / rating if present
- bull/bear counts
- short/mid/long labels + rationale
- no raw_text full-body log line

- [ ] **Step 4: Update docs**

```markdown
- PRD.md §11: Wave 4-D-3 manual AI decomposition backend/UI/export
- CLAUDE.md: raw_text logging rule, user-confirmed overwrite protection, three-source display rule
```

- [ ] **Step 5: Commit**

```bash
git add PRD.md CLAUDE.md
git commit -m "docs: document manual ai decomposition workflow"
```
