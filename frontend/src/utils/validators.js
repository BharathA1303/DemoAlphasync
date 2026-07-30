/**
 * Validate an order form before submission.
 * @param {{ side: string, order_type: string, trading_mode: string, quantity: number|string, price: number|string, triggerPrice: number|string, stopLoss: number|string, takeProfit: number|string }} form
 * @returns {{ valid: boolean, error: string|null }}
 */
export const validateOrderForm = ({ side, order_type, trading_mode, quantity, price, triggerPrice, stopLoss, takeProfit }) => {
    const qty = parseInt(quantity, 10);
    if (!qty || qty <= 0) return { valid: false, error: 'Quantity must be a positive integer.' };

    if (order_type === 'LIMIT' || order_type === 'BRACKET') {
        // Only reject if user has actively entered an invalid non-empty value.
        // Empty string is allowed — backend falls back to live market price.
        const priceVal = parseFloat(price);
        if (price !== '' && price !== undefined && (isNaN(priceVal) || priceVal <= 0)) {
            return { valid: false, error: 'Price must be a valid positive number' };
        }
    }

    if (order_type === 'STOP_LOSS' || order_type === 'SL' || order_type === 'SL-M') {
        const triggerVal = parseFloat(stopLoss || triggerPrice);
        const triggerRaw = stopLoss || triggerPrice || '';
        if (triggerRaw !== '' && (isNaN(triggerVal) || triggerVal <= 0)) {
            return { valid: false, error: 'Stop loss price must be a valid positive number' };
        }
    }

    if (order_type === 'TAKE_PROFIT') {
        const tp = parseFloat(takeProfit);
        if (!tp || tp <= 0) return { valid: false, error: 'Take-profit price must be a positive number.' };
    }

    if (order_type === 'BRACKET') {
        const sl = parseFloat(stopLoss);
        const tp = parseFloat(takeProfit);
        if (stopLoss !== '' && stopLoss !== undefined && (isNaN(sl) || sl <= 0)) {
            return { valid: false, error: 'Stop loss price must be a valid positive number' };
        }
        if (takeProfit !== '' && takeProfit !== undefined && (isNaN(tp) || tp <= 0)) {
            return { valid: false, error: 'Take-profit price must be a valid positive number' };
        }
    }

    if (order_type === 'BRACKET' && price && stopLoss && takeProfit) {
        const p = parseFloat(price);
        const sl = parseFloat(stopLoss);
        const tp = parseFloat(takeProfit);
        if (side === 'BUY') {
            if (!(tp > p && p > sl)) {
                return { valid: false, error: `BUY bracket: Take Profit (₹${tp}) must be above entry (₹${p}), Stop Loss (₹${sl}) must be below.` };
            }
        } else if (side === 'SELL') {
            if (!(sl > p && p > tp)) {
                return { valid: false, error: `SELL bracket: Stop Loss (₹${sl}) must be above entry (₹${p}), Take Profit (₹${tp}) must be below.` };
            }
        }
    }

    // Trading mode must be set
    if (!trading_mode || !['DELIVERY', 'INTRADAY'].includes(trading_mode)) {
        return { valid: false, error: 'Please select a trading type (Delivery or Intraday).' };
    }

    return { valid: true, error: null };
};

/**
 * Validate an email address.
 * @param {string} email
 * @returns {boolean}
 */
export const isValidEmail = (email) =>
    /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);

/**
 * Check if a password meets minimum requirements (8+ chars, 1 number).
 * @param {string} password
 * @returns {{ valid: boolean, error: string|null }}
 */
export const validatePassword = (password) => {
    if (!password || password.length < 8) return { valid: false, error: 'Password must be at least 8 characters.' };
    if (!/\d/.test(password)) return { valid: false, error: 'Password must contain at least one number.' };
    return { valid: true, error: null };
};
