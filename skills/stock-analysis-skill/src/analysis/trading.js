import { round } from './technical.js';
import { getChinaDateTimeParts, getChinaTradingDayStatus } from '../utils/china-time.js';

export const DEFAULT_TRADING_COSTS = {
  commissionRate: 0.0003,
  minCommission: 5,
  stampDutyRate: 0.0005,
  transferFeeRate: 0.00001,
  etfStampDutyRate: 0,
  etfTransferFeeRate: 0,
  lotSize: 100,
  smallTradeCostWarnPct: 0.35,
  minTradeAmount: 1500,
  preferredTradeAmount: 3000,
  splitTradeMinAmount: 3000,
  minProfitFeeMultiple: 2,
};

export function normalizeTradingCosts(config = {}) {
  return {
    ...DEFAULT_TRADING_COSTS,
    ...Object.fromEntries(
      Object.entries(config ?? {}).filter(([, value]) => Number.isFinite(Number(value))),
    ),
  };
}

export function getChinaTradeSession(now = new Date()) {
  const parts = getChinaDateTimeParts(now);
  const tradingDay = getChinaTradingDayStatus(now);
  const minutes = parts.hour * 60 + parts.minute;
  const metadata = {
    tradeDate: tradingDay.date,
    calendarVerified: tradingDay.calendarCovered,
    calendarReason: tradingDay.reason,
  };

  if (!tradingDay.isTradingDay) {
    return { key: 'closed', label: tradingDay.reason, tradable: false, canSubmitOrder: false, ...metadata };
  }
  if (minutes >= 9 * 60 + 15 && minutes < 9 * 60 + 25) {
    return { key: 'opening_auction', label: '集合竞价', tradable: true, canSubmitOrder: true, ...metadata };
  }
  if (minutes >= 9 * 60 + 25 && minutes < 9 * 60 + 30) {
    return { key: 'pre_open_pause', label: '开盘前撮合/等待', tradable: false, canSubmitOrder: true, ...metadata };
  }
  if ((minutes >= 9 * 60 + 30 && minutes < 11 * 60 + 30) || (minutes >= 13 * 60 && minutes < 14 * 60 + 57)) {
    return { key: 'continuous', label: '连续竞价', tradable: true, canSubmitOrder: true, ...metadata };
  }
  if (minutes >= 14 * 60 + 57 && minutes <= 15 * 60) {
    return { key: 'closing_auction', label: '尾盘集合竞价', tradable: true, canSubmitOrder: true, ...metadata };
  }
  if (minutes >= 11 * 60 + 30 && minutes < 13 * 60) {
    return { key: 'lunch_break', label: '午间休市', tradable: false, canSubmitOrder: true, ...metadata };
  }
  if (minutes > 15 * 60) {
    return { key: 'after_close', label: '已收盘', tradable: false, canSubmitOrder: false, ...metadata };
  }
  return { key: 'pre_market', label: '盘前', tradable: false, canSubmitOrder: false, ...metadata };
}

export function getHoldingDays(buyDate, now = new Date()) {
  if (!buyDate || Number.isNaN(Date.parse(buyDate))) return null;
  const start = toChinaDateString(new Date(buyDate));
  const end = toChinaDateString(now);
  const startTime = Date.parse(`${start}T00:00:00+08:00`);
  const endTime = Date.parse(`${end}T00:00:00+08:00`);
  return Math.max(0, Math.floor((endTime - startTime) / 86400000));
}

export function isTPlusOneBlocked(position = {}, now = new Date()) {
  const type = String(position.assetType ?? '').toLowerCase();
  if (!isExchangeTraded(type)) return false;
  const holdingDays = getHoldingDays(position.buyDate, now);
  return holdingDays === 0;
}

export function estimateTradeFees(amount, side = 'buy', assetType = 'stock', config = {}) {
  const costs = normalizeTradingCosts(config);
  const value = Math.max(0, Number(amount) || 0);
  const type = String(assetType ?? 'stock').toLowerCase();
  const isEtf = type === 'etf';
  const commission = value > 0 ? Math.max(value * costs.commissionRate, costs.minCommission) : 0;
  const stampDutyRate = isEtf ? costs.etfStampDutyRate : costs.stampDutyRate;
  const transferFeeRate = isEtf ? costs.etfTransferFeeRate : costs.transferFeeRate;
  const stampDuty = side === 'sell' ? value * stampDutyRate : 0;
  const transferFee = value * transferFeeRate;
  const total = commission + stampDuty + transferFee;
  return {
    amount: round(value, 2),
    commission: round(commission, 2),
    stampDuty: round(stampDuty, 2),
    transferFee: round(transferFee, 2),
    total: round(total, 2),
    minCommissionApplied: value > 0 && commission === costs.minCommission,
  };
}

