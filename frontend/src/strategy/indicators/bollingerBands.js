import { sma } from './sma';

/**
 * Bollinger Bands
 * Matches MT4's iBands(period, deviation).
 *
 * @param {number[]} closes
 * @param {number} [period=20]
 * @param {number} [deviation=2]
 * @returns {{ upper: number[], middle: number[], lower: number[] }}
 */
export function bollingerBands(closes, period = 20, deviation = 2) {
    const middle = sma(closes, period);
    const upper = [];
    const lower = [];

    for (let i = 0; i < closes.length; i++) {
        if (isNaN(middle[i])) {
            upper.push(NaN);
            lower.push(NaN);
            continue;
        }
        let sumSq = 0;
        for (let j = i - period + 1; j <= i; j++) {
            const diff = closes[j] - middle[i];
            sumSq += diff * diff;
        }
        const stdDev = Math.sqrt(sumSq / period);
        upper.push(middle[i] + deviation * stdDev);
        lower.push(middle[i] - deviation * stdDev);
    }

    return { upper, middle, lower };
}
