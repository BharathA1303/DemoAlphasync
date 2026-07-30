import { bollingerBands } from '../indicators';

/**
 * Bollinger Bands Strategy — matches MQ4 iBands(20,2.0), Weight: 15%
 * Price > Upper → Bearish (overbought)
 * Price < Lower → Bullish (oversold)
 */
export const meta = {
    id: 'bollinger-bands',
    name: 'Bollinger Bands',
    description: 'BB(20,2) volatility-based reversal detection',
    category: 'Volatility',
    weight: 0.15,
};

export function runStrategy(candles) {
    const closes = candles.map((c) => c.close);
    if (closes.length < 22) {
        return { name: meta.name, signal: 'Neutral', confidence: 0, detail: 'Need 22+ candles' };
    }

    const { upper, middle, lower } = bollingerBands(closes, 20, 2.0);
    const lastClose = closes[closes.length - 1];
    const lastUpper = upper[upper.length - 1];
    const lastMiddle = middle[middle.length - 1];
    const lastLower = lower[lower.length - 1];

    if ([lastUpper, lastMiddle, lastLower].some(isNaN)) {
        return { name: meta.name, signal: 'Neutral', confidence: 0, detail: 'BB data incomplete' };
    }

    const bandwidth = ((lastUpper - lastLower) / lastMiddle) * 100;
    let signal = 'Neutral';
    let confidence = 50;

    if (lastClose > lastUpper) {
        signal = 'Bearish';
        const overshoot = ((lastClose - lastUpper) / (lastUpper - lastMiddle)) * 100;
        confidence = Math.min(65 + overshoot * 0.5, 92);
    } else if (lastClose < lastLower) {
        signal = 'Bullish';
        const overshoot = ((lastLower - lastClose) / (lastMiddle - lastLower)) * 100;
        confidence = Math.min(65 + overshoot * 0.5, 92);
    } else if (lastClose > lastMiddle) {
        signal = 'Bullish'; confidence = 55;
    } else {
        signal = 'Bearish'; confidence = 55;
    }

    return {
        name: meta.name, signal, confidence: Math.round(confidence),
        detail: `Upper: ${lastUpper.toFixed(2)} | Mid: ${lastMiddle.toFixed(2)} | Lower: ${lastLower.toFixed(2)} | BW: ${bandwidth.toFixed(1)}%`,
    };
}
