/**
 * Average Directional Index (ADX) with +DI / -DI
 * Matches MT4's iADX(period) behaviour.
 *
 * @param {{ high: number, low: number, close: number }[]} candles
 * @param {number} [period=14]
 * @returns {{ adx: number[], plusDI: number[], minusDI: number[] }}
 */
export function adx(candles, period = 14) {
    const len = candles.length;
    const adxArr = Array(len).fill(NaN);
    const plusDIArr = Array(len).fill(NaN);
    const minusDIArr = Array(len).fill(NaN);

    if (len < period + 1) return { adx: adxArr, plusDI: plusDIArr, minusDI: minusDIArr };

    // True Range, +DM, -DM
    const tr = [];
    const plusDM = [];
    const minusDM = [];

    for (let i = 1; i < len; i++) {
        const h = candles[i].high;
        const l = candles[i].low;
        const pc = candles[i - 1].close;
        tr.push(Math.max(h - l, Math.abs(h - pc), Math.abs(l - pc)));

        const upMove = h - candles[i - 1].high;
        const downMove = candles[i - 1].low - l;
        plusDM.push(upMove > downMove && upMove > 0 ? upMove : 0);
        minusDM.push(downMove > upMove && downMove > 0 ? downMove : 0);
    }

    // Smooth with Wilder's method (initial SMA then exponential)
    const smooth = (arr) => {
        const out = [];
        let sum = 0;
        for (let i = 0; i < period; i++) sum += arr[i];
        out.push(sum);
        for (let i = period; i < arr.length; i++) {
            out.push(out[out.length - 1] - out[out.length - 1] / period + arr[i]);
        }
        return out;
    };

    const sTR = smooth(tr);
    const sPlusDM = smooth(plusDM);
    const sMinusDM = smooth(minusDM);

    const dx = [];
    for (let i = 0; i < sTR.length; i++) {
        const pdi = sTR[i] !== 0 ? (sPlusDM[i] / sTR[i]) * 100 : 0;
        const mdi = sTR[i] !== 0 ? (sMinusDM[i] / sTR[i]) * 100 : 0;
        const diSum = pdi + mdi;
        dx.push(diSum !== 0 ? (Math.abs(pdi - mdi) / diSum) * 100 : 0);

        const idx = i + period; // actual candle index
        plusDIArr[idx] = pdi;
        minusDIArr[idx] = mdi;
    }

    // ADX = smoothed DX
    if (dx.length >= period) {
        let adxSum = 0;
        for (let i = 0; i < period; i++) adxSum += dx[i];
        let adxVal = adxSum / period;
        adxArr[2 * period - 1] = adxVal;
        for (let i = period; i < dx.length; i++) {
            adxVal = (adxVal * (period - 1) + dx[i]) / period;
            adxArr[i + period] = adxVal;
        }
    }

    return { adx: adxArr, plusDI: plusDIArr, minusDI: minusDIArr };
}
