# Wave 3 W3-B Strategy Library & Backtest Expansion Plan

> **For agentic workers:** Implement this plan step-by-step with explicit verification before each completion claim. Keep true backtests and retrospective tracks physically separated in storage and UI.

**Goal:** Expand the current momentum-only comparison into a named strategy library with separate true and retrospective tracks, multi-horizon metrics (1Y/3Y/5Y), regime-return summaries, and benchmark overlays backed by the new `index_daily` history.

**Architecture:** Introduce `src/strategies.py` as the strategy registry, evolve `backtest_results` into a horizon-aware results store, rewrite `src/backtest.py` around reusable curve/benchmark/regime helpers, and update export/UI to render true and retrospective sections independently with a visible retrospective warning.

**Tech Stack:** Python 3.12, pandas, numpy, psycopg3, React 19, Vite, Recharts, pytest.

## Global Constraints

- Preserve §F7 separation: never mix retrospective metrics into the same chart/table as true-backtest metrics.
- Retrospective sections must carry a visible selection-bias warning.
- Use only point-in-time-safe data for true strategies.
- Convert DB NUMERIC to float at read boundaries.
- Update `PRD.md` §11/change history and `CLAUDE.md` in this PR.

### Task 1: Define the strategy registry and result schema

**Files:**
- Create: `src/strategies.py`
- Modify: `db/schema.sql`
- Modify: `src/db.py`

**Interfaces:**
- `StrategyDefinition(name, track, label, selector_kind, description)`
- True: `momentum_12_1`, `low_vol`, `equal_weight_bh`
- Retrospective: `value`, `quality`, `multifactor`
- `backtest_results` rows keyed by `(strategy, track, horizon)` with `regime_returns` JSONB and `payload` for chart data.

- [ ] **Step 1: Write failing tests**

Add tests that assert the required strategy names exist in the right track and that stored rows are keyed by `(strategy, track, horizon)`.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_backtest_v2.py -q`

- [ ] **Step 3: Implement the registry and schema evolution**

Add the registry file and evolve `backtest_results` with additive columns/constraints so old rows are ignored and new rows are uniquely addressable by strategy/track/horizon.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_backtest_v2.py -q`

### Task 2: Build reusable strategy curves, benchmarks, and regime summaries

**Files:**
- Modify: `src/backtest.py`
- Modify: `tests/test_backtest_v2.py`

**Interfaces:**
- Reusable helpers for:
  - monthly strategy curve generation,
  - benchmark rebase-100 curves from `index_daily`,
  - horizon slicing (`1y`, `3y`, `5y`),
  - regime-bucket returns (`bull` / `neutral` / `bear`).

- [ ] **Step 1: Write failing tests**

Add tests that prove:

- true results only use `track='true'`,
- retrospective results only use `track='retrospective'`,
- benchmark curves are rebased to 100,
- regime summaries bucket returns by regime.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_backtest_v2.py -q`

- [ ] **Step 3: Implement the engine rewrite**

Keep the existing momentum formula, add low-vol and equal-weight buy-and-hold true strategies, add value/quality/multifactor retrospective fixed-basket curves, and persist 1Y/3Y/5Y rows per strategy with payload-backed chart data.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_backtest.py tests/test_backtest_v2.py -q`

### Task 3: Export the separated results and render the new Strategy UI

**Files:**
- Modify: `src/export_dashboard_data.py`
- Modify: `dashboard-web/src/tabsD.jsx`

**Interfaces:**
- Export grouped true/retrospective strategy objects by horizon.
- Render:
  - separate true and retrospective sections,
  - 1Y/3Y/5Y metric table,
  - selected-strategy rebase-100 line chart + KOSPI/S&P500/NASDAQ,
  - regime bar chart,
  - retrospective warning banner.

- [ ] **Step 1: Write failing UI-shape assertions**

Add or extend tests to assert the export shape includes grouped strategies, horizons, benchmark curves, and regime returns.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_backtest_v2.py -q`

- [ ] **Step 3: Implement export and UI**

Keep the sections fully separate, default to the 5Y horizon when available, and ensure retrospective warnings are visually prominent.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
PYTHONPATH=/Users/kyeongpilheo/Desktop/Python/stock/stock-dashboard /Users/kyeongpilheo/Desktop/Python/stock/stock-dashboard/.venv/bin/pytest tests/test_backtest.py tests/test_backtest_v2.py -q
/Users/kyeongpilheo/Desktop/Python/stock/stock-dashboard/.venv/bin/python -m compileall /Users/kyeongpilheo/Desktop/Python/stock/stock-dashboard/src
cd /Users/kyeongpilheo/Desktop/Python/stock/stock-dashboard/dashboard-web && npm run build
```

Expected: Python tests pass, sources compile, and the React app builds cleanly.
