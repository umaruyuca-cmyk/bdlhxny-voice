import {
  chinaDateString,
  chinaDateTimeString,
  countChinaTradingDaysBetween,
  getChinaTradingDayStatus,
} from '../utils/china-time.js';
import { getChinaTradeSession } from './trading.js';

export function assessDataFreshness({
  assetKind,
  assetType,
  quote = {},
  history = [],
  historyWasSynthesized = false,
  now = new Date(),
}) {
  const asOf = chinaDateTimeString(now);
  const today = chinaDateString(now);
  const latestBarDate = history.at(-1)?.date ?? null;

  if (assetKind === 'open_fund') {
    const navLagTradingDays = latestBarDate ? countChinaTradingDaysBetween(latestBarDate, today) : null;
    const qdii = String(assetType ?? '').toLowerCase() === 'qdii';
    const allowedLag = qdii ? 3 : 1;
    const stale = navLagTradingDays == null || navLagTradingDays > allowedLag;
    return {
      kind: qdii ? 'nav_qdii' : 'nav',
      status: stale ? 'stale' : navLagTradingDays === 0 ? 'nav_latest' : `nav_t${navLagTradingDays}`,
      label: stale
        ? '净值过期'
        : navLagTradingDays === 0
          ? '最新已公布净值（非实时）'
          : `净值滞后 ${navLagTradingDays} 个交易日（非实时）`,
      asOf,
      quoteTime: null,
      tradeDate: latestBarDate,
      latestBarDate,
      ageSeconds: null,
      navLagTradingDays,
      historyWasSynthesized: false,
      provisional: false,
      allowsDirectionalSignal: !stale,
      warnings: [
        '场外基金/QDII按已公布净值分析，不属于盘中实时价格',
        ...(stale ? ['最新净值超过允许延迟，方向性信号已阻断'] : []),
      ],
    };
  }

  const session = getChinaTradeSession(now);
  const quoteTime = toValidDate(quote.quoteTime);
  const tradeDate = quote.tradeDate ?? (quoteTime ? chinaDateString(quoteTime) : null);
  const ageSeconds = quoteTime ? Math.max(0, Math.round((now.getTime() - quoteTime.getTime()) / 1000)) : null;
  const quoteIsToday = tradeDate === today;
  const currentBarPresent = latestBarDate === today;
  const warnings = [];
  let status;
  let label;
  let allowsDirectionalSignal = true;

  if (session.tradable) {
    if (!quoteTime || !quoteIsToday) {
      status = 'unknown';
      label = '盘中行情时间未核验';
      allowsDirectionalSignal = false;
      warnings.push('当前处于交易时段，但行情缺少可验证的当日时间戳');
    } else if (ageSeconds <= 120) {
      status = 'live';
      label = `盘中行情，延迟约 ${ageSeconds} 秒`;
    } else if (ageSeconds <= 900) {
      status = 'delayed';
      label = `盘中行情延迟约 ${ageSeconds} 秒`;
      allowsDirectionalSignal = false;
      warnings.push('盘中行情延迟超过 120 秒，方向性信号已阻断');
    } else {
      status = 'stale';
      label = '盘中行情已过期';
      allowsDirectionalSignal = false;
      warnings.push('行情时间戳明显过期，方向性信号已阻断');
    }
    if (!currentBarPresent) {
      allowsDirectionalSignal = false;
      warnings.push('最新K线不是北京时间当天，技术指标与现价不同步');
    }
  } else if (quoteIsToday) {
    status = session.key === 'after_close' ? 'closed_current_day' : 'current_non_trading';
    label = session.key === 'after_close' ? '当日收盘/盘后数据' : '当日非连续交易时段数据';
  } else if (!tradeDate) {
    status = 'unknown';
    label = '行情时间未核验';
    allowsDirectionalSignal = false;
    warnings.push('行情缺少时间戳，方向性信号已阻断');
  } else {
    status = 'previous_close';
    label = `最近行情日 ${tradeDate}`;
  }

  if (historyWasSynthesized) warnings.push('当日K线由实时行情临时合成，MA/RSI/MACD均为盘中临时值');
  if (!session.calendarVerified) warnings.push('当前年份交易所休市日历未覆盖，交易状态未完全核验');

  return {
    kind: 'exchange_quote',
    status,
    label,
    asOf,
    quoteTime: quoteTime ? chinaDateTimeString(quoteTime) : null,
    tradeDate,
    latestBarDate,
    ageSeconds,
    navLagTradingDays: null,
    historyWasSynthesized,
    provisional: session.tradable && currentBarPresent,
    allowsDirectionalSignal,
    session,
    warnings,
  };
}

export function applyFreshnessGuard(score, freshness) {
  if (freshness?.allowsDirectionalSignal !== false) return score;
  return {
    ...score,
    rawSignal: score.signal,
    signal: 'wait',
    freshnessBlocked: true,
  };
}

function toValidDate(value) {
  if (!value) return null;
  const parsed = value instanceof Date ? value : new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}
