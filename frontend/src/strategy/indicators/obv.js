/**
 * On-Balance Volume (OBV)
 * @param {Object[]} candles - Array of candle objects with { close, volume }
 * @returns {number[]} OBV values
 */
export function obv(candles) {
    const len = candles.length;
    const result = new Array(len).fill(NaN);
    if (len === 0) return result;
    result[0] = candles[0].volume || 0;
    for (let i = 1; i < len; i++) {
        const vol = candles[i].volume || 0;
        if (candles[i].close > candles[i - 1].close) result[i] = result[i - 1] + vol;
        else if (candles[i].close < candles[i - 1].close) result[i] = result[i - 1] - vol;
        else result[i] = result[i - 1];
    }
    return result;
}
