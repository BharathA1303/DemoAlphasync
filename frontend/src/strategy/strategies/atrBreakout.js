import { atr as calcAtr } from '../indicators';

/**
 * ATR Breakout Strategy — matches MQ4 CalculateATRScore()
 * Price breaks above/below previous close ± ATR × multiplier
 */
export const meta = {
    id: 'atr-breakout',
    name: 'ATR Breakout',
    description: 'ATR(14) volatility breakout detector',
    category: 'Volatility',
    weight: 0.10,
};

export function runStrategy(candles) {
    if (candles.length < 16) {
        return { name: meta.name, signal: 'Neutral', confidence: 0, detail: 'Need 16+ candles' };
    }

    const atrArr = calcAtr(candles, 14);
    const lastAtr = atrArr[atrArr.length - 1];
    const lastClose = candles[candles.length - 1].close;
    const prevClose = candles[candles.length - 2].close;

    if (isNaN(lastAtr)) {
        return { name: meta.name, signal: 'Neutral', confidence: 0, detail: 'ATR data incomplete' };
    }

    const multiplier = 2.0;
    const breakoutUp = lastClose > prevClose + lastAtr * multiplier;
    const breakoutDown = lastClose < prevClose - lastAtr * multiplier;
    const atrPercent = (lastAtr / lastClose) * 100;

    let signal = 'Neutral';
    let confidence = 50;

    if (breakoutUp) {
        signal = 'Bullish';
        confidence = Math.min(75 + atrPercent * 3, 95);
    } else if (breakoutDown) {
        signal = 'Bearish';
        confidence = Math.min(75 + atrPercent * 3, 95);
    }

    return {
        name: meta.name, signal, confidence: Math.round(confidence),
        detail: `ATR(14): ${lastAtr.toFixed(2)} | ATR%: ${atrPercent.toFixed(2)}% | Threshold: ±${(lastAtr * multiplier).toFixed(2)}`,
    };
}
