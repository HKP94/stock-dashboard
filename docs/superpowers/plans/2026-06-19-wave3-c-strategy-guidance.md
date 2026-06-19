# Wave 3 W3-C Strategy Guidance Plan

**Goal:** Expose a display-only “current regime strategy guidance” card that recommends the strongest true-track strategy for the current market regime, while keeping retrospective output as a clearly labeled reference only.

**Architecture:** Reuse `backtest_results` from W3-B through `export_dashboard_data.py`, compute one `strategyGuidance` object from the current `market.overall` regime, and render it in the Market tab so UI reads a precomputed contract instead of re-deriving signals client-side.

## Constraints

- The guidance must be display-only; no execution path.
- True track is the primary basis.
- Retrospective, if shown, must include a visible selection-bias warning.
- Update `PRD.md` §11/change history and `CLAUDE.md`.

## Tasks

- [ ] Add a failing export test that asserts `strategyGuidance` prefers true-track regime winners and keeps retrospective as a warning-tagged reference.
- [ ] Implement `_build_strategy_guidance(backtest, market)` in `src/export_dashboard_data.py` and attach its output to exported data.
- [ ] Render the guidance card in `dashboard-web/src/tabsB.jsx` with label, reason, confidence, and reference warning.
- [ ] Verify with `pytest tests/test_backtest_v2.py -q` and `npm run build`.
