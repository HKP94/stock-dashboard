# Wave 1 T7 Signals and Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove mandatory disclaimer boilerplate and add deterministic display-only buy/watch/reduce signals with a reason and confidence.

**Architecture:** A pure Python signal module ranks active stocks by composite score and enriches both assembled contract records and dashboard exports. Policy documents and prompts allow explanation of this deterministic signal while continuing to prohibit any order execution path. UI renders label, reason, and confidence as one inseparable component.

**Tech Stack:** Python 3.12, Pydantic v2, PostgreSQL, React 19, pytest, Node test runner.

## Global Constraints

- Signals are display-only; no broker order, transfer, or execution code may be added.
- Every visible signal includes reason and confidence; a standalone label is a defect.
- Signal calculation is deterministic Python with no LLM call.
- Keep the three attractiveness axes separate.
- Update `AGENTS.md`, `CLAUDE.md`, `PRD.md` §0/§2/§5.2/§6/§10/§11/change history in this separate PR.

---

### Task 1: Define and test the deterministic signal contract

**Files:**
- Create: `src/display_signals.py`
- Create: `tests/test_display_signals.py`
- Modify: `src/schemas.py`
- Modify: `tests/test_assemble.py`

**Interfaces:**
- Produces `TradeSignal(label, percentile, reason, confidence)`.
- Produces `compute_display_signals(rows: list[dict]) -> dict[str, TradeSignal | None]`.
- Adds `QuantView.signal: Optional[TradeSignal]`.

- [ ] **Step 1: Write failing boundary, tie, missing, reason, and confidence tests**

```python
def test_top_middle_bottom_labels_include_explanation():
    rows = [_row('A', 90, m=80), _row('B', 60, q=75), _row('C', 10, v=70)]
    out = compute_display_signals(rows)
    assert out['A'].label == '매수'
    assert out['B'].label == '관망'
    assert out['C'].label == '축소'
    for signal in out.values():
        assert '백분위' in signal.reason
        assert 50 <= signal.confidence <= 100

def test_equal_composites_receive_equal_percentiles():
    out = compute_display_signals([_row('A', 70), _row('B', 70), _row('C', 20)])
    assert out['A'].percentile == out['B'].percentile
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_display_signals.py -q`

Expected: module missing.

- [ ] **Step 3: Implement average-rank percentiles and confidence**

Use average ranks for ties. Map percentile `>=70` to 매수, `<=30` to 축소, otherwise 관망. Apply the approved 50–100 boundary-distance formula. Build the reason from percentile position and the highest available factor using Korean display labels.

- [ ] **Step 4: Add Pydantic models and verify GREEN**

```python
class TradeSignal(BaseModel):
    label: Literal['매수', '관망', '축소']
    percentile: float = Field(ge=0, le=100)
    reason: str = Field(min_length=1)
    confidence: int = Field(ge=50, le=100)
```

Run: `pytest tests/test_display_signals.py tests/test_assemble.py -q`

- [ ] **Step 5: Commit**

```bash
git add src/display_signals.py src/schemas.py tests/test_display_signals.py tests/test_assemble.py
git commit -m "feat: 근거와 신뢰도를 포함한 표시용 매매신호 계약 추가"
```

### Task 2: Attach the same signals to assemble and export

**Files:**
- Modify: `src/assemble.py`
- Modify: `src/export_dashboard_data.py`
- Modify: `tests/test_assemble.py`
- Modify: `tests/test_export_safety.py`

**Interfaces:**
- `assemble_daily` enriches all records after assembly.
- Dashboard stock objects gain `signal` with the same four fields.

- [ ] **Step 1: Write failing integration tests**

