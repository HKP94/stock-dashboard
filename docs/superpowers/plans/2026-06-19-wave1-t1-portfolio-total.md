# Wave 1 T1 Portfolio Total Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Overview and Portfolio display exactly the same KRW total asset value from one canonical calculation.

**Architecture:** `compute_portfolio` remains the canonical calculator and persists `asset_total`. A local API summary endpoint exposes that snapshot, while both React tabs call the same pure `portfolioAssetTotal` display helper. The portfolio tab may still calculate stock/cash breakdowns for display, but its total asset number comes from the canonical summary.

**Tech Stack:** Python 3.12, FastAPI, psycopg3, React 19, Vite 8, Node built-in test runner, pytest.

## Global Constraints

- Never hardcode secrets and never add an order, transfer, or brokerage execution path.
- Use per-ticker latest prices and the latest USD/KRW rate; never use a global `max(asof)` for ticker exports.
- Convert DB NUMERIC values to `float` at read boundaries.
- Commit after each DB write stage and roll back on failure.
- Update `PRD.md` §11/change history and `CLAUDE.md` in this PR.

---

### Task 1: Lock the canonical portfolio calculation

**Files:**
- Create: `tests/test_compute_portfolio.py`
- Modify: `src/compute_portfolio.py`

**Interfaces:**
- Consumes: `_load_holdings`, `_get_latest_price`, `_get_usdkrw`, `_load_cash`.
- Produces: `compute_portfolio(...) -> dict` containing `total_eval_krw`, `cash_total_krw`, and `asset_total_krw`.

- [ ] **Step 1: Write failing tests**

Add tests using a fake connection/cursor and patched loaders that prove: two tickers use their own latest prices, USD stocks and cash share one FX rate, and `asset_total_krw == total_eval_krw + cash_total_krw`.

```python
def test_asset_total_includes_krw_converted_cash(monkeypatch, fake_conn):
    monkeypatch.setattr(cp, "_load_holdings", lambda conn: [
        {"ticker": "AAPL", "qty": 2, "avg_price": 100, "currency": "USD"},
        {"ticker": "005930.KS", "qty": 1, "avg_price": 70000, "currency": "KRW"},
    ])
    monkeypatch.setattr(cp, "_get_latest_price", lambda ticker, conn: {"AAPL": 120.0, "005930.KS": 75000.0}[ticker])
    monkeypatch.setattr(cp, "_get_usdkrw", lambda conn: 1400.0)
    monkeypatch.setattr(cp, "_load_cash", lambda conn: {"USD": 10.0, "KRW": 1000.0})
    out = cp.compute_portfolio(fake_conn, date(2026, 6, 19))
    assert out["total_eval_krw"] == 411000.0
    assert out["cash_total_krw"] == 15000.0
    assert out["asset_total_krw"] == 426000.0
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_compute_portfolio.py -q`

Expected: failure because `cash_total_krw` and `asset_total_krw` are absent from the return value.

- [ ] **Step 3: Return the persisted canonical totals**

```python
return {
    "n": n_ok,
    "total_eval_krw": total_eval_krw,
    "cash_total_krw": cash_total_krw,
    "asset_total_krw": asset_total_krw,
    "total_pnl_krw": total_pnl_krw,
    "total_pnl_pct": total_pnl_pct,
    "fx_rate": fx,
    "fx_missing": fx_missing_usd,
}
```

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_compute_portfolio.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/compute_portfolio.py tests/test_compute_portfolio.py
git commit -m "fix: 포트폴리오 총자산 계산 계약 고정"
```

### Task 2: Expose and share the portfolio summary

**Files:**
- Modify: `src/local_api.py`
- Modify: `tests/test_local_api_cors.py`
- Create: `dashboard-web/src/display.js`
- Create: `dashboard-web/tests/display.test.js`
- Modify: `dashboard-web/package.json`

**Interfaces:**
- Produces: `GET /api/portfolio/summary -> portfolio summary object | null`.
- Produces: `portfolioAssetTotal(portfolio) -> number | null`.

- [ ] **Step 1: Write failing API and JavaScript tests**

```javascript
import test from 'node:test';
import assert from 'node:assert/strict';
import { portfolioAssetTotal } from '../src/display.js';

