/**
 * Triple Exponential Moving Average (TEMA)
 * @param {number[]} data - Array of closing prices
 * @param {number} period - Number of periods
 * @returns {number[]} TEMA values
 */
import { ema } from './ema';

export function tema(data, period) {
    const e1 = ema(data, period);
    const e1Clean = e1.filter(v => !isNaN(v));
    const e2 = ema(e1Clean, period);
    const e2Clean = e2.filter(v => !isNaN(v));
    const e3 = ema(e2Clean, period);
    const result = new Array(data.length).fill(NaN);
    const e1Valid = e1.map((v, i) => ({ v, i })).filter(x => !isNaN(x.v));
    const e2Valid = e2.map((v, i) => ({ v, i: e1Valid[i + (e1Valid.length - e2.length)]?.i })).filter(x => x.i !== undefined && !isNaN(x.v));
    const e3Offset = e2Valid.length - e3.length;
    for (let j = 0; j < e3.length; j++) {
        const idx = e2Valid[j + e3Offset]?.i;
        if (idx !== undefined && !isNaN(e1[idx]) && !isNaN(e2[j + e3Offset])) {
            result[idx] = 3 * e1[idx] - 3 * e2[j + e3Offset] + e3[j];
        }
    }
    return result;
}
