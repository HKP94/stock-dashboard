export function portfolioAssetTotal(portfolio) {
  if (!portfolio) return null;
  const canonical = Number(portfolio.asset_total);
  if (portfolio.asset_total !== null && portfolio.asset_total !== undefined && Number.isFinite(canonical)) return canonical;
  const evaluation = Number(portfolio.total_eval);
  const cash = Number(portfolio.cash_total ?? 0);
  return portfolio.total_eval !== null && portfolio.total_eval !== undefined
    && Number.isFinite(evaluation) && Number.isFinite(cash)
    ? evaluation + cash
    : null;
}

export function sortStocksBySentiment(stocks) {
  return [...stocks].sort((a, b) => {
    const scoreDiff = Number(b.sscore ?? b.s?.sscore ?? -Infinity) - Number(a.sscore ?? a.s?.sscore ?? -Infinity);
    return scoreDiff || String(a.name ?? a.s?.name ?? a.t).localeCompare(String(b.name ?? b.s?.name ?? b.t), 'ko');
  });
}

export function sortStocksByLabel(stocks) {
  const collator = new Intl.Collator('ko', { sensitivity: 'base', numeric: true });
  return [...stocks].sort((a, b) => {
    const nameDiff = collator.compare(String(a.name ?? a.s?.name ?? a.t ?? ''), String(b.name ?? b.s?.name ?? b.t ?? ''));
    return nameDiff || collator.compare(String(a.t ?? ''), String(b.t ?? ''));
  });
}

export function filterStocks(stocks, { query = '', market = 'all', sector = 'all' } = {}) {
  const needle = query.trim().toLocaleLowerCase();
  return stocks.filter((stock) => {
    const matchesQuery = !needle
      || String(stock.t ?? '').toLocaleLowerCase().includes(needle)
      || String(stock.name ?? '').toLocaleLowerCase().includes(needle);
    const matchesMarket = market === 'all' || stock.mk === market;
    const matchesSector = sector === 'all' || stock.sec === sector;
    return matchesQuery && matchesMarket && matchesSector;
  });
}

export function analystConsensusGap(consensus, price) {
  if (consensus?.targetPrice === null || consensus?.targetPrice === undefined) return null;
  if (price === null || price === undefined) return null;
  const targetPrice = Number(consensus?.targetPrice);
  const latestPrice = Number(price);
  if (!Number.isFinite(targetPrice) || !Number.isFinite(latestPrice) || latestPrice === 0) return null;
  return targetPrice / latestPrice - 1;
}

export function analystViewCounts(analystViews) {
  return {
    bull: Array.isArray(analystViews?.bull) ? analystViews.bull.length : 0,
    bear: Array.isArray(analystViews?.bear) ? analystViews.bear.length : 0,
  };
}

export function hasAnalystCoverage(stock) {
  if (stock?.consensus) return true;
  if ((stock?.analystViews?.bull || []).length > 0) return true;
  if ((stock?.analystViews?.bear || []).length > 0) return true;
  return (stock?.insightHistory || []).length > 0;
}

export function buildAiDecompositionBadges(summary) {
  if (!summary?.labels) return [];
  return [
    ['short', '단기'],
    ['mid', '중기'],
    ['long', '장기'],
  ]
    .filter(([key]) => summary.labels[key])
    .map(([key, label]) => `${label} · ${summary.labels[key]}`);
}

