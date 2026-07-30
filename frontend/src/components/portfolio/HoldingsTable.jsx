import { useState, useMemo, memo } from 'react';
import { useNavigate } from 'react-router-dom';
import { cn } from '../../utils/cn';
import { formatCurrency, formatPrice, formatPercent, pnlColorClass, cleanSymbol } from '../../utils/formatters';
import Skeleton from '../ui/Skeleton';
import Badge from '../ui/Badge';
import { IndianRupee, Download, ChevronsUpDown, ArrowUp, ArrowDown } from 'lucide-react';

/** Export holdings data to a CSV file */
function exportToCSV(holdings) {
    const headers = ['Symbol', 'Company', 'Qty', 'Avg Price', 'LTP', 'Invested', 'Current Value', 'P&L', 'P&L %'];
    const rows = holdings.map((h) => [
        cleanSymbol(h.symbol),
        h.company_name || '',
        h.quantity,
        Number(h.avg_price).toFixed(2),
        Number(h.current_price).toFixed(2),
        Number(h.invested_value).toFixed(2),
        Number(h.current_value).toFixed(2),
        Number(h.pnl).toFixed(2),
        Number(h.pnl_percent).toFixed(2),
    ]);
    const csv = [headers, ...rows].map((r) => r.map(String).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `alphasync_holdings_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
}

const SORT_KEYS = { symbol: 'symbol', pnl: 'pnl', pnl_percent: 'pnl_percent', current_value: 'current_value' };

/**
 * Sortable, exportable holdings table with P&L flash animations.
 *
 * @param {{ holdings: Array, isLoading: boolean }} props
 */
const HoldingsTable = memo(function HoldingsTable({ holdings = [], isLoading = false }) {
    const navigate = useNavigate();
    const [sortKey, setSortKey] = useState('pnl_percent');
    const [sortDir, setSortDir] = useState('desc');

    const handleSort = (key) => {
        if (sortKey === key) setSortDir((d) => d === 'asc' ? 'desc' : 'asc');
        else { setSortKey(key); setSortDir('desc'); }
    };

    const sorted = useMemo(() => {
        return [...holdings].sort((a, b) => {
            const av = a[sortKey] ?? 0;
            const bv = b[sortKey] ?? 0;
            const cmp = typeof av === 'string' ? av.localeCompare(bv) : av - bv;
            return sortDir === 'asc' ? cmp : -cmp;
        });
    }, [holdings, sortKey, sortDir]);

    // Aggregate totals row
    const totals = useMemo(() => ({
        invested: holdings.reduce((s, h) => s + (h.invested_value ?? 0), 0),
        current: holdings.reduce((s, h) => s + (h.current_value ?? 0), 0),
        pnl: holdings.reduce((s, h) => s + (h.pnl ?? 0), 0),
    }), [holdings]);

    const SortIcon = ({ col }) => {
        if (sortKey !== col) return <ChevronsUpDown className="w-3 h-3 opacity-30" />;
        return sortDir === 'asc'
            ? <ArrowUp className="w-3 h-3 text-primary-600" />
            : <ArrowDown className="w-3 h-3 text-primary-600" />;
    };

    if (isLoading) {
        return (
            <div className="glass-card p-5">
                <div className="h-5 w-32 bg-surface-700 rounded animate-skeleton mb-4" />
                {Array.from({ length: 5 }, (_, i) => <Skeleton key={i} variant="table-row" />)}
            </div>
        );
    }

    return (
        <div className="rounded-xl border border-edge/5 bg-surface-900/60 p-5">
            <div className="flex items-center justify-between mb-4">
                <h2 className="section-title text-xs">
                    Holdings ({holdings.length})
                </h2>
                {holdings.length > 0 && (
                    <button
                        onClick={() => exportToCSV(holdings)}
                        className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-heading transition-colors"
                        title="Export to CSV"
                    >
                        <Download className="w-3.5 h-3.5" />
                        Export
                    </button>
                )}
            </div>

            {holdings.length > 0 ? (
                <div className="overflow-x-auto">
                    <table className="w-full text-sm min-w-[700px]">
                        <thead>
                            <tr className="border-b border-edge/5">
                                <th
                                    className="text-left py-3 text-[11px] font-medium tracking-wider uppercase text-gray-500 cursor-pointer hover:text-heading select-none"
                                    onClick={() => handleSort('symbol')}
                                >
                                    <span className="flex items-center gap-1">Symbol <SortIcon col="symbol" /></span>
                                </th>
                                <th className="text-right py-3 text-[11px] font-medium tracking-wider uppercase text-gray-500">Qty</th>
                                <th className="text-right py-3 text-[11px] font-medium tracking-wider uppercase text-gray-500">Avg</th>
                                <th className="text-right py-3 text-[11px] font-medium tracking-wider uppercase text-gray-500">LTP</th>
                                <th className="text-right py-3 text-[11px] font-medium tracking-wider uppercase text-gray-500">Invested</th>
                                <th
                                    className="text-right py-3 text-[11px] font-medium tracking-wider uppercase text-gray-500 cursor-pointer hover:text-heading select-none"
                                    onClick={() => handleSort('current_value')}
                                >
                                    <span className="flex items-center justify-end gap-1">Current <SortIcon col="current_value" /></span>
                                </th>
                                <th
                                    className="text-right py-3 text-[11px] font-medium tracking-wider uppercase text-gray-500 cursor-pointer hover:text-heading select-none"
                                    onClick={() => handleSort('pnl')}
                                >
                                    <span className="flex items-center justify-end gap-1">P&L <SortIcon col="pnl" /></span>
                                </th>
                                <th
                                    className="text-right py-3 text-[11px] font-medium tracking-wider uppercase text-gray-500 cursor-pointer hover:text-heading select-none"
                                    onClick={() => handleSort('pnl_percent')}
                                >
                                    <span className="flex items-center justify-end gap-1">P&L % <SortIcon col="pnl_percent" /></span>
                                </th>
                                <th className="text-right py-3 text-[11px] font-medium tracking-wider uppercase text-gray-500">Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {sorted.map((h, i) => {
                                const pnlPos = (h.pnl ?? 0) >= 0;
                                const sym = cleanSymbol(h.symbol) || '';
                                const initials = sym.slice(0, 2).toUpperCase();
                                return (
                                    <tr
                                        key={h.symbol || i}
                                        className="border-b border-edge/[0.025] hover:bg-overlay/[0.02] transition-colors group"
                                    >
                                        <td className="py-3">
                                            <div className="flex items-center gap-2.5">
                                                <div className="w-8 h-8 rounded-lg bg-primary-500/10 border border-primary-500/20 flex items-center justify-center text-[11px] font-semibold text-primary-600 flex-shrink-0">
                                                    {initials}
                                                </div>
                                                <div>
                                                    <div className="font-medium text-heading">{sym}</div>
                                                    <div className="text-xs font-normal text-gray-500">{h.company_name || h.exchange}</div>
                                                </div>
                                            </div>
                                        </td>
                                        <td className={cn('py-3 text-right font-price font-normal tabular-nums', Number(h.quantity) < 0 ? 'text-amber-400' : 'text-gray-400')}>
                                            {h.quantity}
                                            {Number(h.quantity) < 0 && <span className="ml-1 text-[9px] font-bold text-amber-400">SHORT</span>}
                                        </td>
                                        <td className="py-3 text-right font-price font-normal text-gray-400 tabular-nums">{formatPrice(h.avg_price)}</td>
                                        <td className="py-3 text-right font-price text-heading font-medium tabular-nums">{formatPrice(h.current_price)}</td>
                                        <td className="py-3 text-right font-price font-normal text-gray-400 tabular-nums">{formatCurrency(h.invested_value)}</td>
                                        <td className="py-3 text-right font-price text-heading tabular-nums">{formatCurrency(h.current_value)}</td>
                                        <td className={cn('py-3 text-right font-price font-medium tabular-nums', pnlColorClass(h.pnl ?? 0))}>
                                            {pnlPos ? '+' : ''}{formatCurrency(h.pnl)}
                                        </td>
                                        <td className={cn('py-3 text-right font-price font-medium tabular-nums', pnlColorClass(h.pnl_percent ?? 0))}>
                                            <div className="flex items-center justify-end gap-1">
                                                <span className="text-[10px]">{pnlPos ? '\u25b2' : '\u25bc'}</span>
                                                {formatPercent(h.pnl_percent, 2)}
                                            </div>
                                        </td>
                                        <td className="py-3 text-right">
                                            <div className="flex items-center justify-end gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
                                                {Number(h.quantity) < 0 ? (
                                                    /* Short position → Exit (buy to cover) */
                                                    <button
                                                        onClick={() => navigate(`/terminal?symbol=${encodeURIComponent(h.symbol)}&action=buy`)}
                                                        className="text-xs bg-bull/10 text-bull border border-bull/20 px-2 py-1 rounded hover:bg-bull/20 transition-colors"
                                                    >
                                                        Exit
                                                    </button>
                                                ) : (
                                                    /* Long position → Buy more / Sell */
                                                    <>
                                                        <button
                                                            onClick={() => navigate(`/terminal?symbol=${encodeURIComponent(h.symbol)}&action=buy`)}
                                                            className="text-xs bg-bull/10 text-bull border border-bull/20 px-2 py-1 rounded hover:bg-bull/20 transition-colors"
                                                        >
                                                            Buy
                                                        </button>
                                                        <button
                                                            onClick={() => navigate(`/terminal?symbol=${encodeURIComponent(h.symbol)}&action=sell`)}
                                                            className="text-xs bg-bear/10 text-bear border border-bear/20 px-2 py-1 rounded hover:bg-bear/20 transition-colors"
                                                        >
                                                            Sell
                                                        </button>
                                                    </>
                                                )}
                                            </div>
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                        {/* Pinned totals row */}
                        <tfoot>
                            <tr className="border-t-2 border-edge/10 text-xs font-medium">
                                <td colSpan={4} className="pt-3 text-gray-500">Total</td>
                                <td className="pt-3 text-right font-price text-gray-400 tabular-nums">{formatCurrency(totals.invested)}</td>
                                <td className="pt-3 text-right font-price text-heading tabular-nums">{formatCurrency(totals.current)}</td>
                                <td className={cn('pt-3 text-right font-price tabular-nums', pnlColorClass(totals.pnl))}>
                                    {totals.pnl >= 0 ? '+' : ''}{formatCurrency(totals.pnl)}
                                </td>
                                <td className={cn('pt-3 text-right font-price tabular-nums', pnlColorClass(totals.pnl))}>
                                    {formatPercent(totals.invested > 0 ? (totals.pnl / totals.invested) * 100 : 0)}
                                </td>
                                <td />
                            </tr>
                        </tfoot>
                    </table>
                </div>
            ) : (
                <div className="text-center py-16 text-gray-600">
                    <IndianRupee className="w-12 h-12 mx-auto mb-3 opacity-30" />
                    <p className="text-lg font-medium text-gray-500">No holdings yet</p>
                    <p className="text-sm text-gray-600 mt-1">Visit the Trading Terminal to place your first trade</p>
                </div>
            )}
        </div>
    );
});

export default HoldingsTable;
