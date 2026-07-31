import { DEFAULTS, loadPortfolio } from './config.js';
import { fetchMarketOverview } from './data/market.js';
import { fetchOvernightContext } from './data/overseas.js';
import { fetchRankedSectors } from './data/sector.js';
import { fetchStockBundle, isSupportedIndexCode } from './data/stock.js';
import { allocateMonthlyBudget } from './analysis/allocation.js';
import { analyzeHolding, calculatePortfolioSummary } from './analysis/position.js';
import { getAnalysisProfile } from './analysis/profiles.js';
import { backtestMomentumRotation } from './analysis/quant.js';
import { buildTradingRisk, estimateLotTrade, getChinaTradeSession, normalizeTradingCosts } from './analysis/trading.js';
import { renderDecisionBoard, renderSectorHeatmap } from './output/decision-board.js';
import { chaseLabel, makeTable, money, pct, plainNumber, signalLabel } from './output/formatter.js';
import { logWarn } from './utils/logger.js';
import { saveAnalysisOutput } from './utils/storage.js';
import { fetchKlineHistory } from './data/stock.js';
import { chinaDateString } from './utils/china-time.js';
import { buildSuccessContract, writeJsonContract } from './output/json-contract.js';
import { mapWithConcurrency } from './utils/concurrency.js';
import {
  portfolioDecisionBasis,
  quantDecisionBasis,
  sectorDecisionBasis,
  stockDecisionBasis,
} from './analysis/methodology.js';

export function completedDailyBars(history, now = new Date()) {
  const session = getChinaTradeSession(now);
  const today = chinaDateString(now);
  const currentDayIsComplete = session.key === 'after_close';
  return history.filter((row) => currentDayIsComplete || row.date !== today);
}

/**
 * 构建稳定、可供后端程序读取的单标的分析数据契约。
 */
export function buildStockJsonOutput({ data, profile, session, lotTrade, tradingRisk, options = {} }) {
  return {
    ...buildSuccessContract('stock', {
      asOf: data.dataQuality?.asOf ?? null,
      request: {
        code: data.code,
        asset: options.asset ?? 'auto',
        days: options.days ?? 120,
      },
      dataQuality: data.dataQuality,
      data,
      sources: data.sources ?? {},
      decisionBasis: stockDecisionBasis(data),
    }),
    profile: {
      key: profile.key,
      label: profile.label,
      description: profile.description,
    },
    trading: {
      session,
      lotTrade,
      positionRisk: tradingRisk,
    },
  };
}