export function estimateRoundTrip(position = {}, currentPrice, config = {}) {
  if (!isExchangeTraded(position.assetType ?? 'stock')) return null;
  const shares = Number(position.shares ?? 0);
  const avgCost = Number(position.avgCost ?? currentPrice);
  const price = Number(currentPrice);
  const assetType = position.assetType ?? 'stock';
  if (!Number.isFinite(shares) || shares <= 0 || !Number.isFinite(avgCost) || avgCost <= 0 || !Number.isFinite(price) || price <= 0) {
    return null;
  }

  const buyAmount = avgCost * shares;
  const sellAmount = price * shares;
  const buyFees = estimateTradeFees(buyAmount, 'buy', assetType, config);
  const sellFees = estimateTradeFees(sellAmount, 'sell', assetType, config);
  const grossPnl = sellAmount - buyAmount;
  const totalFees = buyFees.total + sellFees.total;
  const netPnl = grossPnl - totalFees;
  const feePctOfMarketValue = sellAmount ? totalFees / sellAmount * 100 : 0;
  const netPnlPct = buyAmount ? netPnl / buyAmount * 100 : 0;
  const breakEvenPrice = solveBreakEvenSellPrice(avgCost, shares, assetType, config);

  return {
    buyAmount: round(buyAmount, 2),
    sellAmount: round(sellAmount, 2),
    buyFees,
    sellFees,
    totalFees: round(totalFees, 2),
    grossPnl: round(grossPnl, 2),
    netPnl: round(netPnl, 2),
    feePctOfMarketValue: round(feePctOfMarketValue, 2),
    netPnlPct: round(netPnlPct, 2),
    breakEvenPrice,
    minCommissionDominates: buyFees.minCommissionApplied || sellFees.minCommissionApplied,
  };
}

export function estimateLotTrade(price, assetType = 'stock', config = {}, lots = 1) {
  if (!isExchangeTraded(assetType)) return null;
  const costs = normalizeTradingCosts(config);
  const lotSize = Number(costs.lotSize ?? 100);
  const shares = lotSize * Math.max(1, Number(lots) || 1);
  const amount = Number(price) * shares;
  if (!Number.isFinite(amount) || amount <= 0) return null;
  const buyFees = estimateTradeFees(amount, 'buy', assetType, costs);
  const sellFees = estimateTradeFees(amount, 'sell', assetType, costs);
  const totalFees = buyFees.total + sellFees.total;
  return {
    shares,
    amount: round(amount, 2),
    buyFees,
    sellFees,
    totalFees: round(totalFees, 2),
    roundTripPct: round(totalFees / amount * 100, 2),
    minCommissionDominates: buyFees.minCommissionApplied || sellFees.minCommissionApplied,
  };
}

export function buildTradingRisk(position = {}, currentPrice, config = {}, now = new Date()) {
  const assetType = String(position.assetType ?? 'stock').toLowerCase();
  if (!isExchangeTraded(assetType)) {
    return {
      session: { key: 'otc_fund', label: '场外申赎', tradable: false, canSubmitOrder: true },
      holdingDays: getHoldingDays(position.buyDate, now),
      tPlusOneBlocked: false,
      roundTrip: null,
      messages: ['场外基金/QDII按净值申赎，不按A股盘中成交和股票佣金估算'],
      actions: [],
    };
  }
  const session = getChinaTradeSession(now);
  const holdingDays = getHoldingDays(position.buyDate, now);
  const tPlusOneBlocked = isTPlusOneBlocked(position, now);
  const roundTrip = estimateRoundTrip(position, currentPrice, config);
  const sizing = analyzeTradeSizing(position, currentPrice, config);
  const messages = [];
  const actions = [];

  if (tPlusOneBlocked) {
    messages.push('T+1限制：今天买入的A股/场内ETF今天不能卖出');
    actions.push('今日只做观察，最早下个交易日处理');
  }
  if (!session.tradable) {
    messages.push(`当前交易期：${session.label}，无法即时成交`);
  }
  if (roundTrip?.minCommissionDominates) {
    messages.push('单笔金额偏小，最低佣金对收益影响较大');
  }
  if (roundTrip && roundTrip.feePctOfMarketValue >= normalizeTradingCosts(config).smallTradeCostWarnPct) {
    messages.push(`往返费用约占市值${roundTrip.feePctOfMarketValue}%`);
  }
  if (roundTrip && roundTrip.netPnl > 0 && roundTrip.netPnl < roundTrip.totalFees) {
    actions.push('小盈利优先合并成一次交易，避免分批手续费吞利润');
  }

  if (sizing) {
    messages.push(...sizing.messages);
    actions.push(...sizing.actions);
  }

  return {
    session,
    holdingDays,
    tPlusOneBlocked,
    roundTrip,
    sizing,
    messages,
    actions,
  };
}

