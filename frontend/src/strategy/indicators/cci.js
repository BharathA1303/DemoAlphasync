/**
 * Commodity Channel Index (CCI)
 * Matches MT4's iCCI(period, PRICE_CLOSE).
 *
 * @param {{ high: number, low: number, close: number }[]} candles
 * @param {number} [period=14]
 * @returns {number[]}
 */
export function cci(candles, period = 14) {
    const tp = candles.map((c) => (c.high + c.low + c.close) / 3);
    const result = [];

    for (let i = 0; i < tp.length; i++) {
        if (i < period - 1) { result.push(NaN); continue; }

        let sum = 0;
        for (let j = i - period + 1; j <= i; j++) sum += tp[j];
        const mean = sum / period;

        let meanDev = 0;
        for (let j = i - period + 1; j <= i; j++) meanDev += Math.abs(tp[j] - mean);
        meanDev /= period;

        result.push(meanDev !== 0 ? (tp[i] - mean) / (0.015 * meanDev) : 0);
    }

    return result;
}
