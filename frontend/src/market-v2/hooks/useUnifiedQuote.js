import { useCallback, useSyncExternalStore } from 'react';
import { unifiedQuoteAuthority } from '../UnifiedQuoteAuthority';
import { resolveFreshness, isVisuallyStale } from '../QuoteFreshnessResolver';
import { quotePriorityEngine } from '../QuotePriorityEngine';

/**
 * Resolved authoritative quote for a symbol (gradual UI migration hook).
 */
export function useUnifiedQuote(symbol) {
  const sym = String(symbol || '').trim().toUpperCase();

  const quote = useSyncExternalStore(
    (cb) => unifiedQuoteAuthority.subscribe(() => cb()),
    () => (sym ? unifiedQuoteAuthority.get(sym) : null),
    () => null,
  );

  const freshness = quote ? resolveFreshness(sym, quote) : null;
  const tier = sym ? quotePriorityEngine.getTier(sym) : null;
  const stale = quote ? isVisuallyStale(sym, quote) : false;

  const getQuote = useCallback(
    (s) => unifiedQuoteAuthority.get(String(s || '').trim().toUpperCase()),
    [],
  );

  return {
    symbol: sym,
    quote,
    freshness,
    tier,
    isStale: stale,
    heartbeat: unifiedQuoteAuthority.getLastHeartbeat(),
    getQuote,
  };
}
