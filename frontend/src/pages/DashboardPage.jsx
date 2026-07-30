import { useState, useEffect, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { useAuthStore } from '../stores/useAuthStore';
import { usePortfolioStore } from '../store/usePortfolioStore';
import { useMarketStore } from '../store/useMarketStore';
import api from '../services/api';
import {
    TrendingUp, TrendingDown, IndianRupee,
    BarChart3, ArrowRight, Zap, Briefcase,
    ShieldCheck,
} from 'lucide-react';
import { formatCurrency, formatPrice, formatPercent, pnlColorClass, cleanSymbol } from '../utils/formatters';
import { buildPortfolioMetrics } from '../utils/portfolioMetrics';
import { Skeleton } from '../components/ui';
import { cn } from '../utils/cn';
import LeaderboardButton from '../components/ui/LeaderboardButton';

/* ── Mini SVG Sparkline ──────────────────────────────────────────────────────── */
function MiniSparkline({ data = [], color = 'var(--bullish)', width = 80, height = 24 }) {
    if (!data || data.length < 2) return null;
    const min = Math.min(...data);
    const max = Math.max(...data);
    const range = max - min || 1;
    const points = data.map((v, i) => {
        const x = (i / (data.length - 1)) * width;
        const y = height - ((v - min) / range) * height;
        return `${x},${y}`;
    }).join(' ');

    return (
        <svg width={width} height={height} className="flex-shrink-0 opacity-60" aria-hidden="true">
            <polyline
                fill="none"
                stroke={color}
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                points={points}
            />
        </svg>
    );
}

export default function DashboardPage() {
    const { user } = useAuthStore();
    const [portfolio, setPortfolio] = useState(null);
    const [indices, setIndices] = useState([]);
    const [holdings, setHoldings] = useState([]);
    const [recentOrders, setRecentOrders] = useState([]);
    const [loading, setLoading] = useState(true);

    // Real-time portfolio data from store (updated by WebSocket + global polling hook)
    const storeSummary = usePortfolioStore((s) => s.summary);
    const storeHoldings = usePortfolioStore((s) => s.holdings);
    const storePnl = usePortfolioStore((s) => s.pnl);
    const liveQuotes = useMarketStore((s) => s.symbols);

    useEffect(() => {
        const load = async () => {
            try {
                const [pRes, iRes, hRes, oRes] = await Promise.allSettled([
                    api.get('/portfolio'),
                    api.get('/market/indices'),
                    api.get('/portfolio/holdings'),
                    api.get('/orders'),
                ]);
                if (pRes.status === 'fulfilled') setPortfolio(pRes.value.data);
                if (iRes.status === 'fulfilled') setIndices(iRes.value.data.indices || []);
                if (hRes.status === 'fulfilled') setHoldings(hRes.value.data.holdings || []);
                if (oRes.status === 'fulfilled') setRecentOrders((oRes.value.data.orders || []).slice(0, 5));
            } catch { /* ignore */ }
            setLoading(false);
        };
        load();
    }, []);

    const metrics = useMemo(() => buildPortfolioMetrics({
        summary: storeSummary,
        pnl: storePnl,
        holdings: storeHoldings?.length > 0 ? storeHoldings : holdings,
        liveQuotes,
        portfolio,
    }), [storeSummary, storePnl, storeHoldings, holdings, liveQuotes, portfolio]);

    if (loading) {
        return (
            <div className="p-4 lg:p-6 space-y-6">
                <Skeleton variant="text" className="h-8 w-48" />
                <div className="grid grid-cols-2 lg:grid-cols-6 gap-3">
                    {Array.from({ length: 5 }).map((_, i) => (
                        <div key={i} className={cn('kpi-card', i === 4 && 'col-span-2')}>
                            <Skeleton variant="text" className="h-3 w-20" />
                            <Skeleton variant="text" className="h-7 w-28 mt-2" />
                        </div>
                    ))}
                </div>
                <Skeleton variant="chart" className="h-40" />
                <Skeleton variant="table-row" count={4} />
            </div>
        );
    }

    const {
        totalInvested,
        currentValue,
        availableCash,
        totalCapital,
        totalPnl,
        totalPnlPct,
    } = metrics;

    return (
        <div className="p-4 lg:p-6 space-y-5 animate-fade-in">
            {/* ── Welcome Header ───────────────────────────────────────── */}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-display font-semibold text-heading">
                        Welcome, {user?.full_name?.split(' ')[0] || user?.username || 'Trader'}
                    </h1>
                </div>
                <div className="flex items-center gap-2">
                    <LeaderboardButton />
                    <Link to="/terminal" className="btn-primary text-sm hidden sm:inline-flex items-center gap-2" aria-label="Open trading terminal">
                        Trade Now <ArrowRight className="w-4 h-4" />
                    </Link>
                </div>
            </div>

            {/* ── KPI Bar — P&L card 2x wider ──────────────────────────── */}
            <div className="grid grid-cols-2 lg:grid-cols-6 gap-3">
                {/* Regular metrics */}
                {[
                    { label: 'TOTAL CAPITAL', value: formatCurrency(totalCapital), icon: IndianRupee, iconColor: 'text-primary-600' },
                    { label: 'AVAILABLE CASH', value: formatCurrency(availableCash), icon: IndianRupee, iconColor: 'text-primary-500' },
                    { label: 'INVESTED', value: formatCurrency(totalInvested), icon: BarChart3, iconColor: 'text-gray-500' },
                    { label: 'CURRENT VALUE', value: formatCurrency(currentValue), icon: TrendingUp, iconColor: 'text-bull' },
                ].map(({ label, value, icon: Icon, iconColor }) => (
                    <div key={label} className="kpi-card">
                        <div className="flex items-center justify-between">
                            <span className="metric-label">{label}</span>
                            <Icon className={cn('w-4 h-4', iconColor)} />
                        </div>
                        <span className="text-lg font-price font-semibold text-heading tabular-nums mt-1">
                            {value}
                        </span>
                    </div>
                ))}

                {/* P&L Card — 2x wide, color-coded background */}
                <div className={cn(
                    'kpi-card-highlight',
                    totalPnl >= 0
                        ? 'bg-gradient-to-br from-green-500/[0.07] to-surface-900/60 border-green-500/10'
                        : 'bg-gradient-to-br from-red-500/[0.07] to-surface-900/60 border-red-500/10'
                )}>
                    <div className="flex items-center justify-between">
                        <span className="metric-label">TOTAL P&L</span>
                        {totalPnl >= 0
                            ? <TrendingUp className="w-5 h-5 text-profit" />
                            : <TrendingDown className="w-5 h-5 text-loss" />
                        }
                    </div>
                    <div className="flex items-end gap-3 mt-1">
                        <span className={cn('text-3xl font-price font-semibold tabular-nums', pnlColorClass(totalPnl))}>
                            {totalPnl >= 0 ? '+' : ''}{formatCurrency(totalPnl)}
                        </span>
                        <span className={cn('text-sm font-price mb-1 tabular-nums', pnlColorClass(totalPnl))}>
                            {totalPnl >= 0 ? '▲' : '▼'} {formatPercent(totalPnlPct)}
                        </span>
                    </div>
                </div>
            </div>

            {/* ── Row: Market Indices Grid + Quick Actions Dock ─────────── */}
            <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
                {/* Market Indices — 2x2 grid */}
                <div className="lg:col-span-3 rounded-xl border border-edge/5 bg-surface-900/60 p-5">
                    <h2 className="section-title text-sm text-heading mb-4">Market Indices</h2>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        {indices.length > 0 ? indices.slice(0, 4).map((idx, i) => {
                            const isUp = (idx.change ?? 0) >= 0;
                            return (
                                <div key={i} className="flex items-center justify-between p-3.5 rounded-lg bg-surface-800/40 border border-edge/[0.04] hover:border-edge/10 transition-colors">
                                    <div className="flex-1 min-w-0">
                                        <div className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide">{idx.name}</div>
                                        <div className="text-xl font-price font-semibold text-heading tabular-nums mt-0.5">
                                            {Number(idx.price).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                                        </div>
                                    </div>
                                    <div className={cn('text-right flex flex-col items-end gap-0.5', pnlColorClass(idx.change))}>
                                        <div className="flex items-center gap-1 text-sm font-price font-semibold tabular-nums">
                                            {isUp ? '▲' : '▼'}
                                            {idx.change > 0 ? '+' : ''}{formatPrice(idx.change)}
                                        </div>
                                        <div className="text-xs font-price tabular-nums opacity-70">{formatPercent(idx.change_percent)}</div>
                                        <MiniSparkline
                                            data={[100, 102, 99, 101, 98, 103, 100 + (idx.change ?? 0) / 10]}
                                            color={isUp ? 'var(--bullish)' : 'var(--bearish)'}
                                            width={56}
                                            height={18}
                                        />
                                    </div>
                                </div>
                            );
                        }) : (
                            <div className="col-span-2 text-center py-8 text-gray-600">
                                <BarChart3 className="w-8 h-8 mx-auto mb-2 opacity-40" />
                                <p className="text-sm">Market data loading...</p>
                            </div>
                        )}
                    </div>
                </div>

                {/* Quick Actions — vertical dock */}
                <div className="lg:col-span-2 rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] p-5">
                    <h2 className="section-title text-sm text-heading mb-4">Quick Actions</h2>
                    <div className="space-y-2">
                        {[
                            { to: '/terminal', icon: BarChart3, label: 'Trading Terminal', desc: 'Charts & order execution', iconBg: 'bg-primary-500/10', iconColor: 'text-primary-600', border: 'border-primary-500/15  hover:border-primary-500/30' },
                            { to: '/portfolio', icon: Briefcase, label: 'Portfolio', desc: 'Holdings & P&L tracking', iconBg: 'bg-bull/10', iconColor: 'text-bull', border: 'border-bull/15         hover:border-bull/30' },
                            { to: '/algo', icon: Zap, label: 'Algo Strategies', desc: 'Automated trading bots', iconBg: 'bg-accent-purple/10', iconColor: 'text-accent-purple', border: 'border-accent-purple/15 hover:border-accent-purple/30' },
                            { to: '/auto-alpha', icon: ShieldCheck, label: 'Alpha Auto', desc: 'AI-managed high-conviction trades', iconBg: 'bg-accent-amber/10', iconColor: 'text-accent-amber', border: 'border-accent-amber/15  hover:border-accent-amber/30' },
                        ].map(({ to, icon: Icon, label, desc, iconBg, iconColor, border }) => (
                            <Link key={to} to={to} aria-label={label}
                                className={cn(
                                    'flex items-center justify-between p-3.5 rounded-lg border bg-[var(--bg-raised)] transition-all duration-150 group',
                                    border
                                )}
                            >
                                <div className="flex items-center gap-3">
                                    <div className={cn('w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0', iconBg)}>
                                        <Icon className={cn('w-4 h-4', iconColor)} />
                                    </div>
                                    <div>
                                        <span className={cn('text-sm font-semibold block', iconColor)}>{label}</span>
                                        <span className="text-[11px] text-gray-500">{desc}</span>
                                    </div>
                                </div>
                                <ArrowRight className={cn('w-4 h-4 group-hover:translate-x-0.5 transition-transform', iconColor)} />
                            </Link>
                        ))}
                    </div>
                </div>
            </div>

            {/* ── Row: Holdings Preview + Recent Orders ────────────────── */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {/* Holdings */}
                <div className="rounded-xl border border-edge/5 bg-surface-900/60 p-5">
                    <div className="flex items-center justify-between mb-4">
                        <h2 className="section-title text-sm text-heading">Holdings</h2>
                        <Link to="/portfolio" className="text-xs text-primary-600 hover:text-primary-500 transition-colors font-medium">View All →</Link>
                    </div>
                    {liveHoldings.length > 0 ? (
                        <div className="space-y-0.5">
                            {liveHoldings.slice(0, 5).map((h, i) => (
                                <div key={i} className="flex items-center justify-between px-3 py-2.5 rounded-lg hover:bg-surface-800/40 transition-colors">
                                    <div className="flex items-center gap-3">
                                        <div className="w-8 h-8 rounded-lg bg-primary-500/10 flex items-center justify-center text-[11px] font-semibold text-primary-600 flex-shrink-0">
                                            {(cleanSymbol(h.symbol) || '??').slice(0, 2)}
                                        </div>
                                        <div>
                                            <div className="text-sm font-semibold text-heading">{cleanSymbol(h.symbol)}</div>
                                            <div className="text-[11px] text-gray-600 font-price tabular-nums">{h.quantity} × {formatCurrency(h.avg_price)}</div>
                                        </div>
                                    </div>
                                    <div className="text-right">
                                        <div className="text-sm font-price font-semibold text-heading tabular-nums">{formatCurrency(h.current_value)}</div>
                                        <div className={cn('text-[11px] font-price tabular-nums', pnlColorClass(h.pnl))}>
                                            {(h.pnl ?? 0) >= 0 ? '+' : ''}{formatCurrency(h.pnl)} ({formatPercent(h.pnl_percent)})
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    ) : (
                        <div className="text-center py-10">
                            <IndianRupee className="w-10 h-10 mx-auto mb-2 text-gray-600 opacity-30" />
                            <p className="text-sm font-medium text-gray-500">No holdings yet</p>
                            <Link to="/terminal" className="inline-flex items-center gap-1.5 mt-2 text-xs text-primary-600 hover:text-primary-500 font-medium transition-colors">
                                Start trading <ArrowRight className="w-3 h-3" />
                            </Link>
                        </div>
                    )}
                </div>

                {/* Recent Orders */}
                <div className="rounded-xl border border-edge/5 bg-surface-900/60 p-5">
                    <div className="flex items-center justify-between mb-4">
                        <h2 className="section-title text-sm text-heading">Recent Orders</h2>
                        <Link to="/terminal" className="text-xs text-primary-600 hover:text-primary-500 transition-colors font-medium">View All →</Link>
                    </div>
                    {recentOrders.length > 0 ? (
                        <div className="space-y-0.5">
                            {recentOrders.map((o, i) => (
                                <div key={i} className="flex items-center justify-between px-3 py-2.5 rounded-lg hover:bg-surface-800/40 transition-colors">
                                    <div className="flex items-center gap-3">
                                        <span className={cn(
                                            'text-[11px] font-semibold px-2 py-0.5 rounded-md',
                                            o.side === 'BUY' ? 'bg-profit/10 text-profit' : 'bg-loss/10 text-loss'
                                        )}>
                                            {o.side}
                                        </span>
                                        <div>
                                            <div className="text-sm font-semibold text-heading">{cleanSymbol(o.symbol)}</div>
                                            <div className="text-[11px] text-gray-600 font-price tabular-nums">{o.quantity} qty</div>
                                        </div>
                                    </div>
                                    <div className="text-right">
                                        <div className="text-sm font-price font-semibold text-heading tabular-nums">{formatCurrency(o.filled_price ?? o.price)}</div>
                                        <span className={cn('text-[10px] px-1.5 py-0.5 rounded font-semibold',
                                            o.status === 'FILLED' || o.status === 'COMPLETE' ? 'text-profit bg-profit/10' :
                                                o.status === 'REJECTED' || o.status === 'CANCELLED' ? 'text-loss bg-loss/10' :
                                                    'text-primary-600 bg-primary-500/10'
                                        )}>{o.status}</span>
                                    </div>
                                </div>
                            ))}
                        </div>
                    ) : (
                        <div className="text-center py-10">
                            <BarChart3 className="w-10 h-10 mx-auto mb-2 text-gray-600 opacity-30" />
                            <p className="text-sm font-medium text-gray-500">No orders yet</p>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