Assert that an assembled three-stock universe and an exported three-stock universe receive identical labels, reasons, percentiles, and confidence. Assert filtered/missing composite records receive `signal=None`.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_assemble.py tests/test_export_safety.py -q`

- [ ] **Step 3: Attach signals after universe construction**

Do not calculate signals inside a per-ticker query. Build all records/stocks, call `compute_display_signals` once, then attach by ticker. This preserves cross-sectional percentile semantics and performs no DB write.

- [ ] **Step 4: Verify and commit**

Run: `pytest tests/test_display_signals.py tests/test_assemble.py tests/test_export_safety.py -q`

```bash
git add src/assemble.py src/export_dashboard_data.py tests/test_assemble.py tests/test_export_safety.py
git commit -m "feat: 조립 계약과 대시보드에 동일 매매신호 연결"
```

### Task 3: Render signals with mandatory explanation

**Files:**
- Modify: `dashboard-web/src/ui.jsx`
- Modify: `dashboard-web/src/tabsA.jsx`
- Modify: `dashboard-web/src/tabsB.jsx`
- Modify: `dashboard-web/tests/display.test.js`

**Interfaces:**
- Produces `SignalCard({signal, compact})`; it never renders a label without reason and confidence.

- [ ] **Step 1: Add a pure render-policy test**

Add `isCompleteSignal(signal)` to `display.js` and test that missing reason or confidence returns false.

```javascript
test('rejects standalone signal labels', () => {
  assert.equal(isCompleteSignal({label:'매수'}), false);
  assert.equal(isCompleteSignal({label:'매수', reason:'종합 백분위 80위', confidence:67}), true);
});
```

- [ ] **Step 2: Verify RED, then implement SignalCard**

Render the signal in Stock Detail and comparison/ranking rows. Each occurrence shows label, reason, and `신뢰도 N`. Missing signals show `신호 산정 데이터 없음`.

- [ ] **Step 3: Verify frontend and commit**

Run: `cd dashboard-web && npm test && npm run lint && npm run build`

```bash
git add dashboard-web/src/display.js dashboard-web/src/ui.jsx dashboard-web/src/tabsA.jsx dashboard-web/src/tabsB.jsx dashboard-web/tests/display.test.js
git commit -m "feat: 근거와 신뢰도를 갖춘 매매신호 표시"
```

### Task 4: Remove disclaimer boilerplate and synchronize policy

**Files:**
- Create: `AGENTS.md` from the workspace builder rules, with the approved signal policy and without the removed disclaimer rule
- Modify: `CLAUDE.md`, `PRD.md`, `START_HERE.md`, `README.md`
- Modify: `prompt/GEMINI_PROMPT.md`, `prompt/HERMES_PROMPT.md`
- Modify: `src/send_telegram.py`, `src/enrich_gemini.py`, `src/portfolio_advice.py`, `src/schemas.py`, and disclaimer-bearing runtime modules
- Modify: `dashboard-web/src/App.jsx`, `dashboard-web/src/tabsA.jsx`, `dashboard-web/src/tabsC.jsx`, `dashboard-web/src/tabsD.jsx`
- Modify: legacy `dashboard/` documentation/UI text and `db/schema.sql` comments containing the removed boilerplate
- Modify: disclaimer-dependent tests

**Interfaces:**
- No output contract contains a mandatory disclaimer field.
- LLM prompts may explain deterministic signals but may not invent signals or execute orders.

- [ ] **Step 1: Invert the existing disclaimer tests**

Replace assertions requiring disclaimers with assertions that output payloads and generated Telegram text omit the boilerplate. Add a repository audit test that scans runtime UI/prompts for the three prohibited phrases while excluding historical change logs.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_daily_brief.py tests/test_portfolio_advice.py tests/test_assemble.py -q`

Expected: existing disclaimer fields/text cause failures.

- [ ] **Step 3: Remove boilerplate and update prompt policy**

Remove footer/cards/constants/print lines and `StockDailyRecord.DISCLAIMER`. Preserve factual warnings such as `과거 성과는 미래를 보장하지 않습니다` because it is not the removed boilerplate. Update portfolio/Gemini/Hermes prompts to allow explanation of the deterministic `signal` object, forbid invention of unsupported signals, and retain the ban on order/transfer execution.

- [ ] **Step 4: Synchronize governing documents**

State: `매매신호 허용(근거·신뢰도 동반), 자동 주문 실행 금지, 신호는 표시 전용`. Remove mandatory disclaimer rules from `AGENTS.md`, `CLAUDE.md`, and PRD. Add the signal object to PRD §5.2 and the temporary percentile rule to §F4.

- [ ] **Step 5: Run static audit and tests**

Run: `rg -n "투자 자문 아님|본 정보는 투자자문이 아닙니다|본 정보는 참고용이며 투자 자문이 아닙니다|원금 손실 가능|원금 손실이 발생할 수 있습니다" . --glob '!.git/**' --glob '!docs/superpowers/**'`

Expected: no runtime, UI, prompt, or active-policy matches. Historical PRD change-log wording may be rewritten neutrally so the audit is clean.

Run: `pytest -q`

Run: `cd dashboard-web && npm test && npm run lint && npm run build`

- [ ] **Step 6: Commit**

```bash
git add AGENTS.md CLAUDE.md PRD.md START_HERE.md README.md prompt src dashboard dashboard-web db/schema.sql tests
git commit -m "docs: 매매신호 허용과 자동 주문 금지 정책 동기화"
```

### Task 5: Full verification and PR delivery

- [ ] Run: `pytest -q`
- [ ] Run: `cd dashboard-web && npm test && npm run lint && npm run build`
- [ ] Run the disclaimer audit and `git diff --check` again with fresh output.
- [ ] Confirm no order, transfer, or broker execution function was added by reviewing the diff.
- [ ] Push the dedicated T7 branch and open a separate PR with What/Why/Verification sections. Do not merge automatically.
