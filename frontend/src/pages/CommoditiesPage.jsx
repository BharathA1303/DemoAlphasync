import { useEffect, useMemo, useRef, useState } from 'react';
import {
    BarChart3,
    PanelLeftClose,
    PanelLeftOpen,
    Plus,
    Search,
    Shield,
    Star,
    Trash2,
    X,
} from 'lucide-react';
import { useCommodityStore } from '../stores/useCommodityStore';
import { useMarketStore } from '../store/useMarketStore';
import { usePortfolioStore } from '../store/usePortfolioStore';
import { useWebSocket } from '../hooks/useWebSocket';
import { useMarketData } from '../hooks/useMarketData';
import ZebuLiveChart from '../components/trading/ZebuLiveChart';
import OrderPanel from '../components/trading/OrderPanel';
import { PositionsPanel, OpenLotsPanel, OrderHistoryPanel } from '../panels';
import { CHART_PERIODS, DEFAULT_CHART_PERIOD, DEFAULT_MCX_WATCHLIST, MCX_SYMBOLS } from '../utils/constants';
import { formatPercent, pnlColorClass } from '../utils/formatters';
import { getLiveQuoteForSymbol } from '../utils/liveQuote';
import { cn } from '../utils/cn';

const STORAGE_KEY = 'alphasync_mcx_watchlist_v2';
const COMMODITY_POLL_MS = 3_000; // Always poll every 3s — MCX WS resolution can be slow

const MCX_META = {
    GOLD: { name: 'Gold', category: 'metals', unit: 'per 10g' },
    GOLDM: { name: 'Gold Mini', category: 'metals', unit: 'per 10g' },
    GOLDGUINEA: { name: 'Gold Guinea', category: 'metals', unit: 'per 8g' },
    GOLDPETAL: { name: 'Gold Petal', category: 'metals', unit: 'per 1g' },
    SILVER: { name: 'Silver', category: 'metals', unit: 'per kg' },
    SILVERM: { name: 'Silver Mini', category: 'metals', unit: 'per kg' },
    SILVERMIC: { name: 'Silver Micro', category: 'metals', unit: 'per kg' },
    COPPER: { name: 'Copper', category: 'metals', unit: 'per kg' },
    COPPERM: { name: 'Copper Mini', category: 'metals', unit: 'per kg' },
    ALUMINIUM: { name: 'Aluminium', category: 'metals', unit: 'per kg' },
    ALUMINI: { name: 'Aluminium Mini', category: 'metals', unit: 'per kg' },
    ZINC: { name: 'Zinc', category: 'metals', unit: 'per kg' },
    ZINCMINI: { name: 'Zinc Mini', category: 'metals', unit: 'per kg' },
    LEAD: { name: 'Lead', category: 'metals', unit: 'per kg' },
    LEADMINI: { name: 'Lead Mini', category: 'metals', unit: 'per kg' },
    NICKEL: { name: 'Nickel', category: 'metals', unit: 'per kg' },
    CRUDEOIL: { name: 'Crude Oil', category: 'energy', unit: 'per bbl' },
    CRUDEOILM: { name: 'Crude Oil Mini', category: 'energy', unit: 'per bbl' },
    NATURALGAS: { name: 'Natural Gas', category: 'energy', unit: 'per MMBtu' },
    NATGASMINI: { name: 'Nat Gas Mini', category: 'energy', unit: 'per MMBtu' },
    COTTONCNDY: { name: 'Cotton Candy', category: 'agriculture', unit: 'per candy' },
    KAPAS: { name: 'Kapas', category: 'agriculture', unit: 'per 20kg' },
    MENTHOIL: { name: 'Mentha Oil', category: 'agriculture', unit: 'per kg' },
};

const CATEGORY_LABELS = {
    all: 'All MCX',
    metals: 'Metals',
    energy: 'Energy',
    agriculture: 'Agri',
};

const toNumber = (value) => {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
};

const clean = (symbol) => String(symbol || '').trim().toUpperCase();
const priceOf = (q) => toNumber(q?.price ?? q?.ltp ?? q?.lp ?? q?.last_price) ?? 0;

const loadSavedWatchlist = () => {
    try {
        const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
        if (Array.isArray(parsed) && parsed.length > 0) {
            return parsed.map(clean).filter((sym) => MCX_SYMBOLS.has(sym));
        }
    } catch {
        /* ignore corrupted storage */
    }
    return [...DEFAULT_MCX_WATCHLIST];
};