export async function runQuantAnalysis(codes, options = {}) {
  const uniqueCodes = [...new Set(codes.map((code) => String(code).trim()).filter(Boolean))];
  if (uniqueCodes.length < 2) throw new Error('量化轮动至少需要两个ETF代码');
  const days = options.historyDays ?? 750;
  const benchmarkCode = String(options.benchmark ?? '510300');
  const fetched = await mapWithConcurrency(uniqueCodes, DEFAULTS.quantFetchConcurrency, async (code) => {
    const result = await fetchKlineHistory(code, days, options);
    return { code, name: code, history: completedDailyBars(result.history, options.now), source: result.source };
  });
  const benchmarkIsIndex = isSupportedIndexCode(benchmarkCode);
  const benchmark = !benchmarkIsIndex && uniqueCodes.includes(benchmarkCode)
    ? fetched.find((asset) => asset.code === benchmarkCode)
    : await fetchKlineHistory(benchmarkCode, days, {
      ...options,
      instrumentType: benchmarkIsIndex ? 'index' : options.instrumentType,
    }).then((result) => ({
      code: benchmarkCode,
      name: benchmarkCode,
      history: completedDailyBars(result.history, options.now),
      source: result.source,
    }));
  const config = {
    selectCount: options.selectCount,
    maxAssetWeight: options.maxAssetWeight,
    targetAnnualVolatility: options.targetVol,
    rebalanceEvery: options.rebalanceEvery,
    transactionCostRate: options.transactionCostRate,
  };
  Object.keys(config).forEach((key) => config[key] == null && delete config[key]);
  const result = backtestMomentumRotation(fetched, config, benchmark);

  if (options.json) {
    const jsonOutput = buildQuantJsonOutput({
      result,
      codes: uniqueCodes,
      benchmarkCode,
      fetched,
      benchmark,
    });
    writeJsonContract(jsonOutput);
    return jsonOutput;
  }

  const metrics = result.metrics;
  const metricRows = [
    ['回测区间', `${result.period.start} 至 ${result.period.end}（${result.period.tradingDays}日）`],
    ['基准过滤', `${benchmarkCode}：${result.currentRegime?.eligible ? '允许持仓' : '转为现金'}；数据截至 ${result.currentRegime?.asOf ?? 'N/A'}`],
    ['累计收益 / CAGR', `${pct(metrics.totalReturn * 100)} / ${pct(metrics.cagr * 100)}`],
    ['基准收益 / CAGR', result.benchmarkMetrics
      ? `${pct(result.benchmarkMetrics.totalReturn * 100)} / ${pct(result.benchmarkMetrics.cagr * 100)}`
      : 'N/A'],
    ['年化波动 / Sharpe', `${pct(metrics.annualizedVolatility * 100)} / ${plainNumber(metrics.sharpe)}`],
    ['最大回撤 / Calmar', `${pct(metrics.maxDrawdown * 100)} / ${plainNumber(metrics.calmar)}`],
    ['累计换手 / 成本拖累', `${pct(metrics.totalTurnover * 100)} / ${pct(metrics.estimatedCostDrag * 100)}`],
  ];
  const rankRows = result.currentRanking.map((asset, index) => [
    index + 1,
    asset.code,
    plainNumber(asset.score, 3),
    asset.features.trendEligible ? '通过' : '未通过',
    pct(asset.features.momentum[20] * 100),
    pct(asset.features.momentum[60] * 100),
    pct(asset.features.momentum[120] * 100),
    pct(asset.features.annualizedVolatility * 100),
    pct((result.currentAllocation.weights[asset.code] ?? 0) * 100),
  ]);
  const lines = [
    '\nETF多周期动量 + 波动率目标回测',
    makeTable(['项目', '结果'], metricRows, { colWidths: [20, 56] }),
    makeTable(
      ['排名', '代码', '动量Z分', 'MA60', '20日', '60日', '120日', '年化波动', '目标仓位'],
      rankRows,
      { colWidths: [6, 10, 10, 8, 10, 10, 10, 12, 12] },
    ),
    `现金目标: ${pct(result.currentAllocation.cashWeight * 100)}`,
    `口径: 仅使用已完成日K；信号使用前一交易日及更早数据；每${result.config.rebalanceEvery}个共同交易日调仓；成本按单边费率估算。`,
    '提醒: 当前结果是历史回测，不是实时行情或收益保证；未包含最低佣金、冲击成本、涨跌停和申赎限制。',
  ];
  const output = lines.join('\n');
  console.log(output);
  if (options.save !== false) saveAnalysisOutput('quant', uniqueCodes.join('-'), output);
  return result;
}

export async function runSectorAnalysis(options = {}) {
  const sectorData = await fetchRankedSectors({ type: options.type, limit: options.limit ?? 20, verbose: options.verbose });
  if (options.json) {
    const jsonOutput = buildSectorJsonOutput(sectorData, options);
    writeJsonContract(jsonOutput);
    return jsonOutput;
  }
  const output = renderSectorHeatmap(sectorData);
  console.log(output);
  if (options.save !== false) {
    saveAnalysisOutput('sector', '', output);
  }
}

export async function runPortfolioAnalysis(options = {}) {
  const portfolio = loadPortfolio(options.config, {
    allowFallback: !options.json,
    requirePositions: Boolean(options.json),
  });
  portfolio.__meta.warnings.forEach(logWarn);

  const sectorLimit = options.sectorLimit ?? 10;
  // 1. 持仓行情是组合结论的核心事实，限制并发并在支持性数据之前完成。
  const bundles = await mapWithConcurrency(
    portfolio.positions,
    DEFAULTS.portfolioFetchConcurrency,
    (position) => fetchStockBundle(position.code, {
      ...options,
      analysisProfile: portfolio.analysisProfile,
      assetType: position.assetType ?? position.riskRole,
    }),
  );
  // 2. 市场、板块和海外背景属于支持信息，失败时不得覆盖已经核验的持仓事实。
  const [market, sectorData, overseas] = await Promise.all([
    fetchMarketOverview(options),
    fetchRankedSectors({
      limit: sectorLimit,
      type: 'industry',
      verbose: options.verbose,
      historyEnrichmentLimit: 0,
    }).catch((error) => emptySectorData('industry', error)),
    fetchOvernightContext(options),
  ]);

  const preliminaryValue = bundles.reduce((sum, bundle, index) => {
    const position = portfolio.positions[index];
    const price = bundle.quote.price ?? bundle.technical.close ?? position.avgCost;
    return sum + price * position.shares;
  }, Number(portfolio.cash ?? 0));

  const holdings = portfolio.positions.map((position, index) => analyzeHolding(
    position,
    bundles[index],
    preliminaryValue,
    Number(portfolio.monthlyBudget),
    portfolio.analysisProfile,
    portfolio.tradingCosts,
  ));
  const summary = calculatePortfolioSummary(portfolio, holdings);
  const allocation = allocateMonthlyBudget(portfolio, holdings);

  if (options.json) {
    const jsonOutput = buildPortfolioJsonOutput({
      portfolio,
      market,
      sectorData,
      holdings,
      summary,
      allocation,
      overseas,
      sectorLimit,
    });
    writeJsonContract(jsonOutput);
    return jsonOutput;
  }
  const output = renderDecisionBoard({ portfolio, market, sectorData, holdings, summary, allocation, overseas });
  console.log(output);
  if (options.save !== false) {
    saveAnalysisOutput('portfolio', '', output);
  }
}

