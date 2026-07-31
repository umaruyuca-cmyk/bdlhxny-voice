import chalk from 'chalk';
import {
  alignmentLabels,
  amountYi,
  chaseLabel,
  colorPct,
  makeTable,
  money,
  pct,
  plainNumber,
  signalLabel,
  todayString,
} from './formatter.js';

export function renderSectorHeatmap(sectorData) {
  const title = sectorData.type === 'concept' ? 'A股概念板块热力排行' : 'A股行业板块热力排行';
  const rows = sectorData.sectors.map((sector, index) => [
    index + 1,
    sector.name,
    colorPct(sector.changePct),
    colorPct(sector.change5d),
    colorPct(sector.change20d),
    amountYi(sector.mainNetInflow),
    plainNumber(sector.volumeRatio ?? sector.turnoverRate),
    sector.rotation,
  ]);

  return [
    chalk.bold(`\n${title} — ${todayString()}`),
    makeTable(['#', '板块', '日涨跌', '5日', '20日', '主力净流入', '换手/量能', '轮动信号'], rows, {
      colWidths: [5, 18, 11, 11, 11, 13, 11, 24],
    }),
    renderRotationSummary(sectorData),
  ].join('\n');
}

export function renderRotationSummary(sectorData) {
  const leaders = sectorData.leaders.map((item) => `${item.name}(${pct(item.changePct)})`).join('、') || 'N/A';
  const laggards = sectorData.laggards.map((item) => `${item.name}(${pct(item.changePct)})`).join('、') || 'N/A';
  const strong5d = sectorData.rotation.strong5d.map((item) => item.name).join('、') || 'N/A';
  const weak5d = sectorData.rotation.weak5d.map((item) => item.name).join('、') || 'N/A';
  const divergence = sectorData.rotation.fundDivergence
    .map((item) => `${item.name}(资金${amountYi(item.mainNetInflow)}但价格${pct(item.changePct)})`)
    .join('、') || 'N/A';

  return [
    '【板块轮动提示】',
    `- 领涨板块: ${leaders}`,
    `- 领跌板块: ${laggards}`,
    `- 持续走强(5日): ${strong5d}`,
    `- 持续走弱(5日): ${weak5d}`,
    `- 资金异动: ${divergence}`,
  ].join('\n');
}

export function renderDecisionBoard({ portfolio, market, sectorData, holdings, summary, allocation, overseas }) {
  const lines = [];
  lines.push('═══════════════════════════════════════════');
  lines.push(`  持仓决策看板 — ${todayString()}`);
  lines.push(`  分析标准 — ${allocation.profile.label}: ${allocation.profile.description}`);
  lines.push('═══════════════════════════════════════════');
  lines.push('');
  lines.push(renderOverseasContext(overseas));
  lines.push(renderMarketOverview(market, sectorData));
  lines.push('');
  lines.push(renderRotationSummary(sectorData));
  lines.push('');
  lines.push(renderPortfolioSummary(summary, portfolio));
  lines.push('');
  lines.push('【持仓诊断】');
  holdings.forEach((holding) => {
    lines.push(renderHoldingCard(holding));
  });
  lines.push('');
  lines.push(renderAllocationPlan(allocation));
  lines.push('═══════════════════════════════════════════');
  lines.push('⚠ 风险提示: 以上为AI辅助分析，不构成投资建议。A股波动和数据源延迟都可能影响结果，请独立决策。');
  return lines.join('\n');
}

function renderOverseasContext(overseas) {
  if (!overseas || !Array.isArray(overseas.indices)) {
    return '【隔夜外围】\n- 海外数据暂不可用\n';
  }

  const all = overseas.indices;
  const usMajor = all.filter((i) => ['usIXIC', 'usDJI', 'usSPX'].includes(i.code));
  const others = all.filter((i) => !['usIXIC', 'usDJI', 'usSPX'].includes(i.code));

  const line1 = usMajor.length
    ? usMajor.map((i) => {
        if (i.error) return `${i.name}: N/A`;
        return `${i.name}: ${plainNumber(i.price)} (${pct(i.changePct)})`;
      }).join(' | ')
    : '美股指数数据暂不可用';

  const line2 = others.length
    ? others.map((i) => {
        if (i.error) return `${i.name}: N/A`;
        return `${i.name}: ${plainNumber(i.price)} (${pct(i.changePct)})`;
      }).join(' | ')
    : null;

  const biasLabel = {
    '顺风': '顺风',
    '中性': '中性',
    '逆风': '逆风',
    '未知': '未知',
  }[overseas.context?.bias] ?? '未知';
  const summary = overseas.context?.summary ?? '';

  const lines = ['【隔夜外围】', `- ${line1}`];
  if (line2) lines.push(`- ${line2}`);
  lines.push(`- 隔夜情绪: ${biasLabel} — ${summary}`);
  return lines.join('\n');
}

