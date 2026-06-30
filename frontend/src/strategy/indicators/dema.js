/**
 * Double Exponential Moving Average (DEMA)
 * @param {number[]} data - Array of closing prices
 * @param {number} period - Number of periods
 * @returns {number[]} DEMA values
 */
import { ema } from './ema';

export function dema(data, period) {
    const e1 = ema(data, period);
    const e2 = ema(e1.filter(v => !isNaN(v)), period);
    const result = new Array(data.length).fill(NaN);
    // DEMA = 2*EMA - EMA(EMA)
    // Need to align properly
    const e1Valid = e1.map((v, i) => ({ v, i })).filter(x => !isNaN(x.v));
    const e2Offset = e1Valid.length - e2.length;
    for (let j = 0; j < e2.length; j++) {
        const origIdx = e1Valid[j + e2Offset].i;
        result[origIdx] = 2 * e1[origIdx] - e2[j];
    }
    return result;
}
