import test from 'node:test';
import assert from 'node:assert/strict';

import { stopDistance, eventDDay, buildTriggers, fmtEok } from '../src/display.js';

const intact = {
  t: '001450.KS', name: '현대해상', mk: 'KR', cur: '₩', hold: true, price: 39300,
  momoZone: { state: 'intact', buy: 38005, stop: 37173, target: 41250, note: '눌림 지지 매수 · 이탈 손절' },
};
const broken = {
  t: '005930.KS', name: '삼성전자', mk: 'KR', cur: '₩', hold: true, price: 240000,
  momoZone: { state: 'broken', buy: null, reclaim: 247950, note: 'sma20/50 재탈환 전 매수 없음' },
};

// ── stopDistance ────────────────────────────────────────────
test('intact 종목은 손절·목표 거리를 %로 준다', () => {
  const d = stopDistance(intact);
  assert.equal(d.kind, 'zone');
  assert.ok(d.stopPct < 0 && Math.abs(d.stopPct + 5.41) < 0.01);   // 손절선은 아래
  assert.ok(d.targetPct > 0 && Math.abs(d.targetPct - 4.96) < 0.01);
  assert.equal(d.breached, false);
});

test('broken 종목은 손절선을 지어내지 않고 재탈환가를 준다', () => {
  const d = stopDistance(broken);
  assert.equal(d.kind, 'reclaim');
  assert.equal(d.reclaim, 247950);
  assert.equal(d.stop, undefined);          // ★ 없는 손절선을 0/null 숫자로 채우면 안 된다
});

test('손절선 아래면 breached', () => {
  assert.equal(stopDistance({ ...intact, price: 36000 }).breached, true);
});

test('momoZone·가격이 없으면 null', () => {
  assert.equal(stopDistance({ price: 100 }), null);
  assert.equal(stopDistance({ ...intact, price: null }), null);
});

// ── eventDDay ───────────────────────────────────────────────
const earnings = {
  upcoming: [
    { ticker: 'LITE', fiscal_period: '2026Q2', scheduled_date: '2026-08-11', confirmed: true, consensus_eps: 2.97 },
    { kind: 'group', scheduled_date: '2026-08-14', confirmed: false, label: 'KR 반기·분기보고서 법정기한', tickers: ['005930.KS', '001450.KS'] },
    { ticker: 'LITE', fiscal_period: '2026Q3', scheduled_date: '2026-11-10', confirmed: true },
    { ticker: 'OLD', scheduled_date: '2026-08-01', confirmed: true },
  ],
};

test('개별 일정의 D-day', () => {
  const e = eventDDay(earnings, 'LITE', '2026-08-08');
  assert.equal(e.days, 3);
  assert.equal(e.estimated, false);
  assert.equal(e.consensusEps, 2.97);
});

test('가장 가까운 일정만 고른다', () => {
  assert.equal(eventDDay(earnings, 'LITE', '2026-08-08').date, '2026-08-11');
});

test('KR group 법정기한은 추정 표식이 붙는다', () => {
  const e = eventDDay(earnings, '005930.KS', '2026-08-08');
  assert.equal(e.days, 6);
  assert.equal(e.estimated, true);          // ★ 추정을 확정처럼 보여주면 안 된다
});

test('지난 일정·미매칭·결측은 null', () => {
  assert.equal(eventDDay(earnings, 'OLD', '2026-08-08'), null);
  assert.equal(eventDDay(earnings, 'NOPE', '2026-08-08'), null);
  assert.equal(eventDDay(null, 'LITE', '2026-08-08'), null);
});

// ── buildTriggers ───────────────────────────────────────────
test('rules.py 플래그를 트리거로 싣는다', () => {
  const out = buildTriggers([{ ...intact, flagsAction: ['목표가 근접 (3.0%)'] }]);
  const hit = out.find((x) => x.label === '목표가 근접 (3.0%)' && x.kind === 'condition');
  assert.ok(hit);
  assert.equal(hit.flag, '목표가 근접 (3.0%)');   // 원본 플래그 — 표시 레이어가 근거 문장을 붙인다
});

test('데이터 품질 표식(fallback)은 트리거가 아니다', () => {
  const out = buildTriggers([{ ...intact, flagsAction: ['fallback'] }]);
  assert.equal(out.length, 0);
});

test('손절선 이탈·접근 경고', () => {
  const breach = buildTriggers([{ ...intact, price: 36000 }]);
  assert.equal(breach[0].label, '손절선 이탈');
  assert.equal(breach[0].kind, 'alert');

  const near = buildTriggers([{ ...intact, price: 38000 }]);   // 손절선까지 -2.2%
  assert.equal(near[0].label, '손절선 접근');

  const far = buildTriggers([intact]);                          // -5.4% → 경고 아님
  assert.equal(far.length, 0);
});

// ③ PM 지시: 종목 하드코딩 금지 — 보유 전체에 일반화
test('보유 종목 외국인 당일 순매수 양전환을 잡는다 (삼성 하드코딩 없이)', () => {
  const out = buildTriggers([
    { ...broken, investorFlow: { foreignNet1d: 3_500_000_000, foreignNet3d: -1_200_000_000 } },
  ]);
  const hit = out.find((x) => x.label === '외국인 당일 순매수');
  assert.ok(hit, '보유 종목이면 티커와 무관하게 잡혀야 한다');
  assert.match(hit.detail, /\+35\.0억/);
  assert.match(hit.detail, /3일 −12\.0억/);      // 당일 +인데 3일 − — 병기가 의미를 가지는 지점
});

test('당일이 음수거나 미보유면 순매수 트리거 없음', () => {
  const neg = buildTriggers([{ ...broken, investorFlow: { foreignNet1d: -100 } }]);
  assert.equal(neg.some((x) => x.label === '외국인 당일 순매수'), false);

  const notHeld = buildTriggers([{ ...broken, hold: false, investorFlow: { foreignNet1d: 3e9 } }]);
  assert.equal(notHeld.some((x) => x.label === '외국인 당일 순매수'), false);
});

test('US 종목은 수급이 None이라 조용히 건너뛴다', () => {
  const out = buildTriggers([{ t: 'MSFT', name: '마이크로소프트', hold: true, price: 500, investorFlow: null }]);
  assert.equal(out.some((x) => x.label === '외국인 당일 순매수'), false);
});

test('정렬: 보유 우선 → 경고 → 조건 → 정보', () => {
  const out = buildTriggers([
    { t: 'X', name: '미보유종목', hold: false, price: 100, flagsAction: ['RSI 과열 (78)'] },
    { ...intact, price: 36000, grade: '축소', gradeConfidence: '상' },
  ]);
  assert.equal(out[0].name, '현대해상');
  assert.equal(out[0].kind, 'alert');
  assert.equal(out[1].kind, 'info');          // 같은 보유 종목의 등급 축소
  assert.equal(out[2].name, '미보유종목');
});

// ── fmtEok ──────────────────────────────────────────────────
test('원 → 억 표기', () => {
  assert.equal(fmtEok(6_254_000_000), '+62.5억');
  assert.equal(fmtEok(-864_000_000), '−8.6억');
  assert.equal(fmtEok(15_000_000_000), '+150억');   // 100억 이상은 소수점 없이
  assert.equal(fmtEok(null), '—');
});
