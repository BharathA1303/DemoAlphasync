import { ema } from '../indicators';
import { adx as calcAdx } from '../indicators';

/**
 * EMA Cross Strategy — EMA(9) vs EMA(21) with ADX trend-strength filter.
 * Only signals on crossovers or when spread > 0.3% AND ADX confirms trend.
 * Stays Neutral when EMAs are tangled or trend is weak.
 */
export const meta = {
    id: 'ema-cross',
    name: 'EMA Cross (9/21)',
    description: 'EMA 9/21 crossover with ADX trend filter',
    category: 'Trend',
    weight: 0.25,
};

export function runStrategy(candles) {
    const closes = candles.map((c) => c.close);
    if (closes.length < 30) {
        return { name: meta.name, signal: 'Neutral', confidence: 0, detail: 'Need 30+ candles' };
    }

    const fast = ema(closes, 9);
    const slow = ema(closes, 21);
    const { adx: adxArr } = calcAdx(candles, 14);

    const lastFast = fast[fast.length - 1];
    const lastSlow = slow[slow.length - 1];
    const prevFast = fast[fast.length - 2];
    const prevSlow = slow[slow.length - 2];
    const lastAdx = adxArr[adxArr.length - 1];

    if (isNaN(lastFast) || isNaN(lastSlow)) {
        return { name: meta.name, signal: 'Neutral', confidence: 0, detail: 'Insufficient data' };
    }

    const spread = ((lastFast - lastSlow) / lastSlow) * 100;
    const absSpread = Math.abs(spread);
    const crossUp = prevFast <= prevSlow && lastFast > lastSlow;
    const crossDown = prevFast >= prevSlow && lastFast < lastSlow;
    const adxValid = !isNaN(lastAdx);
    const strongTrend = adxValid && lastAdx > 20;
    const veryStrongTrend = adxValid && lastAdx > 30;

    let signal = 'Neutral';
    let confidence = 0;
    let detail = `EMA9: ${lastFast.toFixed(2)} | EMA21: ${lastSlow.toFixed(2)}`;
    if (adxValid) detail += ` | ADX: ${lastAdx.toFixed(1)}`;

    // Fresh crossover — high conviction regardless of ADX
    if (crossUp) {
        signal = 'Bullish';
        confidence = strongTrend ? 88 : 72;
        detail += ' — Bullish crossover';
    } else if (crossDown) {
        signal = 'Bearish';
        confidence = strongTrend ? 88 : 72;
        detail += ' — Bearish crossover';
    }
    // Sustained trend — spread > 0.15% AND ADX confirms
    else if (absSpread > 0.15 && strongTrend) {
        signal = spread > 0 ? 'Bullish' : 'Bearish';
        confidence = veryStrongTrend
            ? Math.min(60 + absSpread * 4, 82)
            : Math.min(55 + absSpread * 3, 72);
        detail += ` | Spread: ${spread >= 0 ? '+' : ''}${spread.toFixed(2)}%`;
    }
    // Moderate trend — spread meaningful but ADX not confirming strongly
    else if (absSpread > 0.15) {
        signal = spread > 0 ? 'Bullish' : 'Bearish';
        confidence = Math.min(45 + absSpread * 2, 55);
        detail += ` | Spread: ${spread >= 0 ? '+' : ''}${spread.toFixed(2)}% — Moderate trend`;
    }
    // Otherwise — EMAs are tangled → Neutral
    else {
        detail += ` | Spread: ${spread >= 0 ? '+' : ''}${spread.toFixed(2)}% — No clear trend`;
    }

    return { name: meta.name, signal, confidence: Math.round(confidence), detail };
}
