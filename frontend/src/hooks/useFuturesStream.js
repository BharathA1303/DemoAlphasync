/**
 * Futures stream hook — broker-grade tiered WebSocket priority system.
 *
 * THREE TIERS:
 * - HOT:  Selected chart contract, near expiry, open positions, active orders
 *         → Always WS-subscribed, tick-by-tick, instant updates
 * - WARM: Mid expiry, visible watchlist contracts not in HOT
 *         → WS-subscribed, medium-priority updates
 * - COLD: Far expiry, illiquid contracts
 *         → REST batch refresh every 30-60s, UI shows "delayed" indicator
 *
 * NO ARTIFICIAL CAP on HOT/WARM subscriptions.
 * Selected contract and near expiry NEVER lose realtime.
 */

import { useEffect, useRef, useCallback, useMemo } from 'react';
import useUnifiedFuturesStore from '../stores/useUnifiedFuturesStore';
import { useFuturesWatchlistStore } from '../stores/useFuturesWatchlistStore';
import { futuresWsSend } from '../services/futuresWsBridge';
import { useMarketStore } from '../store/useMarketStore';
import api from '../services/api';
import { shouldUseRealtimePrices } from '../market/utils/marketSessionUtils';

const COLD_REFRESH_NEAR_MS = 4_000;
const COLD_REFRESH_FAR_MS = 10_000;
const COLD_BATCH_SIZE = 40;

function buildNearContractSymbols(state) {
  const underlying = state.contracts.selectedUnderlying;
  if (!underlying) return [];
  const symbols = state.contracts.byUnderlying[underlying] || [];
  const contracts = symbols
    .map((sym) => state.contracts.bySymbol[sym])
    .filter(Boolean)
    .sort((a, b) => new Date(a.expiry_date || 0) - new Date(b.expiry_date || 0));
  return contracts.slice(0, 3).map((c) => c.contract_symbol);
}

function classifyContracts(state, watchlistSymbols, positionSymbols, nearSymbols) {
  const hot = new Set();
  const warm = new Set();

  // HOT: selected chart contract (always realtime, non-negotiable)
  if (state.contracts.selectedContract) hot.add(state.contracts.selectedContract);

  // HOT: near expiry contracts (first 2-3 of selected underlying)
  if (nearSymbols) nearSymbols.split('|').filter(Boolean).forEach((s) => hot.add(s));

  // HOT: open position contracts (must track PnL tick-by-tick)
  if (positionSymbols) positionSymbols.split('|').filter(Boolean).forEach((s) => hot.add(s));

  // HOT: active (open) order contracts — need instant fill detection
  const openOrders = state.orders.filter((o) => o.status === 'OPEN' || o.status === 'PENDING');
  for (const o of openOrders) {
    if (o.contract_symbol) hot.add(o.contract_symbol);
  }

  // WARM: watchlist contracts not already in HOT
  if (watchlistSymbols) {
    watchlistSymbols.split('|').filter(Boolean).forEach((s) => {
      if (!hot.has(s)) warm.add(s);
    });
  }

  // WARM: all expiries for selected underlying (right panel ladder — not watchlist-only)
  const underlying = state.contracts.selectedUnderlying;
  if (underlying) {
    const ladderSymbols = state.contracts.byUnderlying[underlying] || [];
    ladderSymbols.forEach((s) => {
      if (s && !hot.has(s)) warm.add(s);
    });
  }

  return { hot: [...hot], warm: [...warm] };
}

