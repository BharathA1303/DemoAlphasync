/**
 * Standard Deviation
 * @param {number[]} data - Array of closing prices
 * @param {number} period - Number of periods (default 20)
 * @returns {number[]} Standard deviation values
 */
import { sma } from './sma';

export function stddev(data, period = 20) {
    const avg = sma(data, period);
    const result = new Array(data.length).fill(NaN);
    for (let i = period - 1; i < data.length; i++) {
        let sum = 0;
        for (let j = i - period + 1; j <= i; j++) {
            sum += (data[j] - avg[i]) ** 2;
        }
        result[i] = Math.sqrt(sum / period);
    }
    return result;
}
