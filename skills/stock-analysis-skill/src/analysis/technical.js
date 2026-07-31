export function safeNumber(value, fallback = null) {
  if (value == null || value === '' || value === '-' || value === '--') return fallback;
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

export function round(value, digits = 2) {
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  return Number(number.toFixed(digits));
}

export function movingAverage(values, period) {
  return values.map((_, index) => {
    if (index + 1 < period) return null;
    const window = values.slice(index + 1 - period, index + 1).filter(Number.isFinite);
    if (window.length < period) return null;
    return round(window.reduce((sum, value) => sum + value, 0) / period, 3);
  });
}

export function ema(values, period) {
  const multiplier = 2 / (period + 1);
  const result = [];
  let previous = null;

  values.forEach((value, index) => {
    if (!Number.isFinite(value)) {
      result.push(previous);
      return;
    }
    if (index + 1 < period) {
      result.push(null);
      return;
    }
    if (previous == null) {
      const seed = values.slice(index + 1 - period, index + 1);
      previous = seed.reduce((sum, item) => sum + item, 0) / period;
    } else {
      previous = (value - previous) * multiplier + previous;
    }
    result.push(round(previous, 4));
  });

  return result;
}

export function macd(values, fast = 12, slow = 26, signal = 9) {
  const emaFast = ema(values, fast);
  const emaSlow = ema(values, slow);
  const dif = values.map((_, index) => (
    emaFast[index] == null || emaSlow[index] == null ? null : round(emaFast[index] - emaSlow[index], 4)
  ));
  const dea = ema(dif.map((value) => (value == null ? 0 : value)), signal);
  const hist = dif.map((value, index) => (
    value == null || dea[index] == null ? null : round((value - dea[index]) * 2, 4)
  ));
  return { dif, dea, hist };
}

export function rsi(values, period = 6) {
  const result = Array(values.length).fill(null);
  let avgGain = 0;
  let avgLoss = 0;

  for (let index = 1; index < values.length; index += 1) {
    const change = values[index] - values[index - 1];
    const gain = Math.max(change, 0);
    const loss = Math.max(-change, 0);

    if (index <= period) {
      avgGain += gain;
      avgLoss += loss;
      if (index === period) {
        avgGain /= period;
        avgLoss /= period;
        result[index] = avgLoss === 0 ? 100 : round(100 - 100 / (1 + avgGain / avgLoss), 2);
      }
    } else {
      avgGain = (avgGain * (period - 1) + gain) / period;
      avgLoss = (avgLoss * (period - 1) + loss) / period;
      result[index] = avgLoss === 0 ? 100 : round(100 - 100 / (1 + avgGain / avgLoss), 2);
    }
  }

  return result;
}

export function lastDefined(values) {
  for (let index = values.length - 1; index >= 0; index -= 1) {
    if (values[index] != null && Number.isFinite(values[index])) return values[index];
  }
  return null;
}

export function pctDistance(price, base) {
  if (!Number.isFinite(price) || !Number.isFinite(base) || base === 0) return null;
  return round((price - base) / base * 100, 2);
}

export function tradingMinutesElapsed(now = new Date()) {
  if (!getChinaTradingDayStatus(now).isTradingDay) return 240;
  const parts = getChinaDateTimeParts(now);
  const mins = parts.hour * 60 + parts.minute;
  if (mins <= 570) return 0;
  if (mins <= 690) return mins - 570;
  if (mins <= 780) return 120;
  if (mins <= 900) return 120 + (mins - 780);
  return 240;
}

function isSameDay(dateValue, now) {
  if (dateValue == null) return false;
  const normalized = dateValue instanceof Date ? chinaDateString(dateValue) : String(dateValue).slice(0, 10);
  return normalized === chinaDateString(now);
}

export function calculateTechnicalIndicators(history, options = {}) {
  const rows = history.filter((row) => Number.isFinite(row.close));
  const closes = rows.map((row) => row.close);
  const volumes = rows.map((row) => row.volume ?? 0);
  const latest = rows.at(-1) ?? {};

  const ma5Series = movingAverage(closes, 5);
  const ma10Series = movingAverage(closes, 10);
  const ma20Series = movingAverage(closes, 20);
  const ma60Series = movingAverage(closes, 60);
  const macdSeries = macd(closes);
  const rsi6Series = rsi(closes, 6);
  const rsi12Series = rsi(closes, 12);
  const rsi24Series = rsi(closes, 24);

  const ma = {
    ma5: lastDefined(ma5Series),
    ma10: lastDefined(ma10Series),
    ma20: lastDefined(ma20Series),
    ma60: lastDefined(ma60Series),
  };

  const previousVolumes = volumes.slice(-6, -1).filter((value) => Number.isFinite(value) && value > 0);
  const avgVolume5 = previousVolumes.length ? previousVolumes.reduce((sum, value) => sum + value, 0) / previousVolumes.length : null;
  const now = options.now ?? new Date();
  const elapsed = tradingMinutesElapsed(now);
  const latestIsToday = isSameDay(latest.date, now);
  const intradayScaling = latestIsToday && elapsed > 0 && elapsed < 240;
  const latestVolume = latest.volume ?? 0;
  let volumeRatio = null;
  if (avgVolume5) {
    volumeRatio = intradayScaling
      ? round(latestVolume * 240 / (avgVolume5 * elapsed), 2)
      : round(latestVolume / avgVolume5, 2);
  }
  const high20 = Math.max(...rows.slice(-20).map((row) => row.high ?? row.close).filter(Number.isFinite));
  const low20 = Math.min(...rows.slice(-20).map((row) => row.low ?? row.close).filter(Number.isFinite));

  const alignment = classifyMaAlignment(ma);
  const trend = classifyTrend(alignment, macdSeries, latest);
  const volumeStatus = classifyVolumeStatus(latest, volumeRatio);

  return {
    date: latest.date,
    close: latest.close,
    changePct: latest.pctChg ?? latest.changePct ?? null,
    ma,
    macd: {
      dif: lastDefined(macdSeries.dif),
      dea: lastDefined(macdSeries.dea),
      hist: lastDefined(macdSeries.hist),
      signal: classifyMacd(macdSeries),
    },
    rsi: {
      rsi6: lastDefined(rsi6Series),
      rsi12: lastDefined(rsi12Series),
      rsi24: lastDefined(rsi24Series),
      zone: classifyRsi(lastDefined(rsi6Series)),
    },
    deviation: {
      ma5: pctDistance(latest.close, ma.ma5),
      ma10: pctDistance(latest.close, ma.ma10),
      ma20: pctDistance(latest.close, ma.ma20),
      ma60: pctDistance(latest.close, ma.ma60),
    },
    volume: {
      volumeRatio,
      avgVolume5: avgVolume5 ? round(avgVolume5, 0) : null,
      status: volumeStatus,
      intradayScaled: intradayScaling,
    },
    support: {
      ma20: ma.ma20,
      ma60: ma.ma60,
      low20: Number.isFinite(low20) ? round(low20, 3) : null,
      high20: Number.isFinite(high20) ? round(high20, 3) : null,
    },
    trend,
    alignment,
    series: {
      ma5: ma5Series,
      ma10: ma10Series,
      ma20: ma20Series,
      ma60: ma60Series,
    },
  };
}

export function classifyMaAlignment(ma) {
  const { ma5, ma10, ma20, ma60 } = ma;
  if ([ma5, ma10, ma20, ma60].every(Number.isFinite) && ma5 > ma10 && ma10 > ma20 && ma20 > ma60) {
    return 'strong_bullish';
  }
  if ([ma5, ma10, ma20].every(Number.isFinite) && ma5 > ma10 && ma10 > ma20) return 'bullish';
  if ([ma5, ma10].every(Number.isFinite) && ma5 > ma10) return 'weak_bullish';
  if ([ma5, ma10, ma20, ma60].every(Number.isFinite) && ma5 < ma10 && ma10 < ma20 && ma20 < ma60) {
    return 'strong_bearish';
  }
  if ([ma5, ma10, ma20].every(Number.isFinite) && ma5 < ma10 && ma10 < ma20) return 'bearish';
  if ([ma5, ma10].every(Number.isFinite) && ma5 < ma10) return 'weak_bearish';
  return 'consolidation';
}

export function classifyTrend(alignment, macdSeries) {
  const hist = lastDefined(macdSeries.hist);
  if (['strong_bullish', 'bullish'].includes(alignment) && hist >= 0) return 'uptrend';
  if (['strong_bearish', 'bearish'].includes(alignment) && hist <= 0) return 'downtrend';
  return 'sideways';
}

export function classifyMacd(macdSeries) {
  const dif = lastDefined(macdSeries.dif);
  const dea = lastDefined(macdSeries.dea);
  const hist = lastDefined(macdSeries.hist);
  const previousHist = macdSeries.hist.slice(0, -1).reverse().find((value) => value != null);
  if (dif == null || dea == null || hist == null) return 'neutral';
  if (previousHist != null && previousHist <= 0 && hist > 0 && dif > 0) return 'golden_cross_above_zero';
  if (previousHist != null && previousHist <= 0 && hist > 0) return 'golden_cross';
  if (previousHist != null && previousHist >= 0 && hist < 0) return 'death_cross';
  if (dif > dea && dif > 0) return 'bullish';
  if (dif < dea && dif < 0) return 'bearish';
  return 'neutral';
}

export function classifyRsi(rsi6) {
  if (rsi6 == null) return 'unknown';
  if (rsi6 > 80) return 'overbought';
  if (rsi6 >= 60) return 'strong';
  if (rsi6 >= 40) return 'neutral';
  if (rsi6 >= 20) return 'weak';
  return 'oversold';
}

export function classifyVolumeStatus(latest, volumeRatio) {
  if (volumeRatio == null) return 'unknown';
  const pct = latest.pctChg ?? latest.changePct ?? 0;
  if (volumeRatio >= 1.5 && pct > 0) return 'heavy_volume_up';
  if (volumeRatio >= 1.5 && pct < 0) return 'heavy_volume_down';
  if (volumeRatio <= 0.8 && pct < 0) return 'shrink_pullback';
  if (volumeRatio <= 0.8 && pct > 0) return 'shrink_up';
  return 'normal';
}
import { chinaDateString, getChinaDateTimeParts, getChinaTradingDayStatus } from '../utils/china-time.js';
