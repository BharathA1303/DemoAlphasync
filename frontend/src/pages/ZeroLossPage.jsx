import { useState, useEffect, useMemo, useRef } from 'react';
import toast from 'react-hot-toast';
import { cn } from '../utils/cn';
import { pnlColorClass, formatPrice, formatPercent, cleanSymbol, formatCurrency } from '../utils/formatters';
import { useZeroLossStore } from '../stores/useZeroLossStore';
import { useMarketSession } from '../hooks/useMarketSession';
import {
    ShieldCheck, Play, Pause, Zap, TrendingUp, TrendingDown,
    Activity, Target, AlertTriangle, Clock, BarChart3, Eye, Compass,
} from 'lucide-react';

// ── Confidence Gauge ──────────────────────────────────────────────────────────

function ConfidenceGauge({ score, size = 120 }) {
    const radius = (size - 16) / 2;
    const circumference = Math.PI * radius;
    const progress = Math.min(Math.max(score, 0), 100);
    const offset = circumference - (progress / 100) * circumference;

    const color =
        progress >= 60 ? '#22c55e' :
            progress >= 45 ? '#00bcd4' :
                progress >= 25 ? '#f97316' : '#ef4444';

    return (
        <div className="flex flex-col items-center">
            <svg width={size} height={size / 2 + 16} viewBox={`0 0 ${size} ${size / 2 + 16}`}>
                <path
                    d={`M 8,${size / 2 + 8} A ${radius},${radius} 0 0 1 ${size - 8},${size / 2 + 8}`}
                    fill="none" stroke="rgb(var(--c-edge) / 0.1)" strokeWidth="6" strokeLinecap="round"
                />
                <path
                    d={`M 8,${size / 2 + 8} A ${radius},${radius} 0 0 1 ${size - 8},${size / 2 + 8}`}
                    fill="none" stroke={color} strokeWidth="6" strokeLinecap="round"
                    strokeDasharray={circumference} strokeDashoffset={offset}
                    className="transition-all duration-700 ease-out"
                />
                <text x={size / 2} y={size / 2 - 2} textAnchor="middle"
                    className="fill-heading" style={{ fontSize: '22px', fontFamily: 'JetBrains Mono, monospace', fontWeight: 600 }}>
                    {Math.round(progress)}
                </text>
                <text x={size / 2} y={size / 2 + 12} textAnchor="middle"
                    className="fill-gray-500" style={{ fontSize: '8px', letterSpacing: '0.5px' }}>
                    CONFIDENCE
                </text>
            </svg>
        </div>
    );
}

// ── Direction Badge ───────────────────────────────────────────────────────────

function DirectionBadge({ direction, small = false }) {
    const config = {
        LONG: { icon: <TrendingUp className={small ? 'w-3 h-3' : 'w-3.5 h-3.5'} />, cls: 'text-emerald-500 bg-emerald-500/15 border-emerald-500/20' },
        SHORT: { icon: <TrendingDown className={small ? 'w-3 h-3' : 'w-3.5 h-3.5'} />, cls: 'text-red-500 bg-red-500/15 border-red-500/20' },
        NO_TRADE: { icon: null, cls: 'text-gray-400 bg-gray-500/10 border-gray-500/10' },
        BULLISH: { icon: <TrendingUp className={small ? 'w-3 h-3' : 'w-3.5 h-3.5'} />, cls: 'text-emerald-500 bg-emerald-500/15 border-emerald-500/20' },
        BEARISH: { icon: <TrendingDown className={small ? 'w-3 h-3' : 'w-3.5 h-3.5'} />, cls: 'text-red-500 bg-red-500/15 border-red-500/20' },
        NEUTRAL: { icon: <Compass className={small ? 'w-3 h-3' : 'w-3.5 h-3.5'} />, cls: 'text-gray-400 bg-gray-500/10 border-gray-500/10' },
    };
    const c = config[direction] || config.NEUTRAL;
    return (
        <span className={cn('inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[10px] font-semibold', c.cls)}>
            {c.icon} {direction}
        </span>
    );
}

// ── Status Badge ──────────────────────────────────────────────────────────────

