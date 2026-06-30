import { ema } from './ema';

/**
 * MACD (Moving Average Convergence Divergence)
 * @param {number[]} closes
 * @param {number} [fast=12]
 * @param {number} [slow=26]
 * @param {number} [signal=9]
 * @returns {{ macd: number[], signal: number[], histogram: number[] }}
 */
export function macd(closes, fast = 12, slow = 26, signal = 9) {
    const emaFast = ema(closes, fast);
    const emaSlow = ema(closes, slow);

    const macdLine = emaFast.map((f, i) =>
        isNaN(f) || isNaN(emaSlow[i]) ? NaN : f - emaSlow[i]
    );

    // Signal line = EMA of MACD line (skip NaN prefix)
    const validMacd = macdLine.filter((v) => !isNaN(v));
    const signalLine = ema(validMacd, signal);

    // Re‑align signal line with original indices
    const nanCount = macdLine.length - validMacd.length;
    const fullSignal = Array(nanCount).fill(NaN).concat(signalLine);

    const histogram = macdLine.map((m, i) =>
        isNaN(m) || isNaN(fullSignal[i]) ? NaN : m - fullSignal[i]
    );

    return { macd: macdLine, signal: fullSignal, histogram };
}
