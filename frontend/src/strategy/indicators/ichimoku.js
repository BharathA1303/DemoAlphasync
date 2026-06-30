/**
 * Ichimoku Cloud
 * Matches MT4's iIchimoku(tenkan, kijun, senkou).
 *
 * @param {{ high: number, low: number, close: number }[]} candles
 * @param {number} [tenkanPeriod=9]
 * @param {number} [kijunPeriod=26]
 * @param {number} [senkouPeriod=52]
 * @returns {{ tenkan: number[], kijun: number[], senkouA: number[], senkouB: number[] }}
 */
export function ichimoku(candles, tenkanPeriod = 9, kijunPeriod = 26, senkouPeriod = 52) {
    const len = candles.length;

    const midline = (period, idx) => {
        if (idx < period - 1) return NaN;
        let hh = -Infinity, ll = Infinity;
        for (let j = idx - period + 1; j <= idx; j++) {
            if (candles[j].high > hh) hh = candles[j].high;
            if (candles[j].low < ll) ll = candles[j].low;
        }
        return (hh + ll) / 2;
    };

    const tenkan = [];
    const kijun = [];
    const senkouA = [];
    const senkouB = [];

    for (let i = 0; i < len; i++) {
        const t = midline(tenkanPeriod, i);
        const k = midline(kijunPeriod, i);
        tenkan.push(t);
        kijun.push(k);
        senkouA.push(!isNaN(t) && !isNaN(k) ? (t + k) / 2 : NaN);
        senkouB.push(midline(senkouPeriod, i));
    }

    return { tenkan, kijun, senkouA, senkouB };
}
