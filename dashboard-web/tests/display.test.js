import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  cleanDisplayText,
  extractBullets,
  filterStocks,
  factorLabel,
  isCompleteSignal,
  portfolioAssetTotal,
  regimeLabel,
  sortStocksByLabel,
  sortStocksBySentiment,
} from '../src/display.js';


test('prefers the canonical asset total', () => {
  assert.equal(portfolioAssetTotal({ asset_total: 130, total_eval: 100, cash_total: 20 }), 130);
});


test('falls back to evaluation plus cash for older exports', () => {
  assert.equal(portfolioAssetTotal({ total_eval: 100, cash_total: 20 }), 120);
});


test('returns null when no evaluation total exists', () => {
  assert.equal(portfolioAssetTotal({ cash_total: 20 }), null);
});


// 총자산 표시는 단일 경로여야 한다(CLAUDE.md). Phase 3에서 포트폴리오 탭이
// assetEquation을 거치도록 바뀌었으므로, 가드는 "두 화면이 같은 계산에 도달하는가"를
// 체인으로 확인한다 — tabsA는 직접, tabsC는 assetEquation 경유, 그 내부가 공용 헬퍼 호출.
test('overview and portfolio reach the same total-assets helper', () => {
  const tabsA = readFileSync(new URL('../src/tabsA.jsx', import.meta.url), 'utf8');
  assert.match(tabsA, /portfolioAssetTotal\(/);

  const tabsC = readFileSync(new URL('../src/tabsC.jsx', import.meta.url), 'utf8');
  assert.match(tabsC, /assetEquation\(/);

  const display = readFileSync(new URL('../src/display.js', import.meta.url), 'utf8');
  const body = display.slice(display.indexOf('export function assetEquation'));
  assert.match(body.slice(0, body.indexOf('\n}')), /portfolioAssetTotal\(/,
    'assetEquation은 asset_total을 직접 읽지 말고 공용 헬퍼를 거쳐야 한다');
});

// P① 회귀: 포트폴리오 탭이 수식을 클라이언트에서 다시 합산하면 소스가 갈려 레이스가 재발한다
test('portfolio tab does not re-sum the asset equation client-side', () => {
  const tabsC = readFileSync(new URL('../src/tabsC.jsx', import.meta.url), 'utf8');
  // 주석은 걷어내고 실제 코드만 본다(설명문에 옛 변수명이 남아 있어도 통과해야 한다)
  const code = tabsC.split('\n').filter((l) => !l.trim().startsWith('//')).join('\n');
  assert.doesNotMatch(code, /totalEvalKrw|cashKrw/,
    '주식·현금을 클라이언트에서 합산하면 summary와 도착 시점이 갈린다(현금 ₩0 프레임의 원인)');
});


test('sorts ticker sentiment descending with a deterministic name tie-break', () => {
  const out = sortStocksBySentiment([
    { name: 'B', sscore: 50 },
    { name: 'A', sscore: 80 },
    { name: 'C', sscore: 50 },
  ]);
  assert.deepEqual(out.map((stock) => stock.name), ['A', 'B', 'C']);
});


test('sorts stock labels by Korean name with ticker tie-break', () => {
  const out = sortStocksByLabel([
    { t: '005930.KS', name: '나' },
    { t: '000660.KS', name: '가' },
    { t: 'AAPL', name: '나' },
    { t: 'MSFT', name: null },
  ]);
  assert.deepEqual(out.map((stock) => stock.t), ['000660.KS', '005930.KS', 'AAPL', 'MSFT']);
});


test('filters by ticker or name, market, and sector', () => {
  const stocks = [
    { t: 'AAPL', name: '애플', mk: 'US', sec: '기술' },
    { t: '005930.KS', name: '삼성전자', mk: 'KR', sec: '반도체' },
  ];
  assert.deepEqual(
    filterStocks(stocks, { query: '삼성', market: 'KR', sector: '반도체' }).map((stock) => stock.t),
    ['005930.KS'],
  );
  assert.deepEqual(filterStocks(stocks, { query: 'aapl' }).map((stock) => stock.t), ['AAPL']);
});


test('maps internal factor and regime keys to Korean display labels', () => {
  assert.equal(factorLabel('m'), '모멘텀');
  assert.equal(factorLabel('v'), '가치');
  assert.equal(factorLabel('q'), '우량성');
  assert.equal(factorLabel('g'), '성장');
  assert.equal(factorLabel('s'), '심리');
  assert.equal(regimeLabel('bull'), '강세');
});


test('rejects standalone signal labels', () => {
  assert.equal(isCompleteSignal({ label: '매수' }), false);
  assert.equal(isCompleteSignal({ label: '매수', reason: '종합 백분위 80위', confidence: 67 }), true);
});


test('flattens excessive markdown emphasis for display text', () => {
  assert.equal(cleanDisplayText('**강조** *남발* ***정리***'), '강조 남발 정리');
  assert.equal(cleanDisplayText('포트폴리오 *리스크*와 **국면** 체크'), '포트폴리오 리스크와 국면 체크');
});


test('extracts bullet lines while removing raw emphasis markers', () => {
  const bullets = extractBullets('- **실적** 개선\n* *과도한 강조* 자제\n일반 문장', { limit: 2 });
  assert.deepEqual(bullets, ['실적 개선', '과도한 강조 자제']);
});


test('watchlist rows stay top-level and keyed by ticker to preserve input focus', () => {
  const source = readFileSync(new URL('../src/tabsE.jsx', import.meta.url), 'utf8');
  assert.match(source, /function WatchlistRow\(/);
  assert.doesNotMatch(source, /const Row\s*=\s*\(/);
  assert.match(source, /<WatchlistRow key=\{w\.ticker\}/);
});
