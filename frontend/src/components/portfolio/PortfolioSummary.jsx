import { formatCurrency } from '../../utils/formatters';
import { buildPortfolioMetrics } from '../../utils/portfolioMetrics';
import PnLCard from './PnLCard';
import Skeleton from '../ui/Skeleton';

/**
 * Portfolio summary: 5-card stat grid + capital allocation bar.
 *
 * @param {{ summary: object|null, isLoading: boolean }} props
 */
export default function PortfolioSummary({ summary, isLoading }) {
    const metrics = buildPortfolioMetrics({ summary });
    const { availableCash, currentValue, totalInvested, totalPnl, totalPnlPct, totalCapital, investedPct } = metrics;

    if (isLoading) {
        return (
            <div className="space-y-4">
                <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
                    {Array.from({ length: 5 }, (_, i) => <Skeleton key={i} variant="stat-card" />)}
                </div>
            </div>
        );
    }

    return (
        <div className="space-y-4">
            {/* Stat grid */}
            <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
                <div className="kpi-card">
                    <span className="metric-label">Total Capital</span>
                    <span className="text-xl font-semibold text-heading font-price tabular-nums">{formatCurrency(totalCapital)}</span>
                </div>
                <div className="kpi-card">
                    <span className="metric-label">Available Cash</span>
                    <span className="text-xl font-semibold text-heading font-price tabular-nums">{formatCurrency(availableCash)}</span>
                </div>
                <div className="kpi-card">
                    <span className="metric-label">Invested</span>
                    <span className="text-xl font-semibold text-heading font-price tabular-nums">{formatCurrency(totalInvested)}</span>
                    <span className="text-xs text-gray-500 font-price tabular-nums">{investedPct.toFixed(1)}% deployed</span>
                </div>
                <div className="kpi-card">
                    <span className="metric-label">Current Value</span>
                    <span className="text-xl font-semibold text-heading font-price tabular-nums">{formatCurrency(currentValue)}</span>
                </div>
                <PnLCard label="Total P&L" value={totalPnl} percent={totalPnlPct} />
            </div>

            {/* Capital allocation bar — segmented */}
            <div className="rounded-xl border border-edge/5 bg-surface-900/60 p-5">
                <h2 className="section-title text-xs mb-3">
                    Capital Allocation
                </h2>
                <div className="w-full h-2.5 bg-surface-800 rounded-full overflow-hidden flex gap-px">
                    <div
                        className="bg-primary-500 h-full rounded-l-full transition-all duration-700"
                        style={{ width: `${investedPct}%` }}
                    />
                    <div
                        className="bg-emerald-500/40 h-full rounded-r-full transition-all duration-700"
                        style={{ width: `${100 - investedPct}%` }}
                    />
                </div>
                <div className="flex justify-between mt-2 text-xs">
                    <span className="text-primary-600 font-price tabular-nums">Invested: {investedPct.toFixed(1)}%</span>
                    <span className="text-emerald-600 font-price tabular-nums">Cash: {(100 - investedPct).toFixed(1)}%</span>
                </div>
            </div>
        </div>
    );
}
