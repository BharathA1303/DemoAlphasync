import { create } from 'zustand';
import {
    shouldUseRealtimePrices,
    shouldApplyQuoteSource,
    isAuthoritativeClosedQuoteSource,
} from '../market/utils/marketSessionUtils';
import { isCommoditySymbol, isDerivativeContractSymbol } from '../utils/constants';

const LIVE_STALE_PROTECT_MS = 5_000;

const toFiniteNumber = (value) => {
    const num = Number(value);
    return Number.isFinite(num) ? num : null;
};

const toSymbolAliases = (symbol = '') => {
    const raw = String(symbol || '').trim().toUpperCase();
    if (!raw) return [];

    const withNs =
        raw.endsWith('.NS') ||
        raw.endsWith('.BO') ||
        raw.startsWith('^') ||
        isCommoditySymbol(raw) ||
        isDerivativeContractSymbol(raw)
            ? raw
            : `${raw}.NS`;
    const withoutNs = withNs.replace(/\.(NS|BO)$/i, '');

    return [...new Set([raw, withNs, withoutNs])].filter(Boolean);
};

const normalizeIncomingQuote = (raw = {}, existing = {}) => {
    const price = toFiniteNumber(raw.price ?? raw.lp ?? raw.ltp ?? raw.last_price ?? raw.lastPrice);
    const prevClose = toFiniteNumber(raw.prev_close ?? raw.prevClose ?? raw.previous_close ?? raw.close ?? existing.prev_close);
    const change = toFiniteNumber(raw.change ?? raw.net_change ?? raw.netChange);
    const changePercent = toFiniteNumber(raw.change_percent ?? raw.changePercent ?? raw.pct_change ?? raw.pc ?? raw.pChange ?? raw.percent_change);
    const derivedPrevClose = prevClose ?? (
        price != null && changePercent != null && (1 + changePercent / 100) > 0
            ? price / (1 + changePercent / 100)
            : null
    );
    const derivedChange = change ?? (
        price != null && derivedPrevClose != null
            ? price - derivedPrevClose
            : null
    );
    const derivedChangePercent = changePercent ?? (
        derivedChange != null && derivedPrevClose != null && derivedPrevClose > 0
            ? (derivedChange / derivedPrevClose) * 100
            : null
    );

    return {
        ...existing,
        ...raw,
        ...(price != null ? { price } : {}),
        ...(derivedChange != null ? { change: Number(derivedChange.toFixed(2)) } : {}),
        ...(derivedChangePercent != null ? { change_percent: Number(derivedChangePercent.toFixed(2)) } : {}),
        ...(derivedPrevClose != null ? { prev_close: Number(derivedPrevClose.toFixed(2)) } : {}),
    };
};

/**
 * Market data store — source of truth for all live quotes and watchlist.
 *
 * Quote shape (from /market/quote/:symbol API):
 * { price, change, change_percent, volume, high, low, open, prev_close, ... }
 */