export function cleanDisplayText(text) {
  if (text == null) return '';
  return String(text)
    .replace(/\*{1,3}([^*]+?)\*{1,3}/g, '$1')
    .replace(/`([^`]+?)`/g, '$1')
    .replace(/\*\*/g, '')
    .replace(/\*/g, '')
    .replace(/[ \t]+/g, ' ')
    .trim();
}

export function extractBullets(text, { limit = Infinity } = {}) {
  if (!text) return [];
  return String(text)
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => line.replace(/^[-*•]\s*/, ''))
    .map(cleanDisplayText)
    .filter(Boolean)
    .slice(0, limit);
}

const FACTOR_LABELS = { m: '모멘텀', v: '가치', q: '우량성', g: '성장', s: '심리' };
const REGIME_LABELS = { bull: '강세', neutral: '중립', bear: '약세' };

export const factorLabel = (key) => FACTOR_LABELS[key] ?? key;
export const regimeLabel = (key) => REGIME_LABELS[key] ?? key;

export function isCompleteSignal(signal) {
  return Boolean(signal?.label && signal?.reason && Number.isFinite(Number(signal?.confidence)));
}


// ⑤ Phase 1: 내부 용어를 사용자 언어로 바꾼다.
// CLAUDE.md — "UI 텍스트에 내부 용어 노출 금지". 실제로 '오늘의 알림'에 `fallback`,
// `발행주식수 미수집(signal 7)` 같은 개발자 문자열이 그대로 떠 있었다.
// ★값(DB·export)은 진단용으로 그대로 두고 **표시할 때만** 바꾼다.
const FLAG_LABELS = [
  [/^fallback$/i, "선별 기준 미달 — 종합점수는 참고용"],
  [/사전필터 제외/, "선별 기준 미달"],
  [/발행주식수 미수집.*signal ?7/i, "재무점수 일부 항목 미수집"],
  [/^데이터 부족\(PER\)$/, "가치지표 미수집 (PER)"],
  [/^데이터 부족\(F-Score\)$/, "재무점수 미수집 (F-Score)"],
  [/^데이터 부족\((.+)\)$/, (m) => `지표 미수집 (${m[1]})`],
  [/^데이터 없음$/, "수집 대기 중"],
];

export function userFlagLabel(flag) {
  if (!flag) return "";
  for (const [re, label] of FLAG_LABELS) {
    const m = String(flag).match(re);
    if (m) return typeof label === "function" ? label(m) : label;
  }
  return flag;   // 이미 사용자 언어인 플래그(과열·골든크로스·목표가 근접 등)는 그대로
}


// ============================================================
// 홈 4밴드 — 표시 전용 순수 함수 (계산·수집 무변경, §2 관찰만)
// ============================================================

/** 1열 카드: 현재가와 손절·목표선의 거리(%).
 *  momoZone은 `broken`이면 stop/target이 **없고** reclaim만 준다(#90 철학 —
 *  재탈환 전엔 매수·손절선을 제시하지 않는다). 그 경우를 숫자로 위조하지 않고
 *  kind='reclaim'으로 구분해 돌려준다. */
export function stopDistance(stock) {
  const price = Number(stock?.price);
  const zone = stock?.momoZone;
  if (!zone || !Number.isFinite(price) || price === 0) return null;

  const pct = (level) => ((Number(level) - price) / price) * 100;

  if (zone.state === "broken") {
    return Number.isFinite(Number(zone.reclaim))
      ? { kind: "reclaim", reclaim: Number(zone.reclaim), reclaimPct: pct(zone.reclaim), note: zone.note }
      : null;
  }
  const stop = Number.isFinite(Number(zone.stop)) ? Number(zone.stop) : null;
  const target = Number.isFinite(Number(zone.target)) ? Number(zone.target) : null;
  if (stop === null && target === null) return null;
  return {
    kind: "zone",
    state: zone.state,
    stop, target,
    stopPct: stop === null ? null : pct(stop),        // 음수 = 손절선이 아래
    targetPct: target === null ? null : pct(target),
    breached: stop !== null && price < stop,
    note: zone.note,
  };
}

/** 1열 카드: 임박 실적 이벤트 D-day.
 *  earnings.upcoming은 개별 행과 KR 법정기한 group 행(tickers[])이 섞여 있다.
 *  group은 추정(confirmed=false)이므로 estimated 표식을 반드시 달고 나간다. */
export function eventDDay(earnings, ticker, todayISO) {
  const items = earnings?.upcoming;
  if (!Array.isArray(items) || !ticker || !todayISO) return null;
  const today = Date.parse(`${todayISO}T00:00:00Z`);
  if (!Number.isFinite(today)) return null;

  let best = null;
  for (const it of items) {
    const hit = it.kind === "group"
      ? (it.tickers || []).includes(ticker)
      : it.ticker === ticker;
    if (!hit) continue;
    const when = Date.parse(`${it.scheduled_date}T00:00:00Z`);
    if (!Number.isFinite(when)) continue;
    const days = Math.round((when - today) / 86400000);
    if (days < 0) continue;                       // 지난 일정은 '임박'이 아니다
    if (best && best.days <= days) continue;
    best = {
      days,
      date: it.scheduled_date,
      estimated: it.confirmed === false,
      label: it.label || it.fiscal_period || "실적 발표",
      consensusEps: it.consensus_eps ?? null,
    };
  }
  return best;
}

// 트리거 정렬: 경고(하방)가 먼저, 그다음 조건 충족, 그다음 정보.
const TRIGGER_RANK = { alert: 0, condition: 1, info: 2 };

/** 2열 「오늘의 트리거」 — 이미 export된 값만 조합한다(새 규칙 판정 없음).
 *  ① rules.py가 판정한 flagsAction
 *  ② 손절선 이탈·접근  (price vs momoZone.stop 단순 비교)
 *  ③ 보유 종목 외인 **당일** 순매수 양(+) 전환 — 종목 하드코딩 없이 보유 전체 일반화
 *  ④ 3축 등급 '축소'
 *  보유 종목을 항상 위로 올린다(내 돈이 걸린 것 먼저). */
export function buildTriggers(stocks, { stopWarnPct = 3 } = {}) {
  const out = [];
  for (const s of stocks || []) {
    const push = (kind, label, detail) => out.push({ t: s.t, name: s.name, hold: !!s.hold, kind, label, detail });

    for (const f of s.flagsAction || []) {
      if (/^fallback$/i.test(f)) continue;          // 데이터 품질 표식은 트리거가 아니다
      // 원본 플래그도 실어 보낸다 — 표시 레이어가 근거 문장을 붙일 수 있게.
      out.push({ t: s.t, name: s.name, hold: !!s.hold, kind: "condition", label: userFlagLabel(f), detail: null, flag: f });
    }

    const d = stopDistance(s);
    if (d?.kind === "zone" && d.stopPct !== null) {
      if (d.breached) push("alert", "손절선 이탈", `현재가가 손절선(${fmtLevel(d.stop, s)}) 아래 ${Math.abs(d.stopPct).toFixed(1)}%`);
      else if (Math.abs(d.stopPct) <= stopWarnPct) push("alert", "손절선 접근", `손절선까지 ${Math.abs(d.stopPct).toFixed(1)}%`);
    }

    // ③ 당일값이 본질 — 3일 합계로는 "순매수일" 판정이 안 된다.
    const net1d = s.investorFlow?.foreignNet1d;
    if (s.hold && Number.isFinite(Number(net1d)) && Number(net1d) > 0) {
      push("condition", "외국인 당일 순매수", `외국인 ${fmtEok(net1d)} 순매수 · 3일 ${fmtEok(s.investorFlow?.foreignNet3d)}`);
    }

    if (s.grade === "축소") push("info", "3축 등급 축소", s.gradeConfidence ? `신뢰도 ${s.gradeConfidence}` : null);
  }

  return out.sort((a, b) =>
    (b.hold - a.hold) || (TRIGGER_RANK[a.kind] - TRIGGER_RANK[b.kind]) || String(a.name).localeCompare(String(b.name), "ko"));
}

function fmtLevel(v, s) {
  if (!Number.isFinite(Number(v))) return "—";
  return s?.cur === "₩" ? `₩${Math.round(v).toLocaleString("ko-KR")}` : `$${Number(v).toFixed(2)}`;
}

// ============================================================
// 포트폴리오 — 총자산 수식 (Phase 3, P① 구조 수정)
// ============================================================

/** 결측을 0으로 흘리지 않는 숫자 변환.
 *  ★`Number(null) === 0`·`Number("") === 0`이라 `Number.isFinite(Number(v))`만으로는
 *  결측이 0으로 새어나간다. 이 프로젝트에서 세 번 재발했다 —
 *  fmtEok가 결측을 '+0.0억'으로 표시, 비중이 결측을 '0%'로 표시(둘 다 "실제 0"과 구분 불가).
 *  돈·비중 화면에서 0은 "없음"이 아니라 "정말 0"이라는 뜻이므로 반드시 구분한다. */
function num(v) {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

/** 「주식 + 현금 = 총자산」 세 항을 **한 소스**(/api/portfolio/summary 또는 data.json
 *  portfolio)에서 함께 읽는다.
 *
 *  P① 원인: 종전엔 주식=rows·현금=cashRows·총자산=summary로 소스가 3개였고
 *  순차 await라 도착 시점이 달랐다. rows만 먼저 반영된 ~1초 동안 화면이
 *  「주식 4,025,881 + 현금 ₩0 = 총자산 8,784,009」이라는 자기모순을 보여줬다(실측).
 *  한 객체에서 세 항을 꺼내면 시점에서 갈릴 구조 자체가 없어진다.
 *
 *  ★결측이면 null을 돌려준다(0 금지) — 돈 화면에서 ₩0은 "없음"으로 읽히므로,
 *  호출부는 null일 때 수식을 렌더하지 않아야 한다. */
export function assetEquation(summary) {
  if (!summary) return null;
  const stock = num(summary.total_eval);
  const cash = num(summary.cash_total);
  // 총자산은 반드시 공용 헬퍼를 거친다 — "총자산 표시는 단일 경로"(CLAUDE.md).
  // 여기서 asset_total을 직접 읽으면 오버뷰와 계산 경로가 갈린다.
  const asset = num(portfolioAssetTotal(summary));
  if (stock === null || cash === null || asset === null) return null;
  return {
    stock, cash, asset,
    pnl: num(summary.total_pnl),
    pnlPct: num(summary.total_pnl_pct),
    fxRate: num(summary.fx_rate),
    fxMissing: Boolean(summary.fx_missing),
    nHoldings: num(summary.n_holdings),
    // 세 항이 한 소스라 어긋날 일이 없지만, 어긋나면 그건 서버 계산 버그다 — 표면화한다.
    balanced: Math.abs(stock + cash - asset) <= 1,
  };
}

/** 보유 비중(%) — 분모는 **총자산(현금 포함)**. 분모가 바뀌면 숫자가 두 배 달라지므로
 *  표시할 때 분모를 반드시 함께 쓴다. 사실 표시 전용(§2) — 목표 비중·리밸런싱 지시 아님. */
export function holdingWeightPct(evalKrw, assetTotal) {
  const e = num(evalKrw), a = num(assetTotal);
  if (e === null || a === null || a <= 0) return null;
  return (e / a) * 100;
}

/** 자산흐름 차트용 — n_holdings가 바뀐 지점(계단의 원인)을 마커로 뽑는다.
 *  이 시계열은 매매·입출금이 섞인 잔고 추이이지 수익률이 아니다. */
export function holdingChangePoints(history) {
  const out = [];
  for (let i = 1; i < (history || []).length; i++) {
    const prev = history[i - 1].nHoldings, cur = history[i].nHoldings;
    if (prev != null && cur != null && prev !== cur) {
      out.push({ asof: history[i].asof, from: prev, to: cur, asset: history[i].asset });
    }
  }
  return out;
}

/** 원 단위 순매수 → 억원 표기. 수급은 억 단위로 읽는 게 관례다. */
export function fmtEok(won) {
  const n = num(won);            // 결측이 '0억'으로 새면 안 된다 — num() 주석 참고
  if (n === null) return "—";
  const eok = n / 1e8;
  return `${eok >= 0 ? "+" : "−"}${Math.abs(eok).toFixed(Math.abs(eok) >= 100 ? 0 : 1)}억`;
}
