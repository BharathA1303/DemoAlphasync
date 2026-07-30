/**
 * Pivot Points (Standard)
 * @param {Object[]} candles - Array of candle objects with { high, low, close }
 * @returns {{ pp: number[], r1: number[], r2: number[], r3: number[], s1: number[], s2: number[], s3: number[] }}
 */
export function pivotPoints(candles) {
    const len = candles.length;
    const pp = new Array(len).fill(NaN);
    const r1 = new Array(len).fill(NaN);
    const r2 = new Array(len).fill(NaN);
    const r3 = new Array(len).fill(NaN);
    const s1 = new Array(len).fill(NaN);
    const s2 = new Array(len).fill(NaN);
    const s3 = new Array(len).fill(NaN);
    for (let i = 1; i < len; i++) {
        const prev = candles[i - 1];
        const p = (prev.high + prev.low + prev.close) / 3;
        pp[i] = p;
        r1[i] = 2 * p - prev.low;
        s1[i] = 2 * p - prev.high;
        r2[i] = p + (prev.high - prev.low);
        s2[i] = p - (prev.high - prev.low);
        r3[i] = prev.high + 2 * (p - prev.low);
        s3[i] = prev.low - 2 * (prev.high - p);
    }
    return { pp, r1, r2, r3, s1, s2, s3 };
}
