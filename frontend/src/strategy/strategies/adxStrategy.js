import { adx as calcAdx } from '../indicators';

/**
 * ADX Trend Strength Strategy — matches MQ4 ADX(14), Weight: 10%
 * ADX > 20 && +DI > -DI → Bullish
 * ADX > 20 && -DI > +DI → Bearish
 */
export const meta = {
    id: 'adx-trend',
    name: 'ADX Trend',
    description: 'ADX(14) trend strength with DI± directional filter',
    category: 'Trend',
    weight: 0.10,
};

export function runStrategy(candles) {
    if (candles.length < 30) {
        return { name: meta.name, signal: 'Neutral', confidence: 0, detail: 'Need 30+ candles' };
    }

    const { adx, plusDI, minusDI } = calcAdx(candles, 14);
    const lastAdx = adx[adx.length - 1];
    const lastPlus = plusDI[plusDI.length - 1];
    const lastMinus = minusDI[minusDI.length - 1];

    if ([lastAdx, lastPlus, lastMinus].some(isNaN)) {
        return { name: meta.name, signal: 'Neutral', confidence: 0, detail: 'ADX data incomplete' };
    }

    let signal = 'Neutral';
    let confidence = 50;
    const detail = `ADX: ${lastAdx.toFixed(1)} | +DI: ${lastPlus.toFixed(1)} | -DI: ${lastMinus.toFixed(1)}`;

    if (lastAdx > 20 && lastPlus > lastMinus) {
        signal = 'Bullish';
        confidence = Math.min(55 + (lastAdx - 20) * 1.2, 92);
    } else if (lastAdx > 20 && lastMinus > lastPlus) {
        signal = 'Bearish';
        confidence = Math.min(55 + (lastAdx - 20) * 1.2, 92);
    }

    return { name: meta.name, signal, confidence: Math.round(confidence), detail };
}
