/**
 * Money Flow Index (MFI)
 * @param {Object[]} candles - Array of candle objects with { high, low, close, volume }
 * @param {number} period - Number of periods (default 14)
 * @returns {number[]} MFI values
 */
export function mfi(candles, period = 14) {
    const len = candles.length;
    const result = new Array(len).fill(NaN);
    if (len < period + 1) return result;
    const tp = candles.map(c => (c.high + c.low + c.close) / 3);
    const mf = tp.map((t, i) => t * (candles[i].volume || 0));
    for (let i = period; i < len; i++) {
        let posFlow = 0, negFlow = 0;
        for (let j = i - period + 1; j <= i; j++) {
            if (tp[j] > tp[j - 1]) posFlow += mf[j];
            else negFlow += mf[j];
        }
        const ratio = negFlow === 0 ? 100 : posFlow / negFlow;
        result[i] = 100 - 100 / (1 + ratio);
    }
    return result;
}
