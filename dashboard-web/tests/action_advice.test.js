import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

test('stock detail includes action advice card wiring', () => {
  const source = fs.readFileSync(new URL('../src/tabsA.jsx', import.meta.url), 'utf8');
  assert.match(source, /actionAdviceLatest/);
  assert.match(source, /actionAdviceHistory/);
  // 신규-D: 카드는 비중 권고가 아니라 보유성격 + 집중 리스크 관찰 중심으로 재정의됨
  assert.match(source, /종목 성격 · 액션/);
  assert.match(source, /holdCharacter/);
  assert.match(source, /concentrationNote/);
  assert.match(source, /관찰 · 집중 리스크/);
});

test('action advice card no longer renders weight-directive cells', () => {
  const source = fs.readFileSync(new URL('../src/tabsA.jsx', import.meta.url), 'utf8');
  // 목표 비중/조정 방향 그리드는 종목 카드 표시에서 제거(데이터는 DB 보존)
  assert.doesNotMatch(source, /MonoCaps[^>]*>목표 비중</);
  assert.doesNotMatch(source, /MonoCaps[^>]*>조정 방향</);
});
