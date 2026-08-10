import test from 'node:test';
import assert from 'node:assert/strict';

import { assetEquation, holdingWeightPct, holdingChangePoints } from '../src/display.js';

// 실측값 (/api/portfolio/summary 2026-08-09)
const SUMMARY = {
  total_eval: 4025880.8873418,
  total_cost: 4075595.47607422,
  total_pnl: -49714.5887324214,
  total_pnl_pct: -1.22,
  n_holdings: 4,
  fx_rate: 1407.44995117188,
  fx_missing: false,
  cash_total: 4758128.0,
  asset_total: 8784008.89,
};

// ── assetEquation ───────────────────────────────────────────
test('세 항을 한 소스에서 읽고 합이 맞는다', () => {
  const e = assetEquation(SUMMARY);
  assert.equal(e.stock, 4025880.8873418);
  assert.equal(e.cash, 4758128.0);
  assert.equal(e.asset, 8784008.89);
  assert.equal(e.balanced, true);
});

// ★P① 회귀 가드 — 결측을 0으로 채우면 「현금 ₩0 = 총자산 8,784,009」 모순이 재발한다
test('현금이 결측이면 0이 아니라 null을 돌려준다', () => {
  assert.equal(assetEquation({ ...SUMMARY, cash_total: null }), null);
  assert.equal(assetEquation({ ...SUMMARY, cash_total: undefined }), null);
});

test('주식·총자산 결측도 null', () => {
  assert.equal(assetEquation({ ...SUMMARY, total_eval: null }), null);
  assert.equal(assetEquation({ total_eval: 1, cash_total: 2, asset_total: null }).asset, 3);  // 합으로 폴백
  assert.equal(assetEquation(null), null);
  assert.equal(assetEquation(undefined), null);
});

test('현금 0원은 결측과 구분해 유효값으로 통과시킨다', () => {
  const e = assetEquation({ total_eval: 100, cash_total: 0, asset_total: 100 });
  assert.equal(e.cash, 0);
  assert.equal(e.balanced, true);   // 진짜 현금 0원은 정상 상태다
});

test('서버 계산이 어긋나면 balanced=false로 표면화', () => {
  assert.equal(assetEquation({ total_eval: 100, cash_total: 50, asset_total: 999 }).balanced, false);
});

// ── holdingWeightPct ────────────────────────────────────────
test('비중은 총자산(현금 포함) 대비', () => {
  // 현대해상 943,200 / 8,784,009 ≈ 10.7%
  assert.ok(Math.abs(holdingWeightPct(943200, 8784008.89) - 10.74) < 0.01);
});

test('분모가 0·결측이면 null (0% 아님)', () => {
  assert.equal(holdingWeightPct(100, 0), null);
  assert.equal(holdingWeightPct(100, null), null);
  assert.equal(holdingWeightPct(null, 100), null);
});

// ── holdingChangePoints ─────────────────────────────────────
// 실측 스냅샷: 매매로 n_holdings가 6→2→3→2로 움직였고 그게 계단의 원인이다
const HISTORY = [
  { asof: '2026-07-30', asset: 8118511, nHoldings: 6 },
  { asof: '2026-07-31', asset: 8874385, nHoldings: 2 },
  { asof: '2026-08-01', asset: 8874385, nHoldings: 2 },
  { asof: '2026-08-03', asset: 8549245, nHoldings: 3 },
  { asof: '2026-08-04', asset: 8511125, nHoldings: 2 },
];

test('보유 종목 수가 바뀐 날만 마커로 뽑는다', () => {
  const pts = holdingChangePoints(HISTORY);
  assert.equal(pts.length, 3);
  assert.deepEqual(pts.map((p) => p.asof), ['2026-07-31', '2026-08-03', '2026-08-04']);
  assert.equal(pts[0].from, 6);
  assert.equal(pts[0].to, 2);
});

test('평탄 구간(주말 중복)은 마커가 생기지 않는다', () => {
  assert.equal(holdingChangePoints(HISTORY).some((p) => p.asof === '2026-08-01'), false);
});

test('결측 nHoldings는 변화로 세지 않는다', () => {
  const h = [{ asof: 'a', nHoldings: 3 }, { asof: 'b', nHoldings: null }, { asof: 'c', nHoldings: 3 }];
  assert.equal(holdingChangePoints(h).length, 0);
});

test('빈 이력 안전', () => {
  assert.deepEqual(holdingChangePoints([]), []);
  assert.deepEqual(holdingChangePoints(null), []);
});