/**
 * 板块背景不可用时返回显式空结果，使组合分析能够按持仓事实安全降级。
 */
function emptySectorData(type, error) {
  return {
    type,
    sectors: [],
    leaders: [],
    laggards: [],
    rotation: {
      strong5d: [],
      weak5d: [],
      fundDivergence: [],
    },
    dataTime: null,
    warnings: [`板块数据暂不可用：${error.message}`],
  };
}

export async function runStockAnalysis(code, options = {}) {
  const profile = getAnalysisProfile();
  const data = await fetchStockBundle(code, { ...options, analysisProfile: profile.key });
  const technical = data.technical;
  const tradingCosts = normalizeTradingCosts({
    commissionRate: options.commissionRate,
    minCommission: options.minCommission,
    stampDutyRate: options.stampDutyRate,
    transferFeeRate: options.transferFeeRate,
    minTradeAmount: options.minTradeAmount,
    preferredTradeAmount: options.preferredTradeAmount,
    splitTradeMinAmount: options.splitTradeMinAmount,
    minProfitFeeMultiple: options.minProfitFeeMultiple,
  });
  const effectivePrice = data.quote.price > 0 ? data.quote.price : data.technical.close;
  const session = data.assetKind === 'open_fund'
    ? { key: 'otc_fund', label: '场外申赎（按净值确认）', tradable: false }
    : getChinaTradeSession();
  const lotTrade = estimateLotTrade(effectivePrice, options.asset, tradingCosts);
  const virtualPosition = Number.isFinite(Number(options.shares)) && Number(options.shares) > 0
    ? {
      code: data.code,
      name: data.name,
      assetType: options.asset,
      avgCost: Number(options.avgCost ?? effectivePrice),
      shares: Number(options.shares),
      buyDate: options.buyDate,
    }
    : null;
  const tradingRisk = virtualPosition ? buildTradingRisk(virtualPosition, effectivePrice, tradingCosts) : null;
  if (options.json) {
    const jsonOutput = buildStockJsonOutput({
      data,
      profile,
      session,
      lotTrade,
      tradingRisk,
      options,
    });
    writeJsonContract(jsonOutput);
    return jsonOutput;
  }
  const rows = [
    ['分析标准', `${profile.label} - ${profile.description}`],
    [data.assetKind === 'open_fund' ? '最新公布净值' : '现价', `${money(data.quote.price)} (${pct(data.quote.changePct)})`],
    ['数据截至', data.dataQuality?.asOf ? `${data.dataQuality.asOf}（北京时间）` : 'N/A'],
    ['行情时间', data.dataQuality?.quoteTime ?? data.dataQuality?.tradeDate ?? '未核验'],
    ['数据可信度', data.dataQuality?.label ?? '未评估'],
    ['最新K线/净值', `${data.dataQuality?.latestBarDate ?? 'N/A'}${data.dataQuality?.provisional ? '（盘中临时）' : ''}`],
    ['评分', scoreLine(data.score)],
    ['市盈率(PE)', data.fundamental?.indicators?.pe != null ? plainNumber(data.fundamental.indicators.pe, 2) : 'N/A'],
    ['市净率(PB)', data.fundamental?.indicators?.pb != null ? plainNumber(data.fundamental.indicators.pb, 2) : 'N/A'],
    ['总市值', data.fundamental?.indicators?.marketCap != null ? `${plainNumber(data.fundamental.indicators.marketCap / 1e8, 2)}亿` : 'N/A'],
    ['追高状态', chaseLabel(data.chase)],
    ['MA5/10/20/60', [technical.ma.ma5, technical.ma.ma10, technical.ma.ma20, technical.ma.ma60].map((value) => plainNumber(value)).join(' / ')],
    ['RSI6/12/24', [technical.rsi.rsi6, technical.rsi.rsi12, technical.rsi.rsi24].map((value) => plainNumber(value)).join(' / ')],
    ['乖离 MA5/20/60', [technical.deviation.ma5, technical.deviation.ma20, technical.deviation.ma60].map((value) => pct(value)).join(' / ')],
    ['量比', `${plainNumber(technical.volume.volumeRatio)}${technical.volume.intradayScaled ? ' (盘中估算)' : ''}`],
    ['止损参考', money(data.technical.support.low20 ? data.technical.support.low20 * 0.97 : data.technical.ma.ma60 * 0.97)],
    ['交易期', `${session.label}${session.tradable ? '，可即时成交' : '，不可即时成交'}`],
  ];
  if (lotTrade) {
    rows.push([
      '一手费用',
      `${plainNumber(lotTrade.shares, 0)}股约${money(lotTrade.amount)}；买入费${money(lotTrade.buyFees.total)}，往返约${money(lotTrade.totalFees)}(${pct(lotTrade.roundTripPct)})${lotTrade.minCommissionDominates ? '；最低佣金影响明显' : ''}`,
    ]);
  }
  if (tradingRisk?.roundTrip) {
    rows.push(['持仓净盈亏', `${money(tradingRisk.roundTrip.netPnl)} (${pct(tradingRisk.roundTrip.netPnlPct)})；保本卖价约${money(tradingRisk.roundTrip.breakEvenPrice, 3)}`]);
    if (tradingRisk.sizing) {
      rows.push([
        '交易金额',
        `市值约${money(tradingRisk.sizing.marketValue)}；${tradingRisk.sizing.canSplit ? `可分批但每笔尽量不低于${money(tradingRisk.sizing.splitTradeMinAmount)}` : '不建议拆单，优先整笔处理'}；盈利至少覆盖${money(tradingRisk.sizing.minProfitToTrade)}`,
      ]);
    }
    rows.push(['交易限制', tradingRisk.messages.concat(tradingRisk.actions).join('；') || '无明显交易限制']);
  }
  const lines = [];
  lines.push(`\n${data.code} ${data.name} 标的分析`);
  lines.push(makeTable(['项目', '数值'], rows, { colWidths: [18, 54] }));
  if (data.chase.reasons.length) {
    lines.push(`追高原因: ${data.chase.reasons.join('；')}`);
  }
  if (data.dataQuality?.warnings?.length) {
    lines.push(`数据提醒: ${data.dataQuality.warnings.join('；')}`);
  }
  if (data.score.freshnessBlocked) {
    lines.push(`信号阻断: 原始信号=${data.score.rawSignal}，因数据可信度不足强制降为观望`);
  }
  if (data.fundamental?.veto) {
    lines.push(`基本面否决: ${data.fundamental.redFlags.join('；')}`);
  } else if (data.fundamental?.redFlags?.length) {
    lines.push(`基本面红旗: ${data.fundamental.redFlags.join('；')}`);
  }
  if (data.fundamental?.warnings?.length) {
    lines.push(`基本面提醒: ${data.fundamental.warnings.join('；')}`);
  }
  const output = lines.join('\n');
  console.log(output);
  if (options.save !== false) {
    saveAnalysisOutput('stock', code, output);
  }
}

