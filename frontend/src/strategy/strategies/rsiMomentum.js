import { rsi as calcRsi } from '../indicators';

/**
 * RSI Momentum Strategy — with proper dead zone.
 * Only signals at extremes or with confirmed divergence.
 * 40–60 = Neutral dead zone (no opinion).
 * 60–70 = Mild bullish, 30–40 = Mild bearish (low confidence).
 * >70 = Overbought reversal (bearish), <30 = Oversold reversal (bullish).
 */
export const meta = {
    id: 'rsi-momentum',
    name: 'RSI Momentum',
    description: 'RSI(14) with dead zone — signals only at extremes',
    category: 'Momentum',
    weight: 0.20,
};

export function runStrategy(candles) {
    const closes = candles.map((c) => c.close);
    if (closes.length < 20) {
        return { name: meta.name, signal: 'Neutral', confidence: 0, detail: 'Need 20+ candles' };
    }

    const rsiArr = calcRsi(closes, 14);
    const current = rsiArr[rsiArr.length - 1];
    const prev = rsiArr[rsiArr.length - 2];
    const prev2 = rsiArr[rsiArr.length - 3];

    if ([current, prev, prev2].some(isNaN)) {
        return { name: meta.name, signal: 'Neutral', confidence: 0, detail: 'RSI not available' };
    }

    const rsiRising = current > prev && prev > prev2;
    const rsiFalling = current < prev && prev < prev2;

    let signal = 'Neutral';
    let confidence = 0;
    let detail = `RSI(14): ${current.toFixed(1)}`;

    // Extreme overbought — reversal signal (bearish)
    if (current >= 75) {
        signal = 'Bearish';
        confidence = Math.min(70 + (current - 75) * 2, 92);
        detail += ' — Overbought reversal zone';
    } else if (current >= 70) {
        signal = 'Bearish';
        confidence = rsiFalling ? 72 : 58;
        detail += ' — Overbought';
    }
    // Extreme oversold — reversal signal (bullish)
    else if (current <= 25) {
        signal = 'Bullish';
        confidence = Math.min(70 + (25 - current) * 2, 92);
        detail += ' — Oversold reversal zone';
    } else if (current <= 30) {
        signal = 'Bullish';
        confidence = rsiRising ? 72 : 58;
        detail += ' — Oversold';
    }
    // Mild zones — with or without momentum confirmation
    else if (current > 58 && rsiRising) {
        signal = 'Bullish';
        confidence = 60;
        detail += ' — Bullish momentum';
    } else if (current > 55) {
        signal = 'Bullish';
        confidence = 45;
        detail += ' — Mildly bullish';
    } else if (current < 42 && rsiFalling) {
        signal = 'Bearish';
        confidence = 60;
        detail += ' — Bearish momentum';
    } else if (current < 45) {
        signal = 'Bearish';
        confidence = 45;
        detail += ' — Mildly bearish';
    }
    // Dead zone 45–55 — no opinion
    else {
        detail += ' — Neutral zone';
    }

    return { name: meta.name, signal, confidence: Math.round(confidence), detail };
}
