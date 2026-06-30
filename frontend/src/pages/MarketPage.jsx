import { useEffect, useMemo, useState, useRef, useSyncExternalStore } from 'react';
import { useNavigate } from 'react-router-dom';
import {
    TrendingUp,
    TrendingDown,
    ArrowUpRight,
    ArrowDownRight,
    Maximize2,
    Building2,
    Laptop,
    ShoppingCart,
    Factory,
    Coins,
    Info,
    ChevronDown
} from 'lucide-react';
import { createChart, CrosshairMode } from 'lightweight-charts';
import { cn } from '../utils/cn';
import { formatPrice, formatPercent, pnlColorClass, cleanSymbol } from '../utils/formatters';
import { resolveSymbolPrice } from '../market/UnifiedPriceResolver';
import { useMarketStore } from '../store/useMarketStore';
import { useWebSocket } from '../hooks/useWebSocket';
import { marketSessionManager } from '../market/MarketSessionManager';
import api from '../services/api';
import { Skeleton } from '../components/ui';
import { useTheme } from '../context/ThemeContext';

// Vector icons map for sectors
const SECTOR_ICONS = {
    '^CNXIT': Laptop,
    '^NSEBANK': Building2,
    '^CNXFIN': Coins,
    '^CNXFMCG': ShoppingCart,
    '^CNXMETAL': Factory,
};

// Mini inline sparkline SVG chart
function Sparkline({ prices = [], isPositive }) {
    const width = 120;
    const height = 32;

    if (!prices || prices.length < 2) {
        return (
            <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="overflow-visible opacity-25">
                <line x1="0" y1={height / 2} x2={width} y2={height / 2} stroke="#9ca3af" strokeWidth="1.5" strokeDasharray="3,3" />
            </svg>
        );
    }

    const min = Math.min(...prices);
    const max = Math.max(...prices);
    const range = max - min || 1;

    const points = prices
        .map((price, idx) => {
            const x = (idx / (prices.length - 1)) * width;
            const y = height - ((price - min) / range) * height;
            return `${x},${y}`;
        })
        .join(' ');

    const strokeColor = isPositive ? '#10b981' : '#ef4444';

    return (
        <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="overflow-visible">
            <polyline
                fill="none"
                stroke={strokeColor}
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                points={points}
            />
        </svg>
    );
}

// Custom Semicircular SVG Sentiment Gauge
function SentimentGauge({ score = 50 }) {
    const minAngle = -180;
    const maxAngle = 0;
    const angle = minAngle + (score / 100) * (maxAngle - minAngle);

    const r = 45; // needle length
    const cx = 80;
    const cy = 80;
    const rad = (angle * Math.PI) / 180;
    const x = cx + r * Math.cos(rad);
    const y = cy + r * Math.sin(rad);

    return (
        <svg width="160" height="90" viewBox="0 0 160 90" className="mx-auto overflow-visible select-none">
            <defs>
                <linearGradient id="gaugeGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" stopColor="#ef4444" />
                    <stop offset="50%" stopColor="#f59e0b" />
                    <stop offset="100%" stopColor="#10b981" />
                </linearGradient>
            </defs>
            {/* Background Arc */}
            <path
                d="M 20 80 A 60 60 0 0 1 140 80"
                fill="none"
                stroke="#e2e8f0"
                strokeWidth="10"
                strokeLinecap="round"
                className="dark:stroke-neutral-800"
            />
            {/* Value Arc */}
            <path
                d="M 20 80 A 60 60 0 0 1 140 80"
                fill="none"
                stroke="url(#gaugeGradient)"
                strokeWidth="10"
                strokeLinecap="round"
            />
            {/* Needle */}
            <line
                x1={cx}
                y1={cy}
                x2={x}
                y2={y}
                stroke="#374151"
                strokeWidth="3.5"
                strokeLinecap="round"
                className="dark:stroke-neutral-200 transition-all duration-500 ease-out"
            />
            {/* Center Cap */}
            <circle cx={cx} cy={cy} r="6" fill="#374151" className="dark:fill-neutral-200" />
            <circle cx={cx} cy={cy} r="2.5" fill="#ffffff" className="dark:fill-neutral-900" />
        </svg>
    );
}

