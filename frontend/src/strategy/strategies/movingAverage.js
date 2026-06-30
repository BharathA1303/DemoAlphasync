import { sma } from '../indicators';

/**
 * Moving Average Cross-over Strategy
 * Bullish when fast SMA > slow SMA, Bearish otherwise.
 */
export const meta = {
    id: 'moving-average',
    name: 'Moving Average Cross',
    description: 'SMA 20/50 crossover — trend-following signal',
    category: 'Trend',
    weight: 0.10,
};

/**
 * @param {{ close: number }[]} candles
 * @returns {{ name: string, signal: 'Bullish'|'Bearish'|'Neutral', confidence: number, detail: string }}
 */
export function runStrategy(candles) {
    const closes = candles.map((c) => c.close);
    if (closes.length < 50) {
        return { name: meta.name, signal: 'Neutral', confidence: 0, detail: 'Not enough data (need 50 candles)' };
    }

    const fast = sma(closes, 20);
    const slow = sma(closes, 50);
    const lastFast = fast[fast.length - 1];
    const lastSlow = slow[slow.length - 1];
    const prevFast = fast[fast.length - 2];
    const prevSlow = slow[slow.length - 2];

    if (isNaN(lastFast) || isNaN(lastSlow)) {
        return { name: meta.name, signal: 'Neutral', confidence: 0, detail: 'Insufficient indicator data' };
    }

    const spread = ((lastFast - lastSlow) / lastSlow) * 100;
    const crossUp = prevFast <= prevSlow && lastFast > lastSlow;
    const crossDown = prevFast >= prevSlow && lastFast < lastSlow;

    let signal = 'Neutral';
    let confidence = 50;
    let detail = `SMA20: ${lastFast.toFixed(2)} | SMA50: ${lastSlow.toFixed(2)}`;

    if (crossUp) {
        signal = 'Bullish';
        confidence = 85;
        detail += ' — Golden cross detected';
    } else if (crossDown) {
        signal = 'Bearish';
        confidence = 85;
        detail += ' — Death cross detected';
    } else if (lastFast > lastSlow) {
        signal = 'Bullish';
        confidence = Math.min(50 + Math.abs(spread) * 5, 90);
        detail += ` — Spread: +${spread.toFixed(2)}%`;
    } else {
        signal = 'Bearish';
        confidence = Math.min(50 + Math.abs(spread) * 5, 90);
        detail += ` — Spread: ${spread.toFixed(2)}%`;
    }

    return { name: meta.name, signal, confidence: Math.round(confidence), detail };
}
