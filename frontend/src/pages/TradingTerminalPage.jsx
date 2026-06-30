// ─── TradingTerminalPage — watchlist wired to store ───────────────────────────
// Watchlist state (items, prices, id) is now owned by useWatchlistStore.
// TradingTerminalPage no longer manages watchlist local state at all.
import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useMarketStore } from '../store/useMarketStore';
import { usePortfolioStore } from '../store/usePortfolioStore';
import { useWatchlistStore } from '../stores/useWatchlistStore';
import { useMarketData } from '../hooks/useMarketData';
import ZebuLiveChart from '../components/trading/ZebuLiveChart';
import { useZeroLossStore } from '../stores/useZeroLossStore';
import Watchlist from '../components/trading/Watchlist';
import OrderPanel from '../components/trading/OrderPanel';
import Modal from '../components/ui/Modal';
import { StrategyDock } from '../strategy/components';
import { runEngine, getAvailableStrategies } from '../strategy';
import ErrorBoundary from '../components/ErrorBoundary';
import { cn } from '../utils/cn';
import { formatPrice, formatPercent, pnlColorClass, cleanSymbol } from '../utils/formatters';
import { getLiveQuoteForSymbol } from '../utils/liveQuote';
import { CHART_PERIODS, DEFAULT_CHART_PERIOD, ORDER_STATUS_CLASS } from '../utils/constants';
import { shouldUseRealtimePrices } from '../market/utils/marketSessionUtils';

const toFiniteNumber = (value) => {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
};

const normalizeDisplayCandles = (rows = []) => {
    const seen = new Map();
    const nowSec = Math.floor(Date.now() / 1000);

    for (const c of rows || []) {
        let time = Number(c?.time);
        if (!Number.isFinite(time) && c?.timestamp != null) {
            time = Number(c.timestamp);
        }

        if (Number.isFinite(time)) {
            if (time > 1e18) time = Math.floor(time / 1_000_000_000);
            else if (time > 1e15) time = Math.floor(time / 1_000_000);
            else if (time > 1e12) time = Math.floor(time / 1_000);
            else time = Math.floor(time);
        }

        const open = toFiniteNumber(c?.open);
        const high = toFiniteNumber(c?.high);
        const low = toFiniteNumber(c?.low);
        const close = toFiniteNumber(c?.close);
        const volume = toFiniteNumber(c?.volume) ?? 0;

        if (!Number.isFinite(time) || open == null || high == null || low == null || close == null) continue;
        if (time < 946684800 || time > nowSec + 7 * 24 * 60 * 60) continue;
        if (open <= 0 || high <= 0 || low <= 0 || close <= 0) continue;

        const candleHigh = Math.max(high, open, close, low);
        const candleLow = Math.min(low, open, close, high);
        const midPrice = (open + close) / 2;
        if (midPrice > 0 && (candleHigh > midPrice * 6 || candleLow < midPrice / 6)) continue;

        seen.set(time, {
            time,
            open,
            high: candleHigh,
            low: candleLow,
            close,
            volume: Math.max(0, volume),
        });
    }

    return [...seen.values()].sort((a, b) => a.time - b.time);
};

const symbolAliases = (symbol = '') => {
    const raw = String(symbol || '').trim().toUpperCase();
    if (!raw) return [];
    const withSuffix = raw.startsWith('^') || raw.endsWith('.NS') || raw.endsWith('.BO')
        ? raw
        : `${raw}.NS`;
    const withoutSuffix = withSuffix.replace(/\.(NS|BO)$/i, '');
    return [...new Set([raw, withSuffix, withoutSuffix])];
};

