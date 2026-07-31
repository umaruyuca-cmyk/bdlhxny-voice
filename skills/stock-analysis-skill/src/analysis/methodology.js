export const METHODOLOGY_ID = 'stockwise-objective-analysis';
export const METHODOLOGY_VERSION = '1.1.0';

const RULES = Object.freeze({
  'DATA-FRESH-001': {
    evidenceLevel: 'risk_policy',
    summary: '行情时间、交易日和K线同步性不通过时阻断方向性信号',
  },
  'TECH-IND-001': {
    evidenceLevel: 'deterministic',
    summary: '使用固定公式计算MA、MACD、RSI、乖离、量比与支撑压力',
  },
  'SCORE-HEURISTIC-001': {
    evidenceLevel: 'heuristic',
    summary: '六维100分技术评分用于规则化排序，尚未完成独立样本外校准',
  },
  'CHASE-HARD-001': {
    evidenceLevel: 'risk_policy',
    summary: '过热、严重乖离或量价背离触发禁止新增',
  },
  'PORT-RISK-001': {
    evidenceLevel: 'risk_policy',
    summary: '检查仓位上限、集中度、现金底线、交易费用与T+1',
  },
  'ALLOC-HEURISTIC-001': {
    evidenceLevel: 'heuristic',
    summary: '按目标权重、评分、欠配程度和回踩条件分配可部署预算',
  },
  'QUANT-MOM-001': {
    evidenceLevel: 'research_based',
    summary: '使用20/60/120日横截面动量Z分数进行ETF排序',
  },
  'QUANT-VOL-001': {
    evidenceLevel: 'research_based',
    summary: '使用逆波动率、单品种上限和目标波动率确定组合暴露',
  },
  'BACKTEST-NOFUTURE-001': {
    evidenceLevel: 'deterministic',
    summary: '调仓信号只使用前一交易日及更早数据并扣除配置成本',
  },
  'SECTOR-HEAT-001': {
    evidenceLevel: 'heuristic',
    summary: '按同类板块横截面分位数标准化后，对日/5日/20日涨跌、资金和换手加权计算板块热度',
  },
});

const COMMAND_RULES = Object.freeze({
  stock: ['DATA-FRESH-001', 'TECH-IND-001', 'SCORE-HEURISTIC-001', 'CHASE-HARD-001'],
  portfolio: [
    'DATA-FRESH-001',
    'TECH-IND-001',
    'SCORE-HEURISTIC-001',
    'CHASE-HARD-001',
    'PORT-RISK-001',
    'ALLOC-HEURISTIC-001',
  ],
  quant: ['QUANT-MOM-001', 'QUANT-VOL-001', 'BACKTEST-NOFUTURE-001'],
  sector: ['SECTOR-HEAT-001'],
});

/**
 * 返回可随结果交付的方法论版本和规则目录，使消费者能够定位代码与文档。
 */
export function methodologyFor(command) {
  const ruleIds = COMMAND_RULES[command] ?? [];
  return {
    id: METHODOLOGY_ID,
    version: METHODOLOGY_VERSION,
    nature: 'deterministic_engine_with_declared_heuristics',
    documentation: 'references/methodology.md',
    rules: ruleIds.map((ruleId) => ({
      ruleId,
      ...RULES[ruleId],
    })),
  };
}

/**
 * 构建单标的结论依据，明确硬门禁、观测值和启发式评分边界。
 */
export function stockDecisionBasis(data) {
  const quality = data.dataQuality ?? {};
  const chase = data.chase ?? {};
  const score = data.score ?? {};
  const technical = data.technical ?? {};
  return {
    verdict: score.signal ?? 'unknown',
    gates: [
      {
        ruleId: 'DATA-FRESH-001',
        passed: quality.allowsDirectionalSignal === true,
        observed: {
          status: quality.status ?? 'unknown',
          asOf: quality.asOf ?? null,
          latestBarDate: quality.latestBarDate ?? null,
        },
        consequence: quality.allowsDirectionalSignal === true ? '允许解释方向性信号' : '强制观望并刷新数据',
      },
      {
        ruleId: 'CHASE-HARD-001',
        passed: chase.level !== 'hard',
        observed: {
          level: chase.level ?? 'unknown',
          reasons: chase.reasons ?? [],
        },
        consequence: chase.level === 'hard' ? '禁止买入或加仓' : '未触发追高硬阻断',
      },
    ],
    evidence: [
      {
        ruleId: 'SCORE-HEURISTIC-001',
        observed: {
          total: score.total ?? null,
          rawTotal: score.rawTotal ?? null,
          dimensions: score.dimensions ?? {},
          alignment: technical.alignment ?? null,
        },
        thresholds: {
          strongBuy: 72,
          buy: 62,
          hold: 42,
          wait: 28,
        },
        caveat: '该分值是未完成独立样本外校准的启发式排序，不代表胜率或预期收益',
      },
    ],
    limitations: [
      '缺少完整财报质量、盈利预测和公告事件核验时，不能形成长期价值结论',
      '技术指标是价格历史的变换，不是独立因果证据',
    ],
  };
}

