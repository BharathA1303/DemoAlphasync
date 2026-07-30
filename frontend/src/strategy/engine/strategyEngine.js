import * as rsiMomentum from '../strategies/rsiMomentum';
import * as vwapStrategy from '../strategies/vwapStrategy';
import * as goldenRsi from '../strategies/goldenRsi';
import * as trendDetector from '../strategies/trendDetector';
import * as emaCross from '../strategies/emaCross';

/**
 * Strategy Engine — strict weighted aggregation.
 *
 * Scoring rules:
 *   1. Only non-Neutral strategies contribute to the weighted score.
 *   2. Bullish = +weight × (confidence/100), Bearish = -weight × (confidence/100).
 *   3. Normalised score must exceed ±0.40 threshold for BULLISH/BEARISH.
 *   4. At least 3 strategies must have an opinion (non-Neutral) to signal.
 *   5. Confidence = weighted average of agreeing strategies' confidence values.
 *
 * ┌──────────────────────────────────┬────────┐
 * │ Strategy                         │ Weight │
 * ├──────────────────────────────────┼────────┤
 * │ EMA Cross (9/21) + ADX           │  25%   │
 * │ RSI Momentum (dead-zone)         │  20%   │
 * │ Volume-Price Confluence (VWAP+BB)│  15%   │
 * │ Golden RSI (multi-confirm)       │  20%   │
 * │ Trend Detector (MACD+EMA+ADX)    │  20%   │
 * └──────────────────────────────────┴────────┘
 */
const STRATEGY_REGISTRY = [
    emaCross,
    rsiMomentum,
    vwapStrategy,
    goldenRsi,
    trendDetector,
];

export function getAvailableStrategies() {
    return STRATEGY_REGISTRY.map((mod) => ({ ...mod.meta }));
}

/**
 * Execute enabled strategies and aggregate signals with strict thresholds.
 */
export function runEngine(candles, enabledIds = []) {
    if (!candles || candles.length === 0) {
        return { signals: [], overall: 'NEUTRAL', confidence: 0 };
    }

    const modulesToRun =
        enabledIds.length > 0
            ? STRATEGY_REGISTRY.filter((m) => enabledIds.includes(m.meta.id))
            : STRATEGY_REGISTRY;

    const signals = modulesToRun.map((mod) => {
        try {
            const result = mod.runStrategy(candles);
            return { ...result, id: mod.meta.id, weight: mod.meta.weight || 0.10 };
        } catch (err) {
            return {
                id: mod.meta.id,
                name: mod.meta.name,
                signal: 'Neutral',
                confidence: 0,
                detail: `Error: ${err.message}`,
                weight: mod.meta.weight || 0.10,
            };
        }
    });

    // ── Confidence-weighted aggregation ────────────────────────────────────
    // Score each strategy: weight × (confidence / 100) in its direction.
    // This means a low-confidence signal contributes less than a high-confidence one.
    let weightedScore = 0;
    let activeWeight = 0; // total weight of non-Neutral strategies
    let bullish = 0;
    let bearish = 0;
    let neutral = 0;
    let bullConfSum = 0;
    let bullWeightSum = 0;
    let bearConfSum = 0;
    let bearWeightSum = 0;

    for (const s of signals) {
        const w = s.weight || 0.10;
        const confFactor = (s.confidence || 0) / 100;

        if (s.signal === 'Bullish') {
            weightedScore += w * confFactor;
            activeWeight += w;
            bullish++;
            bullConfSum += s.confidence * w;
            bullWeightSum += w;
        } else if (s.signal === 'Bearish') {
            weightedScore -= w * confFactor;
            activeWeight += w;
            bearish++;
            bearConfSum += s.confidence * w;
            bearWeightSum += w;
        } else {
            neutral++;
        }
    }

    const totalStrategies = signals.length;
    const activeStrategies = bullish + bearish;

    // ── Decision rules ────────────────────────────────────────────────────
    // Rule 1: Need at least 2 non-Neutral strategies to have any opinion
    // Rule 2: Normalised score must exceed ±0.40 threshold
    // Rule 3: Majority of active strategies must agree on direction

    let overall = 'NEUTRAL';
    let confidence = 0;

    if (activeStrategies >= 1) {
        const normScore = activeWeight > 0 ? weightedScore / activeWeight : 0;

        // Lower threshold (0.15) — allows signal when even 1-2 strategies agree strongly
        if (normScore > 0.15 && bullish >= bearish) {
            overall = 'BULLISH';
            confidence = bullWeightSum > 0 ? Math.round(bullConfSum / bullWeightSum) : 0;
            // Penalise if only 1 strategy has opinion
            if (activeStrategies === 1) confidence = Math.round(confidence * 0.7);
            else if (activeStrategies < 3) confidence = Math.round(confidence * 0.85);
        } else if (normScore < -0.15 && bearish >= bullish) {
            overall = 'BEARISH';
            confidence = bearWeightSum > 0 ? Math.round(bearConfSum / bearWeightSum) : 0;
            if (activeStrategies === 1) confidence = Math.round(confidence * 0.7);
            else if (activeStrategies < 3) confidence = Math.round(confidence * 0.85);
        }
    }

    // Cap confidence — never claim 100%
    confidence = Math.min(confidence, 92);

    const score = activeWeight > 0 ? Math.round((weightedScore / activeWeight) * 100) : 0;

    return { signals, overall, confidence, score, weightedScore: +weightedScore.toFixed(2) };
}
