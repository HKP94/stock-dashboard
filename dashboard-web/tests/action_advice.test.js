import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

test('stock detail includes action advice card wiring', () => {
  const source = fs.readFileSync(new URL('../src/tabsA.jsx', import.meta.url), 'utf8');
  assert.match(source, /actionAdviceLatest/);
  assert.match(source, /actionAdviceHistory/);
  assert.match(source, /액션 제언/);
});
