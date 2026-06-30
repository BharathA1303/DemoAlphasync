/**
 * Parabolic SAR
 * @param {Object[]} candles - Array of candle objects with { high, low, close }
 * @param {number} step - Acceleration factor step (default 0.02)
 * @param {number} max - Maximum acceleration factor (default 0.2)
 * @returns {{ sar: number[], direction: number[] }}
 */
export function psar(candles, step = 0.02, max = 0.2) {
    const len = candles.length;
    if (len < 2) return { sar: [], direction: [] };
    const sar = new Array(len).fill(NaN);
    const direction = new Array(len).fill(0);
    let isLong = candles[1].close > candles[0].close;
    let af = step;
    let ep = isLong ? candles[0].high : candles[0].low;
    sar[0] = isLong ? candles[0].low : candles[0].high;
    for (let i = 1; i < len; i++) {
        const prevSar = sar[i - 1];
        let currentSar = prevSar + af * (ep - prevSar);
        if (isLong) {
            currentSar = Math.min(currentSar, candles[i - 1].low, i > 1 ? candles[i - 2].low : candles[i - 1].low);
            if (candles[i].low < currentSar) {
                isLong = false;
                currentSar = ep;
                ep = candles[i].low;
                af = step;
            } else {
                if (candles[i].high > ep) {
                    ep = candles[i].high;
                    af = Math.min(af + step, max);
                }
            }
        } else {
            currentSar = Math.max(currentSar, candles[i - 1].high, i > 1 ? candles[i - 2].high : candles[i - 1].high);
            if (candles[i].high > currentSar) {
                isLong = true;
                currentSar = ep;
                ep = candles[i].high;
                af = step;
            } else {
                if (candles[i].low < ep) {
                    ep = candles[i].low;
                    af = Math.min(af + step, max);
                }
            }
        }
        sar[i] = currentSar;
        direction[i] = isLong ? 1 : -1;
    }
    return { sar, direction };
}
