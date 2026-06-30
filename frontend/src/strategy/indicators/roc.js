/**
 * Rate of Change (ROC)
 * @param {number[]} data - Array of closing prices
 * @param {number} period - Number of periods (default 12)
 * @returns {number[]} ROC values
 */
export function roc(data, period = 12) {
    const result = new Array(data.length).fill(NaN);
    for (let i = period; i < data.length; i++) {
        if (data[i - period] !== 0) {
            result[i] = ((data[i] - data[i - period]) / data[i - period]) * 100;
        }
    }
    return result;
}
