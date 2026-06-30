import { create } from 'zustand';
import { shallow } from 'zustand/shallow';

// ---------------------------------------------------------------------------
// Initial state — used by reset() and store creation
// ---------------------------------------------------------------------------

const INITIAL_CONNECTION = {
  status: 'disconnected',
  lastHeartbeat: null,
};

const INITIAL_CONTRACTS = {
  bySymbol: {},
  byUnderlying: {},
  selectedContract: null,
  selectedUnderlying: null,
  loading: false,
};

const INITIAL_CHART = {
  candles: [],
  liveCandle: null,
  interval: '5m',
  loading: false,
};

const INITIAL_MARGIN = {
  totalFunds: 1000000,
  usedMargin: 0,
  availableMargin: 1000000,
  exposureMargin: 0,
  unrealizedPnl: 0,
  realizedPnl: 0,
};

const INITIAL_WATCHLIST = {
  items: [],
  sortBy: 'underlying',
  sortDir: 'asc',
};

const INITIAL_STATE = {
  connection: INITIAL_CONNECTION,
  contracts: INITIAL_CONTRACTS,
  quotes: {},
  chart: INITIAL_CHART,
  positions: [],
  orders: [],
  ordersLoading: false,
  margin: INITIAL_MARGIN,
  watchlist: INITIAL_WATCHLIST,
  _lastQuoteUpdate: null,
};

const quoteLtp = (q) => {
  const n = Number(q?.ltp ?? q?.price ?? q?.lp);
  return Number.isFinite(n) ? n : null;
};

const quotesEqual = (prev, next) => {
  if (!prev && !next) return true;
  if (!prev || !next) return false;
  return (
    quoteLtp(prev) === quoteLtp(next) &&
    Number(prev.bid ?? prev.best_bid_price) === Number(next.bid ?? next.best_bid_price) &&
    Number(prev.ask ?? prev.best_ask_price) === Number(next.ask ?? next.best_ask_price) &&
    Number(prev.volume) === Number(next.volume) &&
    Number(prev.oi) === Number(next.oi) &&
    Number(prev.change ?? prev.net_change) === Number(next.change ?? next.net_change) &&
    Number(prev.change_pct ?? prev.change_percent ?? prev.pc ?? prev.percent_change) ===
      Number(next.change_pct ?? next.change_percent ?? next.pc ?? next.percent_change)
  );
};

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

