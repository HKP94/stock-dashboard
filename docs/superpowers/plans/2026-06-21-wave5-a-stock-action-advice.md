# Wave 5-A Stock Action Advice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 보유/관심 종목에 대해 방향·현재 비중·목표 비중 레인지·진입/이탈 구간·지지/반대 재료·신뢰도를 가진 액션 제언을 저장하고, 먼저 백엔드/파이프라인/스모크를 완료한 뒤 export/UI를 붙인다.

**Architecture:** `stock_action_advice`를 일 단위 저장 레이어로 추가하고, 결정론 숫자 산출은 순수 Python 엔진이 담당한다. 상위 Gemini 모델은 숫자를 변경하지 못하도록 입력된 값만 해석하는 서술 레이어로 제한하며, 06시 파이프라인은 우선순위 대상만 예산 내에서 처리하고 이월을 기록한다.

**Tech Stack:** Python 3.12, psycopg3, pydantic v2, FastAPI-local export helpers, React+Vite, existing Gemini wrapper, pytest, node test

## Global Constraints

- 절대 시크릿 하드코딩 금지, 환경변수/기존 로딩 경로만 사용
- 자동 주문 실행 금지, 액션 제언은 표시 전용
- DB/JSON 계약 준수, 스키마 변경 시 PRD §11/변경이력·CLAUDE.md 갱신
- 모든 숫자(비중·구간)는 코드 책임, LLM은 숫자 생성/수정 금지
- 목표 비중은 규칙 기반 캡만 허용, 단일 종목 상한 10%
- 현재 비중은 `eval_amount / asset_total` 파생 후 해당 일자 판단값으로 저장
- 신뢰도는 `상/중/하`만 저장, 단일 합산점수 금지
- 종목별 latest 조회만 사용, 글로벌 `max(asof)` 금지
- DB NUMERIC은 읽기 경계에서 float 변환
- Gemini timeout·배치예산 준수, 종목 단위 try/except 격리
- 우선순위: 보유 7종목 매일 > 신호변화/뉴스이벤트 관심종목 > 잔여 예산 순환
- 커밋은 단계별로 수행, push/PR은 하지 않음

---

### Task 1: Add stock_action_advice schema and row models

**Files:**
- Modify: `db/schema.sql`
- Modify: `src/schemas.py`
- Modify: `src/db.py`
- Test: `tests/test_stock_action_advice_schema.py`

**Interfaces:**
- Consumes: existing `get_conn`, row-model pattern in `src/schemas.py`
- Produces:
  - `class StockActionAdviceRow(BaseModel)`
  - `upsert_stock_action_advice(conn, row: StockActionAdviceRow) -> None`
  - `load_latest_stock_action_advice(conn, tickers: list[str], limit_per_ticker: int = 5) -> dict[str, list[dict]]`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from src.schemas import StockActionAdviceRow


def test_stock_action_advice_row_accepts_expected_contract():
    row = StockActionAdviceRow(
        ticker="AAPL",
        asof="2026-06-21",
        direction="비중확대",
        current_weight=4.2,
        target_weight_low=3.0,
        target_weight_high=6.0,
        weight_action="늘림",
        entry_zone="SMA60 부근 재확인 시",
        exit_zone="목표가 근접 시",
        confidence="중",
        rationale="설명",
        supporting_factors=[{"source": "퀀트신호", "value": "매수"}],
        opposing_factors=[{"source": "드라이버", "value": "단기 약세"}],
        divergence_note="재료 혼조",
        model="gemini-2.5-pro",
    )
    assert row.direction == "비중확대"
    assert row.target_weight_high == 6.0


