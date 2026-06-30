import { useState, useCallback, useMemo, useEffect, useRef } from 'react';
import api from '../services/api';
import { usePortfolioStore } from '../store/usePortfolioStore';
import { validateOrderForm } from '../utils/validators';
import { ORDER_SIDE, ORDER_TYPE, TRADING_MODE, TRADING_MODE_PRODUCT, isMcxSymbol } from '../utils/constants';
import toast from 'react-hot-toast';

const ORDER_TYPE_ALIAS_MAP = {
    MARKET: 'MARKET',
    LIMIT: 'LIMIT',
    BRACKET: 'BRACKET',
    'LIMIT + TP + SL': 'BRACKET',
    STOP_LOSS: 'STOP_LOSS',
    'STOP LOSS': 'STOP_LOSS',
    SL: 'STOP_LOSS',
    STOP_LOSS_LIMIT: 'STOP_LOSS_LIMIT',
    'STOP LOSS LIMIT': 'STOP_LOSS_LIMIT',
    'SL-M': 'STOP_LOSS_LIMIT',
    TAKE_PROFIT: 'TAKE_PROFIT',
    'TAKE PROFIT': 'TAKE_PROFIT',
    TP: 'TAKE_PROFIT',
};

function normalizeOrderType(value) {
    const normalized = String(value || '')
        .trim()
        .toUpperCase()
        .replace(/\s+/g, ' ')
        .replace(/-/g, '_');
    return ORDER_TYPE_ALIAS_MAP[normalized] || 'MARKET';
}

