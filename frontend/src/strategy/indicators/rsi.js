/**
 * Relative Strength Index (RSI)
 * @param {number[]} closes - Array of closing prices
 * @param {number} [period=14] - RSI lookback period
 * @returns {number[]} RSI values (first `period` entries are NaN)
 */
export function rsi(closes, period = 14) {
    const safePeriod = Math.max(1, Number(period) || 14);
    const safeCloses = (closes || []).map((v) => Number(v));
    const result = safeCloses.map(() => NaN);

    if (safeCloses.length < safePeriod + 1) return result;

    const gains = [];
    const losses = [];

    for (let i = 1; i < safeCloses.length; i++) {
        const curr = safeCloses[i];
        const prev = safeCloses[i - 1];
        if (!Number.isFinite(curr) || !Number.isFinite(prev)) {
            gains.push(0);
            losses.push(0);
            continue;
        }
        const diff = curr - prev;
        gains.push(diff > 0 ? diff : 0);
        losses.push(diff < 0 ? -diff : 0);
    }

    let avgGain = 0;
    let avgLoss = 0;
    for (let i = 0; i < safePeriod; i++) {
        avgGain += gains[i] || 0;
        avgLoss += losses[i] || 0;
    }
    avgGain /= safePeriod;
    avgLoss /= safePeriod;

    const toRsi = (gain, loss) => {
        if (loss === 0 && gain === 0) return 50;
        if (loss === 0) return 100;
        if (gain === 0) return 0;
        const rs = gain / loss;
        return 100 - (100 / (1 + rs));
    };

    result[safePeriod] = toRsi(avgGain, avgLoss);

    for (let i = safePeriod; i < gains.length; i++) {
        avgGain = ((avgGain * (safePeriod - 1)) + (gains[i] || 0)) / safePeriod;
        avgLoss = ((avgLoss * (safePeriod - 1)) + (losses[i] || 0)) / safePeriod;
        result[i + 1] = toRsi(avgGain, avgLoss);
    }

    return result;
}
