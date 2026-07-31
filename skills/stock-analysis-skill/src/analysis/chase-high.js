import { round } from './technical.js';

export function evaluateChaseHigh({ quote, history, technical }) {
  const price = quote?.price ?? technical.close;
  const latest = history.at(-1) ?? {};
  const high20 = technical.support.high20;
  const hard = [];
  const soft = [];

  if (technical.rsi.rsi6 > 75) {
    hard.push(`RSI6=${technical.rsi.rsi6} > 75，短线过热`);
  }
  if (technical.deviation.ma5 > 4) {
    hard.push(`偏离 MA5 ${technical.deviation.ma5}% > 4%`);
  }
  if (technical.deviation.ma20 > 8) {
    hard.push(`偏离 MA20 ${technical.deviation.ma20}% > 8%`);
  }
  if (high20 && price >= high20 * 0.999 && technical.volume.volumeRatio != null && technical.volume.volumeRatio < 0.8) {
    hard.push(`接近 20 日新高且量比 ${technical.volume.volumeRatio} < 0.8，量价背离`);
  }
  if ((latest.pctChg ?? quote?.changePct ?? 0) > 5 && technical.volume.volumeRatio > 2.5) {
    hard.push(`单日涨幅 ${round(latest.pctChg ?? quote.changePct)}% 且量比 ${technical.volume.volumeRatio} > 2.5，放量冲高`);
  }
  if (technical.deviation.ma60 > 30) {
    hard.push(`偏离 MA60 ${technical.deviation.ma60}% > 30%，严重偏离长期均线`);
  }

  if (technical.rsi.rsi6 >= 65 && technical.rsi.rsi6 <= 75) {
    soft.push(`RSI6=${technical.rsi.rsi6} 位于 65-75`);
  }
  if (technical.deviation.ma5 >= 2 && technical.deviation.ma5 <= 4) {
    soft.push(`偏离 MA5 ${technical.deviation.ma5}% 位于 +2% 到 +4%`);
  }
  if (high20 && price >= high20 * 0.98 && price < high20) {
    soft.push(`距离 20 日高点 ${round((high20 - price) / high20 * 100)}%，已在高位附近`);
  }

  const level = hard.length ? 'hard' : soft.length ? 'soft' : 'safe';
  const label = level === 'hard' ? '追高警告' : level === 'soft' ? '追高关注' : '安全';

  return {
    level,
    label,
    hard,
    soft,
    reasons: hard.length ? hard : soft,
    canBuy: hard.length === 0,
  };
}