export default function MarketPage() {
    const navigate = useNavigate();
    const { theme } = useTheme();

    const [overview, setOverview] = useState(null);
    const [selectedSymbol, setSelectedSymbol] = useState('^NSEI');
    const [timeframe, setTimeframe] = useState('1D');
    const [candles, setCandles] = useState([]);
    const [chartLoading, setChartLoading] = useState(false);
    const [dropdownOpen, setDropdownOpen] = useState(false);
    // True once overview has loaded and chart container is in the DOM
    const [chartReady, setChartReady] = useState(false);

    const dropdownRef = useRef(null);
    const chartContainerRef = useRef(null);
    const chartRef = useRef(null);
    const seriesRef = useRef(null);

    const liveQuotes = useMarketStore((s) => s.symbols);
    const { subscribe, unsubscribe } = useWebSocket();

    // Fetch initial Overview data
    const fetchOverview = async () => {
        try {
            const res = await api.get('/market/overview');
            setOverview(res.data);
        } catch (err) {
            console.error('Failed to load market overview:', err);
        }
    };

    useEffect(() => {
        fetchOverview();
        const interval = setInterval(fetchOverview, 20000); // refresh metadata every 20s
        return () => clearInterval(interval);
    }, []);

    // Signal that the chart container is now in the DOM (overview just loaded)
    useEffect(() => {
        if (overview && !chartReady) {
            setChartReady(true);
        }
    }, [overview, chartReady]);

    // WebSocket subscription management
    useEffect(() => {
        if (!overview) return;

        const symbols = [
            ...overview.indices.map((i) => i.symbol),
            ...overview.sectors.map((s) => s.symbol),
            ...overview.gainers.map((g) => g.symbol),
            ...overview.losers.map((l) => l.symbol),
        ].filter(Boolean);

        const uniqueSymbols = [...new Set(symbols)];
        subscribe(uniqueSymbols);

        return () => {
            unsubscribe(uniqueSymbols);
        };
    }, [overview, subscribe, unsubscribe]);

    // Close index selector dropdown on clicking outside
    useEffect(() => {
        const handleOutsideClick = (e) => {
            if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
                setDropdownOpen(false);
            }
        };
        document.addEventListener('mousedown', handleOutsideClick);
        return () => document.removeEventListener('mousedown', handleOutsideClick);
    }, []);

    // Resolve live prices for display
    const getLiveItem = (item) => {
        if (!item?.symbol) return item;
        const resolved = resolveSymbolPrice(item.symbol, { liveQuotes });
        if (resolved && resolved.price !== null) {
            const high = resolved.quote?.high ?? item.high ?? resolved.price;
            const low = resolved.quote?.low ?? item.low ?? resolved.price;
            return {
                ...item,
                price: resolved.price,
                change: resolved.change ?? item.change,
                change_percent: resolved.change_percent ?? item.change_percent,
                high: high === 0 ? resolved.price : high,
                low: low === 0 ? resolved.price : low,
            };
        }
        return item;
    };

    // Append current live ticks to sparklines
    const getLiveSparkline = (item) => {
        const live = getLiveItem(item);
        const baseSparkline = item.sparkline || [];
        if (live.price !== null && baseSparkline.length > 0) {
            const lastVal = baseSparkline[baseSparkline.length - 1];
            if (Math.abs(live.price - lastVal) > 0.01) {
                return [...baseSparkline, live.price];
            }
        }
        return baseSparkline;
    };

    // Load active index historical candles
    useEffect(() => {
        let active = true;
        const fetchCandles = async () => {
            setChartLoading(true);
            let period = '1mo';
            let interval = '1d';

            if (timeframe === '1D') {
                period = '1d';
                interval = '5m';
            } else if (timeframe === '1W') {
                period = '5d';
                interval = '30m';
            } else if (timeframe === '1M') {
                period = '1mo';
                interval = '1d';
            } else if (timeframe === '3M') {
                period = '3mo';
                interval = '1d';
            } else if (timeframe === '1Y') {
                period = '1y';
                interval = '1wk';
            } else if (timeframe === '5Y') {
                period = '5y';
                interval = '1mo';
            }

            try {
                const res = await api.get(`/market/history/${selectedSymbol}?period=${period}&interval=${interval}`);
                if (active) {
                    setCandles(res.data.candles || []);
                }
            } catch (err) {
                console.error('Failed to load historical candles:', err);
                if (active) setCandles([]);
            } finally {
                if (active) setChartLoading(false);
            }
        };

        fetchCandles();

        // Intraday polling interval when market is open
        let pollTimer = null;
        if (marketSessionManager.getSnapshot().isOpen && timeframe === '1D') {
            pollTimer = setInterval(fetchCandles, 15000);
        }

        return () => {
            active = false;
            if (pollTimer) clearInterval(pollTimer);
        };
    }, [selectedSymbol, timeframe]);

    // Initialize TradingView Area Chart — only after overview has loaded and mounted the container
    useEffect(() => {
        if (!chartReady || !chartContainerRef.current) return;

        const isDark = theme === 'dark';
        const chart = createChart(chartContainerRef.current, {
            layout: {
                background: { color: isDark ? 'transparent' : '#ffffff' },
                textColor: isDark ? '#9ca3af' : '#64748b',
                fontFamily: 'Inter, sans-serif',
            },
            grid: {
                vertLines: { visible: false },
                horzLines: { color: isDark ? 'rgba(255, 255, 255, 0.04)' : '#f1f5f9' },
            },
            timeScale: {
                borderVisible: false,
                timeVisible: true,
                secondsVisible: false,
            },
            rightPriceScale: {
                borderVisible: false,
                scaleMargins: {
                    top: 0.15,
                    bottom: 0.15,
                },
            },
            crosshair: {
                mode: CrosshairMode.Normal,
            },
            handleScale: {
                axisPressedMouseMove: true,
                mouseWheel: true,
                pinch: true,
            },
            handleScroll: {
                mouseWheel: true,
                pressedMouseMove: true,
            },
        });

        const areaSeries = chart.addAreaSeries({
            lineColor: '#10b981',
            topColor: 'rgba(16, 185, 129, 0.22)',
            bottomColor: 'rgba(16, 185, 129, 0.00)',
            lineWidth: 2,
            priceLineVisible: true,
            lastValueVisible: true,
        });

        chartRef.current = chart;
        seriesRef.current = areaSeries;

        const container = chartContainerRef.current;
        const resizeObserver = new ResizeObserver((entries) => {
            if (entries.length === 0) return;
            const { width, height } = entries[0].contentRect;
            chart.applyOptions({ width, height });
        });
        resizeObserver.observe(container);

        return () => {
            resizeObserver.disconnect();
            chart.remove();
            chartRef.current = null;
            seriesRef.current = null;
        };
    }, [theme, chartReady]);

    // Bind candle data to chart series — also re-run when chart is first initialized
    useEffect(() => {
        if (seriesRef.current && candles.length > 0) {
            const formatted = candles.map((c) => ({
                time: c.time,
                value: c.close,
            }));
            seriesRef.current.setData(formatted);

            // Re-colorize line based on actual candle net change
            const isPositive = candles[candles.length - 1].close >= candles[0].close;
            seriesRef.current.applyOptions({
                lineColor: isPositive ? '#10b981' : '#ef4444',
                topColor: isPositive ? 'rgba(16, 185, 129, 0.22)' : 'rgba(239, 68, 68, 0.22)',
                bottomColor: isPositive ? 'rgba(16, 185, 129, 0.00)' : 'rgba(239, 68, 68, 0.00)',
            });

            chartRef.current?.timeScale().fitContent();
        }
    }, [candles, chartReady]);

    // Live update hook for active chart symbol
    useEffect(() => {
        const live = resolveSymbolPrice(selectedSymbol, { liveQuotes });
        if (live && live.price !== null && seriesRef.current && candles.length > 0) {
            const lastCandle = candles[candles.length - 1];
            if (timeframe === '1D') {
                seriesRef.current.update({
                    time: lastCandle.time,
                    value: live.price,
                });
            }
        }
    }, [liveQuotes, selectedSymbol, timeframe, candles]);

    const sessionTick = useSyncExternalStore(
        (cb) => marketSessionManager.subscribe(cb),
        () => marketSessionManager.getSnapshot().fetchedAt,
        () => 0
    );

    const isMarketOpen = useMemo(() => {
        return marketSessionManager.getSnapshot().isOpen;
    }, [sessionTick]);

    if (!overview) {
        return (
            <div className="p-4 lg:p-6 space-y-6">
                <div className="flex justify-between items-center mb-6">
                    <Skeleton className="h-9 w-64 rounded-lg" />
                    <Skeleton className="h-10 w-28 rounded-full" />
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-4">
                    <Skeleton variant="stat-card" count={5} />
                </div>
                <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
                    <div className="xl:col-span-8 space-y-6">
                        <div className="glass-card p-6 min-h-[400px]">
                            <Skeleton className="h-6 w-48 mb-6" />
                            <Skeleton className="h-[280px] w-full" />
                        </div>
                    </div>
                    <div className="xl:col-span-4 space-y-6">
                        <div className="glass-card p-6 min-h-[400px]">
                            <Skeleton className="h-6 w-48 mb-6" />
                            <Skeleton className="h-[280px] w-full" />
                        </div>
                    </div>
                </div>
            </div>
        );
    }

    // Mapping dropdown options
    const indexOptions = [
        { symbol: '^NSEI', name: 'NIFTY 50' },
        { symbol: '^BSESN', name: 'SENSEX' },
        { symbol: '^NSEBANK', name: 'BANK NIFTY' },
        { symbol: '^CNXFIN', name: 'FINNIFTY' },
        { symbol: '^CNXIT', name: 'NIFTY IT' },
    ];

    const activeIndexInfo = indexOptions.find((opt) => opt.symbol === selectedSymbol);
    const activeIndexLive = getLiveItem(
        overview.indices.find((i) => i.symbol === selectedSymbol) || { symbol: selectedSymbol }
    );
    const activeIndexPositive = (activeIndexLive.change ?? 0) >= 0;

    return (
        <div className="p-4 lg:p-6 space-y-6 animate-fade-in bg-[#f8fafc]/55 dark:bg-transparent">
            {/* Header Title Panel */}
            <div>
                <h1 className="text-3xl font-display font-bold text-heading tracking-tight">Market Overview</h1>
                <p className="text-sm text-gray-500 mt-0.5">Real-time Indian market indices and performance</p>
            </div>

            {/* Top Index Cards (5 Card Grid) */}
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-4">
                {overview.indices.map((idx) => {
                    const live = getLiveItem(idx);
                    const isPositive = (live.change ?? 0) >= 0;
                    const spkPrices = getLiveSparkline(idx);

                    // Compute Day Slider Range Position
                    const range = (live.high ?? 0) - (live.low ?? 0) || 1;
                    const positionPercent = Math.min(100, Math.max(0, (((live.price ?? live.low) - live.low) / range) * 100));

                    return (
                        <div
                            key={idx.symbol}
                            onClick={() => idx.symbol && setSelectedSymbol(idx.symbol)}
                            className={cn(
                                'rounded-2xl border border-gray-200/70 dark:border-neutral-800 bg-white dark:bg-neutral-900/60 p-5 cursor-pointer select-none transition-all duration-300 shadow-sm relative overflow-hidden flex flex-col justify-between hover:shadow-md hover:border-emerald-500/20 dark:hover:border-emerald-500/20 active:scale-[0.98]',
                                selectedSymbol === idx.symbol && 'ring-2 ring-emerald-500/35 border-emerald-500/30 dark:border-emerald-500/40'
                            )}
                        >
                            {/* Card Header */}
                            <div className="flex items-center justify-between">
                                <span className="text-[11px] font-bold text-gray-400 dark:text-gray-500 uppercase tracking-wider">
                                    {live.name}
                                </span>
                                <div className={cn('p-1 rounded-md', isPositive ? 'bg-emerald-500/10' : 'bg-red-500/10')}>
                                    {isPositive ? (
                                        <ArrowUpRight className="w-3.5 h-3.5 text-emerald-500" />
                                    ) : (
                                        <ArrowDownRight className="w-3.5 h-3.5 text-red-500" />
                                    )}
                                </div>
                            </div>

                            {/* LTP and Sparkline Row */}
                            <div className="mt-3 flex items-center justify-between gap-4">
                                <div className="space-y-1">
                                    <div className="text-2xl font-price font-bold text-heading tracking-tight tabular-nums">
                                        {live.price ? Number(live.price).toLocaleString('en-IN', { minimumFractionDigits: 2 }) : '—'}
                                    </div>
                                    <div className={cn('flex items-center gap-1 text-[11px] font-semibold tabular-nums', isPositive ? 'text-emerald-500' : 'text-red-500')}>
                                        <span>{isPositive ? '▲' : '▼'}</span>
                                        <span>{live.change ? Number(Math.abs(live.change)).toFixed(2) : '—'}</span>
                                        <span className="opacity-90">({formatPercent(live.change_percent)})</span>
                                    </div>
                                </div>
                                <div className="flex-shrink-0">
                                    <Sparkline prices={spkPrices} isPositive={isPositive} />
                                </div>
                            </div>

                            {/* Range Slider Block */}
                            <div className="mt-5 space-y-1.5">
                                <div className="relative w-full h-1 bg-gray-100 dark:bg-neutral-800 rounded-full">
                                    <div
                                        className={cn('absolute top-0 bottom-0 rounded-full', isPositive ? 'bg-emerald-500' : 'bg-red-500')}
                                        style={{ left: 0, width: `${positionPercent}%` }}
                                    />
                                    <div
                                        className={cn('absolute top-1/2 -translate-y-1/2 w-2 h-2 rounded-full border border-white dark:border-neutral-900 shadow-sm', isPositive ? 'bg-emerald-500' : 'bg-red-500')}
                                        style={{ left: `${positionPercent}%`, transform: 'translate(-50%, -50%)' }}
                                    />
                                </div>
                                <div className="flex justify-between text-[10px] text-gray-400 font-medium">
                                    <div>
                                        <span className="text-gray-450 block text-[9px] uppercase tracking-wider leading-none mb-0.5">Day Low</span>
                                        <span className="font-price font-semibold text-heading tabular-nums">{live.low ? Number(live.low).toLocaleString('en-IN', { maximumFractionDigits: 2 }) : '—'}</span>
                                    </div>
                                    <div className="text-right">
                                        <span className="text-gray-450 block text-[9px] uppercase tracking-wider leading-none mb-0.5">Day High</span>
                                        <span className="font-price font-semibold text-heading tabular-nums">{live.high ? Number(live.high).toLocaleString('en-IN', { maximumFractionDigits: 2 }) : '—'}</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    );
                })}
            </div>

            {/* Middle & Bottom Dashboard Grid */}
            <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
                {/* Left Side Column: Chart & Sector Performance */}
                <div className="xl:col-span-8 space-y-6">
                    {/* Interactive Area Chart */}
                    <div className="rounded-2xl border border-gray-200/70 dark:border-neutral-800 bg-white dark:bg-neutral-900/60 p-5 shadow-sm flex flex-col justify-between">
                        {/* Chart Control Header */}
                        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-4">
                            {/* Timeframe Selectors */}
                            <div className="flex items-center gap-1 bg-gray-100 dark:bg-neutral-900 p-1 rounded-lg self-start">
                                {['1D', '1W', '1M', '3M', '1Y', '5Y'].map((tf) => (
                                    <button
                                        key={tf}
                                        onClick={() => setTimeframe(tf)}
                                        className={cn(
                                            'px-3 py-1.5 rounded-md text-xs font-semibold select-none transition-all cursor-pointer',
                                            timeframe === tf
                                                ? 'bg-emerald-500 text-white shadow-sm'
                                                : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'
                                        )}
                                    >
                                        {tf}
                                    </button>
                                ))}
                            </div>

                            {/* Selector and Option Badges */}
                            <div className="flex items-center gap-2 self-end">
                                {/* Details Header */}
                                <div className="text-right hidden md:block">
                                    <span className="text-[10px] text-gray-450 uppercase tracking-widest font-bold block leading-none mb-1">
                                        Active Index Info
                                    </span>
                                    <div className="flex items-center gap-2 text-sm font-semibold text-heading leading-none">
                                        <span>{activeIndexInfo?.name || selectedSymbol}</span>
                                        <span className="text-gray-400">&gt;</span>
                                        <span className="font-price font-bold tabular-nums">
                                            {activeIndexLive.price ? Number(activeIndexLive.price).toLocaleString('en-IN', { minimumFractionDigits: 2 }) : '—'}
                                        </span>
                                        <span className={cn('text-xs font-semibold tabular-nums', activeIndexPositive ? 'text-emerald-500' : 'text-red-500')}>
                                            {activeIndexPositive ? '+' : ''}
                                            {activeIndexLive.change ? Number(activeIndexLive.change).toFixed(2) : '—'}
                                            ({formatPercent(activeIndexLive.change_percent)})
                                        </span>
                                    </div>
                                </div>

                                {/* Custom Dropdown Selector */}
                                <div className="relative" ref={dropdownRef}>
                                    <button
                                        onClick={() => setDropdownOpen(!dropdownOpen)}
                                        className="inline-flex items-center justify-between gap-2 px-3 py-2 text-xs font-semibold text-gray-700 dark:text-gray-300 bg-gray-55 dark:bg-neutral-900 border border-gray-200 dark:border-neutral-800 rounded-lg cursor-pointer hover:bg-gray-100 dark:hover:bg-neutral-850 transition-all select-none min-w-[124px]"
                                    >
                                        <span>{activeIndexInfo?.name || selectedSymbol}</span>
                                        <ChevronDown className="w-4 h-4 text-gray-400" />
                                    </button>
                                    {dropdownOpen && (
                                        <div className="absolute right-0 mt-1.5 w-44 bg-white dark:bg-neutral-900 border border-gray-200 dark:border-neutral-800 rounded-xl shadow-lg z-50 overflow-hidden py-1">
                                            {indexOptions.map((opt) => (
                                                <button
                                                    key={opt.symbol}
                                                    onClick={() => {
                                                        setSelectedSymbol(opt.symbol);
                                                        setDropdownOpen(false);
                                                    }}
                                                    className={cn(
                                                        'w-full flex items-center justify-between px-4 py-2.5 text-xs text-left cursor-pointer hover:bg-gray-50 dark:hover:bg-neutral-800/80 transition-colors',
                                                        selectedSymbol === opt.symbol ? 'text-emerald-500 font-semibold' : 'text-gray-650 dark:text-gray-300'
                                                    )}
                                                >
                                                    {opt.name}
                                                </button>
                                            ))}
                                        </div>
                                    )}
                                </div>

                                {/* Fullscreen and Details Toggle */}
                                <button
                                    onClick={() => navigate(`/terminal?symbol=${encodeURIComponent(selectedSymbol)}`)}
                                    className="p-2 rounded-lg bg-gray-55 dark:bg-neutral-900 border border-gray-200 dark:border-neutral-800 text-gray-550 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-neutral-850 cursor-pointer transition-all"
                                    title="Open Index in Terminal"
                                >
                                    <Maximize2 className="w-4 h-4" />
                                </button>
                            </div>
                        </div>

                        {/* Chart Render Block */}
                        <div className="relative w-full h-[320px] rounded-lg overflow-hidden bg-white dark:bg-transparent">
                            {chartLoading && (
                                <div className="absolute inset-0 z-10 flex items-center justify-center bg-white/40 dark:bg-neutral-950/40 backdrop-blur-xs">
                                    <div className="animate-spin rounded-full h-8 w-8 border-2 border-emerald-500 border-t-transparent" />
                                </div>
                            )}
                            <div ref={chartContainerRef} className="w-full h-full" />
                        </div>

                        {/* Stats Info Panel */}
                        <div className="grid grid-cols-2 sm:grid-cols-6 gap-4 border-t border-gray-200/50 dark:border-neutral-800/60 pt-5 mt-4 text-xs select-none">
                            <div>
                                <span className="text-[10px] text-gray-400 block uppercase tracking-wider font-bold mb-0.5">Prev. Close</span>
                                <span className="font-price font-bold text-heading tabular-nums">
                                    {activeIndexLive.prev_close ? Number(activeIndexLive.prev_close).toLocaleString('en-IN', { maximumFractionDigits: 2 }) : '—'}
                                </span>
                            </div>
                            <div>
                                <span className="text-[10px] text-gray-400 block uppercase tracking-wider font-bold mb-0.5 flex items-center gap-0.5">
                                    Open
                                    <Info className="w-3 h-3 text-gray-400 cursor-help" title="Index opening price for today" />
                                </span>
                                <span className="font-price font-bold text-heading tabular-nums">
                                    {activeIndexLive.open ? Number(activeIndexLive.open).toLocaleString('en-IN', { maximumFractionDigits: 2 }) : '—'}
                                </span>
                            </div>
                            <div>
                                <span className="text-[10px] text-gray-400 block uppercase tracking-wider font-bold mb-0.5">Day High</span>
                                <span className="font-price font-bold text-heading tabular-nums">
                                    {activeIndexLive.high ? Number(activeIndexLive.high).toLocaleString('en-IN', { maximumFractionDigits: 2 }) : '—'}
                                </span>
                            </div>
                            <div>
                                <span className="text-[10px] text-gray-400 block uppercase tracking-wider font-bold mb-0.5">Day Low</span>
                                <span className="font-price font-bold text-heading tabular-nums">
                                    {activeIndexLive.low ? Number(activeIndexLive.low).toLocaleString('en-IN', { maximumFractionDigits: 2 }) : '—'}
                                </span>
                            </div>
                            <div>
                                <span className="text-[10px] text-gray-400 block uppercase tracking-wider font-bold mb-0.5">52W High</span>
                                <span className="font-price font-bold text-heading tabular-nums">
                                    {activeIndexLive.high_52w ? Number(activeIndexLive.high_52w).toLocaleString('en-IN', { maximumFractionDigits: 2 }) : '—'}
                                </span>
                            </div>
                            <div>
                                <span className="text-[10px] text-gray-400 block uppercase tracking-wider font-bold mb-0.5">52W Low</span>
                                <span className="font-price font-bold text-heading tabular-nums">
                                    {activeIndexLive.low_52w ? Number(activeIndexLive.low_52w).toLocaleString('en-IN', { maximumFractionDigits: 2 }) : '—'}
                                </span>
                            </div>
                        </div>
                    </div>

                    {/* Sector Performance Section */}
                    <div className="rounded-2xl border border-gray-200/70 dark:border-neutral-800 bg-white dark:bg-neutral-900/60 p-5 shadow-sm select-none">
                        <div className="flex items-center justify-between mb-4">
                            <h2 className="text-sm font-bold text-heading uppercase tracking-wider flex items-center gap-1.5">
                                Sector Performance
                            </h2>
                            <button
                                onClick={() => navigate('/watchlist')}
                                className="text-xs text-emerald-500 font-semibold hover:underline"
                            >
                                View All Sectors
                            </button>
                        </div>
                        <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-5 gap-4">
                            {overview.sectors.map((sec) => {
                                const live = getLiveItem(sec);
                                const isPositive = (live.change ?? 0) >= 0;
                                const IconComponent = SECTOR_ICONS[sec.symbol] || Laptop;

                                return (
                                    <div
                                        key={sec.symbol}
                                        onClick={() => sec.symbol && navigate(`/terminal?symbol=${encodeURIComponent(sec.symbol)}`)}
                                        className={cn(
                                            'rounded-xl p-4 transition-all duration-300 border flex flex-col gap-2 cursor-pointer active:scale-95',
                                            isPositive
                                                ? 'bg-emerald-50/40 dark:bg-emerald-950/10 border-emerald-100 dark:border-emerald-900/30 hover:border-emerald-350 hover:bg-emerald-50/70 dark:hover:bg-emerald-950/20'
                                                : 'bg-red-50/40 dark:bg-red-950/10 border-red-100 dark:border-red-900/30 hover:border-red-350 hover:bg-red-50/70 dark:hover:bg-red-950/20'
                                        )}
                                    >
                                        <div className="flex items-center justify-between">
                                            <div className={cn('p-1.5 rounded-lg', isPositive ? 'bg-emerald-500/10' : 'bg-red-500/10')}>
                                                <IconComponent className={cn('w-4 h-4', isPositive ? 'text-emerald-500' : 'text-red-550')} />
                                            </div>
                                            <span className={cn('text-xs font-bold tabular-nums', isPositive ? 'text-emerald-550' : 'text-red-500')}>
                                                {formatPercent(live.change_percent)}
                                            </span>
                                        </div>
                                        <div className="space-y-0.5">
                                            <div className="text-[10px] uppercase font-bold tracking-wider text-gray-500 truncate" title={live.name}>
                                                {live.name}
                                            </div>
                                            <div className="text-xs font-price font-bold text-heading tabular-nums">
                                                {live.price ? Number(live.price).toLocaleString('en-IN', { maximumFractionDigits: 2 }) : '—'}
                                            </div>
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                </div>

                {/* Right Side Column: Movers, Breadth, Sentiment */}
                <div className="xl:col-span-4 space-y-6">
                    {/* Top Movers Row (Gainers & Losers side-by-side) */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {/* Top Gainers Card */}
                        <div className="rounded-2xl border border-gray-200/70 dark:border-neutral-800 bg-white dark:bg-neutral-900/60 p-5 shadow-sm select-none">
                            <div className="flex items-center justify-between mb-3.5">
                                <h2 className="text-xs font-bold text-heading uppercase tracking-wider flex items-center gap-1.5">
                                    <TrendingUp className="w-4 h-4 text-emerald-500" />
                                    Top Gainers
                                </h2>
                                <button onClick={() => navigate('/watchlist')} className="text-[10px] text-emerald-500 font-semibold hover:underline">
                                    View All
                                </button>
                            </div>
                            <div className="space-y-3">
                                {overview.gainers.slice(0, 5).map((stock, i) => {
                                    const live = getLiveItem(stock);
                                    return (
                                        <div
                                            key={stock.symbol}
                                            onClick={() => stock.symbol && navigate(`/terminal?symbol=${encodeURIComponent(stock.symbol)}`)}
                                            className="flex items-center justify-between py-1 border-b border-gray-100/50 dark:border-neutral-800/40 hover:bg-gray-50/50 dark:hover:bg-neutral-800/30 rounded-lg px-1 transition-all cursor-pointer active:scale-98"
                                        >
                                            <div className="flex items-center gap-2.5 truncate">
                                                <span className="text-[10px] font-bold text-gray-400 w-3">{i + 1}</span>
                                                <span className="text-xs font-bold text-heading truncate" title={live.symbol}>
                                                    {cleanSymbol(live.symbol)}
                                                </span>
                                            </div>
                                            <div className="text-right space-y-0.5">
                                                <div className="text-xs font-price font-bold text-heading tabular-nums">
                                                    {live.price ? Number(live.price).toLocaleString('en-IN', { minimumFractionDigits: 2 }) : '—'}
                                                </div>
                                                <div className="text-[10px] font-price font-semibold text-emerald-500 tabular-nums">
                                                    {formatPercent(live.change_percent)}
                                                </div>
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>

                        {/* Top Losers Card */}
                        <div className="rounded-2xl border border-gray-200/70 dark:border-neutral-800 bg-white dark:bg-neutral-900/60 p-5 shadow-sm select-none">
                            <div className="flex items-center justify-between mb-3.5">
                                <h2 className="text-xs font-bold text-heading uppercase tracking-wider flex items-center gap-1.5">
                                    <TrendingDown className="w-4 h-4 text-red-500" />
                                    Top Losers
                                </h2>
                                <button onClick={() => navigate('/watchlist')} className="text-[10px] text-red-550 font-semibold hover:underline">
                                    View All
                                </button>
                            </div>
                            <div className="space-y-3">
                                {overview.losers.slice(0, 5).map((stock, i) => {
                                    const live = getLiveItem(stock);
                                    return (
                                        <div
                                            key={stock.symbol}
                                            onClick={() => stock.symbol && navigate(`/terminal?symbol=${encodeURIComponent(stock.symbol)}`)}
                                            className="flex items-center justify-between py-1 border-b border-gray-100/50 dark:border-neutral-800/40 hover:bg-gray-50/50 dark:hover:bg-neutral-800/30 rounded-lg px-1 transition-all cursor-pointer active:scale-98"
                                        >
                                            <div className="flex items-center gap-2.5 truncate">
                                                <span className="text-[10px] font-bold text-gray-400 w-3">{i + 1}</span>
                                                <span className="text-xs font-bold text-heading truncate" title={live.symbol}>
                                                    {cleanSymbol(live.symbol)}
                                                </span>
                                            </div>
                                            <div className="text-right space-y-0.5">
                                                <div className="text-xs font-price font-bold text-heading tabular-nums">
                                                    {live.price ? Number(live.price).toLocaleString('en-IN', { minimumFractionDigits: 2 }) : '—'}
                                                </div>
                                                <div className="text-[10px] font-price font-semibold text-red-500 tabular-nums">
                                                    {formatPercent(live.change_percent)}
                                                </div>
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    </div>

                    {/* Stats Widget Row (Breadth & Sentiment) */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {/* Market Breadth Card */}
                        <div className="rounded-2xl border border-gray-200/70 dark:border-neutral-800 bg-white dark:bg-neutral-900/60 p-5 shadow-sm select-none flex flex-col justify-between min-h-[190px]">
                            <div>
                                <div className="flex items-center justify-between mb-3">
                                    <h2 className="text-xs font-bold text-heading uppercase tracking-wider">
                                        Market Breadth
                                    </h2>
                                    <button onClick={() => navigate('/watchlist')} className="text-[10px] text-emerald-500 font-semibold hover:underline">
                                        More Details
                                    </button>
                                </div>

                                {/* Text Stats */}
                                <div className="grid grid-cols-3 gap-2 text-center mt-2 select-none">
                                    <div className="space-y-0.5">
                                        <span className="text-[9px] text-gray-400 uppercase tracking-wider block font-bold leading-none">Advances</span>
                                        <span className="text-sm font-bold text-emerald-500 tabular-nums">
                                            {overview.breadth.advances.toLocaleString()}
                                        </span>
                                    </div>
                                    <div className="space-y-0.5">
                                        <span className="text-[9px] text-gray-400 uppercase tracking-wider block font-bold leading-none">Declines</span>
                                        <span className="text-sm font-bold text-red-500 tabular-nums">
                                            {overview.breadth.declines.toLocaleString()}
                                        </span>
                                    </div>
                                    <div className="space-y-0.5">
                                        <span className="text-[9px] text-gray-400 uppercase tracking-wider block font-bold leading-none">Unchanged</span>
                                        <span className="text-sm font-bold text-gray-400 dark:text-gray-500 tabular-nums">
                                            {overview.breadth.unchanged.toLocaleString()}
                                        </span>
                                    </div>
                                </div>
                            </div>

                            {/* Proportion Progress Segment Bar */}
                            <div className="mt-4">
                                <div className="flex h-2 w-full rounded-full overflow-hidden bg-gray-100 dark:bg-neutral-800">
                                    <div
                                        style={{ width: `${(overview.breadth.advances / overview.breadth.total) * 100}%` }}
                                        className="bg-emerald-500"
                                    />
                                    <div
                                        style={{ width: `${(overview.breadth.declines / overview.breadth.total) * 100}%` }}
                                        className="bg-red-500"
                                    />
                                    <div
                                        style={{ width: `${(overview.breadth.unchanged / overview.breadth.total) * 100}%` }}
                                        className="bg-gray-400 dark:bg-neutral-600"
                                    />
                                </div>
                                <div className="flex justify-between text-[10px] font-bold mt-1.5 text-heading tabular-nums px-0.5 select-none">
                                    <span className="text-emerald-500">
                                        {Math.round((overview.breadth.advances / overview.breadth.total) * 100)}%
                                    </span>
                                    <span className="text-red-500">
                                        {Math.round((overview.breadth.declines / overview.breadth.total) * 100)}%
                                    </span>
                                    <span className="text-gray-400 dark:text-gray-500">
                                        {Math.round((overview.breadth.unchanged / overview.breadth.total) * 100)}%
                                    </span>
                                </div>
                            </div>
                        </div>

                        {/* Market Sentiment Card */}
                        <div className="rounded-2xl border border-gray-200/70 dark:border-neutral-800 bg-white dark:bg-neutral-900/60 p-5 shadow-sm select-none flex flex-col justify-between text-center min-h-[190px]">
                            <div className="flex items-center justify-between mb-3 text-left">
                                <h2 className="text-xs font-bold text-heading uppercase tracking-wider">
                                    Market Sentiment
                                </h2>
                                <a href="#" onClick={(e) => e.preventDefault()} className="text-[10px] text-emerald-500 font-semibold hover:underline">
                                    More Insights
                                </a>
                            </div>

                            {/* Gauge and Dial */}
                            <div className="flex items-center justify-center my-1 select-none">
                                <div className="relative">
                                    <SentimentGauge score={overview.sentiment.score} />
                                    <div className="absolute bottom-1 left-1/2 -translate-x-1/2 text-center select-none leading-none">
                                        <span className="text-[10px] text-gray-400 font-bold uppercase block tracking-wider mb-0.5">Sentiment</span>
                                        <span className={cn('text-sm font-extrabold uppercase', overview.sentiment.score >= 50 ? 'text-emerald-500' : 'text-red-550')}>
                                            {overview.sentiment.label}
                                        </span>
                                    </div>
                                </div>
                            </div>

                            {/* Dynamic Score Text */}
                            <div className="text-[11px] font-medium text-gray-500 leading-tight select-none mt-2 px-1">
                                {overview.sentiment.description} (Score: <span className="font-bold text-heading tabular-nums">{overview.sentiment.score}/100</span>)
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            {/* Bottom Status Disclaimer Footer */}
            <div className="flex flex-col md:flex-row items-center justify-between border-t border-gray-200/40 dark:border-neutral-800/40 pt-4 mt-6 text-xs text-gray-400 gap-3 select-none">
                <div className="flex items-center gap-1.5 text-[11px]">
                    <Info className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
                    <span>Market data is real-time and updated continuously during market hours.</span>
                </div>
                <div className="flex items-center gap-2">
                    <span className="text-[11px] font-medium text-gray-405">
                        Market Hours: 9:15 AM – 3:30 PM IST
                    </span>
                    <span className={cn('inline-block w-2 h-2 rounded-full ring-2 ring-opacity-35', isMarketOpen ? 'bg-emerald-500 ring-emerald-500' : 'bg-gray-400 ring-gray-400')} />
                    <span className="font-semibold uppercase tracking-wider text-[10px]">
                        {isMarketOpen ? 'Market Open' : 'Market Closed'}
                    </span>
                </div>
            </div>
        </div>
    );
}
