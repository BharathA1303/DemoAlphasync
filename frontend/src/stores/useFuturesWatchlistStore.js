import { create } from 'zustand';
import api, { isRateLimited } from '../services/api';
import toast from 'react-hot-toast';
import useUnifiedFuturesStore from './useUnifiedFuturesStore';

const STORAGE_KEY = 'alphasync_futures_watchlists';
const SEEDED_BASES = ['NIFTY', 'BANKNIFTY', 'RELIANCE', 'TCS'];

const isLikelySeededContract = (symbol = '') => {
    const upper = String(symbol || '').toUpperCase();
    if (!upper) return false;
    return SEEDED_BASES.some((base) => upper.startsWith(base));
};

const stripSeededDefaults = (watchlists = []) => watchlists.map((watchlist) => {
    const items = Array.isArray(watchlist?.items) ? watchlist.items : [];
    if (items.length === 0 || items.length > 4) return watchlist;
    const allSeeded = items.every((item) => isLikelySeededContract(item?.contract_symbol));
    if (!allSeeded) return watchlist;
    return { ...watchlist, items: [] };
});

const persistToStorage = (watchlists, activeId) => {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ watchlists, activeId }));
    } catch (err) {
        console.error('[FuturesWatchlist] Failed to persist to localStorage:', err);
    }
};

const loadFromStorage = () => {
    try {
        const stored = localStorage.getItem(STORAGE_KEY);
        return stored ? JSON.parse(stored) : null;
    } catch (err) {
        console.error('[FuturesWatchlist] Failed to load local watchlist:', err);
        return null;
    }
};

const ensureState = (watchlists, activeId) => {
    if (Array.isArray(watchlists) && watchlists.length > 0) {
        const nextActiveId = watchlists.some((watchlist) => watchlist.id === activeId)
            ? activeId
            : watchlists[0].id;
        return { watchlists, activeId: nextActiveId };
    }

    const defaultId = `local_${Date.now()}`;
    return {
        watchlists: [{ id: defaultId, name: 'Watchlist 1', items: [] }],
        activeId: defaultId,
    };
};

