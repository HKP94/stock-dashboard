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


test('overview and portfolio both call the shared total helper', () => {
  for (const file of ['src/tabsA.jsx', 'src/tabsC.jsx']) {
    const source = readFileSync(new URL(`../${file}`, import.meta.url), 'utf8');
    assert.match(source, /portfolioAssetTotal\(/);
  }
});


test('sorts ticker sentiment descending with a deterministic name tie-break', () => {
  const out = sortStocksBySentiment([
    { name: 'B', sscore: 50 },
    { name: 'A', sscore: 80 },
    { name: 'C', sscore: 50 },
  ]);
  assert.deepEqual(out.map((stock) => stock.name), ['A', 'B', 'C']);
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
