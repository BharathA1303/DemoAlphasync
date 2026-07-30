/**
 * Aroon Indicator
 * @param {Object[]} candles - Array of candle objects with { high, low }
 * @param {number} period - Number of periods (default 25)
 * @returns {{ up: number[], down: number[] }}
 */
export function aroon(candles, period = 25) {
    const len = candles.length;
    const up = new Array(len).fill(NaN);
    const down = new Array(len).fill(NaN);
    for (let i = period; i < len; i++) {
        let highIdx = 0, lowIdx = 0;
        let hh = -Infinity, ll = Infinity;
        for (let j = 0; j <= period; j++) {
            if (candles[i - period + j].high > hh) { hh = candles[i - period + j].high; highIdx = j; }
            if (candles[i - period + j].low < ll) { ll = candles[i - period + j].low; lowIdx = j; }
        }
        up[i] = (highIdx / period) * 100;
        down[i] = (lowIdx / period) * 100;
    }
    return { up, down };
}
