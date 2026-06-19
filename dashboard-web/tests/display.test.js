import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { portfolioAssetTotal } from '../src/display.js';


test('prefers the canonical asset total', () => {
  assert.equal(portfolioAssetTotal({ asset_total: 130, total_eval: 100, cash_total: 20 }), 130);
});


test('falls back to evaluation plus cash for older exports', () => {
  assert.equal(portfolioAssetTotal({ total_eval: 100, cash_total: 20 }), 120);
});


test('returns null when no evaluation total exists', () => {
  assert.equal(portfolioAssetTotal({ cash_total: 20 }), null);
});


test('overview and portfolio both call the shared total helper', () => {
  for (const file of ['src/tabsA.jsx', 'src/tabsC.jsx']) {
    const source = readFileSync(new URL(`../${file}`, import.meta.url), 'utf8');
    assert.match(source, /portfolioAssetTotal\(/);
  }
});