function renderMarketOverview(market, sectorData) {
  const indexLine = (market.indexes ?? [])
    .slice(0, 2)
    .map((item) => `${item.name}: ${plainNumber(item.price)} (${pct(item.changePct)})`)
    .join('  |  ') || '指数数据暂不可用';
  const leaders = sectorData.leaders.slice(0, 2).map((item) => `${item.name} (${pct(item.changePct)})`).join('、') || 'N/A';
  const laggards = sectorData.laggards.slice(0, 2).map((item) => `${item.name} (${pct(item.changePct)})`).join('、') || 'N/A';
  const north = market.northbound?.northbound?.total == null ? 'N/A' : amountYi(market.northbound.northbound.total);
  return [
    '【市场概况】',
    `- 数据时间: 指数 ${market.dataTime ?? '未核验'} | 板块 ${sectorData.dataTime ?? '未核验'}`,
    `- ${indexLine}`,
    `- 领涨板块: ${leaders}`,
    `- 领跌板块: ${laggards}`,
    `- 北向资金: ${north}`,
  ].join('\n');
}

function renderPortfolioSummary(summary, portfolio) {
  const warnings = summary.concentrationWarnings.length
    ? summary.concentrationWarnings.map((item) => `${item.sector} ${pct(item.weight)}`).join('、')
    : '无超过 35% 的单板块集中风险';
  const fallbackNotice = portfolio.__meta.usedFallback ? '\n- 当前未找到 portfolio.json，已使用 templates/portfolio.example.json 示例配置' : '';
  return [
    '【组合概况】',
    `- 分析标准: ${allocationProfileLabel(portfolio.analysisProfile)}`,
    `- 总市值: ${money(summary.totalValue)} | 持仓市值: ${money(summary.stockValue)} | 现金: ${money(summary.cash)} (${pct(summary.cashRatio)})`,
    `- 总盈亏: ${money(summary.pnlAmount)} (${pct(summary.pnlPct)})`,
    `- 板块集中度: ${warnings}${fallbackNotice}`,
  ].join('\n');
}

