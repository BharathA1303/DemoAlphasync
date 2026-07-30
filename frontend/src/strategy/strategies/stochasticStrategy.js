import { stochastic as calcStoch } from '../indicators';

/**
 * Stochastic Oscillator Strategy — matches MQ4 Stochastic(14,3,3), Weight: 15%
 * %K > 80 && %D > 80 → Bearish (overbought)
 * %K < 20 && %D < 20 → Bullish (oversold)
 */
export const meta = {
    id: 'stochastic',
    name: 'Stochastic Oscillator',
    description: 'Stochastic(14,3,3) overbought/oversold zones',
    category: 'Momentum',
    weight: 0.15,
};

export function runStrategy(candles) {
    if (candles.length < 20) {
        return { name: meta.name, signal: 'Neutral', confidence: 0, detail: 'Need 20+ candles' };
    }

    const { k, d } = calcStoch(candles, 14, 3, 3);
    const lastK = k[k.length - 1];
    const lastD = d[d.length - 1];

    if (isNaN(lastK) || isNaN(lastD)) {
        return { name: meta.name, signal: 'Neutral', confidence: 0, detail: 'Stochastic data incomplete' };
    }

    let signal = 'Neutral';
    let confidence = 50;

    if (lastK > 80 && lastD > 80) {
        signal = 'Bearish';
        confidence = Math.min(65 + (lastK - 80) * 1.5, 95);
    } else if (lastK < 20 && lastD < 20) {
        signal = 'Bullish';
        confidence = Math.min(65 + (20 - lastK) * 1.5, 95);
    } else if (lastK > lastD && lastK < 80) {
        signal = 'Bullish';
        confidence = 55;
    } else if (lastK < lastD && lastK > 20) {
        signal = 'Bearish';
        confidence = 55;
    }

    return {
        name: meta.name, signal, confidence: Math.round(confidence),
        detail: `%K: ${lastK.toFixed(1)} | %D: ${lastD.toFixed(1)}`,
    };
}
