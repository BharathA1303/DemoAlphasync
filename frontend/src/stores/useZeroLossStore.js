import { create } from 'zustand';
import api from '../services/api';

/**
 * ZeroLoss Strategy store — real-time state via WebSocket + REST fallback.
 *
 * WebSocket messages (channel: "zeroloss") update confidence, positions,
 * and stats in real time. REST calls provide initial load + history.
 */
export const useZeroLossStore = create((set, get) => ({
    // ── State ────────────────────────────────────────────────────────────────
    enabled: false,
    symbols: [],
    confidence: {},          // symbol → { score, direction, breakdown, ... }
    activePositions: {},     // symbol → position dict
    stats: {},               // { today_trades, today_profit, today_breakeven, today_pnl }
    signals: [],             // signal history
    trades: [],              // ZeroLoss-tagged orders from /orders
    performance: null,       // { records, summary }
    loading: true,
    lastUpdate: null,
    liveLog: [],             // Real-time activity log (last 50 entries)

    // ── REST Actions (initial load + manual refresh) ─────────────────────────

    fetchAll: async () => {
        try {
            const [statusRes, signalsRes, perfRes, tradesRes] = await Promise.allSettled([
                api.get('/zeroloss/status'),
                api.get('/zeroloss/signals?limit=50'),
                api.get('/zeroloss/performance?days=30'),
                api.get('/orders?limit=100'),
            ]);

            const update = { loading: false, lastUpdate: Date.now() };

            if (statusRes.status === 'fulfilled') {
                const d = statusRes.value.data;
                update.enabled = d.enabled;
                update.symbols = d.symbols || [];
                update.confidence = d.confidence || {};
                update.activePositions = d.active_positions || {};
                update.stats = d.stats || {};
            }
            if (signalsRes.status === 'fulfilled') {
                update.signals = signalsRes.value.data.signals || [];
            }
            if (perfRes.status === 'fulfilled') {
                update.performance = perfRes.value.data;
            }
            if (tradesRes.status === 'fulfilled') {
                const allOrders = tradesRes.value.data.orders || [];
                update.trades = allOrders.filter((o) => o.tag === 'ZEROLOSS');
            }

            set(update);
        } catch (err) {
            console.error('ZeroLoss fetch error:', err);
            set({ loading: false });
        }
    },

    toggle: async () => {
        try {
            const res = await api.post('/zeroloss/toggle');
            const update = { enabled: res.data.enabled };
            // When strategy is stopped, clear active positions from UI
            if (!res.data.enabled) {
                update.activePositions = {};
            }
            set(update);
            return res.data;
        } catch (err) {
            console.error('ZeroLoss toggle error:', err);
            throw err;
        }
    },

    // ── Push a log entry to the live activity feed ────────────────────────────
    _pushLog: (entry) => {
        set((state) => ({
            liveLog: [{ ...entry, ts: Date.now() }, ...state.liveLog].slice(0, 50),
        }));
    },

    // ── WebSocket Handlers (called from useWebSocket) ────────────────────────

    /** Handle any zeroloss channel message */
    handleWsMessage: (data) => {
        const msgType = data.type || data.data?.type;
        const payload = data.data || data;
        const pushLog = get()._pushLog;

        switch (msgType) {
            case 'confidence_update':
            case 'algo_signal': {
                // Update confidence for the symbol
                const conf = payload.confidence;
                if (conf?.symbol) {
                    set((state) => ({
                        confidence: {
                            ...state.confidence,
                            [conf.symbol]: conf,
                        },
                        stats: payload.stats || state.stats,
                        lastUpdate: Date.now(),
                    }));
                    pushLog({
                        type: 'scan',
                        symbol: conf.symbol,
                        message: `Scanned ${conf.symbol.replace('.NS', '')} — ${conf.direction} ${Math.round(conf.score)}%`,
                        direction: conf.direction,
                        score: conf.score,
                    });
                }
                break;
            }

            case 'algo_trade': {
                // Position entry or exit
                const action = payload.action;
                const signal = payload.signal;
                if (!signal?.symbol) break;
                const sym = signal.symbol.replace('.NS', '');

                if (action === 'ENTRY') {
                    set((state) => ({
                        activePositions: {
                            ...state.activePositions,
                            [signal.symbol]: signal,
                        },
                        stats: payload.stats || { ...state.stats, today_trades: (state.stats.today_trades || 0) + 1 },
                        lastUpdate: Date.now(),
                    }));
                    pushLog({
                        type: 'entry',
                        symbol: signal.symbol,
                        message: `ENTERED ${signal.direction} on ${sym} @ ₹${signal.entry_price?.toFixed(2)}`,
                        direction: signal.direction,
                        price: signal.entry_price,
                    });
                } else if (action === 'EXIT' || action === 'FORCE_CLOSE') {
                    set((state) => {
                        const positions = { ...state.activePositions };
                        delete positions[signal.symbol];
                        const stats = payload.stats ? { ...payload.stats } : { ...state.stats };
                        const pnl = payload.pnl || 0;
                        if (!payload.stats) {
                            if (payload.reason === 'PROFIT') {
                                stats.today_profit = (stats.today_profit || 0) + 1;
                            } else if (pnl >= 0) {
                                stats.today_breakeven = (stats.today_breakeven || 0) + 1;
                            } else {
                                stats.today_losses = (stats.today_losses || 0) + 1;
                            }
                            stats.today_pnl = (stats.today_pnl || 0) + pnl;
                        }
                        return { activePositions: positions, stats, lastUpdate: Date.now() };
                    });
                    const pnl = payload.pnl || 0;
                    const reason = action === 'FORCE_CLOSE' ? 'FORCE CLOSE' : payload.reason;
                    pushLog({
                        type: payload.reason === 'PROFIT' ? 'profit' : 'stoploss',
                        symbol: signal.symbol,
                        message: `EXITED ${sym} — ${reason} | P&L: ₹${pnl.toFixed(2)}`,
                        pnl,
                    });
                }
                break;
            }

            default:
                // Update stats if present
                if (payload.stats) {
                    set({ stats: payload.stats, lastUpdate: Date.now() });
                }
        }
    },
}));
