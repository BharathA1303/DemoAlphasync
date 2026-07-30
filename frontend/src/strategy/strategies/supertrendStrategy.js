import { supertrend as calcST } from '../indicators';

/**
 * SuperTrend Strategy — matches MQ4 SuperTrend(ATR 10, Mult 3.0)
 * Direction = 1 → Bullish, Direction = -1 → Bearish
 */
export const meta = {
    id: 'supertrend',
    name: 'SuperTrend',
    description: 'SuperTrend(10,3.0) — ATR-based trend reversal',
    category: 'Trend',
    weight: 0.10,
};

export function runStrategy(candles) {
    if (candles.length < 15) {
        return { name: meta.name, signal: 'Neutral', confidence: 0, detail: 'Need 15+ candles' };
    }

    const { supertrend, direction } = calcST(candles, 10, 3.0);
    const lastDir = direction[direction.length - 1];
    const lastST = supertrend[supertrend.length - 1];
    const prevDir = direction[direction.length - 2];
    const lastClose = candles[candles.length - 1].close;

    if (lastDir === 0 || isNaN(lastST)) {
        return { name: meta.name, signal: 'Neutral', confidence: 0, detail: 'SuperTrend data incomplete' };
    }

    const flipOccurred = prevDir !== 0 && lastDir !== prevDir;
    const distance = Math.abs(((lastClose - lastST) / lastST) * 100);

    let signal = 'Neutral';
    let confidence = 50;

    if (lastDir === 1) {
        signal = 'Bullish';
        confidence = flipOccurred ? 88 : Math.min(58 + distance * 5, 85);
    } else {
        signal = 'Bearish';
        confidence = flipOccurred ? 88 : Math.min(58 + distance * 5, 85);
    }

    return {
        name: meta.name, signal, confidence: Math.round(confidence),
        detail: `ST: ${lastST.toFixed(2)} | Dir: ${lastDir === 1 ? '▲ Bull' : '▼ Bear'}${flipOccurred ? ' — FLIP!' : ''} | Dist: ${distance.toFixed(2)}%`,
    };
}
