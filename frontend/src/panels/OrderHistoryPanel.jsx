import { memo, useCallback, useMemo, useState } from 'react';
import Modal from '../components/ui/Modal';
import Button from '../components/ui/Button';
import api from '../services/api';
import { cn } from '../utils/cn';
import { formatPrice, cleanSymbol } from '../utils/formatters';
import { ORDER_STATUS_CLASS } from '../utils/constants';
import { usePortfolioStore } from '../store/usePortfolioStore';
import { PanelContainer } from '.';

/**
 * OrderHistoryPanel — shows recent orders.
 * Extracted from TradingTerminalPage BottomTabs → "orders" tab.
 */
function OrderHistoryPanel({ orders = [], className, showHeader = true }) {
    const refreshPortfolio = usePortfolioStore((s) => s.refreshPortfolio);
    const [editingOrder, setEditingOrder] = useState(null);
    const [editDraft, setEditDraft] = useState({ quantity: '', price: '', triggerPrice: '', takeProfitPrice: '' });
    const [editError, setEditError] = useState('');
    const [saving, setSaving] = useState(false);

    const openOnly = useMemo(() => (order) => String(order?.status || '').toUpperCase() === 'OPEN', []);

    const openModify = useCallback((order) => {
        setEditError('');
        setEditingOrder(order);
        setEditDraft({
            quantity: String(order?.quantity ?? ''),
            price: order?.price == null ? '' : String(order.price),
            triggerPrice: order?.trigger_price == null ? '' : String(order.trigger_price),
            takeProfitPrice: order?.take_profit_price == null ? '' : String(order.take_profit_price),
        });
    }, []);

    const closeModify = useCallback(() => {
        if (saving) return;
        setEditingOrder(null);
        setEditError('');
    }, [saving]);

    const handleCancel = useCallback(async (order) => {
        const id = String(order?.id || '').trim();
        if (!id) return;

        const confirmCancel = window.confirm(`Cancel open order for ${cleanSymbol(order.symbol)}?`);
        if (!confirmCancel) return;

        try {
            await api.delete(`/orders/${encodeURIComponent(id)}`);
            usePortfolioStore.setState((state) => ({
                orders: (state.orders || []).map((row) => {
                    const rowId = String(row.id || '').trim();
                    if (rowId !== id) return row;
                    return { ...row, status: 'CANCELLED', updated_at: new Date().toISOString() };
                }),
            }));
            void refreshPortfolio();
        } catch (err) {
            console.error('Cancel order failed:', err);
        }
    }, [refreshPortfolio]);

    const handleModifySubmit = useCallback(async () => {
        if (!editingOrder) return;

        const id = String(editingOrder.id || '').trim();
        if (!id) {
            setEditError('Missing order id.');
            return;
        }

        const orderType = String(editingOrder.order_type || '').toUpperCase();
        const quantity = Number(editDraft.quantity);
        const price = Number(editDraft.price);
        const triggerPrice = Number(editDraft.triggerPrice);
        const takeProfitPrice = Number(editDraft.takeProfitPrice);

        if (!Number.isFinite(quantity) || quantity <= 0) {
            setEditError('Quantity must be positive.');
            return;
        }

        const payload = { quantity };
        if (orderType !== 'MARKET' && Number.isFinite(price) && price > 0) payload.price = price;
        if (['STOP_LOSS', 'STOP_LOSS_LIMIT', 'BRACKET'].includes(orderType) && Number.isFinite(triggerPrice) && triggerPrice > 0) {
            payload.trigger_price = triggerPrice;
        }
        if (['TAKE_PROFIT', 'BRACKET'].includes(orderType) && Number.isFinite(takeProfitPrice) && takeProfitPrice > 0) {
            payload.take_profit_price = takeProfitPrice;
        }

        setSaving(true);
        setEditError('');
        try {
            const response = await api.patch(`/orders/${encodeURIComponent(id)}`, payload);
            const updated = response?.data?.order;
            usePortfolioStore.setState((state) => ({
                orders: (state.orders || []).map((row) => {
                    const rowId = String(row.id || '').trim();
                    if (rowId !== id) return row;
                    return {
                        ...row,
                        quantity: updated?.quantity ?? quantity,
                        price: updated?.price ?? (Number.isFinite(price) && price > 0 ? price : row.price),
                        trigger_price: updated?.trigger_price ?? row.trigger_price,
                        take_profit_price: updated?.take_profit_price ?? row.take_profit_price,
                        updated_at: updated?.updated_at ?? new Date().toISOString(),
                    };
                }),
            }));
            setEditingOrder(null);
            void refreshPortfolio();
        } catch (err) {
            setEditError(err?.response?.data?.detail || err?.response?.data?.error || err?.message || 'Modify failed.');
        } finally {
            setSaving(false);
        }
    }, [editDraft, editingOrder, refreshPortfolio]);

    return (
        <>
        <PanelContainer title={showHeader ? 'Orders' : ''} noPadding className={className}
            actions={<span className="text-[10px] text-gray-600 font-price tabular-nums">{orders.length}</span>}
        >
            {orders.length > 0 ? (
                <div className="overflow-x-auto">
                    <table className="w-full text-xs min-w-[600px]">
                        <thead>
                            <tr>
                                <th className="text-left px-3 pb-2 pt-2 metric-label">Symbol</th>
                                <th className="text-left px-3 pb-2 pt-2 metric-label">Side</th>
                                <th className="text-left px-3 pb-2 pt-2 metric-label">Type</th>
                                <th className="text-right px-3 pb-2 pt-2 metric-label">Qty</th>
                                <th className="text-right px-3 pb-2 pt-2 metric-label">Price</th>
                                <th className="text-right px-3 pb-2 pt-2 metric-label">Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            {orders.map((o, i) => (
                                <tr key={o.id || i} className="border-t border-edge/[0.03] hover:bg-overlay/[0.02] transition-colors">
                                    <td className="px-3 py-1.5 font-semibold text-heading">{cleanSymbol(o.symbol)}</td>
                                    <td className={cn('px-3 py-1.5 font-semibold', o.side === 'BUY' ? 'text-bull' : 'text-bear')}>{o.side}</td>
                                    <td className="px-3 py-1.5 text-gray-400">{o.order_type}</td>
                                    <td className="px-3 py-1.5 text-right font-price text-gray-600 tabular-nums">{o.quantity}</td>
                                    <td className="px-3 py-1.5 text-right font-price text-heading tabular-nums">
                                        {formatPrice(o.filled_price ?? o.price ?? null)}
                                    </td>
                                    <td className="px-3 py-1.5 text-right whitespace-nowrap">
                                        <div className="inline-flex items-center justify-end gap-1.5">
                                            <span className={cn('text-[11px] px-2 py-0.5 rounded-full font-medium',
                                                ORDER_STATUS_CLASS[o.status] || ORDER_STATUS_CLASS.PENDING
                                            )}>
                                                {o.status}
                                            </span>
                                            {openOnly(o) && (
                                                <>
                                                    <button
                                                        type="button"
                                                        onClick={() => openModify(o)}
                                                        className="rounded border border-primary-500/20 bg-primary-500/10 px-2 py-0.5 text-[10px] font-semibold text-primary-600 hover:bg-primary-500/15"
                                                    >
                                                        Modify
                                                    </button>
                                                    <button
                                                        type="button"
                                                        onClick={() => handleCancel(o)}
                                                        className="rounded border border-bear/20 bg-bear/10 px-2 py-0.5 text-[10px] font-semibold text-bear hover:bg-bear/15"
                                                    >
                                                        Cancel
                                                    </button>
                                                </>
                                            )}
                                        </div>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            ) : (
                <div className="text-center py-6 text-gray-600 text-xs">No orders yet.</div>
            )}
        </PanelContainer>
        <Modal
            isOpen={Boolean(editingOrder)}
            onClose={closeModify}
            title={editingOrder ? `Modify ${cleanSymbol(editingOrder.symbol)}` : 'Modify Order'}
            size="sm"
            className="max-w-[420px]"
        >
            {editingOrder && (
                <div className="p-4 space-y-3">
                    <div className="grid grid-cols-2 gap-2 text-xs">
                        <label className="block">
                            <span className="metric-label mb-1 block">Quantity</span>
                            <input
                                type="number"
                                value={editDraft.quantity}
                                onChange={(e) => setEditDraft((prev) => ({ ...prev, quantity: e.target.value }))}
                                className="h-9 w-full rounded border border-edge/10 bg-surface-900/60 px-2 text-heading"
                            />
                        </label>
                        {String(editingOrder.order_type || '').toUpperCase() !== 'MARKET' && (
                            <label className="block">
                                <span className="metric-label mb-1 block">Price</span>
                                <input
                                    type="number"
                                    step="0.05"
                                    value={editDraft.price}
                                    onChange={(e) => setEditDraft((prev) => ({ ...prev, price: e.target.value }))}
                                    className="h-9 w-full rounded border border-edge/10 bg-surface-900/60 px-2 text-heading"
                                />
                            </label>
                        )}
                        {['STOP_LOSS', 'STOP_LOSS_LIMIT', 'BRACKET'].includes(String(editingOrder.order_type || '').toUpperCase()) && (
                            <label className="block">
                                <span className="metric-label mb-1 block">Trigger Price</span>
                                <input
                                    type="number"
                                    step="0.05"
                                    value={editDraft.triggerPrice}
                                    onChange={(e) => setEditDraft((prev) => ({ ...prev, triggerPrice: e.target.value }))}
                                    className="h-9 w-full rounded border border-edge/10 bg-surface-900/60 px-2 text-heading"
                                />
                            </label>
                        )}
                        {['TAKE_PROFIT', 'BRACKET'].includes(String(editingOrder.order_type || '').toUpperCase()) && (
                            <label className="block">
                                <span className="metric-label mb-1 block">Take Profit</span>
                                <input
                                    type="number"
                                    step="0.05"
                                    value={editDraft.takeProfitPrice}
                                    onChange={(e) => setEditDraft((prev) => ({ ...prev, takeProfitPrice: e.target.value }))}
                                    className="h-9 w-full rounded border border-edge/10 bg-surface-900/60 px-2 text-heading"
                                />
                            </label>
                        )}
                    </div>

                    {editError && (
                        <div className="rounded-lg border border-bear/20 bg-bear/10 px-3 py-2 text-[11px] text-bear">
                            {editError}
                        </div>
                    )}

                    <div className="flex items-center justify-end gap-2 pt-1">
                        <Button type="button" variant="ghost" size="sm" onClick={closeModify} disabled={saving}>
                            Cancel
                        </Button>
                        <Button type="button" size="sm" onClick={handleModifySubmit} disabled={saving}>
                            {saving ? 'Saving...' : 'Save'}
                        </Button>
                    </div>
                </div>
            )}
        </Modal>
        </>
    );
}

export default memo(OrderHistoryPanel);
