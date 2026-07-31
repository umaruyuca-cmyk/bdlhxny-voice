import chalk from 'chalk';
import Table from 'cli-table3';
import { chinaDateString } from '../utils/china-time.js';

export const signalLabels = {
  strong_buy: '强烈买入',
  buy: '买入',
  hold: '持有',
  wait: '观望',
  sell: '卖出',
  strong_sell: '强烈卖出',
};

export const alignmentLabels = {
  strong_bullish: '强势多头',
  bullish: '多头排列',
  weak_bullish: '弱多排列',
  consolidation: '震荡',
  weak_bearish: '弱空排列',
  bearish: '空头排列',
  strong_bearish: '强势空头',
};

export function money(value, digits = 2) {
  if (value == null || value === '') return 'N/A';
  if (!Number.isFinite(Number(value))) return 'N/A';
  return `¥${Number(value).toFixed(digits)}`;
}

export function amountYi(value) {
  if (value == null || value === '') return 'N/A';
  if (!Number.isFinite(Number(value))) return 'N/A';
  return `${Number(value).toFixed(2)}亿`;
}

export function pct(value, digits = 2) {
  if (value == null || value === '') return 'N/A';
  if (!Number.isFinite(Number(value))) return 'N/A';
  const sign = Number(value) > 0 ? '+' : '';
  return `${sign}${Number(value).toFixed(digits)}%`;
}

export function plainNumber(value, digits = 2) {
  if (value == null || value === '') return 'N/A';
  if (!Number.isFinite(Number(value))) return 'N/A';
  return Number(value).toFixed(digits);
}

export function colorPct(value) {
  if (!Number.isFinite(Number(value))) return chalk.gray('N/A');
  const formatted = pct(value);
  if (value > 0) return chalk.red(formatted);
  if (value < 0) return chalk.green(formatted);
  return chalk.gray(formatted);
}

export function chaseLabel(chase) {
  if (chase.level === 'hard') return chalk.red('追高警告');
  if (chase.level === 'soft') return chalk.yellow('追高关注');
  return chalk.green('安全');
}

export function signalLabel(signal) {
  const label = signalLabels[signal] ?? signal;
  if (['strong_buy', 'buy'].includes(signal)) return chalk.red(label);
  if (signal === 'hold') return chalk.yellow(label);
  if (signal === 'wait') return chalk.gray(label);
  return chalk.green(label);
}

export function makeTable(head, rows, options = {}) {
  const table = new Table({
    head: head.map((item) => chalk.cyan(item)),
    wordWrap: true,
    colWidths: options.colWidths,
    style: {
      head: [],
      border: ['gray'],
    },
  });
  rows.forEach((row) => table.push(row));
  return table.toString();
}

export function todayString() {
  return chinaDateString();
}
