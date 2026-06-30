/**
 * Chaikin Money Flow (CMF)
 * @param {Object[]} candles - Array of candle objects with { high, low, close, volume }
 * @param {number} period - Number of periods (default 20)
 * @returns {number[]} CMF values
 */
export function cmf(candles, period = 20) {
    const len = candles.length;
    const result = new Array(len).fill(NaN);
    for (let i = period - 1; i < len; i++) {
        let mfvSum = 0, volSum = 0;
        for (let j = i - period + 1; j <= i; j++) {
            const hl = candles[j].high - candles[j].low;
            const clv = hl === 0 ? 0 : ((candles[j].close - candles[j].low) - (candles[j].high - candles[j].close)) / hl;
            mfvSum += clv * (candles[j].volume || 0);
            volSum += candles[j].volume || 0;
        }
        result[i] = volSum === 0 ? 0 : mfvSum / volSum;
    }
    return result;
}
