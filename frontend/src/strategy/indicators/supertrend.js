import { atr } from './atr';

/**
 * SuperTrend Indicator
 * Matches MT4 SuperTrend logic: midPrice ± multiplier * ATR
 *
 * @param {{ high: number, low: number, close: number }[]} candles
 * @param {number} [atrPeriod=10]
 * @param {number} [multiplier=3.0]
 * @returns {{ supertrend: number[], direction: number[] }}
 *          direction: 1 = bullish (price above), -1 = bearish (price below)
 */
export function supertrend(candles, atrPeriod = 10, multiplier = 3.0) {
    const atrArr = atr(candles, atrPeriod);
    const len = candles.length;
    const st = Array(len).fill(NaN);
    const dir = Array(len).fill(0);

    let prevUpper = NaN, prevLower = NaN, prevDir = 1;

    for (let i = 0; i < len; i++) {
        if (isNaN(atrArr[i])) continue;

        const mid = (candles[i].high + candles[i].low) / 2;
        let upperBand = mid + multiplier * atrArr[i];
        let lowerBand = mid - multiplier * atrArr[i];

        // Tighten bands
        if (!isNaN(prevUpper)) upperBand = Math.min(upperBand, prevUpper);
        if (!isNaN(prevLower)) lowerBand = Math.max(lowerBand, prevLower);

        const close = candles[i].close;
        let direction;
        if (prevDir === 1) {
            direction = close < lowerBand ? -1 : 1;
        } else {
            direction = close > upperBand ? 1 : -1;
        }

        st[i] = direction === 1 ? lowerBand : upperBand;
        dir[i] = direction;
        prevUpper = upperBand;
        prevLower = lowerBand;
        prevDir = direction;
    }

    return { supertrend: st, direction: dir };
}
