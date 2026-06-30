// Navbar.jsx
import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useTheme } from '../../context/ThemeContext';
import { useMarketStore } from '../../store/useMarketStore';
import { usePortfolioStore } from '../../store/usePortfolioStore';
import { useWatchlistStore } from '../../stores/useWatchlistStore';
import { useBrokerStore } from '../../stores/useBrokerStore';
import { getBrokerMeta } from '../broker/brokerMeta';
import api from '../../services/api';
import { cn } from '../../utils/cn';
import { useMarketSession } from '../../hooks/useMarketSession';
import { formatCurrency, formatPercent, pnlColorClass } from '../../utils/formatters';
import { buildPortfolioMetrics } from '../../utils/portfolioMetrics';
import {
    Search,
    Menu,
    Bell,
    Moon,
    Sun,
    Check,
    X,
    Clock,
    AlertTriangle,
    Info,
    TrendingUp,
    BadgeIndianRupee,
    Star,
} from 'lucide-react';

/**
 * Fixed top navigation bar — 56px tall.
 * Hosts: menu toggle, global search (with watchlist star), market status, WS status, theme toggle.
 */

// ── Notification helpers ──────────────────────────────────────────────────────

const NOTIF_ICONS = {
    order_complete: { Icon: Check, color: 'text-bull', bg: 'bg-bull/15' },
    order_pending: { Icon: Clock, color: 'text-primary-600', bg: 'bg-primary-500/15' },
    order_rejected: { Icon: X, color: 'text-bear', bg: 'bg-bear/15' },
    market_open: { Icon: TrendingUp, color: 'text-bull', bg: 'bg-bull/15' },
    market_close: { Icon: Info, color: 'text-primary-600', bg: 'bg-primary-500/15' },
    info: { Icon: Info, color: 'text-gray-500', bg: 'bg-surface-800/60' },
    warning: { Icon: AlertTriangle, color: 'text-primary-600', bg: 'bg-primary-500/15' },
};

function timeAgo(ts) {
    const diff = Date.now() - ts;
    if (diff < 60_000) return 'Just now';
    if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
    if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
    return `${Math.floor(diff / 86_400_000)}d ago`;
}

function NotificationPanel({ notifications, onClear, onDismiss }) {
    return (
        <div className="absolute top-full right-0 mt-2 w-80 bg-[var(--bg-surface)] border border-[var(--border)] rounded-xl shadow-xl z-50 overflow-hidden animate-slide-in">
            <div className="flex items-center justify-between px-4 py-2.5 border-b border-[var(--border)]">
                <span className="text-sm font-semibold text-heading">Notifications</span>
                {notifications.length > 0 && (
                    <button
                        onClick={onClear}
                        className="text-[11px] text-gray-500 hover:text-heading transition-colors"
                    >
                        Clear all
                    </button>
                )}
            </div>
            <div className="max-h-80 overflow-y-auto">
                {notifications.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-10 gap-2">
                        <Bell className="w-7 h-7 text-gray-500 opacity-30" />
                        <span className="text-xs text-gray-500">No notifications</span>
                    </div>
                ) : (
                    notifications.map((n) => {
                        const cfg = NOTIF_ICONS[n.type] || NOTIF_ICONS.info;
                        const { Icon } = cfg;
                        return (
                            <div
                                key={n.id}
                                className="flex items-start gap-3 px-4 py-3 border-b border-[var(--border)]/40 last:border-0 transition-colors hover:bg-[var(--bg-raised)]"
                            >
                                <div className={cn('w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5', cfg.bg)}>
                                    <Icon className={cn('w-4 h-4', cfg.color)} />
                                </div>
                                <div className="flex-1 min-w-0">
                                    <p className="text-xs text-heading font-medium leading-snug">{n.title}</p>
                                    <p className="text-[11px] text-gray-500 mt-0.5 leading-snug">{n.message}</p>
                                    <span className="text-[10px] text-gray-500 opacity-60 mt-1 inline-block">{timeAgo(n.timestamp)}</span>
                                </div>
                                <button
                                    onClick={() => onDismiss(n.id)}
                                    className="text-gray-500 hover:text-heading transition-colors flex-shrink-0 mt-1"
                                    title="Dismiss"
                                >
                                    <X className="w-3.5 h-3.5" />
                                </button>
                            </div>
                        );
                    })
                )}
            </div>
        </div>
    );
}

