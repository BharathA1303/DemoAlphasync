import { create } from 'zustand';
import api from '../services/api';

const MAX_TICK_HISTORY = 30;

const normalizeSource = (value) => {
    const src = String(value || '').toLowerCase();
    if (src === 'live_ws' || src.startsWith('live_ws')) return 'live_ws';
    if (src.startsWith('live_zebu')) return 'live_zebu';
    if (src.startsWith('live')) return 'live';
    if (src === 'hot') return 'hot';
    if (src === 'frozen') return 'frozen';
    if (src === 'cache') return 'frozen';
    if (src === 'rest') return 'rest';
    return src || null;
};

/** Source priority — higher number wins when timestamps are equal. */
const SOURCE_PRIORITY = {
    live_ws: 100,
    live_zebu: 90,
    live: 80,
    hot: 50,
    rest: 40,
    frozen: 10,
};

const parseTimestamp = (value) => {
    if (!value) return 0;
    if (typeof value === 'number') return value;
    const ms = Date.parse(value);
    return Number.isFinite(ms) ? ms : 0;
};

const buildCommodityState = (items, source, existingQuotes) => {
    const quotes = {};
    const meta = {};
    const history = {};

    for (const item of items) {
        const sym = String(item?.symbol || '').trim().toUpperCase();
        if (!sym) continue;

        const price = Number(item.price ?? 0) || 0;
        const change = Number(item.change ?? 0) || 0;
        const changePercent = Number(item.change_percent ?? 0) || 0;

        // Timestamp-priority: never overwrite a fresher WS tick with stale REST data.
        const existing = existingQuotes?.[sym];
        if (existing) {
            const existingTs = parseTimestamp(existing.timestamp || existing._receivedAt);
            const incomingTs = parseTimestamp(item.timestamp);
            const existingSrc = normalizeSource(existing.source);
            const incomingSrc = normalizeSource(item.source || source);
            const existingPri = SOURCE_PRIORITY[existingSrc] ?? 0;
            const incomingPri = SOURCE_PRIORITY[incomingSrc] ?? 0;

            if (existingTs > 0 && incomingTs > 0 && existingTs > incomingTs && existingPri >= incomingPri) {
                quotes[sym] = existing;
                continue;
            }

            // When REST wins on timestamp but lacks depth fields, preserve
            // existing WS-populated bid/ask/OI to avoid transient zeros.
            if (existing && incomingPri < existingPri) {
                for (const k of ['bid_price', 'ask_price', 'bid_qty', 'ask_qty', 'oi']) {
                    if ((!item[k] || Number(item[k]) === 0) && existing[k]) {
                        item[k] = existing[k];
                    }
                }
            }
        }

        quotes[sym] = {
            ...item,
            symbol: sym,
            price,
            change,
            change_percent: changePercent,
            high: Number(item.high ?? price) || price,
            low: Number(item.low ?? price) || price,
            volume: Number(item.volume ?? 0) || 0,
            oi: Number(item.oi ?? 0) || 0,
            bid_price: Number(item.bid_price ?? 0) || 0,
            ask_price: Number(item.ask_price ?? 0) || 0,
            bid_qty: Number(item.bid_qty ?? 0) || 0,
            ask_qty: Number(item.ask_qty ?? 0) || 0,
            source: item.source || source,
            kind: 'commodity',
            _receivedAt: Date.now(),
        };

        meta[sym] = {
            name: item.name,
            exchange: item.exchange,
            category: item.category,
            unit: item.unit,
            lot: item.lot || 1,
        };

        if (!history[sym]) {
            history[sym] = price > 0 ? [price] : [];
        }
    }

    return { quotes, meta, history };
};

/**
 * Commodity store — manages MCX/NCDEX commodity data.
 *
 * Live updates come from WebSocket ticks (PRICE_UPDATED → broadcast_price).
 * REST polling is a fallback for initial load and reconnect recovery.
 * Timestamp-priority merge prevents stale REST from overwriting fresh WS data.
 */
