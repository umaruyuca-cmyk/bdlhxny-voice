import { getAnalysisProfile } from './profiles.js';

export function scoreStock(technical, profileValue = 'standard', fundamental = null) {
  const profile = getAnalysisProfile(profileValue);
  const dimensions = {
    trend: scoreTrend(technical.alignment),
    deviation: scoreDeviation(technical.deviation.ma5),
    macd: scoreMacd(technical.macd),
    volume: scoreVolume(technical.volume.status),
    rsi: scoreRsi(technical.rsi.rsi6),
    support: scoreSupport(technical),
  };
  const rawTotal = Object.values(dimensions).reduce((sum, value) => sum + value, 0);
  const fundamentalAdjustment = fundamental?.adjustment ?? 0;
  const adjustedTotal = Math.max(0, rawTotal + fundamentalAdjustment);
  const signalOverridden = fundamental?.veto === true;
  const signal = signalOverridden ? 'wait' : signalFromScore(adjustedTotal, technical.alignment, profile);
  return {
    total: adjustedTotal,
    rawTotal,
    dimensions,
    signal,
    profile: profile.key,
    fundamentalAdjustment,
    signalOverridden,
  };
}

function scoreTrend(alignment) {
  return {
    strong_bullish: 30,
    bullish: 25,
    weak_bullish: 18,
    consolidation: 12,
    weak_bearish: 8,
    bearish: 4,
    strong_bearish: 0,
  }[alignment] ?? 10;
}

function scoreDeviation(biasMa5) {
  if (biasMa5 == null) return 10;
  if (biasMa5 >= -3 && biasMa5 <= 1) return 20;
  if (biasMa5 > 1 && biasMa5 <= 2) return 16;
  if (biasMa5 > 2 && biasMa5 <= 4) return 9;
  if (biasMa5 > 4 && biasMa5 <= 5) return 6;
  if (biasMa5 > 5) return 4;
  if (biasMa5 < -8) return 10;
  return 14;
}

function scoreMacd(macd) {
  return {
    golden_cross_above_zero: 15,
    golden_cross: 13,
    bullish: 11,
    neutral: 8,
    bearish: 4,
    death_cross: 0,
  }[macd.signal] ?? 8;
}

function scoreVolume(status) {
  return {
    shrink_pullback: 15,
    normal: 10,
    heavy_volume_up: 8,
    shrink_up: 6,
    unknown: 7,
    heavy_volume_down: 0,
  }[status] ?? 7;
}

function scoreRsi(rsi6) {
  if (rsi6 == null) return 5;
  if (rsi6 >= 35 && rsi6 <= 60) return 10;
  if (rsi6 >= 20 && rsi6 < 35) return 8;
  if (rsi6 > 60 && rsi6 <= 65) return 7;
  if (rsi6 > 65 && rsi6 <= 75) return 4;
  if (rsi6 > 75) return 0;
  return 6;
}

function scoreSupport(technical) {
  const distanceToMa20 = Math.abs(technical.deviation.ma20 ?? 99);
  const distanceToMa60 = Math.abs(technical.deviation.ma60 ?? 99);
  if (distanceToMa20 <= 2 && distanceToMa60 <= 8) return 10;
  if (distanceToMa20 <= 3) return 8;
  if (distanceToMa60 <= 4) return 7;
  if ((technical.deviation.ma20 ?? 0) > 8) return 2;
  return 5;
}

export function signalFromScore(score, alignment, profileValue = 'standard') {
  const profile = typeof profileValue === 'string' ? getAnalysisProfile(profileValue) : profileValue;
  const thresholds = profile.signalThresholds;
  if (score >= thresholds.strongBuy && ['strong_bullish', 'bullish'].includes(alignment)) return 'strong_buy';
  if (score >= thresholds.buy && ['strong_bullish', 'bullish', 'weak_bullish'].includes(alignment)) return 'buy';
  if (score >= thresholds.hold) return 'hold';
  if (score >= thresholds.wait) return 'wait';
  if (['bearish', 'strong_bearish'].includes(alignment)) return 'strong_sell';
  return 'sell';
}
