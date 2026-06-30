import { memo, useState, useCallback } from 'react';
import { cn } from '../utils/cn';
import { formatPrice, formatPercent, cleanSymbol } from '../utils/formatters';
import { PanelContainer } from '.';
import api from '../services/api';
import { usePortfolioStore } from '../store/usePortfolioStore';

const formatEntryTime = (value) => {
    if (!value) return '--';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return '--';
    return parsed.toLocaleString('en-IN', {
        hour12: false,
        day: '2-digit',
        month: '2-digit',
        year: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
    });
};

/**
 * Positions Panel — shows open positions in a table.
 * Extracted from TradingTerminalPage BottomTabs → "positions" tab.
 */
function PositionsPanel({ holdings = [], className, onSell, onBuy, showHeader = true }) {
    const [closing, setClosing] = useState(false);

    const handleCloseAll = useCallback(async () => {
        if (!confirm('Close ALL open positions? This will place market sell/buy orders for every holding.')) return;
        setClosing(true);
        try {
            const res = await api.post('/orders/close-all');
            const data = res.data;
            alert(`${data.message}${data.errors?.length ? '\nErrors: ' + data.errors.join(', ') : ''}`);
            await usePortfolioStore.getState().refreshPortfolio();
            setTimeout(() => {
                usePortfolioStore.getState().refreshPortfolio();
            }, 500);
        } catch (err) {
            alert('Failed to close positions: ' + (err.response?.data?.detail || err.message));
        } finally {
            setClosing(false);
        }
    }, []);

    return (
        <PanelContainer title={showHeader ? 'Positions' : ''} noPadding className={className}
            actions={
                <div className="flex items-center gap-2">
                    {holdings.length > 0 && (
                        <button
                            onClick={handleCloseAll}
                            disabled={closing}
                            className="px-2 py-0.5 rounded text-[10px] font-bold bg-red-500/15 text-red-500 hover:bg-red-500/30 border border-red-500/20 transition-colors disabled:opacity-50"
                            title="Close all positions (Kill Switch)"
                        >
                            {closing ? 'CLOSING...' : 'CLOSE ALL'}
                        </button>
                    )}
                    <span className="text-[10px] text-gray-600 font-price tabular-nums">{holdings.length}</span>
                </div>
            }
        >
            {holdings.length > 0 ? (
                <div className="overflow-x-auto">
                    <table className="w-full text-sm min-w-[1180px]">
                        <thead>
                            <tr className="border-b border-edge/10">
                                <th className="text-left px-3 pb-2 pt-2 text-[11px] font-medium tracking-wider uppercase text-gray-500">Symbol</th>
                                <th className="text-left px-3 pb-2 pt-2 text-[11px] font-medium tracking-wider uppercase text-gray-500">Type</th>
                                <th className="text-left px-3 pb-2 pt-2 text-[11px] font-medium tracking-wider uppercase text-gray-500">Product</th>
                                <th className="text-left px-3 pb-2 pt-2 text-[11px] font-medium tracking-wider uppercase text-gray-500">Entry Time</th>
                                <th className="text-right px-3 pb-2 pt-2 text-[11px] font-medium tracking-wider uppercase text-gray-500">Qty</th>
                                <th className="text-right px-3 pb-2 pt-2 text-[11px] font-medium tracking-wider uppercase text-gray-500">Avg</th>
                                <th className="text-right px-3 pb-2 pt-2 text-[11px] font-medium tracking-wider uppercase text-gray-500">LTP</th>
                                <th className="text-right px-3 pb-2 pt-2 text-[11px] font-medium tracking-wider uppercase text-gray-500">Invested</th>
                                <th className="text-right px-3 pb-2 pt-2 text-[11px] font-medium tracking-wider uppercase text-gray-500">P&L</th>
                                <th className="text-right px-3 pb-2 pt-2 text-[11px] font-medium tracking-wider uppercase text-gray-500">Action</th>
                            </tr>
                        </thead>
                        <tbody>
                            {holdings.map((h, i) => {
                                const pnl = h.pnl ?? 0;
                                const pnlPct = h.pnl_percent ?? 0;
                                const qty = Number(h.quantity ?? 0);
                                const isShort = qty < 0;
                                const positionType = String(h.position_type || (isShort ? 'SHORT' : 'LONG')).toUpperCase();
                                const productType = String(h.product_type || 'CNC').toUpperCase();
                                const exchange = String(h.exchange || 'NSE').toUpperCase();
                                return (
                                    <tr key={h.symbol || i} className="border-b border-edge/[0.025] hover:bg-overlay/[0.02] transition-colors">
                                        <td className="py-2.5 px-3 font-medium text-heading">
                                            {cleanSymbol(h.symbol)}
                                            <span className="ml-1.5 text-[9px] font-bold px-1 py-0.5 rounded bg-overlay/60 text-gray-500 border border-edge/20">
                                                {exchange}
                                            </span>
                                        </td>
                                        <td className={cn('py-2.5 px-3 text-[11px] font-semibold', positionType === 'SHORT' ? 'text-amber-400' : 'text-bull')}>
                                            {positionType}
                                        </td>
                                        <td className="py-2.5 px-3 text-[11px] font-medium text-gray-400">
                                            {productType}
                                        </td>
                                        <td className="py-2.5 px-3 text-[11px] font-mono text-gray-500 tabular-nums">
                                            {formatEntryTime(h.entry_time)}
                                        </td>
                                        <td className={cn('py-2.5 px-3 text-right font-mono', isShort ? 'text-amber-400' : 'text-gray-400')}>
                                            <span>{h.quantity}</span>
                                        </td>
                                        <td className="py-2.5 px-3 text-right font-mono text-gray-400">{formatPrice(h.avg_price)}</td>
                                        <td className="py-2.5 px-3 text-right font-mono font-medium text-heading">{formatPrice(h.current_price)}</td>
                                        <td className="py-2.5 px-3 text-right font-mono text-gray-400">₹{formatPrice(h.invested_value ?? 0)}</td>
                                        <td className={cn('py-2.5 px-3 text-right font-mono font-medium', pnl >= 0 ? 'text-emerald-600' : 'text-red-500')}>
                                            {pnl >= 0 ? '+' : ''}₹{formatPrice(pnl)}{' '}
                                            ({formatPercent(pnlPct)})
                                        </td>
                                        <td className="py-2.5 px-3 text-right">
                                            {isShort ? (
                                                /* Short position → EXIT (buy to cover) — like Zerodha/Groww */
                                                <button
                                                    onClick={() => onBuy?.(h.symbol)}
                                                    className="px-2 py-1 rounded text-[10px] font-bold bg-emerald-500/15 text-emerald-500 hover:bg-emerald-500/30 border border-emerald-500/20 transition-colors"
                                                >
                                                    EXIT
                                                </button>
                                            ) : (
                                                /* Long position → SELL */
                                                <button
                                                    onClick={() => onSell?.(h.symbol)}
                                                    className="px-2 py-1 rounded text-[10px] font-bold bg-red-500/15 text-red-500 hover:bg-red-500/30 border border-red-500/20 transition-colors"
                                                >
                                                    SELL
                                                </button>
                                            )}
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            ) : (
                <div className="text-center py-6 text-gray-600 text-xs">
                    No open positions. Place a trade to get started.
                </div>
            )}
        </PanelContainer>
    );
}

export default memo(PositionsPanel);
