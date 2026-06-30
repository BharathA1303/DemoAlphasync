/**
 * Williams %R
 * @param {Object[]} candles - Array of candle objects with { high, low, close }
 * @param {number} period - Number of periods (default 14)
 * @returns {number[]} Williams %R values
 */
export function williamsR(candles, period = 14) {
    const len = candles.length;
    const result = new Array(len).fill(NaN);
    for (let i = period - 1; i < len; i++) {
        let hh = -Infinity, ll = Infinity;
        for (let j = i - period + 1; j <= i; j++) {
            if (candles[j].high > hh) hh = candles[j].high;
            if (candles[j].low < ll) ll = candles[j].low;
        }
        result[i] = hh === ll ? 0 : ((hh - candles[i].close) / (hh - ll)) * -100;
    }
    return result;
}