export function analyzeTradeSizing(position = {}, currentPrice, config = {}) {
  if (!isExchangeTraded(position.assetType ?? 'stock')) return null;
  const costs = normalizeTradingCosts(config);
  const shares = Number(position.shares ?? 0);
  const price = Number(currentPrice);
  if (!Number.isFinite(shares) || shares <= 0 || !Number.isFinite(price) || price <= 0) return null;

  const lotSize = Number(costs.lotSize ?? 100);
  const marketValue = shares * price;
  const positionLots = lotSize > 0 ? Math.floor(shares / lotSize) : 0;
  const oneLotAmount = lotSize * price;
  const roundTrip = estimateRoundTrip(position, currentPrice, costs);
  const minTradeAmount = Number(costs.minTradeAmount ?? DEFAULT_TRADING_COSTS.minTradeAmount);
  const preferredTradeAmount = Number(costs.preferredTradeAmount ?? DEFAULT_TRADING_COSTS.preferredTradeAmount);
  const splitTradeMinAmount = Number(costs.splitTradeMinAmount ?? DEFAULT_TRADING_COSTS.splitTradeMinAmount);
  const minProfitFeeMultiple = Number(costs.minProfitFeeMultiple ?? DEFAULT_TRADING_COSTS.minProfitFeeMultiple);
  const messages = [];
  const actions = [];

  const canSplit = positionLots >= 2 && marketValue / 2 >= splitTradeMinAmount;
  const suggestedMaxSlices = canSplit ? Math.max(2, Math.floor(marketValue / splitTradeMinAmount)) : 1;
  const minProfitToTrade = round((roundTrip?.totalFees ?? 0) * minProfitFeeMultiple, 2);
  let decision = 'normal';

  if (marketValue < minTradeAmount) {
    decision = 'avoid_small_trade';
    messages.push(`持仓市值约${round(marketValue, 2)}元，低于建议单笔${minTradeAmount}元，最低佣金会明显吞噬收益`);
    actions.push('除非必须止损/清仓，否则小金额持仓不建议频繁买卖');
  } else if (marketValue < preferredTradeAmount) {
    decision = 'whole_position_only';
    messages.push(`持仓市值约${round(marketValue, 2)}元，低于偏好单笔${preferredTradeAmount}元，不适合精细分批`);
    actions.push('如需交易优先整笔处理，避免拆成多笔支付最低佣金');
  }

  if (!canSplit && positionLots >= 2) {
    decision = decision === 'normal' ? 'whole_position_only' : decision;
    messages.push(`可交易约${positionLots}手，但拆单后单笔金额偏小，不建议分批`);
    actions.push('分批止盈/止损应改为一次性挂单或等待更明确价位');
  }

  if (roundTrip?.feePctOfMarketValue >= costs.smallTradeCostWarnPct) {
    messages.push(`往返费用约占市值${roundTrip.feePctOfMarketValue}%，盈利至少覆盖约${minProfitToTrade}元再考虑主动卖出`);
  }

  if (canSplit) {
    decision = 'can_split';
    actions.push(`可分批但最多约${suggestedMaxSlices}笔，每笔尽量不低于${splitTradeMinAmount}元`);
  }

  return {
    marketValue: round(marketValue, 2),
    lotSize,
    positionLots,
    oneLotAmount: round(oneLotAmount, 2),
    minTradeAmount,
    preferredTradeAmount,
    splitTradeMinAmount,
    suggestedMaxSlices,
    canSplit,
    minProfitToTrade,
    decision,
    messages,
    actions: [...new Set(actions)],
  };
}

function isExchangeTraded(assetType = 'stock') {
  const type = String(assetType ?? 'stock').toLowerCase();
  return !['open_fund', 'fund', 'qdii', 'etf_link'].includes(type);
}

function solveBreakEvenSellPrice(avgCost, shares, assetType, config = {}) {
  const buyAmount = avgCost * shares;
  const buyFees = estimateTradeFees(buyAmount, 'buy', assetType, config).total;
  let low = avgCost;
  let high = avgCost * 1.2 + 1;
  for (let i = 0; i < 40; i += 1) {
    const mid = (low + high) / 2;
    const sellAmount = mid * shares;
    const sellFees = estimateTradeFees(sellAmount, 'sell', assetType, config).total;
    const net = sellAmount - sellFees - buyAmount - buyFees;
    if (net >= 0) high = mid;
    else low = mid;
  }
  return round(high, 3);
}

function toChinaDateString(date) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(date);
}