const useUnifiedFuturesStore = create((set, get) => ({
  ...INITIAL_STATE,

  // =========================================================================
  // 1. CONNECTION ACTIONS
  // =========================================================================

  /**
   * @param {'connected' | 'disconnected' | 'reconnecting'} status
   */
  setConnectionStatus: (status) => {
    if (get().connection.status === status) return;
    set({ connection: { ...get().connection, status } });
  },

  /**
   * @param {number} ts — epoch ms timestamp of last heartbeat
   */
  setLastHeartbeat: (ts) => {
    const prev = get().connection.lastHeartbeat;
    if (prev != null && Math.abs(ts - prev) < 1000) return;
    set({ connection: { ...get().connection, lastHeartbeat: ts } });
  },

  // =========================================================================
  // 2. CONTRACTS ACTIONS
  // =========================================================================

  /**
   * Store a list of contracts for a given underlying.
   * Indexes each contract in `bySymbol` and groups symbols under `byUnderlying`.
   * @param {string} underlying — e.g. "NIFTY"
   * @param {Array<Object>} contractsList — array of contract objects
   */
  setContracts: (underlying, contractsList) => {
    const state = get();
    const newBySymbol = { ...state.contracts.bySymbol };
    const symbols = [];

    for (const c of contractsList) {
      newBySymbol[c.contract_symbol] = c;
      symbols.push(c.contract_symbol);
    }

    set({
      contracts: {
        ...state.contracts,
        bySymbol: newBySymbol,
        byUnderlying: {
          ...state.contracts.byUnderlying,
          [underlying]: symbols,
        },
      },
    });
  },

  /**
   * @param {string} contractSymbol — e.g. "NIFTY24APR26F"
   */
  selectContract: (contractSymbol) => {
    const sym = String(contractSymbol || '').trim().toUpperCase();
    if (!sym || get().contracts.selectedContract === sym) return;
    set({ contracts: { ...get().contracts, selectedContract: sym } });
  },

  /**
   * @param {string} symbol — underlying symbol, e.g. "NIFTY"
   */
  selectUnderlying: (symbol) => {
    const sym = String(symbol || '').trim().toUpperCase();
    if (!sym || get().contracts.selectedUnderlying === sym) return;
    set({ contracts: { ...get().contracts, selectedUnderlying: sym } });
  },

  /** @param {boolean} bool */
  setContractsLoading: (bool) => {
    if (get().contracts.loading === bool) return;
    set({ contracts: { ...get().contracts, loading: bool } });
  },

  // =========================================================================
  // 3. QUOTES ACTIONS (surgical merge — never replaces entire quotes map)
  // =========================================================================

  /**
   * Surgically update a single contract's quote via shallow merge.
   * @param {string} contractSymbol
   * @param {Object} quoteData — partial or full quote fields
   */
  updateQuote: (contractSymbol, quoteData) =>
    set((state) => {
      const sym = String(contractSymbol || '').trim().toUpperCase();
      if (!sym) return state;
      const prev = state.quotes[sym];
      const merged = { ...prev, ...quoteData };
      if (quotesEqual(prev, merged)) return state;
      return {
        quotes: { ...state.quotes, [sym]: merged },
        _lastQuoteUpdate: Date.now(),
      };
    }),

  /**
   * Batch-update multiple contract quotes. Each entry is surgically merged.
   * @param {Record<string, Object>} quotesMap — { contractSymbol: quoteData }
   */
  updateQuotes: (quotesMap) =>
    set((state) => {
      const merged = { ...state.quotes };
      let changed = false;
      for (const [sym, data] of Object.entries(quotesMap)) {
        const prev = merged[sym];
        const next = { ...prev, ...data };
        if (!quotesEqual(prev, next)) {
          merged[sym] = next;
          changed = true;
        }
      }
      if (!changed) return state;
      return { quotes: merged, _lastQuoteUpdate: Date.now() };
    }),

  // =========================================================================
  // 4. CHART ACTIONS
  // =========================================================================

  /** @param {Array<Object>} candles — historical OHLCV array */
  setCandles: (candles) =>
    set({ chart: { ...get().chart, candles } }),

  /**
   * Update or create the live (partial) candle from an incoming tick.
   * @param {Object} tick — { price, volume, timestamp, ... }
   */
  updateLiveCandle: (tick) => {
    const { chart } = get();
    const prev = chart.liveCandle;

    if (!prev || tick.timestamp !== prev.timestamp) {
      set({
        chart: {
          ...chart,
          liveCandle: {
            open: tick.price,
            high: tick.price,
            low: tick.price,
            close: tick.price,
            volume: tick.volume || 0,
            timestamp: tick.timestamp,
          },
        },
      });
      return;
    }

    set({
      chart: {
        ...chart,
        liveCandle: {
          ...prev,
          high: Math.max(prev.high, tick.price),
          low: Math.min(prev.low, tick.price),
          close: tick.price,
          volume: prev.volume + (tick.volume || 0),
        },
      },
    });
  },

  /** @param {string} interval — e.g. "1m", "5m", "15m", "1h", "1d" */
  setChartInterval: (interval) =>
    set({ chart: { ...get().chart, interval, liveCandle: null } }),

  /** @param {boolean} bool */
  setChartLoading: (bool) =>
    set({ chart: { ...get().chart, loading: bool } }),

  // =========================================================================
  // 5. POSITIONS ACTIONS
  // =========================================================================

  /**
   * Replace the entire positions array (used after full fetch).
   * @param {Array<Object>} positions
   */
  setPositions: (positions) => set({ positions }),

  /**
   * Update unrealized PnL for a specific position when LTP changes.
   * @param {string} contractSymbol
   * @param {number} ltp — latest traded price
   */
  updatePositionPnl: (contractSymbol, ltp) =>
    set((state) => {
      const sym = String(contractSymbol || '').trim().toUpperCase();
      const price = Number(ltp);
      if (!sym || !Number.isFinite(price) || price <= 0) return state;

      let changed = false;
      const positions = state.positions.map((p) => {
        if (p.contract_symbol !== sym) return p;
        const qty = Number(p.quantity) || 0;
        const avg = Number(p.avg_entry_price ?? p.avg_price) || 0;
        const unrealized_pnl = qty >= 0 ? (price - avg) * qty : (avg - price) * Math.abs(qty);
        if (p.ltp === price && p.unrealized_pnl === unrealized_pnl) return p;
        changed = true;
        return { ...p, ltp: price, unrealized_pnl };
      });
      if (!changed) return state;

      const unrealizedPnl = positions.reduce((sum, p) => {
        const q = Number(p.quantity) || 0;
        if (q === 0) return sum;
        const u = Number(p.unrealized_pnl);
        return sum + (Number.isFinite(u) ? u : 0);
      }, 0);

      return {
        positions,
        margin: { ...state.margin, unrealizedPnl },
        _lastQuoteUpdate: Date.now(),
      };
    }),

  /** Recalculate P&L for every open position from the latest quote cache (tick batch). */
  recalculateLivePnl: () =>
    set((state) => {
      if (!state.positions.length) return state;

      let changed = false;
      const positions = state.positions.map((p) => {
        const qty = Number(p.quantity) || 0;
        if (qty === 0) return p;
        const q = state.quotes[p.contract_symbol];
        const ltp = quoteLtp(q);
        if (ltp == null) return p;
        const avg = Number(p.avg_entry_price ?? p.avg_price) || 0;
        const unrealized_pnl = qty >= 0 ? (ltp - avg) * qty : (avg - ltp) * Math.abs(qty);
        if (p.ltp === ltp && p.unrealized_pnl === unrealized_pnl) return p;
        changed = true;
        return { ...p, ltp, unrealized_pnl };
      });
      if (!changed) return state;

      const unrealizedPnl = positions.reduce((sum, p) => {
        const u = Number(p.unrealized_pnl);
        return sum + (Number.isFinite(u) ? u : 0);
      }, 0);

      return {
        positions,
        margin: { ...state.margin, unrealizedPnl },
        _lastQuoteUpdate: Date.now(),
      };
    }),

  // =========================================================================
  // 6. ORDERS ACTIONS
  // =========================================================================

  /**
   * Replace the entire orders array (used after full fetch).
   * @param {Array<Object>} orders
   */
  setOrders: (orders) => set({ orders }),

  /**
   * Append a newly placed order.
   * @param {Object} order
   */
  addOrder: (order) =>
    set((state) => ({ orders: [order, ...state.orders] })),

  /**
   * Update status and optional fill data for an existing order.
   * @param {string} orderId
   * @param {string} status — e.g. "FILLED", "CANCELLED", "REJECTED"
   * @param {Object} [filledData] — { filled_quantity, filled_price }
   */
  updateOrderStatus: (orderId, status, filledData = {}) =>
    set((state) => ({
      orders: state.orders.map((o) =>
        o.id === orderId ? { ...o, status, ...filledData } : o
      ),
    })),

  /**
   * Remove an order by id (e.g. after cancellation cleanup).
   * @param {string} orderId
   */
  removeOrder: (orderId) =>
    set((state) => ({
      orders: state.orders.filter((o) => o.id !== orderId),
    })),

  /** @param {boolean} bool */
  setOrdersLoading: (bool) => set({ ordersLoading: bool }),

  // =========================================================================
  // 7. MARGIN ACTIONS
  // =========================================================================

  /**
   * Partial-merge margin fields (e.g. after recalculation).
   * @param {Object} marginData — partial margin fields to merge
   */
  updateMargin: (marginData) =>
    set((state) => ({
      margin: { ...state.margin, ...marginData },
    })),

  /**
   * Block margin when a new position is opened.
   * @param {number} amount — margin amount to block
   */
  blockMargin: (amount) =>
    set((state) => ({
      margin: {
        ...state.margin,
        usedMargin: state.margin.usedMargin + amount,
        availableMargin: state.margin.availableMargin - amount,
      },
    })),

  /**
   * Release margin when a position is closed.
   * @param {number} amount — margin amount to release
   */
  releaseMargin: (amount) =>
    set((state) => ({
      margin: {
        ...state.margin,
        usedMargin: state.margin.usedMargin - amount,
        availableMargin: state.margin.availableMargin + amount,
      },
    })),

  /**
   * Add realized P&L (booked profit/loss) and adjust available margin.
   * @param {number} amount — positive for profit, negative for loss
   */
  addRealizedPnl: (amount) =>
    set((state) => ({
      margin: {
        ...state.margin,
        realizedPnl: state.margin.realizedPnl + amount,
        totalFunds: state.margin.totalFunds + amount,
        availableMargin: state.margin.availableMargin + amount,
      },
    })),

  // =========================================================================
  // 8. WATCHLIST ACTIONS
  // =========================================================================

  /**
   * Add a contract to the watchlist (no-op if already present).
   * @param {string} contractSymbol
   * @param {string} underlying
   */
  addToWatchlist: (contractSymbol, underlying) =>
    set((state) => {
      if (state.watchlist.items.some((w) => w.contract_symbol === contractSymbol)) {
        return state;
      }
      return {
        watchlist: {
          ...state.watchlist,
          items: [
            ...state.watchlist.items,
            { contract_symbol: contractSymbol, underlying, added_at: Date.now() },
          ],
        },
      };
    }),

  /**
   * Remove a contract from the watchlist.
   * @param {string} contractSymbol
   */
  removeFromWatchlist: (contractSymbol) =>
    set((state) => ({
      watchlist: {
        ...state.watchlist,
        items: state.watchlist.items.filter(
          (w) => w.contract_symbol !== contractSymbol
        ),
      },
    })),

  /**
   * Set watchlist sort parameters.
   * @param {string} sortBy — field name to sort by
   * @param {'asc' | 'desc'} sortDir
   */
  setWatchlistSort: (sortBy, sortDir) =>
    set((state) => ({
      watchlist: { ...state.watchlist, sortBy, sortDir },
    })),

  // =========================================================================
  // RESET
  // =========================================================================

  /** Reset the entire store back to initial state. */
  reset: () => set({ ...INITIAL_STATE }),
}));