export const useFuturesWatchlistStore = create((set, get) => ({
    watchlists: [],
    activeId: null,
    prices: {},
    isLoading: false,
    syncDisabled: true,

    loadWatchlist: async () => {
        set({ isLoading: true, syncDisabled: true });
        const cached = loadFromStorage();
        const sanitizedWatchlists = stripSeededDefaults(cached?.watchlists || []);
        const next = ensureState(sanitizedWatchlists, cached?.activeId);
        set({ ...next, isLoading: false });
        persistToStorage(next.watchlists, next.activeId);
    },

    setActiveWatchlist: (id) => {
        const { watchlists } = get();
        const nextActiveId = watchlists.some((watchlist) => watchlist.id === id)
            ? id
            : watchlists[0]?.id ?? null;
        set({ activeId: nextActiveId });
        persistToStorage(watchlists, nextActiveId);
        get().fetchPrices();
    },

    createWatchlist: async (name = 'New Futures Watchlist') => {
        const trimmed = name.trim();
        if (!trimmed) return null;
        const newWatchlist = { id: `local_${Date.now()}`, name: trimmed, items: [] };
        set((state) => ({
            watchlists: [...state.watchlists, newWatchlist],
            activeId: newWatchlist.id,
        }));
        const { watchlists, activeId } = get();
        persistToStorage(watchlists, activeId);
        toast.success(`"${trimmed}" created`);
        return newWatchlist;
    },

    renameWatchlist: async (id, newName) => {
        const trimmed = newName?.trim();
        if (!id || !trimmed) return;
        set((state) => ({
            watchlists: state.watchlists.map((watchlist) =>
                watchlist.id === id ? { ...watchlist, name: trimmed } : watchlist
            ),
        }));
        const { watchlists, activeId } = get();
        persistToStorage(watchlists, activeId);
    },

    deleteWatchlist: async (id) => {
        const { watchlists, activeId } = get();
        if (watchlists.length <= 1) {
            toast.error('You need at least one watchlist');
            return;
        }
        const remaining = watchlists.filter((watchlist) => watchlist.id !== id);
        const nextActiveId = activeId === id ? remaining[0]?.id ?? null : activeId;
        set({ watchlists: remaining, activeId: nextActiveId });
        persistToStorage(remaining, nextActiveId);
        toast.success('Watchlist deleted');
    },

    addItem: async (contractSymbol) => {
        let { activeId, watchlists } = get();
        if (!activeId || watchlists.length === 0) {
            await get().loadWatchlist();
            ({ activeId, watchlists } = get());
        }

        const normalizedSymbol = String(contractSymbol || '').trim().toUpperCase();
        if (!normalizedSymbol) {
            toast.error('Contract symbol is required');
            return;
        }

        const active = watchlists.find((watchlist) => watchlist.id === activeId);
        if (!active) {
            toast.error('Watchlist not found');
            return;
        }
        if (active.items.some((item) => item.contract_symbol === normalizedSymbol)) {
            toast(`${normalizedSymbol} is already in watchlist`);
            return;
        }

        const item = {
            id: `local_item_${Date.now()}`,
            contract_symbol: normalizedSymbol,
            added_at: new Date().toISOString(),
        };

        set((state) => ({
            watchlists: state.watchlists.map((watchlist) =>
                watchlist.id === activeId
                    ? { ...watchlist, items: [...watchlist.items, item] }
                    : watchlist
            ),
        }));

        const next = get();
        persistToStorage(next.watchlists, next.activeId);
        get().fetchPrices();
    },

    removeItem: async (itemId) => {
        const { activeId } = get();
        if (!activeId || !itemId) return;
        set((state) => ({
            watchlists: state.watchlists.map((watchlist) =>
                watchlist.id === activeId
                    ? { ...watchlist, items: watchlist.items.filter((item) => item.id !== itemId) }
                    : watchlist
            ),
        }));
        const { watchlists, activeId: nextActiveId } = get();
        persistToStorage(watchlists, nextActiveId);
    },

    reorderItems: (newItems) => {
        const { activeId } = get();
        set((state) => ({
            watchlists: state.watchlists.map((watchlist) =>
                watchlist.id === activeId ? { ...watchlist, items: newItems } : watchlist
            ),
        }));
        const { watchlists, activeId: nextActiveId } = get();
        persistToStorage(watchlists, nextActiveId);
    },

    fetchPrices: async () => {
        const { activeId, watchlists } = get();
        const active = watchlists.find((watchlist) => watchlist.id === activeId);
        if (!active || active.items.length === 0 || isRateLimited()) return;

        const symbols = active.items.map((item) => item.contract_symbol).filter(Boolean);
        try {
            const res = await api.post('/futures/quotes/batch', { contracts: symbols.slice(0, 50) });
            const quotes = res.data?.quotes ?? {};
            if (Object.keys(quotes).length > 0) {
                set((state) => ({ prices: { ...state.prices, ...quotes } }));
                useUnifiedFuturesStore.getState().updateQuotes(quotes);
            }
        } catch {
            // fallback: per-contract Zebu quote
            const quoteResults = await Promise.allSettled(
                symbols.map((sym) => api.get(`/futures/quote/${encodeURIComponent(sym)}`)),
            );
            const nextPrices = {};
            quoteResults.forEach((result, index) => {
                if (result.status === 'fulfilled') {
                    nextPrices[symbols[index]] = result.value.data;
                }
            });
            if (Object.keys(nextPrices).length > 0) {
                set((state) => ({ prices: { ...state.prices, ...nextPrices } }));
            }
        }
    },

    updatePrices: (priceUpdate) => {
        if (!priceUpdate || Object.keys(priceUpdate).length === 0) return;
        set((state) => ({ prices: { ...state.prices, ...priceUpdate } }));
    },

    clear: () => {
        set({ watchlists: [], activeId: null, prices: {}, isLoading: false, syncDisabled: true });
        try {
            localStorage.removeItem(STORAGE_KEY);
        } catch (err) {
            console.error('[FuturesWatchlist] Failed to clear localStorage:', err);
        }
    },
}));
