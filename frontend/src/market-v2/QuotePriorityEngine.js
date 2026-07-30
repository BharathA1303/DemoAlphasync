/**
 * Client-side symbol priority overlay (does not replace WS subscriptions).
 */
import { TICKER_HOT_SYMBOLS } from './tickerHotSymbols';

export const PriorityTier = {
  HOT: 'hot',
  WARM: 'warm',
  COLD: 'cold',
};

const TIER_RANK = { hot: 0, warm: 1, cold: 2 };

class QuotePriorityEngine {
  constructor() {
    this._tiers = new Map();
    for (const sym of TICKER_HOT_SYMBOLS) {
      this._tiers.set(String(sym).toUpperCase(), PriorityTier.HOT);
    }
  }

  register(symbol, tier) {
    const sym = String(symbol || '').trim().toUpperCase();
    if (!sym) return;
    const prev = this._tiers.get(sym);
    if (!prev || TIER_RANK[tier] < TIER_RANK[prev]) {
      this._tiers.set(sym, tier);
    }
  }

  registerHot(symbol) {
    this.register(symbol, PriorityTier.HOT);
  }

  registerWarm(symbol) {
    this.register(symbol, PriorityTier.WARM);
  }

  getTier(symbol) {
    const sym = String(symbol || '').trim().toUpperCase();
    return this._tiers.get(sym) || PriorityTier.COLD;
  }

  isHot(symbol) {
    return this.getTier(symbol) === PriorityTier.HOT;
  }
}

export const quotePriorityEngine = new QuotePriorityEngine();