// ---------------------------------------------------------------------------
// SELECTORS (standalone hooks with shallow equality)
// ---------------------------------------------------------------------------

/** Returns the full contract object for the currently selected contract. */
export const useSelectedContract = () =>
  useUnifiedFuturesStore((s) => {
    const sym = s.contracts.selectedContract;
    return sym ? s.contracts.bySymbol[sym] ?? null : null;
  });

/** Returns the quote object for the currently selected contract. */
export const useSelectedQuote = () =>
  useUnifiedFuturesStore((s) => {
    const sym = s.contracts.selectedContract;
    return sym ? s.quotes[sym] ?? null : null;
  });

/**
 * Returns the quote for a specific contract symbol.
 * @param {string} contractSymbol
 */
export const useContractQuote = (contractSymbol) =>
  useUnifiedFuturesStore((s) => s.quotes[contractSymbol] ?? null);

/**
 * Returns sorted contract objects for a given underlying.
 * @param {string} symbol — underlying, e.g. "NIFTY"
 */
export const useContractsForUnderlying = (symbol) =>
  useUnifiedFuturesStore((s) => {
    const syms = s.contracts.byUnderlying[symbol];
    if (!syms) return [];
    return syms
      .map((cs) => s.contracts.bySymbol[cs])
      .filter(Boolean)
      .sort((a, b) => {
        if (a.expiry_date && b.expiry_date) {
          return new Date(a.expiry_date) - new Date(b.expiry_date);
        }
        return a.contract_symbol.localeCompare(b.contract_symbol);
      });
  }, shallow);