// ── Compact period dropdown for symbol header bar ─────────────────────────────
function PeriodDropdown({ period, onPeriodChange }) {
    const [open, setOpen] = useState(false);
    const ref = useRef(null);

    useEffect(() => {
        if (!open) return;
        const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
        document.addEventListener('mousedown', h);
        return () => document.removeEventListener('mousedown', h);
    }, [open]);

    const current = CHART_PERIODS[period] || CHART_PERIODS[DEFAULT_CHART_PERIOD];

    return (
        <div className="relative" ref={ref}>
            <button
                onClick={() => setOpen((v) => !v)}
                className={cn(
                    'flex items-center gap-1 px-2.5 py-1.5 rounded-lg border text-xs font-semibold transition-all duration-200',
                    open
                        ? 'bg-primary-600/20 border-primary-500/40 text-primary-600'
                        : 'bg-surface-800/80 border-edge/20 text-gray-400 hover:text-gray-700 hover:border-edge/40'
                )}
            >
                {current.label}
                <svg className={cn('w-3 h-3 transition-transform', open && 'rotate-180')} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                    <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
            </button>
            {open && (
                <div className="absolute top-full right-0 mt-1 w-28 bg-surface-800 border border-edge/10 rounded-xl shadow-panel z-50 animate-slide-in overflow-hidden py-1">
                    {Object.entries(CHART_PERIODS).map(([key, cfg]) => (
                        <button
                            key={key}
                            onClick={() => { onPeriodChange(key); setOpen(false); }}
                            className={cn(
                                'w-full text-left px-3 py-1.5 text-xs font-semibold transition-colors',
                                period === key
                                    ? 'bg-primary-500/15 text-primary-600'
                                    : 'text-gray-400 hover:text-gray-700 hover:bg-overlay/[0.04]'
                            )}
                        >
                            {cfg.label}
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}

// ── Bottom tabs: positions + order history ────────────────────────────────────
function BottomTabs({ holdings, orders, transactions }) {
    const [activeTab, setActiveTab] = useState('positions');
    return (
        <div className="h-[200px] border-t border-slate-200 dark:border-edge/5 flex-shrink-0 flex flex-col bg-white dark:bg-surface-900">
            <div className="flex border-b border-slate-200 dark:border-edge/5 flex-shrink-0">
                {[
                    { key: 'positions', label: `Positions (${holdings.length})` },
                    { key: 'orders', label: `Orders (${orders.length})` },
                    { key: 'trades', label: `Trades (${transactions.length})` },
                ].map(({ key, label }) => (
                    <button key={key} onClick={() => setActiveTab(key)}
                        className={cn(
                            'px-4 py-2 text-xs font-semibold uppercase tracking-wider transition-colors',
                            activeTab === key
                                ? 'text-primary-600 border-b-2 border-primary-500'
                                : 'text-gray-500 hover:text-gray-700'
                        )}>
                        {label}
                    </button>
                ))}
            </div>
            <div className="overflow-y-auto flex-1 px-3 py-2 bg-white dark:bg-surface-900">
                {activeTab === 'positions' ? (
                    holdings.length > 0 ? (
                        <table className="w-full text-xs min-w-[500px]">
                            <thead>
                                <tr className="text-gray-500 uppercase">
                                    <th className="text-left pb-2 font-medium metric-label">Symbol</th>
                                    <th className="text-right pb-2 font-medium metric-label">Qty</th>
                                    <th className="text-right pb-2 font-medium metric-label">Avg</th>
                                    <th className="text-right pb-2 font-medium metric-label">LTP</th>
                                    <th className="text-right pb-2 font-medium metric-label">P&L</th>
                                </tr>
                            </thead>
                            <tbody>
                                {holdings.map((h, i) => {
                                    const qty = Number(h.quantity ?? 0);
                                    const isShort = qty < 0;
                                    return (
                                        <tr key={h.symbol || i} className="border-t border-edge/[0.03] hover:bg-overlay/[0.02] transition-colors">
                                            <td className="py-1.5 font-medium text-heading">
                                                {cleanSymbol(h.symbol)}
                                                {isShort && <span className="ml-1 text-[9px] font-bold text-amber-400">SHORT</span>}
                                            </td>
                                            <td className={cn('py-1.5 text-right font-price tabular-nums', isShort ? 'text-amber-400' : 'text-gray-600')}>{h.quantity}</td>
                                            <td className="py-1.5 text-right font-price text-gray-600 tabular-nums">{formatPrice(h.avg_price)}</td>
                                            <td className="py-1.5 text-right font-price text-heading tabular-nums">{formatPrice(h.current_price)}</td>
                                            <td className={cn('py-1.5 text-right font-price font-medium tabular-nums', pnlColorClass(h.pnl ?? 0))}>
                                                {(h.pnl ?? 0) >= 0 ? '+' : ''}₹{formatPrice(h.pnl ?? 0)}{' '}
                                                ({formatPercent(h.pnl_percent ?? 0)})
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    ) : (
                        <div className="text-center py-6 text-gray-600 text-xs">No open positions. Place a trade to get started.</div>
                    )
                ) : activeTab === 'orders' ? (
                    orders.length > 0 ? (
                        <table className="w-full text-xs min-w-[600px]">
                            <thead>
                                <tr className="text-gray-500 uppercase">
                                    <th className="text-left pb-2 font-medium metric-label">Symbol</th>
                                    <th className="text-left pb-2 font-medium metric-label">Side</th>
                                    <th className="text-left pb-2 font-medium metric-label">Type</th>
                                    <th className="text-right pb-2 font-medium metric-label">Qty</th>
                                    <th className="text-right pb-2 font-medium metric-label">Price</th>
                                    <th className="text-right pb-2 font-medium metric-label">Status</th>
                                </tr>
                            </thead>
                            <tbody>
                                {orders.map((o, i) => (
                                    <tr key={o.id || i} className="border-t border-edge/[0.03] hover:bg-overlay/[0.02] transition-colors">
                                        <td className="py-1.5 font-medium text-heading">{cleanSymbol(o.symbol)}</td>
                                        <td className={cn('py-1.5 font-medium', o.side === 'BUY' ? 'text-bull' : 'text-bear')}>{o.side}</td>
                                        <td className="py-1.5 text-gray-400">{o.order_type}</td>
                                        <td className="py-1.5 text-right font-price text-gray-600 tabular-nums">{o.quantity}</td>
                                        <td className="py-1.5 text-right font-price text-heading tabular-nums">
                                            {formatPrice(o.filled_price ?? o.price ?? null)}
                                        </td>
                                        <td className="py-1.5 text-right">
                                            <span className={cn('text-[11px] px-2 py-0.5 rounded-full font-medium', ORDER_STATUS_CLASS[o.status] || ORDER_STATUS_CLASS.PENDING)}>
                                                {o.status}
                                            </span>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    ) : (
                        <div className="text-center py-6 text-gray-600 text-xs">No orders yet.</div>
                    )
                ) : (
                    transactions.length > 0 ? (
                        <table className="w-full text-xs min-w-[700px]">
                            <thead>
                                <tr className="text-gray-500 uppercase">
                                    <th className="text-left pb-2 font-medium metric-label">Time</th>
                                    <th className="text-left pb-2 font-medium metric-label">Symbol</th>
                                    <th className="text-left pb-2 font-medium metric-label">Side</th>
                                    <th className="text-right pb-2 font-medium metric-label">Qty</th>
                                    <th className="text-right pb-2 font-medium metric-label">Price</th>
                                    <th className="text-right pb-2 font-medium metric-label">Value</th>
                                </tr>
                            </thead>
                            <tbody>
                                {transactions.map((t, i) => {
                                    const txTime = t.created_at
                                        ? new Date(t.created_at).toLocaleTimeString('en-IN', {
                                            hour: '2-digit',
                                            minute: '2-digit',
                                            second: '2-digit',
                                        })
                                        : '--';
                                    return (
                                        <tr key={t.id || i} className="border-t border-edge/[0.03] hover:bg-overlay/[0.02] transition-colors">
                                            <td className="py-1.5 text-gray-500 tabular-nums">{txTime}</td>
                                            <td className="py-1.5 font-medium text-heading">{cleanSymbol(t.symbol)}</td>
                                            <td className={cn('py-1.5 font-medium', t.transaction_type === 'BUY' ? 'text-bull' : 'text-bear')}>
                                                {t.transaction_type}
                                            </td>
                                            <td className="py-1.5 text-right font-price text-gray-600 tabular-nums">{t.quantity}</td>
                                            <td className="py-1.5 text-right font-price text-heading tabular-nums">{formatPrice(t.price)}</td>
                                            <td className="py-1.5 text-right font-price text-heading tabular-nums">
                                                ₹{formatPrice(t.total_value ?? ((t.price ?? 0) * (t.quantity ?? 0)))}
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    ) : (
                        <div className="text-center py-6 text-gray-600 text-xs">No executed trades yet.</div>
                    )
                )}
            </div>
        </div>
    );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function TradingTerminalPage() {
    const [searchParams] = useSearchParams();
    const symbolFromUrl = searchParams.get('symbol') || 'RELIANCE.NS';
    const chartOnly = searchParams.get('chartOnly') === 'true';
    const [selectedSymbol, setSelectedSymbol] = useState(symbolFromUrl);

    useEffect(() => {
        if (symbolFromUrl && symbolFromUrl !== selectedSymbol) {
            setSelectedSymbol(symbolFromUrl);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [symbolFromUrl]);

    const zlConfidence = useZeroLossStore((s) => s.confidence[selectedSymbol] || null);

    const [chartPeriod, setChartPeriod] = useState(DEFAULT_CHART_PERIOD);
    const [isTerminalFocused, setIsTerminalFocused] = useState(false);
    const [strategyDockOpen, setStrategyDockOpen] = useState(false);
    const [watchlistOpen, setWatchlistOpen] = useState(true);
    const [bottomTabsOpen, setBottomTabsOpen] = useState(false);
    const [chartLtp, setChartLtp] = useState(null);
    const [awaitingStablePrice, setAwaitingStablePrice] = useState(true);
    const awaitingStablePriceRef = useRef(true);
    const pendingHistoryPriceRef = useRef(null);
    const stablePriceTimerRef = useRef(null);

    // ── Floating draggable order panel (pinned inside chart area) ────────────
    const [orderPanelOpen, setOrderPanelOpen] = useState(true);
    const [orderPanelPos, setOrderPanelPos] = useState(() => {
        try {
            const saved = localStorage.getItem('alphasync_order_panel_pos_v2');
            // Stored as { x, y } — viewport pixel coords for position:fixed panel.
            // x: null means right-aligned at 12px from right edge.
            return saved ? JSON.parse(saved) : { x: null, y: 60 };
        } catch { return { x: null, y: 60 }; }
    });
    const orderPanelRef = useRef(null);
    const chartContainerRef = useRef(null); // the chart's relative div
    const dragState = useRef({ active: false, ox: 0, oy: 0 });

    const startPanelDrag = useCallback((e) => {
        if (!orderPanelRef.current || !chartContainerRef.current) return;
        e.preventDefault();
        const panelRect = orderPanelRef.current.getBoundingClientRect();
        dragState.current = {
            active: true,
            ox: e.clientX - panelRect.left,
            oy: e.clientY - panelRect.top,
        };
        const onMove = (me) => {
            if (!dragState.current.active) return;
            const PANEL_W = 264, PANEL_H = 320;
            const x = Math.max(0, Math.min(window.innerWidth - PANEL_W, me.clientX - dragState.current.ox));
            const y = Math.max(0, Math.min(window.innerHeight - PANEL_H, me.clientY - dragState.current.oy));
            setOrderPanelPos({ x, y });
        };
        const onUp = () => {
            dragState.current.active = false;
            setOrderPanelPos((pos) => {
                try { localStorage.setItem('alphasync_order_panel_pos_v2', JSON.stringify(pos)); } catch { }
                return pos;
            });
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
        };
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
    }, []);

    // ── Stores ────────────────────────────────────────────────────────────────
    const { holdings, orders, transactions, refreshPortfolio, applyLiveQuote } = usePortfolioStore();
    const liveQuotes = useMarketStore((s) => s.symbols);
    const setGlobalSelectedSymbol = useMarketStore((s) => s.setSelectedSymbol);
    const batchUpdateQuotes = useMarketStore((s) => s.batchUpdateQuotes);

    // ── Watchlist store — single source of truth ──────────────────────────────
    const { loadWatchlist, fetchPrices, updatePrices } = useWatchlistStore();

    // Hook: quote + candles for the selected symbol
    const { quote, candles, candlesSymbol, isLoading: chartLoading, fetchCandles } = useMarketData(selectedSymbol);

    const chartCandles = useMemo(() => {
        const owner = String(candlesSymbol || '').trim().toUpperCase();
        if (!owner) return [];
        const selectedAliases = symbolAliases(selectedSymbol);
        return selectedAliases.includes(owner) ? candles : [];
    }, [candles, candlesSymbol, selectedSymbol]);

    const liveSelectedQuote = useMemo(
        () => getLiveQuoteForSymbol(selectedSymbol, liveQuotes),
        [selectedSymbol, liveQuotes],
    );

    const handleChartPriceUpdate = useCallback((payload) => {
        const payloadSymbol = payload && typeof payload === 'object'
            ? String(payload.symbol || '').trim().toUpperCase()
            : '';
        if (payloadSymbol && !symbolAliases(selectedSymbol).includes(payloadSymbol)) {
            return;
        }

        const source = payload && typeof payload === 'object'
            ? String(payload.source || 'history').toLowerCase()
            : 'history';
        const rawPrice = payload && typeof payload === 'object'
            ? payload.price
            : payload;
        const priceNum = Number(rawPrice);

        if (!Number.isFinite(priceNum) || priceNum <= 0) {
            if (source === 'reset') {
                setChartLtp(null);
                pendingHistoryPriceRef.current = null;
            }
            return;
        }

        const rounded = Number(priceNum.toFixed(2));

        const publishSelectedPrice = (priceValue) => {
            const updates = {};
            const patch = {
                symbol: selectedSymbol,
                price: priceValue,
            };
            for (const key of symbolAliases(selectedSymbol)) {
                updates[key] = patch;
            }
            if (Object.keys(updates).length > 0) {
                updatePrices(updates);
            }
        };

        if (source === 'live') {
            pendingHistoryPriceRef.current = rounded;
            setChartLtp((prev) => (prev === rounded ? prev : rounded));
            awaitingStablePriceRef.current = false;
            setAwaitingStablePrice(false);
            if (stablePriceTimerRef.current) {
                clearTimeout(stablePriceTimerRef.current);
                stablePriceTimerRef.current = null;
            }
            publishSelectedPrice(rounded);
            return;
        }

        // Never let history/timeframe candles drive terminal LTP.
        // Header/watchlist price must come from live tick or quote snapshot only.
        pendingHistoryPriceRef.current = rounded;
    }, [selectedSymbol, updatePrices]);

    const displayQuote = useMemo(() => {
        const baseQuote = {
            ...(quote || {}),
            ...(liveSelectedQuote || {}),
            symbol: selectedSymbol,
            name: liveSelectedQuote?.name || quote?.name || selectedSymbol,
        };

        const chartPrice = toFiniteNumber(chartLtp);
        const normalizedCandles = normalizeDisplayCandles(chartCandles || []);
        const candleClose = toFiniteNumber(normalizedCandles?.[normalizedCandles.length - 1]?.close);

        // Strict source order for header price:
        // 1) chart live close callback.
        // 2) live quote / poll quote.
        // 3) last candle close as a safe fallback.
        const quotePrice = toFiniteNumber(baseQuote.price);
        const resolvedPrice =
            (chartPrice != null && chartPrice > 0) ? chartPrice
                : ((quotePrice != null && quotePrice > 0) ? quotePrice
                    : ((candleClose != null && candleClose > 0) ? candleClose : null));

        const prevClose = toFiniteNumber(baseQuote.prev_close);
        const resolvedChange =
            resolvedPrice != null && prevClose != null && prevClose > 0
                ? Number((resolvedPrice - prevClose).toFixed(2))
                : null;
        const resolvedChangePercent =
            resolvedPrice != null && prevClose != null && prevClose > 0
                ? Number((((resolvedPrice - prevClose) / prevClose) * 100).toFixed(2))
                : null;

        const candleOpen = toFiniteNumber(normalizedCandles?.[normalizedCandles.length - 1]?.open);
        const candleHigh = toFiniteNumber(normalizedCandles?.[normalizedCandles.length - 1]?.high);
        const candleLow = toFiniteNumber(normalizedCandles?.[normalizedCandles.length - 1]?.low);

        return {
            ...baseQuote,
            price: resolvedPrice != null ? Number(resolvedPrice.toFixed(2)) : null,
            change: resolvedChange,
            change_percent: resolvedChangePercent,
            open: candleOpen ?? toFiniteNumber(baseQuote.open),
            high: candleHigh ?? toFiniteNumber(baseQuote.high),
            low: candleLow ?? toFiniteNumber(baseQuote.low),
            prev_close: prevClose ?? toFiniteNumber(baseQuote.prev_close),
        };
    }, [quote, liveSelectedQuote, selectedSymbol, chartCandles, chartLtp]);
    const selectedExchangeLabel = selectedSymbol.endsWith('.BO') ? 'BSE' : 'NSE';

    useEffect(() => {
        setChartLtp(null);
        awaitingStablePriceRef.current = true;
        setAwaitingStablePrice(true);
        pendingHistoryPriceRef.current = null;

        if (stablePriceTimerRef.current) {
            clearTimeout(stablePriceTimerRef.current);
        }

        // If no live update arrives quickly, release with latest history close.
        stablePriceTimerRef.current = setTimeout(() => {
            awaitingStablePriceRef.current = false;
            setAwaitingStablePrice(false);
            const pending = pendingHistoryPriceRef.current;
            if (!Number.isFinite(pending) || pending <= 0) return;

            setChartLtp((prev) => (prev === pending ? prev : pending));

            const releaseUpdates = {};
            const releasePatch = {
                symbol: selectedSymbol,
                price: pending,
            };
            for (const key of symbolAliases(selectedSymbol)) {
                releaseUpdates[key] = releasePatch;
            }
            if (Object.keys(releaseUpdates).length > 0) {
                updatePrices(releaseUpdates);
            }
        }, 1500);

        return () => {
            if (stablePriceTimerRef.current) {
                clearTimeout(stablePriceTimerRef.current);
                stablePriceTimerRef.current = null;
            }
        };
    }, [selectedSymbol, updatePrices]);

    // Compute trend data for chart overlay — deferred so it doesn't block chart render
    const [trendData, setTrendData] = useState(null);
    useEffect(() => {
        if (!chartCandles || chartCandles.length === 0) {
            setTrendData(null);
            return;
        }
        // setTimeout(0) yields to the browser so the chart can paint first
        const id = setTimeout(() => {
            const strategies = getAvailableStrategies();
            const enabledIds = strategies.map((s) => s.id);
            const result = runEngine(chartCandles, enabledIds);
            setTrendData({
                overall: result.overall,
                confidence: result.confidence,
                weightedScore: result.weightedScore ?? 0,
            });
        }, 0);
        return () => clearTimeout(id);
    }, [chartCandles]);

    // Re-fetch candles when period or symbol changes
    useEffect(() => {
        const cfg = CHART_PERIODS[chartPeriod] || CHART_PERIODS[DEFAULT_CHART_PERIOD];
        fetchCandles(cfg.period, cfg.interval);
    }, [selectedSymbol, chartPeriod, fetchCandles]);

    // Load portfolio on mount + poll every 30s as fallback for missed WS events
    useEffect(() => {
        refreshPortfolio();
        const id = setInterval(() => refreshPortfolio(), 30_000);
        return () => clearInterval(id);
    }, [refreshPortfolio]);

    // ── Load watchlist from store on mount ────────────────────────────────────
    useEffect(() => {
        loadWatchlist();
    }, [loadWatchlist]);

    // ── Poll watchlist prices every 5s — sync to other stores in one batch ─
    const syncPricesRef = useRef(null);
    syncPricesRef.current = { batchUpdateQuotes, applyLiveQuote };
    useEffect(() => {
        let mounted = true;
        const poll = async () => {
            await fetchPrices();
            if (!mounted) return;
            // Sync to MarketStore + PortfolioStore using a microtask
            // to batch React updates and reduce cascading re-renders
            const { prices } = useWatchlistStore.getState();
            if (!prices || typeof prices !== 'object') return;
            syncPricesRef.current.batchUpdateQuotes(
                prices,
                shouldUseRealtimePrices() ? 'poll' : 'eod',
            );
            Object.entries(prices).forEach(([symbol, quote]) => {
                if (quote) syncPricesRef.current.applyLiveQuote(symbol, quote);
            });
        };
        poll();
        const id = setInterval(poll, 5_000);
        return () => { mounted = false; clearInterval(id); };
    }, [fetchPrices]);

    const [orderSide, setOrderSide] = useState(null);
    const [orderSideKey, setOrderSideKey] = useState(0);

    // Quick order modal — opens when SELL/EXIT/BUY is clicked from positions/watchlist
    const [quickOrderOpen, setQuickOrderOpen] = useState(false);
    const [quickOrderSymbol, setQuickOrderSymbol] = useState(null);
    const [quickOrderSide, setQuickOrderSide] = useState(null);
    const [quickOrderKey, setQuickOrderKey] = useState(0);

    const handleSelectSymbol = useCallback((symbol) => setSelectedSymbol(symbol), []);

    // Watchlist / position buy/sell → open quick order popup modal
    const handleBuy = useCallback((symbol) => {
        setQuickOrderSymbol(symbol);
        setQuickOrderSide('BUY');
        setQuickOrderKey((k) => k + 1);
        setQuickOrderOpen(true);
    }, []);
    const handleSell = useCallback((symbol) => {
        setQuickOrderSymbol(symbol);
        setQuickOrderSide('SELL');
        setQuickOrderKey((k) => k + 1);
        setQuickOrderOpen(true);
    }, []);

    useEffect(() => {
        setGlobalSelectedSymbol(selectedSymbol);
    }, [selectedSymbol, setGlobalSelectedSymbol]);

    const liveHoldings = useMemo(() => {
        return (holdings || []).map((h) => {
            const symbol = h?.symbol;
            if (!symbol) return h;

            const wsQuote =
                liveQuotes[symbol] ||
                liveQuotes[symbol.replace('.NS', '')] ||
                liveQuotes[`${symbol}.NS`];

            const livePrice = Number(
                wsQuote?.price ?? wsQuote?.lp ?? wsQuote?.ltp ?? wsQuote?.last_price
            );
            if (!Number.isFinite(livePrice) || livePrice <= 0) return h;

            const quantity = Number(h.quantity ?? 0);
            const avgPrice = Number(h.avg_price ?? 0);
            const investedValue = Number(h.invested_value ?? avgPrice * quantity);
            const currentValue = livePrice * quantity;
            const pnl = currentValue - investedValue;
            // For short positions (negative qty/invested), use absolute invested value
            const absInvested = Math.abs(investedValue);
            const pnlPercent = absInvested > 0 ? (pnl / absInvested) * 100 : 0;

            return {
                ...h,
                current_price: livePrice,
                current_value: currentValue,
                pnl,
                pnl_percent: pnlPercent,
            };
        });
    }, [holdings, liveQuotes]);

    return (
        <div
            className="h-full flex overflow-hidden"
            onFocus={() => setIsTerminalFocused(true)}
            onBlur={() => setIsTerminalFocused(false)}
        >
            {/* ── CENTER: Chart + bottom tabs ────────────────────────────── */}
            <div className="flex-1 flex flex-col min-w-0 overflow-hidden relative">
                {/* ── Floating Watchlist overlay ──────────────────────── */}
                {!chartOnly && watchlistOpen && (
                    <>
                        {/* Backdrop */}
                        <div
                            className="absolute inset-0 z-40 bg-black/20 backdrop-blur-[1px]"
                            onClick={() => setWatchlistOpen(false)}
                        />
                        {/* Panel */}
                        <div className="absolute left-0 top-0 h-full w-[220px] z-50 flex flex-col shadow-2xl border-r border-edge/10 bg-surface-900">
                            <Watchlist
                                selectedSymbol={selectedSymbol}
                                selectedSymbolPrice={chartLtp}
                                suppressSelectedPrice={awaitingStablePrice}
                                onSelectSymbol={(sym) => { handleSelectSymbol(sym); setWatchlistOpen(false); }}
                                onBuy={handleBuy}
                                onSell={handleSell}
                                onClose={() => setWatchlistOpen(false)}
                            />
                        </div>
                    </>
                )}

                {/* Symbol header bar */}
                {!chartOnly && (
                    <div className="flex items-center gap-4 px-4 py-2.5 border-b border-edge/5 bg-surface-900/30 flex-shrink-0">
                    <div>
                        <h2 className="text-lg font-display font-semibold text-heading leading-none">
                            {cleanSymbol(selectedSymbol)}
                        </h2>
                        <span className="text-[11px] text-gray-500">{displayQuote?.name || selectedSymbol} • {selectedExchangeLabel}</span>
                    </div>

                    <div className={cn("flex items-baseline gap-3 transition-opacity duration-300", displayQuote?.price != null ? "opacity-100" : "opacity-0")}>
                        <span className="text-2xl font-semibold font-price text-heading tabular-nums">
                            {displayQuote?.price != null ? formatPrice(displayQuote.price) : '—'}
                        </span>
                        {displayQuote?.change != null && (
                            <span className={cn('text-sm font-price font-semibold tabular-nums', pnlColorClass(displayQuote.change))}>
                                {displayQuote.change >= 0 ? '▲' : '▼'}{' '}
                                {displayQuote.change >= 0 ? '+' : ''}{formatPrice(displayQuote.change)}{' '}
                                ({formatPercent(displayQuote.change_percent)})
                            </span>
                        )}
                    </div>

                    {/* Spacer + right-aligned controls */}
                    <div className="flex items-center gap-2 ml-auto">
                        {/* OHLC — xl only */}
                        <div className="hidden xl:flex items-center gap-4 text-xs text-gray-500 mr-2">
                            {[
                                ['Open', displayQuote?.open],
                                ['High', displayQuote?.high],
                                ['Low', displayQuote?.low],
                                ['Prev', displayQuote?.prev_close],
                            ].map(([label, val]) => val != null && (
                                <div key={label} className="flex items-center gap-1">
                                    <span className="metric-label text-[10px]">{label}</span>
                                    <span className="font-price text-gray-400 tabular-nums">{formatPrice(val)}</span>
                                </div>
                            ))}
                        </div>

                        {/* Watchlist toggle */}
                        <button
                            onClick={() => setWatchlistOpen((v) => !v)}
                            className={cn(
                                'flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-xs font-semibold transition-all duration-200',
                                watchlistOpen
                                    ? 'bg-primary-600/20 border-primary-500/40 text-primary-600'
                                    : 'bg-surface-800/80 border-edge/20 text-gray-400 hover:text-gray-700 hover:border-edge/40'
                            )}
                            title="Toggle Watchlist"
                        >
                            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <path d="M4 6h16M4 10h16M4 14h10M4 18h6" strokeLinecap="round" strokeLinejoin="round" />
                            </svg>
                            Watchlist
                        </button>

                        {/* Period dropdown */}
                        <PeriodDropdown period={chartPeriod} onPeriodChange={setChartPeriod} />

                        {/* Strategy toggle */}
                        <button
                            onClick={() => setStrategyDockOpen((v) => !v)}
                            className={cn(
                                'flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-xs font-semibold transition-all duration-200',
                                strategyDockOpen
                                    ? 'bg-primary-600/20 border-primary-500/40 text-primary-600'
                                    : 'bg-surface-800/80 border-edge/20 text-gray-400 hover:text-gray-700 hover:border-edge/40'
                            )}
                            title="Toggle Strategy Dock"
                        >
                            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <path d="M12 20V10M18 20V4M6 20v-4" strokeLinecap="round" strokeLinejoin="round" />
                            </svg>
                            Strategies
                        </button>

                        {/* Order Panel toggle */}
                        <button
                            onClick={() => setOrderPanelOpen((v) => !v)}
                            className={cn(
                                'flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-xs font-semibold transition-all duration-200',
                                orderPanelOpen
                                    ? 'bg-emerald-500/20 border-emerald-500/40 text-emerald-600'
                                    : 'bg-surface-800/80 border-edge/20 text-gray-400 hover:text-gray-700 hover:border-edge/40'
                            )}
                            title="Toggle Order Panel"
                        >
                            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <rect x="3" y="3" width="18" height="18" rx="2" />
                                <path d="M9 9h6M9 12h6M9 15h4" strokeLinecap="round" />
                            </svg>
                            Order Panel
                        </button>
                    </div>
                )}

                {/* Chart — fills remaining height */}
                <div ref={chartContainerRef} className={cn('min-h-0 relative', chartOnly || bottomTabsOpen ? 'flex-1' : 'flex-[1_1_0%]')}>
                    <ErrorBoundary fallback="Chart failed to load. Please refresh.">
                        <ZebuLiveChart
                            candles={chartCandles}
                            period={chartPeriod}
                            isLoading={chartLoading}
                            symbol={selectedSymbol}
                            trendData={trendData}
                            zeroLossTrend={zlConfidence}
                            onPeriodChange={setChartPeriod}
                            onPriceUpdate={handleChartPriceUpdate}
                        />
                    </ErrorBoundary>
                </div>

                {/* Bottom tabs (collapsible) */}
                {!chartOnly && (
                    <div className="border-t border-slate-200 dark:border-edge/5 bg-white dark:bg-surface-900">
                    <button
                        onClick={() => setBottomTabsOpen((v) => !v)}
                        className="w-full h-7 flex items-center justify-center gap-2 bg-gray-100 dark:bg-surface-800 hover:bg-gray-200 dark:hover:bg-surface-700 text-gray-500 hover:text-primary-600 transition-colors text-[11px] font-semibold tracking-wide"
                    >
                        <svg className={cn('w-3.5 h-3.5 transition-transform duration-200', bottomTabsOpen ? 'rotate-0' : 'rotate-180')} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
                        POSITIONS ({liveHoldings.length}) &middot; ORDERS ({orders.length}) &middot; TRADES ({transactions.length})
                    </button>
                    {bottomTabsOpen && (
                        <BottomTabs
                            holdings={liveHoldings}
                            orders={orders}
                            transactions={transactions}
                        />
                    )}
                </div>
            </div>

            {/* ── Floating draggable order panel ────────────────────────── */}
            {orderPanelOpen && (
                <div
                    ref={orderPanelRef}
                    style={{
                        position: 'fixed',
                        left: orderPanelPos.x != null ? orderPanelPos.x : 'auto',
                        right: orderPanelPos.x == null ? '12px' : 'auto',
                        top: orderPanelPos.y ?? 60,
                        width: '264px',
                        zIndex: 150,
                        borderRadius: '12px',
                        overflow: 'hidden',
                        boxShadow: '0 8px 40px rgba(0,0,0,0.45), 0 0 0 1px rgba(255,255,255,0.07)',
                        background: 'var(--surface-900, #0f1117)',
                    }}
                >
                    {/* Drag handle */}
                    <div
                        onMouseDown={startPanelDrag}
                        style={{ cursor: 'grab', userSelect: 'none' }}
                        className="flex items-center justify-between px-3 py-1.5 border-b border-edge/10 bg-surface-800/80"
                    >
                        <div className="flex items-center gap-1.5">
                            <svg className="w-3 h-3 text-gray-500" viewBox="0 0 24 24" fill="currentColor">
                                <circle cx="8" cy="6" r="1.5" /><circle cx="16" cy="6" r="1.5" />
                                <circle cx="8" cy="12" r="1.5" /><circle cx="16" cy="12" r="1.5" />
                                <circle cx="8" cy="18" r="1.5" /><circle cx="16" cy="18" r="1.5" />
                            </svg>
                            <span className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">Order Panel</span>
                        </div>
                        <button
                            onMouseDown={(e) => e.stopPropagation()}
                            onClick={() => setOrderPanelOpen(false)}
                            className="text-gray-600 hover:text-gray-400 transition-colors text-sm leading-none w-5 h-5 flex items-center justify-center rounded"
                        >
                            ×
                        </button>
                    </div>
                    <OrderPanel
                        symbol={selectedSymbol}
                        currentPrice={displayQuote?.price ?? 0}
                        isTerminalFocused={isTerminalFocused}
                        initialSide={orderSide}
                        initialSideKey={orderSideKey}
                        isFloating
                    />
                </div>
            )}

            {/* ── Floating Strategy Dock popup ───────────────────────────── */}
            <ErrorBoundary fallback="Strategy dock failed to load.">
                <StrategyDock
                    candles={chartCandles}
                    isOpen={strategyDockOpen}
                    onClose={() => setStrategyDockOpen(false)}
                />
            </ErrorBoundary>

            {/* ── Quick Order Modal (positions SELL/EXIT/BUY popup) ──── */}
            <Modal
                isOpen={quickOrderOpen}
                onClose={() => setQuickOrderOpen(false)}
                title={`${quickOrderSide === 'BUY' ? 'Buy / Exit Short' : 'Sell'} — ${cleanSymbol(quickOrderSymbol) || ''}`}
                size="sm"
                className="!max-w-[360px]"
            >
                <div className="overflow-y-auto max-h-[80vh]">
                    <OrderPanel
                        symbol={quickOrderSymbol || selectedSymbol}
                        currentPrice={liveQuotes[quickOrderSymbol]?.price ?? 0}
                        initialSide={quickOrderSide}
                        initialSideKey={quickOrderKey}
                        isFloating={true}
                    />
                </div>
            </Modal>
        </div>
    );
}
