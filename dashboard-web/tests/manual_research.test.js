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
