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

const FACTOR_LABELS = { m: '모멘텀', v: '가치', q: '우량성', g: '성장', s: '심리' };
const REGIME_LABELS = { bull: '강세', neutral: '중립', bear: '약세' };

export const factorLabel = (key) => FACTOR_LABELS[key] ?? key;
export const regimeLabel = (key) => REGIME_LABELS[key] ?? key;