function parseOptionalPrice(value) {
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function generateIdempotencyKey() {
    if (typeof window !== 'undefined' && window.crypto && window.crypto.randomUUID) {
        return window.crypto.randomUUID();
    }
    return Math.random().toString(36).substring(2) + Date.now().toString(36);
}

/**
 * Normalize symbol for comparison.
 * NSE stocks get .NS suffix; MCX commodities are left as-is (uppercase).
 */
function _norm(s) {
    if (!s || typeof s !== 'string') return '';
    if (s.startsWith('^') || s.endsWith('.NS') || s.endsWith('.BO')) return s;
    if (isMcxSymbol(s)) return s.toUpperCase();
    return `${s}.NS`;
}

/**
 * Encapsulates order form state and submission logic,
 * wiring into the existing /orders API endpoint.
 *
 * Trading modes (like real brokers — Zerodha, Groww, Angel One, Upstox):
 *   DELIVERY (CNC) → Sell only what you own. No short selling. No leverage.
 *   INTRADAY (MIS) → Short sell allowed. Auto square-off by 3:15 PM. 5× margin.
 *
 * @param {string} symbol - Pre-selected symbol
 * @returns {{
 *   form: object,
 *   setForm: Function,
 *   setSide: (side: 'BUY'|'SELL') => void,
 *   setTradingMode: (mode: 'DELIVERY'|'INTRADAY') => void,
 *   totalCost: number,
 *   isSubmitting: boolean,
 *   submitOrder: () => Promise<void>,
 *   resetForm: () => void,
 *   holdingQty: number,
 *   canSell: boolean,
 *   maxSellQty: number,
 *   isDelivery: boolean,
 *   isIntraday: boolean,
 *   marginRequired: number,
 *   marketOpen: boolean,
 * }}
 */
export function useOrders(symbol, currentPrice = 0) {
    const refreshPortfolio = usePortfolioStore((s) => s.refreshPortfolio);
    const holdings = usePortfolioStore((s) => s.holdings);
    const isSubmittingRef = useRef(false);

    const [form, setForm] = useState({
        side: ORDER_SIDE.BUY,
        order_type: ORDER_TYPE.MARKET,
        trading_mode: TRADING_MODE.INTRADAY,
        product_type: TRADING_MODE_PRODUCT[TRADING_MODE.INTRADAY], // MIS
        quantity: 1,
        price: '',
        triggerPrice: '',
        stopLoss: '',
        takeProfit: '',
    });
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [marketOpen, setMarketOpen] = useState(true);
    const [marketStateLabel, setMarketStateLabel] = useState('');

    // Check market session on mount and every 60s
    useEffect(() => {
        let mounted = true;
        const check = async () => {
            try {
                const res = await api.get('/market/session');
                if (!mounted) return;
                const s = res.data;
                setMarketOpen(!!s.can_place_orders);
                if (!s.can_place_orders) {
                    setMarketStateLabel(
                        s.state === 'weekend' ? 'Weekend'
                            : s.state === 'holiday' ? 'Holiday'
                                : s.state === 'after_market' ? 'After Market Hours'
                                    : 'Market Closed'
                    );
                }
            } catch { /* ignore */ }
        };
        check();
        const id = setInterval(check, 60_000);
        return () => { mounted = false; clearInterval(id); };
    }, []);

    // Check how many shares the user holds for the selected symbol.
    // Only positive (long) positions count as sellable holdings.
    // Negative qty = short position (not sellable in delivery mode).
    const holdingQty = useMemo(() => {
        const sym = _norm(symbol);
        const h = (holdings || []).find((h) => _norm(h.symbol) === sym);
        const qty = h ? Number(h.quantity ?? 0) : 0;
        return Math.max(0, qty); // Short positions (negative) → 0 holdings
    }, [holdings, symbol]);

    const currentSymbolHoldingQty = useMemo(() => {
        const sym = _norm(symbol);
        const h = (holdings || []).find((item) => _norm(item.symbol) === sym);
        return h ? Number(h.quantity ?? 0) : 0;
    }, [holdings, symbol]);

    const exitOrderSide = useMemo(() => {
        if (currentSymbolHoldingQty > 0) return ORDER_SIDE.SELL;
        if (currentSymbolHoldingQty < 0) return ORDER_SIDE.BUY;
        return null;
    }, [currentSymbolHoldingQty]);

    // Derived state
    const isDelivery = form.trading_mode === TRADING_MODE.DELIVERY;
    const isIntraday = form.trading_mode === TRADING_MODE.INTRADAY;
    const isBuy = form.side === ORDER_SIDE.BUY;
    const limitPriceValue = parseOptionalPrice(form.price);
    const isMarketableLimit = form.order_type === ORDER_TYPE.LIMIT && currentPrice > 0
        && limitPriceValue !== null
        && ((isBuy && limitPriceValue >= currentPrice) || (!isBuy && limitPriceValue <= currentPrice));

    // ── Sell rules (mirrors real broker behavior) ──────────────────────
    // DELIVERY (CNC): Can ONLY sell shares you already own. Max qty = holdingQty.
    // INTRADAY (MIS): Short selling allowed. Needs margin (capital / 5).
    const canSell = isDelivery ? holdingQty > 0 : true;
    const maxSellQty = isDelivery ? holdingQty : Infinity;

    // Margin required for intraday short sell (5× leverage like real brokers)
    const effectivePrice = form.order_type === 'LIMIT' || form.order_type === 'BRACKET'
        ? (form.price ? parseFloat(form.price) : currentPrice)
        : form.order_type === 'TAKE_PROFIT'
            ? (form.takeProfit ? parseFloat(form.takeProfit) : currentPrice)
            : form.order_type === 'STOP_LOSS'
                ? (form.stopLoss ? parseFloat(form.stopLoss) : currentPrice)
                : currentPrice;
    const totalCost = (effectivePrice || 0) * (parseInt(form.quantity, 10) || 0);
    const marginRequired = isIntraday ? totalCost / 5 : totalCost;

    const setSide = useCallback((side) => {
        setForm((f) => ({ ...f, side }));
    }, []);

    useEffect(() => {
        if (form.order_type !== 'STOP_LOSS' && form.order_type !== 'TAKE_PROFIT') {
            return;
        }
        if (!exitOrderSide || form.side === exitOrderSide) {
            return;
        }
        setForm((f) => ({ ...f, side: exitOrderSide }));
    }, [exitOrderSide, form.order_type, form.side]);

    /**
     * Switch trading mode — auto-sets the matching product type (like real brokers).
     * DELIVERY → CNC, INTRADAY → MIS
     */
    const setTradingMode = useCallback((mode) => {
        setForm((f) => {
            const product_type = TRADING_MODE_PRODUCT[mode] || 'CNC';
            const newForm = { ...f, trading_mode: mode, product_type };

            // If switching to DELIVERY + SELL, cap quantity to holdings
            if (mode === TRADING_MODE.DELIVERY && f.side === ORDER_SIDE.SELL) {
                const sym = _norm(symbol);
                const h = (usePortfolioStore.getState().holdings || []).find((h) => _norm(h.symbol) === sym);
                const held = h ? Number(h.quantity ?? 0) : 0;
                if (held > 0 && (parseInt(f.quantity, 10) || 0) > held) {
                    newForm.quantity = held;
                }
            }
            return newForm;
        });
    }, [symbol]);

    const resetForm = useCallback(() => {
        setForm({
            side: ORDER_SIDE.BUY,
            order_type: ORDER_TYPE.MARKET,
            trading_mode: TRADING_MODE.INTRADAY,
            product_type: TRADING_MODE_PRODUCT[TRADING_MODE.INTRADAY],
            quantity: 1,
            price: '',
            triggerPrice: '',
            stopLoss: '',
            takeProfit: '',
        });
    }, []);

    const submitOrder = useCallback(async () => {
        if (isSubmittingRef.current) return;
        const normalizedOrderType = normalizeOrderType(form.order_type);

        // Build effective price values (with currentPrice fallback) so validation
        // succeeds even when the quote arrived after the order type was switched.
        const isBuy = form.side === ORDER_SIDE.BUY;
        const priceFallback = currentPrice > 0 ? currentPrice : null;
        const effectiveLimitPrice = form.price || (priceFallback != null ? String(priceFallback) : '');
        const effectiveStopLoss = form.stopLoss || form.triggerPrice
            || (priceFallback != null ? String((priceFallback * (isBuy ? 0.99 : 1.01)).toFixed(2)) : '');
        const effectiveTakeProfit = form.takeProfit
            || (priceFallback != null ? String((priceFallback * (isBuy ? 1.02 : 0.98)).toFixed(2)) : '');

        const formForValidation = {
            ...form,
            order_type: normalizedOrderType,
            price: effectiveLimitPrice,
            stopLoss: effectiveStopLoss,
            takeProfit: effectiveTakeProfit,
        };

        const { valid, error } = validateOrderForm(formForValidation);
        if (!valid) { toast.error(error); return; }

        // NOTE: Stop-loss trigger direction validation is intentionally handled
        // server-side using fresh live market data. Doing it here with currentPrice
        // (a WebSocket prop that may be 1-2 ticks stale) causes false rejections.
        // The backend will return a descriptive error if the trigger is invalid.

        const qty = parseInt(form.quantity, 10);

        // ── Delivery sell validation (real broker rules) ───────────────
        // CNC: must hold shares, cannot sell more than you own
        if (form.side === ORDER_SIDE.SELL && form.trading_mode === TRADING_MODE.DELIVERY) {
            const sym = _norm(symbol);
            const h = (usePortfolioStore.getState().holdings || []).find((h) => _norm(h.symbol) === sym);
            const held = h ? Number(h.quantity ?? 0) : 0;
            if (held <= 0) {
                toast.error(
                    `You don't hold any ${symbol?.replace('.NS', '')} shares. ` +
                    `In Delivery mode, you can only sell stocks you own. ` +
                    `Switch to Intraday for short selling.`
                );
                return;
            }
            if (qty > held) {
                toast.error(
                    `You only hold ${held} shares of ${symbol?.replace('.NS', '')}. ` +
                    `Cannot sell ${qty} in Delivery mode.`
                );
                return;
            }
        }

        // ── Intraday short sell validation ─────────────────────────────
        // MIS: no holdings needed, but needs sufficient margin (capital / 5)
        if (form.side === ORDER_SIDE.SELL && form.trading_mode === TRADING_MODE.INTRADAY) {
            // Backend will verify margin, but show user-friendly warning
            const sym = _norm(symbol);
            const h = (usePortfolioStore.getState().holdings || []).find((h) => _norm(h.symbol) === sym);
            const held = h ? Number(h.quantity ?? 0) : 0;
            if (held <= 0) {
                // This is a short sell — just let user know (not an error)
                // Backend enforces margin check
            }
        }

        isSubmittingRef.current = true;
        setIsSubmitting(true);
        try {
            // Fall back to currentPrice when a price field is empty (e.g. quote
            // hadn't loaded yet when the order type was switched).
            const fallback = currentPrice > 0 ? currentPrice : null;
            const isBuyFallback = form.side === ORDER_SIDE.BUY;
            const limitPrice = parseOptionalPrice(form.price) ?? fallback;
            const stopLossPrice = parseOptionalPrice(form.stopLoss || form.triggerPrice)
                ?? (fallback != null ? fallback * (isBuyFallback ? 0.99 : 1.01) : null);
            const takeProfitPrice = parseOptionalPrice(form.takeProfit)
                ?? (fallback != null ? fallback * (isBuyFallback ? 1.02 : 0.98) : null);

            const payload = {
                symbol,
                side: form.side,
                order_type: normalizedOrderType,
                product_type: form.product_type,
                quantity: qty,
                price: (normalizedOrderType === 'LIMIT' || normalizedOrderType === 'BRACKET')
                    ? limitPrice
                    : normalizedOrderType === 'TAKE_PROFIT'
                        ? takeProfitPrice
                        : normalizedOrderType === 'STOP_LOSS_LIMIT'
                            ? limitPrice
                            : null,
                trigger_price: (normalizedOrderType === 'STOP_LOSS' || normalizedOrderType === 'BRACKET' || normalizedOrderType === 'STOP_LOSS_LIMIT')
                    ? stopLossPrice
                    : null,
                take_profit_price: (normalizedOrderType === 'BRACKET' || normalizedOrderType === 'TAKE_PROFIT')
                    ? takeProfitPrice
                    : null,
                client_price: currentPrice > 0 ? currentPrice : null,
                idempotency_key: generateIdempotencyKey(),
            };
            await api.post('/orders', payload);

            // Show appropriate success message
            const cleanSymbol = symbol?.replace('.NS', '') || symbol;
            if (form.side === ORDER_SIDE.SELL && form.trading_mode === TRADING_MODE.INTRADAY && holdingQty <= 0) {
                toast.success(`${normalizedOrderType} short sell order placed for ${cleanSymbol} (Intraday). Square off by 3:15 PM.`);
            } else if (normalizedOrderType === 'LIMIT' && isMarketableLimit) {
                toast.success(`Limit order filled immediately for ${cleanSymbol} at your limit price.`);
            } else {
                toast.success(`${normalizedOrderType} order placed for ${cleanSymbol} (${form.trading_mode === TRADING_MODE.DELIVERY ? 'Delivery' : 'Intraday'})`);
            }
            // Refresh in background so the order flow doesn't feel blocked.
            refreshPortfolio().catch(() => { });
        } catch (err) {
            toast.error(err.response?.data?.detail || 'Order failed. Please try again.');
        } finally {
            isSubmittingRef.current = false;
            setIsSubmitting(false);
        }
    }, [form, symbol, currentPrice, refreshPortfolio, holdingQty, isMarketableLimit]);

    return {
        form,
        setForm,
        setSide,
        setTradingMode,
        totalCost,
        isSubmitting,
        submitOrder,
        resetForm,
        holdingQty,
        canSell,
        maxSellQty,
        isDelivery,
        isIntraday,
        marginRequired,
        marketOpen,
        marketStateLabel,
    };
}