test('prefers canonical asset_total', () => {
  assert.equal(portfolioAssetTotal({ asset_total: 130, total_eval: 100, cash_total: 20 }), 130);
});

test('falls back to evaluation plus cash', () => {
  assert.equal(portfolioAssetTotal({ total_eval: 100, cash_total: 20 }), 120);
});
```

Extend the CORS test to require `OPTIONS` as well as PATCH and DELETE.

- [ ] **Step 2: Verify RED**

Run: `cd dashboard-web && node --test tests/display.test.js`

Expected: module/function missing.

- [ ] **Step 3: Implement the pure helper and summary endpoint**

```javascript
export function portfolioAssetTotal(portfolio) {
  if (!portfolio) return null;
  const canonical = Number(portfolio.asset_total);
  if (Number.isFinite(canonical)) return canonical;
  const evaluation = Number(portfolio.total_eval);
  const cash = Number(portfolio.cash_total ?? 0);
  return Number.isFinite(evaluation) && Number.isFinite(cash) ? evaluation + cash : null;
}
```

Factor local API snapshot serialization into `_portfolio_snapshot_payload(row)` and reuse it from `_patch_data_json_portfolio` and `GET /api/portfolio/summary`. Every NUMERIC field is converted with `float`.

- [ ] **Step 4: Add the test script and verify GREEN**

Add `"test": "node --test tests/*.test.js"` to `dashboard-web/package.json`.

Run: `cd dashboard-web && npm test`

Expected: all display helper tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/local_api.py tests/test_local_api_cors.py dashboard-web/src/display.js dashboard-web/tests/display.test.js dashboard-web/package.json
git commit -m "feat: 포트폴리오 요약을 공용 총자산 경로로 제공"
```

### Task 3: Use one total in both tabs

**Files:**
- Modify: `dashboard-web/src/tabsA.jsx`
- Modify: `dashboard-web/src/tabsC.jsx`

**Interfaces:**
- Consumes: `portfolioAssetTotal` and `/api/portfolio/summary`.

- [ ] **Step 1: Add a failing consumer-wiring audit**

```javascript
import { readFileSync } from 'node:fs';

test('overview and portfolio both call the shared total helper', () => {
  for (const file of ['src/tabsA.jsx', 'src/tabsC.jsx']) {
    const source = readFileSync(new URL(`../${file}`, import.meta.url), 'utf8');
    assert.match(source, /portfolioAssetTotal\(/);
  }
});
```

- [ ] **Step 2: Verify RED, then wire both consumers**

Run: `cd dashboard-web && npm test`

Expected: both consumer files currently lack the shared helper call.

Overview replaces `D.portfolio.total_eval` with `portfolioAssetTotal(D.portfolio)` and labels it `총자산`. Portfolio stores `/api/portfolio/summary` in state after every load and renders `portfolioAssetTotal(summary || D.portfolio)`.

- [ ] **Step 3: Verify frontend and Python suites**

Run: `cd dashboard-web && npm test && npm run lint && npm run build`

Run: `pytest tests/test_compute_portfolio.py tests/test_local_api_cors.py -q`

Expected: all commands exit 0 and both tabs use the same helper.

- [ ] **Step 4: Update project records and commit**

Add T1 completion and verification evidence to `PRD.md` §11/change history. Add the canonical total rule to `CLAUDE.md`.

```bash
git add dashboard-web/src/tabsA.jsx dashboard-web/src/tabsC.jsx PRD.md CLAUDE.md
git commit -m "fix: 오버뷰와 포트폴리오 총자산 표시 통일"
```

### Task 4: Full verification and PR delivery

- [ ] **Step 1: Run fresh verification**

Run: `pytest -q`

Run: `cd dashboard-web && npm test && npm run lint && npm run build`

Run: `git diff --check origin/main...HEAD`

- [ ] **Step 2: Push and open PR**

Push `codex/wave1-t1-portfolio-total` and open a PR containing What/Why/Verification sections. Do not merge it automatically.