/**
 * 把量化回测结果转换为包含时效、请求和数据源的统一 JSON 契约。
 */
export function buildQuantJsonOutput({ result, codes, benchmarkCode, fetched = [], benchmark = null }) {
  const asOf = result.currentRegime?.asOf ?? result.period?.end ?? null;
  return buildSuccessContract('quant', {
    asOf,
    request: {
      codes,
      benchmark: benchmarkCode,
      config: result.config ?? {},
    },
    dataQuality: {
      status: asOf ? 'verified' : 'unknown',
      asOf,
      allowsDirectionalSignal: Boolean(asOf),
      provisional: false,
      warnings: asOf ? [] : ['量化结果缺少已完成 K 线日期'],
    },
    data: result,
    sources: {
      assets: Object.fromEntries(fetched.map((item) => [item.code, item.source ?? 'unknown'])),
      benchmark: benchmark?.source ?? 'unknown',
    },
    decisionBasis: quantDecisionBasis(result),
  });
}

/**
 * 把板块排行转换为原生结构化 JSON，保留排名、轮动和数据时间。
 */
export function buildSectorJsonOutput(sectorData, options = {}) {
  const asOf = sectorData.dataTime ?? null;
  const warnings = [
    ...(sectorData.warnings ?? []),
    ...(asOf ? [] : ['板块行情时间未核验']),
  ];
  const coverage = sectorData.historyCoverage;
  const historyVerified = coverage != null
    && coverage.requested > 0
    && coverage.succeeded === coverage.requested;
  return buildSuccessContract('sector', {
    asOf,
    request: {
      type: sectorData.type,
      limit: options.limit ?? 20,
    },
    dataQuality: {
      status: !asOf ? 'unknown' : (historyVerified ? 'verified' : 'limited'),
      asOf,
      allowsDirectionalSignal: Boolean(asOf) && historyVerified,
      provisional: false,
      warnings,
    },
    data: sectorData,
    sources: {
      quote: 'eastmoney',
      history: coverage?.succeeded > 0 ? 'eastmoney' : null,
    },
    decisionBasis: sectorDecisionBasis(sectorData),
  });
}

