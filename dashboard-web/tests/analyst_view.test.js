import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  analystConsensusGap,
  analystViewCounts,
  hasAnalystCoverage,
} from '../src/display.js';


test('computes target price gap from latest price on the front-end', () => {
  assert.ok(Math.abs(analystConsensusGap({ targetPrice: 120 }, 100) - 0.2) < 1e-9);
  assert.ok(Math.abs(analystConsensusGap({ targetPrice: 95 }, 100) + 0.05) < 1e-9);
});


test('returns null gap when consensus or price is missing', () => {
  assert.equal(analystConsensusGap(null, 100), null);
  assert.equal(analystConsensusGap({ targetPrice: 120 }, null), null);
  assert.equal(analystConsensusGap({ targetPrice: null }, 100), null);
});


test('counts bull and bear views independently', () => {
  assert.deepEqual(
    analystViewCounts({
      bull: [{ point: '수요 증가' }, { point: '점유율 확대' }],
      bear: [{ point: '밸류 부담' }],
    }),
    { bull: 2, bear: 1 },
  );
});


test('detects whether a stock has any analyst coverage to show', () => {
  assert.equal(hasAnalystCoverage({
    consensus: { targetPrice: 120, ratingLabel: '매수' },
    analystViews: { bull: [], bear: [] },
    insightHistory: [],
  }), true);
  assert.equal(hasAnalystCoverage({
    consensus: null,
    analystViews: { bull: [], bear: [{ point: '실적 우려' }] },
    insightHistory: [],
  }), true);
  assert.equal(hasAnalystCoverage({
    consensus: null,
    analystViews: { bull: [], bear: [] },
    insightHistory: [{ id: 1, content: '누적 인사이트' }],
  }), true);
  assert.equal(hasAnalystCoverage({
    consensus: null,
    analystViews: { bull: [], bear: [] },
    insightHistory: [],
  }), false);
});


test('research stock chooser keeps a shared select style and sorted stock labels', () => {
  const source = readFileSync(new URL('../src/tabsB.jsx', import.meta.url), 'utf8');
  assert.match(source, /const filterSelectStyle = \{/);
  assert.match(source, /minWidth: 0/);
  assert.match(source, /sortStocksByLabel\(D\.stocks\)/);
  assert.ok((source.match(/style=\{filterSelectStyle\}/g) || []).length >= 2);
});


test('strategy horizon buttons avoid undefined dark active text colors', () => {
  const source = readFileSync(new URL('../src/tabsD.jsx', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /C\.bg/);
  assert.match(source, /background: selectedHorizon === h \? C\.accBg : C\.surface/);
  assert.match(source, /color: selectedHorizon === h \? C\.acc : C\.ink2/);
});
