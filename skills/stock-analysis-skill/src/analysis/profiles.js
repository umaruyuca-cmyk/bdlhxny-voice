// 统一的客观分析标准：不再区分保守/一般/激进画像。
// 所有判断基于技术指标本身的事实，使用同一套阈值与仓位规则。
// 取中性客观基准值：追高硬警告、确认下跌趋势仍强制阻断加仓。
export const STANDARD_POLICY = {
  key: 'standard',
  label: '客观标准',
  description: '基于技术指标的中性客观判断，不区分风险画像；追高警告和确认下跌趋势仍强制阻断加仓。',
  cashReserveFloor: 0.15,
  allocation: {
    minScore: 42,
    focusScore: 62,
    pullbackMa10Max: 3,
    pullbackMa20Max: 4,
    focusBoost: 1.35,
    steadyReason: '分批建仓',
  },
  signalThresholds: {
    strongBuy: 72,
    buy: 62,
    hold: 42,
    wait: 28,
  },
  positionLimits: {
    domestic_core: { preferredMax: 0.55, hardMax: 0.65 },
    global_core: { preferredMax: 0.45, hardMax: 0.50 },
    sector_aggressive: { preferredMax: 0.15, hardMax: 0.20 },
    global_growth: { preferredMax: 0.15, hardMax: 0.20 },
    single_stock: { preferredMax: 0.12, hardMax: 0.20 },
    defensive: { preferredMax: 0.45, hardMax: 0.65 },
  },
  profitTaking: [15, 25, 35],
};

// 兼容旧接口：恒返回唯一客观标准，入参被忽略。
export function normalizeAnalysisProfile() {
  return STANDARD_POLICY.key;
}

export function getAnalysisProfile() {
  return STANDARD_POLICY;
}

// 已无画像区分，任何 analysisProfile 值都视为可接受（会被忽略）。
export function isAnalysisProfile() {
  return true;
}

export function applyProfileLimits(instrument, _profileValue = STANDARD_POLICY.key, manualMaxWeight = null) {
  const limits = STANDARD_POLICY.positionLimits[instrument.role] ?? STANDARD_POLICY.positionLimits.single_stock;
  const explicitMax = Number(manualMaxWeight);
  if (Number.isFinite(explicitMax) && explicitMax > 0 && explicitMax <= 1) {
    return {
      ...instrument,
      preferredMax: explicitMax,
      hardMax: explicitMax,
      limitsSource: 'position.maxWeight',
    };
  }
  return {
    ...instrument,
    ...limits,
    limitsSource: STANDARD_POLICY.key,
  };
}
