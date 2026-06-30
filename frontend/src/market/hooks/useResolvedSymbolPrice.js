import { useMemo, useSyncExternalStore } from 'react';
import { useMarketStore } from '../../store/useMarketStore';
import { useWatchlistStore } from '../../stores/useWatchlistStore';
import { resolveSymbolPrice } from '../UnifiedPriceResolver';
import { getEODQuoteCache } from '../EODReconciliationEngine';
import { marketSessionManager } from '../MarketSessionManager';

function subscribeSession(cb) {
  return marketSessionManager.subscribe(cb);
}

function getSession() {
  return marketSessionManager.getSnapshot();
}

/**
 * Session-aware resolved price for a single symbol (watchlist, header, cards).
 */
export function useResolvedSymbolPrice(symbol, options = {}) {
  const session = useSyncExternalStore(subscribeSession, getSession, getSession);
  const liveQuotes = useMarketStore((s) => s.symbols);
  const watchlistPrices = useWatchlistStore((s) => s.prices);
  const { candleClose = null } = options;

  return useMemo(() => {
    if (!symbol) return { price: null, change: null, change_percent: null, priceSource: 'fallback' };
    return resolveSymbolPrice(symbol, {
      liveQuotes,
      watchlistPrices,
      eodQuotes: getEODQuoteCache(),
      candleClose,
    });
  }, [symbol, liveQuotes, watchlistPrices, session.fetchedAt, candleClose]);
}

export default useResolvedSymbolPrice;
