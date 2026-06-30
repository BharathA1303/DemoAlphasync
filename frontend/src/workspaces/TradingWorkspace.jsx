// ─── TradingWorkspace ────────────────────────────────────────────────────────
// CSS Grid layout: Watchlist | (ChartHeader + Chart + BottomDock) | OrderPanel
// + floating StrategyDock
// Responsive: Desktop grid → Tablet (no watchlist) → Mobile (drawers + trade bar)
import { useState, useEffect, useCallback, useMemo, useRef, useSyncExternalStore } from 'react';
import { useSearchParams } from 'react-router-dom';
import { usePortfolioStore } from '../store/usePortfolioStore';
import { useMarketStore } from '../store/useMarketStore';
import { useWatchlistStore } from '../stores/useWatchlistStore';
import { useStrategyStore } from '../stores/useStrategyStore';
import { useMarketData } from '../hooks/useMarketData';
import { useBreakpoint } from '../hooks/useBreakpoint';
import ChartHeader from '../components/trading/ChartHeader';
import ZebuLiveChart from '../components/trading/ZebuLiveChart';
import Watchlist from '../components/trading/Watchlist';
import OrderPanel from '../components/trading/OrderPanel';
import ResizablePanel from '../components/layout/ResizablePanel';
import ResponsiveDrawer from '../components/layout/ResponsiveDrawer';
import { HardenedOrderDrawer, HardenedChartShell } from '../responsive/hardening';
import DockContainer from '../components/layout/DockContainer';
import MobileTradeBar from '../components/layout/MobileTradeBar';
import { PositionsPanel, OrderHistoryPanel, OpenLotsPanel } from '../panels';
import { StrategyDock } from '../strategy/components';
import { runEngine, getAvailableStrategies } from '../strategy';
import Modal from '../components/ui/Modal';
import ErrorBoundary from '../components/ErrorBoundary';
import { cn } from '../utils/cn';
import { CHART_PERIODS, DEFAULT_CHART_PERIOD, isMcxSymbol } from '../utils/constants';
import { useResponsive } from '../responsive/hooks/useResponsive';
import { useZeroLossStore } from '../stores/useZeroLossStore';
import { PanelLeftOpen, PanelLeftClose } from 'lucide-react';
import { computeOpenLots } from '../utils/tradeLots';
import { buildQuoteWithLivePrice, getLiveQuoteForSymbol } from '../utils/liveQuote';
import { resolveSymbolPrice } from '../market/UnifiedPriceResolver';
import { getEODQuoteCache } from '../market/EODReconciliationEngine';
import { setSessionCloseFromCandle } from '../market/SessionClosePriceAuthority';
import { shouldUseRealtimePrices } from '../market/utils/marketSessionUtils';
import { marketSessionManager } from '../market/MarketSessionManager';

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