function renderHoldingCard(holding) {
  const data = holding.stockData;
  const technical = data.technical;
  const tradingMessages = holding.trading?.messages?.length ? holding.trading.messages.join('；') : '无';
  const tradingActions = holding.trading?.actions?.length ? `；${holding.trading.actions.join('；')}` : '';
  const netPnl = holding.trading?.roundTrip
    ? `净盈亏 ${money(holding.trading.roundTrip.netPnl)} (${pct(holding.trading.roundTrip.netPnlPct)}) | 往返费用 ${money(holding.trading.roundTrip.totalFees)} (${pct(holding.trading.roundTrip.feePctOfMarketValue)}) | 保本卖价 ${money(holding.trading.roundTrip.breakEvenPrice, 3)}`
    : 'N/A';
  const sizing = holding.trading?.sizing;
  const sizingText = sizing
    ? `市值 ${money(sizing.marketValue)} | ${sizing.positionLots}手 | ${sizing.canSplit ? `可分批，每笔尽量>=${money(sizing.splitTradeMinAmount)}` : '不建议分批，优先整笔'} | 主动卖出盈利至少覆盖 ${money(sizing.minProfitToTrade)}`
    : 'N/A';
  const next = holding.ladder.next;
  const addPlan = holding.risk?.addBlocked
    ? `风控已阻断加仓：${holding.risk.messages.join('；') || '仓位或数据条件不允许'}`
    : holding.ladder.downtrend
    ? '确认下跌趋势(MA5<MA10<MA20)，禁止补仓'
    : next
      ? `下一补仓位 ${money(next.triggerPrice)} (${next.label}) → 建议加仓 ${money(next.amount)}，止损 ${money(next.stopLoss)}`
      : '暂无有效补仓位，观望';
  const weightHint = holding.risk?.addBlocked || holding.ladder.downtrend
    ? '当前禁止新增'
    : holding.weightGap > 0.02
      ? '略低，可等回踩加仓'
      : holding.weightGap < -0.02
        ? '偏高，暂停新增'
        : '接近目标';
  const reasons = data.chase.reasons.length ? ` | ${data.chase.reasons.join('；')}` : '';
  const riskMessages = holding.risk?.messages?.length ? ` | ${holding.risk.messages.join('；')}` : '';
  const riskActions = holding.risk?.actions?.length ? ` | 建议: ${holding.risk.actions.join('；')}` : '';
  const quality = data.dataQuality;
  const qualityWarnings = quality?.warnings?.length ? ` | ${quality.warnings.join('；')}` : '';

  return [
    `${holding.position.code} ${holding.position.name} | 成本 ${money(holding.position.avgCost)} | 现价 ${money(holding.price)} | 盈亏 ${pct(holding.pnlPct)}`,
    `  评分: ${data.score.total}/100 (${signalLabel(data.score.signal)}) | RSI6: ${plainNumber(technical.rsi.rsi6)} | 乖离MA5: ${pct(technical.deviation.ma5)} | 均线: ${alignmentLabels[technical.alignment]}`,
    `  基本面: ${renderFundamentalLine(data.fundamental)}`,
    `  追高状态: ${chaseLabel(data.chase)}${reasons}`,
    `  数据可信度: ${quality?.label ?? '未评估'} | 北京时间 ${quality?.asOf ?? 'N/A'} | 行情 ${quality?.quoteTime ?? quality?.tradeDate ?? '未核验'} | K线/净值 ${quality?.latestBarDate ?? 'N/A'}${quality?.provisional ? '（临时）' : ''}${qualityWarnings}`,
    `  风控定位: ${holding.risk?.profile?.label ?? '未分类'} | 风险评级: ${holding.risk?.rating ?? 'N/A'}${riskMessages}${riskActions}`,
    `  交易约束: ${holding.trading?.session?.label ?? 'N/A'} | T+1: ${holding.trading?.tPlusOneBlocked ? '今日不可卖' : '可按规则卖'} | ${tradingMessages}${tradingActions}`,
    `  交易金额: ${sizingText}`,
    `  费用影响: ${netPnl}`,
    `  补仓计划: ${addPlan}`,
    `  仓位占比: ${pct(holding.currentWeight * 100)} / 目标 ${pct(holding.targetWeight * 100)} → ${weightHint}`,
    `  数据源: 行情=${data.sources.quote}, K线/净值=${data.sources.history}`,
  ].join('\n');
}

function renderAllocationPlan(allocation) {
  const rows = allocation.plan.map((item) => [
    `${item.code} ${item.name}`,
    signalLabel(item.holding.stockData.score.signal),
    item.score,
    item.action,
    money(item.amount),
    item.reason,
  ]);
  rows.push(['保留现金/等待', '-', '-', '等待更好时机', money(allocation.leftover), '未分配预算不强行出手']);

  return [
    '【月度资金部署】',
    `分析标准: ${allocation.profile.label} | 现金缓冲下限: ${pct(allocation.profile.cashReserveFloor * 100)}`,
    `本月预算: ${money(allocation.monthlyBudget)} | 预留现金: ${money(allocation.reserve)} (${pct(allocation.reserveRatio * 100)}) | 可部署: ${money(allocation.deployable)}`,
    makeTable(['标的', '信号', '评分', '动作', '金额', '原因'], rows, {
      colWidths: [18, 12, 8, 14, 12, 34],
    }),
  ].join('\n');
}

function allocationProfileLabel() {
  return '客观标准';
}

function renderFundamentalLine(fundamental) {
  if (!fundamental) return 'N/A';
  const ind = fundamental.indicators;
  const parts = [
    `PE=${ind.pe != null ? plainNumber(ind.pe, 2) : 'N/A'}`,
    `PB=${ind.pb != null ? plainNumber(ind.pb, 2) : 'N/A'}`,
    `市值=${ind.marketCap != null ? plainNumber(ind.marketCap / 1e8, 2) + '亿' : 'N/A'}`,
    fundamental.adjustment !== 0 ? `调整${fundamental.adjustment > 0 ? '+' : ''}${fundamental.adjustment}` : null,
    ...fundamental.redFlags.map((f) => `\u26A0${f}`),
  ].filter(Boolean);
  return parts.join(' | ');
}
