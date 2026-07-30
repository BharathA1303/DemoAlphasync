/**
 * Simple Moving Average (SMA)
 * @param {number[]} data - Array of closing prices
 * @param {number} period - Number of periods
 * @returns {number[]} SMA values (first `period - 1` entries are NaN)
 */
export function sma(data, period) {
    const result = [];
    for (let i = 0; i < data.length; i++) {
        if (i < period - 1) {
            result.push(NaN);
            continue;
        }
        let sum = 0;
        for (let j = i - period + 1; j <= i; j++) sum += data[j];
        result.push(sum / period);
    }
    return result;
}
