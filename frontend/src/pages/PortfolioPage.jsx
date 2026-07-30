import { useEffect, useMemo } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { usePortfolioStore } from '../store/usePortfolioStore';
import { useMarketStore } from '../store/useMarketStore';
import HoldingsTable from '../components/portfolio/HoldingsTable';
import ErrorBoundary from '../components/ErrorBoundary';
import { Skeleton } from '../components/ui';
import {
    ArrowRight,
    TrendingUp,
    TrendingDown,
    Wallet,
    Activity,
    BadgeIndianRupee,
    BarChart3,
    Clock3,
} from 'lucide-react';
import { cn } from '../utils/cn';
import { cleanSymbol, formatCurrency, formatPercent, pnlColorClass } from '../utils/formatters';
import { buildPortfolioMetrics } from '../utils/portfolioMetrics';

function MetricCard({ label, value, delta, icon: Icon, emphasize = false }) {
    const numeric = Number(value ?? 0);
    const toneClass = emphasize ? pnlColorClass(numeric) : 'text-heading';
    return (
        <div className="kpi-card bg-surface-900/70 border-edge/15">
            <div className="flex items-center justify-between">
                <span className="metric-label">{label}</span>
                {Icon ? (
                    <Icon className={cn('w-4 h-4', emphasize ? toneClass : 'text-primary-600')} />
                ) : null}
            </div>
            <span className={cn('text-xl font-semibold font-price tabular-nums', toneClass)}>
                {numeric > 0 && emphasize ? '+' : ''}{formatCurrency(numeric)}
            </span>
            {delta != null ? (
                <span className={cn('text-xs font-price tabular-nums', emphasize ? toneClass : 'text-gray-500')}>
                    {formatPercent(delta)}
                </span>
            ) : null}
        </div>
    );
}

/**
 * Portfolio & P/L page — pro analytics + recent traded stocks + holdings table.
 * Data is sourced from existing usePortfolioStore/useMarketStore only.
 */
function BreakdownRow({ label, value, valueClass = 'text-heading' }) {
    return (
        <div className="flex items-center justify-between text-sm">
            <span className="text-gray-500">{label}</span>
            <span className={cn('font-price tabular-nums font-semibold', valueClass)}>{value}</span>
        </div>
    );
}