const useCommodityStore = create((set, get) => ({
    /** symbol → full quote (latest) */
    quotes: {},

    /** symbol → last N prices for sparkline */
    tickHistory: {},

    /** symbol → previous price for flash animation */
    prevPrices: {},

    /** Static commodity metadata from backend */
    commodityMeta: {},

    isLoading: false,
    lastFetchAt: null,
    source: null,
    error: null,

    /** Epoch ms when WS last reconnected — REST data older than this is ignored. */
    _wsReconnectedAt: 0,

    /** Call from CommoditiesPage when WS reconnects to arm the freshness guard. */
    markWsReconnect: () => set({ _wsReconnectedAt: Date.now() }),

    /**
     * Initial / fallback load from REST.
     * Will not overwrite fresher WS quotes (timestamp-priority in buildCommodityState).
     */
    fetchCommodities: async () => {
        set({ isLoading: true, error: null });
        try {
            let items = [];
            let src = null;

            try {
                const response = await api.get('/market/commodities');
                const data = response.data || null;
                items = data?.commodities || [];
                src = normalizeSource(data?.source || items[0]?.source) || 'rest';
            } catch (err) {
                console.error('Failed to fetch live commodities:', err);
                const timedOut = err?.code === 'ECONNABORTED';
                const detail = err?.response?.data?.detail;
                set({ error: timedOut ? 'Commodities request timed out. Please retry.' : (detail || 'Failed to fetch commodities.') });
            }

            const existingQuotes = get().quotes;
            const reconnectAt = get()._wsReconnectedAt;

            // After WS reconnect, ignore REST responses that were initiated before
            // the reconnect — they carry stale snapshots that would overwrite
            // fresh ticks arriving on the new connection.
            if (reconnectAt > 0 && items.length > 0) {
                const oldestItemTs = Math.min(
                    ...items.map(i => Date.parse(i.timestamp) || 0).filter(Boolean)
                );
                if (oldestItemTs > 0 && oldestItemTs < reconnectAt) {
                    set({ isLoading: false });
                    return;
                }
            }

            const { quotes, meta, history } = buildCommodityState(items, src, existingQuotes);

            // Merge: keep any WS-populated rows that REST didn't return.
            const mergedQuotes = { ...existingQuotes, ...quotes };

            set({
                quotes: mergedQuotes,
                commodityMeta: { ...get().commodityMeta, ...meta },
                tickHistory: { ...get().tickHistory, ...history },
                isLoading: false,
                lastFetchAt: Date.now(),
                source: src,
            });
        } catch (err) {
            console.error('Failed to fetch commodities:', err);
            set({ isLoading: false, error: 'Failed to fetch commodities.' });
        }
    },

    /**
     * Apply a live tick from WebSocket — highest priority source.
     * Merges into existing row, preserves metadata, tracks flash/history.
     */
    applyTick: (symbol, quote) => {
        if (!symbol || !quote) return;
        const price = Number(quote.price ?? quote.lp ?? quote.ltp ?? 0);
        if (!price || price <= 0) return;

        const marketStatus = String(quote.market_status || '').toLowerCase();
        const isFrozenStatus = marketStatus && marketStatus !== 'open';
        const incomingSource = normalizeSource(quote.source);
        const effectiveSource = isFrozenStatus
            ? 'frozen'
            : (incomingSource || 'live_ws');

        set((state) => {
            const prev = state.quotes[symbol] || {};
            const meta = state.commodityMeta[symbol] || {};

            const merged = {
                ...prev,
                ...quote,
                ...meta,
                symbol,
                price,
                kind: 'commodity',
                source: effectiveSource,
                _receivedAt: Date.now(),
            };

            const prevPrices = { ...state.prevPrices };
            if (prev.price && prev.price !== price) {
                prevPrices[symbol] = prev.price;
            }

            const history = { ...state.tickHistory };
            const arr = [...(history[symbol] || []), price];
            if (arr.length > MAX_TICK_HISTORY) arr.shift();
            history[symbol] = arr;

            return {
                quotes: { ...state.quotes, [symbol]: merged },
                tickHistory: history,
                prevPrices,
                source: effectiveSource,
                lastFetchAt: Date.now(),
            };
        });
    },

    /** Get flash direction for a symbol: 'up', 'down', or null */
    getFlash: (symbol) => {
        const state = get();
        const prev = state.prevPrices[symbol];
        const curr = state.quotes[symbol]?.price;
        if (prev == null || curr == null) return null;
        if (curr > prev) return 'up';
        if (curr < prev) return 'down';
        return null;
    },
}));

export { useCommodityStore };