def test_schema_sql_defines_daily_unique_stock_action_advice_table():
    schema = Path("db/schema.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS stock_action_advice" in schema
    assert "UNIQUE (ticker, asof)" in schema
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest -q tests/test_stock_action_advice_schema.py`
Expected: FAIL with missing `StockActionAdviceRow` and missing DDL

- [ ] **Step 3: Write minimal implementation**

```python
# src/schemas.py
class StockActionAdviceRow(BaseModel):
    ticker: str
    asof: date
    direction: Literal["매수", "비중확대", "유지", "비중축소", "매도"]
    current_weight: Optional[float] = None
    target_weight_low: Optional[float] = None
    target_weight_high: Optional[float] = None
    weight_action: Literal["늘림", "유지", "줄임"]
    entry_zone: Optional[str] = None
    exit_zone: Optional[str] = None
    confidence: Literal["상", "중", "하"]
    rationale: str = Field(min_length=1)
    supporting_factors: list[dict] = Field(default_factory=list)
    opposing_factors: list[dict] = Field(default_factory=list)
    divergence_note: Optional[str] = None
    model: Optional[str] = None
    created_at: Optional[datetime] = None

# db/schema.sql
CREATE TABLE IF NOT EXISTS stock_action_advice (
    ticker TEXT NOT NULL,
    asof DATE NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('매수', '비중확대', '유지', '비중축소', '매도')),
    current_weight NUMERIC,
    target_weight_low NUMERIC,
    target_weight_high NUMERIC,
    weight_action TEXT NOT NULL CHECK (weight_action IN ('늘림', '유지', '줄임')),
    entry_zone TEXT,
    exit_zone TEXT,
    confidence TEXT NOT NULL CHECK (confidence IN ('상', '중', '하')),
    rationale TEXT NOT NULL,
    supporting_factors JSONB NOT NULL DEFAULT '[]'::jsonb,
    opposing_factors JSONB NOT NULL DEFAULT '[]'::jsonb,
    divergence_note TEXT,
    model TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (ticker, asof)
);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m pytest -q tests/test_stock_action_advice_schema.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add db/schema.sql src/schemas.py src/db.py tests/test_stock_action_advice_schema.py
git commit -m "feat: add stock action advice schema"
```

### Task 2: Build deterministic action engine for weights, zones, and confidence

**Files:**
- Create: `src/stock_action_advice.py`
- Test: `tests/test_stock_action_advice_engine.py`

**Interfaces:**
- Consumes:
  - stock payload-like dicts with `signal`, `consensus`, `analystViews`, `manualResearchLatest`, `drivers`, `holding`
  - portfolio snapshot with `asset_total`
- Produces:
  - `compute_current_weight(eval_amount: float | None, asset_total: float | None) -> float`
  - `derive_allocation_band(*, is_holding: bool, signal_label: str | None, regime: str, confidence: str, consensus_gap: float | None) -> str`
  - `allocation_band_to_range(band: str, *, regime: str) -> tuple[float, float]`
  - `derive_weight_action(current_weight: float, low: float, high: float) -> str`
  - `derive_entry_exit_zones(stock: dict) -> tuple[str | None, str | None, list[dict]]`
  - `derive_confidence_and_factors(stock: dict, regime: str) -> tuple[str, list[dict], list[dict], str | None]`
  - `build_action_frame(stock: dict, portfolio_snapshot: dict, regime: str) -> dict`

- [ ] **Step 1: Write the failing test**

```python
from src.stock_action_advice import (
    allocation_band_to_range,
    build_action_frame,
    compute_current_weight,
    derive_allocation_band,
)


def test_compute_current_weight_uses_eval_amount_over_asset_total():
    assert compute_current_weight(50_000, 1_000_000) == 5.0
    assert compute_current_weight(None, 1_000_000) == 0.0


def test_bear_regime_caps_core_band():
    low, high = allocation_band_to_range("core", regime="bear")
    assert (low, high) == (3.0, 6.0)


def test_non_holding_buy_signal_maps_to_starter_or_build():
    band = derive_allocation_band(
        is_holding=False,
        signal_label="매수",
        regime="neutral",
        confidence="상",
        consensus_gap=0.18,
    )
    assert band in {"starter", "build"}


