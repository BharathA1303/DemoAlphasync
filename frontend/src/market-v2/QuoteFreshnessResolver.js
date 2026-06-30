/**
 * Classify quote freshness for soft UI markers (no aggressive flashing).
 */
import { shouldUseRealtimePrices } from '../market/utils/marketSessionUtils';
import { quotePriorityEngine, PriorityTier } from './QuotePriorityEngine';

export const FreshnessState = {
  LIVE: 'LIVE',
  DELAYED: 'DELAYED',
  STALE: 'STALE',
  FROZEN: 'FROZEN',
  EOD: 'EOD',
};

const parseTs = (quote) => {
  const raw = quote?.exchange_timestamp ?? quote?.timestamp ?? quote?.last_trade_time;
  if (!raw) return Date.now();
  const n = Number(raw);
  if (Number.isFinite(n) && n > 1e9) return n > 1e12 ? n : n * 1000;
  const d = Date.parse(raw);
  return Number.isFinite(d) ? d : Date.now();
};

export function resolveFreshness(symbol, quote = {}) {
  const source = String(quote.source || quote._source || '').toLowerCase();
  if (source === 'eod' || quote.freshness_state === 'EOD') {
    return FreshnessState.EOD;
  }
  if (!shouldUseRealtimePrices()) {
    return FreshnessState.FROZEN;
  }

  if (quote.freshness_state) {
    return quote.freshness_state;
  }

  const ageSec = (Date.now() - parseTs(quote)) / 1000;
  const tier = quote.priority_tier || quotePriorityEngine.getTier(symbol);

  let liveLimit = 2;
  let delayLimit = 8;
  if (tier === PriorityTier.WARM) {
    liveLimit = 4;
    delayLimit = 20;
  } else if (tier === PriorityTier.COLD) {
    liveLimit = 15;
    delayLimit = 45;
  }

  if (ageSec <= liveLimit) return FreshnessState.LIVE;
  if (ageSec <= delayLimit) return FreshnessState.DELAYED;
  return FreshnessState.STALE;
}

export function isVisuallyStale(symbol, quote) {
  const state = resolveFreshness(symbol, quote);
  return state === FreshnessState.STALE || state === FreshnessState.FROZEN;
}