/**
 * 把持仓分析转换为结构化 JSON，并汇总每只持仓的数据质量。
 */
export function buildPortfolioJsonOutput({
  portfolio,
  market,
  sectorData,
  holdings,
  summary,
  allocation,
  overseas,
  sectorLimit,
}) {
  const qualities = holdings
    .map((holding) => holding.stockData?.dataQuality)
    .filter(Boolean);
  const qualityTimes = qualities.map((quality) => quality.asOf).filter(Boolean).sort();
  const asOf = qualityTimes.at(-1) ?? market.dataTime ?? sectorData.dataTime ?? null;
  const allowsDirectionalSignal = qualities.length > 0
    && qualities.every((quality) => quality.allowsDirectionalSignal === true);
  const warnings = [
    ...(portfolio.__meta?.warnings ?? []),
    ...(sectorData?.warnings ?? []),
    ...qualities.flatMap((quality) => quality.warnings ?? []),
  ];
  const positions = portfolio.positions.map((position) => ({
    code: position.code,
    name: position.name,
    assetType: position.assetType,
    avgCost: position.avgCost,
    shares: position.shares,
    buyDate: position.buyDate,
    targetWeight: position.targetWeight,
    sector: position.sector,
    riskRole: position.riskRole,
  }));
  return buildSuccessContract('portfolio', {
    asOf,
    request: {
      positionCount: positions.length,
      sectorLimit,
    },
    dataQuality: {
      status: allowsDirectionalSignal ? 'verified' : (asOf ? 'limited' : 'unknown'),
      asOf,
      allowsDirectionalSignal,
      provisional: qualities.some((quality) => quality.provisional === true),
      warnings: [...new Set(warnings)],
      holdings: qualities.map((quality, index) => ({
        code: positions[index]?.code ?? null,
        status: quality.status ?? 'unknown',
        asOf: quality.asOf ?? null,
        allowsDirectionalSignal: Boolean(quality.allowsDirectionalSignal),
      })),
    },
    data: {
      portfolio: {
        monthlyBudget: portfolio.monthlyBudget,
        cash: portfolio.cash,
        cashReserveRatio: portfolio.cashReserveRatio,
        positions,
      },
      market,
      sector: sectorData,
      overseas,
      holdings,
      summary,
      allocation,
    },
    sources: {
      market: 'eastmoney',
      sector: sectorData?.sectors?.length ? 'eastmoney' : null,
      holdings: Object.fromEntries(holdings.map((holding) => [
        holding.position.code,
        holding.stockData?.sources ?? {},
      ])),
      overseas: 'tencent',
    },
    decisionBasis: portfolioDecisionBasis({
      holdings,
      summary,
      allocation,
      allowsDirectionalSignal,
    }),
  });
}

function scoreLine(score) {
  const parts = [`${score.total}/100 ${signalLabel(score.signal)}`];
  if (score.fundamentalAdjustment !== 0) {
    const sign = score.fundamentalAdjustment > 0 ? '+' : '';
    parts.push(`(基本面${sign}${score.fundamentalAdjustment})`);
  }
  return parts.join(' ');
}