def test_build_action_frame_exposes_supporting_sources_without_llm():
    stock = {
        "t": "AAPL",
        "signal": {"label": "매수", "reason": "백분위 상위 20%", "confidence": 82},
        "consensus": {"targetPrice": 240, "ratingLabel": "매수"},
        "price": 200,
        "analystViews": {"bull": [{"point": "수요 견조"}], "bear": []},
        "manualResearchLatest": None,
        "drivers": [],
        "holding": {"eval_amount": 50000},
        "sma20": 198,
        "sma50": 190,
        "sma200": 170,
    }
    advice = build_action_frame(stock, {"asset_total": 1_000_000}, "bull")
    assert advice["current_weight"] == 5.0
    assert advice["direction"] in {"매수", "비중확대", "유지"}
    assert advice["target_weight_high"] <= 10.0
    assert any(item["source"] == "퀀트신호" for item in advice["supporting_factors"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest -q tests/test_stock_action_advice_engine.py`
Expected: FAIL with module/function import errors

- [ ] **Step 3: Write minimal implementation**

```python
CONFIDENCE_ORDER = {"하": 0, "중": 1, "상": 2}
BAND_RANGES = {
    "exit": (0.0, 1.0),
    "starter": (0.0, 3.0),
    "build": (3.0, 6.0),
    "core": (6.0, 10.0),
}

def compute_current_weight(eval_amount, asset_total):
    if not eval_amount or not asset_total:
        return 0.0
    return round(float(eval_amount) / float(asset_total) * 100, 2)

def allocation_band_to_range(band, *, regime):
    low, high = BAND_RANGES[band]
    if regime == "bear" and band == "core":
        return (3.0, 6.0)
    return (low, min(high, 10.0))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m pytest -q tests/test_stock_action_advice_engine.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/stock_action_advice.py tests/test_stock_action_advice_engine.py
git commit -m "feat: add deterministic stock action engine"
```

### Task 3: Add Gemini explanation wrapper with numeric guardrails

**Files:**
- Modify: `src/enrich_gemini.py`
- Test: `tests/test_stock_action_advice_llm.py`

**Interfaces:**
- Consumes:
  - `build_action_frame(...)` output
  - existing `_call_gemini_with_backoff`, `_get_manual_research_model`, timeout config
- Produces:
  - `class StockActionAdviceNarrativeOutput(BaseModel)`
  - `_build_stock_action_advice_prompt(context: dict) -> str`
  - `summarize_stock_action_advice(context: dict) -> StockActionAdviceNarrativeOutput | None`

- [ ] **Step 1: Write the failing test**

```python
from src.enrich_gemini import _build_stock_action_advice_prompt


def test_action_advice_prompt_explicitly_forbids_numeric_generation():
    prompt = _build_stock_action_advice_prompt({
        "ticker": "AAPL",
        "direction": "비중확대",
        "current_weight": 5.0,
        "target_weight_low": 3.0,
        "target_weight_high": 6.0,
        "entry_zone": "SMA60 부근",
        "exit_zone": None,
        "supporting_factors": [{"source": "퀀트신호", "value": "매수"}],
        "opposing_factors": [],
    })
    assert "새로운 숫자" in prompt
    assert "입력으로 받은 값만" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest -q tests/test_stock_action_advice_llm.py`
Expected: FAIL with missing prompt builder

- [ ] **Step 3: Write minimal implementation**

```python
class StockActionAdviceNarrativeOutput(BaseModel):
    rationale: str
    divergenceNote: Optional[str] = None
    supportingFactors: list[dict] = Field(default_factory=list)
    opposingFactors: list[dict] = Field(default_factory=list)

def _build_stock_action_advice_prompt(context: dict) -> str:
    return (
        "너는 종목 액션 제언의 해설자다.\n"
        "중요: 새로운 숫자나 가격대를 만들지 말고 입력으로 받은 값만 사용하라.\n"
        "숫자는 절대 생성·수정하지 말고 왜 그런 숫자가 나왔는지와 재료 divergence만 설명하라.\n"
        f"{json.dumps(context, ensure_ascii=False)}"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m pytest -q tests/test_stock_action_advice_llm.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/enrich_gemini.py tests/test_stock_action_advice_llm.py
git commit -m "feat: add stock action advice narrative wrapper"
```

### Task 4: Integrate daily pipeline prioritization, storage, and smoke for bundle A

**Files:**
- Modify: `src/run_pipeline.py`
- Modify: `src/db.py`
- Test: `tests/test_run_pipeline_action_advice.py`
- Test: `tests/test_db_stock_action_advice.py`

**Interfaces:**
- Consumes:
  - `build_data()`-like stock context loaders or direct DB loaders
  - `build_action_frame(...)`
  - `summarize_stock_action_advice(...)`
  - `upsert_stock_action_advice(...)`
- Produces:
  - `_select_action_advice_targets(conn) -> list[str]`
  - `_step_action_advice(conn, errors: list[dict]) -> None`

- [ ] **Step 1: Write the failing test**

```python
from src.run_pipeline import _select_action_advice_targets


def test_action_advice_target_priority_orders_holdings_first(fake_conn):
    targets = _select_action_advice_targets(fake_conn)
    assert targets[:2] == ["AAPL", "MSFT"]


def test_action_advice_step_records_budget_rollover(monkeypatch, fake_conn):
    from src import run_pipeline as RP

    monkeypatch.setattr(RP, "_select_action_advice_targets", lambda conn: ["AAPL", "TSLA", "NVDA"])
    monkeypatch.setattr(RP, "_within_budget", lambda started_at, budget_seconds=0: False)
    errors = []
    RP._step_action_advice(fake_conn, errors)
    assert any("budget" in item["step"] or "action_advice" in item["step"] for item in errors)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest -q tests/test_run_pipeline_action_advice.py tests/test_db_stock_action_advice.py`
Expected: FAIL with missing pipeline step/helpers

- [ ] **Step 3: Write minimal implementation**

```python
def _select_action_advice_targets(conn):
    # 1) holdings 2) signal/news event 3) remainder
    ...

def _step_action_advice(conn, errors):
    started = time.monotonic()
    for ticker in _select_action_advice_targets(conn):
        if not _within_budget(started, GEMINI_BATCH_BUDGET_SECONDS):
            errors.append(_err("action_advice_budget", RuntimeError("budget exceeded; rolled over")))
            break
        try:
            ...
            upsert_stock_action_advice(conn, row)
            conn.commit()
        except Exception as exc:
            conn.rollback()
            errors.append(_err("action_advice", exc))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m pytest -q tests/test_run_pipeline_action_advice.py tests/test_db_stock_action_advice.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/run_pipeline.py src/db.py tests/test_run_pipeline_action_advice.py tests/test_db_stock_action_advice.py
git commit -m "feat: add action advice pipeline step"
```

- [ ] **Step 6: Run bundle A smoke**

Run:

```bash
set -a; source .env; set +a
./.venv/bin/python - <<'PY'
from src.export_dashboard_data import build_data
from src.run_pipeline import _step_action_advice
from src.db import get_conn

with get_conn() as conn:
    errors = []
    _step_action_advice(conn, errors)
    print("errors:", len(errors))

data = build_data()
holding = next(stock for stock in data["stocks"] if stock.get("holding"))
advice = holding.get("actionAdviceLatest")
print("ticker:", holding["t"])
print("direction:", advice["direction"] if advice else None)
print("current_weight:", advice["currentWeight"] if advice else None)
print("target_range:", (advice["targetWeightLow"], advice["targetWeightHigh"]) if advice else None)
print("entry_zone:", advice["entryZone"] if advice else None)
print("exit_zone:", advice["exitZone"] if advice else None)
print("confidence:", advice["confidence"] if advice else None)
print("supporting_count:", len(advice["supportingFactors"]) if advice else 0)
print("opposing_count:", len(advice["opposingFactors"]) if advice else 0)
filled = [s for s in data["stocks"] if s.get("actionAdviceLatest") and (s["actionAdviceLatest"].get("entryZone") or s["actionAdviceLatest"].get("exitZone"))]
all_with_advice = [s for s in data["stocks"] if s.get("actionAdviceLatest")]
print("zone_fill_ratio:", f"{len(filled)}/{len(all_with_advice)}")
PY
```

Expected: one holding prints full action advice fields; zone fill ratio reported; any blank zones can be manually classified as data shortage vs conservative rule

- [ ] **Step 7: Commit smoke-backed bundle A**

```bash
git add src/run_pipeline.py src/db.py
git commit -m "test: verify action advice bundle A smoke"
```

### Task 5: Export latest and history action advice

**Files:**
- Modify: `src/export_dashboard_data.py`
- Test: `tests/test_export_action_advice.py`

**Interfaces:**
- Consumes:
  - `stock_action_advice` rows
- Produces:
  - per-stock `actionAdviceLatest`
  - per-stock `actionAdviceHistory`

- [ ] **Step 1: Write the failing test**

```python
from src.export_dashboard_data import _group_action_advice_rows


def test_group_action_advice_rows_returns_latest_and_history_in_desc_order():
    rows = [
        {"ticker": "AAPL", "asof": "2026-06-20", "direction": "유지", "current_weight": 4.0, "target_weight_low": 3.0, "target_weight_high": 6.0, "weight_action": "유지", "entry_zone": None, "exit_zone": None, "confidence": "중", "rationale": "old", "supporting_factors": [], "opposing_factors": [], "divergence_note": None, "model": "m1"},
        {"ticker": "AAPL", "asof": "2026-06-21", "direction": "비중확대", "current_weight": 5.0, "target_weight_low": 3.0, "target_weight_high": 6.0, "weight_action": "늘림", "entry_zone": "SMA60", "exit_zone": None, "confidence": "상", "rationale": "new", "supporting_factors": [], "opposing_factors": [], "divergence_note": None, "model": "m1"},
    ]
    grouped = _group_action_advice_rows(rows)
    assert grouped["AAPL"][0]["direction"] == "비중확대"
    assert grouped["AAPL"][1]["direction"] == "유지"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest -q tests/test_export_action_advice.py`
Expected: FAIL with missing export helpers

- [ ] **Step 3: Write minimal implementation**

```python
def _group_action_advice_rows(rows):
    grouped = {}
    for row in sorted(rows, key=lambda r: (r["ticker"], str(r["asof"])), reverse=True):
        grouped.setdefault(row["ticker"], []).append({...})
    return grouped
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m pytest -q tests/test_export_action_advice.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/export_dashboard_data.py tests/test_export_action_advice.py
git commit -m "feat: export stock action advice history"
```

### Task 6: Add stock detail action advice card and history toggle

**Files:**
- Modify: `dashboard-web/src/tabsA.jsx`
- Test: `dashboard-web/tests/action_advice.test.js`

**Interfaces:**
- Consumes:
  - `stock.actionAdviceLatest`
  - `stock.actionAdviceHistory`
- Produces:
  - Action advice card in Stock Detail with direction, weights, zones, confidence, supporting/opposing factors, divergence note, history toggle

- [ ] **Step 1: Write the failing test**

```javascript
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

test('stock detail includes action advice card wiring', () => {
  const source = fs.readFileSync(new URL('../src/tabsA.jsx', import.meta.url), 'utf8');
  assert.match(source, /actionAdviceLatest/);
  assert.match(source, /actionAdviceHistory/);
  assert.match(source, /액션 제언/);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- --test-reporter=spec`
Expected: FAIL with missing action advice wiring

- [ ] **Step 3: Write minimal implementation**

```jsx
function ActionAdviceCard({ advice, history = [] }) {
  ...
}

// in StockDetail render
<ActionAdviceCard advice={s.actionAdviceLatest} history={s.actionAdviceHistory || []} />
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- --test-reporter=spec`
Expected: PASS

- [ ] **Step 5: Build UI**

Run: `npm run build`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add dashboard-web/src/tabsA.jsx dashboard-web/tests/action_advice.test.js
git commit -m "feat: add stock action advice card"
```

### Task 7: Final verification and docs update

**Files:**
- Modify: `PRD.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: completed backend, export, UI implementation
- Produces: updated roadmap/changelog docs reflecting Wave 5-A

- [ ] **Step 1: Update docs**

```markdown
- PRD §11: Wave 5-A 종목 액션 제언 완료 항목 추가
- PRD 변경이력: vX.X Wave 5-A 추가
- CLAUDE.md: 숫자는 코드, LLM은 해석만 / action advice 저장·우선순위·이월 규칙 추가
```

- [ ] **Step 2: Run full verification**

Run:

```bash
./.venv/bin/python -m pytest -q tests/test_stock_action_advice_schema.py tests/test_stock_action_advice_engine.py tests/test_stock_action_advice_llm.py tests/test_run_pipeline_action_advice.py tests/test_db_stock_action_advice.py tests/test_export_action_advice.py
cd dashboard-web && npm test -- --test-reporter=spec && npm run build
```

Expected: all tests pass, build passes

- [ ] **Step 3: Commit**

```bash
git add PRD.md CLAUDE.md
git commit -m "docs: record wave5a action advice"
```
