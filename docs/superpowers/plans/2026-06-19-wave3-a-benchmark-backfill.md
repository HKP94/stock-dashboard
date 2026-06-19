# Wave 3 W3-A Benchmark Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or implement this plan step-by-step with explicit verification after each task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a point-in-time-safe 5-year benchmark history backbone for KOSPI, S&P500, and NASDAQ, and extend stock price backfill checks so true backtests can compare against continuous benchmark series without mixing in snapshot-only data.

**Architecture:** Keep latest snapshot ingestion in `market_daily` unchanged, and introduce a dedicated `index_daily` history table plus a small benchmark-history ingest module. Reuse existing per-market price fetchers for stock backfill, but allow a 5-year history mode for gap checks and repair.

**Tech Stack:** Python 3.12, psycopg3, yfinance, pykrx, pandas, pytest.

## Global Constraints

- Never hardcode secrets and never add any order execution path.
- Preserve the §F7 separation principle: this PR only builds shared historical data for later true backtests; it does not mix retrospective metrics into true-backtest outputs.
- Convert DB NUMERIC values to `float` at read boundaries.
- Commit after each DB write stage and roll back on failure.
- Update `PRD.md` §11/change history and `CLAUDE.md` in this PR.

### Task 1: Add the historical index contract and persistence path

**Files:**
- Modify: `src/schemas.py`
- Modify: `src/db.py`
- Modify: `db/schema.sql`

**Interfaces:**
- Add `IndexDailyRow(index_code, asof, close, source='yfinance')`.
- Add `upsert_index_daily(conn, rows)`.
- Add `index_daily(index_code, asof, close, source, fetched_at)` with `(index_code, asof)` uniqueness.

- [ ] **Step 1: Write failing tests**

Create tests that assert:

```python
row = IndexDailyRow(index_code="^GSPC", asof=date(2026, 6, 19), close=6123.45)
assert row.source == "yfinance"
```

and that `upsert_index_daily` uses `(index_code, asof)` as the upsert key.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_benchmark_backfill.py -q`

Expected: failures because the row model and upsert helper do not exist yet.

- [ ] **Step 3: Implement schema + DB helper**

Add the new model, table DDL, and helper with the same batching style used by `upsert_price_daily`.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_benchmark_backfill.py -q`

Expected: the schema/helper tests pass.

### Task 2: Build 5-year benchmark history ingestion and continuity checks

**Files:**
- Create: `src/ingest_index_history.py`
- Modify: `tests/test_benchmark_backfill.py`

**Interfaces:**
- `fetch_index_history(index_code: str, period: str = "5y") -> list[IndexDailyRow]`
- `find_missing_business_days(rows, max_gap_days=5) -> list[dict]`
- `run_index_backfill(conn, period="5y") -> dict`

- [ ] **Step 1: Write failing tests**

Add tests that prove:

- yfinance history converts into `IndexDailyRow` rows.
- duplicate/empty rows are skipped safely.
- continuity checker flags large business-day gaps but ignores short holiday weekends.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_benchmark_backfill.py -q`

Expected: failures because the ingest module does not exist yet.

- [ ] **Step 3: Implement the benchmark ingest path**

Use yfinance only for `^KS11`, `^GSPC`, `^IXIC`, convert close prices to floats, and log any detected continuity gaps without stopping the whole run.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_benchmark_backfill.py -q`

Expected: ingestion and continuity tests pass.

### Task 3: Extend stock gap detection from 2-year sufficiency to 5-year backtest readiness

**Files:**
- Modify: `src/ingest_us.py`
- Modify: `src/ingest_kr.py`
- Modify: `src/backfill.py`
- Modify: `tests/test_benchmark_backfill.py`

**Interfaces:**
- `fetch_us_prices(..., period: str = PRICE_PERIOD)` already exists; allow `5y` callers.
- `fetch_kr_prices(..., lookback_days: int = PRICE_LOOKBACK_DAYS)` already exists; allow `5 * 366` callers.
- `detect_gap_tickers(conn, min_rows=..., stale_days=..., required_years=...)`

- [ ] **Step 1: Write failing tests**

Add tests showing that a ticker with ~2 years of rows is acceptable for dashboard indicators but still flagged for `required_years=5`, and that `backfill` uses the longer fetch window for those gaps.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_benchmark_backfill.py -q`

Expected: failures because the gap checker is still hardcoded to the 2-year requirement.

- [ ] **Step 3: Implement the extended backfill mode**

Keep the existing default behavior intact for quick Wave 1/2 flows, but add a backtest-readiness mode for 5-year checks and repair.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_benchmark_backfill.py -q`

Expected: the 5-year gap detection/backfill tests pass.

### Task 4: Document the new benchmark backbone

**Files:**
- Modify: `PRD.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the change log and operating rules**

Record that true-backtest benchmark history now lives in `index_daily`, that 5-year continuity is checked/logged, and that this data remains separate from retrospective outputs.

- [ ] **Step 2: Final verification**

Run:

```bash
pytest tests/test_benchmark_backfill.py -q
python -m compileall src
```

Expected: tests pass and Python sources compile cleanly.
