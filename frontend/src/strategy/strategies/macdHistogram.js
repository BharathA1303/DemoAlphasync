import { macd as calcMacd } from '../indicators';

/**
 * MACD Histogram Strategy — matches MQ4 MACD(12,26,9), Weight: 10%
 * Histogram > 0 → Bullish, < 0 → Bearish
 */
export const meta = {
    id: 'macd-histogram',
    name: 'MACD Histogram',
    description: 'MACD(12,26,9) histogram momentum signal',
    category: 'Momentum',
    weight: 0.10,
};

export function runStrategy(candles) {
    const closes = candles.map((c) => c.close);
    if (closes.length < 35) {
        return { name: meta.name, signal: 'Neutral', confidence: 0, detail: 'Need 35+ candles' };
    }

    const { macd: macdLine, signal: signalLine, histogram } = calcMacd(closes, 12, 26, 9);
    const lastMacd = macdLine[macdLine.length - 1];
    const lastSignal = signalLine[signalLine.length - 1];
    const lastHist = histogram[histogram.length - 1];
    const prevHist = histogram[histogram.length - 2];

    if ([lastMacd, lastSignal, lastHist].some(isNaN)) {
        return { name: meta.name, signal: 'Neutral', confidence: 0, detail: 'MACD data incomplete' };
    }

    const histExpanding = Math.abs(lastHist) > Math.abs(prevHist);
    let signal = 'Neutral';
    let confidence = 50;

    if (lastHist > 0) {
        signal = 'Bullish';
        confidence = histExpanding ? 78 : 62;
    } else if (lastHist < 0) {
        signal = 'Bearish';
        confidence = histExpanding ? 78 : 62;
    }

    return {
        name: meta.name, signal, confidence: Math.round(confidence),
        detail: `MACD: ${lastMacd.toFixed(2)} | Signal: ${lastSignal.toFixed(2)} | Hist: ${lastHist.toFixed(2)}`,
    };
}