function StatusBadge({ status }) {
    const colors = {
        WAITING: 'text-gray-400 bg-gray-500/10',
        ACTIVE: 'text-blue-400 bg-blue-500/15 animate-pulse',
        PROFIT: 'text-emerald-600 bg-emerald-500/15',
        BREAKEVEN: 'text-primary-600 bg-primary-500/10',
        STOPLOSS: 'text-red-400 bg-red-500/15',
    };
    return (
        <span className={cn('px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide', colors[status] || colors.WAITING)}>
            {status}
        </span>
    );
}

// ── Market Regime Badge ──────────────────────────────────────────────────────

function RegimeBadge({ regime }) {
    const config = {
        BULLISH: { label: 'Nifty Bullish', cls: 'text-emerald-500 bg-emerald-500/10 border-emerald-500/20', icon: <TrendingUp className="w-3 h-3" /> },
        BEARISH: { label: 'Nifty Bearish', cls: 'text-red-500 bg-red-500/10 border-red-500/20', icon: <TrendingDown className="w-3 h-3" /> },
        NEUTRAL: { label: 'Nifty Neutral', cls: 'text-gray-400 bg-gray-500/10 border-gray-500/20', icon: <Compass className="w-3 h-3" /> },
    };
    const c = config[regime] || config.NEUTRAL;
    return (
        <span className={cn('inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[10px] font-semibold', c.cls)}>
            {c.icon} {c.label}
        </span>
    );
}

// ── Breakdown Bar ─────────────────────────────────────────────────────────────

function BreakdownItem({ label, score, max, color }) {
    const pct = max > 0 ? (score / max) * 100 : 0;
    return (
        <div className="space-y-0.5">
            <div className="flex justify-between text-[10px]">
                <span className="text-gray-500">{label}</span>
                <span className="text-heading font-price tabular-nums">{score}/{max}</span>
            </div>
            <div className="h-1 bg-surface-800 rounded-full overflow-hidden">
                <div className="h-full rounded-full transition-all duration-500"
                    style={{ width: `${pct}%`, backgroundColor: color }} />
            </div>
        </div>
    );
}

// ── Live Activity Log Entry ──────────────────────────────────────────────────

function LogEntry({ entry }) {
    const typeConfig = {
        entry: { icon: <Zap className="w-3 h-3" />, color: 'text-blue-400', bg: 'bg-blue-500/10' },
        profit: { icon: <TrendingUp className="w-3 h-3" />, color: 'text-emerald-500', bg: 'bg-emerald-500/10' },
        stoploss: { icon: <AlertTriangle className="w-3 h-3" />, color: 'text-red-400', bg: 'bg-red-500/10' },
        breakeven: { icon: <ShieldCheck className="w-3 h-3" />, color: 'text-amber-500', bg: 'bg-amber-500/10' },
        scan: { icon: <Eye className="w-3 h-3" />, color: 'text-gray-400', bg: 'bg-gray-500/5' },
    };
    const c = typeConfig[entry.type] || typeConfig.scan;
    const timeStr = new Date(entry.ts).toLocaleTimeString('en-IN', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });

    return (
        <div className={cn('flex items-start gap-2 px-3 py-1.5 text-[11px] border-b border-edge/[0.03]', entry.type !== 'scan' && 'bg-surface-800/30')}>
            <div className={cn('mt-0.5 p-0.5 rounded', c.bg)}>
                <span className={c.color}>{c.icon}</span>
            </div>
            <div className="flex-1 min-w-0">
                <span className={cn('font-medium', c.color)}>{entry.message}</span>
            </div>
            <span className="text-[9px] text-gray-600 font-price tabular-nums flex-shrink-0">{timeStr}</span>
        </div>
    );
}

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN PAGE COMPONENT
// ═══════════════════════════════════════════════════════════════════════════════

