import { cci as calcCci } from '../indicators';

/**
 * CCI Strategy — matches MQ4 CCI(14), Weight: 20%
 * CCI > 0 → Bullish, CCI < 0 → Bearish
 */
export const meta = {
    id: 'cci-momentum',
    name: 'CCI Momentum',
    description: 'CCI(14) zero-line momentum detector',
    category: 'Momentum',
    weight: 0.20,
};

export function runStrategy(candles) {
    if (candles.length < 16) {
        return { name: meta.name, signal: 'Neutral', confidence: 0, detail: 'Need 16+ candles' };
    }

    const cciArr = calcCci(candles, 14);
    const current = cciArr[cciArr.length - 1];

    if (isNaN(current)) {
        return { name: meta.name, signal: 'Neutral', confidence: 0, detail: 'CCI not available' };
    }

    let signal = 'Neutral';
    let confidence = 50;

    if (current > 100) {
        signal = 'Bullish'; confidence = Math.min(70 + (current - 100) * 0.15, 95);
    } else if (current > 0) {
        signal = 'Bullish'; confidence = 55 + (current / 100) * 15;
    } else if (current < -100) {
        signal = 'Bearish'; confidence = Math.min(70 + Math.abs(current + 100) * 0.15, 95);
    } else if (current < 0) {
        signal = 'Bearish'; confidence = 55 + (Math.abs(current) / 100) * 15;
    }

    return {
        name: meta.name, signal, confidence: Math.round(confidence),
        detail: `CCI(14): ${current.toFixed(1)}`,
    };
}
