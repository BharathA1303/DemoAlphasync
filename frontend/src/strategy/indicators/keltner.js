/**
 * Keltner Channels
 * @param {Object[]} candles - Array of candle objects with { high, low, close }
 * @param {number} period - Number of periods (default 20)
 * @param {number} mult - ATR multiplier (default 1.5)
 * @returns {{ upper: number[], middle: number[], lower: number[] }}
 */
import { ema } from './ema';
import { atr } from './atr';

export function keltnerChannels(candles, period = 20, mult = 1.5) {
    const closes = candles.map(c => c.close);
    const mid = ema(closes, period);
    const atrVals = atr(candles, period);
    const upper = mid.map((m, i) => isNaN(m) || isNaN(atrVals[i]) ? NaN : m + mult * atrVals[i]);
    const lower = mid.map((m, i) => isNaN(m) || isNaN(atrVals[i]) ? NaN : m - mult * atrVals[i]);
    return { upper, middle: mid, lower };
}