export default function ZeroLossPage() {
    const {
        enabled, confidence, activePositions, stats,
        signals, trades, performance, loading, fetchAll, toggle, lastUpdate, liveLog,
    } = useZeroLossStore();
    const { marketOpen, marketStateLabel } = useMarketSession();

    const [toggling, setToggling] = useState(false);
    const autoStopRef = useRef(false);
    const [showLog, setShowLog] = useState(true);
    const [nowMs, setNowMs] = useState(Date.now());
    const logRef = useRef(null);

    useEffect(() => { fetchAll(); }, [fetchAll]);

    useEffect(() => {
        const id = setInterval(fetchAll, 15_000);
        return () => clearInterval(id);
    }, [fetchAll]);

    useEffect(() => {
        const id = setInterval(() => setNowMs(Date.now()), 1_000);
        return () => clearInterval(id);
    }, []);

    useEffect(() => {
        if (marketOpen) {
            autoStopRef.current = false;
            return;
        }
        if (!enabled || autoStopRef.current) return;
        autoStopRef.current = true;
        toggle()
            .then((res) => {
                toast.error(res?.message || `Market closed (${marketStateLabel}) — Alpha Auto stopped.`);
            })
            .catch(() => {
                autoStopRef.current = false;
            });
    }, [marketOpen, enabled, marketStateLabel, toggle]);

    const handleToggle = async () => {
        if (!enabled && !marketOpen) {
            toast.error(`Cannot start — ${marketStateLabel || 'market is closed'}.`);
            return;
        }
        setToggling(true);
        try {
            const res = await toggle();
            toast.success(res.message);
        } catch (err) {
            const detail = err?.response?.data?.detail;
            const message = typeof detail === 'string'
                ? detail
                : detail?.message || 'Failed to toggle strategy';
            toast.error(message);
        } finally {
            setToggling(false);
        }
    };

    const positions = activePositions ?? {};
    const positionCount = Object.keys(positions).length;
    const perfSummary = performance?.summary ?? {};
    const symbolEntries = useMemo(() => Object.entries(confidence), [confidence]);
    const marketRegime = stats.market_regime || 'NEUTRAL';
    const confidenceThreshold = Number(stats.confidence_threshold ?? 55);

    const filteredLog = useMemo(() =>
        showLog ? liveLog : liveLog.filter(l => l.type !== 'scan'),
        [liveLog, showLog]
    );

    const lastUpdateStr = lastUpdate
        ? new Date(lastUpdate).toLocaleTimeString('en-IN', { hour12: false })
        : null;
    const liveClockStr = new Date(nowMs).toLocaleTimeString('en-IN', {
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
    });

    if (loading) {
        return (
            <div className="min-h-[calc(100vh-56px)] bg-surface-950 flex items-center justify-center">
                <div className="w-8 h-8 border-2 border-primary-500 border-t-transparent rounded-full animate-spin" />
            </div>
        );
    }

    return (
        <div className="min-h-[calc(100vh-56px)] bg-surface-950 p-4 md:p-5 space-y-4 overflow-y-auto">
            {/* ── Header ──────────────────────────────────────────────── */}
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                    <div className={cn('p-2.5 rounded-xl border', enabled ? 'bg-emerald-500/10 border-emerald-500/20' : 'bg-gray-500/10 border-gray-500/20')}>
                        <ShieldCheck className={cn('w-6 h-6', enabled ? 'text-emerald-500' : 'text-gray-500')} />
                    </div>
                    <div>
                        <h1 className="text-lg font-display font-semibold text-heading flex items-center gap-2">
                            Alpha Auto Engine
                            {enabled && marketOpen && (
                                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-500/15 border border-emerald-500/25 text-[10px] font-bold text-emerald-500 animate-pulse">
                                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" /> LIVE
                                </span>
                            )}
                            {enabled && !marketOpen && (
                                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-500/15 border border-amber-500/25 text-[10px] font-bold text-amber-600">
                                    STOPPING
                                </span>
                            )}
                        </h1>
                    </div>
                </div>

                <div className="flex items-center gap-2">
                    <span
                        className="text-[10px] text-gray-600 font-price tabular-nums flex items-center gap-1"
                        title={lastUpdateStr ? `Last sync ${lastUpdateStr}` : undefined}
                    >
                        <Clock className="w-3 h-3" /> {liveClockStr}
                    </span>
                    <button
                        onClick={handleToggle}
                        disabled={toggling || (!enabled && !marketOpen)}
                        title={!marketOpen && !enabled ? `${marketStateLabel || 'Market closed'} — start disabled` : undefined}
                        className={cn(
                            'flex items-center gap-2 px-4 py-2 rounded-xl border font-semibold text-sm transition-all duration-200 shadow-lg',
                            enabled
                                ? 'bg-red-500/15 border-red-500/30 text-red-500 hover:bg-red-500/25 shadow-red-500/5'
                                : marketOpen
                                    ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-600 hover:bg-emerald-500/25 shadow-emerald-500/5'
                                    : 'bg-gray-500/10 border-gray-500/20 text-gray-500 cursor-not-allowed opacity-60'
                        )}
                    >
                        {enabled ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
                        {toggling ? 'Switching...' : enabled ? 'Stop Strategy' : 'Start Strategy'}
                    </button>
                </div>
            </div>

            {/* ── Stats Cards ─────────────────────────────────────────── */}
            <div className="grid grid-cols-3 md:grid-cols-7 gap-2">
                {[
                    {
                        label: 'Status',
                        value: enabled ? (marketOpen ? 'LIVE' : 'PAUSED') : 'OFF',
                        color: enabled ? (marketOpen ? 'text-emerald-500' : 'text-amber-500') : 'text-gray-500',
                        icon: <Activity className="w-3.5 h-3.5" />,
                    },
                    { label: 'Market', value: marketRegime, color: marketRegime === 'BULLISH' ? 'text-emerald-500' : marketRegime === 'BEARISH' ? 'text-red-400' : 'text-gray-400', icon: <Compass className="w-3.5 h-3.5" /> },
                    { label: 'Positions', value: `${positionCount}/5`, color: positionCount > 0 ? 'text-blue-400' : 'text-gray-500', icon: <Target className="w-3.5 h-3.5" /> },
                    { label: 'Total Trades', value: stats.today_trades ?? 0, icon: <BarChart3 className="w-3.5 h-3.5" /> },
                    { label: 'Wins', value: stats.today_profit ?? 0, color: 'text-emerald-500', icon: <TrendingUp className="w-3.5 h-3.5" /> },
                    { label: 'Losses', value: stats.today_losses ?? stats.today_breakeven ?? 0, color: 'text-red-400', icon: <AlertTriangle className="w-3.5 h-3.5" /> },
                    { label: "Today P&L", value: `₹${formatPrice(stats.today_pnl ?? 0)}`, color: pnlColorClass(stats.today_pnl ?? 0), icon: <Zap className="w-3.5 h-3.5" /> },
                ].map((card, i) => (
                    <div key={i} className="kpi-card p-3 space-y-1">
                        <div className="metric-label flex items-center gap-1">{card.icon} {card.label}</div>
                        <div className={cn('text-base font-semibold font-price tabular-nums', card.color || 'text-heading')}>
                            {card.value}
                        </div>
                    </div>
                ))}
            </div>

            {/* ── Main Grid: Live Activity + Active Positions ──────────── */}
            <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">

                {/* ── Left: Live Activity Feed ──────────── */}
                <div className="lg:col-span-2 rounded-xl border border-edge/5 bg-surface-900/60 flex flex-col" style={{ maxHeight: '420px' }}>
                    <div className="flex items-center justify-between px-4 py-2.5 border-b border-edge/5">
                        <h3 className="section-title text-xs flex items-center gap-1.5">
                            <Activity className="w-3.5 h-3.5 text-blue-400" />
                            Live Activity
                            {liveLog.length > 0 && (
                                <span className="ml-1 px-1.5 py-0.5 rounded-full bg-blue-500/15 text-blue-400 text-[9px] font-bold">{liveLog.length}</span>
                            )}
                        </h3>
                        <button onClick={() => setShowLog(v => !v)}
                            className="text-[10px] text-gray-500 hover:text-heading transition-colors">
                            {showLog ? 'Hide scans' : 'Show all'}
                        </button>
                    </div>

                    <div ref={logRef} className="flex-1 overflow-y-auto min-h-0">
                        {filteredLog.length === 0 ? (
                            <div className="text-center text-gray-600 py-12 text-xs">
                                {enabled ? 'Waiting for activity...' : 'Start the strategy to see live activity'}
                            </div>
                        ) : (
                            filteredLog.map((entry, i) => <LogEntry key={i} entry={entry} />)
                        )}
                    </div>
                </div>

                {/* ── Right: Active Positions ──────────── */}
                <div className="lg:col-span-3 rounded-xl border border-edge/5 bg-surface-900/60 flex flex-col" style={{ maxHeight: '420px' }}>
                    <div className="flex items-center justify-between px-4 py-2.5 border-b border-edge/5">
                        <h3 className="section-title text-xs flex items-center gap-1.5">
                            <Target className="w-3.5 h-3.5 text-emerald-500" />
                            Active Positions
                            {positionCount > 0 && (
                                <span className="ml-1 px-1.5 py-0.5 rounded-full bg-emerald-500/15 text-emerald-500 text-[9px] font-bold">{positionCount}/5</span>
                            )}
                        </h3>
                    </div>

                    <div className="flex-1 overflow-y-auto min-h-0 p-3">
                        {positionCount === 0 ? (
                            <div className="text-center text-gray-600 py-12 text-xs">
                                {enabled
                                    ? marketRegime === 'NEUTRAL'
                                        ? 'Waiting for clear market direction...'
                                        : 'Scanning for high-conviction entries...'
                                    : 'No active positions'}
                            </div>
                        ) : (
                            <div className="space-y-2">
                                {Object.entries(positions).map(([symbol, pos]) => (
                                    <div key={symbol} className="rounded-lg border border-edge/10 bg-surface-800/40 p-3">
                                        <div className="flex items-center justify-between mb-2">
                                            <div className="flex items-center gap-2">
                                                <span className="text-sm font-semibold text-heading">{cleanSymbol(symbol)}</span>
                                                <DirectionBadge direction={pos.direction} small />
                                            </div>
                                            <StatusBadge status={pos.status} />
                                        </div>

                                        <div className="grid grid-cols-4 gap-3 text-[11px]">
                                            <div>
                                                <span className="metric-label block mb-0.5">Entry</span>
                                                <span className="text-heading font-price tabular-nums font-medium">{formatPrice(pos.entry_price)}</span>
                                            </div>
                                            <div>
                                                <span className="metric-label block mb-0.5">Stop Loss</span>
                                                <span className="text-amber-500 font-price tabular-nums font-medium">{formatPrice(pos.stop_loss)}</span>
                                            </div>
                                            <div>
                                                <span className="metric-label block mb-0.5">Target</span>
                                                <span className="text-emerald-500 font-price tabular-nums font-medium">{formatPrice(pos.target)}</span>
                                            </div>
                                            <div>
                                                <span className="metric-label block mb-0.5">Confidence</span>
                                                <span className="text-blue-400 font-price tabular-nums font-medium">{pos.confidence_score?.toFixed(0)}%</span>
                                            </div>
                                        </div>

                                        {pos.entry_price && pos.target && pos.stop_loss && (
                                            <div className="mt-2">
                                                <div className="h-1.5 bg-surface-800 rounded-full overflow-hidden relative">
                                                    <div className="absolute inset-y-0 left-0 bg-emerald-500/40 rounded-full transition-all duration-500"
                                                        style={{ width: '50%' }} />
                                                </div>
                                                <div className="flex justify-between text-[9px] text-gray-500 mt-0.5">
                                                    <span>SL: {formatPrice(pos.stop_loss)}</span>
                                                    <span>RR 1:{pos.risk_reward_ratio?.toFixed(1)}</span>
                                                    <span>T: {formatPrice(pos.target)}</span>
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            </div>

            {/* ── Confidence Grid ───────────────────────────────────────── */}
            <div className="rounded-xl border border-edge/5 bg-surface-900/60 p-4">
                <h3 className="section-title text-xs mb-3 flex items-center gap-1.5">
                    <Eye className="w-3.5 h-3.5 text-blue-400" />
                    Live Confidence Scanner
                    <span className="text-gray-600 font-normal ml-1">({symbolEntries.length} symbols)</span>
                    <span className="ml-2 text-[9px] text-gray-500">
                        Threshold {Math.round(confidenceThreshold)}%
                    </span>
                    {marketRegime !== 'NEUTRAL' && (
                        <span className="ml-2 text-[9px] text-gray-500">
                            Only {marketRegime === 'BULLISH' ? 'LONG' : 'SHORT'} trades allowed
                        </span>
                    )}
                    {marketRegime === 'NEUTRAL' && (
                        <span className="ml-2 text-[9px] text-gray-500">
                            Waiting for clear direction
                        </span>
                    )}
                </h3>

                {symbolEntries.length === 0 ? (
                    <div className="text-center text-gray-600 py-6 text-xs">
                        {enabled ? 'Scanning markets...' : 'Start the strategy to see confidence scores'}
                    </div>
                ) : (
                    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
                        {symbolEntries.map(([symbol, data]) => {
                            const isActive = symbol in positions;
                            const wouldAlign = (
                                (data.direction === 'BULLISH' && marketRegime === 'BULLISH') ||
                                (data.direction === 'BEARISH' && marketRegime === 'BEARISH')
                            );
                            const passesThreshold = data.score >= confidenceThreshold;
                            const tradeable = passesThreshold && wouldAlign;
                            const blockedLabel = marketRegime === 'NEUTRAL'
                                ? 'BLOCKED (neutral)'
                                : 'BLOCKED (regime)';

                            return (
                                <div key={symbol} className={cn(
                                    'rounded-lg border p-3 space-y-2 transition-all',
                                    isActive
                                        ? 'border-emerald-500/30 bg-emerald-500/5'
                                        : 'border-edge/10 bg-surface-800/40'
                                )}>
                                    <div className="flex items-center justify-between">
                                        <span className="text-xs font-semibold text-heading">{cleanSymbol(symbol)}</span>
                                        <DirectionBadge direction={data.direction} small />
                                    </div>

                                    <ConfidenceGauge score={data.score} size={100} />

                                    {data.breakdown && (
                                        <div className="space-y-1">
                                            <BreakdownItem label="EMA" score={data.breakdown.ema} max={20} color="#3b82f6" />
                                            <BreakdownItem label="RSI" score={data.breakdown.rsi} max={15} color="#8b5cf6" />
                                            <BreakdownItem label="MACD" score={data.breakdown.macd} max={15} color="#f59e0b" />
                                            <BreakdownItem label="Volume" score={data.breakdown.volume} max={15} color="#f59e0b" />
                                            <BreakdownItem label="VIX" score={data.breakdown.volatility} max={10} color="#10b981" />
                                            <BreakdownItem label="S/R" score={data.breakdown.support_resistance} max={10} color="#ec4899" />
                                            <BreakdownItem label="VWAP" score={data.breakdown.vwap || 0} max={10} color="#06b6d4" />
                                            <BreakdownItem label="Trend" score={data.breakdown.trend_strength || 0} max={5} color="#14b8a6" />
                                        </div>
                                    )}

                                    <div className="flex items-center justify-between text-[9px]">
                                        <span className={cn('font-semibold',
                                            tradeable ? 'text-emerald-500' :
                                                passesThreshold && !wouldAlign ? 'text-amber-500' :
                                                    'text-gray-500'
                                        )}>
                                            {tradeable ? 'READY TO TRADE' :
                                                passesThreshold && !wouldAlign ? blockedLabel :
                                                    `BELOW ${Math.round(confidenceThreshold)}%`}
                                        </span>
                                        {isActive && <span className="text-emerald-500 font-bold animate-pulse">IN TRADE</span>}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>

            {/* ── Performance + Signal History ─────────────────────────── */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {perfSummary && (
                    <div className="rounded-xl border border-edge/5 bg-surface-900/60 p-4">
                        <h3 className="section-title text-xs mb-3 flex items-center gap-1.5">
                            <BarChart3 className="w-3.5 h-3.5 text-emerald-500" /> 30-Day Performance
                        </h3>
                        <div className="grid grid-cols-3 gap-2">
                            {[
                                { label: 'Total', value: perfSummary.total_trades ?? 0 },
                                { label: 'Profit', value: perfSummary.profit_trades ?? 0, color: 'text-emerald-500' },
                                { label: 'Breakeven', value: perfSummary.breakeven_trades ?? 0, color: 'text-amber-500' },
                                { label: 'Losses', value: perfSummary.loss_trades ?? 0, color: 'text-red-400' },
                                { label: 'Win Rate', value: `${perfSummary.win_rate ?? 0}%`, color: 'text-blue-400' },
                                { label: 'Net P&L', value: `₹${formatPrice(perfSummary.net_pnl ?? 0)}`, color: pnlColorClass(perfSummary.net_pnl ?? 0) },
                            ].map((item, i) => (
                                <div key={i} className="text-center p-2 rounded-lg bg-surface-800/40 border border-edge/5">
                                    <div className="metric-label mb-0.5 text-[9px]">{item.label}</div>
                                    <div className={cn('text-sm font-semibold font-price tabular-nums', item.color || 'text-heading')}>
                                        {item.value}
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                <div className="rounded-xl border border-edge/5 bg-surface-900/60 p-4">
                    <h3 className="section-title text-xs mb-3 flex items-center gap-1.5">
                        <Clock className="w-3.5 h-3.5 text-gray-400" /> Recent Signals
                    </h3>

                    {signals.length === 0 ? (
                        <div className="text-center text-gray-600 py-6 text-xs">No signals yet</div>
                    ) : (
                        <div className="overflow-x-auto max-h-[250px] overflow-y-auto">
                            <table className="w-full text-[11px]">
                                <thead className="sticky top-0 bg-surface-900">
                                    <tr className="border-b border-edge/5">
                                        <th className="text-left py-1.5 px-2 metric-label">Time</th>
                                        <th className="text-left py-1.5 px-2 metric-label">Symbol</th>
                                        <th className="text-left py-1.5 px-2 metric-label">Dir</th>
                                        <th className="text-right py-1.5 px-2 metric-label">Score</th>
                                        <th className="text-right py-1.5 px-2 metric-label">Entry</th>
                                        <th className="text-center py-1.5 px-2 metric-label">Status</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {signals.slice(0, 20).map((sig, i) => (
                                        <tr key={i} className="border-b border-edge/[0.03] hover:bg-overlay/5 transition-colors">
                                            <td className="py-1.5 px-2 text-gray-500 font-price tabular-nums">
                                                {sig.timestamp ? new Date(sig.timestamp).toLocaleTimeString('en-IN', { hour12: false, hour: '2-digit', minute: '2-digit' }) : '-'}
                                            </td>
                                            <td className="py-1.5 px-2 font-semibold text-heading">{sig.symbol ? cleanSymbol(sig.symbol) : '-'}</td>
                                            <td className="py-1.5 px-2"><DirectionBadge direction={sig.direction} small /></td>
                                            <td className="py-1.5 px-2 text-right font-price tabular-nums text-heading">{sig.confidence_score?.toFixed(0)}</td>
                                            <td className="py-1.5 px-2 text-right font-price tabular-nums text-gray-500">{sig.entry_price ? formatPrice(sig.entry_price) : '-'}</td>
                                            <td className="py-1.5 px-2 text-center"><StatusBadge status={sig.status} /></td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            </div>

            {/* ── Alpha Auto History ────────────────────────────── */}
            <div className="rounded-xl border border-edge/5 bg-surface-900/60 p-4">
                <h3 className="section-title text-xs mb-3 flex items-center gap-1.5">
                    <ShieldCheck className="w-3.5 h-3.5 text-emerald-500" />
                    Alpha Auto Trades
                    {trades.length > 0 && (
                        <span className="ml-1 px-1.5 py-0.5 rounded-full bg-emerald-500/15 text-emerald-500 text-[9px] font-bold">{trades.length}</span>
                    )}
                </h3>

                {trades.length === 0 ? (
                    <div className="text-center text-gray-600 py-8 text-xs">
                        {enabled ? 'No Alpha Auto trades executed yet — waiting for high-conviction setups...' : 'Start the strategy to begin automated trading'}
                    </div>
                ) : (
                    <div className="overflow-x-auto max-h-[350px] overflow-y-auto">
                        <table className="w-full text-[11px]">
                            <thead className="sticky top-0 bg-surface-900">
                                <tr className="border-b border-edge/5">
                                    <th className="text-left py-1.5 px-2 metric-label">Time</th>
                                    <th className="text-left py-1.5 px-2 metric-label">Symbol</th>
                                    <th className="text-left py-1.5 px-2 metric-label">Side</th>
                                    <th className="text-right py-1.5 px-2 metric-label">Qty</th>
                                    <th className="text-right py-1.5 px-2 metric-label">Price</th>
                                    <th className="text-right py-1.5 px-2 metric-label">Value</th>
                                    <th className="text-center py-1.5 px-2 metric-label">Status</th>
                                </tr>
                            </thead>
                            <tbody>
                                {trades.map((t, i) => {
                                    const ts = t.executed_at || t.created_at;
                                    const raw = typeof ts === 'string' && !ts.endsWith('Z') && !ts.includes('+') ? ts + 'Z' : ts;
                                    const d = ts ? new Date(raw) : null;
                                    const timeStr = d && !isNaN(d)
                                        ? d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true, timeZone: 'Asia/Kolkata' })
                                        : '—';
                                    const dateStr = d && !isNaN(d)
                                        ? d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', timeZone: 'Asia/Kolkata' })
                                        : '';
                                    const price = t.filled_price ?? t.price;
                                    const qty = t.filled_quantity ?? t.quantity;
                                    const value = price && qty ? price * qty : null;

                                    return (
                                        <tr key={i} className="border-b border-edge/[0.03] hover:bg-overlay/5 transition-colors">
                                            <td className="py-1.5 px-2 text-gray-500 font-price tabular-nums">
                                                <div>{timeStr}</div>
                                                {dateStr && <div className="text-[9px] text-gray-600">{dateStr}</div>}
                                            </td>
                                            <td className="py-1.5 px-2 font-semibold text-heading">{cleanSymbol(t.symbol)}</td>
                                            <td className="py-1.5 px-2">
                                                <span className={cn(
                                                    'text-[10px] font-semibold px-2 py-0.5 rounded',
                                                    t.side === 'BUY' ? 'bg-emerald-500/15 text-emerald-500' : 'bg-red-500/15 text-red-500'
                                                )}>
                                                    {t.side}
                                                </span>
                                            </td>
                                            <td className="py-1.5 px-2 text-right font-price tabular-nums text-heading">{qty}</td>
                                            <td className="py-1.5 px-2 text-right font-price tabular-nums text-heading">{price ? formatPrice(price) : '—'}</td>
                                            <td className="py-1.5 px-2 text-right font-price tabular-nums text-gray-400">{value ? formatCurrency(value) : '—'}</td>
                                            <td className="py-1.5 px-2 text-center">
                                                <span className={cn(
                                                    'text-[10px] px-2 py-0.5 rounded font-medium',
                                                    t.status === 'FILLED' ? 'text-emerald-500 bg-emerald-500/10' :
                                                        t.status === 'CANCELLED' ? 'text-gray-400 bg-gray-400/10' :
                                                            'text-blue-400 bg-blue-500/10'
                                                )}>
                                                    {t.status}
                                                </span>
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>

            {/* ── How It Works ────────────── */}
            <div className="rounded-xl border border-edge/5 bg-surface-900/60 p-4 text-xs text-gray-500 space-y-2">
                <h3 className="section-title text-xs mb-3">How Alpha Auto Engine Works</h3>
                <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                    {[
                        { step: '01', title: 'Market Regime', desc: 'Checks Nifty 50 trend via EMA. Only trades WITH the market — LONG in bullish, SHORT in bearish. Never fights the trend.', color: 'text-blue-400 border-blue-500/20 bg-blue-500/5' },
                        { step: '02', title: 'Smart Filters', desc: 'Confidence >= 58%, MACD alignment, VWAP confirmation, and volume checks. In simulation + neutral regime, high-confidence fallback entries are allowed to avoid dead zones. No entry in first 15min, lunch hour, or after 2:45PM. Max 5 positions.', color: 'text-purple-400 border-purple-500/20 bg-purple-500/5' },
                        { step: '03', title: 'Profit Locking', desc: 'SL starts at 2%. At +0.9% profit, SL moves to entry (breakeven). At +1.5%, locks 0.7% profit. At +1.9%, trailing mode activates to protect gains.', color: 'text-amber-400 border-amber-500/20 bg-amber-500/5' },
                        { step: '04', title: 'Smart Exits', desc: 'Target at 3.2% with momentum reversal exits if MACD flips. 10-min cooldown per symbol. All positions force-closed at 3:20 PM.', color: 'text-emerald-500 border-emerald-500/20 bg-emerald-500/5' },
                    ].map(s => (
                        <div key={s.step} className={cn('rounded-lg border p-3 space-y-1', s.color)}>
                            <div className="flex items-center gap-2">
                                <span className="font-price text-base font-semibold opacity-40">{s.step}</span>
                                <span className="text-[11px] font-semibold">{s.title}</span>
                            </div>
                            <p className="text-gray-500 text-[10px] leading-relaxed">{s.desc}</p>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}
