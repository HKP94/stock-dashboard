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
