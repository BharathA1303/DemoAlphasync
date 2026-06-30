import { useEffect, useMemo, useSyncExternalStore } from 'react';
import { useMarketIndicesStore } from '../../stores/useMarketIndicesStore';
import { useMarketStore } from '../../store/useMarketStore';
import { useWebSocket } from '../../hooks/useWebSocket';
import { resolveTickerItem } from '../UnifiedPriceResolver';
import { getEODQuoteCache } from '../EODReconciliationEngine';
import { marketSessionManager } from '../MarketSessionManager';

/** Benchmark indices — subscribed for live Zebu WS ticks (same as Market page). */
export const INDEX_WS_SYMBOLS = ['^NSEI', '^NSEBANK', '^BSESN', '^CNXIT', '^CNXFIN'];

/**
 * Live market indices: one REST bootstrap + WS merge via useMarketStore.
 */
export function useLiveMarketIndices() {
  const rawIndices = useMarketIndicesStore((s) => s.indices);
  const isLoading = useMarketIndicesStore((s) => s.isLoading);
  const fetchIndices = useMarketIndicesStore((s) => s.fetchIndices);
  const liveQuotes = useMarketStore((s) => s.symbols);
  const lastQuoteAt = useMarketStore((s) => s.lastQuoteAt);
  const { subscribe } = useWebSocket();

  useEffect(() => {
    fetchIndices();
    subscribe(INDEX_WS_SYMBOLS);
  }, [fetchIndices, subscribe]);

  const sessionTick = useSyncExternalStore(
    (cb) => marketSessionManager.subscribe(cb),
    () => marketSessionManager.getSnapshot().fetchedAt,
    () => 0,
  );

  const eodQuotes = useMemo(
    () => getEODQuoteCache(),
    [sessionTick, lastQuoteAt, rawIndices.length],
  );

  const indices = useMemo(
    () => rawIndices.map((idx) => resolveTickerItem(idx, liveQuotes, eodQuotes)),
    [rawIndices, liveQuotes, eodQuotes],
  );

  return { indices, rawIndices, isLoading };
}
