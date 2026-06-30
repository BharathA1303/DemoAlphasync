import { vwap as calcVwap } from '../indicators';
import { bollingerBands } from '../indicators';

/**
 * Volume-Price Confluence Strategy
 * Uses VWAP + Bollinger Band position for institutional bias.
 * On daily+ timeframes, VWAP alone is unreliable, so BB position
 * is used as a confirmation filter.
 * Wider dead zone (1%) and requires BB confirmation.
 */
export const meta = {
    id: 'vwap-bias',
    name: 'Volume-Price Confluence',
    description: 'VWAP + Bollinger Bands — institutional fair-value with volatility filter',
    category: 'Volume',
    weight: 0.15,
};

export function runStrategy(candles) {
    if (candles.length < 25) {
        return { name: meta.name, signal: 'Neutral', confidence: 0, detail: 'Need 25+ candles' };
    }

    const closes = candles.map((c) => c.close);
    const lastClose = closes[closes.length - 1];

    // VWAP analysis
    const vwapArr = calcVwap(candles);
    const lastVwap = vwapArr[vwapArr.length - 1];
    const vwapDeviation = isNaN(lastVwap) ? 0 : ((lastClose - lastVwap) / lastVwap) * 100;

    // Bollinger Bands analysis — where is price within the bands?
    const { upper, middle, lower } = bollingerBands(closes, 20, 2);
    const lastUpper = upper[upper.length - 1];
    const lastMiddle = middle[middle.length - 1];
    const lastLower = lower[lower.length - 1];

    if ([lastUpper, lastMiddle, lastLower].some(isNaN)) {
        return { name: meta.name, signal: 'Neutral', confidence: 0, detail: 'Insufficient data' };
    }

    const bbRange = lastUpper - lastLower;
    const bbPosition = bbRange > 0 ? (lastClose - lastLower) / bbRange : 0.5; // 0=lower, 1=upper
    const aboveVwap = !isNaN(lastVwap) && vwapDeviation > 0.5;
    const belowVwap = !isNaN(lastVwap) && vwapDeviation < -0.5;

    let signal = 'Neutral';
    let confidence = 0;
    const parts = [];
    if (!isNaN(lastVwap)) parts.push(`VWAP: ${lastVwap.toFixed(2)} (${vwapDeviation >= 0 ? '+' : ''}${vwapDeviation.toFixed(2)}%)`);
    parts.push(`BB Position: ${(bbPosition * 100).toFixed(0)}%`);

    // Strong bullish: above VWAP by >1% AND in upper half of BB
    if (aboveVwap && bbPosition > 0.6) {
        signal = 'Bullish';
        confidence = bbPosition > 0.8 ? Math.min(65 + vwapDeviation * 3, 85) : 62;
        parts.push('Above VWAP + Upper BB');
    }
    // Strong bearish: below VWAP by >1% AND in lower half of BB
    else if (belowVwap && bbPosition < 0.4) {
        signal = 'Bearish';
        confidence = bbPosition < 0.2 ? Math.min(65 + Math.abs(vwapDeviation) * 3, 85) : 62;
        parts.push('Below VWAP + Lower BB');
    }
    // Near BB extremes without VWAP confirmation — mild signal
    else if (bbPosition > 0.9) {
        signal = 'Bearish';
        confidence = 52;
        parts.push('Near upper band — potential pullback');
    } else if (bbPosition < 0.1) {
        signal = 'Bullish';
        confidence = 52;
        parts.push('Near lower band — potential bounce');
    }
    // In the middle = no opinion
    else {
        parts.push('No clear bias');
    }

    return { name: meta.name, signal, confidence: Math.round(confidence), detail: parts.join(' | ') };
}
