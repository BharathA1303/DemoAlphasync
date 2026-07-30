/**
 * Volume Weighted Average Price (VWAP)
 * Calculates cumulative VWAP from candle data.
 * @param {{ high: number, low: number, close: number, volume?: number }[]} candles
 * @returns {number[]} VWAP values
 */
export function vwap(candles) {
    let cumVol = 0;
    let cumTP = 0;
    return candles.map((c) => {
        const vol = c.volume ?? 1;
        const tp = (c.high + c.low + c.close) / 3;
        cumVol += vol;
        cumTP += tp * vol;
        return cumVol === 0 ? tp : cumTP / cumVol;
    });
}
