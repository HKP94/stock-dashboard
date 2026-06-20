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
