import { ichimoku as calcIchi } from '../indicators';

/**
 * Ichimoku Cloud Strategy — matches MQ4 iIchimoku(9,26,52), Weight: 20%
 * Price above cloud + Tenkan > Kijun → Bullish
 * Price below cloud + Tenkan < Kijun → Bearish
 */
export const meta = {
    id: 'ichimoku-cloud',
    name: 'Ichimoku Cloud',
    description: 'Ichimoku(9,26,52) cloud + TK cross',
    category: 'Trend',
    weight: 0.20,
};

export function runStrategy(candles) {
    if (candles.length < 55) {
        return { name: meta.name, signal: 'Neutral', confidence: 0, detail: 'Need 55+ candles' };
    }

    const { tenkan, kijun, senkouA, senkouB } = calcIchi(candles, 9, 26, 52);
    const i = candles.length - 1;
    const lastClose = candles[i].close;
    const t = tenkan[i];
    const k = kijun[i];
    const sa = senkouA[i];
    const sb = senkouB[i];

    if ([t, k, sa, sb].some(isNaN)) {
        return { name: meta.name, signal: 'Neutral', confidence: 0, detail: 'Ichimoku data incomplete' };
    }

    const cloudTop = Math.max(sa, sb);
    const cloudBottom = Math.min(sa, sb);
    const aboveCloud = lastClose > cloudTop;
    const belowCloud = lastClose < cloudBottom;
    const tkBull = t > k;
    const tkBear = t < k;

    let signal = 'Neutral';
    let confidence = 50;

    if (aboveCloud && tkBull) {
        signal = 'Bullish'; confidence = 85;
    } else if (belowCloud && tkBear) {
        signal = 'Bearish'; confidence = 85;
    } else if (aboveCloud) {
        signal = 'Bullish'; confidence = 65;
    } else if (belowCloud) {
        signal = 'Bearish'; confidence = 65;
    }

    return {
        name: meta.name, signal, confidence: Math.round(confidence),
        detail: `Tenkan: ${t.toFixed(2)} | Kijun: ${k.toFixed(2)} | Cloud: ${cloudBottom.toFixed(2)}-${cloudTop.toFixed(2)}`,
    };
}