export const useMarketStore = create((set, get) => ({
    /** @type {Record<string, object>} symbol → latest quote data */
    symbols: {},

    /** @type {string[]} Ordered watchlist symbol list */
    watchlist: [],

    /** @type {string|null} Currently selected symbol in the terminal */
    selectedSymbol: null,

    /** @type {'connecting'|'connected'|'disconnected'|'error'} */
    wsStatus: 'disconnected',

    /** @type {number} Epoch ms of last successful quote ingestion */
    lastQuoteAt: 0,

    // ─── Actions ─────────────────────────────────────────────────────────────

    /**
     * Update or merge a quote for a symbol.
     * Called by WebSocket handler and polling fallback.
     * Skips update if price hasn't actually changed (prevents unnecessary re-renders).
     * @param {string} symbol
     * @param {object} data
     */
    updateQuote: (symbol, data, source = 'live') =>
        set((state) => {
            const aliases = toSymbolAliases(symbol);
            if (aliases.length === 0) return state;

            const now = Date.now();
            const marketOpen = shouldUseRealtimePrices();
            const hasCommodity = aliases.some((sym) => isCommoditySymbol(sym));
            const src = String(source || '').toLowerCase();
            if (!marketOpen && !hasCommodity && !isAuthoritativeClosedQuoteSource(src)) {
                return state;
            }
            let hasChanges = false;
            const nextSymbols = { ...state.symbols };

            for (const key of aliases) {
                const existing = nextSymbols[key] || {};

                if (!hasCommodity && !shouldApplyQuoteSource(source, existing)) {
                    continue;
                }

                if (
                    source !== 'live' &&
                    source !== 'eod' &&
                    existing._source === 'live' &&
                    marketOpen &&
                    now - (existing._updatedAt || 0) < LIVE_STALE_PROTECT_MS
                ) {
                    continue;
                }

                const normalized = normalizeIncomingQuote(data, existing);
                const merged = {
                    ...normalized,
                    _source: source,
                    _updatedAt: now,
                };

                const quoteChanged =
                    existing.price !== merged.price ||
                    existing.change !== merged.change ||
                    existing.change_percent !== merged.change_percent ||
                    existing.bid_price !== merged.bid_price ||
                    existing.ask_price !== merged.ask_price ||
                    existing.volume !== merged.volume ||
                    existing.oi !== merged.oi ||
                    existing.high !== merged.high ||
                    existing.low !== merged.low;

                if (
                    quoteChanged
                ) {
                    hasChanges = true;
                }

                nextSymbols[key] = merged;
            }

            if (!hasChanges) {
                // Keep ws freshness alive even when price is unchanged.
                if (source === 'live') {
                    return { ...state, lastQuoteAt: now };
                }
                return state;
            }

            return {
                symbols: nextSymbols,
                lastQuoteAt: source === 'live' ? now : state.lastQuoteAt,
            };
        }),

    /**
     * Set the active symbol in the terminal.
     * @param {string} symbol
     */
    setSelectedSymbol: (symbol) => set({ selectedSymbol: symbol }),

    /**
     * Replace the entire ordered watchlist.
     * @param {string[]} symbols
     */
    setWatchlist: (symbols) => set({ watchlist: symbols }),

    /**
     * Add a symbol to the watchlist (no-op if already present).
     * @param {string} symbol
     */
    addToWatchlist: (symbol) =>
        set((state) => ({
            watchlist: state.watchlist.includes(symbol)
                ? state.watchlist
                : [...state.watchlist, symbol],
        })),

    /**
     * Remove a symbol from the watchlist.
     * @param {string} symbol
     */
    removeFromWatchlist: (symbol) =>
        set((state) => ({
            watchlist: state.watchlist.filter((s) => s !== symbol),
        })),

    /**
     * Set WebSocket connection status (called by useWebSocket hook).
     * @param {'connecting'|'connected'|'disconnected'|'error'} status
     */
    setWsStatus: (status) => set({ wsStatus: status }),

    /**
     * Batch update multiple quotes at once (from HTTP polling).
     * Only triggers a re-render if at least one price actually changed.
     * @param {Record<string, object>} quotesMap
     */
    batchUpdateQuotes: (quotesMap, source = 'poll') =>
        set((state) => {
            if (!quotesMap || Object.keys(quotesMap).length === 0) return state;
            const now = Date.now();
            const marketOpen = shouldUseRealtimePrices();
            const nextSymbols = { ...state.symbols };
            let hasChanges = false;

            const batchSrc = String(source || '').toLowerCase();
            const hasCommodityBatch = Object.keys(quotesMap).some((sym) => isCommoditySymbol(sym));
            if (!marketOpen && !hasCommodityBatch && !isAuthoritativeClosedQuoteSource(batchSrc)) {
                return state;
            }

            for (const [sym, data] of Object.entries(quotesMap)) {
                const aliases = toSymbolAliases(sym);
                if (aliases.length === 0) continue;

                for (const key of aliases) {
                    const existing = nextSymbols[key] || {};

                    const isCommodityQuote = aliases.some((sym) => isCommoditySymbol(sym));
                    if (!isCommodityQuote && !shouldApplyQuoteSource(batchSrc, existing)) {
                        continue;
                    }

                    if (
                        source !== 'live' &&
                        source !== 'eod' &&
                        existing._source === 'live' &&
                        marketOpen &&
                        now - (existing._updatedAt || 0) < LIVE_STALE_PROTECT_MS
                    ) {
                        continue;
                    }

                    const normalized = normalizeIncomingQuote(data, existing);
                    const merged = {
                        ...normalized,
                        _source: source,
                        _updatedAt: now,
                    };

                    const quoteChanged =
                        existing.price !== merged.price ||
                        existing.change !== merged.change ||
                        existing.change_percent !== merged.change_percent ||
                        existing.bid_price !== merged.bid_price ||
                        existing.ask_price !== merged.ask_price ||
                        existing.volume !== merged.volume ||
                        existing.oi !== merged.oi ||
                        existing.high !== merged.high ||
                        existing.low !== merged.low;

                    if (
                        quoteChanged
                    ) {
                        hasChanges = true;
                    }

                    nextSymbols[key] = merged;
                }
            }

            if (!hasChanges) {
                if (source === 'live') {
                    return { ...state, lastQuoteAt: now };
                }
                return state;
            }
            return {
                symbols: nextSymbols,
                lastQuoteAt: source === 'live' ? now : state.lastQuoteAt,
            };
        }),
}));
