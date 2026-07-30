/**
 * Average True Range (ATR)
 * @param {{ high: number, low: number, close: number }[]} candles
 * @param {number} [period=14]
 * @returns {number[]}
 */
export function atr(candles, period = 14) {
    const result = [];
    if (candles.length < 2) return candles.map(() => NaN);

    const trueRanges = [candles[0].high - candles[0].low];
    for (let i = 1; i < candles.length; i++) {
        const h = candles[i].high;
        const l = candles[i].low;
        const pc = candles[i - 1].close;
        trueRanges.push(Math.max(h - l, Math.abs(h - pc), Math.abs(l - pc)));
    }

    for (let i = 0; i < period - 1; i++) result.push(NaN);

    // SMA seed
    let sum = 0;
    for (let i = 0; i < period; i++) sum += trueRanges[i];
    let prev = sum / period;
    result.push(prev);

    // Smoothed (Wilder)
    for (let i = period; i < trueRanges.length; i++) {
        prev = (prev * (period - 1) + trueRanges[i]) / period;
        result.push(prev);
    }

    return result;
}
