import { round } from './technical.js';
import { applyProfileLimits, getAnalysisProfile } from './profiles.js';

const AGGRESSIVE_KEYWORDS = ['半导体', '芯片', '存储', '科创', '新能源', '军工', '医药', '传媒', '游戏', '机器人', 'AI', '人工智能'];
const BROAD_A_KEYWORDS = ['A500', '沪深300', '中证500', '中证800', '中证1000', '上证50', '全指'];
const GLOBAL_BROAD_KEYWORDS = ['标普500', '标普 500', 'S&P500', 'S&P 500', 'SP500'];
const GLOBAL_GROWTH_KEYWORDS = ['纳斯达克', 'NASDAQ', '纳指'];
const DEFENSIVE_KEYWORDS = ['红利', '低波', '短债', '中短债', '货币', '国债', '债券'];

const KNOWN = {
  '159801': { role: 'sector_aggressive', label: '半导体芯片ETF', preferredMax: 0.10, hardMax: 0.15 },
  '008888': { role: 'sector_aggressive', label: '半导体芯片ETF联接C', preferredMax: 0.10, hardMax: 0.15, openFund: true },
  '022463': { role: 'domestic_core', label: '中证A500核心仓', preferredMax: 0.50, hardMax: 0.60, openFund: true },
  '017641': { role: 'global_core', label: '标普500海外核心仓', preferredMax: 0.40, hardMax: 0.45, openFund: true, qdii: true },
};

export function classifyInstrument(position = {}, stockData = {}, profileValue = 'standard') {
  const code = String(position.code ?? stockData.code ?? '').trim();
  const name = `${position.name ?? ''} ${stockData.name ?? ''} ${position.sector ?? ''}`.toUpperCase();
  const manualType = String(position.assetType ?? position.riskRole ?? '').toLowerCase();

  if (KNOWN[code]) {
    return applyProfileLimits({ code, ...KNOWN[code], source: 'known-code' }, profileValue, position.maxWeight);
  }

  if (['sector', 'aggressive', 'industry'].includes(manualType)) {
    return applyProfileLimits({ code, role: 'sector_aggressive', label: '行业进攻仓', source: 'manual' }, profileValue, position.maxWeight);
  }
  if (['global', 'qdii', 'overseas'].includes(manualType)) {
    return applyProfileLimits({ code, role: 'global_core', label: '海外核心仓', qdii: true, source: 'manual' }, profileValue, position.maxWeight);
  }
  if (['broad', 'core', 'a_core'].includes(manualType)) {
    return applyProfileLimits({ code, role: 'domestic_core', label: 'A股宽基核心仓', source: 'manual' }, profileValue, position.maxWeight);
  }
  if (['defensive', 'bond', 'cash'].includes(manualType)) {
    return applyProfileLimits({ code, role: 'defensive', label: '防守/低波仓', source: 'manual' }, profileValue, position.maxWeight);
  }

  if (containsAny(name, GLOBAL_GROWTH_KEYWORDS)) {
    return applyProfileLimits({ code, role: 'global_growth', label: '海外科技进攻仓', qdii: true, source: 'name' }, profileValue, position.maxWeight);
  }
  if (containsAny(name, GLOBAL_BROAD_KEYWORDS)) {
    return applyProfileLimits({ code, role: 'global_core', label: '标普500海外核心仓', qdii: true, source: 'name' }, profileValue, position.maxWeight);
  }
  if (containsAny(name, AGGRESSIVE_KEYWORDS)) {
    return applyProfileLimits({ code, role: 'sector_aggressive', label: '行业进攻仓', source: 'name' }, profileValue, position.maxWeight);
  }
  if (containsAny(name, DEFENSIVE_KEYWORDS)) {
    return applyProfileLimits({ code, role: 'defensive', label: '防守/低波仓', source: 'name' }, profileValue, position.maxWeight);
  }
  if (containsAny(name, BROAD_A_KEYWORDS)) {
    return applyProfileLimits({ code, role: 'domestic_core', label: 'A股宽基核心仓', source: 'name' }, profileValue, position.maxWeight);
  }

  return applyProfileLimits({ code, role: 'single_stock', label: '个股/未分类', source: 'default' }, profileValue, position.maxWeight);
}

export function evaluateHoldingRisk(holding, analysisProfileValue = 'standard') {
  const analysisProfile = getAnalysisProfile(analysisProfileValue);
  const profile = classifyInstrument(holding.position, holding.stockData, analysisProfile.key);
  const currentWeight = Number(holding.currentWeight ?? 0);
  const pnlPct = Number(holding.pnlPct ?? 0);
  const messages = [];
  const actions = [];
  let addBlocked = false;

  const preferredWeightPct = round(profile.preferredMax * 100, 2);
  const hardWeightPct = round(profile.hardMax * 100, 2);
  const currentWeightPct = round(currentWeight * 100, 2);

  if (currentWeight > profile.hardMax) {
    messages.push(`仓位 ${currentWeightPct}% 已超过硬上限 ${hardWeightPct}%`);
    actions.push('优先降仓');
    addBlocked = true;
  } else if (currentWeight > profile.preferredMax) {
    messages.push(`仓位 ${currentWeightPct}% 高于建议上限 ${preferredWeightPct}%`);
    actions.push('暂停加仓');
    addBlocked = true;
  }

  if (['sector_aggressive', 'global_growth', 'single_stock'].includes(profile.role)) {
    const [first, second, third] = analysisProfile.profitTaking;
    if (pnlPct >= third) actions.push(`盈利${third}%+：建议大部分止盈，仅留底仓`);
    else if (pnlPct >= second) actions.push(`盈利${second}%+：建议再卖1/3，锁定利润`);
    else if (pnlPct >= first) actions.push(`盈利${first}%+：可卖1/3，降低波动`);
  }

  if (holding.stockData?.chase?.level === 'hard') {
    messages.push('触发追高警告，禁止新增买入');
    addBlocked = true;
  }
  if (holding.stockData?.dataQuality?.allowsDirectionalSignal === false) {
    messages.push(`数据可信度不足：${holding.stockData.dataQuality.label}`);
    actions.push('暂停新增，先刷新并核验数据时间');
    addBlocked = true;
  }

  const holdingDays = calculateHoldingDays(holding.position.buyDate);
  if (holdingDays != null && holdingDays < 7 && isLikelyOpenFund(holding.position, profile)) {
    messages.push(`持有约 ${holdingDays} 天，场外基金可能触发不足7天高赎回费`);
  }

  const rating = addBlocked ? '高风险/不加仓' : messages.length ? '关注' : '正常';
  return {
    profile,
    analysisProfile,
    rating,
    messages,
    actions,
    addBlocked,
    holdingDays,
  };
}

export function shouldBlockNewBuy(holding) {
  return Boolean(holding?.risk?.addBlocked);
}

function containsAny(text, keywords) {
  return keywords.some((keyword) => text.includes(String(keyword).toUpperCase()));
}

function calculateHoldingDays(buyDate) {
  if (!buyDate || Number.isNaN(Date.parse(buyDate))) return null;
  const start = new Date(buyDate);
  const now = new Date();
  return Math.max(0, Math.floor((now.getTime() - start.getTime()) / 86400000));
}

function isLikelyOpenFund(position = {}, profile = {}) {
  const type = String(position.assetType ?? '').toLowerCase();
  if (profile.openFund || profile.qdii) return true;
  if (['fund', 'open_fund', 'qdii', 'etf_link'].includes(type)) return true;
  const name = `${position.name ?? ''}`;
  return /联接|QDII|基金|C$|A$/.test(name);
}
