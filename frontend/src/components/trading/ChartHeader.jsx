import { memo, useState, useRef, useEffect, useCallback } from 'react';
import { cn } from '../../utils/cn';
import { CHART_PERIODS, isMcxSymbol } from '../../utils/constants';
import { formatPrice, formatPercent, pnlColorClass, cleanSymbol } from '../../utils/formatters';
import api from '../../services/api';
import { useZeroLossStore } from '../../stores/useZeroLossStore';
import { useNavigate } from 'react-router-dom';
import { usePortfolioStore } from '../../store/usePortfolioStore';

const ALL_PERIODS = Object.entries(CHART_PERIODS);
const INTRADAY = ALL_PERIODS.filter(([, v]) => v.group === 'intraday');
const DAILY = ALL_PERIODS.filter(([, v]) => v.group === 'daily');
const EXTENDED = ALL_PERIODS.filter(([, v]) => v.group === 'extended');

function ChartHeader({
    symbol,
    quote,
    period,
    onPeriodChange,
    strategyDockOpen,
    onToggleStrategyDock,
    isWatchlisted = false,
    onToggleWatchlist,
    watchlistBusy = false,
    trendData,
    isMobile = false,
    hasPositions = false,
    orderPanelVisible = true,
    onToggleOrderPanel,
}) {
    const [open, setOpen] = useState(false);
    const [killSwitchBusy, setKillSwitchBusy] = useState(false);
    const [zlPopup, setZlPopup] = useState(false);
    const dropRef = useRef(null);
    const zlRef = useRef(null);
    const navigate = useNavigate();

    // ZeroLoss store
    const zlEnabled = useZeroLossStore((s) => s.enabled);
    const zlStats = useZeroLossStore((s) => s.stats);
    const zlPositions = useZeroLossStore((s) => s.activePositions);
    const zlLog = useZeroLossStore((s) => s.liveLog);
    const zlPosCount = Object.keys(zlPositions || {}).length;

    const handleKillSwitch = useCallback(async () => {
        if (!confirm('⚠️ KILL SWITCH: Close ALL open positions immediately?')) return;
        setKillSwitchBusy(true);
        try {
            const res = await api.post('/orders/close-all');
            const data = res.data;
            alert(data.message + (data.errors?.length ? '\nErrors: ' + data.errors.join(', ') : ''));
            await usePortfolioStore.getState().refreshPortfolio();
            setTimeout(() => {
                usePortfolioStore.getState().refreshPortfolio();
            }, 500);
        } catch (err) {
            alert('Kill switch failed: ' + (err.response?.data?.detail || err.message));
        } finally {
            setKillSwitchBusy(false);
        }
    }, []);

    // Close on outside click
    useEffect(() => {
        if (!open) return;
        const handler = (e) => {
            if (dropRef.current && !dropRef.current.contains(e.target)) setOpen(false);
        };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, [open]);

    // Close ZL popup on outside click
    useEffect(() => {
        if (!zlPopup) return;
        const handler = (e) => {
            if (zlRef.current && !zlRef.current.contains(e.target)) setZlPopup(false);
        };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, [zlPopup]);

    if (!symbol) return null;

    const currentLabel = CHART_PERIODS[period]?.label ?? period;
    const exchangeLabel = symbol.endsWith('.BO')
        ? 'BSE'
        : isMcxSymbol(symbol)
            ? 'MCX'
            : 'NSE';

    return (
        <div className="flex items-center w-full h-11 px-4 border-b border-edge/5 bg-surface-900/30">

            {/* ── LEFT: Symbol + Price + Change ──────────────────── */}
            <div className="flex items-center gap-3 flex-shrink-0">
                <div className="flex flex-col leading-none">
                    <span className="text-sm font-semibold text-heading truncate max-w-[120px]">
                        {cleanSymbol(symbol)}
                    </span>
                    <span className="text-[10px] text-gray-500 mt-0.5">{exchangeLabel}</span>
                </div>

                {quote?.price != null && (
                    <div className="flex items-center gap-2">
                        <span className="text-base font-semibold font-price text-heading tabular-nums">
                            {formatPrice(quote.price)}
                        </span>
                        {quote.change != null && !isMobile && (
                            <span className={cn(
                                'text-xs font-price font-medium whitespace-nowrap tabular-nums',
                                pnlColorClass(quote.change)
                            )}>
                                {quote.change >= 0 ? '+' : ''}
                                {formatPrice(quote.change)} ({formatPercent(quote.change_percent)})
                            </span>
                        )}
                    </div>
                )}
            </div>

            {/* Divider */}
            <div className="w-px h-5 bg-edge/10 mx-3 flex-shrink-0" />

            {/* ── CENTER: Timeframe dropdown + Strategy ───────────── */}
            <div className="flex items-center gap-2 flex-1 justify-center">
                {/* Timeframe dropdown */}
                <div className="relative" ref={dropRef}>
                    <button
                        onClick={() => setOpen((v) => !v)}
                        className={cn(
                            'h-7 px-2.5 rounded-md border text-xs font-semibold',
                            'inline-flex items-center gap-1.5 transition-colors duration-150',
                            open
                                ? 'bg-primary-600/20 border-primary-500/40 text-primary-600'
                                : 'bg-surface-800/80 border-edge/20 text-gray-600 hover:text-heading hover:border-edge/40'
                        )}
                    >
                        <span className="font-price tabular-nums">{currentLabel}</span>
                        <svg className={cn('w-3 h-3 transition-transform duration-150', open && 'rotate-180')} viewBox="0 0 20 20" fill="currentColor">
                            <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
                        </svg>
                    </button>

                    {open && (
                        <div className="absolute top-full left-1/2 -translate-x-1/2 mt-1.5 z-50 min-w-[160px] rounded-lg border border-edge/10 bg-surface-900/95 backdrop-blur-xl shadow-xl shadow-black/40 py-1.5">
                            <p className="px-3 pt-1 pb-1 text-[9px] font-semibold text-gray-500 uppercase tracking-wider">Intraday</p>
                            {INTRADAY.map(([key, { label }]) => (
                                <button
                                    key={key}
                                    onClick={() => { onPeriodChange?.(key); setOpen(false); }}
                                    className={cn(
                                        'w-full text-left px-3 py-1.5 text-xs font-medium transition-colors',
                                        'flex items-center justify-between',
                                        period === key
                                            ? 'bg-primary-600/15 text-primary-600'
                                            : 'text-gray-400 hover:text-heading hover:bg-edge/5'
                                    )}
                                >
                                    <span>{label}</span>
                                    {period === key && (
                                        <svg className="w-3 h-3 text-primary-600" viewBox="0 0 20 20" fill="currentColor">
                                            <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                                        </svg>
                                    )}
                                </button>
                            ))}
                            <div className="h-px bg-edge/10 my-1.5 mx-2" />
                            <p className="px-3 pt-1 pb-1 text-[9px] font-semibold text-gray-500 uppercase tracking-wider">Daily+</p>
                            {DAILY.map(([key, { label }]) => (
                                <button
                                    key={key}
                                    onClick={() => { onPeriodChange?.(key); setOpen(false); }}
                                    className={cn(
                                        'w-full text-left px-3 py-1.5 text-xs font-medium transition-colors',
                                        'flex items-center justify-between',
                                        period === key
                                            ? 'bg-primary-600/15 text-primary-600'
                                            : 'text-gray-400 hover:text-heading hover:bg-edge/5'
                                    )}
                                >
                                    <span>{label}</span>
                                    {period === key && (
                                        <svg className="w-3 h-3 text-primary-600" viewBox="0 0 20 20" fill="currentColor">
                                            <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                                        </svg>
                                    )}
                                </button>
                            ))}
                            <div className="h-px bg-edge/10 my-1.5 mx-2" />
                            <p className="px-3 pt-1 pb-1 text-[9px] font-semibold text-gray-500 uppercase tracking-wider">Extended</p>
                            {EXTENDED.map(([key, { label }]) => (
                                <button
                                    key={key}
                                    onClick={() => { onPeriodChange?.(key); setOpen(false); }}
                                    className={cn(
                                        'w-full text-left px-3 py-1.5 text-xs font-medium transition-colors',
                                        'flex items-center justify-between',
                                        period === key
                                            ? 'bg-primary-600/15 text-primary-600'
                                            : 'text-gray-400 hover:text-heading hover:bg-edge/5'
                                    )}
                                >
                                    <span>{label}</span>
                                    {period === key && (
                                        <svg className="w-3 h-3 text-primary-600" viewBox="0 0 20 20" fill="currentColor">
                                            <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                                        </svg>
                                    )}
                                </button>
                            ))}
                        </div>
                    )}
                </div>

                {!isMobile && (
                    <>
                        <button
                            onClick={onToggleWatchlist}
                            disabled={watchlistBusy}
                            className={cn(
                                'h-7 px-2 rounded-md border text-xs font-semibold',
                                'inline-flex items-center justify-center transition-colors duration-150 flex-shrink-0',
                                watchlistBusy && 'opacity-60 cursor-not-allowed',
                                isWatchlisted
                                    ? 'bg-primary-600/20 border-primary-500/40 text-primary-600'
                                    : 'bg-surface-800/80 border-edge/20 text-gray-400 hover:text-gray-700 hover:border-edge/40'
                            )}
                            title={isWatchlisted ? 'Remove from watchlist' : 'Add to watchlist'}
                            aria-label={isWatchlisted ? 'Remove from watchlist' : 'Add to watchlist'}
                        >
                            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill={isWatchlisted ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="2">
                                <path d="m12 2 3.09 6.26L22 9.27l-5 4.87L18.18 22 12 18.56 5.82 22 7 14.14 2 9.27l6.91-1.01L12 2z" strokeLinecap="round" strokeLinejoin="round" />
                            </svg>
                        </button>

                        <button
                            onClick={onToggleStrategyDock}
                            className={cn(
                                'h-7 px-2.5 rounded-md border text-xs font-semibold',
                                'inline-flex items-center justify-center gap-1.5',
                                'transition-colors duration-150 flex-shrink-0',
                                strategyDockOpen
                                    ? 'bg-primary-600/20 border-primary-500/40 text-primary-600'
                                    : 'bg-surface-800/80 border-edge/20 text-gray-400 hover:text-gray-700 hover:border-edge/40'
                            )}
                            title="Toggle Strategy Dock"
                        >
                            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <path d="M12 20V10M18 20V4M6 20v-4" strokeLinecap="round" strokeLinejoin="round" />
                            </svg>
                            <span className="hidden md:inline">Strategies</span>
                        </button>

                        {/* Alpha Auto Quick View */}
                        <div className="relative" ref={zlRef}>
                            <button
                                onClick={() => setZlPopup(v => !v)}
                                className={cn(
                                    'h-7 px-2.5 rounded-md border text-[11px] font-bold',
                                    'inline-flex items-center justify-center gap-1.5',
                                    'transition-colors duration-150 flex-shrink-0',
                                    zlEnabled
                                        ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-500'
                                        : 'bg-surface-800/80 border-edge/20 text-gray-500 hover:text-heading hover:border-edge/40'
                                )}
                                title="Alpha Auto Status"
                            >
                                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                                </svg>
                                <span>ZL</span>
                                {zlEnabled && zlPosCount > 0 && (
                                    <span className="px-1 py-0 rounded-full bg-emerald-500/20 text-[9px]">{zlPosCount}</span>
                                )}
                            </button>

                            {zlPopup && (
                                <div className="absolute top-full right-0 mt-1.5 z-50 w-[320px] rounded-xl border border-edge/10 bg-surface-900/98 backdrop-blur-xl shadow-xl shadow-black/40 p-3 space-y-2.5">
                                    {/* Header */}
                                    <div className="flex items-center justify-between">
                                        <span className="text-xs font-semibold text-heading flex items-center gap-1.5">
                                            <svg className="w-3.5 h-3.5 text-emerald-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                                            </svg>
                                            Alpha Auto
                                        </span>
                                        <span className={cn(
                                            'px-2 py-0.5 rounded-full text-[9px] font-bold',
                                            zlEnabled ? 'bg-emerald-500/15 text-emerald-500' : 'bg-gray-500/10 text-gray-500'
                                        )}>
                                            {zlEnabled ? 'LIVE' : 'OFF'}
                                        </span>
                                    </div>

                                    {/* Quick Stats */}
                                    <div className="grid grid-cols-4 gap-1.5">
                                        {[
                                            { l: 'Positions', v: zlPosCount, c: zlPosCount > 0 ? 'text-blue-400' : 'text-gray-500' },
                                            { l: 'Trades', v: zlStats?.today_trades ?? 0 },
                                            { l: 'Wins', v: zlStats?.today_profit ?? 0, c: 'text-emerald-500' },
                                            { l: 'P&L', v: `₹${(zlStats?.today_pnl ?? 0).toFixed(0)}`, c: (zlStats?.today_pnl ?? 0) >= 0 ? 'text-emerald-500' : 'text-red-500' },
                                        ].map((s, i) => (
                                            <div key={i} className="text-center p-1.5 rounded-lg bg-surface-800/60">
                                                <div className="text-[8px] text-gray-600 uppercase">{s.l}</div>
                                                <div className={cn('text-xs font-semibold font-price tabular-nums', s.c || 'text-heading')}>{s.v}</div>
                                            </div>
                                        ))}
                                    </div>

                                    {/* Active Positions Mini List */}
                                    {zlPosCount > 0 && (
                                        <div className="space-y-1">
                                            <div className="text-[9px] text-gray-600 uppercase font-semibold">Active Positions</div>
                                            {Object.entries(zlPositions).slice(0, 5).map(([sym, pos]) => (
                                                <div key={sym} className="flex items-center justify-between px-2 py-1 rounded-md bg-surface-800/40 text-[10px]">
                                                    <span className="font-semibold text-heading">{cleanSymbol(sym)}</span>
                                                    <span className={cn(
                                                        'px-1.5 py-0.5 rounded-full text-[9px] font-bold',
                                                        pos.direction === 'LONG' ? 'bg-emerald-500/15 text-emerald-500' : 'bg-red-500/15 text-red-500'
                                                    )}>
                                                        {pos.direction}
                                                    </span>
                                                    <span className="text-gray-400 font-price tabular-nums">@ {pos.entry_price?.toFixed(2)}</span>
                                                </div>
                                            ))}
                                            {zlPosCount > 5 && (
                                                <div className="text-[9px] text-gray-500 text-center">+{zlPosCount - 5} more</div>
                                            )}
                                        </div>
                                    )}

                                    {/* Recent Activity */}
                                    {zlLog.length > 0 && (
                                        <div className="space-y-0.5">
                                            <div className="text-[9px] text-gray-600 uppercase font-semibold">Recent Activity</div>
                                            {zlLog.filter(l => l.type !== 'scan').slice(0, 4).map((entry, i) => (
                                                <div key={i} className="text-[10px] text-gray-400 px-1 py-0.5 truncate">
                                                    <span className={cn(
                                                        'font-semibold mr-1',
                                                        entry.type === 'entry' ? 'text-blue-400' :
                                                            entry.type === 'profit' ? 'text-emerald-500' : 'text-amber-500'
                                                    )}>
                                                        {entry.type === 'entry' ? '→' : entry.type === 'profit' ? '✓' : '○'}
                                                    </span>
                                                    {entry.message}
                                                </div>
                                            ))}
                                        </div>
                                    )}

                                    {/* Open Full Page */}
                                    <button
                                        onClick={() => { setZlPopup(false); navigate('/auto-alpha'); }}
                                        className="w-full text-center py-1.5 rounded-lg bg-primary-600/15 border border-primary-500/20 text-primary-600 text-[11px] font-semibold hover:bg-primary-600/25 transition-colors"
                                    >
                                        Open Alpha Auto Dashboard →
                                    </button>
                                </div>
                            )}
                        </div>

                        <button
                            onClick={onToggleOrderPanel}
                            className={cn(
                                'h-7 px-2.5 rounded-md border text-[11px] font-semibold',
                                'inline-flex items-center justify-center gap-1.5',
                                'transition-colors duration-150 flex-shrink-0',
                                orderPanelVisible
                                    ? 'bg-primary-600/20 border-primary-500/40 text-primary-600'
                                    : 'bg-surface-800/80 border-edge/20 text-gray-500 hover:text-heading hover:border-edge/40'
                            )}
                            title={orderPanelVisible ? 'Hide order panel' : 'Show order panel'}
                        >
                            Order Panel
                        </button>

                        {/* Kill Switch — visible when positions exist */}
                        {hasPositions && (
                            <button
                                onClick={handleKillSwitch}
                                disabled={killSwitchBusy}
                                className={cn(
                                    'h-7 px-2.5 rounded-md border text-[11px] font-bold',
                                    'inline-flex items-center justify-center gap-1.5',
                                    'transition-colors duration-150 flex-shrink-0',
                                    'bg-red-500/15 border-red-500/30 text-red-500 hover:bg-red-500/25 hover:border-red-500/50',
                                    killSwitchBusy && 'opacity-50 cursor-not-allowed'
                                )}
                                title="Kill Switch — Close all positions immediately"
                            >
                                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                                    <circle cx="12" cy="12" r="10" />
                                    <path d="M12 2v4M12 6v6" />
                                </svg>
                                <span>{killSwitchBusy ? 'CLOSING...' : 'KILL'}</span>
                            </button>
                        )}

                    </>
                )}
            </div>

        </div>
    );
}

export default memo(ChartHeader);
