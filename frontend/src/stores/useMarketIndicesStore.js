import { create } from 'zustand';
import api from '../services/api';

/**
 * Market‑indices store — centralises NIFTY/SENSEX/BANKNIFTY polling
 * + full ticker data (indices + popular stocks) for the scrolling bar.
 */
export const useMarketIndicesStore = create((set, get) => ({
    /** @type {Array<object>} Index data (legacy — indices only) */
    indices: [],

    /** @type {Array<object>} Full ticker items (indices + stocks) */
    tickerItems: [],

    /** @type {boolean} */
    isLoading: false,

    /** @type {number|null} Polling interval ID */
    _intervalId: null,

    /** @type {number} Consecutive auth ticker failures */
    _tickerFailures: 0,

    // ─── Actions ──────────────────────────────────────────────────────────────

    /** Fetch market indices once (legacy). */
    fetchIndices: async () => {
        set({ isLoading: true });
        try {
            const res = await api.get('/market/indices');
            set({ indices: res.data.indices || [] });
        } catch {
            // Keep last successful values instead of blanking UI on transient failures.
        } finally {
            set({ isLoading: false });
        }
    },

    /** Fetch full ticker data (indices + stocks) — requires auth. */
    fetchTicker: async () => {
        try {
            const res = await api.get('/market/ticker');
            const items = res.data.items || [];
            const indices = items.filter((i) => i.kind === 'index');
            set({ tickerItems: items, indices, _tickerFailures: 0 });
        } catch (err) {
            const failures = get()._tickerFailures + 1;
            // Keep last successful ticker payload when requests fail.
            set({ _tickerFailures: failures });
        }
    },

    /** Start periodic polling (default 60s). */
    startPolling: (intervalMs = 60_000) => {
        const { _intervalId, fetchTicker, fetchIndices } = get();
        if (_intervalId) return; // already polling
        set({ isLoading: true });
        // Fetch ticker and indices in parallel.
        Promise.all([
            fetchTicker(),
            fetchIndices(),
        ]).finally(() => set({ isLoading: false }));
        const id = setInterval(fetchTicker, intervalMs);
        set({ _intervalId: id });
    },

    /** Stop polling. */
    stopPolling: () => {
        const { _intervalId } = get();
        if (_intervalId) {
            clearInterval(_intervalId);
            set({ _intervalId: null });
        }
    },
}));
