import { create } from 'zustand';
import api from '../services/api';

/**
 * Portfolio store — holdings, positions, orders and funds.
 * All mutations proxy through existing services/api.js.
 */
export const usePortfolioStore = create((set, get) => ({
    /** @type {Array} Current holdings from /portfolio/holdings */
    holdings: [],

    /** @type {Array} Intraday positions from /portfolio/positions */
    positions: [],

    /** @type {Array} Orders from /orders */
    orders: [],

    /** @type {Array} Executed trades from /portfolio/transactions */
    transactions: [],

    /** @type {Array|null} Open lots from /portfolio/open-lots (null = unavailable) */
    openLots: null,

    /** @type {object|null} Portfolio summary from /portfolio/summary */
    summary: null,

    /** @type {{ realized: number, unrealized: number, total: number }} */
    pnl: { realized: 0, unrealized: 0, total: 0 },

    /** @type {boolean} */
    isLoading: false,

    // ─── Actions ──────────────────────────────────────────────────────────────

    /**
     * Fetch all portfolio data in parallel.
     * Called on mount and after order placement.
     */
    refreshPortfolio: async () => {
        // Only show loading spinner on the very first load (no data yet).
        // Background refreshes run silently to avoid flickering skeleton states.
        const isFirstLoad = get().summary === null && get().holdings.length === 0;
        if (isFirstLoad) set({ isLoading: true });
        try {
            const [summaryRes, ordersRes, transactionsRes, openLotsRes] = await Promise.allSettled([
                api.get('/portfolio/summary'),
                api.get('/orders?limit=500'),
                api.get('/portfolio/transactions?limit=500'),
                api.get('/portfolio/open-lots'),
            ]);

            const summaryPayload = summaryRes.status === 'fulfilled' ? summaryRes.value.data : null;
            const summary = summaryPayload?.summary ?? get().summary;
            const holdings = summaryPayload?.holdings ?? get().holdings;
            const orders = ordersRes.status === 'fulfilled' ? ordersRes.value.data.orders ?? [] : get().orders;
            const transactions = transactionsRes.status === 'fulfilled'
                ? transactionsRes.value.data.transactions ?? []
                : get().transactions;
            const openLots = openLotsRes.status === 'fulfilled'
                ? (openLotsRes.value.data.open_lots ?? [])
                : null;

            set({
                summary,
                holdings,
                orders,
                transactions,
                openLots,
                pnl: {
                    realized: summary?.realized_pnl ?? 0,
                    unrealized: summary?.unrealized_pnl ?? 0,
                    total: summary?.total_pnl ?? 0,
                },
                isLoading: false,
            });
        } catch { /* ignore — keep stale data */ } finally {
            if (isFirstLoad) set({ isLoading: false });
        }
    },

    /**
     * Live-update a single position's P&L without a full refetch.
     * @param {string} symbol
     * @param {Partial<object>} data
     */
    updatePosition: (symbol, data) =>
        set((state) => ({
            positions: state.positions.map((p) =>
                p.symbol === symbol ? { ...p, ...data } : p
            ),
        })),

    /**
     * Append a new order to local state (optimistic update).
     * @param {object} order
     */
    addOrder: (order) =>
        set((state) => ({ orders: [order, ...state.orders] })),

    /**
     * Apply a live quote tick to holdings and derived P&L/summary.
     * @param {string} symbol
     * @param {object} quote
     */
    applyLiveQuote: (symbol, quote = {}) =>
        set((state) => {
            if (!symbol) return {};

            const normalize = (s) => {
                if (!s || typeof s !== 'string') return '';
                if (s.startsWith('^') || s.endsWith('.NS') || s.endsWith('.BO')) return s;
                return `${s}.NS`;
            };

            const incoming = normalize(symbol);
            const livePrice = Number(
                quote.price ?? quote.lp ?? quote.ltp ?? quote.last_price
            );

            if (!Number.isFinite(livePrice) || livePrice <= 0) return {};

            let changed = false;
            const holdings = (state.holdings || []).map((h) => {
                const hs = normalize(h.symbol);
                if (hs !== incoming) return h;

                changed = true;
                const quantity = Number(h.quantity ?? 0);
                const avgPrice = Number(h.avg_price ?? 0);
                const investedValue = avgPrice * quantity;
                const currentValue = livePrice * quantity;
                const pnl = currentValue - investedValue;
                // Use absolute invested value so P&L% works for both long and short positions
                const absInvested = Math.abs(investedValue);
                const pnlPercent = absInvested > 0 ? (pnl / absInvested) * 100 : 0;

                return {
                    ...h,
                    current_price: livePrice,
                    current_value: currentValue,
                    invested_value: investedValue,
                    pnl,
                    pnl_percent: pnlPercent,
                };
            });

            if (!changed) return {};

            const invested = holdings.reduce((sum, h) => {
                const qty = Number(h.quantity ?? 0);
                const avg = Number(h.avg_price ?? 0);
                return sum + Number(h.invested_value ?? (avg * qty));
            }, 0);
            const current = holdings.reduce((sum, h) => sum + Number(h.current_value ?? 0), 0);
            const unrealized = holdings.reduce((sum, h) => sum + Number(h.pnl ?? 0), 0);
            const realized = Number(state.summary?.realized_pnl ?? state.pnl?.realized ?? 0);
            const total = realized + unrealized;
            const baseCapital = Number(state.summary?.base_capital ?? 0);
            const pnlDenominator = baseCapital > 0 ? baseCapital : Math.abs(invested);
            const netEquity = baseCapital > 0
                ? baseCapital + total
                : Number(state.summary?.available_capital ?? 0) + current;
            const absInvested = Math.abs(invested);

            const nextSummary = state.summary
                ? {
                    ...state.summary,
                    total_invested: invested,
                    current_value: current,
                    unrealized_pnl: unrealized,
                    realized_pnl: realized,
                    total_pnl: total,
                    total_pnl_percent: pnlDenominator > 0 ? (total / pnlDenominator) * 100 : 0,
                    net_equity: netEquity,
                }
                : state.summary;

            return {
                holdings,
                summary: nextSummary,
                pnl: {
                    realized,
                    unrealized,
                    total,
                },
            };
        }),
}));
