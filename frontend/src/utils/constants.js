/** API base path (handled by Vite proxy / api.js baseURL) */
export const API_BASE = '/api';

/** LocalStorage keys */
export const LS_TOKEN = 'alphasync_token';
export const LS_USER = 'alphasync_user';
export const LS_THEME = 'alphasync_theme';
export const LS_SIDEBAR = 'alphasync_sidebar_collapsed';

/** WebSocket reconnect config */
export const WS_MAX_BACKOFF_MS = 30_000;
export const WS_HEARTBEAT_MS = 30_000;

/** Chart period → { period, interval } mapping (Zebu NorenOMS conventions)
 *  period:   how far back to fetch (days-based string for backend)
 *  interval: candle size passed to Zebu TPSeries / EODChartData
 */
export const CHART_PERIODS = {
    '1m': { period: '5d', interval: '1m', label: '1m', group: 'intraday' },
    '2m': { period: '5d', interval: '2m', label: '2m', group: 'intraday' },
    '3m': { period: '5d', interval: '3m', label: '3m', group: 'intraday' },
    '5m': { period: '5d', interval: '5m', label: '5m', group: 'intraday' },
    '15m': { period: '5d', interval: '15m', label: '15m', group: 'intraday' },
    '30m': { period: '5d', interval: '30m', label: '30m', group: 'intraday' },
    '1H': { period: '1mo', interval: '1h', label: '1H', group: 'intraday' },
    '4H': { period: '6mo', interval: '4h', label: '4H', group: 'intraday' },
    '1D': { period: '1y', interval: '1d', label: '1D', group: 'daily' },
    '1W': { period: '5y', interval: '1wk', label: '1W', group: 'daily' },
    '1M': { period: 'max', interval: '1mo', label: '1M', group: 'daily' },
    '3M': { period: '3mo', interval: '1d', label: '3M', group: 'extended' },
    '6M': { period: '6mo', interval: '1d', label: '6M', group: 'extended' },
    '1Y': { period: '1y', interval: '1d', label: '1Y', group: 'extended' },
    '3Y': { period: '3y', interval: '1d', label: '3Y', group: 'extended' },
    '5Y': { period: '5y', interval: '1d', label: '5Y', group: 'extended' },
    'MAX': { period: 'max', interval: '1d', label: 'MAX', group: 'extended' },
};

/** Default chart period key */
export const DEFAULT_CHART_PERIOD = '5m';

/** Order sides */
export const ORDER_SIDE = { BUY: 'BUY', SELL: 'SELL' };

/** Order types */
export const ORDER_TYPE = {
    MARKET: 'MARKET',
    LIMIT: 'LIMIT',
    BRACKET: 'BRACKET',
    TAKE_PROFIT: 'TAKE_PROFIT',
    SL: 'SL',
    SL_M: 'SL-M',
};

/** Product types */
export const PRODUCT_TYPE = {
    CNC: 'CNC',
    MIS: 'MIS',
    NRML: 'NRML',
};

/**
 * Trading modes — mirrors how real Indian stock brokers (Zerodha, Groww,
 * Angel One, Upstox) present trading choices to users.
 *
 * DELIVERY (CNC)  → Buy & hold in demat. Sell only what you own. No leverage.
 * INTRADAY (MIS)  → Buy or short-sell first. Must square off same day by 3:15 PM.
 *                    Leveraged margin (typically 5×).
 */
export const TRADING_MODE = {
    DELIVERY: 'DELIVERY',
    INTRADAY: 'INTRADAY',
};

/** Maps trading mode → default product type */
export const TRADING_MODE_PRODUCT = {
    DELIVERY: 'CNC',
    INTRADAY: 'MIS',
};

/** Human-readable labels for each trading mode */
export const TRADING_MODE_INFO = {
    DELIVERY: {
        label: 'Delivery',
        sublabel: 'CNC',
    },
    INTRADAY: {
        label: 'Intraday',
        sublabel: 'MIS',
    },
};

