/**
 * Format a number as Indian Rupee currency string.
 * @param {number|null|undefined} value
 * @param {number} [decimals=2]
 * @returns {string}
 */
export const formatCurrency = (value, decimals = 2) => {
    if (value == null || isNaN(value)) return '—';
    return `₹${Number(value).toLocaleString('en-IN', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
    })}`;
};

/**
 * Format a number as compact Indian Rupee (e.g. ₹1.2Cr, ₹45L).
 * @param {number|null|undefined} value
 * @returns {string}
 */
export const formatCurrencyCompact = (value) => {
    if (value == null || isNaN(value)) return '—';
    const abs = Math.abs(value);
    const sign = value < 0 ? '-' : '';
    if (abs >= 1e7) return `${sign}₹${(abs / 1e7).toFixed(2)}Cr`;
    if (abs >= 1e5) return `${sign}₹${(abs / 1e5).toFixed(2)}L`;
    if (abs >= 1e3) return `${sign}₹${(abs / 1e3).toFixed(1)}K`;
    return `${sign}₹${abs.toFixed(2)}`;
};

/**
 * Format a quantity (integer, comma-separated).
 * @param {number|null|undefined} value
 * @returns {string}
 */
export const formatQuantity = (value) => {
    if (value == null || isNaN(value)) return '—';
    return Number(value).toLocaleString('en-IN');
};

/**
 * Format a percentage value with sign.
 * @param {number|null|undefined} value
 * @param {number} [decimals=2]
 * @param {boolean} [showSign=true]
 * @returns {string}
 */
export const formatPercent = (value, decimals = 2, showSign = true) => {
    if (value == null || isNaN(value)) return '—';
    const sign = showSign && value > 0 ? '+' : '';
    return `${sign}${Number(value).toFixed(decimals)}%`;
};

/**
 * Format a price with fixed decimal places (no rupee symbol).
 * @param {number|null|undefined} value
 * @param {number} [decimals=2]
 * @returns {string}
 */
export const formatPrice = (value, decimals = 2) => {
    if (value == null || isNaN(value)) return '—';
    return Number(value).toFixed(decimals);
};

/**
 * Returns Tailwind color class based on P&L sign.
 * @param {number} value
 * @returns {string}
 */
export const pnlColorClass = (value) =>
    value >= 0 ? 'text-profit' : 'text-loss';

/**
 * Returns bull/bear color class for trading semantics.
 * @param {number} value
 * @returns {string}
 */
export const bullBearClass = (value) =>
    value >= 0 ? 'text-bull' : 'text-bear';

/**
 * Format a Date or timestamp to a readable date string (DD MMM YYYY).
 * @param {Date|string|number} value
 * @returns {string}
 */
export const formatDate = (value) => {
    const d = new Date(value);
    if (isNaN(d)) return '—';
    return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
};

/**
 * Format a Date to HH:MM:SS.
 * @param {Date|string|number} value
 * @returns {string}
 */
export const formatTime = (value) => {
    const d = new Date(value);
    if (isNaN(d)) return '—';
    return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
};

/**
 * Clean a trading symbol for display — strips exchange suffixes and index prefix.
 * "RELIANCE.NS" → "RELIANCE", "^NSEI" → "NSEI", "^CNXIT.NS" → "CNXIT"
 * @param {string|null|undefined} symbol
 * @returns {string}
 */
export const cleanSymbol = (symbol) => {
    if (!symbol) return '';
    return symbol.replace('.NS', '').replace('.BO', '').replace('=F', '').replace(/^\^/, '');
};
