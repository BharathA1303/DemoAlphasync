/**
 * Weighted Moving Average (WMA)
 * @param {number[]} data - Array of closing prices
 * @param {number} period - Number of periods
 * @returns {number[]} WMA values
 */
export function wma(data, period) {
    const result = new Array(data.length).fill(NaN);
    const denom = (period * (period + 1)) / 2;
    for (let i = period - 1; i < data.length; i++) {
        let sum = 0;
        for (let j = 0; j < period; j++) {
            sum += data[i - period + 1 + j] * (j + 1);
        }
        result[i] = sum / denom;
    }
    return result;
}