function WatchlistRow({ item, selected, onSelect, onDelete, flash }) {
    const price = priceOf(item);
    const change = Number(item?.change ?? 0);
    const pct = Number(item?.change_percent ?? 0);

    return (
        <div
            className={cn(
                'group grid grid-cols-[1fr_auto_auto] items-center gap-2 border-b border-white/[0.06] px-3 py-2.5 cursor-pointer transition-colors',
                selected
                    ? 'bg-cyan-500/10 border-l-2 border-l-cyan-500'
                    : 'hover:bg-white/[0.04]',
            )}
            onClick={() => onSelect(item.symbol)}
        >
            <div className="min-w-0">
                <div className="flex items-center gap-1.5">
                    <span className="truncate text-[13px] font-semibold text-heading leading-tight">{item.symbol}</span>
                    <span className="flex-shrink-0 rounded-sm bg-blue-500/15 px-1 py-0 text-[9px] font-bold text-blue-400 uppercase tracking-wide">MCX</span>
                </div>
                <span className="text-[10px] text-muted truncate block mt-0.5">{item.name || item.symbol}</span>
            </div>

            <div className="text-right min-w-[72px]">
                <div
                    className={cn(
                        'font-price text-[13px] font-semibold tabular-nums text-heading transition-colors',
                        flash === 'up' && 'text-emerald-400',
                        flash === 'down' && 'text-red-400',
                    )}
                >
                    {price > 0 ? price.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'}
                </div>
                <div className={cn('font-price text-[11px] tabular-nums', pnlColorClass(change))}>
                    {change !== 0
                        ? `${change > 0 ? '+' : ''}${change.toFixed(2)}`
                        : ''}{' '}
                    <span className="opacity-80">{pct !== 0 ? formatPercent(pct) : '—'}</span>
                </div>
            </div>

            <button
                type="button"
                title="Remove"
                onClick={(e) => { e.stopPropagation(); onDelete(item.symbol); }}
                className="grid h-6 w-6 flex-shrink-0 place-items-center rounded text-muted opacity-0 transition-opacity hover:bg-red-500/10 hover:text-red-400 group-hover:opacity-100"
            >
                <Trash2 className="h-3 w-3" />
            </button>
        </div>
    );
}

export default function CommoditiesPage() {
    const { status: wsStatus, subscribe } = useWebSocket();
    const quotes = useCommodityStore((s) => s.quotes);
    const isLoadingQuotes = useCommodityStore((s) => s.isLoading);
    const error = useCommodityStore((s) => s.error);
    const fetchCommodities = useCommodityStore((s) => s.fetchCommodities);
    const applyTick = useCommodityStore((s) => s.applyTick);
    const getFlash = useCommodityStore((s) => s.getFlash);
    const markWsReconnect = useCommodityStore((s) => s.markWsReconnect);
    const marketSymbols = useMarketStore((s) => s.symbols);
    const { holdings, orders, openLots, refreshPortfolio } = usePortfolioStore();

    const [watchlist, setWatchlist] = useState(loadSavedWatchlist);
    const [selectedSymbol, setSelectedSymbol] = useState(() => watchlist[0] || DEFAULT_MCX_WATCHLIST[0]);
    const [chartPeriod, setChartPeriod] = useState(DEFAULT_CHART_PERIOD);
    const [activeCategory, setActiveCategory] = useState('all');
    const [searchQuery, setSearchQuery] = useState('');
    const [addSymbol, setAddSymbol] = useState('');
    const [leftOpen, setLeftOpen] = useState(true);
    const [orderOpen, setOrderOpen] = useState(false);
    const [orderSide, setOrderSide] = useState('BUY');
    const [orderKey, setOrderKey] = useState(0);
    const [bottomTab, setBottomTab] = useState('positions');
    const prevWsStatus = useRef(wsStatus);

    const { quote: chartQuote, candles, candlesSymbol, isLoading: isChartLoading, fetchCandles } = useMarketData(
        selectedSymbol,
        { pollInterval: wsStatus === 'connected' ? 0 : 5_000 },
    );

    // Persist watchlist
    useEffect(() => {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(watchlist));
    }, [watchlist]);

    // Track WS reconnect to invalidate stale REST cache
    useEffect(() => {
        if (wsStatus === 'connected' && prevWsStatus.current !== 'connected') markWsReconnect();
        prevWsStatus.current = wsStatus;
    }, [wsStatus, markWsReconnect]);

    // Initial load + portfolio
    useEffect(() => {
        fetchCommodities();
        refreshPortfolio();
    }, [fetchCommodities, refreshPortfolio]);

    // Always poll at 3s — MCX WebSocket token resolution can be slow/unreliable.
    // This ensures prices are live even without a working WS subscription.
    useEffect(() => {
        const id = setInterval(fetchCommodities, COMMODITY_POLL_MS);
        return () => clearInterval(id);
    }, [fetchCommodities]);

    // Discovered MCX symbols from the commodity quotes store
    const discoveredSymbols = useMemo(() => {
        const out = [];
        for (const sym of Object.keys(quotes || {})) {
            const value = clean(sym);
            if (MCX_SYMBOLS.has(value)) out.push(value);
        }
        return out;
    }, [quotes]);

    const subscriptionSymbols = useMemo(
        () => [...new Set([...watchlist, ...discoveredSymbols])],
        [watchlist, discoveredSymbols],
    );
    const subscriptionKey = subscriptionSymbols.join('|');

    // Subscribe to Zebu WS for real-time MCX ticks
    useEffect(() => {
        if (subscriptionSymbols.length > 0) subscribe(subscriptionSymbols);
    }, [subscribe, subscriptionKey]); // eslint-disable-line react-hooks/exhaustive-deps

    // Apply any WS ticks that arrived via market store
    useEffect(() => {
        for (const sym of subscriptionSymbols) {
            const wsQuote = getLiveQuoteForSymbol(sym, marketSymbols);
            if (wsQuote && priceOf(wsQuote) > 0) applyTick(sym, wsQuote);
        }
    }, [marketSymbols, applyTick, subscriptionKey]); // eslint-disable-line react-hooks/exhaustive-deps

    // Fetch chart candles when symbol or period changes
    useEffect(() => {
        const cfg = CHART_PERIODS[chartPeriod] || CHART_PERIODS[DEFAULT_CHART_PERIOD];
        fetchCandles(cfg.period, cfg.interval);
    }, [selectedSymbol, chartPeriod, fetchCandles]);

    const makeItem = (symbol) => {
        const quote = quotes[symbol] || {};
        const meta = MCX_META[symbol] || {};
        return {
            ...meta,
            ...quote,
            symbol,
            name: quote.name || meta.name || symbol,
            category: quote.category || meta.category || 'other',
            unit: quote.unit || meta.unit || 'per unit',
            exchange: 'MCX',
            price: priceOf(quote),
        };
    };

    const watchlistItems = useMemo(() => watchlist.map(makeItem), [watchlist, quotes]); // eslint-disable-line react-hooks/exhaustive-deps

    const filteredWatchlist = useMemo(() => {
        const query = searchQuery.trim().toUpperCase();
        return watchlistItems.filter((item) => {
            if (activeCategory !== 'all' && item.category !== activeCategory) return false;
            if (!query) return true;
            return item.symbol.includes(query) || String(item.name || '').toUpperCase().includes(query);
        });
    }, [watchlistItems, activeCategory, searchQuery]);

    const addCurrentSymbol = () => {
        const sym = clean(addSymbol);
        if (!sym || !MCX_SYMBOLS.has(sym) || watchlist.includes(sym)) return;
        setWatchlist((items) => [...items, sym]);
        setSelectedSymbol(sym);
        setAddSymbol('');
    };

    const deleteSymbol = (symbol) => {
        setWatchlist((items) => {
            const next = items.filter((s) => s !== symbol);
            if (symbol === selectedSymbol) setSelectedSymbol(next[0] || DEFAULT_MCX_WATCHLIST[0]);
            return next.length ? next : [DEFAULT_MCX_WATCHLIST[0]];
        });
    };

    const selectedQuote = useMemo(() => {
        const live = getLiveQuoteForSymbol(selectedSymbol, marketSymbols) || {};
        const commodity = quotes[selectedSymbol] || {};
        const meta = MCX_META[selectedSymbol] || {};
        const generic = chartQuote || {};
        return {
            ...generic,
            ...meta,
            ...commodity,
            ...live,
            symbol: selectedSymbol,
            name: live.name || commodity.name || meta.name || selectedSymbol,
            exchange: 'MCX',
            price: priceOf(live) || priceOf(commodity) || priceOf(generic),
            unit: live.unit || commodity.unit || meta.unit || 'per unit',
        };
    }, [selectedSymbol, marketSymbols, quotes, chartQuote]);

    const chartCandles = useMemo(
        () => (clean(candlesSymbol) === clean(selectedSymbol) ? candles : []),
        [candles, candlesSymbol, selectedSymbol],
    );
    const selectedChange = Number(selectedQuote?.change ?? 0);
    const selectedPct = Number(selectedQuote?.change_percent ?? 0);
    const selectedLivePrice = priceOf(selectedQuote) || undefined;

    const mcxHoldings = useMemo(
        () => (holdings || []).filter((h) => String(h.exchange || '').toUpperCase() === 'MCX' || MCX_SYMBOLS.has(clean(h.symbol))),
        [holdings],
    );
    const mcxOrders = useMemo(
        () => (orders || []).filter((o) => String(o.exchange || '').toUpperCase() === 'MCX' || MCX_SYMBOLS.has(clean(o.symbol))),
        [orders],
    );
    const mcxLots = useMemo(
        () => (openLots || []).filter((l) => String(l.exchange || '').toUpperCase() === 'MCX' || MCX_SYMBOLS.has(clean(l.symbol))),
        [openLots],
    );

    const openOrderPanel = (side = 'BUY') => {
        setOrderSide(side);
        setOrderKey((v) => v + 1);
        setOrderOpen(true);
    };

    return (
        <div className="relative flex h-[calc(100vh-56px)] min-h-0 overflow-hidden bg-surface-950 text-heading">

            {/* ── Left Watchlist ── */}
            {leftOpen && (
                <aside className="hidden w-[300px] min-w-[300px] flex-col border-r border-white/[0.07] bg-surface-950/60 lg:flex">
                    {/* Header */}
                    <div className="flex h-11 flex-shrink-0 items-center justify-between border-b border-white/[0.07] px-3">
                        <button
                            type="button"
                            title="Collapse watchlist"
                            onClick={() => setLeftOpen(false)}
                            className="grid h-7 w-7 place-items-center rounded-md text-muted hover:bg-white/[0.06] hover:text-heading"
                        >
                            <PanelLeftClose className="h-3.5 w-3.5" />
                        </button>
                        <span className="text-[13px] font-semibold text-heading">MCX Watchlist</span>
                        <span className="rounded-full bg-white/[0.07] px-2 py-0.5 font-price text-[11px] tabular-nums text-muted">
                            {watchlist.length}
                        </span>
                    </div>

                    {/* Search + Add */}
                    <div className="flex-shrink-0 border-b border-white/[0.06] px-3 py-2.5 space-y-2">
                        <div className="relative">
                            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted pointer-events-none" />
                            <input
                                value={searchQuery}
                                onChange={(e) => setSearchQuery(e.target.value)}
                                placeholder="Search MCX..."
                                className="h-8 w-full rounded-md border border-white/[0.08] bg-white/[0.05] pl-8 pr-3 text-[12px] text-heading outline-none placeholder:text-muted focus:border-cyan-500/50 focus:bg-white/[0.07]"
                            />
                        </div>
                        <div className="flex gap-1.5">
                            <input
                                value={addSymbol}
                                onChange={(e) => setAddSymbol(e.target.value.toUpperCase())}
                                onKeyDown={(e) => { if (e.key === 'Enter') addCurrentSymbol(); }}
                                placeholder="Add symbol (e.g. GOLD)..."
                                className="h-8 min-w-0 flex-1 rounded-md border border-white/[0.08] bg-white/[0.05] px-2.5 text-[12px] text-heading outline-none placeholder:text-muted focus:border-cyan-500/50"
                            />
                            <button
                                type="button"
                                title="Add MCX symbol"
                                onClick={addCurrentSymbol}
                                className="grid h-8 w-8 flex-shrink-0 place-items-center rounded-md border border-white/[0.08] bg-white/[0.05] text-muted hover:bg-white/[0.09] hover:text-heading"
                            >
                                <Plus className="h-3.5 w-3.5" />
                            </button>
                        </div>
                        {/* Category filter */}
                        <div className="grid grid-cols-4 gap-1">
                            {Object.entries(CATEGORY_LABELS).map(([key, label]) => (
                                <button
                                    key={key}
                                    type="button"
                                    onClick={() => setActiveCategory(key)}
                                    className={cn(
                                        'h-7 rounded-md text-[11px] font-medium transition-colors',
                                        activeCategory === key
                                            ? 'bg-cyan-500/15 text-cyan-400'
                                            : 'text-muted hover:bg-white/[0.05] hover:text-heading',
                                    )}
                                >
                                    {label}
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* List */}
                    <div className="min-h-0 flex-1 overflow-y-auto">
                        {filteredWatchlist.length > 0 ? (
                            filteredWatchlist.map((item) => (
                                <WatchlistRow
                                    key={item.symbol}
                                    item={item}
                                    selected={item.symbol === selectedSymbol}
                                    flash={getFlash(item.symbol)}
                                    onSelect={setSelectedSymbol}
                                    onDelete={deleteSymbol}
                                />
                            ))
                        ) : (
                            <div className="flex items-center justify-center py-10 text-[12px] text-muted">
                                No symbols match filter
                            </div>
                        )}
                    </div>

                    {error && (
                        <div className="flex-shrink-0 border-t border-red-500/20 bg-red-500/5 px-3 py-2 text-[11px] text-red-400">
                            {error}
                        </div>
                    )}
                </aside>
            )}

            {/* ── Center: Chart area ── */}
            <main className="flex min-w-0 flex-1 flex-col">

                {/* Top bar — instrument header */}
                <div className="flex h-12 flex-shrink-0 items-center gap-3 border-b border-white/[0.07] bg-surface-950/40 px-4">
                    {!leftOpen && (
                        <button
                            type="button"
                            title="Open watchlist"
                            onClick={() => setLeftOpen(true)}
                            className="grid h-7 w-7 flex-shrink-0 place-items-center rounded-md text-muted hover:bg-white/[0.06] hover:text-heading"
                        >
                            <PanelLeftOpen className="h-3.5 w-3.5" />
                        </button>
                    )}

                    {/* Symbol + exchange */}
                    <div className="min-w-0">
                        <div className="flex items-center gap-2">
                            <span className="truncate text-[15px] font-bold text-heading">{selectedSymbol}</span>
                            <span className="flex-shrink-0 rounded-sm bg-blue-500/15 px-1.5 py-0.5 text-[10px] font-bold text-blue-400 uppercase tracking-wide">MCX</span>
                        </div>
                        <div className="text-[10px] text-muted truncate leading-tight">{selectedQuote?.name || selectedSymbol}</div>
                    </div>

                    {/* Price + change */}
                    <div className="flex items-baseline gap-2.5 pl-1">
                        <span className="font-price text-[20px] font-semibold tabular-nums text-heading">
                            {selectedLivePrice ? selectedLivePrice.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'}
                        </span>
                        <span className={cn('font-price text-[13px] tabular-nums', pnlColorClass(selectedChange))}>
                            {selectedChange > 0 ? '+' : ''}{selectedChange.toFixed(2)}&nbsp;
                            ({formatPercent(selectedPct)})
                        </span>
                    </div>

                    {/* Spacer */}
                    <div className="flex-1" />

                    {/* Toolbar */}
                    <div className="flex items-center gap-1.5">
                        <select
                            value={chartPeriod}
                            onChange={(e) => setChartPeriod(e.target.value)}
                            className="h-8 rounded-md border border-white/[0.08] bg-surface-900 px-2 text-[12px] text-heading outline-none hover:bg-white/[0.07]"
                        >
                            {['1m', '2m', '3m', '5m', '15m', '30m', '1H', '1D'].map((k) => (
                                <option key={k} value={k}>{k}</option>
                            ))}
                        </select>
                        <button
                            type="button"
                            className="grid h-8 w-8 place-items-center rounded-md border border-white/[0.08] bg-surface-900 text-yellow-400 hover:bg-white/[0.07]"
                        >
                            <Star className="h-3.5 w-3.5 fill-current" />
                        </button>
                        <button
                            type="button"
                            onClick={() => openOrderPanel('BUY')}
                            className="flex h-8 items-center gap-1.5 rounded-md border border-white/[0.08] bg-surface-900 px-3 text-[12px] font-semibold text-heading hover:bg-white/[0.07]"
                        >
                            <BarChart3 className="h-3.5 w-3.5" />
                            Strategies
                        </button>
                        <button
                            type="button"
                            className="flex h-8 items-center gap-1.5 rounded-md border border-white/[0.08] bg-surface-900 px-3 text-[12px] font-semibold text-heading hover:bg-white/[0.07]"
                        >
                            <Shield className="h-3.5 w-3.5" />
                            ZL
                        </button>
                        <button
                            type="button"
                            onClick={() => openOrderPanel('BUY')}
                            className="flex h-8 items-center gap-1.5 rounded-md border border-white/[0.08] bg-surface-900 px-3 text-[12px] font-semibold text-heading hover:bg-white/[0.07]"
                        >
                            Order Panel
                        </button>
                    </div>
                </div>

                {/* Status bar */}
                <div className="flex flex-shrink-0 items-center gap-3 border-b border-white/[0.06] bg-surface-950/25 px-4 py-1.5">
                    <span className={cn(
                        'inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide',
                        wsStatus === 'connected'
                            ? 'bg-emerald-500/10 text-emerald-400'
                            : 'bg-amber-500/10 text-amber-400',
                    )}>
                        <span className={cn(
                            'h-1.5 w-1.5 rounded-full',
                            wsStatus === 'connected' ? 'bg-emerald-400' : 'bg-amber-400',
                        )} />
                        {wsStatus === 'connected' ? 'LIVE' : 'REST'}
                    </span>
                    <span className="text-[11px] text-muted">MCX contracts only</span>
                    {isLoadingQuotes && (
                        <span className="text-[11px] text-muted animate-pulse">Refreshing quotes…</span>
                    )}
                </div>

                {/* Chart */}
                <div className="min-h-0 flex-1">
                    <ZebuLiveChart
                        candles={chartCandles}
                        isLoading={isChartLoading}
                        period={chartPeriod}
                        onPeriodChange={setChartPeriod}
                        symbol={selectedSymbol}
                        livePrice={selectedLivePrice}
                    />
                </div>

                {/* Bottom panel */}
                <div className="h-[180px] flex-shrink-0 border-t border-white/[0.07] bg-surface-950/30">
                    <div className="flex h-10 flex-shrink-0 items-center gap-5 border-b border-white/[0.07] px-4">
                        {[
                            ['positions', `NET POSITIONS (${mcxHoldings.length})`],
                            ['lots', `ENTRY LOTS (${mcxLots.length})`],
                            ['orders', `ORDERS (${mcxOrders.length})`],
                        ].map(([key, label]) => (
                            <button
                                key={key}
                                type="button"
                                onClick={() => setBottomTab(key)}
                                className={cn(
                                    'h-full border-b-2 text-[11px] font-semibold tracking-wide transition-colors',
                                    bottomTab === key
                                        ? 'border-cyan-500 text-cyan-400'
                                        : 'border-transparent text-muted hover:text-heading',
                                )}
                            >
                                {label}
                            </button>
                        ))}
                    </div>
                    <div className="h-[calc(100%-40px)] overflow-auto">
                        {bottomTab === 'positions' && (
                            <PositionsPanel
                                holdings={mcxHoldings}
                                showHeader={false}
                                onBuy={(s) => { setSelectedSymbol(clean(s)); openOrderPanel('BUY'); }}
                                onSell={(s) => { setSelectedSymbol(clean(s)); openOrderPanel('SELL'); }}
                            />
                        )}
                        {bottomTab === 'lots' && (
                            <OpenLotsPanel
                                lots={mcxLots}
                                holdings={mcxHoldings}
                                showHeader={false}
                                onBuy={(s) => { setSelectedSymbol(clean(s)); openOrderPanel('BUY'); }}
                                onSell={(s) => { setSelectedSymbol(clean(s)); openOrderPanel('SELL'); }}
                            />
                        )}
                        {bottomTab === 'orders' && (
                            <OrderHistoryPanel orders={mcxOrders} showHeader={false} />
                        )}
                    </div>
                </div>
            </main>

            {/* ── Floating Order Panel ── */}
            {orderOpen && (
                <div className="absolute right-4 top-16 z-40 w-[320px] overflow-hidden rounded-xl border border-white/[0.08] bg-surface-950 shadow-2xl shadow-black/60">
                    <div className="flex h-10 flex-shrink-0 items-center justify-between border-b border-white/[0.07] px-3">
                        <span className="text-[13px] font-semibold text-heading">Order Panel</span>
                        <button
                            type="button"
                            onClick={() => setOrderOpen(false)}
                            className="grid h-7 w-7 place-items-center rounded-md text-muted hover:bg-white/[0.08] hover:text-heading"
                        >
                            <X className="h-4 w-4" />
                        </button>
                    </div>
                    <OrderPanel
                        symbol={selectedSymbol}
                        currentPrice={selectedLivePrice}
                        initialSide={orderSide}
                        initialSideKey={orderKey}
                        isFloating
                    />
                </div>
            )}
        </div>
    );
}
