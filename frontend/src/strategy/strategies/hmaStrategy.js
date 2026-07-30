import { hma as calcHma } from '../indicators';

/**
 * HMA Strategy — matches MQ4 HMA(21) vs HMA(55)
 * Fast HMA > Slow HMA → Bullish
 */
export const meta = {
    id: 'hma-trend',
    name: 'HMA Trend',
    description: 'Hull MA(21/55) — smooth trend filter',
    category: 'Trend',
    weight: 0.10,
};

export function runStrategy(candles) {
    const closes = candles.map((c) => c.close);
    if (closes.length < 60) {
        return { name: meta.name, signal: 'Neutral', confidence: 0, detail: 'Need 60+ candles' };
    }

    const hmaFast = calcHma(closes, 21);
    const hmaSlow = calcHma(closes, 55);
    const lastFast = hmaFast[hmaFast.length - 1];
    const lastSlow = hmaSlow[hmaSlow.length - 1];
    const prevFast = hmaFast[hmaFast.length - 2];

    if ([lastFast, lastSlow].some(isNaN)) {
        return { name: meta.name, signal: 'Neutral', confidence: 0, detail: 'HMA data incomplete' };
    }

    const rising = lastFast > prevFast;
    const spread = ((lastFast - lastSlow) / lastSlow) * 100;

    let signal = 'Neutral';
    let confidence = 50;

    if (lastFast > lastSlow && rising) {
        signal = 'Bullish';
        confidence = Math.min(60 + Math.abs(spread) * 4, 90);
    } else if (lastFast < lastSlow && !rising) {
        signal = 'Bearish';
        confidence = Math.min(60 + Math.abs(spread) * 4, 90);
    } else if (lastFast > lastSlow) {
        signal = 'Bullish'; confidence = 55;
    } else {
        signal = 'Bearish'; confidence = 55;
    }

    return {
        name: meta.name, signal, confidence: Math.round(confidence),
        detail: `HMA21: ${lastFast.toFixed(2)} | HMA55: ${lastSlow.toFixed(2)} | ${rising ? '▲ Rising' : '▼ Falling'}`,
    };
}
