/**
 * Donchian Channels
 * @param {Object[]} candles - Array of candle objects with { high, low }
 * @param {number} period - Number of periods (default 20)
 * @returns {{ upper: number[], middle: number[], lower: number[] }}
 */
export function donchianChannels(candles, period = 20) {
    const len = candles.length;
    const upper = new Array(len).fill(NaN);
    const lower = new Array(len).fill(NaN);
    const middle = new Array(len).fill(NaN);
    for (let i = period - 1; i < len; i++) {
        let hi = -Infinity, lo = Infinity;
        for (let j = i - period + 1; j <= i; j++) {
            if (candles[j].high > hi) hi = candles[j].high;
            if (candles[j].low < lo) lo = candles[j].low;
        }
        upper[i] = hi;
        lower[i] = lo;
        middle[i] = (hi + lo) / 2;
    }
    return { upper, middle, lower };
}
