import { evaluateHoldingRisk } from './asset-rules.js';
import { getAnalysisProfile } from './profiles.js';
import { pctDistance, round } from './technical.js';
import { buildTradingRisk } from './trading.js';

export function analyzeHolding(position, stockData, portfolioValue, monthlyBudget, profileValue = 'standard', tradingCosts = {}) {
  const analysisProfile = getAnalysisProfile(profileValue);
  const price = stockData.quote.price ?? stockData.technical.close;
  const costBasis = round(position.avgCost * position.shares, 2);
  const marketValue = round(price * position.shares, 2);
  const pnlAmount = round(marketValue - costBasis, 2);
  const pnlPct = round((price - position.avgCost) / position.avgCost * 100, 2);
  const currentWeight = portfolioValue > 0 ? round(marketValue / portfolioValue, 4) : 0;
  const weightGap = round(position.targetWeight - currentWeight, 4);
  const ladder = calculateAddingLadder(stockData, monthlyBudget, position.targetWeight);

  const holding = {
    position,
    stockData,
    price,
    costBasis,
    marketValue,
    pnlAmount,
    pnlPct,
    currentWeight,
    targetWeight: position.targetWeight,
    weightGap,
    maDistances: {
      ma5: pctDistance(price, stockData.technical.ma.ma5),
      ma10: pctDistance(price, stockData.technical.ma.ma10),
      ma20: pctDistance(price, stockData.technical.ma.ma20),
      ma60: pctDistance(price, stockData.technical.ma.ma60),
    },
    ladder,
  };
  holding.risk = evaluateHoldingRisk(holding, analysisProfile);
  holding.trading = buildTradingRisk(position, price, tradingCosts);
  return holding;
}

export function calculatePortfolioSummary(portfolio, holdings) {
  const stockValue = holdings.reduce((sum, holding) => sum + (holding.marketValue ?? 0), 0);
  const costBasis = holdings.reduce((sum, holding) => sum + (holding.costBasis ?? 0), 0);
  const cash = Number(portfolio.cash ?? 0);
  const totalValue = round(stockValue + cash, 2);
  const pnlAmount = round(stockValue - costBasis, 2);
  const pnlPct = costBasis ? round(pnlAmount / costBasis * 100, 2) : 0;
  const cashRatio = totalValue ? round(cash / totalValue * 100, 2) : 0;
  const sectorWeights = {};

  holdings.forEach((holding) => {
    const sector = holding.position.sector ?? holding.stockData.quote.sector ?? '未分类';
    sectorWeights[sector] = (sectorWeights[sector] ?? 0) + (holding.marketValue ?? 0);
  });

  const concentrationWarnings = Object.entries(sectorWeights)
    .map(([sector, value]) => ({ sector, weight: totalValue ? round(value / totalValue * 100, 2) : 0 }))
    .filter((item) => item.weight >= 35);

  return {
    stockValue: round(stockValue, 2),
    costBasis: round(costBasis, 2),
    cash,
    totalValue,
    pnlAmount,
    pnlPct,
    cashRatio,
    concentrationWarnings,
  };
}

export function calculateAddingLadder(stockData, monthlyBudget, targetWeight = 1) {
  const technical = stockData.technical;
  const downtrend = technical.ma.ma5 < technical.ma.ma10 && technical.ma.ma10 < technical.ma.ma20;
  const baseBudget = Math.max(monthlyBudget * Math.max(targetWeight, 0.05), monthlyBudget * 0.08);
  const stopLoss = calculateStopLoss(technical);
  const target = technical.support.high20 ?? technical.ma.ma20;

  const levels = [
    { label: '回踩 MA10', key: 'ma10', ratio: 0.25 },
    { label: '回踩 MA20', key: 'ma20', ratio: 0.35 },
    { label: '回踩 MA60', key: 'ma60', ratio: 0.40 },
  ].map((level) => {
    const triggerPrice = technical.ma[level.key];
    const amount = round(baseBudget * level.ratio, 2);
    const risk = triggerPrice && stopLoss ? triggerPrice - stopLoss : null;
    const reward = target && triggerPrice ? target - triggerPrice : null;
    const riskReward = risk && reward && risk > 0 ? round(reward / risk, 2) : null;
    return {
      ...level,
      triggerPrice: triggerPrice ? round(triggerPrice, 2) : null,
      amount,
      stopLoss,
      riskReward,
      enabled: !downtrend && triggerPrice != null,
    };
  });

  return {
    downtrend,
    stopLoss,
    levels,
    next: levels.find((level) => level.enabled && stockData.quote.price >= level.triggerPrice) ?? levels.find((level) => level.enabled) ?? null,
  };
}

function calculateStopLoss(technical) {
  const candidates = [technical.support.low20, technical.ma.ma60].filter(Number.isFinite);
  if (!candidates.length) return null;
  return round(Math.min(...candidates) * 0.97, 2);
}
