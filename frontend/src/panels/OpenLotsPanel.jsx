import { memo, useEffect, useMemo, useRef } from 'react';
import { cn } from '../utils/cn';
import { formatPrice, formatPercent, cleanSymbol } from '../utils/formatters';
import { PanelContainer } from '.';

const normalizeSymbol = (value) => String(value || '').trim().toUpperCase();

const getLotIdentity = (lot, index) =>
    String(
        lot?.id
        || lot?.order_id
        || `${lot?.symbol || 'UNKNOWN'}-${lot?.created_at || index}`
    );

const formatLotTime = (value) => {
    if (!Number.isFinite(Number(value))) return '--';
    const parsed = new Date(Number(value));
    if (Number.isNaN(parsed.getTime())) return '--';

    return parsed.toLocaleTimeString('en-IN', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
    });
};

function OpenLotsPanel({
    lots = [],
    holdings = [],
    className,
    showHeader = true,
    onSell,
    onBuy,
}) {
    const localLotTimesRef = useRef(new Map());

    useEffect(() => {
        const seenKeys = new Set();

        (lots || []).forEach((lot, index) => {
            const key = getLotIdentity(lot, index);
            seenKeys.add(key);
            if (!localLotTimesRef.current.has(key)) {
                localLotTimesRef.current.set(key, Date.now());
            }
        });

        for (const existingKey of localLotTimesRef.current.keys()) {
            if (!seenKeys.has(existingKey)) {
                localLotTimesRef.current.delete(existingKey);
            }
        }
    }, [lots]);

    const ltpBySymbol = useMemo(() => {
        const map = new Map();
        for (const h of holdings || []) {
            const key = normalizeSymbol(h.symbol);
            if (!key) continue;
            const ltp = Number(h.current_price ?? h.avg_price ?? 0);
            if (Number.isFinite(ltp) && ltp > 0) {
                map.set(key, ltp);
            }
        }
        return map;
    }, [holdings]);

    const lotsWithComputed = useMemo(() => {
        return (lots || []).map((lot, index) => {
            const lotIdentity = getLotIdentity(lot, index);
            const symbolKey = normalizeSymbol(lot.symbol);
            const holdingLtp = Number(ltpBySymbol.get(symbolKey));
            const lotLtp = Number(lot.current_price);
            const ltp = Number.isFinite(holdingLtp) && holdingLtp > 0
                ? holdingLtp
                : (Number.isFinite(lotLtp) && lotLtp > 0 ? lotLtp : null);

            const qty = Math.abs(Number(lot.remaining_qty ?? 0));
            const entry = Number(lot.entry_price ?? 0);
            const isShort = Number(lot.remaining_qty ?? 0) < 0;

            let pnl = null;
            let pnlPercent = null;
            if (Number.isFinite(ltp) && Number.isFinite(entry) && entry > 0 && qty > 0) {
                pnl = isShort ? (entry - ltp) * qty : (ltp - entry) * qty;
                pnlPercent = (pnl / (entry * qty)) * 100;
            } else {
                const lotPnl = Number(lot.pnl);
                const lotPnlPercent = Number(lot.pnl_percent);
                if (Number.isFinite(lotPnl)) {
                    pnl = lotPnl;
                    pnlPercent = Number.isFinite(lotPnlPercent) ? lotPnlPercent : null;
                }
            }

            return {
                ...lot,
                lotIdentity,
                localCreatedAtMs: localLotTimesRef.current.get(lotIdentity) ?? Date.now(),
                ltp,
                qty,
                entry,
                isShort,
                pnl,
                pnlPercent,
            };
        });
    }, [lots, ltpBySymbol]);

    const totals = useMemo(() => {
        let qty = 0;
        let pnl = 0;
        for (const lot of lotsWithComputed) {
            qty += Math.abs(Number(lot.remaining_qty ?? 0));
            if (Number.isFinite(lot.pnl)) {
                pnl += Number(lot.pnl);
            }
        }
        return { qty, pnl };
    }, [lotsWithComputed]);

    return (
        <PanelContainer
            title={showHeader ? 'Lots' : ''}
            noPadding
            className={className}
            actions={<span className="text-[10px] text-gray-600 font-price tabular-nums">{lotsWithComputed.length}</span>}
        >
            {lotsWithComputed.length > 0 ? (
                <div className="overflow-x-auto">
                    <table className="w-full text-xs min-w-[980px]">
                        <thead>
                            <tr>
                                <th className="text-left px-3 pb-2 pt-2 metric-label">Time</th>
                                <th className="text-left px-3 pb-2 pt-2 metric-label">Trade</th>
                                <th className="text-left px-3 pb-2 pt-2 metric-label">Symbol</th>
                                <th className="text-left px-3 pb-2 pt-2 metric-label">Lot Type</th>
                                <th className="text-left px-3 pb-2 pt-2 metric-label">Product</th>
                                <th className="text-right px-3 pb-2 pt-2 metric-label">Qty</th>
                                <th className="text-right px-3 pb-2 pt-2 metric-label">Entry</th>
                                <th className="text-right px-3 pb-2 pt-2 metric-label">LTP</th>
                                <th className="text-right px-3 pb-2 pt-2 metric-label">P&L</th>
                                <th className="text-right px-3 pb-2 pt-2 metric-label">Action</th>
                            </tr>
                        </thead>
                        <tbody>
                            {lotsWithComputed.map((lot, index) => {
                                const formattedTime = formatLotTime(lot.localCreatedAtMs);
                                const tradeId = String(lot.order_id || lot.id || '').replace(/-/g, '').slice(0, 8) || '--';

                                return (
                                    <tr key={lot.lotIdentity || `${lot.symbol}-${index}`} className="border-t border-edge/[0.03] hover:bg-overlay/[0.02] transition-colors">
                                        <td className="px-3 py-1.5 text-gray-500 font-price tabular-nums">{formattedTime}</td>
                                        <td className="px-3 py-1.5 text-gray-500 font-price tabular-nums uppercase">{tradeId}</td>
                                        <td className="px-3 py-1.5 font-semibold text-heading">{cleanSymbol(lot.symbol)}</td>
                                        <td className={cn('px-3 py-1.5 font-semibold', lot.isShort ? 'text-amber-400' : 'text-bull')}>
                                            {lot.isShort ? 'SHORT' : 'LONG'}
                                        </td>
                                        <td className="px-3 py-1.5 text-[11px] font-medium text-gray-400">
                                            {String(lot.product_type || 'CNC').toUpperCase()}
                                        </td>
                                        <td className="px-3 py-1.5 text-right font-price text-gray-600 tabular-nums">{lot.qty}</td>
                                        <td className="px-3 py-1.5 text-right font-price text-heading tabular-nums">{formatPrice(lot.entry)}</td>
                                        <td className="px-3 py-1.5 text-right font-price text-heading tabular-nums">
                                            {Number.isFinite(lot.ltp) ? formatPrice(lot.ltp) : '--'}
                                        </td>
                                        <td className={cn(
                                            'px-3 py-1.5 text-right font-price tabular-nums',
                                            lot.pnl == null ? 'text-gray-500' : (lot.pnl >= 0 ? 'text-bull' : 'text-bear')
                                        )}>
                                            {lot.pnl == null ? '--' : `${lot.pnl >= 0 ? '+' : ''}₹${formatPrice(lot.pnl)} (${formatPercent(lot.pnlPercent ?? 0)})`}
                                        </td>
                                        <td className="px-3 py-1.5 text-right">
                                            {lot.isShort ? (
                                                <button
                                                    onClick={() => onBuy?.(lot.symbol)}
                                                    className="px-2 py-1 rounded text-[10px] font-bold bg-emerald-500/15 text-emerald-500 hover:bg-emerald-500/30 border border-emerald-500/20 transition-colors"
                                                >
                                                    EXIT
                                                </button>
                                            ) : (
                                                <button
                                                    onClick={() => onSell?.(lot.symbol)}
                                                    className="px-2 py-1 rounded text-[10px] font-bold bg-red-500/15 text-red-500 hover:bg-red-500/30 border border-red-500/20 transition-colors"
                                                >
                                                    EXIT
                                                </button>
                                            )}
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                        <tfoot>
                            <tr className="border-t border-edge/20 bg-overlay/[0.03]">
                                <td className="px-3 py-2 text-[11px] font-semibold text-gray-500" colSpan={5}>TOTAL</td>
                                <td className="px-3 py-2 text-right text-[11px] font-semibold text-heading font-price tabular-nums">{totals.qty}</td>
                                <td className="px-3 py-2" colSpan={2} />
                                <td className={cn(
                                    'px-3 py-2 text-right text-[11px] font-semibold font-price tabular-nums',
                                    totals.pnl >= 0 ? 'text-bull' : 'text-bear'
                                )}>
                                    {totals.pnl >= 0 ? '+' : ''}₹{formatPrice(totals.pnl)}
                                </td>
                                <td className="px-3 py-2" />
                            </tr>
                        </tfoot>
                    </table>
                </div>
            ) : (
                <div className="text-center py-6 text-gray-600 text-xs">
                    No open lots yet. New entries will appear here separately.
                </div>
            )}
        </PanelContainer>
    );
}

export default memo(OpenLotsPanel);