// ── Main workspace ───────────────────────────────────────────────────────────
export default function TradingWorkspace() {
    const MIN_BOTTOM_HEIGHT = 32;
    const EXPANDED_MIN_HEIGHT = 120;
    const MAX_BOTTOM_HEIGHT = 420;
    const DEFAULT_BOTTOM_HEIGHT = 200;
    const ORDER_FLOAT_WIDTH = 312;

    const [searchParams] = useSearchParams();
    const initialSymbol = searchParams.get('symbol') || 'RELIANCE.NS';

    const [selectedSymbol, setSelectedSymbol] = useState(initialSymbol);
    const [chartPeriod, setChartPeriod] = useState(DEFAULT_CHART_PERIOD);
    const [isTerminalFocused, setIsTerminalFocused] = useState(false);
    const [strategyDockOpen, setStrategyDockOpen] = useState(false);
    const [watchlistToggleBusy, setWatchlistToggleBusy] = useState(false);
    const [bottomCollapsed, setBottomCollapsed] = useState(false);
    const [bottomHeight, setBottomHeight] = useState(DEFAULT_BOTTOM_HEIGHT);
    const [watchlistVisible, setWatchlistVisible] = useState(true);
    const [orderPanelVisible, setOrderPanelVisible] = useState(false);
    const getDefaultOrderPanelPos = useCallback(() => ({
        x: Math.max(16, window.innerWidth - ORDER_FLOAT_WIDTH - 16),
        y: 72,
    }), [ORDER_FLOAT_WIDTH]);
    const [orderPanelPos, setOrderPanelPos] = useState(() => getDefaultOrderPanelPos());
    const orderPanelDrag = useRef({ active: false, sx: 0, sy: 0, ox: 0, oy: 0 });

    // Sync selectedSymbol when URL ?symbol= changes (e.g. ticker bar click)
    useEffect(() => {
        const urlSymbol = searchParams.get('symbol');
        if (urlSymbol && urlSymbol !== selectedSymbol) {
            setSelectedSymbol(urlSymbol);
        }
        // Auto-open order panel if ?side=BUY or ?side=SELL is in the URL
        const urlSide = searchParams.get('side');
        if (urlSide === 'BUY' || urlSide === 'SELL') {
            setOrderSide(urlSide);
            setOrderSideKey((k) => k + 1);
            setOrderPanelVisible(true);
            setOrderDrawerOpen(true);
        }
    }, [searchParams]);

    // Responsive drawer states
    const [watchlistDrawerOpen, setWatchlistDrawerOpen] = useState(false);
    const [orderDrawerOpen, setOrderDrawerOpen] = useState(false);

    // Breakpoint
    const { isMobile, isCompact, isWide } = useBreakpoint();

    // ── Stores ────────────────────────────────────────────────────────────────
    const { holdings, orders, transactions, openLots, refreshPortfolio } = usePortfolioStore();
    const setGlobalSelectedSymbol = useMarketStore((s) => s.setSelectedSymbol);
    const wsStatus = useMarketStore((s) => s.wsStatus);
    const liveQuotes = useMarketStore((s) => s.symbols);

    // ── Watchlist store — FIX: use proper reactive selectors, NOT broken JS getters ──
    // The store previously had `get items()` and `get watchlistId()` as JS getters.
    // Those were removed. Now we must select raw state and derive what we need.
    const watchlists = useWatchlistStore((s) => s.watchlists);
    const activeId = useWatchlistStore((s) => s.activeId);
    const loadWatchlist = useWatchlistStore((s) => s.loadWatchlist);
    const fetchWatchlistPrices = useWatchlistStore((s) => s.fetchPrices);
    const addWatchlistItem = useWatchlistStore((s) => s.addItem);
    const removeWatchlistItem = useWatchlistStore((s) => s.removeItem);
    // Derive items safely — only recomputes when watchlists/activeId actually change
    const watchlistItems = useMemo(
        () => watchlists.find(w => w.id === activeId)?.items ?? [],
        [watchlists, activeId]
    );

    const currentWatchlistItem = useMemo(() => {
        if (!selectedSymbol) return null;
        return watchlistItems.find((item) =>
            String(item.symbol || '').toUpperCase() === String(selectedSymbol).toUpperCase()
        ) || null;
    }, [watchlistItems, selectedSymbol]);

    // Strategy store — the StrategyDock writes engine output here;
    // the chart badge reads it so both always show the same result.
    const engineOutput = useStrategyStore((s) => s.engineOutput);
    const setEngineOutput = useStrategyStore((s) => s.setEngineOutput);

    // ── Hooks ─────────────────────────────────────────────────────────────────
    const { quote, candles, candlesSymbol, isLoading: chartLoading, fetchCandles } = useMarketData(
        selectedSymbol,
        { pollInterval: wsStatus === 'connected' ? 0 : 5_000 },
    );

    const chartCandles = useMemo(() => {
        const owner = String(candlesSymbol || '').trim().toUpperCase();
        if (!owner) return [];
        const selectedAliases = symbolAliases(selectedSymbol);
        return selectedAliases.includes(owner) ? candles : [];
    }, [candles, candlesSymbol, selectedSymbol]);

    const normalizedCandles = useMemo(
        () => normalizeDisplayCandles(chartCandles || []),
        [chartCandles],
    );

    const sessionTick = useSyncExternalStore(
        (cb) => marketSessionManager.subscribe(cb),
        () => marketSessionManager.getSnapshot().fetchedAt,
        () => 0,
    );

    const displayQuote = useMemo(() => {
        const lastBar = normalizedCandles[normalizedCandles.length - 1];
        const candleClose = toFiniteNumber(lastBar?.close);
        const marketOpen = shouldUseRealtimePrices();

        const resolved = resolveSymbolPrice(selectedSymbol, {
            liveQuotes: marketOpen ? liveQuotes : {},
            eodQuotes: getEODQuoteCache(),
            candleClose,
        });

        const baseQuote = {
            ...(quote || {}),
            ...(resolved.quote || {}),
            symbol: selectedSymbol,
            name: resolved.quote?.name || quote?.name || selectedSymbol,
        };

        const resolvedPrice = marketOpen
            ? resolved.price
            : (candleClose ?? resolved.price);

        const candleOpen = toFiniteNumber(lastBar?.open);
        const candleHigh = toFiniteNumber(lastBar?.high);
        const candleLow = toFiniteNumber(lastBar?.low);

        const withLive = buildQuoteWithLivePrice(baseQuote, resolvedPrice);

        return {
            ...withLive,
            open: candleOpen ?? toFiniteNumber(baseQuote.open),
            high: candleHigh ?? toFiniteNumber(baseQuote.high),
            low: candleLow ?? toFiniteNumber(baseQuote.low),
            prev_close: toFiniteNumber(baseQuote.prev_close) ?? toFiniteNumber(resolved.quote?.prev_close),
            _priceSource: resolved.priceSource,
        };
    }, [quote, selectedSymbol, normalizedCandles, liveQuotes, sessionTick]);

    const zlConfidence = useZeroLossStore((s) => s.confidence[selectedSymbol] || null);

    // ── Derived: Trend data from the shared strategy store ─────────────────
    // The StrategyDock computes engine results with user-enabled strategies
    // and writes them to the store. We read from the store here so the chart
    // badge always matches the dock. If the dock hasn't run yet (e.g. first
    // load), compute a fallback with all strategies.
    const trendData = useMemo(() => {
        if (engineOutput && engineOutput.signals?.length > 0) {
            return {
                overall: engineOutput.overall,
                confidence: engineOutput.confidence,
                weightedScore: engineOutput.weightedScore ?? 0,
            };
        }
        // Fallback: compute with all strategies if dock hasn't run yet
        if (!chartCandles || chartCandles.length === 0) return null;
        const strategies = getAvailableStrategies();
        const enabledIds = strategies.map((s) => s.id);
        const result = runEngine(chartCandles, enabledIds);
        return {
            overall: result.overall,
            confidence: result.confidence,
            weightedScore: result.weightedScore ?? 0,
        };
    }, [engineOutput, chartCandles, setEngineOutput]);

    // ── Effects ───────────────────────────────────────────────────────────────
    useEffect(() => {
        const cfg = CHART_PERIODS[chartPeriod] || CHART_PERIODS[DEFAULT_CHART_PERIOD];
        fetchCandles(cfg.period, cfg.interval);
    }, [selectedSymbol, chartPeriod, fetchCandles]);

    // Register chart last-bar close as closed-session authority (matches chart Y-axis).
    useEffect(() => {
        if (!selectedSymbol || normalizedCandles.length === 0) return;
        const lastBar = normalizedCandles[normalizedCandles.length - 1];
        const close = toFiniteNumber(lastBar?.close);
        if (close == null || close <= 0) return;
        setSessionCloseFromCandle(selectedSymbol, close, {
            prev_close: toFiniteNumber(quote?.prev_close),
        });
    }, [selectedSymbol, normalizedCandles, quote?.prev_close]);

    useEffect(() => { refreshPortfolio(); }, [refreshPortfolio]);
    useEffect(() => { loadWatchlist(); }, [loadWatchlist]);
    useEffect(() => { setGlobalSelectedSymbol(selectedSymbol); }, [selectedSymbol, setGlobalSelectedSymbol]);

    // HTTP fallback when WS down, or after market close (EOD reconciliation via batch poll).
    useEffect(() => {
        if (watchlistItems.length === 0) return;
        if (wsStatus === 'connected' && shouldUseRealtimePrices()) return;

        fetchWatchlistPrices();
        const id = setInterval(fetchWatchlistPrices, 10_000);
        return () => clearInterval(id);
    }, [watchlistItems, fetchWatchlistPrices, wsStatus]);

    // Close drawers on breakpoint change to desktop
    useEffect(() => {
        if (isWide) {
            setWatchlistDrawerOpen(false);
            setOrderDrawerOpen(false);
        }
    }, [isWide]);

    const clampOrderPanelPos = useCallback((p) => ({
        x: Math.max(0, Math.min(window.innerWidth - ORDER_FLOAT_WIDTH, p.x)),
        y: Math.max(0, Math.min(window.innerHeight - 120, p.y)),
    }), [ORDER_FLOAT_WIDTH]);

    useEffect(() => {
        const handleResize = () => {
            setOrderPanelPos((p) => clampOrderPanelPos(p));
        };
        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }, [clampOrderPanelPos]);

    // ── Handlers ──────────────────────────────────────────────────────────────
    const [orderSide, setOrderSide] = useState(null);
    const [orderSideKey, setOrderSideKey] = useState(0);

    // Quick order modal — opens when SELL/EXIT/BUY is clicked from positions
    const [quickOrderOpen, setQuickOrderOpen] = useState(false);
    const [quickOrderSymbol, setQuickOrderSymbol] = useState(null);
    const [quickOrderSide, setQuickOrderSide] = useState(null);
    const [quickOrderKey, setQuickOrderKey] = useState(0);

    const handleSelectSymbol = useCallback((symbol) => {
        setSelectedSymbol(symbol);
        if (isCompact) setWatchlistDrawerOpen(false);
    }, [isCompact]);

    const handleToggleWatchlist = useCallback(async () => {
        if (!selectedSymbol || watchlistToggleBusy) return;
        setWatchlistToggleBusy(true);
        try {
            if (currentWatchlistItem?.id) {
                await removeWatchlistItem(currentWatchlistItem.id);
            } else {
                await addWatchlistItem(selectedSymbol, isMcxSymbol(selectedSymbol) ? 'MCX' : 'NSE');
            }
        } finally {
            setWatchlistToggleBusy(false);
        }
    }, [selectedSymbol, watchlistToggleBusy, currentWatchlistItem, addWatchlistItem, removeWatchlistItem]);

    const handleBuy = useCallback(() => {
        setOrderSide('BUY');
        setOrderSideKey((k) => k + 1);
        setOrderDrawerOpen(true);
    }, []);

    const handleSell = useCallback(() => {
        setOrderSide('SELL');
        setOrderSideKey((k) => k + 1);
        setOrderDrawerOpen(true);
    }, []);

    // Position SELL/EXIT → open quick order popup modal
    const handlePositionSell = useCallback((symbol) => {
        setQuickOrderSymbol(symbol);
        setQuickOrderSide('SELL');
        setQuickOrderKey((k) => k + 1);
        setQuickOrderOpen(true);
    }, []);

    const handlePositionBuy = useCallback((symbol) => {
        setQuickOrderSymbol(symbol);
        setQuickOrderSide('BUY');
        setQuickOrderKey((k) => k + 1);
        setQuickOrderOpen(true);
    }, []);

    const handleOrderPanelGrab = useCallback((event) => {
        if (event.target.closest('button') || event.target.closest('input')) return;
        event.preventDefault();
        orderPanelDrag.current = {
            active: true,
            sx: event.clientX,
            sy: event.clientY,
            ox: orderPanelPos.x,
            oy: orderPanelPos.y,
        };
        const onMove = (moveEvent) => {
            if (!orderPanelDrag.current.active) return;
            setOrderPanelPos(clampOrderPanelPos({
                x: orderPanelDrag.current.ox + (moveEvent.clientX - orderPanelDrag.current.sx),
                y: orderPanelDrag.current.oy + (moveEvent.clientY - orderPanelDrag.current.sy),
            }));
        };
        const onUp = () => {
            orderPanelDrag.current.active = false;
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
        };
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
    }, [orderPanelPos, clampOrderPanelPos]);

    const closeFloatingOrderPanel = useCallback(() => {
        setOrderPanelVisible(false);
        setOrderPanelPos(getDefaultOrderPanelPos());
        setTimeout(() => window.dispatchEvent(new Event('resize')), 250);
    }, [getDefaultOrderPanelPos]);

    const openFloatingOrderPanel = useCallback((side = null) => {
        if (side) {
            setOrderSide(side);
            setOrderSideKey((k) => k + 1);
        }
        setOrderPanelPos(clampOrderPanelPos(getDefaultOrderPanelPos()));
        setOrderPanelVisible(true);
        setTimeout(() => window.dispatchEvent(new Event('resize')), 250);
    }, [clampOrderPanelPos, getDefaultOrderPanelPos]);

    // ── Handle bottom panel collapse/expand ────────────────────────────────────
    const handleBottomPanelToggle = useCallback(() => {
        setBottomCollapsed((v) => {
            const nextCollapsed = !v;
            if (!nextCollapsed && bottomHeight < EXPANDED_MIN_HEIGHT) {
                setBottomHeight(DEFAULT_BOTTOM_HEIGHT);
            }
            return nextCollapsed;
        });
        // Trigger chart resize after layout transition completes
        setTimeout(() => {
            window.dispatchEvent(new Event('resize'));
        }, 250);
    }, [bottomHeight]);

    const handleBottomResizeStart = useCallback((event) => {
        if (isCompact) return;

        event.preventDefault();
        const startY = event.clientY;
        const initialHeight = bottomCollapsed ? DEFAULT_BOTTOM_HEIGHT : bottomHeight;

        if (bottomCollapsed) {
            setBottomCollapsed(false);
        }

        const onMouseMove = (moveEvent) => {
            const delta = startY - moveEvent.clientY;
            const nextHeight = Math.max(
                MIN_BOTTOM_HEIGHT,
                Math.min(MAX_BOTTOM_HEIGHT, initialHeight + delta)
            );

            if (nextHeight <= 56) {
                setBottomCollapsed(true);
                setBottomHeight(MIN_BOTTOM_HEIGHT);
            } else {
                setBottomCollapsed(false);
                setBottomHeight(nextHeight);
            }

            window.dispatchEvent(new Event('resize'));
        };

        const onMouseUp = () => {
            window.removeEventListener('mousemove', onMouseMove);
            window.removeEventListener('mouseup', onMouseUp);
            setTimeout(() => window.dispatchEvent(new Event('resize')), 0);
        };

        window.addEventListener('mousemove', onMouseMove);
        window.addEventListener('mouseup', onMouseUp);
    }, [bottomCollapsed, bottomHeight, isCompact]);

    const computedOpenLots = useMemo(
        () => computeOpenLots(transactions || [], holdings || []),
        [transactions, holdings]
    );

    const effectiveOpenLots = useMemo(
        () => (Array.isArray(openLots) ? openLots : computedOpenLots),
        [openLots, computedOpenLots]
    );

    // ── Dock tabs ─────────────────────────────────────────────────────────────
    const dockTabs = useMemo(() => [
        {
            key: 'positions',
            label: 'Net Positions',
            count: holdings.length,
            content: <PositionsPanel showHeader={false} holdings={holdings} onSell={handlePositionSell} onBuy={handlePositionBuy} />,
        },
        {
            key: 'lots',
            label: 'Entry Lots',
            count: effectiveOpenLots.length,
            content: (
                <OpenLotsPanel
                    showHeader={false}
                    lots={effectiveOpenLots}
                    holdings={holdings}
                    onSell={handlePositionSell}
                    onBuy={handlePositionBuy}
                />
            ),
        },
        {
            key: 'orders',
            label: 'Orders',
            count: orders.length,
            content: <OrderHistoryPanel showHeader={false} orders={orders} />,
        },
    ], [holdings, effectiveOpenLots, orders, handlePositionSell, handlePositionBuy]);

    // ── Shared watchlist element ───────────────────────────────────────────────
    // NOTE: Watchlist now reads everything from useWatchlistStore internally.
    // We no longer need to pass items/prices/watchlistId as props.
    const watchlistEl = (
        <Watchlist
            selectedSymbol={selectedSymbol}
            onSelectSymbol={handleSelectSymbol}
            onBuy={handlePositionBuy}
            onSell={handlePositionSell}
        />
    );

    const { mobileTradingTab } = useResponsive();

    useEffect(() => {
        if (!isCompact) return;
        if (mobileTradingTab === 'watchlist') {
            setWatchlistDrawerOpen(true);
            setOrderDrawerOpen(false);
        } else if (mobileTradingTab === 'order') {
            setOrderDrawerOpen(true);
            setWatchlistDrawerOpen(false);
        } else {
            setWatchlistDrawerOpen(false);
            setOrderDrawerOpen(false);
        }
    }, [isCompact, mobileTradingTab]);

    const orderPanelEl = (
        <OrderPanel
            symbol={selectedSymbol}
            currentPrice={displayQuote?.price ?? 0}
            isTerminalFocused={isTerminalFocused}
            initialSide={orderSide}
            initialSideKey={orderSideKey}
            isFloating={isWide}
        />
    );

    return (
        <div
            className={cn(
                'terminal-grid',
                isCompact ? 'h-full min-h-0 flex-1' : 'h-[calc(100vh-56px-36px)]',
            )}
            onFocus={() => setIsTerminalFocused(true)}
            onBlur={() => setIsTerminalFocused(false)}
        >
            {isCompact && mobileTradingTab === 'watchlist' && (
                <div className="hard-mobile-watchlist-panel flex-col flex-1 min-h-0 min-w-0 overflow-hidden lg:hidden">
                    {watchlistEl}
                </div>
            )}
            {/* ── WATCHLIST AREA ─────────────────────────────────────── */}
            {isWide ? (
                watchlistVisible ? (
                    <ResizablePanel
                        side="left"
                        defaultSize={360}
                        minSize={260}
                        maxSize={520}
                        className="terminal-area-watchlist hidden lg:flex"
                    >
                        {watchlistEl}
                    </ResizablePanel>
                ) : null
            ) : (
                <ResponsiveDrawer
                    open={watchlistDrawerOpen}
                    onClose={() => setWatchlistDrawerOpen(false)}
                    side="left"
                    isCompact={true}
                    width="w-[280px]"
                >
                    {watchlistEl}
                </ResponsiveDrawer>
            )}

            {/* ── CHART HEADER AREA ─────────────────────────────────── */}
            <div className="terminal-area-header min-w-0 flex items-center">
                {/* Watchlist toggle — desktop only */}
                {isWide && (
                    <button
                        onClick={() => {
                            setWatchlistVisible((v) => !v);
                            setTimeout(() => window.dispatchEvent(new Event('resize')), 250);
                        }}
                        className={cn(
                            "flex-shrink-0 p-1.5 ml-1 rounded-md transition-all duration-200",
                            "text-slate-400 hover:text-heading hover:bg-overlay/[0.06]",
                            !watchlistVisible && "text-primary-500 bg-primary-500/10"
                        )}
                        title={watchlistVisible ? "Hide watchlist" : "Show watchlist"}
                    >
                        {watchlistVisible ? <PanelLeftClose className="w-4 h-4" /> : <PanelLeftOpen className="w-4 h-4" />}
                    </button>
                )}
                <div className="flex-1 min-w-0">
                    <ChartHeader
                        symbol={selectedSymbol}
                        quote={displayQuote}
                        period={chartPeriod}
                        onPeriodChange={setChartPeriod}
                        strategyDockOpen={strategyDockOpen}
                        isWatchlisted={Boolean(currentWatchlistItem)}
                        onToggleWatchlist={handleToggleWatchlist}
                        watchlistBusy={watchlistToggleBusy}
                        onToggleStrategyDock={() => setStrategyDockOpen((v) => !v)}
                        trendData={trendData}
                        isMobile={isMobile}
                        hasPositions={holdings.length > 0}
                        orderPanelVisible={orderPanelVisible}
                        onToggleOrderPanel={() => {
                            if (orderPanelVisible) {
                                closeFloatingOrderPanel();
                            } else {
                                openFloatingOrderPanel();
                            }
                        }}
                    />
                </div>
            </div>

            {/* ── CHART AREA ────────────────────────────────────────── */}
            <HardenedChartShell className="terminal-area-chart min-w-0 min-h-0 relative overflow-hidden">
                <ErrorBoundary fallback="Chart failed to load. Please refresh.">
                    <ZebuLiveChart
                        key={selectedSymbol}
                        candles={chartCandles}
                        isLoading={chartLoading}
                        trendData={trendData}
                        symbol={selectedSymbol}
                        period={chartPeriod}
                        onPeriodChange={setChartPeriod}
                        zeroLossTrend={zlConfidence}
                    />
                </ErrorBoundary>
            </HardenedChartShell>

            {/* ── BOTTOM DOCK ───────────────────────────────────────── */}
            <div className={cn(
                'terminal-area-bottom min-w-0',
                'transition-all duration-200'
            )}
                style={{ height: `${bottomCollapsed ? MIN_BOTTOM_HEIGHT : bottomHeight}px` }}
            >
                <DockContainer
                    tabs={dockTabs}
                    defaultTab="lots"
                    collapsed={bottomCollapsed}
                    onToggleCollapse={handleBottomPanelToggle}
                    onResizeStart={handleBottomResizeStart}
                />
            </div>

            {/* ── ORDER PANEL AREA ──────────────────────────────────── */}
            {isWide ? (
                orderPanelVisible ? (
                    <div
                        className="fixed z-50 hidden lg:flex flex-col rounded-2xl select-none bg-surface-900/95 border border-edge/10 shadow-2xl shadow-black/40 overflow-visible"
                        style={{
                            left: orderPanelPos.x,
                            top: orderPanelPos.y,
                            width: ORDER_FLOAT_WIDTH,
                            maxHeight: 'calc(100vh - 140px)',
                            backdropFilter: 'blur(24px)',
                        }}
                    >
                        <div
                            onMouseDown={handleOrderPanelGrab}
                            className="h-8 px-3 flex items-center justify-between cursor-move border-b border-edge/10 flex-shrink-0"
                        >
                            <div className="flex items-center gap-2">
                                <span className="text-[11px] font-semibold text-heading">Order Panel</span>
                            </div>
                            <button
                                onClick={closeFloatingOrderPanel}
                                className="w-5 h-5 rounded-md flex items-center justify-center text-gray-500 hover:text-heading hover:bg-surface-800 transition-all duration-150"
                                title="Close"
                            >
                                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                                    <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" strokeLinejoin="round" />
                                </svg>
                            </button>
                        </div>
                        <div className="flex-1 min-h-0 overflow-y-auto rounded-b-2xl">
                            {orderPanelEl}
                        </div>
                    </div>
                ) : null
            ) : (
                <HardenedOrderDrawer
                    open={orderDrawerOpen}
                    onClose={() => setOrderDrawerOpen(false)}
                    side="right"
                    isCompact={true}
                    width="w-[320px]"
                >
                    {orderPanelEl}
                </HardenedOrderDrawer>
            )}

            {/* ── MOBILE/TABLET TRADE BAR ────────────────────────── */}
            {isCompact && (
                <div className="terminal-area-tradebar">
                    <MobileTradeBar
                        symbol={selectedSymbol}
                        price={displayQuote?.price ?? 0}
                        onBuy={handleBuy}
                        onSell={handleSell}
                        onToggleWatchlist={() => setWatchlistDrawerOpen((v) => !v)}
                    />
                </div>
            )}

            {/* ── Floating Strategy Dock popup ───────────────────────── */}
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
                title={`${quickOrderSide === 'BUY' ? 'Buy / Exit Short' : 'Sell'} — ${quickOrderSymbol?.replace('.NS', '') || ''}`}
                size="sm"
                className="!max-w-[360px]"
            >
                <div className="overflow-y-auto max-h-[80vh]">
                    <OrderPanel
                        symbol={quickOrderSymbol || selectedSymbol}
                        currentPrice={
                            getLiveQuoteForSymbol(quickOrderSymbol || selectedSymbol, liveQuotes)?.price
                            ?? displayQuote?.price
                            ?? 0
                        }
                        initialSide={quickOrderSide}
                        initialSideKey={quickOrderKey}
                        isFloating={true}
                    />
                </div>
            </Modal>
        </div>
    );
}