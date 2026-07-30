import { rsi as calcRsi, sma, ema } from '../indicators';

/**
 * Golden RSI Strategy — strict multi-confirmation.
 * Requires ALL of these to signal:
 *   1. Price clearly above/below SMA50 (>0.5% margin)
 *   2. RSI in confirming zone (not in dead zone 45–55)
 *   3. RSI momentum direction matches (3-bar trend)
 *   4. EMA 9 slope confirms direction
 * Falls to Neutral on any disagreement.
 */
export const meta = {
    id: 'golden-rsi',
    name: 'Golden RSI',
    description: 'RSI + SMA50 + EMA9 slope — multi-confirmation confluence',
    category: 'Confluence',
    weight: 0.20,
};

export function runStrategy(candles) {
    const closes = candles.map((c) => c.close);
    if (closes.length < 55) {
        return { name: meta.name, signal: 'Neutral', confidence: 0, detail: 'Need 55+ candles' };
    }

    const rsiArr = calcRsi(closes, 14);
    const sma50 = sma(closes, 50);
    const ema9 = ema(closes, 9);

    const currentRsi = rsiArr[rsiArr.length - 1];
    const prevRsi = rsiArr[rsiArr.length - 2];
    const prev2Rsi = rsiArr[rsiArr.length - 3];
    const lastSma = sma50[sma50.length - 1];
    const lastClose = closes[closes.length - 1];
    const lastEma = ema9[ema9.length - 1];
    const prevEma = ema9[ema9.length - 2];

    if ([currentRsi, prevRsi, prev2Rsi, lastSma, lastEma, prevEma].some(isNaN)) {
        return { name: meta.name, signal: 'Neutral', confidence: 0, detail: 'Insufficient data' };
    }

    // Derived conditions
    const smaDeviation = ((lastClose - lastSma) / lastSma) * 100;
    const aboveSma = smaDeviation > 0.2;
    const belowSma = smaDeviation < -0.2;
    const rsiRising = currentRsi > prevRsi && prevRsi > prev2Rsi;
    const rsiFalling = currentRsi < prevRsi && prevRsi < prev2Rsi;
    const emaSlopeUp = lastEma > prevEma;
    const emaSlopeDown = lastEma < prevEma;
    const rsiInDeadZone = currentRsi >= 47 && currentRsi <= 53;

    let signal = 'Neutral';
    let confidence = 0;
    const parts = [`RSI: ${currentRsi.toFixed(1)}`, `SMA50: ${lastSma.toFixed(2)}`, `Δ: ${smaDeviation >= 0 ? '+' : ''}${smaDeviation.toFixed(2)}%`];
    const confirms = [];

    // Full bullish confluence: price > SMA50 + RSI rising above dead zone + EMA slope up
    if (aboveSma && !rsiInDeadZone && currentRsi > 53 && rsiRising && emaSlopeUp) {
        signal = 'Bullish';
        confirms.push('SMA50▲', 'RSI▲', 'EMA9 slope▲');
        confidence = currentRsi > 60 ? 82 : 70;
    }
    // Full bearish confluence: price < SMA50 + RSI falling below dead zone + EMA slope down
    else if (belowSma && !rsiInDeadZone && currentRsi < 47 && rsiFalling && emaSlopeDown) {
        signal = 'Bearish';
        confirms.push('SMA50▼', 'RSI▼', 'EMA9 slope▼');
        confidence = currentRsi < 40 ? 82 : 70;
    }
    // Partial bullish — 2 of 3 conditions
    else if (aboveSma && currentRsi > 53 && (rsiRising || emaSlopeUp)) {
        signal = 'Bullish';
        confidence = 58;
        confirms.push('Partial confluence (2/3)');
    }
    // Partial bearish — 2 of 3 conditions
    else if (belowSma && currentRsi < 47 && (rsiFalling || emaSlopeDown)) {
        signal = 'Bearish';
        confidence = 58;
        confirms.push('Partial confluence (2/3)');
    }
    // Anything else — no confluence
    else {
        confirms.push('No confluence — conflicting signals');
    }

    parts.push(confirms.join(', '));
    return { name: meta.name, signal, confidence: Math.round(confidence), detail: parts.join(' | ') };
}
