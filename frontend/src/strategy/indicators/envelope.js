/**
 * Moving Average Envelope
 * @param {number[]} data - Array of closing prices
 * @param {number} period - Number of periods (default 20)
 * @param {number} percent - Envelope percentage (default 2.5)
 * @returns {{ upper: number[], middle: number[], lower: number[] }}
 */
import { sma } from './sma';

export function envelope(data, period = 20, percent = 2.5) {
    const mid = sma(data, period);
    const mult = percent / 100;
    const upper = mid.map(m => isNaN(m) ? NaN : m * (1 + mult));
    const lower = mid.map(m => isNaN(m) ? NaN : m * (1 - mult));
    return { upper, middle: mid, lower };
}
