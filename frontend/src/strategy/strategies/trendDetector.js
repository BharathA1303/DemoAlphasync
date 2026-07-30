import { macd as calcMacd, ema, atr } from '../indicators';
import { adx as calcAdx } from '../indicators';

/**
 * Trend Detector Strategy — strict multi-signal confirmation.
 * Requires MACD + EMA21 + ADX to ALL agree before signalling.
 * When indicators conflict (e.g. above EMA but MACD negative) → Neutral.
 * Uses ADX > 20 as a trend-existence filter.
 */
export const meta = {
    id: 'trend-detector',
    name: 'Trend Detector',
    description: 'MACD + EMA21 + ADX — triple-confirmation trend engine',
    category: 'Trend',
    weight: 0.20,
};

export function runStrategy(candles) {
    const closes = candles.map((c) => c.close);
    if (closes.length < 40) {
        return { name: meta.name, signal: 'Neutral', confidence: 0, detail: 'Need 40+ candles' };
    }

    const { macd: macdLine, histogram } = calcMacd(closes);
    const ema21 = ema(closes, 21);
    const { adx: adxArr, plusDI, minusDI } = calcAdx(candles, 14);

    const lastMacd = macdLine[macdLine.length - 1];
    const lastHist = histogram[histogram.length - 1];
    const prevHist = histogram[histogram.length - 2];
    const prev2Hist = histogram[histogram.length - 3];
    const lastEma = ema21[ema21.length - 1];
    const lastClose = closes[closes.length - 1];
    const lastAdx = adxArr[adxArr.length - 1];
    const lastPlusDI = plusDI[plusDI.length - 1];
    const lastMinusDI = minusDI[minusDI.length - 1];

    if ([lastMacd, lastHist, prevHist, lastEma].some(isNaN)) {
        return { name: meta.name, signal: 'Neutral', confidence: 0, detail: 'Indicator data incomplete' };
    }

    const emaDeviation = ((lastClose - lastEma) / lastEma) * 100;
    const aboveEma = emaDeviation > 0.1;
    const belowEma = emaDeviation < -0.1;
    const macdPositive = lastMacd > 0;
    const macdNegative = lastMacd < 0;
    const histExpanding = Math.abs(lastHist) > Math.abs(prevHist) && Math.abs(prevHist) > Math.abs(prev2Hist);
    const adxValid = !isNaN(lastAdx);
    const trendExists = adxValid && lastAdx > 15;
    const strongTrend = adxValid && lastAdx > 25;
    const diConfirmsBull = !isNaN(lastPlusDI) && !isNaN(lastMinusDI) && lastPlusDI > lastMinusDI;
    const diConfirmsBear = !isNaN(lastPlusDI) && !isNaN(lastMinusDI) && lastMinusDI > lastPlusDI;

    let signal = 'Neutral';
    let confidence = 0;
    const details = [];

    // All three agree + ADX confirms trend exists
    if (aboveEma && macdPositive && trendExists && diConfirmsBull) {
        signal = 'Bullish';
        if (strongTrend && histExpanding) {
            confidence = 88;
            details.push('Strong accelerating uptrend');
        } else if (strongTrend || histExpanding) {
            confidence = 75;
            details.push('Confirmed uptrend');
        } else {
            confidence = 65;
            details.push('Developing uptrend');
        }
    } else if (belowEma && macdNegative && trendExists && diConfirmsBear) {
        signal = 'Bearish';
        if (strongTrend && histExpanding) {
            confidence = 88;
            details.push('Strong accelerating downtrend');
        } else if (strongTrend || histExpanding) {
            confidence = 75;
            details.push('Confirmed downtrend');
        } else {
            confidence = 65;
            details.push('Developing downtrend');
        }
    }
    // Partial agreement — only if 2/3 align with ADX
    else if (trendExists && ((aboveEma && macdPositive) || (aboveEma && diConfirmsBull) || (macdPositive && diConfirmsBull))) {
        signal = 'Bullish';
        confidence = 55;
        details.push('Partial bullish alignment');
    } else if (trendExists && ((belowEma && macdNegative) || (belowEma && diConfirmsBear) || (macdNegative && diConfirmsBear))) {
        signal = 'Bearish';
        confidence = 55;
        details.push('Partial bearish alignment');
    }
    // No trend (ADX < 20) or conflicting signals
    else {
        details.push(adxValid && lastAdx <= 20 ? 'No trend (ADX too low)' : 'Conflicting signals');
    }

    details.push(`MACD: ${lastMacd.toFixed(2)}`);
    details.push(`EMA21: ${lastEma.toFixed(2)}`);
    if (adxValid) details.push(`ADX: ${lastAdx.toFixed(1)}`);

    return { name: meta.name, signal, confidence: Math.round(confidence), detail: details.join(' | ') };
}