/** Order status badge map — uses design system tokens only, no hardcoded hex */
export const ORDER_STATUS_CLASS = {
    COMPLETE: 'bg-bull/10 text-bull border border-bull/20',
    FILLED: 'bg-bull/10 text-bull border border-bull/20',
    PENDING: 'bg-primary-500/10 text-primary-600 border border-primary-500/20',
    OPEN: 'bg-primary-500/10 text-primary-600 border border-primary-500/20',
    CANCELLED: 'bg-surface-800/60 text-gray-500 border border-edge/10',
    REJECTED: 'bg-bear/10 text-bear border border-bear/20',
};

/** Market session state labels */
export const MARKET_STATE_LABEL = {
    open: 'Market Open',
    pre_market: 'Pre-Market',
    closing: 'Closing',
    after_market: 'After Hours',
    weekend: 'Weekend',
    holiday: 'Holiday',
    closed: 'Market Closed',
};

/** Default watchlist symbols to seed a new account */
export const DEFAULT_WATCHLIST_SYMBOLS = [
    'RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS', 'INFY.NS', 'ICICIBANK.NS',
];

/** Sidebar widths */
export const SIDEBAR_EXPANDED_W = 240;
export const SIDEBAR_COLLAPSED_W = 72;

/** MCX commodity symbols — must NOT get .NS suffix */
export const MCX_SYMBOLS = new Set([
    'GOLD', 'GOLDM', 'GOLDGUINEA', 'GOLDPETAL',
    'SILVER', 'SILVERM', 'SILVERMIC',
    'COPPER', 'COPPERM',
    'CRUDEOIL', 'CRUDEOILM',
    'NATURALGAS', 'NATGASMINI',
    'ALUMINIUM', 'ALUMINI',
    'ZINC', 'ZINCMINI',
    'LEAD', 'LEADMINI',
    'NICKEL',
    'COTTONCNDY', 'KAPAS', 'MENTHOIL',
]);

export const DEFAULT_MCX_WATCHLIST = [
    'SILVERMIC', 'CRUDEOIL', 'NATURALGAS', 'GOLD', 'GOLDM',
    'SILVER', 'SILVERM', 'COPPER', 'COPPERM', 'ALUMINIUM',
    'ALUMINI', 'ZINC', 'ZINCMINI', 'LEAD', 'LEADMINI',
    'CRUDEOILM', 'NATGASMINI', 'GOLDGUINEA', 'GOLDPETAL',
    'COTTONCNDY', 'KAPAS', 'MENTHOIL',
];

/** NCDEX commodity symbols — must NOT get .NS suffix */
export const NCDEX_SYMBOLS = new Set([
    'COTTON', 'CASTORSEED', 'SOYBEAN', 'GUARSEED',
    'RMSEED', 'CHANA', 'MENTHOIL',
]);

/** Unified set of all commodity symbols (MCX + NCDEX) */
export const COMMODITY_SYMBOLS = new Set([...MCX_SYMBOLS, ...NCDEX_SYMBOLS]);

/** Check if a symbol is a known commodity */
export const isMcxSymbol = (s) => COMMODITY_SYMBOLS.has((s || '').toUpperCase());
export const isCommoditySymbol = isMcxSymbol;

/** NFO/BFO option & futures contract symbols (must not get .NS suffix). */
export const isDerivativeContractSymbol = (s) => {
    const u = String(s || '').trim().toUpperCase();
    if (!u || u.startsWith('^')) return false;
    return /\d/.test(u) && /(CE|PE|FUT|F)$/.test(u);
};

/**
 * Normalise a symbol to its canonical form.
 * NSE stocks get .NS suffix. MCX commodities and indices are left as-is.
 */
export const normalizeSymbol = (s) => {
    if (!s || typeof s !== 'string') return null;
    const raw = s.trim().toUpperCase();
    if (raw.startsWith('^') || raw.endsWith('.NS') || raw.endsWith('.BO')) return raw;
    if (isCommoditySymbol(raw)) return raw;
    if (isDerivativeContractSymbol(raw)) return raw;
    return `${raw}.NS`;
};