export default function PortfolioPage() {
    const navigate = useNavigate();
    const summary = usePortfolioStore((s) => s.summary);
    const holdings = usePortfolioStore((s) => s.holdings);
    const orders = usePortfolioStore((s) => s.orders);
    const pnl = usePortfolioStore((s) => s.pnl);
    const isLoading = usePortfolioStore((s) => s.isLoading);
    const refreshPortfolio = usePortfolioStore((s) => s.refreshPortfolio);
    const liveQuotes = useMarketStore((s) => s.symbols);

    useEffect(() => {
        refreshPortfolio();
    }, [refreshPortfolio]);

    const metrics = useMemo(() => buildPortfolioMetrics({
        summary,
        pnl,
        holdings,
        liveQuotes,
    }), [summary, pnl, holdings, liveQuotes]);

    const { liveHoldings } = metrics;

    const analytics = useMemo(() => {
        const {
            totalInvested,
            currentValue,
            liveTotals,
            realized,
            unrealized,
            totalPnl,
            availableCash,
            totalCapital,
            totalPnlPct: pnlPct,
            m2mPct,
            investedPct,
            cashPct,
        } = metrics;
        const winners = liveHoldings.filter((h) => Number(h.pnl ?? 0) > 0).length;
        const losers = liveHoldings.filter((h) => Number(h.pnl ?? 0) < 0).length;
        const winRate = winners + losers > 0 ? (winners / (winners + losers)) * 100 : 0;
        const grossExposure = liveHoldings.reduce((sum, h) => sum + Math.abs(Number(h.current_value ?? 0)), 0);

        return {
            totalInvested,
            currentValue,
            liveM2M: liveTotals.unrealized,
            realized,
            unrealized,
            totalPnl,
            availableCash,
            totalCapital,
            pnlPct,
            m2mPct,
            winners,
            losers,
            winRate,
            grossExposure,
            cashRatio: cashPct,
            allocationBase: totalCapital,
            investedPct,
        };
    }, [metrics, liveHoldings]);

    const recentTrades = useMemo(() => {
        const toEpoch = (order) => {
            const raw = order?.executed_at || order?.created_at || order?.updated_at;
            const ts = raw ? new Date(raw).getTime() : 0;
            return Number.isFinite(ts) ? ts : 0;
        };

        return [...(orders || [])]
            .sort((a, b) => toEpoch(b) - toEpoch(a))
            .slice(0, 8);
    }, [orders]);

    const turnover = useMemo(() => {
        return recentTrades.reduce((sum, order) => {
            const qty = Number(order.quantity ?? 0);
            const price = Number(order.filled_price ?? order.price ?? 0);
            return sum + (Math.abs(qty) * Math.abs(price));
        }, 0);
    }, [recentTrades]);

    const formatTradeTime = (order) => {
        const raw = order?.executed_at || order?.created_at || order?.updated_at;
        if (!raw) return '—';
        const date = new Date(raw);
        if (Number.isNaN(date.getTime())) return '—';
        return date.toLocaleString('en-IN', {
            day: '2-digit',
            month: 'short',
            hour: '2-digit',
            minute: '2-digit',
        });
    };

    const investedRatio = analytics.allocationBase > 0 ? (analytics.totalInvested / analytics.allocationBase) * 100 : 0;

    return (
        <div className="p-4 lg:p-6 space-y-6 animate-fade-in">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-display font-semibold text-heading">Portfolio &amp; P/L</h1>
                </div>
                <Link to="/terminal" className="btn-primary text-sm hidden sm:inline-flex items-center gap-2">
                    Open Terminal <ArrowRight className="w-4 h-4" />
                </Link>
            </div>

            {isLoading && !summary ? (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
                    {Array.from({ length: 5 }).map((_, i) => (
                        <Skeleton key={i} variant="stat-card" />
                    ))}
                </div>
            ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
                    <MetricCard label="Total Capital" value={analytics.totalCapital} icon={Wallet} />
                    <MetricCard label="Available Cash" value={analytics.availableCash} icon={BadgeIndianRupee} />
                    <MetricCard label="Invested Capital" value={analytics.totalInvested} delta={investedRatio} icon={BarChart3} />
                    <MetricCard label="Live M2M" value={analytics.liveM2M} delta={analytics.m2mPct} icon={Activity} emphasize />
                    <MetricCard label="Net P&L" value={analytics.totalPnl} delta={analytics.pnlPct} icon={analytics.totalPnl >= 0 ? TrendingUp : TrendingDown} emphasize />
                </div>
            )}

            <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
                <div className="xl:col-span-1 rounded-xl border border-edge/5 bg-surface-900/60 p-5 section-card card-hover-glow">
                    <h2 className="section-title text-sm text-heading mb-4">P/L Breakdown</h2>
                    <div className="space-y-3">
                        <BreakdownRow label="Realized P&L" value={`${analytics.realized > 0 ? '+' : ''}${formatCurrency(analytics.realized)}`} valueClass={pnlColorClass(analytics.realized)} />
                        <BreakdownRow label="Unrealized P&L" value={`${analytics.unrealized > 0 ? '+' : ''}${formatCurrency(analytics.unrealized)}`} valueClass={pnlColorClass(analytics.unrealized)} />
                        <BreakdownRow label="Live M2M" value={`${analytics.liveM2M > 0 ? '+' : ''}${formatCurrency(analytics.liveM2M)}`} valueClass={pnlColorClass(analytics.liveM2M)} />
                        <BreakdownRow label="Gross Exposure" value={formatCurrency(analytics.grossExposure)} />
                        <BreakdownRow label="Holdings Win Rate" value={formatPercent(analytics.winRate)} />
                    </div>

                    <div className="mt-5 pt-4 border-t border-edge/10">
                        <div className="grid grid-cols-3 gap-2">
                            <div className="rounded-lg border border-edge/10 bg-surface-800/50 p-2 text-center">
                                <div className="text-[11px] text-gray-500">Winners</div>
                                <div className="text-sm font-semibold text-profit tabular-nums">{analytics.winners}</div>
                            </div>
                            <div className="rounded-lg border border-edge/10 bg-surface-800/50 p-2 text-center">
                                <div className="text-[11px] text-gray-500">Losers</div>
                                <div className="text-sm font-semibold text-loss tabular-nums">{analytics.losers}</div>
                            </div>
                            <div className="rounded-lg border border-edge/10 bg-surface-800/50 p-2 text-center">
                                <div className="text-[11px] text-gray-500">Open Pos.</div>
                                <div className="text-sm font-semibold text-heading tabular-nums">{liveHoldings.length}</div>
                            </div>
                        </div>
                    </div>

                    <div className="mt-4">
                        <div className="flex items-center justify-between text-[11px] mb-2">
                            <span className="text-primary-600 font-price">Invested: {Math.max(0, investedRatio).toFixed(1)}%</span>
                            <span className="text-emerald-600 font-price">Cash: {Math.max(0, analytics.cashRatio).toFixed(1)}%</span>
                        </div>
                        <div className="w-full h-2.5 bg-surface-800 rounded-full overflow-hidden flex gap-px">
                            <div className="bg-primary-500 h-full rounded-l-full transition-all duration-700" style={{ width: `${Math.max(0, Math.min(100, investedRatio))}%` }} />
                            <div className="bg-emerald-500/40 h-full rounded-r-full transition-all duration-700" style={{ width: `${Math.max(0, Math.min(100, analytics.cashRatio))}%` }} />
                        </div>
                    </div>
                </div>

                <div className="xl:col-span-2 rounded-xl border border-edge/5 bg-surface-900/60 p-5 section-card card-hover-glow">
                    <div className="flex items-center justify-between mb-4">
                        <h2 className="section-title text-sm text-heading">Recently Traded Stocks</h2>
                        <Link to="/orders" className="text-xs text-primary-600 hover:text-primary-500 transition-colors font-medium">View Full Orderbook →</Link>
                    </div>

                    {recentTrades.length > 0 ? (
                        <div className="space-y-1">
                            {recentTrades.map((order, index) => (
                                <button
                                    type="button"
                                    key={`${order.id || order.order_id || index}`}
                                    onClick={() => navigate(`/terminal?symbol=${encodeURIComponent(order.symbol || '')}`)}
                                    className="w-full rounded-lg border border-edge/10 bg-surface-800/35 px-3 py-2.5 hover:bg-surface-800/60 transition-colors text-left"
                                >
                                    <div className="flex items-center justify-between gap-3">
                                        <div className="min-w-0">
                                            <div className="text-sm font-semibold text-heading truncate">{cleanSymbol(order.symbol || 'N/A')}</div>
                                            <div className="text-[11px] text-gray-500 flex items-center gap-1.5">
                                                <Clock3 className="w-3 h-3" />
                                                {formatTradeTime(order)}
                                            </div>
                                        </div>

                                        <div className="flex items-center gap-2 sm:gap-4">
                                            <span className={cn(
                                                'text-[11px] font-semibold px-2 py-0.5 rounded-md',
                                                order.side === 'BUY' ? 'bg-profit/10 text-profit' : 'bg-loss/10 text-loss'
                                            )}>
                                                {order.side || '—'}
                                            </span>
                                            <span className="text-xs font-price tabular-nums text-heading">{order.quantity ?? 0}</span>
                                            <span className="text-xs font-price tabular-nums text-heading min-w-[90px] text-right">{formatCurrency(order.filled_price ?? order.price ?? 0)}</span>
                                            <span className={cn(
                                                'text-[10px] px-1.5 py-0.5 rounded font-semibold min-w-[62px] text-center',
                                                order.status === 'FILLED'
                                                    ? 'text-profit bg-profit/10'
                                                    : order.status === 'REJECTED' || order.status === 'CANCELLED'
                                                        ? 'text-loss bg-loss/10'
                                                        : 'text-primary-600 bg-primary-500/10'
                                            )}>
                                                {order.status || 'PENDING'}
                                            </span>
                                        </div>
                                    </div>
                                </button>
                            ))}
                        </div>
                    ) : (
                        <div className="text-center py-10 text-gray-600">
                            <p className="text-sm">No recent trades available.</p>
                            <p className="text-xs mt-1">Your latest executed and active orders appear here.</p>
                        </div>
                    )}

                    <div className="mt-4 pt-4 border-t border-edge/10">
                        <BreakdownRow label="Recent Turnover" value={formatCurrency(turnover)} />
                    </div>
                </div>
            </div>

            <ErrorBoundary fallback="Holdings table failed to load.">
                <HoldingsTable holdings={liveHoldings} isLoading={isLoading} />
            </ErrorBoundary>
        </div>
    );
}

