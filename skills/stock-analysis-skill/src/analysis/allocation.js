import { round } from './technical.js';
import { getAnalysisProfile } from './profiles.js';
import { estimateTradeFees, normalizeTradingCosts } from './trading.js';

export function allocateMonthlyBudget(portfolio, holdings) {
  const profile = getAnalysisProfile(portfolio.analysisProfile);
  const policy = profile.allocation;
  const monthlyBudget = Number(portfolio.monthlyBudget);
  const tradingCosts = normalizeTradingCosts(portfolio.tradingCosts);
  const reserveRatio = Math.max(Number(portfolio.cashReserveRatio ?? profile.cashReserveFloor), profile.cashReserveFloor);
  const reserve = round(monthlyBudget * reserveRatio, 2);
  const deployable = round(monthlyBudget - reserve, 2);

  const candidates = holdings.map((holding) => {
    const score = holding.stockData.score.total;
    const chase = holding.stockData.chase;
    const technical = holding.stockData.technical;
    const downtrend = technical.ma.ma5 < technical.ma.ma10 && technical.ma.ma10 < technical.ma.ma20;
    const pullbackAvailable = (technical.deviation.ma10 ?? 99) <= policy.pullbackMa10Max
      || (technical.deviation.ma20 ?? 99) <= policy.pullbackMa20Max;
    const overweight = score >= policy.focusScore && technical.trend === 'uptrend' && pullbackAvailable && chase.level !== 'hard';
    const skipReasons = [];

    if (score < policy.minScore) skipReasons.push(`评分 ${score}<${policy.minScore}`);
    if (technical.trend === 'downtrend' || downtrend) skipReasons.push('确认下跌趋势');
    if (chase.level === 'hard') skipReasons.push('追高警告 active');
    if (holding.stockData.dataQuality?.allowsDirectionalSignal === false) {
      skipReasons.push(`数据可信度不足：${holding.stockData.dataQuality.label}`);
    }
    if (holding.risk?.addBlocked) {
      const riskReason = holding.risk.messages[0] ?? '仓位/风控规则禁止加仓';
      skipReasons.push(riskReason);
    }

    const eligible = skipReasons.length === 0;
    const baseWeight = Math.max(holding.targetWeight, 0.01);
    const scoreWeight = Math.max(score, 30) / 100;
    const gapBoost = Math.max(0, holding.weightGap ?? 0) * 2;

    return {
      code: holding.position.code,
      name: holding.position.name,
      score,
      eligible,
      overweight,
      skipReasons,
      pullbackAvailable,
      weight: eligible ? baseWeight * scoreWeight * (1 + gapBoost) * (overweight ? policy.focusBoost : 1) : 0,
      holding,
    };
  });

  const totalWeight = candidates.reduce((sum, item) => sum + item.weight, 0);
  let used = 0;
  const plan = candidates.map((candidate) => {
    let amount = totalWeight > 0 ? round(deployable * candidate.weight / totalWeight, 2) : 0;
    const amountTooSmall = amount > 0 && amount < tradingCosts.minTradeAmount;
    if (amountTooSmall) amount = 0;
    const buyFee = estimateTradeFees(amount, 'buy', candidate.holding.position.assetType, tradingCosts);
    const feeNote = buyFee.minCommissionApplied && amount > 0
      ? `；单笔买入费约${buyFee.total}，最低佣金影响明显，适合合并交易`
      : '';
    used += amount;
    return {
      ...candidate,
      amount,
      buyFee,
      action: amountTooSmall ? '金额过小，合并等待' : candidate.eligible ? (candidate.overweight ? '重点部署' : '小额等待回踩') : '本月跳过',
      reason: candidate.eligible
        ? (amountTooSmall ? `建议金额低于${tradingCosts.minTradeAmount}元，最低佣金影响明显，先保留现金或合并到下一次交易` : candidate.overweight ? `评分${candidate.score}，趋势向上且有回踩${feeNote}` : `评分${candidate.score}，${policy.steadyReason}${feeNote}`)
        : candidate.skipReasons.join('；'),
    };
  });

  const leftover = round(Math.max(0, deployable - used), 2);

  return {
    monthlyBudget,
    profile,
    reserveRatio,
    reserve,
    deployable,
    plan,
    leftover,
    totalSuggested: round(used, 2),
  };
}
