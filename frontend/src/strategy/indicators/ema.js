/**
 * Exponential Moving Average (EMA)
 * @param {number[]} data - Array of closing prices
 * @param {number} period - Number of periods
 * @returns {number[]} EMA values
 */
export function ema(data, period) {
    const k = 2 / (period + 1);
    const result = [];
    let prev = NaN;

    for (let i = 0; i < data.length; i++) {
        if (i < period - 1) {
            result.push(NaN);
            continue;
        }
        if (i === period - 1) {
            // Seed with SMA
            let sum = 0;
            for (let j = 0; j < period; j++) sum += data[j];
            prev = sum / period;
            result.push(prev);
            continue;
        }
        prev = data[i] * k + prev * (1 - k);
        result.push(prev);
    }
    return result;
}