export default function Navbar({ onMenuToggle }) {
    const { theme, toggleTheme } = useTheme();
    const navigate = useNavigate();
    const location = useLocation();
    const wsStatus = useMarketStore((s) => s.wsStatus);
    const lastQuoteAt = useMarketStore((s) => s.lastQuoteAt);
    const liveQuotes = useMarketStore((s) => s.symbols);

    const summary = usePortfolioStore((s) => s.summary);
    const holdings = usePortfolioStore((s) => s.holdings);
    const pnl = usePortfolioStore((s) => s.pnl);
    const refreshPortfolio = usePortfolioStore((s) => s.refreshPortfolio);
    const orders = usePortfolioStore((s) => s.orders);

    // ── Watchlist store ────────────────────────────────────────────────────────
    // FIX: Select only stable primitives/actions from the store individually.
    // Never select a derived array like `items` inline — that creates a new array
    // reference every render and causes an infinite update loop.
    // Instead: select `watchlists` + `activeId` (stable references that only change
    // when data actually changes), then derive `watchlistedSymbols` with useMemo.
    const watchlists = useWatchlistStore((s) => s.watchlists);
    const activeId = useWatchlistStore((s) => s.activeId);
    const addToWatchlist = useWatchlistStore((s) => s.addItem);
    const removeFromWatchlist = useWatchlistStore((s) => s.removeItem);

    // Broker status state from useBrokerStore
    const brokers = useBrokerStore((s) => s.brokers);
    const fetchStatus = useBrokerStore((s) => s.fetchStatus);
    const statusLoaded = useBrokerStore((s) => s.statusLoaded);

    const connectedBrokerEntry = useMemo(() => {
        return Object.entries(brokers).find(([, info]) => info.status === 'connected')
            || Object.entries(brokers).find(([, info]) => info.status === 'expired');
    }, [brokers]);

    const connectedBroker = connectedBrokerEntry?.[0] || null;
    const connectedInfo = connectedBrokerEntry?.[1] || null;
    const connectedMeta = useMemo(() => connectedBroker ? getBrokerMeta(connectedBroker) : null, [connectedBroker]);

    // Derive the active watchlist's items safely — only recomputes when watchlists
    // or activeId actually changes, not on every render.
    const watchlistItems = useMemo(() => {
        return watchlists.find(w => w.id === activeId)?.items ?? [];
    }, [watchlists, activeId]);

    // Stable O(1) set of watchlisted symbols for fast lookup in the dropdown
    const watchlistedSymbols = useMemo(
        () => new Set(watchlistItems.map((i) => i.symbol)),
        [watchlistItems]
    );

    const [searchQuery, setSearchQuery] = useState('');
    const [searchResults, setSearchResults] = useState([]);
    const [popularResults, setPopularResults] = useState([]);
    const [showResults, setShowResults] = useState(false);
    const [searchFocused, setSearchFocused] = useState(false);
    const { marketOpen, sessionLabel } = useMarketSession();
    const [showNotifications, setShowNotifications] = useState(false);
    const [notifications, setNotifications] = useState([]);
    const seenOrderIdsRef = useRef(new Set());
    const [starredNow, setStarredNow] = useState(new Set());
    const searchRef = useRef(null);
    const bellRef = useRef(null);

    // Fetch broker status on mount if not loaded
    useEffect(() => {
        if (!statusLoaded) {
            fetchStatus();
        }
    }, [statusLoaded, fetchStatus]);

    // Ensure navbar has the same portfolio source data used by Portfolio page
    useEffect(() => {
        if (!summary && holdings.length === 0) {
            refreshPortfolio();
        }
    }, [refreshPortfolio, summary, holdings.length]);

    // ── Close notification panel on outside click ─────────────────────────────
    useEffect(() => {
        if (!showNotifications) return;
        const handler = (e) => {
            if (bellRef.current && !bellRef.current.contains(e.target)) {
                setShowNotifications(false);
            }
        };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, [showNotifications]);

    // ── Generate notifications from orders ────────────────────────────────────
    useEffect(() => {
        if (!orders || orders.length === 0) return;
        const newNotifs = [];
        orders.forEach((o) => {
            if (seenOrderIdsRef.current.has(o.id)) return;
            seenOrderIdsRef.current.add(o.id);
            const sym = o.symbol?.replace('.NS', '') || 'Unknown';
            const side = o.side || 'BUY';
            const qty = o.quantity || 0;
            const status = o.status || 'PENDING';

            let type = 'order_pending';
            let title = `Order ${status.charAt(0) + status.slice(1).toLowerCase()}`;
            let message = `${side} ${qty} × ${sym}`;

            if (status === 'FILLED' || status === 'COMPLETE') {
                type = 'order_complete';
                title = 'Order Filled';
                const price = o.filled_price ?? o.price;
                message = `${side} ${qty} × ${sym} @ ₹${price?.toFixed(2) ?? '—'}`;
            } else if (status === 'REJECTED' || status === 'CANCELLED') {
                type = 'order_rejected';
                title = `Order ${status.charAt(0) + status.slice(1).toLowerCase()}`;
            }

            newNotifs.push({
                id: `order-${o.id}`,
                type,
                title,
                message,
                timestamp: o.created_at ? new Date(o.created_at).getTime() : Date.now(),
                read: false,
            });
        });

        if (newNotifs.length > 0) {
            setNotifications((prev) => [...newNotifs, ...prev].slice(0, 50));
        }
    }, [orders]);

    // ── Generate notification on market status change ─────────────────────────
    const prevMarketOpen = useRef(null);
    useEffect(() => {
        if (prevMarketOpen.current === null) {
            prevMarketOpen.current = marketOpen;
            return;
        }
        if (prevMarketOpen.current !== marketOpen) {
            prevMarketOpen.current = marketOpen;
            setNotifications((prev) => [{
                id: `market-${Date.now()}`,
                type: marketOpen ? 'market_open' : 'market_close',
                title: marketOpen ? 'Market Opened' : 'Market Closed',
                message: marketOpen
                    ? 'NSE is now open for trading.'
                    : `NSE session: ${sessionLabel || 'closed'}.`,
                timestamp: Date.now(),
                read: false,
            }, ...prev].slice(0, 50));
        }
    }, [marketOpen, sessionLabel]);

    // ── Notification helpers ──────────────────────────────────────────────────
    const unreadCount = useMemo(() => notifications.filter((n) => !n.read).length, [notifications]);

    const handleDismiss = useCallback((id) => {
        setNotifications((prev) => prev.filter((n) => n.id !== id));
    }, []);

    const handleClearAll = useCallback(() => {
        setNotifications([]);
    }, []);

    const toggleNotifications = useCallback(() => {
        setShowNotifications((v) => {
            if (!v) {
                setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
            }
            return !v;
        });
    }, []);


    // ── Symbol search (debounced 200ms) ───────────────────────────────────────
    useEffect(() => {
        let active = true;
        (async () => {
            try {
                const res = await api.get('/market/popular');
                if (!active) return;
                setPopularResults((res.data?.stocks || []).slice(0, 10));
            } catch {
                if (active) setPopularResults([]);
            }
        })();
        return () => { active = false; };
    }, []);

    useEffect(() => {
        if (searchQuery.trim().length < 1) {
            setSearchResults([]);
            setShowResults(searchFocused && popularResults.length > 0);
            return;
        }
        const t = setTimeout(async () => {
            try {
                const res = await api.get(`/market/search?q=${encodeURIComponent(searchQuery.trim())}`);
                setSearchResults(res.data.results || []);
                setShowResults(true);
            } catch {
                // On error, still show empty state so user knows search ran
                setSearchResults([]);
                setShowResults(true);
            }
        }, 200);
        return () => clearTimeout(t);
    }, [searchQuery, searchFocused, popularResults.length]);

    // ── Reset search on route change ──────────────────────────────────────────
    useEffect(() => {
        setSearchQuery('');
        setSearchResults([]);
        setShowResults(false);
    }, [location.pathname]);

    // ── Close search on outside click ─────────────────────────────────────────
    useEffect(() => {
        const handler = (e) => {
            if (searchRef.current && !searchRef.current.contains(e.target)) {
                setSearchFocused(false);
                setShowResults(false);
                setSearchQuery('');
                setSearchResults([]);
            }
        };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, []);

    const handleSelectStock = useCallback((symbol) => {
        setSearchQuery('');
        setSearchFocused(false);
        setShowResults(false);
        navigate(`/terminal?symbol=${encodeURIComponent(symbol)}`);
    }, [navigate]);

    const dropdownResults = searchQuery.trim().length > 0 ? searchResults : popularResults;
    const showingRecommendations = searchQuery.trim().length === 0;

    // ── Star toggle ───────────────────────────────────────────────────────────
    const handleStarClick = useCallback((e, stock) => {
        e.stopPropagation();
        const symbol = stock.symbol;
        // Read latest items directly from store to avoid stale closure
        const currentItems = useWatchlistStore.getState().watchlists
            .find(w => w.id === useWatchlistStore.getState().activeId)?.items ?? [];
        const existing = currentItems.find((i) => i.symbol === symbol);

        if (existing) {
            removeFromWatchlist(existing.id);
        } else {
            addToWatchlist(symbol, stock.exchange || 'NSE');
            setStarredNow((prev) => new Set([...prev, symbol]));
            setTimeout(() => {
                setStarredNow((prev) => {
                    const next = new Set(prev);
                    next.delete(symbol);
                    return next;
                });
            }, 600);
        }
    }, [addToWatchlist, removeFromWatchlist]);

    // ── Derived display values ─────────────────────────────────────────────────
    const statusText = sessionLabel;
    const statusColor = marketOpen ? 'bg-green-400' : 'bg-primary-500';

    const hasFreshQuotes = lastQuoteAt > 0 && (Date.now() - lastQuoteAt) < 90_000;
    const effectiveWsStatus = !marketOpen
        ? 'frozen'
        : wsStatus === 'connected'
            ? 'connected'
            : hasFreshQuotes
                ? 'connected'
                : wsStatus;

    const wsColor = {
        connected: 'bg-green-400',
        frozen: 'bg-primary-500',
        connecting: 'bg-primary-500 animate-pulse',
        disconnected: 'bg-gray-500',
        error: 'bg-red-400',
    }[effectiveWsStatus];
    const wsLabel = {
        connected: 'Live',
        frozen: 'Frozen',
        connecting: 'Connecting',
        disconnected: 'Offline',
        error: 'Error',
    }[effectiveWsStatus];

    const portfolioMetrics = useMemo(() => buildPortfolioMetrics({
        summary,
        pnl,
        holdings,
        liveQuotes,
    }), [summary, pnl, holdings, liveQuotes]);

    const totalPnl = Number(portfolioMetrics.totalPnl ?? 0);
    const totalPnlPct = Number(portfolioMetrics.totalPnlPct ?? 0);
    const hasPortfolioData = !!summary || holdings.length > 0;

    return (
        <header
            className={cn(
                'h-14 bg-surface-900/80 backdrop-blur-xl border-b border-edge/5',
                'flex items-center justify-between px-4 lg:px-6',
                'sticky top-0 z-30'
            )}
        >

            {/* Left: hamburger (mobile) + search */}
            <div className="flex items-center gap-2 sm:gap-3 min-w-0 flex-1">
                <button
                    type="button"
                    onClick={onMenuToggle}
                    className="lg:hidden flex-shrink-0 p-2 rounded-lg text-gray-400 hover:text-heading hover:bg-overlay/5 transition-colors min-h-[44px] min-w-[44px] flex items-center justify-center"
                    aria-label="Open navigation menu"
                >
                    <Menu className="w-5 h-5" />
                </button>
                <div className="relative hidden sm:block flex-1 min-w-0 max-w-[340px]" ref={searchRef}>
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500 pointer-events-none" />
                    <input
                        type="text"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        onFocus={() => {
                            setSearchFocused(true);
                            setShowResults((searchResults.length > 0) || (popularResults.length > 0));
                        }}
                        onKeyDown={(e) => {
                            if (e.key === 'Escape') {
                                setSearchQuery('');
                                setSearchResults([]);
                                setSearchFocused(false);
                                setShowResults(false);
                            }
                        }}
                        placeholder="Search stocks… (e.g. RELIANCE, TCS)"
                        aria-label="Stock search"
                        className={cn(
                            'w-[300px] lg:w-[340px] bg-surface-800/60 border border-edge/5 rounded-lg',
                            'pl-10 pr-10 py-2 text-sm text-heading placeholder-gray-500',
                            'focus:outline-none focus:border-primary-500/30 transition-all duration-200'
                        )}
                    />

                    {/* ── Autocomplete dropdown ── */}
                    {showResults && (
                        <div
                            className="absolute top-full left-0 mt-1 bg-[var(--bg-surface)] border border-[var(--border)] rounded-xl shadow-xl z-50 max-h-[320px] overflow-y-auto animate-slide-in"
                            style={{ minWidth: '100%', width: 'max-content' }}
                        >
                            {showingRecommendations && (
                                <div className="px-4 py-2 text-[10px] uppercase tracking-wider text-gray-500 border-b border-[var(--border)]/40">
                                    Suggested Stocks
                                </div>
                            )}
                            {dropdownResults.length > 0 ? dropdownResults.map((stock) => {
                                const isWatchlisted = watchlistedSymbols.has(stock.symbol);
                                const justStarred = starredNow.has(stock.symbol);
                                return (
                                    <div
                                        key={stock.symbol}
                                        className="flex items-center border-b border-[var(--border)]/50 last:border-0"
                                    >
                                        <button
                                            onClick={() => handleSelectStock(stock.symbol)}
                                            className="flex-1 flex items-center gap-4 px-4 py-2.5 hover:bg-[var(--bg-raised)] transition-colors text-left"
                                        >
                                            <div className="flex-1 min-w-0">
                                                <div className="text-sm font-semibold text-heading">
                                                    {stock.symbol.replace(/^\^/, '').replace('.NS', '')}
                                                </div>
                                                <div className="text-xs text-gray-500 truncate">{stock.name}</div>
                                            </div>
                                            <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded flex-shrink-0 bg-surface-800/60 text-gray-500 border border-[var(--border)]/50">
                                                {stock.exchange}
                                            </span>
                                        </button>
                                        <button
                                            onClick={(e) => handleStarClick(e, stock)}
                                            title={isWatchlisted ? 'Remove from watchlist' : 'Add to watchlist'}
                                            className={cn(
                                                'flex-shrink-0 w-9 h-full flex items-center justify-center mr-1 rounded-lg transition-all duration-150',
                                                isWatchlisted
                                                    ? 'text-yellow-400 hover:text-gray-500 hover:bg-[var(--bg-raised)]'
                                                    : 'text-gray-500 hover:text-yellow-400 hover:bg-yellow-500/10',
                                                justStarred && 'scale-125'
                                            )}
                                        >
                                            {isWatchlisted
                                                ? <Star className="w-[17px] h-[17px]" fill="currentColor" />
                                                : <Star className="w-[17px] h-[17px]" />
                                            }
                                        </button>
                                    </div>
                                );
                            }) : (
                                <div className="px-4 py-3 text-center text-xs text-gray-500">
                                    {showingRecommendations
                                        ? 'No suggestions available right now'
                                        : `No results for “${searchQuery.trim()}”`}
                                </div>
                            )}
                        </div>
                    )}
                </div>
            </div>

            {/* Right: market status, WS status, theme, bell */}
            <div className="flex items-center gap-1.5">
                {/* Total P&L (same logic as Portfolio page) */}
                <div
                    className="hidden md:flex items-center gap-2 px-3 py-1.5 rounded-lg bg-surface-800/40 mr-1"
                    title="Total P&L from portfolio summary + live quote pricing"
                >
                    <BadgeIndianRupee className={cn('w-3.5 h-3.5', hasPortfolioData ? pnlColorClass(totalPnl) : 'text-gray-500')} />
                    <div className="flex items-center gap-1.5 text-xs font-medium tabular-nums">
                        <span className="text-gray-400">Total P&L</span>
                        <span className={cn(hasPortfolioData ? pnlColorClass(totalPnl) : 'text-gray-500')}>
                            {hasPortfolioData ? `${totalPnl >= 0 ? '+' : ''}${formatCurrency(totalPnl)}` : '—'}
                        </span>
                        {hasPortfolioData && (
                            <span className={cn('hidden xl:inline', pnlColorClass(totalPnl))}>
                                ({formatPercent(totalPnlPct)})
                            </span>
                        )}
                    </div>
                </div>

                {/* Broker Badge */}
                <div
                    onClick={() => navigate('/brokers')}
                    className={cn(
                        "hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-lg bg-surface-800/40 hover:bg-surface-800/80 cursor-pointer border border-edge/5 transition-all select-none mr-1",
                        connectedInfo?.status === 'expired' && "border-amber-500/20 bg-amber-500/5 hover:bg-amber-500/10"
                    )}
                    title={connectedBroker ? `${connectedMeta?.name}: ${connectedInfo?.status === 'connected' ? 'Active' : 'Session Expired'}. Click to manage.` : "No broker connected. Click to connect."}
                >
                    <div className={cn(
                        "w-2 h-2 rounded-full",
                        connectedInfo?.status === 'connected' ? "bg-emerald-400 animate-pulse" : connectedInfo?.status === 'expired' ? "bg-amber-400" : "bg-red-400"
                    )} />
                    <span className="text-xs font-medium text-heading">
                        {connectedBroker ? connectedMeta?.name : "No Broker"}
                    </span>
                    {connectedInfo?.status === 'expired' && (
                        <span className="text-[9px] bg-amber-500/20 text-amber-500 px-1 py-0.5 rounded font-semibold uppercase tracking-wider scale-90">
                            Expired
                        </span>
                    )}
                </div>

                {/* Market status */}
                <div className="hidden md:flex items-center gap-2 px-3 py-1.5 rounded-lg bg-surface-800/40 mr-1">
                    <div className={cn('w-2 h-2 rounded-full', statusColor, marketOpen && 'animate-pulse')} />
                    <span className="text-xs text-gray-400 font-medium">{statusText}</span>
                </div>

                {/* WebSocket status */}
                <div
                    className="hidden lg:flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-surface-800/40 mr-1"
                    title={`Transport: ${wsStatus}${hasFreshQuotes && wsStatus !== 'connected' ? ' • Data: active (fallback)' : ''}`}
                >
                    <div className={cn('w-1.5 h-1.5 rounded-full', wsColor)} />
                    <span className="text-xs text-gray-500">{wsLabel}</span>
                </div>

                {/* Theme toggle */}
                <button
                    onClick={toggleTheme}
                    className="relative p-2 rounded-lg text-gray-400 hover:text-heading hover:bg-overlay/5 transition-all duration-300 group"
                    aria-label="Toggle theme"
                >
                    <Sun
                        className={cn(
                            'w-5 h-5 absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 transition-all duration-500 ease-in-out',
                            theme === 'dark'
                                ? 'opacity-100 rotate-0 scale-100'
                                : 'opacity-0 rotate-90 scale-0'
                        )}
                    />
                    <Moon
                        className={cn(
                            'w-5 h-5 transition-all duration-500 ease-in-out',
                            theme === 'dark'
                                ? 'opacity-0 -rotate-90 scale-0'
                                : 'opacity-100 rotate-0 scale-100'
                        )}
                    />
                </button>

                {/* Notifications */}
                <div className="relative" ref={bellRef}>
                    <button
                        onClick={toggleNotifications}
                        className={cn(
                            'p-2 rounded-lg transition-all relative',
                            showNotifications
                                ? 'text-primary-600 bg-primary-500/10'
                                : 'text-gray-400 hover:text-heading hover:bg-overlay/5'
                        )}
                        aria-label="Notifications"
                    >
                        <Bell className={cn('w-5 h-5 transition-transform', unreadCount > 0 && 'animate-[bell-ring_0.5s_ease-in-out]')} />
                        {unreadCount > 0 && (
                            <span className="absolute top-1 right-1 min-w-[16px] h-4 px-1 rounded-full bg-primary-500 text-[10px] font-semibold text-white flex items-center justify-center leading-none">
                                {unreadCount > 9 ? '9+' : unreadCount}
                            </span>
                        )}
                    </button>
                    {showNotifications && (
                        <NotificationPanel
                            notifications={notifications}
                            onClear={handleClearAll}
                            onDismiss={handleDismiss}
                        />
                    )}
                </div>
            </div>
        </header>
    );
}   