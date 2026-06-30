/**
 * Hull Moving Average (HMA)
 * HMA = WMA(2 * WMA(n/2) − WMA(n), √n)
 *
 * @param {number[]} data - Close prices
 * @param {number} period
 * @returns {number[]}
 */
export function hma(data, period) {
    const wma = (arr, p) => {
        const result = [];
        for (let i = 0; i < arr.length; i++) {
            if (i < p - 1) { result.push(NaN); continue; }
            let num = 0, den = 0;
            for (let j = 0; j < p; j++) {
                const w = p - j;
                num += arr[i - j] * w;
                den += w;
            }
            result.push(num / den);
        }
        return result;
    };

    const halfPeriod = Math.floor(period / 2);
    const sqrtPeriod = Math.round(Math.sqrt(period));

    const wmaHalf = wma(data, halfPeriod);
    const wmaFull = wma(data, period);

    // 2 * WMA(half) - WMA(full)
    const diff = wmaHalf.map((v, i) =>
        isNaN(v) || isNaN(wmaFull[i]) ? NaN : 2 * v - wmaFull[i]
    );

    // Filter out NaN prefix for the final WMA
    const validDiff = diff.filter((v) => !isNaN(v));
    const hmaValid = wma(validDiff, sqrtPeriod);

    // Re-align with original indices
    const nanCount = diff.length - validDiff.length;
    return Array(nanCount).fill(NaN).concat(hmaValid);
}