export function useFuturesStream() {
  const subscribedRef = useRef(new Set());
  const bootstrappedRef = useRef(false);

  const selectedContract = useUnifiedFuturesStore((s) => s.contracts.selectedContract);
  const orders = useUnifiedFuturesStore((s) => s.orders);
  const watchlistSymbols = useFuturesWatchlistStore((s) => {
    const active = s.watchlists.find((w) => w.id === s.activeId);
    return (active?.items ?? []).map((item) => item.contract_symbol).filter(Boolean).join('|');
  });
  const positionSymbols = useUnifiedFuturesStore((s) =>
    s.positions
      .filter((p) => Number(p.quantity) !== 0)
      .map((p) => p.contract_symbol)
      .filter(Boolean)
      .join('|'),
  );
  const nearSymbols = useUnifiedFuturesStore((s) => {
    const near = buildNearContractSymbols(s);
    return near.join('|');
  });
  const allUnderlyingSymbols = useUnifiedFuturesStore((s) => {
    const underlying = s.contracts.selectedUnderlying;
    if (!underlying) return '';
    return (s.contracts.byUnderlying[underlying] || []).join('|');
  });
  const wsStatus = useMarketStore((s) => s.wsStatus);

  const subscribe = useCallback((contract) => {
    if (!contract || subscribedRef.current.has(contract)) return;
    subscribedRef.current.add(contract);
    futuresWsSend({ type: 'subscribe_futures', contract });
  }, []);

  const unsubscribe = useCallback((contract) => {
    if (!contract || !subscribedRef.current.has(contract)) return;
    subscribedRef.current.delete(contract);
    futuresWsSend({ type: 'unsubscribe_futures', contract });
  }, []);

  // Classify into HOT + WARM (WS) vs COLD (REST)
  const { hotContracts, warmContracts, coldContracts } = useMemo(() => {
    const state = useUnifiedFuturesStore.getState();
    const { hot, warm } = classifyContracts(state, watchlistSymbols, positionSymbols, nearSymbols);

    const wsSet = new Set([...hot, ...warm]);
    const all = allUnderlyingSymbols ? allUnderlyingSymbols.split('|').filter(Boolean) : [];
    const cold = all.filter((s) => !wsSet.has(s));

    return { hotContracts: hot, warmContracts: warm, coldContracts: cold };
  }, [selectedContract, watchlistSymbols, positionSymbols, nearSymbols, allUnderlyingSymbols, orders]);

  // All WS-subscribed contracts (HOT + WARM) — NO artificial cap
  const wsContracts = useMemo(() => {
    return [...new Set([...hotContracts, ...warmContracts])];
  }, [hotContracts, warmContracts]);

  // One-time REST bootstrap for orders / positions / margin
  useEffect(() => {
    if (bootstrappedRef.current) return;
    bootstrappedRef.current = true;

    (async () => {
      try {
        const [ordersRes, positionsRes, marginRes] = await Promise.allSettled([
          api.get('/futures/orders'),
          api.get('/futures/positions'),
          api.get('/futures/margin'),
        ]);
        const store = useUnifiedFuturesStore.getState();
        if (ordersRes.status === 'fulfilled') {
          store.setOrders(ordersRes.value.data?.orders ?? []);
        }
        if (positionsRes.status === 'fulfilled') {
          store.setPositions(positionsRes.value.data?.positions ?? []);
          store.recalculateLivePnl();
        }
        if (marginRes.status === 'fulfilled' && marginRes.value.data) {
          store.updateMargin(marginRes.value.data);
        }
      } catch {
        // best-effort
      }
    })();
  }, []);

  // Sync WS subscriptions — HOT + WARM always subscribed, no cap
  useEffect(() => {
    const desired = new Set(wsContracts);

    for (const sym of desired) {
      if (!subscribedRef.current.has(sym)) subscribe(sym);
    }
    for (const sym of [...subscribedRef.current]) {
      if (!desired.has(sym)) unsubscribe(sym);
    }
  }, [wsContracts, subscribe, unsubscribe]);

  // Bootstrap REST quotes for entire expiry ladder (independent of watchlist)
  useEffect(() => {
    const symbols = allUnderlyingSymbols ? allUnderlyingSymbols.split('|').filter(Boolean) : [];
    if (symbols.length === 0) return;

    let cancelled = false;

    const fetchLadderQuotes = async () => {
      for (let i = 0; i < symbols.length; i += COLD_BATCH_SIZE) {
        if (cancelled) return;
        const chunk = symbols.slice(i, i + COLD_BATCH_SIZE);
        try {
          const res = await api.post('/futures/quotes/batch', { contracts: chunk });
          if (cancelled) return;
          const quotes = res.data?.quotes ?? {};
          if (Object.keys(quotes).length > 0) {
            useUnifiedFuturesStore.getState().updateQuotes(quotes);
          }
        } catch {
          // non-fatal
        }
      }
    };

    fetchLadderQuotes();
    const pollMs = shouldUseRealtimePrices() ? 5_000 : 30_000;
    const interval = setInterval(fetchLadderQuotes, pollMs);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [allUnderlyingSymbols]);

  // COLD tier: Adaptive REST refresh for far-expiry / illiquid contracts
  // Near-cold (< 30 days): refresh every 15s (still active, just not WS-subscribed)
  // Far-cold (> 30 days): refresh every 45s (truly illiquid, save bandwidth)
  useEffect(() => {
    if (!coldContracts.length) return;

    let cancelled = false;

    // Classify cold contracts by days to expiry
    const classifyCold = () => {
      const store = useUnifiedFuturesStore.getState();
      const nearCold = [];
      const farCold = [];

      for (const sym of coldContracts) {
        const contract = store.contracts.bySymbol[sym];
        const daysToExpiry = contract?.days_to_expiry;
        if (daysToExpiry != null && daysToExpiry <= 30) {
          nearCold.push(sym);
        } else {
          farCold.push(sym);
        }
      }
      return { nearCold, farCold };
    };

    const refreshBatch = async (contracts, tier) => {
      if (cancelled || contracts.length === 0) return;
      try {
        const res = await api.post('/futures/quotes/batch', {
          contracts: contracts.slice(0, COLD_BATCH_SIZE),
        });
        if (cancelled) return;
        const quotes = res.data?.quotes ?? {};
        if (Object.keys(quotes).length > 0) {
          const store = useUnifiedFuturesStore.getState();
          const markedQuotes = {};
          for (const [sym, q] of Object.entries(quotes)) {
            const volume = Number(q.volume || 0);
            const isIlliquid = volume < 100;
            markedQuotes[sym] = {
              ...q,
              _tier: tier,
              _refreshedAt: Date.now(),
              _illiquid: isIlliquid,
            };
          }
          store.updateQuotes(markedQuotes);
          useFuturesWatchlistStore.getState().updatePrices(quotes);
        }
      } catch {
        // non-fatal
      }
    };

    // Initial refresh for all cold
    const { nearCold, farCold } = classifyCold();
    refreshBatch(nearCold, 'cold-near');
    refreshBatch(farCold, 'cold-far');

    // Near-cold: faster refresh
    const nearInterval = setInterval(() => {
      if (cancelled) return;
      const { nearCold } = classifyCold();
      refreshBatch(nearCold, 'cold-near');
    }, COLD_REFRESH_NEAR_MS);

    // Far-cold: slower refresh
    const farInterval = setInterval(() => {
      if (cancelled) return;
      const { farCold } = classifyCold();
      refreshBatch(farCold, 'cold-far');
    }, COLD_REFRESH_FAR_MS);

    return () => {
      cancelled = true;
      clearInterval(nearInterval);
      clearInterval(farInterval);
    };
  }, [coldContracts.join('|'), wsStatus]);

  // Cleanup subscriptions on unmount
  useEffect(() => {
    return () => {
      for (const sym of subscribedRef.current) {
        futuresWsSend({ type: 'unsubscribe_futures', contract: sym });
      }
      subscribedRef.current.clear();
    };
  }, []);

  return {
    isConnected: wsStatus === 'connected',
    isStale: wsStatus === 'error',
    subscribe,
    unsubscribe,
    hotContracts,
    warmContracts,
    coldContracts,
  };
}

export default useFuturesStream;
