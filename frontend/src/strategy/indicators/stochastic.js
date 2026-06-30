/**
 * Stochastic Oscillator (%K and %D)
 * Matches MT4's iStochastic(K, D, slowing, MODE_SMA).
 *
 * @param {{ high: number, low: number, close: number }[]} candles
 * @param {number} [kPeriod=14]
 * @param {number} [dPeriod=3]
 * @param {number} [slowing=3]
 * @returns {{ k: number[], d: number[] }}
 */
export function stochastic(candles, kPeriod = 14, dPeriod = 3, slowing = 3) {
    const len = candles.length;
    const rawK = [];

    // Raw %K (fast stochastic)
    for (let i = 0; i < len; i++) {
        if (i < kPeriod - 1) { rawK.push(NaN); continue; }
        let hh = -Infinity, ll = Infinity;
        for (let j = i - kPeriod + 1; j <= i; j++) {
            if (candles[j].high > hh) hh = candles[j].high;
            if (candles[j].low < ll) ll = candles[j].low;
        }
        rawK.push(hh !== ll ? ((candles[i].close - ll) / (hh - ll)) * 100 : 50);
    }

    // Slowed %K = SMA of rawK over slowing period
    const slowedK = [];
    for (let i = 0; i < len; i++) {
        if (i < kPeriod - 1 + slowing - 1) { slowedK.push(NaN); continue; }
        let sum = 0;
        for (let j = i - slowing + 1; j <= i; j++) sum += rawK[j];
        slowedK.push(sum / slowing);
    }

    // %D = SMA of slowedK over dPeriod
    const d = [];
    for (let i = 0; i < len; i++) {
        if (isNaN(slowedK[i]) || i < kPeriod - 1 + slowing - 1 + dPeriod - 1) { d.push(NaN); continue; }
        let sum = 0;
        for (let j = i - dPeriod + 1; j <= i; j++) sum += slowedK[j];
        d.push(sum / dPeriod);
    }

    return { k: slowedK, d };
}