/** Returns the positions array. */
export const useFuturesPositions = () =>
  useUnifiedFuturesStore((s) => s.positions, shallow);

/** Returns the orders array. */
export const useFuturesOrders = () =>
  useUnifiedFuturesStore((s) => s.orders, shallow);

/** Returns the margin state object. */
export const useFuturesMargin = () =>
  useUnifiedFuturesStore((s) => s.margin, shallow);

/** Returns the connection state object. */
export const useFuturesConnection = () =>
  useUnifiedFuturesStore((s) => s.connection, shallow);

/**
 * Returns watchlist items enriched with their latest quote data.
 * Each item gains all quote fields (ltp, bid, ask, change, etc.).
 */
export const useWatchlistWithQuotes = () =>
  useUnifiedFuturesStore((s) => {
    const { items, sortBy, sortDir } = s.watchlist;

    const enriched = items.map((item) => ({
      ...item,
      ...(s.quotes[item.contract_symbol] ?? {}),
    }));

    enriched.sort((a, b) => {
      const aVal = a[sortBy] ?? '';
      const bVal = b[sortBy] ?? '';
      if (typeof aVal === 'number' && typeof bVal === 'number') {
        return sortDir === 'asc' ? aVal - bVal : bVal - aVal;
      }
      const cmp = String(aVal).localeCompare(String(bVal));
      return sortDir === 'asc' ? cmp : -cmp;
    });

    return enriched;
  }, shallow);

export default useUnifiedFuturesStore;