/**
 * 构建组合结论依据，公开每只持仓的门禁、风险和资金分配原因。
 */
export function portfolioDecisionBasis({ holdings, summary, allocation, allowsDirectionalSignal }) {
  return {
    verdict: allowsDirectionalSignal ? 'portfolio_analysis_available' : 'wait_for_verified_data',
    gates: [
      {
        ruleId: 'DATA-FRESH-001',
        passed: allowsDirectionalSignal,
        consequence: allowsDirectionalSignal ? '所有持仓数据允许方向性分析' : '至少一只持仓数据未通过，阻断整体方向性结论',
      },
      {
        ruleId: 'PORT-RISK-001',
        passed: (summary.concentrationWarnings ?? []).length === 0,
        observed: {
          cashRatio: summary.cashRatio ?? null,
          concentrationWarnings: summary.concentrationWarnings ?? [],
        },
        consequence: (summary.concentrationWarnings ?? []).length
          ? '披露集中风险并限制新增'
          : '未触发35%板块集中警告',
      },
    ],
    holdings: holdings.map((holding) => ({
      code: holding.position.code,
      score: holding.stockData?.score?.total ?? null,
      signal: holding.stockData?.score?.signal ?? null,
      chaseLevel: holding.stockData?.chase?.level ?? null,
      dataQuality: holding.stockData?.dataQuality?.status ?? null,
      addBlocked: Boolean(holding.risk?.addBlocked),
      reasons: holding.risk?.messages ?? [],
    })),
    allocation: (allocation.plan ?? []).map((item) => ({
      code: item.code,
      eligible: item.eligible,
      amount: item.amount,
      action: item.action,
      reasons: item.eligible ? [item.reason] : item.skipReasons,
    })),
    limitations: [
      '当前组合模块未使用完整协方差矩阵、VaR/CVaR和压力测试',
      '资金分配属于启发式风险预算，不是均值方差最优解',
    ],
  };
}

/**
 * 构建量化模型依据，公开参数、市场过滤结果和回测边界。
 */
export function quantDecisionBasis(result) {
  return {
    verdict: result.currentRegime?.eligible ? 'risk_on' : 'cash',
    gates: [{
      ruleId: 'QUANT-VOL-001',
      passed: Boolean(result.currentRegime?.eligible),
      observed: result.currentRegime ?? {},
      consequence: result.currentRegime?.eligible ? '允许按目标权重持仓' : '市场过滤触发，目标转为现金',
    }],
    evidence: [{
      ruleId: 'QUANT-MOM-001',
      formula: '0.40×Z(R20)+0.35×Z(R60)+0.25×Z(R120)，并要求价格高于MA60',
      ranking: (result.currentRanking ?? []).map((item) => ({
        code: item.code,
        score: item.score,
        trendEligible: item.features?.trendEligible,
        momentum: item.features?.momentum,
        annualizedVolatility: item.features?.annualizedVolatility,
      })),
    }],
    backtest: {
      ruleId: 'BACKTEST-NOFUTURE-001',
      period: result.period ?? null,
      metrics: result.metrics ?? null,
      transactionCostRate: result.config?.transactionCostRate ?? null,
    },
    limitations: [
      '候选ETF池可能存在幸存者偏差',
      '回测未完整模拟涨跌停、停牌、冲击成本、申赎和跟踪误差',
      '需要滚动样本外验证和参数敏感性测试后才能评估稳健性',
    ],
  };
}

/**
 * 构建板块排序依据，公开热度公式和每个入选板块的组成值。
 */
export function sectorDecisionBasis(sectorData) {
  const coverage = sectorData.historyCoverage ?? { requested: 0, succeeded: 0 };
  return {
    verdict: 'relative_ranking_only',
    evidence: [{
      ruleId: 'SECTOR-HEAT-001',
      formula: '0.35×日涨跌分位+0.25×5日涨跌分位+0.15×20日涨跌分位+0.15×主力净流入分位+0.10×换手率分位；缺失分项不补零，按可用权重重标',
      formulaVersion: 'sector-heat-v2',
      normalization: 'cross_sectional_percentile',
      ranking: (sectorData.sectors ?? []).map((sector) => ({
        code: sector.code,
        name: sector.name,
        heatScore: sector.heatScore,
        changePct: sector.changePct,
        change5d: sector.change5d,
        change20d: sector.change20d,
        mainNetInflow: sector.mainNetInflow,
        turnoverRate: sector.turnoverRate,
        heatScoreQuality: sector.heatScoreQuality,
        heatScoreBreakdown: sector.heatScoreBreakdown,
      })),
    }],
    limitations: [
      '板块热度是启发式相对排序，不代表后续上涨概率',
      '供应商主力资金口径不等同于交易所逐笔资金审计',
      `20日K线核验覆盖 ${coverage.succeeded}/${coverage.requested}；未覆盖板块不计算20日贡献且不得提升为方向性结论`,
    ],
  };
}
